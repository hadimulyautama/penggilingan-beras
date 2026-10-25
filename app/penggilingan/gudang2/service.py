"""Logika Gudang 2 (Penyosohan) — PK masuk, silo/tumpukan, pindah tumpukan→silo.

Acuan WAJIB: LOGIKA_SILO_GUDANG2.md.
- Silo G2 = KOLAM CAMPURAN (banyak sumber).
- Stok silo/tumpukan DITURUNKAN (bukan kolom saldo).
- Tumpukan WAJIB masuk silo dulu sebelum disosoh.
- Pindah tumpukan→silo HANYA operator Gudang 2 — TANPA admin (keputusan
  pemilik 4 Oktober 2026, Aturan 2; lihat `api.act_pindah_tumpukan_silo`),
  bisa parsial, cap 60t.
- PK beli luar yang BARU masuk SELALU ke tumpukan dulu — tak boleh langsung
  ke silo (keputusan pemilik 4 Oktober 2026, Aturan 1; lihat
  `masukkan_pk_luar`). Baris lama sebelum aturan ini tetap apa adanya.
- HPP silo = weighted-average bahan yang SUDAH di silo (kecuali HPP belum tersedia).
"""
from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.peran import PERAN_ADMIN_KEATAS
from app.config import settings
from app.database import input_time
from app.models import (
    Jasa,
    BerasKeSilo,
    BrokenKeSilo,
    HasilSampingKeSilo,
    InternalTransfer,
    OutgoingItem,
    OutgoingRecord,
    PkGudang2Intake,
    PkPurchaseBatch,
    PkPurchaseVerification,
    PkRejection,
    PkTumpukanToSilo,
    PolishingProcess,
    PolishingSiloUsage,
    Silo,
    Supplier,
    User,
    Warehouse,
)
from app.models.peristiwa import (
    PK_LUAR_MASUK, PK_MASUK_G2, PK_MASUK_G2_KOREKSI_BOBOT,
    PK_TUMPUKAN_KE_SILO, PK_TUMPUKAN_KE_SILO_KOREKSI_BOBOT,
)
from app.services import peristiwa as buku
from app.services.activity_log import log_activity
from app.services.codegen import (
    next_beras_move_code,
    next_broken_move_code,
    next_pk_purchase_code,
    next_rejection_code,
    next_tumpukan_move_code,
)
from app.services.jasa import (
    JasaError,
    kunci_silo,
    pastikan_satu_pemilik,
    pemilik_silo_g2,
)
from app.services.notification import create_notification
from app.services.armada import armada_dari_nomor_polisi
from app.penggilingan.gudang1.services.purchase import (
    find_or_create_supplier,
    pesanan_jasa_dari_tiket,
)
from app.penggilingan.gudang1.services.bobot import dari_batch
from app.penggilingan.gudang1.services.timbang_link import bobot_awal_dari_tiket
from app.penggilingan.gudang1.services.timbang_link import (
    TiketSudahDipakai,
    adalah_jasa,
    ambil_tiket,
    kunci_tiket_untuk_ditaut,
    tutup_paksa_pk_ditolak,
)
from app.penggilingan.peta_jenis import intake_dari_jenis
from app.penggilingan.gudang2.karung import bobot_per_karung
from app.penggilingan.gudang2.models import PkPenyesuaianStok

#: JENIS tempat PK di Gudang 2. Yang disimpan ini, bukan nama silonya —
#: silo MANA ada di kolom `silo_id`. Lihat migrasi 0057.
SILO, DITUMPUK = "silo", "ditumpuk"
log = logging.getLogger("gudang2.service")

#: Kata LAMA yang masih berdiri di baris sebelum 24 September 2026, dan masih
#: dikirim halaman yang belum dimuat ulang. Diterima saat MEMBACA masukan,
#: tidak pernah ditulis lagi.
_KATA_LAMA = {"silo_a": "A", "silo_b": "B"}


class Gudang2Error(Exception):
    """Kesalahan Gudang 2 dengan pesan siap-tampil (args[0])."""


def _pastikan_komoditas_silo(silo: Silo, komoditas: str) -> None:
    from app.penggilingan.silo_policy import LABEL_KOMODITAS, boleh_masuk
    if not boleh_masuk(silo, komoditas, "g2"):
        label = LABEL_KOMODITAS.get(komoditas, komoditas)
        raise Gudang2Error(f"{silo.nama_silo} tidak menerima {label} menurut filter komoditasnya.")


# ─────────────────────────── Master helpers ───────────────────────────


def _pesan_integritas(e: IntegrityError, tabel: str, kode: str) -> str:
    """Terjemahkan pelanggaran basis data jadi kalimat yang JUJUR.

    Dulu setiap `IntegrityError` di sini dilabeli "Tiket timbang ini sudah
    ditautkan ke batch lain" — apa pun sebabnya. Itu menutupi dua hal
    sekaligus. Pertama, tabrakan kode harian (P-K-01) muncul sebagai kalimat
    tentang tiket, sehingga operator mencari masalah di tempat yang salah
    seharian. Kedua, pelanggaran lain jadi tak terlihat sama sekali.

    Dibedakan menurut NAMA CONSTRAINT-nya, bukan menurut tebakan: hanya
    pelanggaran unik tautan tiket yang boleh berbunyi soal tiket.
    """
    nama = ""
    asli = getattr(e, "orig", None)
    for atribut in ("constraint_name", "diag"):
        nilai = getattr(asli, atribut, None)
        nama = nama or getattr(nilai, "constraint_name", None) or (
            nilai if isinstance(nilai, str) else "")
    nama = (nama or str(asli))[:200]

    if f"uq_{tabel}_timbangan" in nama or "timbangan_transaksi_id" in nama:
        return "Tiket timbang ini sudah ditautkan ke batch lain."
    if kode and kode in nama or "kode" in nama:
        return (f"Nomor {kode} ternyata sudah dipakai. Coba simpan sekali lagi — "
                "nomornya akan diterbitkan ulang.")
    return (f"Tersimpan gagal karena aturan basis data: {nama}. "
            "Sebutkan pesan ini ke admin bila berulang.")

async def _g2_warehouse_id(db: AsyncSession) -> int:
    wid = (
        await db.execute(
            select(Warehouse.id).where(Warehouse.kode_fungsi == "g2", Warehouse.aktif.is_(True))
        )
    ).scalars().first()
    if wid is None:
        raise Gudang2Error("Data Gudang 2 belum ada.")
    return wid


async def get_g2_silo(db: AsyncSession, letter: str) -> Silo | None:
    wid = await _g2_warehouse_id(db)
    nama = (letter or "").strip()
    return (
        await db.execute(
            select(Silo).where(
                Silo.warehouse_id == wid,
                Silo.aktif.is_(True),
                func.lower(Silo.nama_silo).in_({nama.lower(), f"silo {nama}".lower()}),
            )
        )
    ).scalars().first()


async def silo_g2_dari(db: AsyncSession, nilai: str) -> Silo | None:
    """Silo Gudang 2 dari apa pun yang dikirim layar: "A", "Silo A", "silo_a".

    Tiga bentuk, satu jawaban — dan tak satu pun daftar nama yang diketik di
    kode. `silo_a` diterima karena halaman lama masih mengirimkannya
    (`pindah.js` membuat halaman berumur panjang), dan karena ia tersimpan di
    baris-baris lama.
    """
    teks = (nilai or "").strip()
    if not teks:
        return None
    nama = _KATA_LAMA.get(teks.lower(), teks)
    return await get_g2_silo(db, nama)


async def label_tujuan(db: AsyncSession, tujuan: str | None,
                       silo_id: int | None) -> str:
    """Kalimat untuk layar: "Silo C" atau "tumpukan".

    Dibaca dari MASTER, bukan dari kamus. Kamus lama
    `{"silo_a": "Silo A", "silo_b": "Silo B"}` melempar `KeyError` — yaitu 500,
    halaman putih tanpa sebab — pada nilai ketiga yang belum dikenalnya, dan ia
    menunggu di belakang penjaga yang suatu hari dilonggarkan seseorang.
    """
    if silo_id is not None:
        silo = await db.get(Silo, silo_id)
        if silo is not None:
            return silo.nama_silo
    if (tujuan or "") in (DITUMPUK, ""):
        return "tumpukan"
    # Baris lama tanpa `silo_id` (mestinya tak ada sesudah migrasi 0057) —
    # katanya dipakai apa adanya, bukan dijawab dengan galat.
    return _KATA_LAMA.get(tujuan, tujuan) or "tumpukan"


def is_operator_gudang2(user: User, g2_wid: int) -> bool:
    """Operator Gudang 2 — Direksi ke atas selalu boleh.

    Dulu berbunyi `user.role == "admin"`, jadi SUPER ADMIN jatuh ke baris di
    bawahnya, gagal syarat "operator", lalu ditolak. Peran tertinggi kehilangan
    seluruh Gudang 2 — pola yang sudah sembilan kali berulang di kode ini.
    """
    from hmu_identitas import peran as P

    if P.admin_keatas(user.role):
        return True
    # Operator mana pun: gudang utama bukan pagar (pemilik 13 Sep 2026,
    # operator saling menggantikan). `g2_wid` dipertahankan untuk pemanggil.
    return P.operator_saja(user.role)


# ─────────────────────────── Formula stok ───────────────────────────
async def segarkan_status_silo(db: AsyncSession, silo_id: int | None) -> None:
    """Samakan `Silo.status` dengan isi silo yang SEBENARNYA.

    Temuan QA 28 September 2026: sesudah penyosohan ditutup, silo Gudang 2 yang
    berisi 2.000 kg PK baru tetap tercap `kosong`. Diperiksa lebih jauh, sebabnya
    lebih sederhana dan lebih buruk daripada satu cap yang salah: Gudang 2 TAK
    PERNAH menulis kolom itu sama sekali, jadi seluruh silonya membeku pada nilai
    yang ditanam seed. Gudang 1 justru konsisten menulisnya.

    Hari ini tak ada yang rusak — tak satu pun layar membaca kolom itu; semuanya
    membaca `hitung_stok_silo`, dan `dashboard._silo_status` pun menurunkan
    "terisi" dari baris `SiloStorage`, bukan dari sini. Yang diperbaiki justru
    itu: kolom yang ditulis tanpa pernah dibaca DAN isinya salah adalah kolom
    yang akan dipercaya orang berikutnya.

    DITURUNKAN, bukan ditebak: nilainya dihitung dari `hitung_stok_silo`, jawaban
    yang sama yang dipakai layar. Dua sumber untuk satu pertanyaan akan
    berselisih, dan yang salah adalah yang lebih jarang dibaca orang — yaitu
    kolom ini.

    Dipanggil dari corong yang MENGUBAH ISI silo G2, bukan dari tiap penulis:
    `_add_intake` (PK masuk, satu titik tulis untuk PK luar maupun transfer G1),
    `_catat_pindah` (tumpukan → silo), dan penutupan penyosohan per silo. Yang
    menjaga bahwa ketiganya benar-benar memanggilnya adalah uji PERILAKU, bukan
    uji yang membaca sumber: sesudah tiap operasi, status wajib sama dengan
    "stoknya di atas nol".
    """
    if silo_id is None:
        return
    silo = await db.get(Silo, silo_id)
    if silo is None:
        return
    silo.status = "terisi" if await hitung_stok_silo(db, silo_id) > 0.001 else "kosong"


async def hitung_stok_silo(db: AsyncSession, silo_id: int, *,
                           pemilik: str = "semua") -> float:
    """Stok campuran sebuah silo G2 dari seluruh arus masuk dan keluar.

    `pemilik` bawaannya "semua" — isi FISIK silonya — dan itu bukan kelonggaran:
    angka ini dipakai menentukan status silo, menolak penyosohan dari silo
    kosong, dan menyalin `berat_awal_kg` saat sosoh dimulai. Menyaringnya di
    sana akan membuat silo yang berisi terbaca kosong, lalu hilang dari borang
    tanpa satu pun galat — kelas kerusakan yang sudah pernah dibayar saat stok
    silo disaring dengan kata tujuannya.

    "pabrik" hanya untuk pertanyaan MILIK ("berapa yang pabrik punya"), dan
    pemanggilnya menyebutnya terang-terangan. "jasa" kebalikannya — barang
    titipan saja — dan ia ADA supaya layar yang menyaring stok pabrik bisa
    menyebut titipannya DI SEBELAHNYA alih-alih menghilangkannya: PK jasa yang
    tidak terbaca di mana pun membuat operator menyimpulkan barangnya tak bisa
    dipindahkan. Tiga nilai, dan "pabrik" + "jasa" = "semua".

    Isi silo boleh merupakan campuran PK, beras putih, broken, menir, dan
    reject. Karena itu jenis historis pada master silo tidak menentukan
    hitungan stok; semua arus masuk dihitung bersama dan pemakaian/keluar
    mengurangi saldo campuran yang sama.
    """
    if pemilik == "semua":
        # Toleransi timbang berlaku per pemilik. Jangan satukan defisit kecil
        # milik A dengan stok milik B di tumpukan fisik yang sama.
        return (await hitung_stok_silo(db, silo_id, pemilik="pabrik")
                + await hitung_stok_silo(db, silo_id, pemilik="jasa"))
    # ── SATU kalimat pemilik, EMPAT bagian hitungan ──
    #
    # Dulu saringannya cuma dipasang pada dua yang MASUK; `terpakai` tak
    # disaring sama sekali. Akibatnya satu proses sosoh barang pelanggan
    # mengurangi stok PABRIK silo itu — angkanya turun, bisa sampai negatif,
    # dan tak ada satu pun galat yang menyebutnya. Kelas kerusakan yang sama
    # dengan yang membuat PK jasa hilang dari Beranda.
    #
    # `jasa_id` ada di `pk_gudang2_intakes` MAUPUN `polishing_process`, jadi
    # kalimatnya sama untuk keduanya.
    def milik(k):
        return k.jasa_id.is_(None) if pemilik == "pabrik" else k.jasa_id.isnot(None)

    syarat_langsung = [PkGudang2Intake.silo_id == silo_id]
    # Syaratnya menempel pada INTAKE di kedua jalur masuk — `pk_tumpukan_to_silo`
    # tak punya `jasa_id` sendiri, pemiliknya ada di intake asalnya.
    q_tumpukan = (select(func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0))
                  .where(PkTumpukanToSilo.silo_id == silo_id))
    q_terpakai = (
        select(func.coalesce(func.sum(PolishingSiloUsage.berat_terpakai_kg), 0))
        .where(PolishingSiloUsage.silo_id == silo_id,
               # Hanya proses yang berat_akhir-nya sudah diisi.
               PolishingSiloUsage.berat_akhir_kg.isnot(None)))
    # Suku KEEMPAT, lahir bersamaan dengan jalur pengambilan PK Gudang 2
    # (pesan kerja 7 Oktober 2026, butir 4 — migrasi 0076): pengambilan tanpa
    # suku pengurang ini membuat PK terbaca utuh sesudah diangkut, dan silo
    # yang terbaca berisi padahal sudah kosong menolak isian berikutnya.
    q_keluar = (select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
                .join(OutgoingRecord,
                      OutgoingRecord.id == OutgoingItem.outgoing_record_id)
                .where(OutgoingItem.item_type == "pk_g2",
                       OutgoingItem.silo_id == silo_id))
    q_broken = (select(func.coalesce(func.sum(BrokenKeSilo.berat_kg), 0))
                .where(BrokenKeSilo.silo_id == silo_id))
    q_beras = (select(func.coalesce(func.sum(BerasKeSilo.berat_kg), 0))
               .where(BerasKeSilo.silo_id == silo_id))
    q_hasil_samping = (select(func.coalesce(func.sum(HasilSampingKeSilo.berat_kg), 0))
                       .where(HasilSampingKeSilo.silo_id == silo_id))
    if pemilik != "semua":
        syarat_langsung.append(milik(PkGudang2Intake))
        q_tumpukan = q_tumpukan.join(
            PkGudang2Intake,
            PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id
        ).where(milik(PkGudang2Intake))
        q_terpakai = q_terpakai.join(
            PolishingProcess,
            PolishingProcess.id == PolishingSiloUsage.polishing_process_id
        ).where(milik(PolishingProcess))
        q_keluar = q_keluar.where(milik(OutgoingRecord))
        q_broken = q_broken.where(milik(BrokenKeSilo))
        q_beras = q_beras.where(milik(BerasKeSilo))
        q_hasil_samping = q_hasil_samping.where(milik(HasilSampingKeSilo))
    q_langsung = select(func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0)).where(
        *syarat_langsung)
    # Tujuh arus adalah agregat independen. Kirim sebagai scalar subquery
    # dalam satu SELECT agar satu pembacaan saldo tidak memerlukan tujuh
    # perjalanan ke Postgres (dikalikan dua pemilik dan beberapa penjaga
    # dalam satu penyimpanan). Saringan pemilik serta cermin batal tetap
    # menempel pada setiap arus, tanpa cache yang bisa menyimpan saldo lama.
    (masuk_langsung, masuk_dari_tumpukan, masuk_broken, terpakai,
     keluar, masuk_beras_putih, masuk_hasil_samping) = (
        await db.execute(select(*(q.scalar_subquery() for q in (
            q_langsung, q_tumpukan, q_broken, q_terpakai, q_keluar,
            q_beras, q_hasil_samping))))
    ).one()
    # Toleransi timbang pada barang keluar dapat mengizinkan selisih kecil
    # (maks. 0,5 kg). Jangan biarkan selisih itu menjadi saldo negatif yang
    # mengurangi muatan pemilik berikutnya ketika silo sudah dikosongkan.
    return max(0.0, float(masuk_langsung) + float(masuk_dari_tumpukan)
               + float(masuk_broken) + float(masuk_beras_putih)
               + float(masuk_hasil_samping)
               - float(terpakai) - float(keluar))


async def komposisi_bahan_silo(
    db: AsyncSession, silo_id: int, *, sampai=None,
    kecuali_proses_id: int | None = None, target_kg: float | None = None,
) -> dict[str, float]:
    """Komposisi bahan yang tersedia di silo pada satu waktu.

    `jenis_isi` pada master silo hanya metadata umum (silo baru bernilai
    ``campuran``), jadi komposisi diturunkan dari arus masuk yang sebenarnya.
    Karena silo adalah kolam campuran dan pemakaian sosoh lama hanya menyimpan
    berat totalnya, pemakaian terdahulu dialokasikan FIFO ke bahan yang lebih
    dulu masuk. Selisih dari berat snapshot yang tidak punya jejak jenis
    disimpan sebagai `belum_dikenal`, bukan ditebak sebagai PK.
    """
    from datetime import datetime, timezone

    from app.models import (BerasKeSilo, BrokenKeSilo, HasilSampingKeSilo,
                            PolishingProcess, PolishingSiloUsage,
                            PkGudang2Intake, PkTumpukanToSilo)
    from app.penggilingan.inventory.models import OutgoingItem, OutgoingRecord

    # (waktu, prioritas, jenis, berat). Pada waktu yang sama, konsumsi terjadi
    # sebelum pemasukan baru, sama dengan aturan batas isi di _isian_silo.
    gerak: list[tuple[datetime, int, str, float]] = []

    def tambah(waktu, jenis: str, berat, *, masuk: bool = True) -> None:
        if waktu is None:
            return
        saat = waktu if waktu.tzinfo else waktu.replace(tzinfo=timezone.utc)
        batas = sampai
        if batas is not None and batas.tzinfo is None:
            batas = batas.replace(tzinfo=timezone.utc)
        if batas is not None and saat > batas:
            return
        kg = float(berat or 0)
        if kg > 0.001:
            gerak.append((saat, 1 if masuk else 0, jenis, kg if masuk else -kg))

    # PK bisa masuk langsung atau dari tumpukan. Baris intake dari tumpukan
    # tidak punya silo_id, sehingga hanya gerak pindahnya yang dihitung.
    for r in (await db.execute(select(PkGudang2Intake).where(
        PkGudang2Intake.silo_id == silo_id,
        PkGudang2Intake.dibatalkan_pada.is_(None),
    ))).scalars().all():
        tambah(r.waktu_masuk, "pk", r.berat_kg)
    for r in (await db.execute(select(PkTumpukanToSilo).where(
        PkTumpukanToSilo.silo_id == silo_id,
    ))).scalars().all():
        tambah(r.waktu, "pk", r.berat_kg)
    for r in (await db.execute(select(BerasKeSilo).where(
        BerasKeSilo.silo_id == silo_id,
    ))).scalars().all():
        tambah(r.waktu, "beras_putih", r.berat_kg)
    for r in (await db.execute(select(BrokenKeSilo).where(
        BrokenKeSilo.silo_id == silo_id,
    ))).scalars().all():
        tambah(r.waktu, "broken", r.berat_kg)
    for r in (await db.execute(select(HasilSampingKeSilo).where(
        HasilSampingKeSilo.silo_id == silo_id,
    ))).scalars().all():
        jenis = str(r.jenis or "").strip().lower()
        tambah(r.waktu, jenis if jenis in {"menir", "reject"} else "belum_dikenal",
               r.berat_kg)

    # Pengambilan PK dari silo.
    for r, out in (await db.execute(
        select(OutgoingItem, OutgoingRecord)
        .join(OutgoingRecord, OutgoingRecord.id == OutgoingItem.outgoing_record_id)
        .where(OutgoingItem.item_type == "pk_g2",
               OutgoingItem.silo_id == silo_id)
    )).all():
        tambah(out.waktu, "pk", r.berat_kg, masuk=False)

    # Pembebasan tiap siklus mengurangi bahan lama, meskipun mesin masih berjalan.
    for u, pr in (await db.execute(
        select(PolishingSiloUsage, PolishingProcess)
        .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.silo_id == silo_id,
               PolishingSiloUsage.berat_akhir_kg.is_not(None),
               *([PolishingProcess.id != kecuali_proses_id]
                 if kecuali_proses_id is not None else []))
    )).all():
        tambah(u.updated_at or pr.waktu_selesai or pr.waktu_mulai, "*",
               u.berat_terpakai_kg, masuk=False)

    urut = sorted(gerak, key=lambda x: (x[0], x[1]))
    lot: list[list[float | str]] = []
    for _, _, jenis, delta in urut:
        if delta > 0:
            lot.append([jenis, delta])
            continue
        sisa = -delta
        for baris in lot:
            if baris[1] <= 0 or (jenis != "*" and baris[0] != jenis):
                continue
            ambil = min(float(baris[1]), sisa)
            baris[1] = float(baris[1]) - ambil
            sisa -= ambil
            if sisa <= 0.001:
                break
        if sisa > 0.001:
            lot.insert(0, ["belum_dikenal", -sisa])

    hasil = {k: 0.0 for k in ("pk", "beras_putih", "broken", "menir", "reject",
                               "belum_dikenal")}
    for jenis, kg in lot:
        hasil[str(jenis)] = hasil.get(str(jenis), 0.0) + float(kg)
    for jenis in hasil:
        hasil[jenis] = max(0.0, hasil[jenis])
    if target_kg is not None:
        selisih = float(target_kg) - sum(hasil.values())
        if selisih > 0.01:
            hasil["belum_dikenal"] += selisih
        elif selisih < -0.01:
            # Data lama atau jejak pemakaian parsial dapat membuat jumlah
            # jejak lebih besar dari snapshot. Potong dahulu bagian yang
            # belum diketahui, lalu kurangi saldo lama FIFO agar total yang
            # ditampilkan tetap sama dengan berat silo yang benar-benar dipakai.
            lebih = -selisih
            for jenis in ("belum_dikenal", "pk", "beras_putih", "broken", "menir", "reject"):
                ambil = min(hasil[jenis], lebih)
                hasil[jenis] -= ambil
                lebih -= ambil
                if lebih <= 0.01:
                    break
    return hasil


