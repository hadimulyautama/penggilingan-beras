"""Lapisan layanan modul Timbangan: penyimpanan, query, agregasi.

Semua rumus bisnis dipanggil dari `app.timbangan.logic` — modul ini hanya
mengurus DB, aturan kunci/koreksi, pemeriksaan, dan audit.

Dua hal yang membentuk seluruh rancangan modul ini:

  · **Nomor transaksi dibentuk di perangkat.** Server tidak pernah menomori.
    Penyimpanan bersifat idempoten terhadap `kode`, jadi kiriman ulang dari
    antrean offline tidak pernah menghasilkan transaksi kembar.
  · **Aturan komoditas dibaca dari DB lalu disalin ke transaksi.** Merevisi
    ambang tidak pernah menggeser status transaksi yang sudah tersimpan.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Supplier
from app.timbangan import logic, setelan
from app.timbangan.config import tsettings
from app.timbangan.db import berzona, sekarang
from app.timbangan.models import (
    CARA_DUA_KALI,
    CARA_SEKALI,
    PEMERIKSAAN_DIBUKA,
    PEMERIKSAAN_SELESAI,
    ROLE_ADMIN,
    ROLE_SUPERADMIN,
    ROLES,
    TIKET_DITUTUP_PAKSA,
    TIKET_SELESAI,
    TIKET_TERBUKA,
    TRX_AKTIF,
    TRX_VOID,
    TimbanganAkun,
    TimbanganAudit,
    TimbanganCetak,
    TimbanganFoto,
    TimbanganJenis,
    TimbanganKendaraan,
    TimbanganMuatan,
    TimbanganPemeriksaan,
    TimbanganSkorSupplier,
    TimbanganSupplierProfil,
    TimbanganTaraStandar,
    TimbanganTransaksi,
)


class LayananError(Exception):
    """Kesalahan aturan bisnis yang layak ditampilkan ke pengguna."""


# ═══════════════════════════ Audit ═══════════════════════════

async def catat_audit(
    db: AsyncSession,
    *,
    akun: TimbanganAkun | None,
    aksi: str,
    entitas: str | None = None,
    entitas_id: str | int | None = None,
    ringkasan: str | None = None,
    sebelum: dict | None = None,
    sesudah: dict | None = None,
    perangkat: str | None = None,
    ip: str | None = None,
) -> None:
    """Tulis satu baris audit. Hanya bertambah — tidak pernah menimpa."""
    db.add(TimbanganAudit(
        akun_id=akun.id if akun else None,
        akun_nama=akun.nama if akun else None,
        aksi=aksi,
        entitas=entitas,
        entitas_id=str(entitas_id) if entitas_id is not None else None,
        ringkasan=ringkasan,
        nilai_sebelum=json.dumps(sebelum, ensure_ascii=False) if sebelum else None,
        nilai_sesudah=json.dumps(sesudah, ensure_ascii=False) if sesudah else None,
        perangkat_kode=perangkat,
        ip=ip,
    ))


# ═══════════════════════════ Aturan komoditas ═══════════════════════════

def _aturan_dari_baris(baris: TimbanganJenis) -> logic.AturanJenis:
    return logic.AturanJenis(
        kode=baris.kode,
        nama=baris.nama,
        arah=baris.arah,
        acuan=baris.acuan,
        sumber_tara=baris.sumber_tara,
        tara_tetap_kg=float(baris.tara_tetap_kg or 0),
        tara_bawaan_kg=float(baris.tara_bawaan_kg or 0),
        ambang_jenis=baris.ambang_jenis,
        ambang_nilai=float(baris.ambang_nilai or 0),
        ambang_arah=baris.ambang_arah,
        ambang_investigasi_nilai=(
            float(baris.ambang_investigasi_nilai)
            if baris.ambang_investigasi_nilai is not None else None
        ),
        rahasia=bool(baris.rahasia),
        cetak_bukti=bool(baris.cetak_bukti),
        masa_berlaku_tara_hari=int(baris.masa_berlaku_tara_hari or 90),
    )


async def daftar_jenis(
    db: AsyncSession, *, arah: str | None = None, hanya_aktif: bool = True
) -> list[TimbanganJenis]:
    q = select(TimbanganJenis).order_by(TimbanganJenis.urutan, TimbanganJenis.nama)
    if hanya_aktif:
        q = q.where(TimbanganJenis.status == "aktif")
    if arah:
        q = q.where(TimbanganJenis.arah.in_([arah, logic.BEBAS]))
    return list((await db.execute(q)).scalars())


async def peta_aturan(db: AsyncSession) -> dict[str, logic.AturanJenis]:
    """Aturan seluruh komoditas, dibaca dari DB.

    Bila tabel masih kosong (mis. di lingkungan uji), pakai aturan awal dari
    `logic` supaya modul tetap bisa berjalan tanpa penyemaian lebih dulu.
    """
    baris = list((await db.execute(select(TimbanganJenis))).scalars())
    if not baris:
        return dict(logic.JENIS_PETA)
    return {b.kode: _aturan_dari_baris(b) for b in baris}


async def aturan_untuk(db: AsyncSession, kode: str) -> logic.AturanJenis:
    peta = await peta_aturan(db)
    if kode not in peta:
        raise LayananError(f"Komoditas '{kode}' tidak dikenal.")
    return peta[kode]


# ═══════════════════════════ Penyemaian ═══════════════════════════

async def pastikan_jenis(db: AsyncSession) -> int:
    """Isi master komoditas dari `logic.JENIS_AWAL` bila belum ada.

    Hanya MENAMBAH yang belum ada — aturan yang sudah disetel manajemen di DB
    tidak pernah ditimpa oleh nilai bawaan kode.
    """
    ada = set((await db.execute(select(TimbanganJenis.kode))).scalars())
    ditambah = 0
    for urut, a in enumerate(logic.JENIS_AWAL, start=1):
        if a.kode in ada:
            continue
        db.add(TimbanganJenis(
            kode=a.kode, nama=a.nama, urutan=urut * 10,
            arah=a.arah, acuan=a.acuan, sumber_tara=a.sumber_tara,
            tara_tetap_kg=a.tara_tetap_kg, tara_bawaan_kg=a.tara_bawaan_kg,
            ambang_jenis=a.ambang_jenis, ambang_nilai=a.ambang_nilai,
            ambang_arah=a.ambang_arah,
            ambang_investigasi_nilai=a.ambang_investigasi_nilai,
            rahasia=a.rahasia, cetak_bukti=a.cetak_bukti,
            masa_berlaku_tara_hari=a.masa_berlaku_tara_hari,
        ))
        ditambah += 1
    if ditambah:
        await db.commit()
    return ditambah


async def pastikan_admin(db: AsyncSession) -> bool:
    """Buat akun admin awal bila tabel akun masih kosong.

    Tanpa `TIMBANGAN_ADMIN_PASSWORD` di environment, tidak ada akun yang dibuat
    — lebih baik aplikasi tidak bisa dimasuki daripada punya sandi tebakan.
    """
    from app.timbangan.security import hash_sandi

    if (await db.execute(select(func.count(TimbanganAkun.id)))).scalar_one():
        return False
    if not tsettings.admin_password:
        return False
    db.add(TimbanganAkun(
        username=tsettings.admin_username,
        nama=tsettings.admin_nama,
        role=ROLE_ADMIN,
        password_hash=hash_sandi(tsettings.admin_password),
    ))
    await db.commit()
    return True


# ═══════════════════════════ Utilitas ═══════════════════════════

def normalisasi_nopol(nopol: str | None) -> str | None:
    """'  ad 1234 xy ' → 'AD 1234 XY'."""
    if not nopol:
        return None
    bersih = re.sub(r"\s+", " ", str(nopol).strip().upper())
    return bersih or None


async def kendaraan_dari_nopol(
    db: AsyncSession, nopol: str | None
) -> TimbanganKendaraan | None:
    """Cari armada; daftarkan bila belum ada. Master tumbuh sendiri dari pakai."""
    bersih = normalisasi_nopol(nopol)
    if not bersih:
        return None
    kendaraan = (await db.execute(
        select(TimbanganKendaraan).where(TimbanganKendaraan.nomor_polisi == bersih)
    )).scalars().first()
    if kendaraan is None:
        kendaraan = TimbanganKendaraan(nomor_polisi=bersih)
        db.add(kendaraan)
        await db.flush()
    return kendaraan


async def profil_supplier(
    db: AsyncSession, supplier_id: int, *, buat: bool = True
) -> TimbanganSupplierProfil | None:
    profil = (await db.execute(
        select(TimbanganSupplierProfil).where(
            TimbanganSupplierProfil.supplier_id == supplier_id
        )
    )).scalars().first()
    if profil is None and buat:
        profil = TimbanganSupplierProfil(supplier_id=supplier_id)
        db.add(profil)
        await db.flush()
    return profil


async def supplier_pilihan(
    db: AsyncSession, *, hari: int = 120
) -> tuple[list[Supplier], list[Supplier]]:
    """Supplier dipecah dua: yang benar-benar dipakai belakangan, dan sisanya.

    Daftar dari Kledo memuat seluruh vendor — termasuk pemasok karung dan
    sablon yang tidak pernah lewat jembatan timbang. Petugas hanya berurusan
    dengan belasan nama; menyuruhnya menggulir ratusan nama di ponsel, sambil
    truk menunggu, adalah cara membuat orang salah pilih.
    """
    batas = sekarang().date() - timedelta(days=hari)
    terpakai = set((await db.execute(
        select(TimbanganTransaksi.supplier_id)
        .where(
            TimbanganTransaksi.supplier_id.is_not(None),
            TimbanganTransaksi.tanggal >= batas,
            TimbanganTransaksi.status_transaksi == TRX_AKTIF,
        )
        .distinct()
    )).scalars())

    semua = await daftar_supplier(db)
    sering = [s for s in semua if s.id in terpakai]
    lainnya = [s for s in semua if s.id not in terpakai]
    return sering, lainnya


async def daftar_supplier(
    db: AsyncSession, *, hanya_aktif: bool = True
) -> list[Supplier]:
    q = select(Supplier).order_by(Supplier.nama_supplier)
    if hanya_aktif and hasattr(Supplier, "is_active"):
        q = q.where(Supplier.is_active.is_(True))
    return list((await db.execute(q)).scalars())


# ═══════════════════════════ Tara standar ═══════════════════════════

async def tara_berlaku(
    db: AsyncSession, *, supplier_id: int | None, jenis_kode: str
) -> TimbanganTaraStandar | None:
    """Sampling tara yang masih berlaku untuk pihak × komoditas ini.

    Sampling khusus pihak menang atas sampling umum (`supplier_id` kosong).
    """
    hari = sekarang().date()
    q = (
        select(TimbanganTaraStandar)
        .where(
            TimbanganTaraStandar.jenis_kode == jenis_kode,
            TimbanganTaraStandar.status == "BERLAKU",
            TimbanganTaraStandar.berlaku_mulai <= hari,
            or_(
                TimbanganTaraStandar.berlaku_sampai.is_(None),
                TimbanganTaraStandar.berlaku_sampai >= hari,
            ),
            or_(
                TimbanganTaraStandar.supplier_id == supplier_id,
                TimbanganTaraStandar.supplier_id.is_(None),
            ),
        )
        .order_by(
            TimbanganTaraStandar.supplier_id.is_(None),   # khusus dulu
            TimbanganTaraStandar.berlaku_mulai.desc(),
        )
    )
    return (await db.execute(q)).scalars().first()


async def tara_disarankan(
    db: AsyncSession, *, supplier_id: int | None, aturan: logic.AturanJenis
) -> tuple[float, TimbanganTaraStandar | None]:
    """Tara per karung yang diusulkan ke layar, beserta asalnya."""
    if aturan.sumber_tara == logic.TARA_SAMPLING:
        baris = await tara_berlaku(
            db, supplier_id=supplier_id, jenis_kode=aturan.kode
        )
        if baris is not None:
            return float(baris.tara_per_karung_kg), baris
    return aturan.tara_default(), None


async def simpan_tara_standar(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    supplier_id: int | None,
    jenis_kode: str,
    jumlah_sampel: int,
    total_berat_kg: float,
    jenis_karung: str | None = None,
    alasan: str | None = None,
) -> TimbanganTaraStandar:
    """Catat sampling baru. Yang lama DIGANTI, tidak pernah ditimpa."""
    if jumlah_sampel <= 0:
        raise LayananError("Jumlah karung sampel harus lebih dari 0.")
    if total_berat_kg <= 0:
        raise LayananError("Total berat sampel harus lebih dari 0.")

    aturan = await aturan_untuk(db, jenis_kode)
    hari = sekarang().date()

    lama = await tara_berlaku(db, supplier_id=supplier_id, jenis_kode=jenis_kode)
    if lama is not None and lama.supplier_id == supplier_id:
        lama.status = "DIGANTI"
        lama.berlaku_sampai = hari

    baris = TimbanganTaraStandar(
        supplier_id=supplier_id,
        jenis_kode=jenis_kode,
        jumlah_sampel=jumlah_sampel,
        total_berat_kg=total_berat_kg,
        tara_per_karung_kg=round(total_berat_kg / jumlah_sampel, 4),
        jenis_karung=jenis_karung,
        berlaku_mulai=hari,
        berlaku_sampai=hari + timedelta(days=aturan.masa_berlaku_tara_hari),
        alasan=alasan,
        dibuat_oleh_id=akun.id,
    )
    db.add(baris)
    await db.flush()
    await catat_audit(
        db, akun=akun, aksi="TARA_STANDAR", entitas="tara_standar",
        entitas_id=baris.id,
        ringkasan=(
            f"{jenis_kode}: {jumlah_sampel} karung / {total_berat_kg} kg "
            f"= {baris.tara_per_karung_kg} kg per karung"
        ),
        sesudah={"tara_per_karung_kg": float(baris.tara_per_karung_kg)},
    )
    return baris


async def tara_jatuh_tempo(db: AsyncSession, *, dalam_hari: int = 14) -> list:
    """Sampling tara yang akan atau sudah kedaluwarsa — bahan radar."""
    batas = sekarang().date() + timedelta(days=dalam_hari)
    q = (
        select(TimbanganTaraStandar, Supplier.nama_supplier)
        .outerjoin(Supplier, Supplier.id == TimbanganTaraStandar.supplier_id)
        .where(
            TimbanganTaraStandar.status == "BERLAKU",
            TimbanganTaraStandar.berlaku_sampai.is_not(None),
            TimbanganTaraStandar.berlaku_sampai <= batas,
        )
        .order_by(TimbanganTaraStandar.berlaku_sampai)
    )
    return list((await db.execute(q)).all())


# ═══════════════════════════ Aturan kunci & koreksi ═══════════════════════

def terkunci_untuk_petugas(
    trx: TimbanganTransaksi, jam_kunci: float | None = None
) -> bool:
    """Transaksi selesai mengunci sendiri setelah beberapa jam."""
    if trx.terkunci:
        return True
    if not trx.selesai:
        return False
    acuan = berzona(trx.timbang2_waktu_sistem or trx.created_at)
    if acuan is None:
        return False
    if jam_kunci is None:
        jam_kunci = tsettings.jam_kunci_otomatis
    return sekarang() - acuan > timedelta(hours=jam_kunci)


def boleh_mengubah(
    trx: TimbanganTransaksi, akun: TimbanganAkun, jam_kunci: float | None = None
) -> tuple[bool, str]:
    """Input yang salah boleh dikoreksi — dengan jejak, bukan diam-diam."""
    if trx.status_transaksi == TRX_VOID:
        return False, "Transaksi sudah dibatalkan."
    if akun.is_admin:
        return True, ""
    if terkunci_untuk_petugas(trx, jam_kunci):
        jam = jam_kunci if jam_kunci is not None else tsettings.jam_kunci_otomatis
        return False, (
            f"Transaksi terkunci setelah {jam:g} jam. "
            "Minta Admin untuk mengoreksi."
        )
    return True, ""


def boleh_membatalkan(akun: TimbanganAkun) -> bool:
    return akun.is_admin


# ═══════════════════════════ Simpan transaksi ═══════════════════════════

@dataclass
class InputMuatan:
    jenis_kode: str
    jumlah_karung: int = 0
    tara_per_karung_kg: float = 0.0
    berat_acuan_kg: float = 0.0
    nomor_acuan: str | None = None
    tara_standar_id: int | None = None
    catatan: str | None = None


@dataclass
class InputTimbang:
    """Satu kiriman dari perangkat.

    `kode` dibentuk di perangkat — server tidak menomori. Kiriman ulang dengan
    kode yang sama memperbarui baris yang sama, bukan membuat baris baru.
    """
    kode: str
    arah: str
    jenis_kode: str
    berat_kg: float
    waktu_operator: datetime | None = None
    cara_timbang: str = CARA_DUA_KALI
    supplier_id: int | None = None
    pihak_nama: str | None = None
    nomor_polisi: str | None = None
    nama_sopir: str | None = None
    tara_lain_kg: float = 0.0
    muatan: list[InputMuatan] = field(default_factory=list)
    catatan: str | None = None
    perangkat_kode: str | None = None
    dibuat_offline: bool = False


def _baris_logic(muatan: list[TimbanganMuatan]) -> list[logic.BarisMuatan]:
    return [
        logic.BarisMuatan(
            jenis_kode=m.jenis_kode,
            jumlah_karung=int(m.jumlah_karung or 0),
            tara_per_karung_kg=float(m.tara_per_karung_kg or 0),
            berat_acuan_kg=float(m.berat_acuan_kg or 0),
            nomor_acuan=m.nomor_acuan,
        )
        for m in muatan
    ]


def _bermuatan_dan_kosong(
    arah: str, t1: float | None, t2: float | None
) -> tuple[float | None, float | None]:
    """Mana dari kedua angka yang bermuatan, menurut arah barang.

    Masuk: truk datang penuh, pulang kosong. Keluar: kebalikannya.
    """
    if arah == logic.KELUAR:
        return t2, t1
    return t1, t2


def _terapkan_hasil(trx: TimbanganTransaksi, hasil: logic.Hasil) -> None:
    trx.netto_timbangan_kg = hasil.netto_timbangan_kg
    trx.jumlah_karung = hasil.jumlah_karung
    trx.total_tara_kg = hasil.total_tara_kg
    trx.berat_barang_kg = hasil.berat_barang_kg
    trx.berat_acuan_kg = hasil.berat_acuan_kg
    trx.selisih_kg = hasil.selisih_kg
    trx.selisih_persen = hasil.selisih_persen
    trx.batas_bawah_kg = hasil.batas_bawah_kg
    trx.batas_atas_kg = hasil.batas_atas_kg
    trx.status_kontrol = hasil.status
    trx.keterangan = hasil.keterangan


def _kosongkan_hasil(trx: TimbanganTransaksi) -> None:
    trx.netto_timbangan_kg = None
    trx.berat_barang_kg = None
    trx.selisih_kg = 0
    trx.selisih_persen = 0
    trx.batas_bawah_kg = None
    trx.batas_atas_kg = None
    trx.status_kontrol = None
    trx.keterangan = None


async def _pasang_muatan(
    db: AsyncSession, trx: TimbanganTransaksi, muatan: list[InputMuatan]
) -> None:
    """Ganti seluruh baris muatan. Bentuk data sama untuk masuk & keluar."""
    # Koleksi dimuat lebih dulu: di SQLAlchemy async, menyentuh relasi yang
    # belum termuat memicu I/O di tempat yang tidak mengizinkannya.
    await db.refresh(trx, ["muatan"])
    baris_baru = []
    for urut, m in enumerate(muatan, start=1):
        baris_baru.append(TimbanganMuatan(
            urutan=urut,
            jenis_kode=m.jenis_kode,
            nomor_acuan=(m.nomor_acuan or None),
            jumlah_karung=int(m.jumlah_karung or 0),
            tara_per_karung_kg=float(m.tara_per_karung_kg or 0),
            berat_acuan_kg=float(m.berat_acuan_kg or 0),
            tara_standar_id=m.tara_standar_id,
            catatan=m.catatan,
        ))
    # Penggantian di tempat: baris lama terhapus lewat cascade delete-orphan.
    trx.muatan[:] = baris_baru
    await db.flush()


async def kode_baru(db: AsyncSession, akun: TimbanganAkun) -> str:
    """Bentuk nomor transaksi: TRX-<tanggal>-<perangkat>-<urutan>.

    Perangkat ikut masuk ke nomor supaya dua pos yang sedang tanpa jaringan
    tidak bisa membuat nomor yang sama. Urutannya dihitung per perangkat per
    hari — bukan berurut global — justru agar tidak butuh server untuk menomori.
    """
    perangkat = (akun.perangkat_kode or "P0")[:8].upper()
    hari = sekarang().date()
    awalan = f"TRX-{hari:%Y%m%d}-{perangkat}-"

    terpakai = set((await db.execute(
        select(TimbanganTransaksi.kode).where(
            TimbanganTransaksi.kode.like(awalan + "%")
        )
    )).scalars())

    urut = len(terpakai) + 1
    while f"{awalan}{urut:03d}" in terpakai:
        urut += 1
    return f"{awalan}{urut:03d}"


async def ambil_kode(db: AsyncSession, kode: str) -> TimbanganTransaksi | None:
    return (await db.execute(
        select(TimbanganTransaksi).where(TimbanganTransaksi.kode == kode)
    )).scalars().first()


async def simpan_timbang_pertama(
    db: AsyncSession, *, akun: TimbanganAkun, data: InputTimbang, ip: str | None = None
) -> TimbanganTransaksi:
    """Timbang pertama → tiket terbuka (atau langsung selesai bila SEKALI).

    Idempoten terhadap `kode`: mengirim ulang kiriman yang sama dari antrean
    offline memperbarui baris yang sama.
    """
    if data.berat_kg <= 0:
        raise LayananError("Berat timbang harus lebih dari 0 kg.")

    aturan = await aturan_untuk(db, data.jenis_kode)
    kapasitas = (await setelan.semua(db))["kapasitas_jembatan_kg"]
    # Diperiksa SEKARANG, bukan nanti di timbang kedua. Salah ketik yang baru
    # ketahuan setelah truk selesai bongkar sudah terlambat untuk diperbaiki.
    if data.berat_kg > kapasitas:
        raise LayananError(
            f"Melebihi kapasitas jembatan timbang ({kapasitas:.0f} kg) — "
            "angka ini tidak mungkin."
        )
    waktu = sekarang()
    kendaraan = await kendaraan_dari_nopol(db, data.nomor_polisi)

    trx = await ambil_kode(db, data.kode)
    baru = trx is None
    if trx is None:
        trx = TimbanganTransaksi(kode=data.kode)
        db.add(trx)
    elif trx.status_transaksi == TRX_VOID:
        raise LayananError("Transaksi ini sudah dibatalkan.")
    elif trx.selesai:
        # Kiriman ulang atas transaksi yang sudah tuntas — abaikan, jangan
        # mundurkan statusnya.
        return trx

    trx.arah = data.arah
    trx.jenis_kode = data.jenis_kode
    trx.cara_timbang = data.cara_timbang
    trx.aturan_snapshot = json.dumps(
        aturan.__dict__, ensure_ascii=False, default=str
    )
    trx.supplier_id = data.supplier_id
    trx.pihak_nama = data.pihak_nama
    trx.kendaraan_id = kendaraan.id if kendaraan else None
    trx.nomor_polisi = normalisasi_nopol(data.nomor_polisi)
    trx.nama_sopir = data.nama_sopir
    trx.tara_lain_kg = float(data.tara_lain_kg or 0)
    trx.catatan = data.catatan
    trx.perangkat_kode = data.perangkat_kode or akun.perangkat_kode
    trx.dibuat_offline = bool(data.dibuat_offline)
    trx.dikirim_pada = waktu

    trx.timbang1_kg = float(data.berat_kg)
    trx.timbang1_waktu = data.waktu_operator or waktu
    trx.timbang1_waktu_sistem = waktu
    trx.timbang1_petugas_id = akun.id
    trx.dibuat_oleh_id = trx.dibuat_oleh_id or akun.id
    trx.tanggal = (trx.timbang1_waktu or waktu).date()

    await db.flush()
    await _pasang_muatan(db, trx, data.muatan)

    if data.cara_timbang == CARA_SEKALI:
        # Jasa timbang sekali: tidak ada pembanding, tidak ada kontrol.
        trx.berat_bermuatan_kg = trx.timbang1_kg
        trx.berat_kosong_kg = None
        _terapkan_hasil(trx, logic.hitung(
            aturan=aturan,
            berat_bermuatan_kg=trx.timbang1_kg,
            berat_kosong_kg=None,
            muatan=_baris_logic(trx.muatan),
            tara_lain_kg=trx.tara_lain_kg,
            kapasitas_kg=kapasitas,
        ))
        trx.status_tiket = TIKET_SELESAI
        trx.timbang2_petugas_id = akun.id
    else:
        trx.status_tiket = TIKET_TERBUKA
        _kosongkan_hasil(trx)

    await catat_audit(
        db, akun=akun, aksi="SIMPAN_TIMBANG_1" if baru else "KIRIM_ULANG_TIMBANG_1",
        entitas="transaksi", entitas_id=trx.kode,
        ringkasan=f"{trx.arah} {trx.jenis_kode} {trx.nomor_polisi or ''} "
                  f"{trx.timbang1_kg:.0f} kg".strip(),
        sesudah={"timbang1_kg": float(trx.timbang1_kg)},
        perangkat=trx.perangkat_kode, ip=ip,
    )
    await db.commit()
    await db.refresh(trx)
    return trx


async def simpan_timbang_kedua(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    kode: str,
    berat_kg: float,
    waktu_operator: datetime | None = None,
    muatan: list[InputMuatan] | None = None,
    tara_lain_kg: float | None = None,
    catatan: str | None = None,
    selesaikan: bool = True,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Timbang kedua → hitung, beri status, tutup tiket.

    Tanggal transaksi mengikuti timbang KEDUA: truk yang masuk menjelang
    tengah malam dan keluar setelahnya tercatat di hari ia selesai.

    **`selesaikan=False` menyimpan tanpa menutup tiket.** Angka timbang kedua
    sudah masuk dan aman dari HP mati atau shift berganti, tetapi tiketnya
    tetap terbuka karena penimbangannya memang belum selesai — biasanya
    jumlah karung baru diketahui setelah bongkar rampung. Yang ditunda bukan
    penyimpanannya, melainkan perhitungannya: selisih tidak dihitung, status
    kontrol tidak diberikan, dan lembar pemeriksaan tidak dibuka. Menghitung
    selisih tanpa jumlah karung akan memberi angka yang salah sekaligus
    meyakinkan — tara total nol membuat barang tampak berlebih.

    **Barang masuk tidak bisa diselesaikan tanpa jumlah karung.** Seluruh
    komoditas masuk bertara per karung, jadi tanpa angka itu berat barang dan
    selisihnya keliru — dan statusnya tersimpan permanen serta terbawa ke
    ekspor.
    """
    trx = await ambil_kode(db, kode)
    if trx is None:
        raise LayananError(f"Transaksi {kode} tidak ditemukan.")
    if trx.status_transaksi == TRX_VOID:
        raise LayananError("Transaksi ini sudah dibatalkan.")
    if trx.status_tiket == TIKET_DITUTUP_PAKSA:
        raise LayananError("Tiket ini sudah ditutup paksa.")
    if trx.status_tiket == TIKET_SELESAI:
        return trx                      # kiriman ulang — sudah tuntas
    if berat_kg <= 0:
        raise LayananError("Berat timbang harus lebih dari 0 kg.")

    aturan = await aturan_untuk(db, trx.jenis_kode)
    waktu = sekarang()

    trx.timbang2_kg = float(berat_kg)
    trx.timbang2_waktu = waktu_operator or waktu
    trx.timbang2_waktu_sistem = waktu
    trx.timbang2_petugas_id = akun.id
    trx.diubah_oleh_id = akun.id
    trx.dikirim_pada = waktu
    trx.tanggal = (trx.timbang2_waktu or waktu).date()
    if catatan is not None:
        trx.catatan = catatan
    if tara_lain_kg is not None:
        trx.tara_lain_kg = float(tara_lain_kg)
    if muatan is not None:
        await _pasang_muatan(db, trx, muatan)

    if not selesaikan:
        await catat_audit(
            db, akun=akun, aksi="SIMPAN_SEMENTARA", entitas="transaksi",
            entitas_id=trx.kode,
            ringkasan=f"{trx.timbang2_kg:.0f} kg disimpan, tiket tetap terbuka",
            sesudah={"timbang2_kg": float(trx.timbang2_kg)},
            perangkat=trx.perangkat_kode, ip=ip,
        )
        await db.commit()
        await db.refresh(trx)
        return trx

    if trx.arah == logic.MASUK and not sum(
        int(m.jumlah_karung or 0) for m in trx.muatan
    ):
        raise LayananError(
            "Jumlah karung belum diisi. Barang masuk tidak bisa diselesaikan "
            "tanpa angka itu — taranya dihitung per karung, jadi selisihnya "
            "akan keliru. Pakai Simpan sementara sampai bongkar rampung."
        )

    bermuatan, kosong = _bermuatan_dan_kosong(
        trx.arah, float(trx.timbang1_kg), float(trx.timbang2_kg)
    )
    trx.berat_bermuatan_kg = bermuatan
    trx.berat_kosong_kg = kosong

    _terapkan_hasil(trx, logic.hitung(
        aturan=aturan,
        berat_bermuatan_kg=bermuatan,
        berat_kosong_kg=kosong,
        muatan=_baris_logic(trx.muatan),
        tara_lain_kg=float(trx.tara_lain_kg or 0),
        kapasitas_kg=(await setelan.semua(db))["kapasitas_jembatan_kg"],
    ))
    trx.status_tiket = TIKET_SELESAI

    await catat_audit(
        db, akun=akun, aksi="SIMPAN_TIMBANG_2", entitas="transaksi",
        entitas_id=trx.kode,
        ringkasan=f"{trx.timbang2_kg:.0f} kg → selisih {trx.selisih_kg:+.0f} kg "
                  f"({trx.status_kontrol})",
        sesudah={
            "timbang2_kg": float(trx.timbang2_kg),
            "selisih_kg": float(trx.selisih_kg),
            "status_kontrol": trx.status_kontrol,
        },
        perangkat=trx.perangkat_kode, ip=ip,
    )

    if trx.status_kontrol in logic.STATUS_WAJIB_PERIKSA:
        await buka_pemeriksaan(db, akun=akun, trx=trx)

    await db.commit()
    await db.refresh(trx)
    return trx