_SEMUA_PEMILIK_TUMPUKAN = object()


async def hitung_stok_tumpukan(db: AsyncSession, *,
                               pemilik: str = "semua",
                               jasa_id=_SEMUA_PEMILIK_TUMPUKAN) -> float:
    """Stok tumpukan G2 = masuk sbg tumpukan − dipindah ke silo − diambil keluar.

    `pemilik` bawaannya "semua" — isi FISIK lantainya, dan itu yang benar untuk
    penjaga kapasitas: lantai tak peduli milik siapa barang yang berdiri di
    atasnya. "pabrik" untuk pertanyaan milik, "jasa" untuk titipannya yang
    disebut di sebelahnya. Lihat `hitung_stok_silo`.

    Suku KETIGA (`keluar`), lahir bersamaan dengan jalur pengambilan PK
    Gudang 2 (pesan kerja 7 Oktober 2026, butir 4 — migrasi 0076):
    `outgoing_items.silo_id IS NULL` menandai PK yang diambil DARI TUMPUKAN
    (bukan "tak diisi" — lihat docstring kolomnya), jadi syaratnya `IS NULL`
    SEKALIGUS `item_type="pk_g2"`, bukan salah satu saja — tanpa yang kedua
    baris finished_goods/byproduct_curah/pk_langsung (yang `silo_id`-nya
    juga selalu NULL) akan ikut terjumlah ke sini.
    """
    if pemilik == "semua" and jasa_id is _SEMUA_PEMILIK_TUMPUKAN:
        # Sama seperti isi silo, pembulatan/toleransi pemilik A tak boleh
        # mengurangi stok fisik milik B yang berada di tumpukan yang sama.
        return (await hitung_stok_tumpukan(db, pemilik="pabrik")
                + await hitung_stok_tumpukan(db, pemilik="jasa"))

    syarat = [PkGudang2Intake.tujuan == DITUMPUK]
    syarat_keluar = [OutgoingItem.item_type == "pk_g2", OutgoingItem.silo_id.is_(None)]
    if jasa_id is not _SEMUA_PEMILIK_TUMPUKAN:
        syarat.append(PkGudang2Intake.jasa_id.is_(None) if jasa_id is None else PkGudang2Intake.jasa_id == jasa_id)
        syarat_keluar.append(OutgoingItem.jasa_id.is_(None) if jasa_id is None else OutgoingItem.jasa_id == jasa_id)
    elif pemilik != "semua":
        syarat.append(PkGudang2Intake.jasa_id.is_(None) if pemilik == "pabrik" else PkGudang2Intake.jasa_id.isnot(None))
        syarat_keluar.append(OutgoingItem.jasa_id.is_(None) if pemilik == "pabrik" else OutgoingItem.jasa_id.isnot(None))
    intakes = (await db.execute(select(PkGudang2Intake).where(*syarat))).scalars().all()
    saldo = await sisa_tumpukan_banyak(db, intakes)
    keluar = await db.scalar(select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0)).where(*syarat_keluar))
    return max(0.0, float(sum((v or Decimal(0) for v in saldo.values()), Decimal(0))) - float(keluar))


async def sisa_tumpukan_banyak(db: AsyncSession, intakes) -> dict[int, Decimal | None]:
    """Satu pembacaan terkelompok: sisa karung dahulu, satu pembagian di ujung.

    Kg hasil timbang tetap dikurangkan terpisah. Tidak menjumlah kg karung
    yang pernah dibulatkan, dan tidak meminjam R partai tetangganya.
    """
    ids = [i.id for i in intakes]
    if not ids:
        return {}
    gerak = dict((r[0], (int(r[1]), Decimal(str(r[2])))) for r in (await db.execute(
        select(PkTumpukanToSilo.pk_gudang2_intake_id,
               func.coalesce(func.sum(PkTumpukanToSilo.jumlah_karung), 0),
               func.coalesce(func.sum(PkTumpukanToSilo.berat_timbang_kg), 0))
        .where(PkTumpukanToSilo.pk_gudang2_intake_id.in_(ids))
        .group_by(PkTumpukanToSilo.pk_gudang2_intake_id))).all())
    penyesuaian = dict((await db.execute(select(PkPenyesuaianStok.intake_id,
        func.sum(PkPenyesuaianStok.selisih_kg)).where(PkPenyesuaianStok.intake_id.in_(ids))
        .group_by(PkPenyesuaianStok.intake_id))).all())
    batch_ids = [i.pk_purchase_batch_id for i in intakes if i.pk_purchase_batch_id]
    batches = {b.id: b for b in (await db.execute(select(PkPurchaseBatch).where(
        PkPurchaseBatch.id.in_(batch_ids)))).scalars().all()} if batch_ids else {}
    hasil = {}
    for i in intakes:
        k, kg = gerak.get(i.id, (0, Decimal(0)))
        batch = batches.get(i.pk_purchase_batch_id)
        r = bobot_per_karung(batch)
        if batch is not None and batch.jumlah_karung:
            hasil[i.id] = (-kg if batch.jumlah_karung == k else None if r is None
                           else bobot_per_karung(batch, jumlah=batch.jumlah_karung - k) - kg)
        else:
            hasil[i.id] = None if i.berat_kg is None else Decimal(str(i.berat_kg)) - kg + Decimal(str(penyesuaian.get(i.id, 0)))
    return hasil


async def sesuaikan_stok_pk_lama(db, *, user, intake_id: int, selisih_kg, alasan: str, tanggal):
    if user.role not in PERAN_ADMIN_KEATAS:
        raise Gudang2Error("Penyesuaian stok hanya boleh dicatat Admin ke atas.")
    selisih = Decimal(str(selisih_kg))
    if not selisih.is_finite() or selisih == 0 or not (alasan or "").strip() or tanggal is None:
        raise Gudang2Error("Isi tanggal, alasan, dan selisih kg yang bukan nol.")
    it = (await db.scalars(select(PkGudang2Intake).where(
        PkGudang2Intake.id == intake_id).with_for_update())).first()
    if it is None or it.tujuan != DITUMPUK or not it.pk_purchase_batch_id:
        raise Gudang2Error("Pilih tumpukan PK beli luar lama yang akan disesuaikan.")
    batch = await db.get(PkPurchaseBatch,it.pk_purchase_batch_id)
    if batch.jumlah_karung:
        raise Gudang2Error("Batch berkarung mengikuti bobot tiket terkini; penyesuaian ini khusus batch lama tanpa jumlah karung.")
    saldo = await _sisa_tumpukan_intake(db,it.id)
    if saldo is None or Decimal(str(saldo)) + selisih < 0:
        raise Gudang2Error("Penyesuaian tidak boleh membuat saldo tumpukan negatif.")
    now = input_time(tanggal)
    row = PkPenyesuaianStok(intake_id=it.id,selisih_kg=selisih,
        tanggal=now.date(),waktu=now,alasan=alasan.strip(),input_by=user.id)
    db.add(row)
    await db.flush()
    await log_activity(db,table_name="pk_penyesuaian_stok",record_id=row.id,action="INSERT",
        changed_by=user.id,gudang="g2",alasan=row.alasan,new_value=f"{batch.kode_batch}: {selisih:+} kg, tanggal {row.tanggal}")
    await db.commit()
    return row


async def _sisa_tumpukan_intake(db: AsyncSession, intake_id: int) -> float:
    """Sisa PK sebuah intake tumpukan yang belum dipindah ke silo."""
    intake = await db.get(PkGudang2Intake, intake_id)
    if intake is None:
        raise Gudang2Error("Data tumpukan tidak ditemukan.")
    nilai = (await sisa_tumpukan_banyak(db, [intake]))[intake.id]
    return await _sisa_karung_setelah_keluar(db,intake,nilai)


async def ringkasan_karung(db, intake, sisa_kg=None):
    from app.penggilingan.gudang2.karung import teks_kg
    batch = await db.get(PkPurchaseBatch, intake.pk_purchase_batch_id) if intake.pk_purchase_batch_id else None
    if not batch or not batch.jumlah_karung:
        return None
    k = await db.scalar(select(func.coalesce(func.sum(PkTumpukanToSilo.jumlah_karung), 0))
        .where(PkTumpukanToSilo.pk_gudang2_intake_id == intake.id))
    if sisa_kg is None:
        sisa_kg = await _sisa_tumpukan_intake(db, intake.id)
    from app.penggilingan.gudang2.karung import teks_sisa_karung
    return teks_sisa_karung(batch,sisa_kg,batch.jumlah_karung - int(k))


# `hitung_hpp_wavg_silo` DIBUANG 28 September 2026 — lihat catatan di
# `stok_pk_g2`. Satu-satunya pembaca lainnya `hitung_hpp_beras`, yang juga
# dibuang. `pk_gudang2_intakes.hpp_per_kg` TIDAK dijatuhkan: baris lama memuat
# angka sungguhan, dan itu riwayat.


# ─────────────────────────── Beli PK luar ───────────────────────────
@dataclass
class PkPurchaseResult:
    batch: PkPurchaseBatch
    supplier_nama: str
    supplier_created: bool


JENIS_PK_LUAR = {"ks", "kl", "campuran", "semi_ks"}
_JENIS_PK_LABEL = {"ks": "KS", "kl": "KL", "campuran": "Campuran", "semi_ks": "Semi KS"}


def norm_jenis_pk(v: str | None) -> str | None:
    """Normalisasi jenis PK luar → ks/kl/campuran/semi_ks; None bila tak dikenali."""
    if not v:
        return None
    s = v.lower().strip().replace("-", " ").replace("_", " ")
    if s in ("semi ks", "semi", "semiks"):
        return "semi_ks"
    if s in ("campuran", "campur", "mix", "mixed"):
        return "campuran"
    if s == "ks":
        return "ks"
    if s == "kl":
        return "kl"
    return None


async def create_pk_purchase(
    db: AsyncSession, *, user: User, nama_supplier: str | None, berat_kg: float | None,
    jenis_pk: str | None = None, kadar_air: float | None = None,
    no_polisi: str | None = None, tanggal: date | None = None, jam: time | None = None,
) -> PkPurchaseResult:
    """Catat PK dari luar yang MASUK (Gudang 2). PK yang masuk = PASTI diterima
    (tak ada penolakan). Selanjutnya: input KUALITAS (properti batch) & verifikasi
    HARGA — dua langkah terpisah, kapan saja, oleh staff/admin (seperti gabah G1).

    Master §2: input PK dari luar = STAFF/ADMIN saja (bukan operator).
    Wajib: supplier, berat, plat truk, jenis PK (ks/kl/campuran/semi_ks).
    """
    if user.role not in PERAN_ADMIN_KEATAS:
        raise Gudang2Error(
            "🔒 Input PK dari luar (+ QC) hanya bisa dilakukan oleh Staff/Admin."
        )
    if not nama_supplier:
        raise Gudang2Error("Sebutkan supplier PK-nya, contoh: `beli PK dari pak andi 5 ton`")
    if not berat_kg:
        raise Gudang2Error("Sebutkan berat PK-nya (mis. `5 ton`).")
    if not no_polisi:
        raise Gudang2Error("Sebutkan plat nomor truk pengirim PK.")
    jenis = norm_jenis_pk(jenis_pk)
    if jenis is None:
        raise Gudang2Error("Sebutkan jenis PK: KS, KL, Campuran, atau Semi KS.")
    now = input_time(tanggal, jam)  # BackdateError bila di masa depan
    try:
        armada = await armada_dari_nomor_polisi(db, no_polisi)
    except ValueError as e:
        raise Gudang2Error(str(e)) from e
    supplier, created = await find_or_create_supplier(db, nama_supplier)
    kode = await next_pk_purchase_code(db, now.date())
    batch = PkPurchaseBatch(
        kode_batch=kode, supplier_id=supplier.id, berat_total_kg=berat_kg,
        no_polisi_truk=armada.nomor_polisi if armada else no_polisi,
        jenis_pk=jenis, kadar_air_awal_persen=kadar_air,
        armada_id=armada.id if armada else None,
        tanggal_pembelian=now.date(), waktu_pembelian=now, input_by=user.id,
        # PK masuk = pasti diterima. flag_unverified = harga belum diverifikasi.
        status_batch="diterima", flag_unverified=True,
    )
    db.add(batch)
    await db.flush()
    await log_activity(
        db, table_name="pk_purchase_batches", record_id=batch.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {supplier.nama_supplier} | {berat_kg:.0f}kg PK luar",
    )
    await create_notification(
        db, tipe="verifikasi_pk_luar",
        pesan=(
            f"🟡 PK luar {kode} ({supplier.nama_supplier}, {berat_kg:.0f} kg) MASUK "
            "— menunggu input kualitas & verifikasi harga."
        ),
        target_role="admin", prioritas="kuning",
        table_name="pk_purchase_batches", record_id=batch.id,
    )
    await db.commit()
    await db.refresh(batch)
    return PkPurchaseResult(batch=batch, supplier_nama=supplier.nama_supplier,
                            supplier_created=created)