async def koreksi_transaksi(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    perubahan: dict,
    muatan: list[InputMuatan] | None = None,
    alasan: str | None = None,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Koreksi input yang salah — dengan jejak sebelum & sesudah.

    Angka lama tidak hilang: ia tertulis di `timbangan_audit`.
    """
    nilai = await setelan.semua(db)
    boleh, sebab = boleh_mengubah(trx, akun, nilai["jam_kunci_otomatis"])
    if not boleh:
        raise LayananError(sebab)

    dapat_diubah = {
        "supplier_id", "pihak_nama", "nomor_polisi", "nama_sopir",
        "timbang1_kg", "timbang2_kg", "timbang1_waktu", "timbang2_waktu",
        "tara_lain_kg", "catatan",
    }
    sebelum, sesudah = {}, {}
    for kolom, nilai in perubahan.items():
        if kolom not in dapat_diubah:
            continue
        lama = getattr(trx, kolom)
        if kolom == "nomor_polisi":
            nilai = normalisasi_nopol(nilai)
        if lama == nilai:
            continue
        sebelum[kolom] = str(lama) if lama is not None else None
        sesudah[kolom] = str(nilai) if nilai is not None else None
        setattr(trx, kolom, nilai)

    if "nomor_polisi" in sesudah:
        kendaraan = await kendaraan_dari_nopol(db, trx.nomor_polisi)
        trx.kendaraan_id = kendaraan.id if kendaraan else None

    if muatan is not None:
        sebelum["muatan"] = [
            {"jenis": m.jenis_kode, "karung": m.jumlah_karung,
             "acuan_kg": float(m.berat_acuan_kg or 0)}
            for m in trx.muatan
        ]
        await _pasang_muatan(db, trx, muatan)
        sesudah["muatan"] = [
            {"jenis": m.jenis_kode, "karung": m.jumlah_karung,
             "acuan_kg": float(m.berat_acuan_kg or 0)}
            for m in trx.muatan
        ]

    if not sebelum:
        return trx

    # Hitung ulang bila transaksi sudah punya kedua angka.
    if trx.timbang2_kg is not None and trx.cara_timbang == CARA_DUA_KALI:
        aturan = await aturan_untuk(db, trx.jenis_kode)
        bermuatan, kosong = _bermuatan_dan_kosong(
            trx.arah, float(trx.timbang1_kg), float(trx.timbang2_kg)
        )
        trx.berat_bermuatan_kg = bermuatan
        trx.berat_kosong_kg = kosong
        _terapkan_hasil(trx, logic.hitung(
            aturan=aturan,
            berat_bermuatan_kg=bermuatan,
            berat_kosong_kg=kosong,
            muatan=_baris_logic(trx.muatan),
            tara_lain_kg=float(trx.tara_lain_kg or 0),
            kapasitas_kg=(await setelan.semua(db))["kapasitas_jembatan_kg"],
        ))
        sesudah["status_kontrol"] = trx.status_kontrol
        sesudah["selisih_kg"] = float(trx.selisih_kg)

    trx.jumlah_revisi = (trx.jumlah_revisi or 0) + 1
    trx.diubah_oleh_id = akun.id

    await catat_audit(
        db, akun=akun, aksi="KOREKSI", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=alasan or f"Koreksi {', '.join(sebelum)}",
        sebelum=sebelum, sesudah=sesudah,
        perangkat=trx.perangkat_kode, ip=ip,
    )
    await db.commit()
    await db.refresh(trx)
    return trx


async def void_transaksi(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    alasan: str,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Batalkan transaksi. Data TIDAK pernah dihapus — hanya ditandai."""
    if not boleh_membatalkan(akun):
        raise LayananError("Hanya Admin yang boleh membatalkan.")
    if not (alasan or "").strip():
        raise LayananError("Pembatalan harus disertai alasan.")
    if trx.status_transaksi == TRX_VOID:
        return trx

    trx.status_transaksi = TRX_VOID
    trx.void_alasan = alasan.strip()
    trx.void_oleh_id = akun.id
    trx.void_pada = sekarang()

    await catat_audit(
        db, akun=akun, aksi="VOID", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=trx.void_alasan, ip=ip,
    )
    await db.commit()
    await db.refresh(trx)
    return trx


async def tutup_paksa(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    alasan: str,
    ip: str | None = None,
) -> TimbanganTransaksi:
    """Tutup tiket yang tidak akan pernah punya timbang kedua.

    Truk yang batal bongkar tetap meninggalkan jejak: tiketnya ditutup dengan
    alasan, bukan dihapus supaya daftar terlihat rapi.
    """
    if trx.status_tiket != TIKET_TERBUKA:
        raise LayananError("Tiket ini tidak dalam keadaan terbuka.")
    if not (alasan or "").strip():
        raise LayananError("Penutupan paksa harus disertai alasan.")

    trx.status_tiket = TIKET_DITUTUP_PAKSA
    trx.tutup_paksa_alasan = alasan.strip()
    trx.diubah_oleh_id = akun.id
    _kosongkan_hasil(trx)

    await catat_audit(
        db, akun=akun, aksi="TUTUP_PAKSA", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=trx.tutup_paksa_alasan, ip=ip,
    )
    await db.commit()
    await db.refresh(trx)
    return trx


async def kunci_transaksi(
    db: AsyncSession, *, akun: TimbanganAkun, trx: TimbanganTransaksi
) -> TimbanganTransaksi:
    trx.terkunci = True
    trx.dikunci_pada = sekarang()
    await catat_audit(
        db, akun=akun, aksi="KUNCI", entitas="transaksi", entitas_id=trx.kode,
    )
    await db.commit()
    return trx


# ═══════════════════════════ Akun ═══════════════════════════

async def hapus_transaksi(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    alasan: str,
    ip: str | None = None,
) -> str:
    """Hapus catatan timbang seluruhnya. Hanya Super Admin.

    **Ini bukan pembatalan.** Membatalkan (VOID) meninggalkan barisnya di
    catatan beserta alasannya — truk yang batal bongkar tetap terlihat pernah
    datang, dan itu memang yang benar. Menghapus meniadakan barisnya sama
    sekali. Karena itu wewenangnya dipisahkan ke peran tersendiri: agar
    pekerjaan sehari-hari tidak dilakukan sambil memegang tombol yang tidak
    bisa dibatalkan.

    Yang tetap tertinggal adalah jejak auditnya, berisi salinan penuh angka
    yang dihapus beserta alasannya. Audit hanya bertambah — sebuah catatan
    boleh hilang dari daftar, tetapi tidak boleh hilang dari sejarah.
    """
    from app.timbangan.models import TimbanganCetak, TimbanganPemeriksaan

    if not akun.is_super:
        raise LayananError("Menghapus catatan timbang hanya bisa Super Admin.")
    if not (alasan or "").strip():
        raise LayananError("Penghapusan harus disertai alasan.")

    kode = trx.kode
    await db.refresh(trx, ["muatan"])
    salinan = {
        "kode": kode, "tanggal": str(trx.tanggal), "arah": trx.arah,
        "jenis_kode": trx.jenis_kode,
        "pihak": trx.pihak_nama, "supplier_id": trx.supplier_id,
        "nomor_polisi": trx.nomor_polisi, "nama_sopir": trx.nama_sopir,
        "timbang1_kg": trx.timbang1_kg, "timbang2_kg": trx.timbang2_kg,
        "netto_timbangan_kg": trx.netto_timbangan_kg,
        "berat_barang_kg": trx.berat_barang_kg,
        "berat_acuan_kg": trx.berat_acuan_kg,
        "selisih_kg": trx.selisih_kg, "selisih_persen": trx.selisih_persen,
        "status_kontrol": trx.status_kontrol,
        "status_tiket": trx.status_tiket,
        "status_transaksi": trx.status_transaksi,
        "muatan": [
            {"jenis_kode": m.jenis_kode, "jumlah_karung": m.jumlah_karung,
             "tara_per_karung_kg": m.tara_per_karung_kg,
             "berat_acuan_kg": m.berat_acuan_kg, "nomor_acuan": m.nomor_acuan}
            for m in trx.muatan
        ],
    }
    await catat_audit(
        db, akun=akun, aksi="HAPUS_TRANSAKSI", entitas="transaksi",
        entitas_id=kode,
        ringkasan=f"{kode} dihapus permanen — {alasan.strip()}",
        sebelum=salinan, sesudah={"alasan": alasan.strip()},
        perangkat=trx.perangkat_kode, ip=ip,
    )

    # Muatan dan foto ikut terhapus lewat cascade relasinya; cetak dan
    # pemeriksaan tidak punya relasi, jadi dihapus di sini. Menghapus muatan
    # dua kali membuat ORM mengira ada baris yang hilang diam-diam.
    for model in (TimbanganCetak, TimbanganPemeriksaan):
        await db.execute(delete(model).where(model.transaksi_id == trx.id))
    await db.delete(trx)
    await db.commit()
    return kode


async def _admin_aktif_lain(db: AsyncSession, kecuali_id: int) -> int:
    """Admin lain yang masih aktif — Super Admin ikut dihitung.

    Yang dijaga adalah "masih ada yang bisa mengelola pengguna", dan Super
    Admin bisa. Menghitungnya terpisah akan menolak penurunan peran yang
    sebenarnya aman.
    """
    return (await db.execute(
        select(func.count(TimbanganAkun.id)).where(
            TimbanganAkun.role.in_((ROLE_ADMIN, ROLE_SUPERADMIN)),
            TimbanganAkun.status == "aktif",
            TimbanganAkun.id != kecuali_id,
        )
    )).scalar_one()


async def _terapkan_ubah_akun(
    db: AsyncSession,
    *,
    pelaku: TimbanganAkun,
    orang: TimbanganAkun,
    nama: str | None = None,
    username: str | None = None,
    role: str | None = None,
    perangkat_kode: str | None = None,
    sandi_baru: str | None = None,
    ip: str | None = None,
) -> list[str]:
    """Ubah data satu akun. Mengembalikan daftar kolom yang benar-benar berubah.

    Dua pagar yang tidak boleh dilepas, keduanya melindungi dari mengunci diri
    sendiri di luar sistem:

      · **Selalu tersisa satu Admin aktif.** Menurunkan peran atau
        menonaktifkan Admin terakhir akan membuat tidak ada lagi yang bisa
        mengelola pengguna — dan tidak ada jalan memperbaikinya dari dalam
        aplikasi.
      · **Sandi kosong berarti tidak diubah**, bukan dikosongkan. Kalau tidak,
        Admin yang hanya ingin membetulkan ejaan nama akan tanpa sadar
        menghapus sandi orang lain.

    Sandi lama tidak pernah tersimpan maupun tercatat di audit — yang dicatat
    hanya FAKTA bahwa sandi diganti.
    """
    from app.timbangan.security import hash_sandi

    sebelum, sesudah, berubah = {}, {}, []

    if username is not None:
        bersih = username.strip().lower()
        if not bersih:
            raise LayananError("Nama pengguna tidak boleh kosong.")
        if bersih != orang.username:
            bentrok = (await db.execute(
                select(TimbanganAkun).where(
                    TimbanganAkun.username == bersih,
                    TimbanganAkun.id != orang.id,
                )
            )).scalars().first()
            if bentrok is not None:
                raise LayananError(f"Nama pengguna '{bersih}' sudah dipakai.")
            sebelum["username"], sesudah["username"] = orang.username, bersih
            orang.username = bersih
            berubah.append("nama pengguna")

    if nama is not None and nama.strip() and nama.strip() != orang.nama:
        sebelum["nama"], sesudah["nama"] = orang.nama, nama.strip()
        orang.nama = nama.strip()
        berubah.append("nama")

    if role is not None and role != orang.role:
        if role not in ROLES:
            raise LayananError(f"Peran '{role}' tidak dikenal.")
        if orang.is_admin and not await _admin_aktif_lain(db, orang.id):
            raise LayananError(
                "Ini satu-satunya Admin yang aktif. Angkat Admin lain lebih "
                "dulu, kalau tidak tidak akan ada yang bisa mengelola pengguna."
            )
        sebelum["role"], sesudah["role"] = orang.role, role
        orang.role = role
        berubah.append("peran")

    if perangkat_kode is not None:
        kode = perangkat_kode.strip().upper()[:8] or None
        if kode != orang.perangkat_kode:
            sebelum["perangkat_kode"] = orang.perangkat_kode
            sesudah["perangkat_kode"] = kode
            orang.perangkat_kode = kode
            berubah.append("kode perangkat")

    # Kosong berarti "jangan diubah" — bukan "kosongkan".
    if sandi_baru:
        try:
            orang.password_hash = hash_sandi(sandi_baru)
        except ValueError as e:
            raise LayananError(str(e)) from None
        # Sandi tidak pernah masuk audit, baik yang lama maupun yang baru.
        sesudah["sandi"] = "diganti"
        berubah.append("sandi")

    if not berubah:
        return []

    await catat_audit(
        db, akun=pelaku, aksi="UBAH_AKUN", entitas="akun", entitas_id=orang.id,
        ringkasan=f"{orang.username}: {', '.join(berubah)} diubah",
        sebelum=sebelum or None, sesudah=sesudah or None, ip=ip,
    )
    await db.commit()
    return berubah


async def _super_aktif_ada(db: AsyncSession, kecuali_id: int | None = None) -> bool:
    q = select(func.count(TimbanganAkun.id)).where(
        TimbanganAkun.role == ROLE_SUPERADMIN,
        TimbanganAkun.status == "aktif",
    )
    if kecuali_id is not None:
        q = q.where(TimbanganAkun.id != kecuali_id)
    return bool((await db.execute(q)).scalar_one())


async def _jaga_wewenang_super(
    db: AsyncSession, *, admin: TimbanganAkun, orang: TimbanganAkun,
    role_baru: str | None = None,
) -> None:
    """Admin biasa tidak boleh menyentuh Super Admin, apalagi menjadi satu.

    Kalau boleh, pemisahan perannya tidak berarti apa-apa: Admin mana pun
    tinggal mengangkat dirinya sendiri, atau menonaktifkan Super Admin yang
    ada lalu mengangkat dirinya. Wewenang menghapus data akan kembali
    melekat pada pekerjaan sehari-hari — persis yang hendak dihindari.

    Satu pengecualian, untuk membuat yang PERTAMA dan untuk memulihkan bila
    satu-satunya hilang: selama belum ada Super Admin aktif, Admin boleh
    mengangkatnya. Begitu ada, pintunya tertutup dan hanya Super Admin yang
    bisa membukanya lagi.
    """
    if admin.is_super:
        return
    if orang.is_super:
        raise LayananError(
            "Akun Super Admin hanya bisa diubah oleh Super Admin."
        )
    if role_baru == ROLE_SUPERADMIN and await _super_aktif_ada(db):
        raise LayananError(
            "Hanya Super Admin yang bisa mengangkat Super Admin baru."
        )


async def jaga_pemberian_peran(
    db: AsyncSession, *, admin: TimbanganAkun, role: str
) -> None:
    """Dipakai saat MEMBUAT akun. Pagarnya sama dengan saat mengubah peran —
    kalau tidak, Admin cukup membuat akun Super Admin baru dan masuk dengannya.
    """
    if role == ROLE_SUPERADMIN and not admin.is_super and await _super_aktif_ada(db):
        raise LayananError("Hanya Super Admin yang bisa mengangkat Super Admin baru.")
    if role not in ROLES:
        raise LayananError(f"Peran '{role}' tidak dikenal.")


async def ubah_akun(
    db: AsyncSession,
    *,
    admin: TimbanganAkun,
    orang: TimbanganAkun,
    **ubahan,
) -> list[str]:
    """Admin mengubah akun siapa pun, termasuk peran dan kode perangkat."""
    if not admin.is_admin:
        raise LayananError("Hanya Admin yang boleh mengubah akun orang lain.")
    await _jaga_wewenang_super(
        db, admin=admin, orang=orang, role_baru=ubahan.get("role")
    )
    return await _terapkan_ubah_akun(db, pelaku=admin, orang=orang, **ubahan)


async def ubah_profil(
    db: AsyncSession,
    *,
    orang: TimbanganAkun,
    nama: str | None = None,
    username: str | None = None,
    sandi_lama: str | None = None,
    sandi_baru: str | None = None,
    ip: str | None = None,
) -> list[str]:
    """Siapa pun membetulkan akunnya SENDIRI: nama, nama pengguna, sandi.

    Yang sengaja TIDAK ada di sini: peran dan kode perangkat. Keduanya
    menentukan apa yang boleh dilakukan orang ini dan nomor transaksi apa
    yang keluar dari perangkatnya — itu keputusan Admin, bukan keputusan
    pemakainya sendiri.

    Mengganti sandi menuntut sandi yang sekarang. Perangkat di pos timbang
    dipakai bergantian dan tetap masuk sepanjang shift; tanpa syarat ini,
    siapa pun yang lewat di depan layar yang ditinggal terbuka bisa mengunci
    pemiliknya keluar dari akunnya sendiri.
    """
    from app.timbangan.security import cek_sandi

    if sandi_baru:
        if not sandi_lama:
            raise LayananError(
                "Masukkan sandi Anda yang sekarang untuk menggantinya."
            )
        if not cek_sandi(sandi_lama, orang.password_hash):
            raise LayananError("Sandi sekarang tidak cocok.")

    return await _terapkan_ubah_akun(
        db, pelaku=orang, orang=orang,
        nama=nama, username=username, sandi_baru=sandi_baru, ip=ip,
    )


async def _tabel_yang_menunjuk_akun(db: AsyncSession, akun_id: int) -> list[str]:
    """Nama kolom mana saja yang masih menunjuk akun ini. Audit dikecualikan.

    Dibaca dari metadata, bukan dari daftar tabel yang ditulis tangan — supaya
    tabel baru yang menyimpan "siapa yang mengerjakan" ikut terjaga sendiri
    tanpa ada yang perlu ingat memperbarui fungsi ini.

    Audit sengaja di luar hitungan: barisnya sudah menyimpan `akun_nama`
    sebagai salinan, jadi jejaknya tetap terbaca meski penunjuknya dilepas.
    """
    from app.database import Base

    dipakai = []
    for tabel in Base.metadata.sorted_tables:
        if tabel.name == "timbangan_audit":
            continue
        for kolom in tabel.columns:
            if not any(
                fk.target_fullname == "timbangan_akun.id"
                for fk in kolom.foreign_keys
            ):
                continue
            ada = (await db.execute(
                select(literal(1)).select_from(tabel)
                .where(kolom == akun_id).limit(1)
            )).first()
            if ada:
                dipakai.append(f"{tabel.name}.{kolom.name}")
    return dipakai


async def hapus_akun(
    db: AsyncSession,
    *,
    admin: TimbanganAkun,
    orang: TimbanganAkun,
    ip: str | None = None,
) -> str:
    """Hapus akun yang belum pernah dipakai. Mengembalikan namanya.

    Menghapus akun BUKAN kebalikan dari membuatnya. Begitu seseorang pernah
    menimbang, namanya melekat pada catatan timbang, lembar pemeriksaan, dan
    riwayat cetak — dokumen yang gunanya justru menyebut siapa yang
    mengerjakan. Menghapusnya berarti salah satu dari dua hal: catatan itu
    ikut hilang, atau ia berubah menjadi menunjuk "tidak ada siapa-siapa".
    Keduanya memalsukan catatan.

    Maka yang bisa dihapus hanya akun yang belum meninggalkan jejak apa pun —
    salah ketik saat membuat, akun percobaan, orang yang batal masuk kerja.
    Selebihnya dinonaktifkan: pintunya tertutup, catatannya tetap benar.

    Jejak audit miliknya tidak ikut dihapus. Penunjuk akunnya dilepas, tetapi
    `akun_nama` sudah tersimpan sebagai salinan sejak baris itu ditulis,
    sehingga "siapa" tetap terbaca. Audit hanya bertambah — termasuk ketika
    yang dicatat adalah penghapusan ini sendiri.
    """
    from app.timbangan.models import TimbanganAudit

    if not admin.is_admin:
        raise LayananError("Hanya Admin yang boleh menghapus akun.")
    await _jaga_wewenang_super(db, admin=admin, orang=orang)
    if orang.id == admin.id:
        raise LayananError("Tidak bisa menghapus akun sendiri.")
    if orang.is_admin and not await _admin_aktif_lain(db, orang.id):
        raise LayananError(
            "Ini satu-satunya Admin yang aktif. Angkat Admin lain lebih dulu."
        )

    dipakai = await _tabel_yang_menunjuk_akun(db, orang.id)
    if dipakai:
        raise LayananError(
            f"{orang.nama} sudah punya riwayat kerja, jadi akunnya tidak bisa "
            "dihapus tanpa merusak catatan yang menyebut namanya. "
            "Nonaktifkan saja — pintunya tertutup, catatannya tetap benar."
        )

    nama = orang.nama
    await catat_audit(
        db, akun=admin, aksi="HAPUS_AKUN", entitas="akun", entitas_id=orang.id,
        ringkasan=f"{orang.username} ({nama}) dihapus — belum punya riwayat kerja",
        sebelum={"username": orang.username, "nama": nama, "role": orang.role,
                 "perangkat_kode": orang.perangkat_kode, "status": orang.status},
        ip=ip,
    )
    # Lepaskan penunjuk di audit sebelum barisnya hilang; `akun_nama` tetap.
    await db.execute(
        update(TimbanganAudit)
        .where(TimbanganAudit.akun_id == orang.id)
        .values(akun_id=None)
    )
    await db.delete(orang)
    await db.commit()
    return nama


async def ubah_status_akun(
    db: AsyncSession, *, admin: TimbanganAkun, orang: TimbanganAkun,
    ip: str | None = None,
) -> str:
    """Aktifkan atau nonaktifkan satu akun."""
    if not admin.is_admin:
        raise LayananError("Hanya Admin yang boleh mengubah akun.")
    await _jaga_wewenang_super(db, admin=admin, orang=orang)
    if orang.id == admin.id:
        raise LayananError("Anda tidak bisa menonaktifkan akun sendiri.")
    if (orang.status == "aktif" and orang.is_admin
            and not await _admin_aktif_lain(db, orang.id)):
        raise LayananError(
            "Ini satu-satunya Admin yang aktif — menonaktifkannya membuat "
            "tidak ada lagi yang bisa mengelola pengguna."
        )

    lama = orang.status
    orang.status = "nonaktif" if lama == "aktif" else "aktif"
    await catat_audit(
        db, akun=admin, aksi="UBAH_STATUS_AKUN", entitas="akun",
        entitas_id=orang.id, ringkasan=f"{orang.username} → {orang.status}",
        sebelum={"status": lama}, sesudah={"status": orang.status}, ip=ip,
    )
    await db.commit()
    return orang.status


# ═══════════════════════════ Pemeriksaan (SOP butir 6) ═══════════════════

async def buka_pemeriksaan(
    db: AsyncSession, *, akun: TimbanganAkun, trx: TimbanganTransaksi
) -> TimbanganPemeriksaan:
    """Buka lembar pemeriksaan bila belum ada yang terbuka."""
    ada = (await db.execute(
        select(TimbanganPemeriksaan).where(
            TimbanganPemeriksaan.transaksi_id == trx.id,
            TimbanganPemeriksaan.status == PEMERIKSAAN_DIBUKA,
        )
    )).scalars().first()
    if ada is not None:
        return ada

    lembar = TimbanganPemeriksaan(transaksi_id=trx.id, dibuka_oleh_id=akun.id)
    db.add(lembar)
    await db.flush()
    await catat_audit(
        db, akun=akun, aksi="PEMERIKSAAN_DIBUKA", entitas="pemeriksaan",
        entitas_id=lembar.id, ringkasan=f"{trx.kode}: {trx.status_kontrol}",
    )
    return lembar


async def pemeriksaan_transaksi(
    db: AsyncSession, transaksi_id: int
) -> TimbanganPemeriksaan | None:
    return (await db.execute(
        select(TimbanganPemeriksaan)
        .where(TimbanganPemeriksaan.transaksi_id == transaksi_id)
        .order_by(TimbanganPemeriksaan.id.desc())
    )).scalars().first()


async def selesaikan_pemeriksaan(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    lembar: TimbanganPemeriksaan,
    langkah: dict,
    kategori_hasil: str,
    catatan_resolusi: str,
    dilaporkan_ke: str | None = None,
    ip: str | None = None,
) -> TimbanganPemeriksaan:
    """Tutup lembar pemeriksaan dengan catatan resolusi.

    Selesai TIDAK berarti bersih — ia berarti sudah ditelusuri dan hasilnya
    tercatat. Itulah gunanya `kategori_hasil` dan `catatan_resolusi`.
    """
    if not akun.is_admin:
        raise LayananError("Hanya Admin yang boleh menutup pemeriksaan.")
    if not (catatan_resolusi or "").strip():
        raise LayananError("Catatan resolusi wajib diisi.")
    if not kategori_hasil:
        raise LayananError("Kategori hasil wajib dipilih.")

    for kolom in (
        "langkah_ulang_timbang", "langkah_hitung_karung", "langkah_periksa_tara",
        "langkah_periksa_dokumen", "langkah_periksa_muatan", "langkah_lapor",
    ):
        if kolom in langkah:
            setattr(lembar, kolom, langkah[kolom])

    if dilaporkan_ke:
        lembar.dilaporkan_ke = dilaporkan_ke
        lembar.dilaporkan_pada = lembar.dilaporkan_pada or sekarang()

    lembar.kategori_hasil = kategori_hasil
    lembar.catatan_resolusi = catatan_resolusi.strip()
    lembar.status = PEMERIKSAAN_SELESAI
    lembar.ditutup_oleh_id = akun.id
    lembar.ditutup_pada = sekarang()

    await catat_audit(
        db, akun=akun, aksi="PEMERIKSAAN_SELESAI", entitas="pemeriksaan",
        entitas_id=lembar.id,
        ringkasan=f"{kategori_hasil}: {lembar.catatan_resolusi[:120]}", ip=ip,
    )
    await db.commit()
    await db.refresh(lembar)
    return lembar


# ═══════════════════════════ Cetak & foto ═══════════════════════════

async def catat_cetak(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    alasan: str | None = None,
    format: str = "80MM",
    ip: str | None = None,
) -> TimbanganCetak:
    """Catat satu kali cetak. Cetak kedua dan seterusnya wajib beralasan."""
    urutan = ((await db.execute(
        select(func.max(TimbanganCetak.urutan)).where(
            TimbanganCetak.transaksi_id == trx.id
        )
    )).scalar() or 0) + 1

    if urutan > 1 and not (alasan or "").strip():
        raise LayananError("Cetak ulang harus disertai alasan.")

    baris = TimbanganCetak(
        transaksi_id=trx.id, urutan=urutan, ulang=urutan > 1,
        format=(format if format in ("80MM", "NCR") else "80MM"),
        alasan=(alasan or None), oleh_id=akun.id,
    )
    db.add(baris)
    await catat_audit(
        db, akun=akun, aksi="CETAK", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=f"cetak ke-{urutan} ({baris.format})"
                  + (f" — {alasan}" if alasan else ""), ip=ip,
    )
    await db.commit()
    return baris


async def simpan_foto(
    db: AsyncSession,
    *,
    akun: TimbanganAkun,
    trx: TimbanganTransaksi,
    nama_file: str,
    mime: str,
    konten: bytes,
    jenis: str = "LAIN",
) -> TimbanganFoto:
    maks_mb = (await setelan.semua(db))["maks_foto_mb"]
    if len(konten) > maks_mb * 1024 * 1024:
        raise LayananError(f"Foto terlalu besar (maksimal {maks_mb:g} MB).")
    foto = TimbanganFoto(
        transaksi_id=trx.id, jenis=jenis, nama_file=nama_file[:255],
        mime=mime or "image/jpeg", ukuran_byte=len(konten), konten=konten,
        diunggah_oleh_id=akun.id,
    )
    db.add(foto)
    await catat_audit(
        db, akun=akun, aksi="UNGGAH_FOTO", entitas="transaksi", entitas_id=trx.kode,
        ringkasan=f"{jenis}: {nama_file}",
    )
    await db.commit()
    return foto


# ═══════════════════════════ Query & filter ═══════════════════════════

@dataclass
class FilterTransaksi:
    dari: date | None = None
    sampai: date | None = None
    supplier_id: int | None = None
    arah: str | None = None
    jenis_kode: str | None = None
    status_kontrol: str | None = None
    status_tiket: str | None = None
    nomor_polisi: str | None = None
    cari: str | None = None
    sertakan_void: bool = False
    #: Batasi ke transaksi yang ditimbang orang ini (timbang pertama ATAU
    #: kedua). Dipakai untuk petugas, yang hanya berhak melihat hasil
    #: pekerjaannya sendiri.
    petugas_id: int | None = None


def _terapkan_filter(q, f: FilterTransaksi):
    if not f.sertakan_void:
        q = q.where(TimbanganTransaksi.status_transaksi == TRX_AKTIF)
    if f.dari:
        q = q.where(TimbanganTransaksi.tanggal >= f.dari)
    if f.sampai:
        q = q.where(TimbanganTransaksi.tanggal <= f.sampai)
    if f.supplier_id:
        q = q.where(TimbanganTransaksi.supplier_id == f.supplier_id)
    if f.arah:
        q = q.where(TimbanganTransaksi.arah == f.arah)
    if f.jenis_kode:
        q = q.where(TimbanganTransaksi.jenis_kode == f.jenis_kode)
    if f.status_kontrol:
        q = q.where(TimbanganTransaksi.status_kontrol == f.status_kontrol)
    if f.status_tiket:
        q = q.where(TimbanganTransaksi.status_tiket == f.status_tiket)
    if f.nomor_polisi:
        q = q.where(TimbanganTransaksi.nomor_polisi == normalisasi_nopol(f.nomor_polisi))
    if f.petugas_id:
        q = q.where(or_(
            TimbanganTransaksi.timbang1_petugas_id == f.petugas_id,
            TimbanganTransaksi.timbang2_petugas_id == f.petugas_id,
        ))
    if f.cari:
        pola = f"%{f.cari.strip()}%"
        q = q.where(or_(
            TimbanganTransaksi.kode.ilike(pola),
            TimbanganTransaksi.nomor_polisi.ilike(pola),
            TimbanganTransaksi.pihak_nama.ilike(pola),
            TimbanganTransaksi.nama_sopir.ilike(pola),
        ))
    return q


@dataclass
class BarisTransaksi:
    trx: TimbanganTransaksi
    supplier_nama: str | None


async def daftar_transaksi(
    db: AsyncSession, f: FilterTransaksi, *, batas: int = 100, offset: int = 0
) -> list[BarisTransaksi]:
    q = _terapkan_filter(
        select(TimbanganTransaksi, Supplier.nama_supplier)
        .outerjoin(Supplier, Supplier.id == TimbanganTransaksi.supplier_id),
        f,
    ).order_by(
        TimbanganTransaksi.tanggal.desc(), TimbanganTransaksi.id.desc()
    ).limit(batas).offset(offset)
    return [BarisTransaksi(trx=t, supplier_nama=n) for t, n in (await db.execute(q)).all()]


async def hitung_transaksi(db: AsyncSession, f: FilterTransaksi) -> int:
    q = _terapkan_filter(
        select(func.count(TimbanganTransaksi.id)).select_from(TimbanganTransaksi), f
    )
    return (await db.execute(q)).scalar_one()


async def tiket_terbuka(db: AsyncSession) -> list[BarisTransaksi]:
    """Truk yang sudah timbang pertama dan belum kembali."""
    return await daftar_transaksi(
        db, FilterTransaksi(status_tiket=TIKET_TERBUKA), batas=200
    )


async def tiket_menganggur(db: AsyncSession) -> list[BarisTransaksi]:
    """Tiket terbuka yang sudah kelewat lama — kandidat ditutup paksa."""
    jam = (await setelan.semua(db))["jam_tiket_menganggur"]
    batas = sekarang() - timedelta(hours=jam)
    q = (
        select(TimbanganTransaksi, Supplier.nama_supplier)
        .outerjoin(Supplier, Supplier.id == TimbanganTransaksi.supplier_id)
        .where(
            TimbanganTransaksi.status_tiket == TIKET_TERBUKA,
            TimbanganTransaksi.status_transaksi == TRX_AKTIF,
            TimbanganTransaksi.timbang1_waktu_sistem < batas,
        )
        .order_by(TimbanganTransaksi.timbang1_waktu_sistem)
    )
    return [BarisTransaksi(trx=t, supplier_nama=n) for t, n in (await db.execute(q)).all()]


async def ambil_transaksi(
    db: AsyncSession, transaksi_id: int
) -> BarisTransaksi | None:
    baris = (await db.execute(
        select(TimbanganTransaksi, Supplier.nama_supplier)
        .outerjoin(Supplier, Supplier.id == TimbanganTransaksi.supplier_id)
        .where(TimbanganTransaksi.id == transaksi_id)
    )).first()
    if baris is None:
        return None
    return BarisTransaksi(trx=baris[0], supplier_nama=baris[1])


def ke_ringkas(baris: list[BarisTransaksi]) -> list[logic.TransaksiRingkas]:
    """Bentuk yang dipakai deteksi pola & skor — tanpa objek DB."""
    hasil = []
    for b in baris:
        t = b.trx
        if t.selisih_kg is None or t.status_kontrol is None:
            continue
        selisih = float(t.selisih_kg or 0)
        # Batas yang relevan adalah batas DI ARAH selisihnya. Untuk aturan yang
        # tidak simetris — gabah kering boleh lebih, kiriman tidak boleh kurang
        # — memakai satu angka saja akan salah menilai.
        if selisih < 0:
            batas = abs(float(t.batas_bawah_kg)) if t.batas_bawah_kg is not None else 0.0
        else:
            batas = float(t.batas_atas_kg) if t.batas_atas_kg is not None else 0.0
        hasil.append(logic.TransaksiRingkas(
            tanggal=t.tanggal,
            selisih_kg=selisih,
            selisih_persen=float(t.selisih_persen or 0),
            batas_kg=batas,
            berat_barang_kg=float(t.berat_barang_kg or 0),
            berat_acuan_kg=float(t.berat_acuan_kg or 0),
            nomor_polisi=t.nomor_polisi,
            pihak_id=t.supplier_id,
            pihak_nama=b.supplier_nama or (t.pihak_nama or ""),
            dikoreksi=bool(t.jumlah_revisi),
            kode=t.kode,
        ))
    return hasil


# ═══════════════════════════ Ringkasan & monitoring ═══════════════════════

@dataclass
class RingkasanDashboard:
    jumlah: int = 0
    tiket_terbuka: int = 0
    perlu_periksa: int = 0
    pemeriksaan_terbuka: int = 0
    total_barang_kg: float = 0.0
    total_selisih_kg: float = 0.0


async def ringkasan_dashboard(
    db: AsyncSession, f: FilterTransaksi
) -> RingkasanDashboard:
    baris = (await db.execute(_terapkan_filter(
        select(
            func.count(TimbanganTransaksi.id),
            func.coalesce(func.sum(TimbanganTransaksi.berat_barang_kg), 0),
            func.coalesce(func.sum(TimbanganTransaksi.selisih_kg), 0),
        ).select_from(TimbanganTransaksi),
        f,
    ))).one()

    perlu = (await db.execute(_terapkan_filter(
        select(func.count(TimbanganTransaksi.id)).select_from(TimbanganTransaksi), f
    ).where(
        TimbanganTransaksi.status_kontrol.in_(sorted(logic.STATUS_WAJIB_PERIKSA))
    ))).scalar_one()

    terbuka = (await db.execute(_terapkan_filter(
        select(func.count(TimbanganTransaksi.id)).select_from(TimbanganTransaksi), f
    ).where(TimbanganTransaksi.status_tiket == TIKET_TERBUKA))).scalar_one()

    lembar = (await db.execute(
        select(func.count(TimbanganPemeriksaan.id))
        .where(TimbanganPemeriksaan.status == PEMERIKSAAN_DIBUKA)
    )).scalar_one()

    return RingkasanDashboard(
        jumlah=baris[0],
        tiket_terbuka=terbuka,
        perlu_periksa=perlu,
        pemeriksaan_terbuka=lembar,
        total_barang_kg=float(baris[1] or 0),
        total_selisih_kg=float(baris[2] or 0),
    )


@dataclass
class BarisMonitoring:
    supplier_id: int
    nama: str
    jumlah_transaksi: int
    skor: logic.SkorPihak | None
    pola: list[logic.Pola]
    status_saat_ini: str
    status_disarankan: str


async def monitoring_supplier(
    db: AsyncSession, f: FilterTransaksi, *, minimal_transaksi: int = 3
) -> list[BarisMonitoring]:
    """Skor & pola per pihak. Bahasa hasilnya selalu 'perlu diperiksa',
    tidak pernah menuduh."""
    semua = await daftar_transaksi(db, f, batas=5000)
    per_supplier: dict[int, list[BarisTransaksi]] = {}
    nama: dict[int, str] = {}
    for b in semua:
        if b.trx.supplier_id is None:
            continue
        per_supplier.setdefault(b.trx.supplier_id, []).append(b)
        nama[b.trx.supplier_id] = b.supplier_nama or "(tanpa nama)"

    profil = {
        p.supplier_id: p for p in (await db.execute(
            select(TimbanganSupplierProfil)
        )).scalars()
    }

    hasil: list[BarisMonitoring] = []
    for supplier_id, baris in per_supplier.items():
        if len(baris) < minimal_transaksi:
            continue
        ringkas = ke_ringkas(baris)
        skor = logic.hitung_skor_pihak(ringkas)
        pola = logic.deteksi_pola(ringkas)
        hasil.append(BarisMonitoring(
            supplier_id=supplier_id,
            nama=nama[supplier_id],
            jumlah_transaksi=len(ringkas),
            skor=skor,
            pola=pola,
            status_saat_ini=(
                profil[supplier_id].status_monitoring
                if supplier_id in profil else "AKTIF"
            ),
            status_disarankan=logic.status_pihak_disarankan(skor, pola),
        ))
    hasil.sort(key=lambda b: (b.skor.skor_total if b.skor else 100))
    return hasil


async def simpan_skor(db: AsyncSession, baris: list[BarisMonitoring]) -> int:
    """Simpan cache skor 'TERKINI' — dihitung ulang, bukan ditumpuk."""
    disimpan = 0
    for b in baris:
        if b.skor is None:
            continue
        lama = (await db.execute(
            select(TimbanganSkorSupplier).where(
                TimbanganSkorSupplier.supplier_id == b.supplier_id,
                TimbanganSkorSupplier.periode == "TERKINI",
            )
        )).scalars().first()
        data = dict(
            skor_total=b.skor.skor_total,
            kategori=b.skor.kategori,
            jumlah_transaksi=b.jumlah_transaksi,
            komponen_json=json.dumps(b.skor.komponen, ensure_ascii=False),
            pola_json=json.dumps(
                [
                    {"kode": p.kode, "judul": p.judul,
                     "keterangan": p.keterangan, "tingkat": p.tingkat}
                    for p in b.pola
                ],
                ensure_ascii=False,
            ),
            dihitung_pada=sekarang(),
        )
        if lama is None:
            db.add(TimbanganSkorSupplier(
                supplier_id=b.supplier_id, periode="TERKINI", **data
            ))
        else:
            for kolom, nilai in data.items():
                setattr(lama, kolom, nilai)
        disimpan += 1
    await db.commit()
    return disimpan