async def create_pk_purchase_dari_timbang(
    db: AsyncSession, *, user: User, timbangan_transaksi_id: int, jenis_pk: str | None,
    kadar_air: float | None = None, tanggal: date | None = None, jam: time | None = None,
    kunci_kiriman: str | None = None,
    jumlah_karung: int | None = None, ukuran_karung_kg: Decimal | None = None,
) -> PkPurchaseResult:
    """Catat PK luar MASUK DARI tiket TIMBANG (jenis BERAS_PK). Supplier/bobot/nopol dari
    timbang — hanya pilih tiket + jenis PK (timbang tak membedakan ks/kl/dst). STAFF/ADMIN
    saja. Bobot boleh belum ada ('menunggu') → disinkron dari tiket. Referensi bobot = tiket.

    **Jalur PERISTIWA (Tahap 3, aksi kedua)** — persis kembaran gabah masuk:
    kunci tiket → nomor atomik → peristiwa `pk_luar_masuk` (kunci kiriman
    idempoten) → `proyeksi_pk_luar_masuk` → cermin `pk_purchase_batches` →
    jejak & notifikasi → commit. Gagal di mana pun = tak ada yang tersimpan.
    """
    if jumlah_karung is not None and (isinstance(jumlah_karung, bool) or int(jumlah_karung) != jumlah_karung or jumlah_karung <= 0):
        raise Gudang2Error("Jumlah karung surat jalan harus bilangan bulat lebih dari nol.")
    if ukuran_karung_kg is not None and (not Decimal(str(ukuran_karung_kg)).is_finite() or ukuran_karung_kg <= 0):
        raise Gudang2Error("Ukuran nominal karung harus lebih dari nol.")
    if user.role not in PERAN_ADMIN_KEATAS:
        raise Gudang2Error("🔒 Input PK dari luar hanya bisa oleh Staff/Admin.")
    jenis = norm_jenis_pk(jenis_pk)
    if jenis is None:
        raise Gudang2Error("Pilih jenis PK: KS, KL, Campuran, atau Semi KS.")
    # Kunci dulu, baru baca — lihat alasannya di `kunci_tiket_untuk_ditaut`.
    try:
        await kunci_tiket_untuk_ditaut(db, timbangan_transaksi_id)
    except TiketSudahDipakai as e:
        raise Gudang2Error(str(e))
    tiket = await ambil_tiket(db, timbangan_transaksi_id)
    if tiket is None:
        raise Gudang2Error(
            "Tiket timbang tidak ditemukan atau sudah dibatalkan/ditutup paksa."
        )
    if tiket.get("arah") != "MASUK":
        raise Gudang2Error("Tiket timbang bukan barang MASUK.")
    info = intake_dari_jenis(tiket.get("jenis_kode", ""))
    if info is None or info.model != "pk":
        raise Gudang2Error("Tiket ini bukan PK masuk.")

    # Tiga keadaan (QA P6, 21 September 2026): pasti / perkiraan dari tara
    # truk yang sama / tak diketahui. Lihat `bobot_awal_dari_tiket`.
    tiket_bobot = dict(tiket)
    if jumlah_karung is not None:
        # Nota karung bukan W. Bobot yang belum ada tetap memakai mekanisme
        # perkiraan dari tara truk; tidak ditetapkan pasti dari surat jalan.
        real = next((v for v in (tiket.get("berat_barang_kg"), tiket.get("netto_timbangan_kg"))
                     if v is not None and float(v) > 0), None)
        tiket_bobot["berat_hpp_kg"] = real
        tiket_bobot["sumber_berat"] = "timbangan"
    berat, sumber, berat_perkiraan = await bobot_awal_dari_tiket(db, tiket_bobot)
    ada_bobot = berat is not None

    now = input_time(tanggal, jam)
    # ── DIBELI atau DITITIPKAN — dan cabang jasa HARUS lebih dulu ──
    #
    # Cabang lama di bawah berbunyi "tak ada supplier_id → CARI ATAU BUAT dari
    # nama pihak", dan tiket jasa memang tak punya `supplier_id`. Tanpa cabang
    # ini, PK pelanggan jadi PEMBELIAN atas nama pemasok karangan bernama
    # pelanggan itu sendiri — lalu barang yang tak pernah dibeli ikut ke skor
    # pemasok, laporan pembelian, dan HPP, sementara pemiliknya hilang.
    #
    # Sampai migrasi 0065 jalur ini MENOLAK tiket jasa terang-terangan, justru
    # karena `pk_purchase_batches` belum punya tempat menyimpan pemiliknya.
    # Sekarang ada, jadi penolakannya dicabut dan jalurnya dibuka.
    jasa_ini: Jasa | None = None
    jasa_baru = False
    supplier: Supplier | None = None
    created = False
    if adalah_jasa(tiket):
        pass                      # pesanannya dibuat sesudah pemeriksaan ulang
    elif tiket.get("supplier_id"):
        supplier = await db.get(Supplier, tiket["supplier_id"])
    else:
        nama = tiket.get("nama_supplier") or tiket.get("pihak_nama") or "Tanpa Nama"
        supplier, created = await find_or_create_supplier(db, nama)

    def _sebut() -> str:
        """Nama pihak untuk kalimat & jejak — pemasok, atau PEMILIKNYA."""
        if supplier is not None:
            return supplier.nama_supplier
        return (f"JASA {jasa_ini.kode} {tiket.get('nama_pelanggan') or ''}".strip()
                if jasa_ini else "JASA")

    if kunci_kiriman:
        ada = await _pk_batch_dari_kunci(db, kunci_kiriman)
        if ada is not None:
            return PkPurchaseResult(batch=ada, supplier_nama=_sebut(), supplier_created=False)
    else:
        urutan = await buku.jumlah_jenis(db, PK_LUAR_MASUK, "timbangan_transaksi_id",
                                         timbangan_transaksi_id)
        kunci_kiriman = f"{PK_LUAR_MASUK}:tiket:{timbangan_transaksi_id}:{urutan + 1}"

    # Pesanan jasa dibuat SESUDAH pemeriksaan kiriman ulang di atas dan SEBELUM
    # peristiwanya dicatat: muatan buku besar menyebut kodenya, dan buku besar
    # itu tambah-saja — kode yang menyusul tak bisa ditambalkan ke sana.
    if adalah_jasa(tiket):
        jasa_ini, jasa_baru = await pesanan_jasa_dari_tiket(db, user=user, tiket=tiket)

    kode = await next_pk_purchase_code(db, now.date())
    muatan = {
        "kode_batch": kode, "timbangan_transaksi_id": timbangan_transaksi_id,
        "tiket_kode": tiket.get("kode"),
        "supplier_id": supplier.id if supplier else None,
        "nama_supplier": supplier.nama_supplier if supplier else None,
        # Pemiliknya ikut ke buku besar berikut NAMANYA: muatan peristiwa tak
        # boleh bergantung pada tabel lain untuk bisa dibaca.
        "jasa_id": jasa_ini.id if jasa_ini else None,
        "jasa_kode": jasa_ini.kode if jasa_ini else None,
        "pelanggan_id": tiket.get("pelanggan_id"),
        "nama_pelanggan": tiket.get("nama_pelanggan"),
        "berat_kg": berat, "sumber_berat": sumber,
        "jumlah_karung": jumlah_karung, "ukuran_karung_kg": ukuran_karung_kg,
        "jenis_pk": jenis, "kadar_air": kadar_air, "no_polisi": tiket.get("nomor_polisi"),
        "tanggal": now.date(), "waktu": now,
    }
    try:
        e = await buku.catat(db, jenis=PK_LUAR_MASUK, pelaku_id=user.id, kunci_kiriman=kunci_kiriman,
                             muatan=muatan, waktu=now)
    except IntegrityError as e_:
        raise Gudang2Error(_pesan_integritas(e_, "proyeksi_pk_luar_masuk", kode))
    if not e.baru:
        ada = await _pk_batch_dari_kunci(db, kunci_kiriman)
        if ada is not None:
            return PkPurchaseResult(batch=ada, supplier_nama=_sebut(), supplier_created=False)

    armada = await armada_dari_nomor_polisi(db, tiket.get("nomor_polisi"), dari_tiket_lama=True)

    # Cermin untuk layar & laporan lama, ditambah penunjuk ke peristiwanya.
    batch = PkPurchaseBatch(
        # TEPAT SATU dari keduanya — `ck_pk_purchase_batches_beli_atau_jasa`.
        kode_batch=kode, supplier_id=supplier.id if supplier else None,
        jasa_id=jasa_ini.id if jasa_ini else None, berat_total_kg=berat,
        jumlah_karung=jumlah_karung, ukuran_karung_kg=ukuran_karung_kg,
        no_polisi_truk=armada.nomor_polisi if armada else tiket.get("nomor_polisi"),
        jenis_pk=jenis, kadar_air_awal_persen=kadar_air,
        armada_id=armada.id if armada else None,
        tanggal_pembelian=now.date(), waktu_pembelian=now, input_by=user.id,
        status_batch="diterima", flag_unverified=True,
        timbangan_transaksi_id=timbangan_transaksi_id, sumber_berat=sumber,
        berat_perkiraan_kg=berat_perkiraan,
        peristiwa_id=e.id,
    )
    db.add(batch)
    try:
        await db.flush()
    except IntegrityError as e_:
        await db.rollback()
        raise Gudang2Error(_pesan_integritas(e_, "pk_purchase_batches", kode))
    getattr(e, "proyeksi", None) and setattr(e.proyeksi, "pk_purchase_batch_id", batch.id)

    b_str = f"{berat:.0f}kg ({sumber})" if ada_bobot else "menunggu bobot"
    await log_activity(
        db, table_name="pk_purchase_batches", record_id=batch.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {_sebut()} | {b_str} PK {jenis} | timbang {tiket['kode']}",
    )
    await create_notification(
        db, tipe="verifikasi_pk_luar",
        pesan=(f"🟡 PK luar {kode} ({_sebut()}, {b_str}, {jenis}, "
               f"dari timbang {tiket['kode']}) MASUK — menunggu QC & verifikasi harga."),
        target_role="admin", prioritas="kuning",
        table_name="pk_purchase_batches", record_id=batch.id,
    )
    if jasa_baru and jasa_ini is not None:
        jasa_ini.peristiwa_id = e.id
    await db.commit()
    await db.refresh(batch)
    return PkPurchaseResult(batch=batch, supplier_nama=_sebut(),
                            supplier_created=created)


@dataclass
class PkRejectionResult:
    batch: PkPurchaseBatch
    rejection: PkRejection
    pihak_nama: str
    #: True bila tiket timbangnya ikut ditutup paksa. False berarti tiketnya
    #: sudah tak TERBUKA lagi (sudah selesai timbang kedua secara normal, atau
    #: sudah ditutup lebih dulu) — bukan kegagalan, cuma tak ada yang perlu
    #: ditutup lagi.
    tiket_ditutup: bool


async def create_pk_rejection_dari_timbang(
    db: AsyncSession, *, user: User, timbangan_transaksi_id: int, alasan: str,
    tanggal: date | None = None, jam: time | None = None,
) -> PkRejectionResult:
    """Tolak PK luar SAAT DATANG — ditimbang, tapi tak diterima, dan kembali
    ke truknya. Keputusan pemilik 4 Oktober 2026, borang yang sama dengan
    `catat_pk_luar`: satu tombol "Terima" (→ `create_pk_purchase_dari_timbang`
    lalu `masukkan_pk_luar`), satu tombol "Tolak" — di sini.

    ⚠ TAK LEWAT JALUR PERISTIWA (beda dari kembarannya di atas). PK yang
    DITERIMA mengubah stok — itu yang dijaga peristiwa/proyeksi/undo. PK yang
    DITOLAK tidak pernah jadi stok; `pk_rejections` cuma register "truk apa,
    berapa kg, kenapa ditolak" untuk laporan, dan `kunci_tiket_untuk_ditaut`
    sendiri sudah cukup menjaga tiket yang sama tak diproses dua kali —
    sama seperti keputusan tiket "diterima" dijaga di sana.

    ⚠ Tabel & kolomnya (`pk_rejections`, `alasan_tolak`) sudah ada sejak
    migrasi 0012 (5 Juli 2026) tetapi TAK PERNAH dipakai — diimpor, tak
    sekali pun diinstansiasi. Fungsi ini pemakai pertamanya.

    Satu-satunya yang wajib diisi `alasan` — jenis PK & kadar air TIDAK
    ditanya, sebab PK yang ditolak tak pernah jadi stok yang perlu diklasifikasi.

    ⚠⚠ IKUT MENUTUP PAKSA TIKET TIMBANGNYA (keputusan pemilik 4 Oktober 2026,
    MENGESAMPINGKAN Temuan QA T-15 di repo timbangan — lihat `timbang_link.
    tutup_paksa_pk_ditolak`). Timbangan sendiri menolak menutup paksa tiket
    hanya karena muatannya ditolak, sebab truk yang ditolak tetap wajib lewat
    timbangan keluar untuk kontrol masuk−keluar. Pemilik sadar melepas kontrol
    itu KHUSUS untuk kasus ini."""
    if user.role not in PERAN_ADMIN_KEATAS:
        raise Gudang2Error("🔒 Input PK dari luar hanya bisa oleh Staff/Admin.")
    if not (alasan or "").strip():
        raise Gudang2Error("Sebutkan alasan menolaknya.")
    # Kunci dulu, baru baca — lihat alasannya di `kunci_tiket_untuk_ditaut`.
    # Kuncinya SAMA dengan jalur terima: tiket yang sudah DITOLAK pun
    # terbaca "sudah dipakai" bagi percobaan kedua, sebab baris penandanya
    # tetap `pk_purchase_batches` — satu-satunya tabel yang diperiksa di sana.
    try:
        await kunci_tiket_untuk_ditaut(db, timbangan_transaksi_id)
    except TiketSudahDipakai as e:
        raise Gudang2Error(str(e))
    tiket = await ambil_tiket(db, timbangan_transaksi_id)
    if tiket is None:
        raise Gudang2Error(
            "Tiket timbang tidak ditemukan atau sudah dibatalkan/ditutup paksa."
        )
    if tiket.get("arah") != "MASUK":
        raise Gudang2Error("Tiket timbang bukan barang MASUK.")
    info = intake_dari_jenis(tiket.get("jenis_kode", ""))
    if info is None or info.model != "pk":
        raise Gudang2Error("Tiket ini bukan PK masuk.")

    berat, sumber, berat_perkiraan = await bobot_awal_dari_tiket(db, tiket)
    now = input_time(tanggal, jam)

    # Pemiliknya tetap disebut sebagai jejak — lihat catatan jasa di
    # `create_pk_purchase_dari_timbang`, alasan yang sama berlaku di sini:
    # barang jasa yang ditolak bukan pembelian, dan nama pelanggannya harus
    # tetap terbaca, bukan tersamar jadi pemasok karangan.
    jasa_ini: Jasa | None = None
    supplier: Supplier | None = None
    if adalah_jasa(tiket):
        jasa_ini, _ = await pesanan_jasa_dari_tiket(db, user=user, tiket=tiket)
    elif tiket.get("supplier_id"):
        supplier = await db.get(Supplier, tiket["supplier_id"])
    else:
        nama = tiket.get("nama_supplier") or tiket.get("pihak_nama") or "Tanpa Nama"
        supplier, _ = await find_or_create_supplier(db, nama)
    pihak_nama = (supplier.nama_supplier if supplier else
                 f"JASA {jasa_ini.kode} {tiket.get('nama_pelanggan') or ''}".strip())
    armada = await armada_dari_nomor_polisi(db, tiket.get("nomor_polisi"), dari_tiket_lama=True)

    kode = await next_pk_purchase_code(db, now.date())
    batch = PkPurchaseBatch(
        kode_batch=kode, supplier_id=supplier.id if supplier else None,
        jasa_id=jasa_ini.id if jasa_ini else None, berat_total_kg=berat,
        no_polisi_truk=armada.nomor_polisi if armada else tiket.get("nomor_polisi"),
        jenis_pk=None, armada_id=armada.id if armada else None,
        tanggal_pembelian=now.date(), waktu_pembelian=now, input_by=user.id,
        # Ditolak = tak pernah jadi stok. `flag_unverified` tak berarti apa
        # pun di sini (tak ada harga yang menunggu verifikasi), tapi False
        # supaya layar lama yang menyaringnya tak ikut menagih batch ini.
        status_batch="ditolak", flag_unverified=False,
        timbangan_transaksi_id=timbangan_transaksi_id, sumber_berat=sumber,
        berat_perkiraan_kg=berat_perkiraan,
    )
    db.add(batch)
    try:
        await db.flush()
    except IntegrityError as e_:
        await db.rollback()
        raise Gudang2Error(_pesan_integritas(e_, "pk_purchase_batches", kode))

    kode_rej = await next_rejection_code(db, now.date())
    rejection = PkRejection(
        kode=kode_rej, pk_purchase_batch_id=batch.id,
        berat_kg=berat or 0, no_polisi_truk=tiket.get("nomor_polisi"),
        alasan=alasan.strip(), tanggal=now.date(), waktu=now, created_by=user.id,
    )
    db.add(rejection)
    await db.flush()

    b_str = f"{berat:.0f}kg ({sumber})" if berat is not None else "bobot belum diketahui"
    await log_activity(
        db, table_name="pk_rejections", record_id=rejection.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode_rej} | batch {kode} | {pihak_nama} | {b_str} | {alasan.strip()}",
    )
    await create_notification(
        db, tipe="pk_luar_ditolak",
        pesan=(f"⛔ PK luar {kode_rej} ({pihak_nama}, {b_str}, dari timbang "
               f"{tiket['kode']}) DITOLAK — {alasan.strip()}"),
        target_role="admin", prioritas="kuning",
        table_name="pk_rejections", record_id=rejection.id,
    )
    # Tiketnya sudah TERKUNCI `FOR UPDATE` sejak `kunci_tiket_untuk_ditaut` di
    # atas, dalam transaksi yang SAMA — jadi ditutup di sini, bukan sesudah
    # commit, supaya batch ini dan penutupan tiketnya gagal/berhasil bersama.
    ditutup = await tutup_paksa_pk_ditolak(db, tid=timbangan_transaksi_id,
                                           alasan=alasan.strip())
    await db.commit()
    await db.refresh(batch)
    await db.refresh(rejection)
    return PkRejectionResult(batch=batch, rejection=rejection, pihak_nama=pihak_nama,
                             tiket_ditutup=ditutup)


async def _pk_batch_dari_kunci(db: AsyncSession, kunci_kiriman: str) -> PkPurchaseBatch | None:
    """Cermin batch PK dari peristiwa berkunci ini — untuk kiriman ulang."""
    from app.models import Peristiwa

    return (await db.execute(
        select(PkPurchaseBatch).join(Peristiwa, Peristiwa.id == PkPurchaseBatch.peristiwa_id)
        .where(Peristiwa.kunci_kiriman == kunci_kiriman)
    )).scalars().first()


@dataclass
class PkQcResult:
    batch: PkPurchaseBatch
    kadar_air: float | None
    broken: float | None
    penyusutan: float | None
    butir_kuning: str | None
    gabah: str | None
    merang: str | None
    qc_count: int = 0


class PkPriceResult:
    batch: PkPurchaseBatch
    berat_bersih_kg: float
    total_biaya: float | None
    hpp_per_kg: float | None


async def _get_or_make_pk_verif(db: AsyncSession, batch_id: int) -> PkPurchaseVerification:
    verif = (
        await db.execute(
            select(PkPurchaseVerification).where(
                PkPurchaseVerification.pk_purchase_batch_id == batch_id
            )
        )
    ).scalars().first()
    if verif is None:
        verif = PkPurchaseVerification(pk_purchase_batch_id=batch_id, keputusan="terima")
        db.add(verif)
    return verif


async def segarkan_qc_pk_luar(db: AsyncSession, batch_id: int):
    """Snapshot dibaca stok lama; riwayat dan angka sumber tetap dari log QC."""
    from app.models import PkPurchaseQcLog
    from app.services.mutu_pk import ringkasan_banyak
    await db.flush()
    peta = await ringkasan_banyak(db, PkPurchaseQcLog,
                                 PkPurchaseQcLog.pk_purchase_batch_id, [batch_id])
    rata = peta.get(batch_id, {})
    verif = await _get_or_make_pk_verif(db, batch_id)
    for medan, sumber in (("kadar_air", "kadar_air"), ("broken_persen", "broken"),
                           ("penyusutan_persen", "susut"), ("butir_kuning", "butir_kuning"),
                           ("gabah", "gabah"), ("merang", "merang"), ("catatan_lab", "catatan_lab")):
        setattr(verif, medan, rata.get(sumber))
    return rata


async def log_pk_qc(
    db: AsyncSession, *, user: User, kode: str,
    kadar_air: float | None = None, broken: float | None = None,
    penyusutan_persen: float | None = None, butir_kuning: str | None = None,
    gabah: str | None = None, merang: str | None = None,
    catatan_lab: str | None = None,
) -> PkQcResult:
    """Input KUALITAS PK luar (uji lab) sebagai PROPERTI batch — bukan keputusan.

    PK yang masuk sudah pasti diterima; ini mencatat kualitasnya (kadar air,
    broken%, penyusutan/bekatul lab%, butir kuning, gabah, merang, catatan).
    Staff/admin, kapan saja. MURNI pencatatan mutu — tak pernah mengubah
    stok atau bobot; lihat catatan panjang soal potongan bobot yang DIHAPUS
    pada migrasi yang membuang kolomnya dari `pk_purchase_verifications`.

    `gabah`/`merang` ditambahkan 5 Oktober 2026 (keputusan pemilik) —
    campuran gabah (belum terkupas) dan merang (jerami/malai) di PK, dinilai
    dengan skala kualitatif yang sama dengan butir kuning."""
    if user.role not in PERAN_ADMIN_KEATAS:
        raise Gudang2Error("🔒 Input kualitas PK luar hanya oleh Staff/Admin.")
    batch = (
        await db.execute(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == kode).with_for_update())
    ).scalars().first()
    if batch is None:
        raise Gudang2Error(f"PK luar {kode} tidak ditemukan.")
    from app.services.mutu_pk import wajib_kualitatif
    try:
        nilai = wajib_kualitatif(butir_kuning=butir_kuning, gabah=gabah, merang=merang)
    except ValueError as e:
        raise Gudang2Error(str(e)) from e
    butir_kuning, gabah, merang = (nilai[k] for k in ("butir_kuning", "gabah", "merang"))

    catatan_lab = catatan_lab.strip() if catatan_lab else None
    if catatan_lab and len(catatan_lab) > 255:
        raise Gudang2Error("Catatan lab maksimal 255 karakter.")
    from app.models import PkPurchaseQcLog
    from app.database import now_local
    log = PkPurchaseQcLog(pk_purchase_batch_id=batch.id, kadar_air=kadar_air,
                          broken_persen=broken, susut_persen=penyusutan_persen,
                          butir_kuning=butir_kuning, gabah=gabah, merang=merang,
                          catatan_lab=catatan_lab, waktu=now_local(), input_by=user.id)
    db.add(log)
    rata = await segarkan_qc_pk_luar(db, batch.id)
    verif = await _get_or_make_pk_verif(db, batch.id)
    verif.keputusan = "terima"  # PK masuk selalu diterima
    await log_activity(
        db, table_name="pk_purchase_qc_logs", record_id=log.id, action="INSERT",
        changed_by=user.id, field_name="qc",
        new_value=(f"ka={kadar_air} broken={broken} susut={penyusutan_persen} "
                  f"bk={butir_kuning} gabah={gabah} merang={merang}"),
    )
    await db.commit()
    await db.refresh(batch)
    return PkQcResult(batch=batch, kadar_air=kadar_air, broken=broken,
                      penyusutan=penyusutan_persen, butir_kuning=butir_kuning,
                      gabah=gabah, merang=merang, qc_count=rata.get("n", 0))


# `verify_pk_price` DIBUANG 28 September 2026: harga keluar dari Pos Produksi
# (keputusan pemilik). Ia dulu satu-satunya penulis `potongan_kg` — potongan
# BOBOT karena mutu, yang mengubah stok — dan sempat pindah ke `log_pk_qc`.
# Potongannya sendiri DIBUANG 4 Oktober 2026 (lihat migrasi yang menghapus
# `pk_purchase_verifications.potongan_kg`/`potongan_alasan`): basis data
# produksi tak pernah memuat satu baris pun berisi angka itu, dan bobot PK
# yang masuk Gudang 2 kini selalu sama dengan bobot tiket timbangnya.
#
# Akibat yang perlu diketahui pembaca berikutnya: `PkPurchaseBatch.
# flag_unverified` kini tak pernah kembali ke False, sebab tak ada lagi yang
# memverifikasi harga di sini. Kolomnya SENGAJA tak dibuang — ia riwayat
# pembelian sungguhan dan keuangan akan memintanya. Yang membacanya sebagai
# "belum dikerjakan" sudah dicabut (kartu meja, pemantau, daftar pilihan).


# ─────────────────────────── Intake ke silo/tumpukan ───────────────────────────
@dataclass
class IntakeResult:
    intake: PkGudang2Intake
    lokasi_label: str
    hpp_per_kg: float | None


async def _tujuan_and_silo(db: AsyncSession, tujuan: str | None):
    """Normalisasi tujuan → (jenis, silo_id|None).

    Yang keluar dari sini `silo` + rujukannya, atau `ditumpuk` + None. Nama
    silonya dicari di MASTER: silo yang ditambahkan lewat Pengaturan → Alat
    langsung bisa menerima PK, tanpa satu baris kode pun berubah.
    """
    teks = (tujuan or "").strip()
    if teks.lower() == DITUMPUK:
        return DITUMPUK, None
    silo = await silo_g2_dari(db, teks) if teks else None
    if silo is None:
        # Daftarnya tak disebut dalam kalimat ini: ia berubah menurut master,
        # dan kalimat yang menyebut dua silo akan keliru begitu ada yang ketiga.
        raise Gudang2Error(
            "Pilih silo Gudang 2 dari daftar, atau pilih tumpukan.")
    _pastikan_komoditas_silo(silo, "pk")
    return SILO, silo.id


async def _guard_kapasitas_tumpukan(db: AsyncSession, tambahan_kg: float | None) -> None:
    """Batas tumpukan hanya ditegakkan bila memang disetel (> 0).

    Keputusan pemilik 12 September 2026: tumpukan Gudang 2 TIDAK berbatas —
    bawaannya 0. Yang menyebut angka di sini adalah lantai pabrik lain.
    Bobot yang belum diketahui (None) tak bisa dinilai, dan tumpukan yang
    tak berbatas memang tak menolaknya.
    """
    cap = settings.g2_tumpukan_maks_kg
    if not cap or tambahan_kg is None:
        return
    stok = await hitung_stok_tumpukan(db)
    if stok + tambahan_kg > cap:
        sisa = max(cap - stok, 0)
        raise Gudang2Error(
            f"❌ Kapasitas tumpukan Gudang 2 penuh (maks {cap / 1000:g} ton). "
            f"Terisi {stok / 1000:g} ton (sisa {sisa / 1000:g} ton), "
            f"tambahan {tambahan_kg / 1000:g} ton."
        )


async def _catat_masuk_selama_proses(
    db: AsyncSession, silo_id: int | None, berat_kg: float,
) -> str | None:
    """PK masuk ke silo yang SEDANG DIPOLES: dicatat pada prosesnya.

    Sampai 12 September 2026 intake seperti ini DITOLAK (temuan QA P-K-11):
    rumus bahan terpakai adalah awal − akhir, dan PK yang masuk di tengah
    proses akan terbaca sebagai "habis dipoles". Pemilik memutuskan lain:
    di lapangan silo memang diisi lagi sesuai kebutuhan, jadi yang harus
    berubah rumusnya, bukan pekerjaannya. Yang dituang selama proses ditambah
    ke `berat_masuk_kg` pemakaian silo itu, dan saat ditutup terpakai = awal
    + masuk − akhir. Rendemen tetap atas bahan yang sungguh masuk mesin.

    Mengembalikan kode proses yang menerimanya (untuk pesan ke layar), atau
    None bila silonya tidak sedang dipoles.
    """
    if silo_id is None or berat_kg is None:
        return None
    from app.models import PolishingProcess, PolishingSiloUsage

    baris = (await db.execute(
        select(PolishingSiloUsage, PolishingProcess.kode_proses)
        .join(PolishingProcess,
              PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.silo_id == silo_id,
               PolishingProcess.status == "proses",
               PolishingSiloUsage.berat_akhir_kg.is_(None))
        .limit(1)
    )).first()
    if baris is None:
        return None
    usage, kode = baris
    usage.masuk_tetap_kg = float(usage.masuk_tetap_kg or 0) + float(berat_kg)
    return kode


async def _add_intake(
    db: AsyncSession, *, user: User, sumber_tipe: str, tujuan: str,
    berat_kg: float | None, hpp_per_kg: float | None, tanggal, jam,
    pk_purchase_batch_id: int | None = None, internal_transfer_id: int | None = None,
    kunci_kiriman: str | None = None, transfer_peristiwa_id: int | None = None,
    commit: bool = True, bobot_final: bool = True,
    jasa_id: int | None = None,
) -> IntakeResult:
    """SATU titik tulis untuk semua PK yang masuk Gudang 2 — dari PK luar
    maupun transfer Gudang 1.

    **Jalur PERISTIWA (Tahap 3, aksi ketiga):** tujuan & silo → penjaga
    kapasitas / catat ke proses yang sedang memakai silo → peristiwa
    `pk_masuk_g2` (kunci kiriman idempoten) → proyeksi (constraint: satu
    batch / satu transfer satu pemasukan hidup) → cermin `pk_gudang2_intakes`
    → jejak → commit. Pembatalannya (`undo._undo_pk_intake`) ditolak bila
    PK-nya sudah dipoles atau tumpukannya sudah dipindah — P-K-10.
    """
    tujuan_norm, silo_id = await _tujuan_and_silo(db, tujuan)
    ke_proses = None
    if tujuan_norm == "ditumpuk":
        await _guard_kapasitas_tumpukan(db, berat_kg)
    else:
        # ── Isi silo Gudang 2 harus SEPEMILIK ──
        #
        # Silonya dikunci lebih dulu: dua PK dua pemilik yang masuk ke silo yang
        # sama pada detik yang sama sama-sama membaca isi yang lama. Lihat
        # catatan panjang di `jasa.kunci_silo`.
        await kunci_silo(db, silo_id)
        try:
            jasa_id = await pastikan_satu_pemilik(
                db, user=user, jasa_ids=list(await pemilik_silo_g2(db, silo_id)) + [jasa_id])
        except JasaError as e:
            raise Gudang2Error(f"❌ {e.args[0]}") from None
        ke_proses = await _catat_masuk_selama_proses(db, silo_id, berat_kg)
        # `pastikan_satu_pemilik` di atas sudah memastikan barang yang masuk
        # sepemilik dengan isi silo/proses. PolishingProcess menyimpan jasa_id,
        # jadi PK jasa yang sama pemiliknya aman ditambahkan dan tetap tercatat
        # sebagai bahan proses jasa tersebut.
    now = input_time(tanggal, jam)

    if not kunci_kiriman:
        if pk_purchase_batch_id is not None:
            n = await buku.jumlah_jenis(db, PK_MASUK_G2, "pk_purchase_batch_id", pk_purchase_batch_id)
            kunci_kiriman = f"{PK_MASUK_G2}:batch:{pk_purchase_batch_id}:{n + 1}"
        elif internal_transfer_id is not None:
            n = await buku.jumlah_jenis(db, PK_MASUK_G2, "internal_transfer_id", internal_transfer_id)
            kunci_kiriman = f"{PK_MASUK_G2}:transfer:{internal_transfer_id}:{n + 1}"
        else:
            import secrets
            kunci_kiriman = f"{PK_MASUK_G2}:bebas:{secrets.token_hex(8)}"
    muatan = {
        "sumber_tipe": sumber_tipe, "pk_purchase_batch_id": pk_purchase_batch_id,
        "internal_transfer_id": internal_transfer_id, "tujuan": tujuan_norm, "silo_id": silo_id,
        "berat_kg": berat_kg, "hpp_per_kg": hpp_per_kg, "ke_proses": ke_proses,
        "tanggal": now.date(), "waktu": now, "transfer_peristiwa_id": transfer_peristiwa_id,
        "jasa_id": jasa_id,
    }
    try:
        e = await buku.catat(db, jenis=PK_MASUK_G2, pelaku_id=user.id, kunci_kiriman=kunci_kiriman,
                             muatan=muatan, waktu=now)
    except IntegrityError as e_:
        raise Gudang2Error(_pesan_integritas(e_, "proyeksi_pk_masuk_g2", ""))
    if not e.baru:
        from app.models import Peristiwa
        ada = (await db.execute(
            select(PkGudang2Intake).join(Peristiwa, Peristiwa.id == PkGudang2Intake.peristiwa_id)
            .where(Peristiwa.kunci_kiriman == kunci_kiriman))).scalars().first()
        if ada is not None:
            label = await label_tujuan(db, ada.tujuan, ada.silo_id)
            return IntakeResult(intake=ada, lokasi_label=label, hpp_per_kg=ada.hpp_per_kg)

    intake = PkGudang2Intake(
        sumber_tipe=sumber_tipe,
        pk_purchase_batch_id=pk_purchase_batch_id,
        internal_transfer_id=internal_transfer_id,
        tujuan=tujuan_norm, silo_id=silo_id, berat_kg=berat_kg,
        # False = masih perkiraan / belum diketahui saat masuk; poller
        # melengkapinya dari batch-nya begitu netto sungguhan ada (P6-02).
        bobot_final=bobot_final and berat_kg is not None,
        hpp_per_kg=hpp_per_kg, flag_hpp_belum_tersedia=hpp_per_kg is None,
        tanggal_masuk=now.date(), waktu_masuk=now, input_by=user.id,
        peristiwa_id=e.id,
        # NULL untuk PK beli luar, selalu: PK walk-in jasa belum dikerjakan, dan
        # jalur yang mengisinya belum ada.
        jasa_id=jasa_id,
    )
    db.add(intake)
    await db.flush()
    getattr(e, "proyeksi", None) and setattr(e.proyeksi, "intake_id", intake.id)
    await log_activity(
        db, table_name="pk_gudang2_intakes", record_id=intake.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{sumber_tipe} | "
                  f"{f'{berat_kg:.0f}kg' if berat_kg is not None else 'bobot menunggu timbang'}"
                  f" → {tujuan_norm}",
    )
    # Status silo diturunkan ulang SEBELUM commit, supaya ia ikut satu
    # transaksi dengan pemasukannya — status yang tertulis di transaksi kedua
    # bisa tertinggal saat yang pertama berhasil dan yang kedua gagal.
    await segarkan_status_silo(db, silo_id)
    if commit:
        await db.commit()
        await db.refresh(intake)
    label = await label_tujuan(db, tujuan_norm, silo_id)
    return IntakeResult(intake=intake, lokasi_label=label, hpp_per_kg=hpp_per_kg)


async def terima_transfer_g1(
    db: AsyncSession, *, user: User, kode_transfer: str | None, tujuan: str | None = None,
    tanggal=None, jam=None,
) -> IntakeResult:
    """Terima PK kiriman Gudang 1 (InternalTransfer) → intake stok Gudang 2."""
    if not kode_transfer:
        raise Gudang2Error("Sebutkan kode transfernya, contoh: `terima TRF-20260704-01 ke silo A`")
    trf = (
        await db.execute(
            select(InternalTransfer).where(InternalTransfer.kode_transfer == kode_transfer)
        )
    ).scalars().first()
    if trf is None:
        raise Gudang2Error(f"Transfer {kode_transfer} tidak ditemukan.")
    dup = (
        await db.execute(
            select(PkGudang2Intake.id).where(
                PkGudang2Intake.internal_transfer_id == trf.id
            )
        )
    ).first()
    if dup:
        # PK kiriman G1 kini LANGSUNG masuk stok saat dikirim (staff/admin sudah
        # pilih tujuan) — langkah 'terima' manual tak diperlukan lagi.
        raise Gudang2Error(
            f"Transfer {kode_transfer} sudah otomatis masuk stok Gudang 2 saat "
            "dikirim — tak perlu diterima manual."
        )
    # Transfer lama (sebelum auto-intake): terima manual. Tujuan default ikut
    # lokasi_tujuan transfer bila operator tak menyebut.
    return await _add_intake(
        db, user=user, sumber_tipe="transfer_internal",
        tujuan=tujuan or trf.lokasi_tujuan, berat_kg=float(trf.berat_kg),
        hpp_per_kg=float(trf.hpp_per_kg) if trf.hpp_per_kg is not None else None,
        tanggal=tanggal, jam=jam, internal_transfer_id=trf.id,
    )


async def masukkan_pk_luar(
    db: AsyncSession, *, user: User, kode: str | None, tujuan: str | None = None,
    tanggal=None, jam=None, kunci_kiriman: str | None = None,
) -> IntakeResult:
    """Masukkan PK luar (yang sudah MASUK/diterima) — SELALU ke tumpukan G2.

    PK masuk = pasti diterima, jadi boleh langsung ditempatkan; input
    kualitas & verifikasi harga jalan terpisah (HPP intake di-backfill saat harga
    diverifikasi bila saat masuk belum ada).

    ⚠⚠ TUJUAN TAK LAGI PERTANYAAN (keputusan pemilik 4 Oktober 2026): PK yang
    BARU masuk selalu ke tumpukan — silo tak boleh menyimpan stok berdiri,
    isinya hanya untuk kebutuhan proses, dan satu-satunya jalan sah ke silo
    kini `pindah_tumpukan_ke_silo`, pekerjaan operator. Satu-satunya baris
    historis yang pernah melanggarnya (`beli_luar` langsung ke silo, sebelum
    aturan ini) DIBIARKAN apa adanya — PK-nya memang berdiri di silo, dan
    menulis ulang riwayatnya membuat catatan berbohong tentang tempat
    barangnya.

    `tujuan` di sini TETAP ADA hanya sebagai PAGAR, bukan sebagai pilihan:
    menghilangkan medannya dari borang bukan penjagaan — alamatnya bisa
    diketik, dan lembar lama masih terbuka di layar orang lain. Kosong atau
    "ditumpuk" diterima diam-diam (borang baru tak mengirim apa pun); apa pun
    yang menunjuk SILO ditolak di sini, bukan cuma dihilangkan dari borang."""
    if not kode:
        raise Gudang2Error("Sebutkan kode PK luarnya, contoh: `masukkan PKL-... ke silo B`")
    if tujuan and (await _tujuan_and_silo(db, tujuan))[0] != DITUMPUK:
        raise Gudang2Error(
            "❌ PK yang baru masuk harus ke tumpukan dulu — silo hanya terisi "
            "lewat 'Pindah tumpukan ke silo', dan itu pekerjaan operator."
        )
    tujuan = DITUMPUK
    # ── Batch-nya DIKUNCI sebelum diperiksa ──
    #
    # Tanpa kunci, dua permintaan yang datang bersamaan sama-sama menemukan
    # "belum pernah dimasukkan" lalu sama-sama menulis: PK luar masuk Gudang 2
    # DUA KALI, dan stoknya bertambah dua kali lipat. QA mengukurnya 20 dari
    # 20 percobaan. Temuan P-K-04.
    #
    # Pemeriksaan duplikatnya diulang SESUDAH kunci didapat — kalau diperiksa
    # sebelum, kuncinya tak menjaga apa pun.
    batch = (
        await db.execute(
            select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == kode)
            .with_for_update()
        )
    ).scalars().first()
    if batch is None:
        raise Gudang2Error(f"PK luar {kode} tidak ditemukan.")
    dup = (
        await db.execute(
            select(PkGudang2Intake.id).where(
                PkGudang2Intake.pk_purchase_batch_id == batch.id
            )
        )
    ).first()
    if dup:
        raise Gudang2Error(f"PK luar {kode} sudah dimasukkan sebelumnya.")
    verif = (
        await db.execute(
            select(PkPurchaseVerification).where(
                PkPurchaseVerification.pk_purchase_batch_id == batch.id
            )
        )
    ).scalars().first()
    # Tiga keadaan bobot (QA P6-02): pasti, perkiraan (ikut sebagai angka,
    # ditandai belum final), tak diketahui (NULL — bukan 0, yang ditolak
    # CHECK berat_positif dan memang bohong). Poller melengkapinya.
    #
    # ⚠ Bobot yang masuk sini SELALU bobot batch apa adanya (potongan bobot
    # QC DIHAPUS 4 Oktober 2026 — basis data produksi tak pernah memuat satu
    # baris pun berisi `potongan_kg`). `verif` tetap dibaca di sini bukan
    # untuk potongannya, melainkan untuk HPP di baris berikutnya.
    bobot = dari_batch(batch)
    berat = bobot.angka() if bobot.diketahui else None
    hpp = float(verif.harga_per_kg) if verif and verif.harga_per_kg is not None else None
    res = await _add_intake(
        db, user=user, sumber_tipe="beli_luar", tujuan=tujuan, berat_kg=berat,
        hpp_per_kg=hpp, tanggal=tanggal, jam=jam, pk_purchase_batch_id=batch.id,
        kunci_kiriman=kunci_kiriman, bobot_final=bobot.pasti,
        # Pemiliknya DISALIN dari batch-nya, bukan dibaca menyusul: yang masuk
        # sudah masuk, dan pemiliknya tak boleh ikut bergeser bila batch-nya
        # kemudian dikoreksi. Tanpa baris ini, PK pelanggan berubah jadi PK
        # pabrik tepat di pintu Gudang 2 — tanpa satu pun galat.
        jasa_id=batch.jasa_id,
    )
    batch.status_batch = "di_silo" if res.intake.tujuan != "ditumpuk" else "ditumpuk"
    await db.commit()
    return res


async def resinkron_intake_g2(db: AsyncSession) -> int:
    """Lengkapi berat PK yang masuk Gudang 2 SEBELUM bobotnya pasti (P6-02).

    Intake menyalin bobot batch saat masuk. Jika perkiraan sudah dipindahkan
    dari tumpukan ke silo, timbang final juga harus mengoreksi pemindahan,
    pemakaian silo aktif, dan bahan pada proses bersama dalam transaksi yang
    sama. Koreksi pemindahan dicatat sebagai peristiwa tambahan; peristiwa
    asal tidak diubah.

    Bila satu intake tersebar ke beberapa silo dan koreksi diperlukan, sistem
    tidak menebak silo mana yang menerima selisih: intake tetap belum final
    dan kasusnya masuk log untuk rekonsiliasi manual.
    """
    rows = (await db.execute(
        select(PkGudang2Intake, PkPurchaseBatch)
        .join(PkPurchaseBatch, PkPurchaseBatch.id == PkGudang2Intake.pk_purchase_batch_id)
        .where(PkGudang2Intake.dibatalkan_pada.is_(None),
               (PkGudang2Intake.bobot_final.is_(False) | (
                   PkPurchaseBatch.jumlah_karung.is_not(None) &
                   PkGudang2Intake.berat_kg.is_distinct_from(PkPurchaseBatch.berat_total_kg))),
               PkPurchaseBatch.dibatalkan_pada.is_(None),
               PkPurchaseBatch.sumber_berat.in_(("nota", "timbangan", "manual")),
               PkPurchaseBatch.berat_total_kg.is_not(None),
               PkPurchaseBatch.berat_total_kg > 0)
        .with_for_update(of=PkGudang2Intake, skip_locked=True)
    )).all()
    selesai = 0
    for intake, batch in rows:
        if batch.jumlah_karung:
            intake.berat_kg = batch.berat_total_kg
            intake.bobot_final = True
            for sid in (await db.scalars(select(PkTumpukanToSilo.silo_id).where(
                PkTumpukanToSilo.pk_gudang2_intake_id == intake.id).distinct())).all():
                await segarkan_status_silo(db,sid)
            selesai += 1
            continue
        final = float(batch.berat_total_kg)
        awal = float(intake.berat_kg) if intake.berat_kg is not None else None
        moves = (await db.execute(
            select(PkTumpukanToSilo).where(
                PkTumpukanToSilo.pk_gudang2_intake_id == intake.id,
                PkTumpukanToSilo.dibatalkan_pada.is_(None),
            ).order_by(PkTumpukanToSilo.waktu, PkTumpukanToSilo.id)
            .with_for_update()
        )).scalars().all()

        delta = final - (awal or 0.0)
        jumlah_dipindah = sum(float(m.berat_kg or 0) for m in moves)
        # Bila sisa tumpukan masih dapat menutup bobot final, pertahankan semua
        # pemindahan dan biarkan sisa dihitung sebagai final - jumlah dipindah.
        # Jika seluruh perkiraan sudah dipindah, atau catatan silo melebihi
        # bobot final, koreksi jumlah masuk silo. Pemilik silo harus tunggal
        # agar selisihnya tidak dibagi dengan tebakan.
        pindah_penuh = bool(moves) and awal is not None and jumlah_dipindah >= awal - 1.0
        perlu_koreksi_silo = pindah_penuh or jumlah_dipindah > final + 0.005
        delta_pemindahan = final - jumlah_dipindah if perlu_koreksi_silo else 0.0
        koreksi_moves: list[tuple[PkTumpukanToSilo, float, float]] = []
        if moves and abs(delta_pemindahan) > 0.005:
            silo_ids = {m.silo_id for m in moves}
            if len(silo_ids) != 1:
                log.warning(
                    "Bobot intake G2 %s (%s): %.2f → %.2f kg, sudah tersebar ke %s silo; "
                    "ditahan untuk rekonsiliasi manual.",
                    intake.id, batch.kode_batch, awal, final, len(silo_ids),
                )
                continue
            sisa_koreksi = delta_pemindahan
            for move in reversed(moves):
                lama_move = float(move.berat_kg or 0)
                baru_move = lama_move + sisa_koreksi
                if baru_move >= 0:
                    if abs(baru_move - lama_move) > 0.005:
                        koreksi_moves.append((move, lama_move, baru_move))
                    sisa_koreksi = 0.0
                    break
                koreksi_moves.append((move, lama_move, 0.0))
                sisa_koreksi = baru_move
            if sisa_koreksi < -0.005:
                log.warning("Bobot final intake G2 %s lebih kecil dari seluruh catatan silo; ditahan.", intake.id)
                continue
        koreksi_move = koreksi_moves[-1][0] if koreksi_moves else None

        # Terapkan koreksi pada proses pertama yang memakai silo setelah
        # material masuk. Ini mengubah snapshot awal bila dituangkan sebelum
        # proses, atau berat masuk bila dituangkan saat proses berjalan.
        usage_koreksi = None
        proc_koreksi = None
        output_count = 0
        silo_koreksi_id = (koreksi_move.silo_id if koreksi_move is not None else
                           intake.silo_id if intake.tujuan == SILO else None)
        waktu_masuk_silo = (koreksi_move.waktu if koreksi_move is not None else intake.waktu_masuk)
        delta_silo = (delta_pemindahan if koreksi_move is not None else
                      delta if intake.tujuan == SILO else 0.0)
        if silo_koreksi_id is not None and abs(delta_silo) > 0.005:
            from app.models import PolishingOutputLog
            kandidat = (await db.execute(
                select(PolishingSiloUsage, PolishingProcess)
                .join(PolishingProcess,
                      PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
                .where(PolishingSiloUsage.silo_id == silo_koreksi_id,
                       (PolishingProcess.waktu_selesai.is_(None)
                        | (PolishingProcess.waktu_selesai >= waktu_masuk_silo)))
                .order_by(PolishingProcess.waktu_mulai, PolishingProcess.id)
                .with_for_update(of=PolishingSiloUsage)
            )).first()
            if kandidat:
                usage_koreksi, proc_koreksi = kandidat
                output_count = int((await db.execute(
                    select(func.count(PolishingOutputLog.id)).where(
                        PolishingOutputLog.polishing_process_id == proc_koreksi.id)
                )).scalar_one())
                kolom = ("berat_awal_kg" if waktu_masuk_silo <= proc_koreksi.waktu_mulai
                         else "berat_masuk_kg")
                nilai_lama = float(getattr(usage_koreksi, kolom) or 0)
                nilai_baru = nilai_lama + delta_silo
                if nilai_baru < -0.005:
                    log.warning("Koreksi intake G2 %s akan membuat input proses negatif; ditahan.", intake.id)
                    continue
                setattr(usage_koreksi, kolom, max(0.0, nilai_baru))

        intake.berat_kg = final
        intake.bobot_final = True
        if intake.peristiwa_id is not None and awal is not None and abs(delta) > 0.005:
            await buku.catat(
                db, jenis=PK_MASUK_G2_KOREKSI_BOBOT, pelaku_id=None,
                kunci_kiriman=f"{PK_MASUK_G2_KOREKSI_BOBOT}:intake:{intake.id}",
                muatan={"intake_id": intake.id, "peristiwa_asal_id": intake.peristiwa_id,
                        "berat_lama_kg": awal, "berat_baru_kg": final,
                        "delta_kg": delta, "kode_batch": batch.kode_batch},
            )
        for move, lama_move, baru_move in koreksi_moves:
            move.berat_kg = baru_move
            if move.peristiwa_id is not None:
                await buku.catat(
                    db, jenis=PK_TUMPUKAN_KE_SILO_KOREKSI_BOBOT,
                    pelaku_id=None,
                    kunci_kiriman=(f"{PK_TUMPUKAN_KE_SILO_KOREKSI_BOBOT}:intake:{intake.id}"
                                   f":move:{move.id}"),
                    muatan={"intake_id": intake.id, "move_id": move.id,
                            "peristiwa_asal_id": move.peristiwa_id,
                            "berat_lama_kg": lama_move,
                            "berat_baru_kg": baru_move,
                            "delta_kg": baru_move - lama_move,
                            "kode_batch": batch.kode_batch},
                )
            await log_activity(
                db, table_name="pk_tumpukan_to_silo", record_id=move.id,
                action="UPDATE", changed_by=None, field_name="berat_kg",
                old_value=f"{lama_move:.2f} kg", new_value=f"{baru_move:.2f} kg",
                alasan=f"Rekonsiliasi timbang final batch {batch.kode_batch}; bobot intake "
                       f"{awal:.2f} → {final:.2f} kg",
            )
        await log_activity(
            db, table_name="pk_gudang2_intakes", record_id=intake.id,
            action="UPDATE", changed_by=None, field_name="berat_kg",
            old_value=f"{awal:.2f} kg" if awal is not None else "belum diketahui",
            new_value=f"{final:.2f} kg",
            alasan=f"Bobot final dari tiket timbang batch {batch.kode_batch}",
        )

        if usage_koreksi is not None and proc_koreksi is not None:
            from app.penggilingan.gudang2.polishing import _arus_dari_komposisi
            from app.services.proses_bersama import perbarui_bahan_proses_bersama
            from hmu_core.proses_db import ProsesTerpadu

            total_proc = float(usage_koreksi.berat_awal_kg or 0) + float(usage_koreksi.berat_masuk_kg or 0)
            komposisi = await komposisi_bahan_silo(
                db, silo_koreksi_id,
                sampai=proc_koreksi.waktu_selesai or input_time(None),
                kecuali_proses_id=proc_koreksi.id, target_kg=total_proc,
            )
            silo = await db.get(Silo, silo_koreksi_id)
            await perbarui_bahan_proses_bersama(
                db, tabel_sumber="polishing_process", id_sumber=proc_koreksi.id,
                bahan=tuple(_arus_dari_komposisi(silo, komposisi)),
            )
            proyeksi = (await db.execute(select(ProsesTerpadu).where(
                ProsesTerpadu.aplikasi == "produksi",
                ProsesTerpadu.tabel_sumber == "polishing_process",
                ProsesTerpadu.id_sumber == str(proc_koreksi.id),
            ).with_for_update())).scalar_one_or_none()
            if proyeksi is not None:
                metadata = dict(proyeksi.metadata_domain or {})
                semua_komposisi = dict(metadata.get("komposisi_bahan") or {})
                semua_komposisi[silo.nama_silo] = komposisi
                metadata["komposisi_bahan"] = semua_komposisi
                if output_count:
                    metadata.setdefault("koreksi_bobot_setelah_hasil", []).append({
                        "kode_batch": batch.kode_batch, "delta_kg": delta,
                        "waktu_koreksi": input_time(None).isoformat(),
                        "hasil_sudah_dicatat": output_count,
                    })
                proyeksi.metadata_domain = metadata
            await log_activity(
                db, table_name="polishing_process", record_id=proc_koreksi.id,
                action="UPDATE", changed_by=None, field_name="bobot_bahan",
                old_value=f"{total_proc - delta_silo:.2f} kg", new_value=f"{total_proc:.2f} kg",
                alasan=(f"Rekonsiliasi timbang final batch {batch.kode_batch}; "
                        f"{output_count} catatan hasil sudah ada"),
            )
        selesai += 1
    from app.penggilingan.gudang2.polishing import sinkron_bahan_karung
    await sinkron_bahan_karung(db)
    await db.commit()
    return selesai


# ─────────────────────────── Pindah tumpukan → silo ───────────────────────────
@dataclass
class PindahResult:
    kode_pindah: str
    nama_silo: str
    berat_kg: float | None
    sisa_tumpukan_intake: float | None
    #: Kode penyosohan yang sedang memakai silo itu, bila PK-nya dituang di
    #: tengah proses — ia ikut dihitung sebagai bahan proses tersebut.
    ke_proses: str | None = None
    jumlah_karung: int | None = None
    bobot_final: bool = True
    sisa_karung: int | None = None


async def _catat_pindah(
    db: AsyncSession, *, user: User, intake: PkGudang2Intake, silo: Silo, nama_silo: str,
    kirim: float | None, now, kunci_kiriman: str | None = None,
    jumlah_karung: int | None = None, hasil_timbang: bool = False,
) -> tuple[PkTumpukanToSilo, str | None]:
    """SATU titik tulis pemindahan tumpukan → silo (jalur peristiwa, Tahap 3
    aksi kelima): nomor atomik → catat ke proses yang sedang memakai silo →
    peristiwa `pk_tumpukan_ke_silo` (kunci kiriman idempoten) → proyeksi →
    cermin `pk_tumpukan_to_silo` → jejak. Tidak commit."""
    # ── Isi silo tujuan harus SEPEMILIK dengan tumpukan yang dipindah ──
    #
    # Titik campur keempat: N tumpukan → 1 silo Gudang 2. `pk_tumpukan_to_silo`
    # tak punya kolom `jasa_id` sendiri dan tak perlu — pemiliknya ada di intake
    # asalnya, dan kolom kedua yang berarti hal sama adalah kolom yang suatu
    # hari berselisih dengan yang pertama.
    batch = await db.get(PkPurchaseBatch,intake.pk_purchase_batch_id) if intake.pk_purchase_batch_id else None
    if batch and batch.jumlah_karung and jumlah_karung is None and not hasil_timbang:
        raise Gudang2Error("PK beli luar berkarung harus dipindah dalam karung; kg wajib ditandai hasil timbang / bagian karung.")
    _pastikan_komoditas_silo(silo, "pk")
    await kunci_silo(db, silo.id)
    try:
        await pastikan_satu_pemilik(
            db, user=user, jasa_ids=list(await pemilik_silo_g2(db, silo.id)) + [intake.jasa_id])
    except JasaError as e:
        raise Gudang2Error(f"❌ Silo {nama_silo}: {e.args[0]}") from None

    if not kunci_kiriman:
        n = await buku.jumlah_jenis(db, PK_TUMPUKAN_KE_SILO, "intake_id", intake.id)
        kunci_kiriman = f"{PK_TUMPUKAN_KE_SILO}:intake:{intake.id}:{n + 1}"
    else:
        from app.models import Peristiwa
        ada = (await db.execute(
            select(PkTumpukanToSilo).join(Peristiwa, Peristiwa.id == PkTumpukanToSilo.peristiwa_id)
            .where(Peristiwa.kunci_kiriman == kunci_kiriman))).scalars().first()
        if ada is not None:
            return ada, None
    kode = await next_tumpukan_move_code(db)
    pemakaian = None
    if jumlah_karung is not None:
        pemakaian = (await db.execute(select(PolishingSiloUsage).join(PolishingProcess)
            .where(PolishingSiloUsage.silo_id == silo.id,
                   PolishingSiloUsage.berat_akhir_kg.is_(None), PolishingProcess.status == "proses")
            .limit(1))).scalars().first()
        ke_proses = (await db.get(PolishingProcess, pemakaian.polishing_process_id)).kode_proses if pemakaian else None
        if pemakaian:
            pemakaian.bobot_karung_dinamis = True
    else:
        ke_proses = await _catat_masuk_selama_proses(db, silo.id, kirim)
    # Pemilik sumber sudah disamakan dengan isi silo di atas. Proses sosoh
    # juga menyimpan pemiliknya, sehingga tambahan PK jasa sepemilik dapat
    # ikut dihitung sebagai bahan proses berjalan.
    muatan = {
        "kode_pindah": kode, "intake_id": intake.id, "intake_peristiwa_id": intake.peristiwa_id,
        "silo_id": silo.id, "nama_silo": nama_silo, "berat_kg": None if jumlah_karung is not None else kirim,
        "jumlah_karung": jumlah_karung, "ke_proses": ke_proses,
        "cara_bobot": "karung" if jumlah_karung is not None else "hasil_timbang" if hasil_timbang else "kg_lama",
        "tanggal": now.date(), "waktu": now,
    }
    e = await buku.catat(db, jenis=PK_TUMPUKAN_KE_SILO, pelaku_id=user.id, kunci_kiriman=kunci_kiriman,
                         muatan=muatan, waktu=now)
    move = PkTumpukanToSilo(
        kode_pindah=kode, pk_gudang2_intake_id=intake.id, silo_id=silo.id,
        berat_kg=None if jumlah_karung is not None else kirim, jumlah_karung=jumlah_karung,
        pemakaian_silo_id=pemakaian.id if pemakaian else None, selama_proses=pemakaian is not None,
        tanggal=now.date(), waktu=now, input_by=user.id, peristiwa_id=e.id,
    )
    db.add(move)
    if jumlah_karung is not None:
        move.batch = await db.get(PkPurchaseBatch, intake.pk_purchase_batch_id)
    if pemakaian is not None:
        pemakaian.pemindahan_karung.append(move)
    await db.flush()
    getattr(e, "proyeksi", None) and setattr(e.proyeksi, "move_id", move.id)
    await log_activity(
        db, table_name="pk_tumpukan_to_silo", record_id=move.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | " + (f"{jumlah_karung} karung" if jumlah_karung is not None else f"{kirim:.0f}kg") + f" → Silo {nama_silo}"
                  + (f" | ditambah ke {ke_proses}" if ke_proses else ""),
    )
    await segarkan_status_silo(db, move.silo_id)
    return move, ke_proses


#: Selisih yang masih diterima antara berat yang DIKETIK dan sisa tumpukan
#: yang sebenarnya. Satu kilogram: di bawah ketelitian jembatan timbang, dan
#: cukup menampung pembulatan label mana pun (yang terbesar setengah kilogram).
#: Bukan angka kenyamanan — lihat alasan panjangnya di `pindah_tumpukan_ke_silo`.
TOLERANSI_PINDAH_KG = 1.0


async def acuan_karung_surat_jalan(db, batch, jumlah):
    """Bobot produksi untuk surat jalan yang baru dilengkapi, tanpa menulis.

    Batch yang dahulu memakai nota harus mengambil W dari barang/netto tiket,
    sama seperti penerimaan berkarung baru. Pratinjau dan simpan membaca jalur
    yang sama agar nota nominal tidak menyamar sebagai bobot truk yang pasti.
    """
    from types import SimpleNamespace
    berat, sumber, perkiraan = batch.berat_total_kg, batch.sumber_berat, batch.berat_perkiraan_kg
    if batch.timbangan_transaksi_id:
        tiket = await ambil_tiket(db, batch.timbangan_transaksi_id)
        if tiket is None:
            raise Gudang2Error("Tiket timbang batch tidak tersedia. Periksa penerimaannya dulu.")
        tiket = dict(tiket)
        real = next((v for v in (tiket.get("berat_barang_kg"), tiket.get("netto_timbangan_kg"))
                     if v is not None and float(v) > 0), None)
        tiket["berat_hpp_kg"], tiket["sumber_berat"] = real, "timbangan"
        berat, sumber, perkiraan = await bobot_awal_dari_tiket(db, tiket)
    return SimpleNamespace(jumlah_karung=jumlah, ukuran_karung_kg=batch.ukuran_karung_kg,
                           berat_total_kg=berat,
                           sumber_berat=sumber, berat_perkiraan_kg=perkiraan)


async def pindah_tumpukan_ke_silo(
    db: AsyncSession, *, user: User, intake_id: int, nama_silo: str | None,
    berat: float | None = None, tanggal=None, jam=None, kunci_kiriman: str | None = None,
    jumlah_karung: int | None = None, hasil_timbang: bool = False, commit: bool = True,
    jumlah_karung_partai: int | None = None, ukuran_karung_kg: float | None = None,
) -> PindahResult:
    """Pindah PK dari tumpukan ke silo. HANYA operator Gudang 2 (admin fallback).

    Baris tumpukan sumbernya DIKUNCI sebelum sisanya dibaca: dua operator yang
    sama-sama membaca "sisa 15.000" lalu memindahkan 10.000 akan mengosongkan
    tumpukan −5.000 — pola yang sama dengan P-K-06 di transfer.
    """
    g2_wid = await _g2_warehouse_id(db)
    if not is_operator_gudang2(user, g2_wid):
        raise Gudang2Error(
            "🔒 Pemindahan tumpukan ke silo hanya bisa dilakukan oleh "
            "Operator Gudang 2 (atau admin)."
        )
    if not nama_silo:
        raise Gudang2Error("Pilih nama silo tujuan Gudang 2.")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")
    _pastikan_komoditas_silo(silo, "pk")
    intake = (await db.execute(
        select(PkGudang2Intake).where(PkGudang2Intake.id == intake_id).with_for_update()
    )).scalars().first()
    if intake is None:
        raise Gudang2Error("Tumpukan sumber tidak ditemukan.")
    if intake.tujuan != "ditumpuk":
        raise Gudang2Error("Sumber bukan tumpukan — hanya PK di tumpukan yang bisa dipindah.")

    if kunci_kiriman:
        from app.models import Peristiwa
        ada = (await db.scalars(select(PkTumpukanToSilo).join(Peristiwa,
            Peristiwa.id == PkTumpukanToSilo.peristiwa_id).where(
                Peristiwa.kunci_kiriman == kunci_kiriman))).first()
        if ada is not None:
            if (ada.pk_gudang2_intake_id != intake.id or ada.silo_id != silo.id
                    or (jumlah_karung is not None and ada.jumlah_karung != jumlah_karung)):
                raise Gudang2Error("Kunci kiriman ini sudah dipakai untuk pemindahan lain.")
            batch = await db.get(PkPurchaseBatch,intake.pk_purchase_batch_id) if intake.pk_purchase_batch_id else None
            sisa = await _sisa_tumpukan_intake(db,intake.id)
            return PindahResult(ada.kode_pindah,nama_silo,
                None if ada.berat_kg is None else float(ada.berat_kg),sisa,
                jumlah_karung=ada.jumlah_karung,bobot_final=dari_batch(batch).pasti if batch else intake.bobot_final)
    if berat is not None and (not Decimal(str(berat)).is_finite() or berat <= 0):
        raise Gudang2Error("Kg hasil timbang harus lebih dari nol.")
    batch = await db.get(PkPurchaseBatch, intake.pk_purchase_batch_id) if intake.pk_purchase_batch_id else None
    if jumlah_karung_partai is not None:
        if hasil_timbang or berat is not None:
            raise Gudang2Error("Lengkapi surat jalan untuk pemindahan karung utuh; kg khusus dicatat terpisah.")
        if batch is None:
            raise Gudang2Error("PK giling sendiri tetap dicatat dalam kg.")
        n = jumlah_karung_partai
        if isinstance(n, bool) or n <= 0 or int(n) != n:
            raise Gudang2Error("Jumlah karung separtai harus bilangan bulat lebih dari nol.")
        if batch.jumlah_karung and batch.jumlah_karung != n:
            raise Gudang2Error("Jumlah karung separtai sudah tercatat. Muat ulang formulir.")
        if not batch.jumlah_karung:
            # Melengkapi surat jalan sebelum pemindahan pertama berbeda dari
            # mengubah riwayat kg lama menjadi karung. Yang terakhir dilarang:
            # laporan lama tetap utuh dan memakai penyesuaian bertanggal.
            ada = await db.scalar(select(PkTumpukanToSilo.id).where(
                PkTumpukanToSilo.pk_gudang2_intake_id == intake.id).limit(1))
            if ada is not None:
                raise Gudang2Error("Batch sudah mempunyai pemindahan kg lama. Gunakan kg agar riwayat lama tetap utuh.")
            if ukuran_karung_kg is not None and (not Decimal(str(ukuran_karung_kg)).is_finite() or ukuran_karung_kg <= 0):
                raise Gudang2Error("Ukuran nominal karung harus lebih dari nol.")
            acuan = await acuan_karung_surat_jalan(db, batch, int(n))
            batch.jumlah_karung = int(n)
            # Nota sudah tercatat saat penerimaan; tidak perlu diketik ulang.
            # Payload lama tetap boleh melengkapinya secara eksplisit.
            if ukuran_karung_kg is not None:
                batch.ukuran_karung_kg = ukuran_karung_kg
            batch.berat_total_kg, batch.sumber_berat = acuan.berat_total_kg, acuan.sumber_berat
            batch.berat_perkiraan_kg = acuan.berat_perkiraan_kg
            intake.berat_kg, intake.bobot_final = acuan.berat_total_kg, dari_batch(acuan).pasti
            await log_activity(db, table_name="pk_purchase_batches", record_id=batch.id,
                action="UPDATE", changed_by=user.id, field_name="jumlah_karung",
                old_value="belum tercatat", new_value=str(n),
                alasan="Surat jalan dilengkapi operator sebelum pemindahan pertama; kg lama tidak ditafsirkan ulang.")
    if batch is not None and batch.jumlah_karung and not hasil_timbang:
        if berat is not None:
            raise Gudang2Error("Pilih jumlah karung, atau tandai kg sebagai hasil timbang / karung dibongkar sebagian.")
        sudah = await db.scalar(select(func.coalesce(func.sum(PkTumpukanToSilo.jumlah_karung), 0))
            .where(PkTumpukanToSilo.pk_gudang2_intake_id == intake.id))
        sisa_karung = batch.jumlah_karung - int(sudah)
        k = sisa_karung if jumlah_karung is None else jumlah_karung
        if isinstance(k, bool) or int(k) != k or k <= 0:
            raise Gudang2Error("Jumlah karung harus bilangan bulat lebih dari nol.")
        if k > sisa_karung:
            raise Gudang2Error(f"Tinggal {sisa_karung} karung, tak bisa memasukkan {k} karung.")
        r = bobot_per_karung(batch)
        # Setelah ada baris kg tetap, batas K juga harus menghormati saldo
        # fisiknya. Jumlah karung terakhir mungkin sudah dibongkar sebagian.
        sisa_kg = await _sisa_tumpukan_intake(db, intake.id)
        if r is not None and sisa_kg is not None and Decimal(k) * r > Decimal(str(sisa_kg)) + Decimal("0.000001"):
            utuh = int(Decimal(str(sisa_kg)) // r)
            raise Gudang2Error(f"Tinggal {utuh} karung utuh; sisanya kurang dari 1 karung. Gunakan kg hasil timbang untuk bagian karung.")
        now = input_time(tanggal, jam)
        move, ke_proses = await _catat_pindah(db, user=user, intake=intake, silo=silo,
            nama_silo=nama_silo, kirim=None, jumlah_karung=int(k), now=now, kunci_kiriman=kunci_kiriman)
        if commit:
            await db.commit()
        await db.refresh(move)
        sisa = await _sisa_tumpukan_intake(db, intake.id)
        return PindahResult(move.kode_pindah, nama_silo,
            None if move.berat_kg is None else float(move.berat_kg), sisa, ke_proses,
            jumlah_karung=int(k), bobot_final=dari_batch(batch).pasti,
            sisa_karung=sisa_karung - int(k))
    if jumlah_karung is not None:
        raise Gudang2Error("Jumlah karung separtai belum tercatat pada batch ini. Gunakan kg hasil timbang.")
    if hasil_timbang and berat is None:
        raise Gudang2Error("Isi kg hasil timbang atau karung yang dibongkar sebagian.")
    sisa = await _sisa_tumpukan_intake(db, intake_id)

    if sisa is None:

        raise Gudang2Error(

            "Bobot PK di tumpukan ini belum diketahui — truknya belum ditimbang "

            "kedua. Tunggu timbangnya, lalu pindahkan.")
    if sisa <= 0:
        raise Gudang2Error("Tumpukan ini sudah habis dipindah.")
    # ── TOLERANSI SEKATA, dan sebabnya bukan kelonggaran ──
    #
    # Laporan operator 30 September 2026: pada pemindahan TERAKHIR tumpukan
    # "harus bersisa minimal 1 kg" — tak bisa dikosongkan. Sebabnya bukan di
    # pagar ini melainkan di LABELNYA: kartu membulatkan sisa 2.999,6 kg jadi
    # "3.000 kg", operator mengetik angka yang dibacanya, dan 3000 > 2999,6.
    # Ia hanya menggigit di pemindahan terakhir sebab di situlah orang
    # mengetik angka dari layar, bukan angka kerja yang bulat. "Sisakan 1 kg"
    # adalah siasat yang mereka temukan untuk melompatinya.
    #
    # Labelnya sudah dibetulkan (`berjalan._kg_tepat`), tetapi pagar yang
    # menuntut kesamaan SAMPAI GRAM antara angka ketikan manusia dan angka
    # timbangan akan melahirkan keluhan yang sama dalam bentuk lain. Satu
    # kilogram adalah batas di bawah ketelitian jembatan timbang itu sendiri.
    #
    # Yang dipindahkan tetap `min(berat, sisa)`: toleransi membuat angkanya
    # DITERIMA, bukan membuat tumpukan berutang. Tumpukan yang tersisa 0,4 kg
    # bukan stok — ia pembulatan, dan kartunya akan berdiri selamanya menagih
    # pekerjaan yang tak ada.
    kirim = sisa if berat is None else min(float(berat), sisa)
    if berat is not None and float(berat) > sisa + TOLERANSI_PINDAH_KG:
        raise Gudang2Error(
            f"Berat pindah ({float(berat):g} kg) melebihi sisa tumpukan "
            f"({sisa:g} kg). Kosongkan kotak beratnya untuk memindahkan "
            "seluruh sisanya.")

    now = input_time(tanggal, jam)
    move, ke_proses = await _catat_pindah(db, user=user, intake=intake, silo=silo, nama_silo=nama_silo,
                                          kirim=kirim, now=now, kunci_kiriman=kunci_kiriman, hasil_timbang=hasil_timbang)
    if commit:
        await db.commit()
    await db.refresh(move)
    return PindahResult(
        kode_pindah=move.kode_pindah, nama_silo=nama_silo, berat_kg=float(move.berat_kg),
        sisa_tumpukan_intake=sisa - float(move.berat_kg), ke_proses=ke_proses,
    )


# ─────────────────────────── Broken → silo broken ───────────────────────────
@dataclass
class PindahBrokenResult:
    kode_pindah: str
    nama_silo: str
    berat_kg: float
    sisa_broken: float
    ke_proses: str | None = None


async def _sisa_broken_row(db: AsyncSession, byproduct_stock_id: int) -> float:
    """Sisa SATU baris broken curah (`byproduct_stock`) yang belum dipindah
    ke silo — sebangun `_sisa_tumpukan_intake`."""
    from app.penggilingan.inventory.models import ByproductStock

    row = await db.get(ByproductStock, byproduct_stock_id)
    if row is None or row.jenis_produk != "broken":
        raise Gudang2Error("Baris broken ini tidak ditemukan.")
    dipindah = (await db.execute(
        select(func.coalesce(func.sum(BrokenKeSilo.berat_kg), 0))
        .where(BrokenKeSilo.byproduct_stock_id == byproduct_stock_id)
    )).scalar_one()
    return float(row.berat_kg) - float(dipindah)


async def pindah_broken_ke_silo(
    db: AsyncSession, *, user: User, byproduct_stock_id: int, nama_silo: str | None,
    berat: float | None = None, tanggal=None, jam=None,
) -> PindahBrokenResult:
    """Pindah broken curah (`byproduct_stock`, lahir dari `catat_broken`) ke
    silo broken. Sebangun `pindah_tumpukan_ke_silo` — sumbernya stok curah
    hasil sosoh, bukan tumpukan PK, dan TANPA jalur peristiwa (keputusan
    pemilik tak menyebutnya; aksi baru yang owner tak minta di jalur itu
    tetap di jalur lama, seperti `tutup_silo_giling`). HANYA operator Gudang
    2 (admin fallback) — gerbang yang sama dengan pemindahan tumpukan.

    Baris sumbernya DIKUNCI sebelum sisanya dibaca (pola P-K-04/05/06): dua
    operator yang sama-sama membaca "sisa 500 kg" lalu memindahkan 300 kg
    akan mengosongkan baris itu −100 kg.
    """
    from app.penggilingan.inventory.models import ByproductStock

    g2_wid = await _g2_warehouse_id(db)
    if not is_operator_gudang2(user, g2_wid):
        raise Gudang2Error(
            "🔒 Pemindahan broken ke silo hanya bisa dilakukan oleh "
            "Operator Gudang 2 (atau admin)."
        )
    if not nama_silo:
        raise Gudang2Error("Sebutkan silo broken tujuannya.")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")
    _pastikan_komoditas_silo(silo, "broken")
    row = (await db.execute(
        select(ByproductStock).where(ByproductStock.id == byproduct_stock_id)
        .with_for_update()
    )).scalars().first()
    if row is None or row.jenis_produk != "broken":
        raise Gudang2Error("Baris broken ini tidak ditemukan.")

    sudah = (await db.execute(
        select(func.coalesce(func.sum(BrokenKeSilo.berat_kg), 0))
        .where(BrokenKeSilo.byproduct_stock_id == byproduct_stock_id)
    )).scalar_one()
    sisa = float(row.berat_kg) - float(sudah)
    if sisa <= 0:
        raise Gudang2Error("Broken ini sudah habis dipindah.")
    # TOLERANSI_PINDAH_KG — penjelasan panjangnya di `pindah_tumpukan_ke_silo`.
    kirim = sisa if berat is None else min(float(berat), sisa)
    if berat is not None and float(berat) > sisa + TOLERANSI_PINDAH_KG:
        raise Gudang2Error(
            f"Berat pindah ({float(berat):g} kg) melebihi sisa broken "
            f"({sisa:g} kg). Kosongkan kotak beratnya untuk memindahkan "
            "seluruh sisanya.")

    # ── PAGAR: proses TAK BOLEH memakan broken yang ia hasilkan sendiri ──
    #
    # Secara fisik mustahil — broken keluar di ujung mesin, jadi tak pernah
    # ada sebelum prosesnya selesai menyosoh bahan yang sedang digiling.
    # Tanpa pagar ini, operator bisa mencatat hasil broken (`catat_broken`)
    # lalu memindahkannya ke silo yang SEDANG dipakai proses yang sama
    # sebelum proses itu ditutup — broken "masuk lagi" ke mesin yang justru
    # baru mengeluarkannya.
    if row.source_type == "polishing":
        sedang_dipakai = (await db.execute(
            select(PolishingSiloUsage.polishing_process_id)
            .where(PolishingSiloUsage.silo_id == silo.id,
                   PolishingSiloUsage.berat_akhir_kg.is_(None))
        )).scalars().first()
        if sedang_dipakai is not None and sedang_dipakai == row.source_id:
            raise Gudang2Error(
                f"❌ Broken ini keluar dari proses yang SEDANG memakai Silo "
                f"{nama_silo} — tak bisa dipindah ke sana sebelum prosesnya "
                "ditutup. Pindahkan ke silo broken lain, atau tunggu sampai "
                "prosesnya selesai.")

    # ── Isi silo tujuan harus SEPEMILIK dengan broken yang dipindah ──
    await kunci_silo(db, silo.id)
    try:
        await pastikan_satu_pemilik(
            db, user=user, jasa_ids=list(await pemilik_silo_g2(db, silo.id)) + [row.jasa_id])
    except JasaError as e:
        raise Gudang2Error(f"❌ Silo {nama_silo}: {e.args[0]}") from None

    now = input_time(tanggal, jam)
    kode = await next_broken_move_code(db)
    ke_proses = await _catat_masuk_selama_proses(db, silo.id, kirim)
    move = BrokenKeSilo(
        kode_pindah=kode, byproduct_stock_id=row.id, silo_id=silo.id,
        berat_kg=kirim, tanggal=now.date(), waktu=now, input_by=user.id,
        # DISALIN dari baris sumbernya — lihat docstring `BrokenKeSilo`.
        jasa_id=row.jasa_id,
    )
    db.add(move)
    await db.flush()
    await log_activity(
        db, table_name="broken_ke_silo", record_id=move.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {kirim:.0f}kg → Silo {nama_silo}"
                  + (f" | ditambah ke {ke_proses}" if ke_proses else ""),
    )
    await segarkan_status_silo(db, silo.id)
    await db.commit()
    await db.refresh(move)
    return PindahBrokenResult(
        kode_pindah=move.kode_pindah, nama_silo=nama_silo, berat_kg=float(move.berat_kg),
        sisa_broken=sisa - float(move.berat_kg), ke_proses=ke_proses,
    )


@dataclass
class MasukkanBrokenResult:
    nama_silo: str
    moved_kg: float
    dibongkar_dari_karung_kg: float
    kodes: list[str]


async def masukkan_broken_ke_silo(
    db: AsyncSession, *, user: User, kode_pol: str | None, nama_silo: str | None,
    berat_kg: float | None, jasa_id: int | None = None, tanggal=None, jam=None,
) -> MasukkanBrokenResult:
    """SATU aksi: masukkan broken ke silo. Sumbernya otomatis — curah yang
    SUDAH tercatat dulu (FIFO), lalu hasil mesin yang BELUM tercatat
    dibukukan otomatis bila masih kurang, lalu BONGKAR KARUNG bila masih
    kurang juga. Sisa dari karung yang dibongkar tapi tak terpakai tetap
    jadi curah di stok.

    Mengganti dua langkah lama ("Catat broken (curah)" lalu "Pindah broken ke
    silo"): keduanya menuntut operator menjawab pertanyaan yang salah —
    "berapa yang MASIH BELUM TERCATAT" — padahal yang ingin ia katakan cuma
    "berapa yang masuk silo sekarang". Laporan pemilik 7 Oktober 2026:
    mengetik 5.000 kg berakhir sebagai "tercatat melebihi hasil mesin 500 kg"
    tanpa operator pernah salah ketik — sebabnya murni bentuk borangnya.

    ⚠⚠ **PEMBUKUAN OTOMATIS, BUKAN CUMA PEMINDAHAN** — sejak 10 Oktober 2026.
    Sampai hari itu, "mengganti dua langkah lama" baru benar SEBAGIAN: fungsi
    ini cuma menggabungkan "Pindah broken ke silo" dengan pembongkaran
    karung, tapi tetap menuntut "Catat broken (curah)" dikerjakan TERPISAH
    lebih dulu — borang ini membaca `byproduct_stock` SAJA, tak pernah
    `polishing_output_logs`. Laporan lapangan: proses yang BARU SAJA selesai
    sudah mencatat 3.500 kg broken di mesin, tapi 0 kg lewat "Catat broken
    (curah)" — borang ini menjawab "(belum ada)" walau brokennya nyata ada
    di mesin. Sekarang kalau curah yang sudah tercatat masih kurang, SISA
    hasil mesin yang belum dibukukan (`output_sosoh − _broken_dibukukan`)
    dibukukan dulu — persis logika `catat_broken` — SEBELUM membongkar
    karung, sebab fisiknya memang begitu: hasil mentah yang belum ditimbang
    masih longgar (curah), bukan terkunci dalam karung. Hanya berlaku untuk
    PEMILIK BAWAAN proses ini (`pemilik_hasil_proses`) — broken yang
    sebagian sudah dipindah kepemilikan ke pemilik LAIN tak boleh diam-diam
    "menyerap" hasil mentah yang belum pernah jadi miliknya.

    ⚠ `kode_pol` WAJIB — TIDAK ADA fallback "proses terbaru". `_proc_by_kode`
    (dipakai `catat_broken`/`catat_bekatul`) jatuh ke proses PALING BARU
    DIBUAT bila kode-nya kosong, tanpa peduli proses itu punya broken sama
    sekali — pintu masuk cacat yang sama persis tak boleh terulang di sini.
    """
    from app.penggilingan.inventory.finished_goods import (_broken_dibukukan,
                                                           _proc_by_kode)
    from app.penggilingan.inventory.models import (ByproductStock, FinishedGoodsStock,
                                                   PackageSize, ProductSku)
    from app.services.jasa import pemilik_hasil_proses
    from app.services.stok import output_sosoh

    g2_wid = await _g2_warehouse_id(db)
    if not is_operator_gudang2(user, g2_wid):
        raise Gudang2Error(
            "🔒 Memasukkan broken ke silo hanya bisa dilakukan oleh "
            "Operator Gudang 2 (atau admin)."
        )
    if not berat_kg or float(berat_kg) <= 0:
        raise Gudang2Error("Sebutkan berat yang masuk silo (kg), lebih dari 0.")
    berat_kg = float(berat_kg)
    if not nama_silo:
        raise Gudang2Error("Sebutkan silo broken tujuannya.")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")
    _pastikan_komoditas_silo(silo, "broken")
    if not kode_pol:
        raise Gudang2Error("Sebutkan proses penyosohannya (POL-...).")
    proc = await _proc_by_kode(db, kode_pol)

    def _milik(kolom):
        return kolom.is_(None) if jasa_id is None else kolom == jasa_id

    # ── Pagar: proses TAK BOLEH memakan broken yang ia hasilkan sendiri ──
    # Sama seperti `pindah_broken_ke_silo`; diperiksa SEKALI di sini karena
    # seluruh pool (curah MAUPUN karung yang dibongkar) berasal dari proses
    # yang SAMA (`proc.id`).
    sedang_dipakai = (await db.execute(
        select(PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.silo_id == silo.id,
               PolishingSiloUsage.berat_akhir_kg.is_(None))
    )).scalars().first()
    if sedang_dipakai is not None and sedang_dipakai == proc.id:
        raise Gudang2Error(
            f"❌ Broken ini keluar dari proses yang SEDANG memakai Silo "
            f"{nama_silo} — tak bisa dimasukkan ke sana sebelum prosesnya "
            "ditutup. Pilih silo broken lain, atau tunggu sampai prosesnya "
            "selesai.")

    # ── Isi silo tujuan harus SEPEMILIK ──
    await kunci_silo(db, silo.id)
    try:
        jasa_id = await pastikan_satu_pemilik(
            db, user=user, jasa_ids=list(await pemilik_silo_g2(db, silo.id)) + [jasa_id])
    except JasaError as e:
        raise Gudang2Error(f"❌ Silo {nama_silo}: {e.args[0]}") from None

    # ── Silo sedang disosoh proses LAIN? Daftarkan, dan tolak bila jasa ──
    #
    # Dipanggil SEKALI di sini, bukan di langkah 3 — ia bukan sekadar
    # pembaca, `_catat_masuk_selama_proses` LANGSUNG menulis tambahan ke
    # `berat_masuk_kg` proses yang sedang memakai silo ini. Kalau baru
    # dipanggil belakangan (sesudah pool & `BrokenKeSilo` ditulis), gagalnya
    # pagar jasa di bawah akan menyisakan tulisan yang sudah terlanjur
    # separuh jalan. Sebangun `pindah_broken_ke_silo`.
    ke_proses = await _catat_masuk_selama_proses(db, silo.id, berat_kg)
    # ── Langkah 1 · kumpulkan curah yang SUDAH tercatat, FIFO ──
    curah_rows = (await db.execute(
        select(ByproductStock).where(
            ByproductStock.jenis_produk == "broken",
            ByproductStock.source_type == "polishing",
            ByproductStock.source_id == proc.id, _milik(ByproductStock.jasa_id))
        .order_by(ByproductStock.waktu, ByproductStock.id)
        .with_for_update()
    )).scalars().all()
    pool: list[tuple[int, float]] = []
    for row in curah_rows:
        sisa = await _sisa_broken_row(db, row.id)
        if sisa > 0.5:
            pool.append((row.id, sisa))
    total_curah = sum(s for _, s in pool)

    now = input_time(tanggal, jam)
    dibongkar_kg = 0.0

    # ── Langkah 1.5 · masih kurang? bukukan dulu hasil mesin yang BELUM
    #   TERCATAT, sebelum membongkar karung — lihat ⚠⚠ di docstring.
    if total_curah + 0.5 < berat_kg:
        pemilik_bawaan = await pemilik_hasil_proses(db, proc.jasa_id, "broken")
        if jasa_id == pemilik_bawaan:
            keluar_mesin = (await output_sosoh(db, proc.id)).get("broken") or 0.0
            belum_dicatat = float(keluar_mesin) - await _broken_dibukukan(db, proc.id)
            if belum_dicatat > 0.5:
                catat_kg = min(belum_dicatat, berat_kg - total_curah)
                baris_otomatis = ByproductStock(
                    jenis_produk="broken", source_type="polishing",
                    source_id=proc.id, berat_kg=catat_kg,
                    tanggal=now.date(), waktu=now, input_by=user.id,
                    jasa_id=jasa_id,
                )
                db.add(baris_otomatis)
                await db.flush()
                await log_activity(
                    db, table_name="byproduct_stock", record_id=baris_otomatis.id,
                    action="INSERT", changed_by=user.id, aksi="broken_catat_otomatis",
                    new_value=f"{proc.kode_proses}: {catat_kg:,.0f} kg dibukukan "
                              "otomatis dari hasil mesin saat 'Masukkan ke "
                              "silo'".replace(",", "."),
                )
                pool.append((baris_otomatis.id, catat_kg))
                total_curah += catat_kg

    # ── Langkah 2 · kurang? bongkar karung FIFO, SEUKURAN karung penuh ──
    #
    # Karung tak bisa dipecah — kekurangan DIBULATKAN KE ATAS ke jumlah
    # karung penuh (`ceil`), dan sisanya (karung yang sudah dibongkar tapi
    # tak terpakai memasuki silo) jadi baris curah TERSENDIRI, tetap berdiri
    # sebagai stok. Karung kosongnya sendiri TIDAK dikembalikan ke Stok
    # Karung — keputusan pemilik 7 Oktober 2026: "tidak dilacak balik".
    if total_curah + 0.5 < berat_kg:
        from math import ceil

        kekurangan = berat_kg - total_curah
        karung_rows = (await db.execute(
            select(FinishedGoodsStock)
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(ProductSku.kategori == "broken",
                   FinishedGoodsStock.source_type == "polishing",
                   FinishedGoodsStock.source_id == proc.id,
                   _milik(FinishedGoodsStock.jasa_id))
            .order_by(FinishedGoodsStock.waktu, FinishedGoodsStock.id)
            .with_for_update()
        )).scalars().all()
        for krow in karung_rows:
            sisa_butuh = kekurangan - dibongkar_kg
            if sisa_butuh <= 0.5:
                break
            ukuran = (await db.execute(
                select(PackageSize.ukuran_kg)
                .join(ProductSku, ProductSku.package_size_id == PackageSize.id)
                .where(ProductSku.id == krow.product_sku_id)
            )).scalar_one_or_none()
            if not ukuran or not krow.jumlah_karung:
                continue
            ambil_karung = min(int(krow.jumlah_karung), ceil(sisa_butuh / float(ukuran)))
            if ambil_karung <= 0:
                continue
            ambil_kg = ambil_karung * float(ukuran)
            krow.jumlah_karung = int(krow.jumlah_karung) - ambil_karung
            krow.berat_total_kg = float(krow.berat_total_kg) - ambil_kg
            if krow.jumlah_karung <= 0:
                await db.delete(krow)
            dibongkar_kg += ambil_kg
        if dibongkar_kg + 0.5 < kekurangan:
            raise Gudang2Error(
                f"{proc.kode_proses} broken (curah + berkarung) tinggal "
                f"{total_curah + dibongkar_kg:,.0f} kg — tak bisa memasukkan "
                f"{berat_kg:,.0f} kg ke silo.".replace(",", "."))
        new_row = ByproductStock(
            jenis_produk="broken", source_type="polishing", source_id=proc.id,
            berat_kg=dibongkar_kg, tanggal=now.date(), waktu=now,
            input_by=user.id, jasa_id=jasa_id,
        )
        db.add(new_row)
        await db.flush()
        await log_activity(
            db, table_name="byproduct_stock", record_id=new_row.id, action="INSERT",
            changed_by=user.id, aksi="broken_bongkar_karung",
            new_value=f"{proc.kode_proses}: {dibongkar_kg:,.0f} kg dibongkar dari "
                      "karung untuk dimasukkan ke silo".replace(",", "."),
        )
        pool.append((new_row.id, dibongkar_kg))

    # ── Langkah 3 · masukkan ke silo, FIFO atas pool (curah lama + baru) ──
    kodes: list[str] = []
    remaining = berat_kg
    for row_id, sisa in pool:
        if remaining <= 0.5:
            break
        take = min(sisa, remaining)
        kode = await next_broken_move_code(db)
        move = BrokenKeSilo(
            kode_pindah=kode, byproduct_stock_id=row_id, silo_id=silo.id,
            berat_kg=take, tanggal=now.date(), waktu=now, input_by=user.id,
            jasa_id=jasa_id,
        )
        db.add(move)
        kodes.append(kode)
        remaining -= take
    await log_activity(
        db, table_name="broken_ke_silo", record_id=proc.id, action="INSERT",
        changed_by=user.id,
        new_value=(f"{proc.kode_proses}: {berat_kg:,.0f}kg → Silo {nama_silo}"
                  + (f" (termasuk {dibongkar_kg:,.0f}kg dari karung)"
                     if dibongkar_kg else "")).replace(",", "."),
    )
    await segarkan_status_silo(db, silo.id)
    await db.commit()
    return MasukkanBrokenResult(
        nama_silo=nama_silo, moved_kg=berat_kg,
        dibongkar_dari_karung_kg=dibongkar_kg, kodes=kodes,
    )


async def masukkan_stok_broken_pemilik_ke_silo(
    db: AsyncSession, *, user: User, jasa_id: int | None, nama_silo: str,
    berat_kg: float, tanggal=None, jam=None,
) -> MasukkanBrokenResult:
    """Ambil broken FIFO dari tumpukan stok milik satu pemilik.

    Asal proses tetap disimpan per baris ledger, tetapi tidak menjadi pilihan
    operator. Satu pemindahan boleh menghabiskan beberapa proses sekaligus.
    """
    from app.penggilingan.inventory.models import ByproductStock, FinishedGoodsStock, ProductSku
    from app.services.stok import output_sosoh

    if not berat_kg or float(berat_kg) <= 0:
        raise Gudang2Error("Sebutkan berat yang masuk silo (kg), lebih dari 0.")

    def milik(col):
        return col.is_(None) if jasa_id is None else col == jasa_id

    process_ids = set((await db.execute(
        select(ByproductStock.source_id).where(
            ByproductStock.jenis_produk == "broken",
            ByproductStock.source_type == "polishing", milik(ByproductStock.jasa_id))
    )).scalars())
    process_ids |= set((await db.execute(
        select(FinishedGoodsStock.source_id)
        .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
        .where(ProductSku.kategori == "broken", FinishedGoodsStock.source_type == "polishing",
               milik(FinishedGoodsStock.jasa_id))
    )).scalars())
    # Broken hasil sosoh yang otomatis dipacking tetap bisa dipindah setelah
    # proses ditutup, walau belum ada baris ByproductStock/FinishedGoodsStock.
    process_ids |= set((await db.execute(
        select(PolishingProcess.id)
        .where(PolishingProcess.status.in_(("proses", "selesai")))
    )).scalars())
    procs = (await db.execute(
        select(PolishingProcess).where(PolishingProcess.id.in_(process_ids))
        .order_by(PolishingProcess.created_at, PolishingProcess.id)
    )).scalars().all() if process_ids else []

    # Stok broken yang diterima dari Timbangan juga merupakan tumpukan biasa.
    # Rencanakan sebagai sumber pertama sebelum hasil sosoh, tetap lewat
    # `pindah_broken_ke_silo` agar ledger dan kepemilikan stok tercatat.
    left = float(berat_kg)
    plan: list[tuple[PolishingProcess, float]] = []
    direct_rows = (await db.execute(
        select(ByproductStock.id, ByproductStock.berat_kg)
        .where(ByproductStock.jenis_produk == "broken",
               ByproductStock.source_type == "timbangan",
               milik(ByproductStock.jasa_id))
        .order_by(ByproductStock.waktu, ByproductStock.id)
    )).all()
    direct_plan: list[tuple[int, float]] = []
    for row_id, gross in direct_rows:
        available = await _sisa_broken_row(db, row_id)
        take = min(left, available)
        if take > 0.5:
            direct_plan.append((row_id, take))
            left -= take
        if left <= 0.5:
            break
    for proc in procs:
        if left <= 0.5:
            break
        rows = (await db.execute(select(ByproductStock.id).where(
            ByproductStock.jenis_produk == "broken", ByproductStock.source_type == "polishing",
            ByproductStock.source_id == proc.id, milik(ByproductStock.jasa_id)
        ))).scalars().all()
        available = sum([await _sisa_broken_row(db, rid) for rid in rows])
        packed = float((await db.execute(
            select(func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(ProductSku.kategori == "broken", FinishedGoodsStock.source_type == "polishing",
                   FinishedGoodsStock.source_id == proc.id, milik(FinishedGoodsStock.jasa_id))
        )).scalar_one())
        from app.services.jasa import pemilik_hasil_proses
        if await pemilik_hasil_proses(db, proc.jasa_id, "broken") == jasa_id:
            # Hasil broken otomatis tersedia setelah proses selesai juga.
            # Saat dipindah, masukkan_broken_ke_silo membukukan bagian yang
            # dipakai sebelum mencatat pemindahannya.
            curah_dibukukan = float((await db.execute(
                select(func.coalesce(func.sum(ByproductStock.berat_kg), 0))
                .where(ByproductStock.jenis_produk == "broken",
                       ByproductStock.source_type == "polishing",
                       ByproductStock.source_id == proc.id,
                       milik(ByproductStock.jasa_id))
            )).scalar_one())
            available += max(0, float((await output_sosoh(db, proc.id)).get("broken") or 0)
                             - curah_dibukukan - packed)
        take = min(left, available + packed)
        if take > 0.5:
            plan.append((proc, take))
            left -= take
        if left <= 0.5:
            break
    if left > 0.5:
        raise Gudang2Error(
            f"Stok broken milik pemilih tinggal {berat_kg-left:,.0f} kg; "
            f"tidak cukup untuk memasukkan {berat_kg:,.0f} kg.".replace(",", "."))

    moved_codes: list[str] = []
    opened_bags = 0.0
    for row_id, take in direct_plan:
        result = await pindah_broken_ke_silo(
            db, user=user, byproduct_stock_id=row_id, nama_silo=nama_silo,
            berat=take, tanggal=tanggal, jam=jam)
        moved_codes.append(result.kode_pindah)
    for proc, take in plan:
        result = await masukkan_broken_ke_silo(
            db, user=user, kode_pol=proc.kode_proses, nama_silo=nama_silo,
            berat_kg=take, jasa_id=jasa_id, tanggal=tanggal, jam=jam)
        opened_bags += result.dibongkar_dari_karung_kg
        moved_codes.extend(result.kodes)
    return MasukkanBrokenResult(nama_silo=nama_silo, moved_kg=float(berat_kg),
                                dibongkar_dari_karung_kg=opened_bags, kodes=moved_codes)


async def masukkan_hasil_samping_ke_silo(
    db: AsyncSession, *, user: User, jenis: str, jasa_id: int | None,
    nama_silo: str, berat_kg: float,
) -> dict:
    """Pindahkan stok Menir/Reject yang masih tersedia dari hasil sosoh ke silo."""
    from app.penggilingan.inventory.models import (
        FinishedGoodsStock, PackageSize, ProductSku)
    from app.services.stok import output_sosoh

    jenis = (jenis or "").strip().lower()
    if jenis not in {"menir", "reject"}:
        raise Gudang2Error("Jenis stok harus Menir atau Reject.")
    if float(berat_kg or 0) <= 0:
        raise Gudang2Error("Berat yang masuk silo harus lebih dari 0 kg.")
    wid = await _g2_warehouse_id(db)
    if not is_operator_gudang2(user, wid):
        raise Gudang2Error("Hanya Operator Gudang 2 atau admin yang dapat memindahkan stok.")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")
    _pastikan_komoditas_silo(silo, jenis)

    procs = (await db.execute(
        select(PolishingProcess).where(PolishingProcess.status.in_(("proses", "selesai")))
        .order_by(PolishingProcess.id)
    )).scalars().all()
    from app.penggilingan.inventory.finished_goods import _packed_kg
    candidates: list[list] = []
    for proc in procs:
        hasil = float((await output_sosoh(db, proc.id)).get(jenis) or 0)
        if hasil <= 0:
            continue
        packed_all = await _packed_kg(db, proc.id, jenis, None)
        packed_owner_q = (select(func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
                          .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
                          .where(FinishedGoodsStock.source_type == "polishing",
                                 FinishedGoodsStock.source_id == proc.id,
                                 ProductSku.kategori == jenis,
                                 (FinishedGoodsStock.jasa_id.is_(None) if jasa_id is None
                                  else FinishedGoodsStock.jasa_id == jasa_id))
                          )
        packed_owner = float((await db.execute(packed_owner_q)).scalar_one())
        curah_owner = max(0.0, hasil - packed_all) if proc.jasa_id == jasa_id else 0.0
        moved = float((await db.execute(
            select(func.coalesce(func.sum(HasilSampingKeSilo.berat_kg), 0))
            .where(HasilSampingKeSilo.polishing_process_id == proc.id,
                   HasilSampingKeSilo.jenis == jenis,
                   (HasilSampingKeSilo.jasa_id.is_(None) if jasa_id is None
                    else HasilSampingKeSilo.jasa_id == jasa_id))
        )).scalar_one())
        candidates.append([proc, max(0.0, curah_owner + packed_owner - moved)])

    milik_keluar = (OutgoingItem.jasa_id.is_(None) if jasa_id is None
                    else OutgoingItem.jasa_id == jasa_id)
    keluar_curah = float((await db.execute(
        select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .where(OutgoingItem.item_type == "byproduct_curah",
               OutgoingItem.jenis_byproduct == jenis, milik_keluar)
    )).scalar_one())
    keluar_karung = float((await db.execute(
        select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .join(ProductSku, ProductSku.id == OutgoingItem.product_sku_id)
        .where(OutgoingItem.item_type == "finished_goods",
               ProductSku.kategori == jenis, milik_keluar)
    )).scalar_one())
    sisa_keluar = keluar_curah + keluar_karung
    # Stok dikeluarkan FIFO; terapkan pengeluaran lama sebelum merencanakan
    # perpindahan baru agar aksi tidak menghabiskan kg yang sudah dikirim.
    for candidate in candidates:
        consumed = min(candidate[1], sisa_keluar)
        candidate[1] -= consumed
        sisa_keluar -= consumed

    sisa_diminta = float(berat_kg)
    rencana: list[tuple[PolishingProcess, float]] = []
    for proc, tersedia in candidates:
        ambil = min(tersedia, sisa_diminta)
        if ambil > 0.005:
            rencana.append((proc, ambil))
            sisa_diminta -= ambil
        if sisa_diminta <= 0.005:
            break
    if sisa_diminta > 0.005:
        raise Gudang2Error(
            f"Stok {jenis.title()} yang masih tersedia hanya "
            f"{float(berat_kg)-sisa_diminta:,.2f} kg.".replace(",", "."))

    await kunci_silo(db, silo.id)
    try:
        jasa_id = await pastikan_satu_pemilik(
            db, user=user,
            jasa_ids=list(await pemilik_silo_g2(db, silo.id)) + [jasa_id])
    except JasaError as e:
        raise Gudang2Error(f"Silo {nama_silo}: {e.args[0]}") from None

    now = input_time(None)
    active = (await db.execute(
        select(PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.silo_id == silo.id,
               PolishingSiloUsage.berat_akhir_kg.is_(None))
    )).scalars().first()
    if active is not None and any(proc.id == active for proc, _ in rencana):
        raise Gudang2Error("Stok hasil proses yang sedang memakai silo ini belum boleh dimasukkan kembali.")
    berat_rencana = sum(kg for _, kg in rencana)
    ke_proses = await _catat_masuk_selama_proses(db, silo.id, berat_rencana)
    if ke_proses and jasa_id is not None:
        raise Gudang2Error(
            f"Silo {nama_silo} sedang disosoh ({ke_proses}); stok jasa tak boleh "
            "ditambahkan ke proses yang berjalan.")

    from app.services.activity_log import log_activity
    prefix = f"HSS-{now:%Y%m%d}"
    existing = (await db.execute(
        select(func.count(HasilSampingKeSilo.id))
        .where(HasilSampingKeSilo.kode_pindah.like(f"{prefix}-%"))
    )).scalar_one()
    codes: list[str] = []
    for index, (proc, kg) in enumerate(rencana, start=1):
        code = f"{prefix}-{int(existing)+index:02d}"
        move = HasilSampingKeSilo(
            kode_pindah=code, polishing_process_id=proc.id, jenis=jenis,
            silo_id=silo.id, berat_kg=kg, tanggal=now.date(), waktu=now,
            input_by=user.id, jasa_id=jasa_id)
        db.add(move)
        await db.flush()
        await log_activity(db, table_name="hasil_samping_ke_silo",
                           record_id=move.id, action="INSERT", changed_by=user.id,
                           new_value=f"{code} | {jenis} {kg:.2f}kg → {silo.nama_silo}"
                                     + (f" | ditambah ke {ke_proses}" if ke_proses else ""))
        codes.append(code)
    await db.commit()
    return {"nama_silo": silo.nama_silo, "moved_kg": float(berat_kg), "codes": codes}


@dataclass
class MasukkanBerasResult:
    nama_silo: str
    moved_kg: float
    dibongkar_dari_karung_kg: float
    kode: str


async def masukkan_beras_ke_silo(
    db: AsyncSession, *, user: User, jenis: str | None,
    kode_pol: str | None = None,
    nama_silo: str | None, berat_kg: float | None, jasa_id: int | None = None,
    sumber_stok: str | None = None, tanggal=None, jam=None,
) -> MasukkanBerasResult:
    """Pindahkan grade beras dari curah atau satu SKU kemasan ke silo.

    Sumber proses tidak dipilih pengguna. Curah dialokasikan FIFO ke proses
    pabrik/pesanan yang menghasilkan grade tersebut; kemasan dialokasikan FIFO
    ke baris stok untuk kombinasi merek (termasuk tanpa merek), bahan kemasan,
    ukuran, dan pemilik yang dipilih. Curah maupun kemasan dapat dipilih.
    Setiap sumber dicatat terpisah di buku pemindahan.
    """
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import (
        _packed_kg, _proc_by_kode, get_standard, sisa_karung_per_sumber)
    from app.penggilingan.inventory.models import FinishedGoodsStock, ProductSku
    from hmu_core import PackageSize
    from app.services.stok import BERAS_JENIS, _dipindah_silo_proc, output_sosoh

    g2_wid = await _g2_warehouse_id(db)
    if not is_operator_gudang2(user, g2_wid):
        raise Gudang2Error(
            "🔒 Memasukkan beras ke silo hanya bisa dilakukan oleh "
            "Operator Gudang 2 (atau admin)."
        )
    if not berat_kg or float(berat_kg) <= 0:
        raise Gudang2Error("Sebutkan berat yang masuk silo (kg), lebih dari 0.")
    berat_kg = float(berat_kg)
    jenis = (jenis or "").strip().lower()
    sumber_stok = (sumber_stok or "").strip()
    # Kompatibilitas pemanggil lama: antarmuka baru selalu mengirim sumber
    # eksplisit, sementara fungsi internal/skrip lama masih dapat mengirim
    # kode proses dan memakai urutan curah lalu kemasan.
    legacy = not sumber_stok and bool(kode_pol)
    if legacy:
        sumber_stok = "legacy"
    if jenis not in BERAS_JENIS:
        raise Gudang2Error("Jenis beras (grade) dari kartu stok tidak valid.")
    if not nama_silo:
        raise Gudang2Error("Sebutkan silo tujuannya.")
    if not sumber_stok:
        raise Gudang2Error("Pilih bentuk stok beras yang akan dipindahkan.")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")
    _pastikan_komoditas_silo(silo, "beras_putih")

    now = input_time(tanggal, jam)
    kategori_sku = "beras_b" if jenis == "beras_b" else "beras_putih"
    std = await get_standard(db, jenis)
    alokasi: dict[int, float] = {}
    baris_karung: list[tuple[FinishedGoodsStock, int]] = []
    rencana_pindah: list[tuple[int | None, str, int | None, int | None, float]] = []
    dibongkar_kg = 0.0

    if sumber_stok == "curah":
        # Curah mengikuti pemilik proses. Angka yang dikemas dari proses itu
        # dikurangi dahulu, lalu sisa curah dialokasikan FIFO lintas proses.
        proses = (await db.execute(
            select(PolishingProcess)
            .where(PolishingProcess.id.in_(select(
                PolishingOutputLog.polishing_process_id).where(
                    PolishingOutputLog.jenis == jenis)),
                   PolishingProcess.jasa_id.is_(None) if jasa_id is None
                   else PolishingProcess.jasa_id == jasa_id)
            .order_by(PolishingProcess.waktu_mulai, PolishingProcess.id)
            .with_for_update()
        )).scalars().all()
        perlu = berat_kg
        for proc in proses:
            hasil = (await output_sosoh(db, proc.id)).get(jenis, 0.0)
            dikemas = await _packed_kg(db, proc.id, kategori_sku,
                                       std.id if std else None)
            dipindah = (await _dipindah_silo_proc(db, [proc.id])).get(
                (proc.id, jenis), 0.0)
            tersedia = max(0.0, float(hasil) - dikemas - dipindah)
            ambil = min(perlu, tersedia)
            if ambil > 0.01:
                alokasi[proc.id] = ambil
                rencana_pindah.append((proc.id, "polishing", proc.id, None, ambil))
                perlu -= ambil
            if perlu <= 0.01:
                break
        if perlu > 0.01:
            raise Gudang2Error(
                f"Stok curah {jenis} untuk pemilik ini tinggal "
                f"{berat_kg - perlu:,.2f} kg; tak cukup untuk "
                f"{berat_kg:,.2f} kg.".replace(",", "."))
    elif sumber_stok == "legacy":
        from math import ceil

        proc = await _proc_by_kode(db, kode_pol)
        if proc is None:
            raise Gudang2Error("Proses penyosohan yang dipilih tidak ditemukan.")
        hasil = (await output_sosoh(db, proc.id)).get(jenis, 0.0)
        dikemas = await _packed_kg(
            db, proc.id, kategori_sku, std.id if std else None)
        dipindah = (await _dipindah_silo_proc(db, [proc.id])).get(
            (proc.id, jenis), 0.0)
        curah = (max(0.0, float(hasil) - dikemas - dipindah)
                 if proc.jasa_id == jasa_id else 0.0)
        ambil_curah = min(berat_kg, curah)
        if ambil_curah > 0:
            rencana_pindah.append((proc.id, "polishing", proc.id, None, ambil_curah))
        perlu = berat_kg - ambil_curah
        ukuran_sku = (await db.execute(
            select(ProductSku.id, PackageSize.ukuran_kg)
            .join(FinishedGoodsStock,
                  FinishedGoodsStock.product_sku_id == ProductSku.id)
            .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
            .where(ProductSku.kategori == kategori_sku,
                   FinishedGoodsStock.source_type == "polishing",
                   FinishedGoodsStock.source_id == proc.id,
                   FinishedGoodsStock.rice_quality_standard_id ==
                   (std.id if std else None),
                   FinishedGoodsStock.jasa_id.is_(None) if jasa_id is None
                   else FinishedGoodsStock.jasa_id == jasa_id)
            .group_by(ProductSku.id, PackageSize.ukuran_kg)
            .order_by(PackageSize.ukuran_kg)
        )).all()
        for sku_id, ukuran_raw in ukuran_sku:
            if perlu <= 0.5:
                break
            ukuran = float(ukuran_raw)
            if ukuran <= 0:
                continue
            sisa = await sisa_karung_per_sumber(
                db, sku_id, std.id if std else None,
                jasa_id=jasa_id, proses_id=proc.id, kunci=True)
            tersedia = sum(jumlah for _, jumlah, _ in sisa)
            butuh_karung = min(tersedia, ceil(perlu / ukuran))
            ambil = butuh_karung
            for row, row_sisa, _ in sisa:
                jumlah = min(ambil, row_sisa)
                if jumlah:
                    baris_karung.append((row, jumlah))
                    rencana_pindah.append((proc.id, "polishing", proc.id,
                                           row.product_sku_id, jumlah * ukuran))
                    ambil -= jumlah
                    if not ambil:
                        break
            kg_karung = butuh_karung * ukuran
            perlu = max(0.0, perlu - kg_karung)
            dibongkar_kg += kg_karung
        if perlu > 0.5:
            raise Gudang2Error(
                f"{proc.kode_proses} {jenis} (curah + kemasan) tinggal "
                f"{curah + dibongkar_kg:,.0f} kg — tak bisa memasukkan "
                f"{berat_kg:,.0f} kg ke silo.".replace(",", "."))
        alokasi[proc.id] = berat_kg
    elif sumber_stok.startswith("sku:"):
        try:
            sku_id = int(sumber_stok.partition(":")[2])
        except ValueError:
            raise Gudang2Error("Pilih merek dan ukuran kemasan yang valid.") from None
        sku = await db.get(ProductSku, sku_id)
        if sku is None or sku.kategori != kategori_sku:
            raise Gudang2Error("Merek dan ukuran kemasan yang dipilih tidak dikenal.")
        ukuran = (await db.execute(
            select(PackageSize.ukuran_kg)
            .where(PackageSize.id == sku.package_size_id)
        )).scalar_one_or_none()
        if not ukuran or float(ukuran) <= 0:
            raise Gudang2Error("Ukuran kemasan beras tidak valid.")
        ukuran = float(ukuran)
        jumlah_karung = round(berat_kg / ukuran)
        berat_pilihan = jumlah_karung * ukuran
        if jumlah_karung <= 0 or abs(berat_pilihan - berat_kg) > 0.01:
            raise Gudang2Error(
                f"Berat dari kemasan {ukuran:g} kg harus kelipatan ukuran tersebut.")
        sumber = await sisa_karung_per_sumber(
            db, sku_id, std.id if std else None, jasa_id=jasa_id,
            source_type=None, kunci=True)
        tersedia = sum(jumlah for _, jumlah, _ in sumber)
        if jumlah_karung > tersedia:
            raise Gudang2Error(
                f"Stok kemasan yang dipilih tinggal {tersedia} karung; "
                f"tak cukup untuk {jumlah_karung} karung.")
        perlu_karung = jumlah_karung
        for row, sisa, _ in sumber:
            ambil = min(perlu_karung, sisa)
            if ambil <= 0:
                continue
            proc_id = row.source_id if row.source_type == "polishing" else None
            if row.source_type == "polishing" and proc_id is None:
                raise Gudang2Error(
                    "Asal proses untuk stok kemasan ini tidak tercatat; "
                    "stok tidak dipindahkan agar riwayat tetap utuh.")
            baris_karung.append((row, ambil))
            rencana_pindah.append((proc_id, row.source_type, row.source_id,
                                   row.product_sku_id, ambil * ukuran))
            if proc_id is not None:
                alokasi[proc_id] = alokasi.get(proc_id, 0.0) + ambil * ukuran
            perlu_karung -= ambil
            if perlu_karung <= 0:
                break
        if perlu_karung:
            raise Gudang2Error("Stok kemasan berubah. Muat ulang daftar lalu coba lagi.")
        dibongkar_kg = berat_pilihan
    else:
        raise Gudang2Error("Pilih curah atau merek dan ukuran kemasan yang tersedia.")

    if (not rencana_pindah
            or abs(sum(item[4] for item in rencana_pindah) - berat_kg) > 0.01):
        raise Gudang2Error("Alokasi sumber stok tidak cocok dengan berat yang diminta.")

    # Satu silo tidak boleh dipakai kembali sebagai sumber hasil proses yang
    # masih memakai silo tersebut. Periksa semua asal FIFO sebelum mengubah stok.
    proses_aktif = set((await db.execute(
        select(PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.silo_id == silo.id,
               PolishingSiloUsage.berat_akhir_kg.is_(None))
    )).scalars().all())
    konflik = proses_aktif.intersection(alokasi)
    if konflik:
        kode = (await db.execute(
            select(PolishingProcess.kode_proses)
            .where(PolishingProcess.id.in_(list(konflik)))
        )).scalars().first()
        raise Gudang2Error(
            f"❌ Beras dari proses {kode or ''} keluar dari proses yang sedang "
            f"memakai Silo {nama_silo}. Pilih silo lain atau tunggu proses selesai.")

    # ── Isi silo tujuan harus SEPEMILIK ──
    await kunci_silo(db, silo.id)
    try:
        jasa_id = await pastikan_satu_pemilik(
            db, user=user, jasa_ids=list(await pemilik_silo_g2(db, silo.id)) + [jasa_id])
    except JasaError as e:
        raise Gudang2Error(f"❌ Silo {nama_silo}: {e.args[0]}") from None

    ke_proses = await _catat_masuk_selama_proses(db, silo.id, berat_kg)
    if ke_proses and jasa_id is not None:
        raise Gudang2Error(
            f"❌ Silo {nama_silo} sedang disosoh ({ke_proses}) — beras jasa "
            "tak boleh ditambahkan ke proses yang berjalan.")

    # Simpan identitas sumber dan penggunaan silo untuk pembatalan tepat satu input.
    usages_sebelum = (await db.execute(select(PolishingSiloUsage).where(
        PolishingSiloUsage.silo_id == silo.id))).scalars().all()
    cuplikan = {"moves": [], "stok": [], "logs_karung": [], "usages": [
        [u.id, None if u.berat_akhir_kg is None else float(u.berat_akhir_kg)]
        for u in usages_sebelum], "usage_aktif": [
        u.id for u in usages_sebelum if u.berat_akhir_kg is None]}
    # Kurangi hanya karung yang dipilih. Asal tiap baris stok tetap ditandai
    # di BerasKeSilo, termasuk stok timbang/retur yang bukan hasil penyosohan.
    for row, ambil in baris_karung:
        cuplikan["stok"].append({
            "id": row.id, "product_sku_id": row.product_sku_id,
            "rice_quality_standard_id": row.rice_quality_standard_id,
            "source_type": row.source_type, "source_id": row.source_id,
            "jumlah_karung": ambil,
            "hpp_per_kg": None if row.hpp_per_kg is None else float(row.hpp_per_kg),
            "warehouse_id": row.warehouse_id, "waktu": row.waktu.isoformat(),
            "input_by": row.input_by, "jasa_id": row.jasa_id,
            "kemasan_mengurangi_stok": row.kemasan_mengurangi_stok,
        })
        sku_row = await db.get(ProductSku, row.product_sku_id)
        size = (await db.execute(
            select(PackageSize.ukuran_kg)
            .where(PackageSize.id == sku_row.package_size_id)
        )).scalar_one()
        cuplikan["stok"][-1]["berat_total_kg"] = min(
            float(row.berat_total_kg), float(size) * ambil)
        row.jumlah_karung -= ambil
        row.berat_total_kg = max(
            0.0, float(row.berat_total_kg) - float(size) * ambil)
        if row.jumlah_karung <= 0:
            # Rincian retur menaut baris stok ini untuk jejak penerimaan.
            # Menghapusnya saat karung terakhir habis melanggar FK dan
            # membatalkan seluruh pemindahan. Pertahankan saldo nolnya.
            from app.penggilingan.inventory.models import CustomerReturnItem
            tertaut_retur = await db.scalar(select(CustomerReturnItem.id).where(
                CustomerReturnItem.finished_goods_stock_id == row.id).limit(1))
            if tertaut_retur is None:
                await db.delete(row)
        await log_activity(
            db, table_name="finished_goods_stock", record_id=row.id,
            action="UPDATE", changed_by=user.id, aksi="beras_bongkar_karung",
            new_value=(f"{ambil} karung SKU {row.product_sku_id} · "
                       f"{float(size):g} kg dipindah ke silo").replace(",", "."),
        )

        await db.flush()
        from app.models import ActivityLog
        child_id = (await db.execute(select(ActivityLog.id).where(
            ActivityLog.aksi == "beras_bongkar_karung",
            ActivityLog.record_id == row.id, ActivityLog.changed_by == user.id,
        ).order_by(ActivityLog.id.desc()).limit(1))).scalar_one()
        cuplikan["logs_karung"].append(child_id)

    codes: list[str] = []
    for proc_id, source_type, source_id, sku_id, kg in rencana_pindah:
        proc = await db.get(PolishingProcess, proc_id) if proc_id is not None else None
        if proc_id is not None and proc is None:
            raise Gudang2Error("Asal proses stok tidak ditemukan; perpindahan dibatalkan.")
        kode = await next_beras_move_code(db)
        move = BerasKeSilo(
            kode_pindah=kode, polishing_process_id=proc_id,
            source_type=source_type, source_id=source_id,
            product_sku_id=sku_id, jenis=jenis,
            silo_id=silo.id, berat_kg=kg, tanggal=now.date(), waktu=now,
            input_by=user.id, jasa_id=jasa_id,
        )
        db.add(move)
        codes.append(kode)
        await db.flush()
        cuplikan["moves"].append(move.id)

    await log_activity(
        db, table_name="beras_ke_silo", record_id=cuplikan["moves"][0],
        action="INSERT", changed_by=user.id, aksi="beras_masuk_silo",
        old_value=json.dumps(cuplikan),
        new_value=f"{', '.join(codes)} {jenis}: {berat_kg:g} kg → Silo {nama_silo}",
    )

    await segarkan_status_silo(db, silo.id)
    await db.commit()
    return MasukkanBerasResult(
        nama_silo=nama_silo, moved_kg=berat_kg,
        dibongkar_dari_karung_kg=dibongkar_kg,
        kode=", ".join(codes),
    )


@dataclass
class PindahPoolResult:
    nama_silo: str
    moved_kg: float
    kodes: list[str]
    sisa_tumpukan: float


async def pindah_tumpukan(
    db: AsyncSession, *, user: User, nama_silo: str | None, berat: float | None = None,
    tanggal=None, jam=None, jumlah_karung: int | None = None, hasil_timbang: bool = False,
) -> PindahPoolResult:
    """Pindahkan PK dari tumpukan ke silo (FIFO antar intake tumpukan).

    HANYA operator Gudang 2 (admin fallback). `berat` None = pindah semua tumpukan.
    """
    g2_wid = await _g2_warehouse_id(db)
    if not is_operator_gudang2(user, g2_wid):
        raise Gudang2Error(
            "🔒 Pemindahan tumpukan ke silo hanya bisa dilakukan oleh "
            "Operator Gudang 2 (atau admin)."
        )
    if not nama_silo:
        raise Gudang2Error("Sebutkan silo tujuannya (A atau B).")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")

    intakes = (
        await db.execute(
            select(PkGudang2Intake)
            .where(PkGudang2Intake.tujuan == "ditumpuk")
            .order_by(PkGudang2Intake.id)
        )
    ).scalars().all()
    if jumlah_karung is None and berat is None:
        berkarung = []
        for it in intakes:
            batch = await db.get(PkPurchaseBatch,it.pk_purchase_batch_id) if it.pk_purchase_batch_id else None
            if batch and batch.jumlah_karung:
                berkarung.append(it.id)
        if berkarung:
            hasil = []
            for it in intakes:
                sisa = await _sisa_tumpukan_intake(db,it.id)
                if sisa is not None and sisa <= 0:
                    continue
                hasil.append(await pindah_tumpukan_ke_silo(db,user=user,intake_id=it.id,
                    nama_silo=nama_silo,tanggal=tanggal,jam=jam,commit=False))
            await db.commit()
            bobot = None if any(h.berat_kg is None for h in hasil) else sum(h.berat_kg for h in hasil)
            return PindahPoolResult(nama_silo,bobot,[h.kode_pindah for h in hasil],await hitung_stok_tumpukan(db))
    if jumlah_karung is not None:
        if berat is not None or isinstance(jumlah_karung, bool) or int(jumlah_karung) != jumlah_karung or jumlah_karung <= 0:
            raise Gudang2Error("Isi jumlah karung bulat lebih dari nol tanpa kg sekaligus.")
        # Kunci seluruh sumber dalam urutan yang sama sebelum membaca saldo.
        # R tidak pernah digabung: satu baris hasil untuk tiap partai asalnya.
        intakes = (await db.execute(select(PkGudang2Intake).where(
            PkGudang2Intake.tujuan == DITUMPUK).order_by(PkGudang2Intake.id)
            .with_for_update())).scalars().all()
        alokasi = []
        for it in intakes:
            batch = await db.get(PkPurchaseBatch, it.pk_purchase_batch_id) if it.pk_purchase_batch_id else None
            if not batch or not batch.jumlah_karung:
                continue
            k = await db.scalar(select(func.coalesce(func.sum(PkTumpukanToSilo.jumlah_karung), 0)).where(
                PkTumpukanToSilo.pk_gudang2_intake_id == it.id))
            tersedia = batch.jumlah_karung - int(k)
            r = bobot_per_karung(batch)
            sisa = await _sisa_tumpukan_intake(db,it.id)
            if r and sisa is not None:
                tersedia = min(tersedia, int((Decimal(str(sisa)) + Decimal("0.000001")) // r))
            if tersedia > 0:
                alokasi.append((it, tersedia))
        total = sum(k for _,k in alokasi)
        if jumlah_karung > total:
            raise Gudang2Error(f"Tinggal {total} karung, tak bisa memasukkan {jumlah_karung} karung.")
        perlu = jumlah_karung
        hasil = []
        for it,k in alokasi:
            if not perlu:
                break
            ambil = min(k,perlu)
            hasil.append(await pindah_tumpukan_ke_silo(db,user=user,intake_id=it.id,
                nama_silo=nama_silo,jumlah_karung=ambil,tanggal=tanggal,jam=jam,commit=False))
            perlu -= ambil
        await db.commit()
        return PindahPoolResult(nama_silo, None if any(h.berat_kg is None for h in hasil) else sum(h.berat_kg for h in hasil),
            [h.kode_pindah for h in hasil], await hitung_stok_tumpukan(db))
    pool: list[tuple[PkGudang2Intake, float]] = []
    for it in intakes:
        sisa = await _sisa_tumpukan_intake(db, it.id)
        if sisa is None:
            raise Gudang2Error(
                "Bobot PK di tumpukan ini belum diketahui — truknya belum ditimbang "
                "kedua. Tunggu timbangnya, lalu pindahkan.")
        if sisa > 0:
            pool.append((it, sisa))
    total_sisa = sum(s for _, s in pool)
    if total_sisa <= 0:
        raise Gudang2Error("Tumpukan Gudang 2 kosong — tidak ada yang bisa dipindah.")
    if berat is not None and float(berat) > total_sisa:
        raise Gudang2Error(
            f"Berat pindah ({float(berat):.0f} kg) melebihi total tumpukan "
            f"({total_sisa:.0f} kg)."
        )
    target = total_sisa if berat is None else float(berat)

    now = input_time(tanggal, jam)
    moved = 0.0
    kodes: list[str] = []
    remaining = target
    for it, sisa in pool:
        if remaining <= 0:
            break
        take = min(sisa, remaining)
        move, _ = await _catat_pindah(db, user=user, intake=it, silo=silo, nama_silo=nama_silo,
                                      kirim=take, now=now, hasil_timbang=hasil_timbang)
        kodes.append(move.kode_pindah)
        moved += take
        remaining -= take
    await db.commit()
    return PindahPoolResult(
        nama_silo=nama_silo, moved_kg=moved, kodes=kodes,
        sisa_tumpukan=total_sisa - moved,
    )


# ─────────────────────────── Laporan stok ───────────────────────────
def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


async def laporan_stok_gudang2(
    db: AsyncSession, nama_silo: str | None = None, financial: bool = True
) -> str:
    """Stok PK Gudang 2: silo A/B (+ HPP wavg bila boleh) + tumpukan."""
    lines = ["🏭 Stok PK Gudang 2:"]
    letters = [nama_silo.upper()] if nama_silo else ["A", "B"]
    for letter in letters:
        silo = await get_g2_silo(db, letter)
        if silo is None:
            lines.append(f"• Silo {letter}: (tidak ditemukan)")
            continue
        stok = await hitung_stok_silo(db, silo.id)
        cap = (
            f" / maks {float(silo.kapasitas_ton):g} ton"
            if silo.kapasitas_ton is not None else ""
        )
        # "HPP rata2" DIBUANG 28 September 2026 bersama seluruh harga. Tak
        # disebut brief QA, tetapi akibatnya sama: sumbernya `intake.hpp_per_kg`,
        # yang kini selalu None — baris itu akan hilang diam-diam untuk PK baru
        # dan tetap muncul untuk PK lama, jadi dua silo bersebelahan menjawab
        # pertanyaan yang sama dengan cara yang berbeda.
        lines.append(f"• Silo {letter}: {_kg(stok)}{cap}")
    if not nama_silo:
        tump = await hitung_stok_tumpukan(db)
        # ── NOL DI SINI BERARTI TAK BERBATAS, BUKAN KAPASITAS NOL ──
        #
        # Keputusan pemilik 12 September 2026: tumpukan Gudang 2 tidak
        # berbatas, dan `g2_tumpukan_maks_kg` bawaannya 0 — lihat alasannya di
        # `_pastikan_muat_tumpukan` di atas, yang sudah memperlakukannya benar
        # (`if not cap: return`).
        #
        # Baris ini satu-satunya yang membacanya tanpa pagar, dan hasilnya
        # layar berbunyi "maks 0 ton" sambil tumpukannya berisi — kalimat yang
        # mengaku kapasitasnya nol padahal barangnya berdiri di situ. Tiga
        # pembaca lain sudah berpagar: `stok.py` (`or None`), `beranda.py`
        # (`if maks and ...`), `layar.py` (`if maks else ""`).
        #
        # ⚠ Yang dibetulkan TAMPILANNYA, bukan nilainya — pemilik: "jangan ada
        # batasan berapa ton".
        maks = float(settings.g2_tumpukan_maks_kg or 0)
        batas = f" / maks {maks / 1000:g} ton" if maks else ""
        lines.append(f"• Tumpukan: {_kg(tump)}{batas}")
    return "\n".join(lines)


async def _sisa_karung_setelah_keluar(db, intake, nilai):
    """Pengeluaran tetap kg, tetapi karung yang sudah diambil tak boleh
    dipindah lagi ke silo. Gunakan FIFO pemilik yang sama dengan kartu stok,
    tanpa mengubah satu baris barang keluar atau menskalakan transfer G1.
    """
    batch = await db.get(PkPurchaseBatch,intake.pk_purchase_batch_id) if intake.pk_purchase_batch_id else None
    if not batch or not batch.jumlah_karung or nilai is None:
        return None if nilai is None else float(nilai)
    keluar = await db.scalar(select(func.coalesce(func.sum(OutgoingItem.berat_kg),0)).where(
        OutgoingItem.item_type == "pk_g2",OutgoingItem.silo_id.is_(None),
        OutgoingItem.jasa_id.is_(None) if intake.jasa_id is None else OutgoingItem.jasa_id == intake.jasa_id))
    if not keluar:
        return float(nilai)
    sumber = (await db.scalars(select(PkGudang2Intake).where(
        PkGudang2Intake.tujuan == DITUMPUK,
        PkGudang2Intake.jasa_id.is_(None) if intake.jasa_id is None else PkGudang2Intake.jasa_id == intake.jasa_id)
        .order_by(PkGudang2Intake.waktu_masuk,PkGudang2Intake.id))).all()
    saldo = await sisa_tumpukan_banyak(db,sumber)
    sisa_keluar = Decimal(str(keluar))
    for it in sumber:
        kotor = saldo[it.id]
        ambil = min(max(kotor or Decimal(0),Decimal(0)),sisa_keluar)
        sisa_keluar -= ambil
        if it.id == intake.id:
            return float(kotor - ambil)
    return float(nilai)
