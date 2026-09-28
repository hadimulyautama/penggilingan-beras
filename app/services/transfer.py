"""Logika bisnis transfer internal Gudang 1 -> Gudang 2 + HPP snapshot PK."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import now_local
from app.models import (
    InternalTransfer,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
)
from app.models.peristiwa import PK_DIPINDAH_G1G2
from app.services import peristiwa as buku
from app.services.activity_log import log_activity
from app.services.codegen import next_transfer_code
from app.penggilingan.gudang1.services.milling import pk_jenis

# Tak ada lagi kamus nama silo di sini: labelnya dibaca dari MASTER lewat
# `gudang2.service.label_tujuan`, dan tujuannya dinormalisasi lewat
# `_tujuan_and_silo` yang sama dengan jalan PK luar. Kamus lama melempar
# `KeyError` — 500, halaman putih tanpa sebab — pada silo yang belum
# dikenalnya. Migrasi 0057.


class TransferError(Exception):
    """Kesalahan transfer dengan pesan siap-tampil (args[0])."""


# `hpp_per_kg_pk` DIBUANG 28 September 2026: harga keluar dari Pos Produksi
# (keputusan pemilik). Ia berdiri di atas `costing.production_cost`, yang
# berdiri di atas harga gabah terverifikasi — dan verifikasi harga gabah sudah
# tak ada lagi di sini.
#
# `internal_transfers.hpp_per_kg` TIDAK dijatuhkan: baris lama memuat HPP
# sungguhan dan itu riwayat. Yang baru ditulis None — kolom yang diisi angka
# palsu lebih buruk daripada kolom kosong, sebab yang kosong terbaca sebagai
# "tak diketahui" dan yang palsu terbaca sebagai fakta.


#: Berapa PK dihasilkan sebuah giling — SATU jawaban untuk seluruh aplikasi.
#:
#: Dulu ditulis ulang di sini, membaca progres operator saja. Dua jawaban untuk
#: satu pertanyaan akan berselisih cepat atau lambat, dan yang salah adalah
#: yang lebih jarang dibaca — di sini artinya PK terverifikasi yang tak bisa
#: dikirim ke Gudang 2 karena stoknya terbaca nol.
from app.penggilingan.gudang1.services.milling import _produced_pk  # noqa: E402


async def _transferred_pk(db: AsyncSession, proc_id: int) -> float:
    r = (
        await db.execute(
            select(func.coalesce(func.sum(InternalTransfer.berat_kg), 0)).where(
                InternalTransfer.milling_process_id == proc_id,
                InternalTransfer.status == "terkirim",
            )
        )
    ).scalar_one()
    return float(r)


async def _sold_pk_langsung(db: AsyncSession, proc_id: int) -> float:
    """PK yang sudah DIJUAL LANGSUNG dari Gudang 1 (barang keluar pk_langsung)."""
    from app.models import OutgoingItem
    r = (
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0)).where(
                OutgoingItem.item_type == "pk_langsung",
                OutgoingItem.milling_process_id == proc_id,
            )
        )
    ).scalar_one()
    return float(r)


async def saldo_pk(db: AsyncSession, proc_id: int) -> float:
    """Saldo PK apa adanya — BOLEH NEGATIF.

    `pending_transfer_kg` memotongnya di nol, dan pemotongan itulah yang
    menyembunyikan temuan QA P-K-06: 6 ton PK terkirim 12 ton, dan yang
    terbaca di layar "0" — bukan "−6.000". Yang disembunyikan tak bisa
    diperbaiki siapa pun, karena tak ada yang tahu ia ada.

    Dipakai penjaga dan Rekonsiliasi. Yang ditampilkan ke operator tetap
    lewat `pending_transfer_kg`: angka negatif di layar "stok siap kirim" akan
    dibaca sebagai kerusakan aplikasi, bukan sebagai selisih yang perlu
    ditelusuri — dan yang menelusurinya bukan operator.
    """
    return (
        await _produced_pk(db, proc_id)
        - await _transferred_pk(db, proc_id)
        - await _sold_pk_langsung(db, proc_id)
    )


async def pending_transfer_kg(db: AsyncSession, proc_id: int) -> float:
    """PK tersedia (stok) = produksi − yang ditransfer − yang dijual langsung.

    Dipotong di nol untuk TAMPILAN saja. Yang memeriksa kelebihan memakai
    `saldo_pk`, yang tak memotong apa pun.
    """
    return max(await saldo_pk(db, proc_id), 0.0)


async def _transfer_dari_kunci(db: AsyncSession, kunci_kiriman: str) -> InternalTransfer | None:
    """Cermin transfer dari peristiwa berkunci ini — untuk kiriman ulang."""
    from app.models import Peristiwa

    return (await db.execute(
        select(InternalTransfer).join(Peristiwa, Peristiwa.id == InternalTransfer.peristiwa_id)
        .where(Peristiwa.kunci_kiriman == kunci_kiriman)
    )).scalars().first()


@dataclass
class TransferResult:
    transfer: InternalTransfer
    kode_proses: str
    lokasi_label: str
    hpp_per_kg: float | None
    jenis: str | None = None  # KS / KL / MIX


async def create_internal_transfer(
    db: AsyncSession, *, user, kode_proses: str, lokasi_tujuan: str,
    berat: float | None = None, kunci_kiriman: str | None = None,
) -> TransferResult:
    """Kirim PK dari sebuah milling ke Gudang 2. Mengurangi stok siap kirim.

    `berat` opsional: bila tidak disebut, kirim SEMUA stok yang tersedia.

    **Jalur PERISTIWA (Tahap 3, aksi keempat) — dua kejadian, SATU
    transaksi:** kunci proses (FOR UPDATE) → saldo → nomor atomik → peristiwa
    `pk_dipindah_g1g2` (kunci kiriman idempoten) → proyeksi → cermin
    `internal_transfers` → jejak → `_add_intake` (peristiwa `pk_masuk_g2` +
    cermin intake, TANPA commit) → commit sekali. Gagal di mana pun = tak
    ada yang tersimpan, termasuk nomornya.
    """
    # Tujuannya dinormalisasi lewat jalan yang SAMA dengan PK luar: satu
    # jawaban untuk "tempat mana di Gudang 2", dan satu daftar yang tumbuh
    # bersama master. Yang tersimpan JENIS-nya (`silo`/`ditumpuk`); silo mana
    # jadi rujukan di `silo_id`.
    from app.penggilingan.gudang2.service import (
        Gudang2Error as _G2Error, _tujuan_and_silo, label_tujuan)

    try:
        lokasi_tujuan, silo_tujuan_id = await _tujuan_and_silo(db, lokasi_tujuan)
    except _G2Error as e_:
        raise TransferError(e_.args[0] if e_.args else "Tujuan tidak dikenali.")
    # ── Prosesnya DIKUNCI sebelum saldonya dibaca ──
    #
    # Tanpa kunci, dua transfer yang datang bersamaan sama-sama membaca
    # "tersedia 6 ton" sebelum salah satunya menulis — lalu keduanya
    # mengirim 6 ton, dan 6 ton PK berubah jadi 12 ton di Gudang 2. Temuan QA
    # P-K-06, dan kelebihannya tak terlihat karena saldonya dipotong di nol.
    proc = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.kode_proses == kode_proses)
            .with_for_update()
        )
    ).scalars().first()
    if proc is None:
        raise TransferError(f"Proses {kode_proses} tidak ditemukan.")

    tersedia = await pending_transfer_kg(db, proc.id)
    if tersedia <= 0:
        raise TransferError(
            f"Tidak ada stok PK dari {kode_proses} untuk dikirim "
            "(hasil giling belum dicatat, atau semua sudah terkirim)."
        )
    kirim = tersedia if berat is None else min(float(berat), tersedia)

    # Sejak harga keluar dari Pos Produksi, tak ada lagi yang bisa
    # menghitungnya di sini — lihat catatan di atas.
    hpp = None
    jenis = await pk_jenis(db, proc)
    now = now_local()

    if kunci_kiriman:
        ada = await _transfer_dari_kunci(db, kunci_kiriman)
        if ada is not None:
            return TransferResult(transfer=ada, kode_proses=kode_proses,
                                  lokasi_label=await label_tujuan(
                                      db, ada.lokasi_tujuan, ada.silo_id),
                                  hpp_per_kg=float(ada.hpp_per_kg) if ada.hpp_per_kg is not None else None,
                                  jenis=jenis)
    else:
        n = await buku.jumlah_jenis(db, PK_DIPINDAH_G1G2, "milling_process_id", proc.id)
        kunci_kiriman = f"{PK_DIPINDAH_G1G2}:proses:{proc.id}:{n + 1}"

    kode_transfer = await next_transfer_code(db)
    muatan = {
        "kode_transfer": kode_transfer, "milling_process_id": proc.id, "kode_proses": kode_proses,
        "drying_lot_id": proc.drying_lot_id, "berat_kg": kirim,
        "lokasi_tujuan": lokasi_tujuan, "silo_id": silo_tujuan_id,
        "hpp_per_kg": hpp, "jenis": jenis, "tanggal": now.date(), "waktu": now,
    }
    e = await buku.catat(db, jenis=PK_DIPINDAH_G1G2, pelaku_id=user.id, kunci_kiriman=kunci_kiriman,
                         muatan=muatan, waktu=now)
    if not e.baru:
        ada = await _transfer_dari_kunci(db, kunci_kiriman)
        if ada is not None:
            return TransferResult(
                transfer=ada, kode_proses=kode_proses,
                lokasi_label=await label_tujuan(db, ada.lokasi_tujuan, ada.silo_id),
                hpp_per_kg=hpp, jenis=jenis)

    transfer = InternalTransfer(
        kode_transfer=kode_transfer,
        milling_process_id=proc.id,
        drying_lot_id=proc.drying_lot_id,
        berat_kg=kirim,
        lokasi_tujuan=lokasi_tujuan,
        silo_id=silo_tujuan_id,
        hpp_per_kg=hpp,
        waktu=now,
        created_by=user.id,
        status="terkirim",
        peristiwa_id=e.id,
    )
    db.add(transfer)
    await db.flush()
    getattr(e, "proyeksi", None) and setattr(e.proyeksi, "transfer_id", transfer.id)
    await log_activity(
        db, table_name="internal_transfers", record_id=transfer.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{transfer.kode_transfer} | {kirim:.0f}kg -> "
                  f"{await label_tujuan(db, lokasi_tujuan, silo_tujuan_id)} | hpp={hpp}",
    )
    # PK LANGSUNG masuk stok Gudang 2 — staff/admin sudah menentukan tujuan saat
    # kirim, jadi tak perlu langkah 'terima' terpisah oleh operator G2.
    # (_add_intake menjalankan guard kapasitas tumpukan lalu commit.)
    from app.penggilingan.gudang2.service import Gudang2Error, _add_intake
    try:
        await _add_intake(
            # Disebut dengan NAMA silonya, bukan dengan kata golongannya:
            # `_add_intake` menormalisasi sendiri lewat master, dan "silo"
            # tanpa nama tak bisa dicari di sana.
            db, user=user, sumber_tipe="transfer_internal",
            tujuan=(await label_tujuan(db, lokasi_tujuan, silo_tujuan_id)
                    if silo_tujuan_id is not None else lokasi_tujuan),
            berat_kg=kirim, hpp_per_kg=hpp, tanggal=None, jam=None,
            internal_transfer_id=transfer.id, transfer_peristiwa_id=e.id, commit=False,
        )
    except Gudang2Error as e_:  # mis. tumpukan G2 penuh → seluruh transaksi batal
        raise TransferError(e_.args[0] if e_.args else "Gagal memasukkan PK ke Gudang 2.")
    # ── Permintaan TIDAK lagi ditutup di sini ──
    #
    # Sampai 25 September 2026 baris ini menutupnya: status 'selesai', sebab
    # "Transfer dicatat.". Akibatnya permintaan menutup DIRINYA SENDIRI di
    # langkah ketiga, dan Admin tak pernah kebagian menutupnya — padahal
    # penutupan itulah yang pemilik jadikan langkah keempat, lengkap dengan
    # hak membetulkan bobotnya.
    #
    # Yang menggantikannya: `permintaan_pk.kirim` menandai barisnya `dikirim`
    # dan menyimpan `internal_transfer_id` — di transaksi yang SAMA dengan
    # transfer ini, sebab ia yang memanggil fungsi ini. Alasan lama tetap
    # berlaku dan sengaja diulang di sana: perubahan keadaan harus ikut commit
    # yang sama, kalau tidak ada jeda di mana transfernya sudah tercatat
    # sementara kartunya masih menawarkan pekerjaan yang sudah dikerjakan.
    #
    # Transfer yang BUKAN dari permintaan tetap sah dan tetap lewat sini:
    # Admin masih boleh memindahkan atas inisiatifnya sendiri.
    await db.commit()
    await db.refresh(transfer)
    return TransferResult(
        transfer=transfer, kode_proses=kode_proses,
        lokasi_label=await label_tujuan(db, lokasi_tujuan, silo_tujuan_id),
        hpp_per_kg=hpp, jenis=jenis,
    )


# ─────────────────────────── Laporan ───────────────────────────
def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


async def laporan_pk_siap_transfer(db: AsyncSession) -> str:
    """PK yang menumpuk di Gudang 1 — dan karena itu juga yang siap dikirim.

    Dua sebutan untuk satu tumpukan yang sama. "Menumpuk" adalah tempatnya,
    "siap kirim" adalah apa yang bisa dilakukan padanya; keduanya tak pernah
    berbeda isinya, karena PK meninggalkan lantai Gudang 1 tepat pada saat
    transfernya dicatat.

    Diurut yang PALING LAMA MENUNGGU lebih dulu. Tumpukan yang cuma disebut
    jumlahnya tak bisa ditindaklanjuti: yang perlu diputuskan adalah lot mana
    yang berangkat duluan, dan jawabannya hampir selalu yang paling lama
    menunggu.
    """
    from app.penggilingan.gudang1.services.milling import (
        pk_breakdown_banyak,
        pk_jenis_banyak,
    )

    procs = list((await db.execute(
        select(MillingProcess).order_by(MillingProcess.kode_proses)
    )).scalars().all())
    # Sisa per proses dihitung sekali untuk semuanya; jenis PK hanya dicari
    # untuk yang benar-benar punya sisa. Temuan QA P-S-02.
    rincian = await pk_breakdown_banyak(db, [p.id for p in procs])
    punya = [p for p in procs if rincian[p.id].tersedia > 0]
    peta_jenis = await pk_jenis_banyak(db, punya)

    items: list[tuple[str, str | None, float, float | None]] = []
    for p in punya:
        avail = rincian[p.id].tersedia
        sejak = p.waktu_selesai or p.waktu_mulai
        hari = ((now_local() - sejak).total_seconds() / 86400) if sejak else None
        items.append((p.kode_proses, peta_jenis.get(p.id), avail, hari))
    if not items:
        return "🚚 Lantai PK Gudang 1 kosong — tidak ada yang menunggu dikirim."
    items.sort(key=lambda it: (it[3] is None, -(it[3] or 0)))

    total = sum(a for _, _, a, _ in items)
    sub: dict[str, float] = {}
    for _, jenis, a, _ in items:
        sub[jenis or "?"] = sub.get(jenis or "?", 0.0) + a
    ringkas = " · ".join(f"{j} {_kg(v)}" for j, v in sorted(sub.items()))
    cap = settings.g1_pk_tumpukan_maks_kg
    lines = [
        f"🚚 PK menumpuk di Gudang 1: {_kg(total)}"
        + (f" / maks {cap / 1000:g} ton" if cap else "")
        + f"  ({ringkas})"
    ]
    for kode, jenis, a, hari in items:
        umur = f" · menunggu {hari:.0f} hari" if hari is not None else ""
        lines.append(f"• {jenis or '-'} dari {kode}: {_kg(a)}{umur}")
    if cap and total > cap:
        lines.append(
            f"⚠️ Melewati batas lantai {cap / 1000:g} ton — kirim ke gudang penyosohan."
        )
    return "\n".join(lines)


async def laporan_transfer(db: AsyncSession, financial: bool = True) -> str:
    """Riwayat transfer internal (terbaru dulu). HPP hanya untuk staff/admin."""
    from app.penggilingan.gudang2.service import label_tujuan

    rows = (
        await db.execute(
            select(InternalTransfer, MillingProcess)
            .join(MillingProcess, MillingProcess.id == InternalTransfer.milling_process_id)
            .order_by(InternalTransfer.id.desc())
            .limit(10)
        )
    ).all()
    if not rows:
        return "🚚 Belum ada transfer ke Gudang 2."
    lines = ["🚚 Transfer terakhir ke Gudang 2:"]
    for t, proc in rows:
        hpp = (
            f" · HPP {_rp(float(t.hpp_per_kg))}/kg"
            if financial and t.hpp_per_kg is not None
            else ""
        )
        jenis = await pk_jenis(db, proc)
        jlbl = f"{jenis} " if jenis else ""
        lines.append(
            f"• {t.kode_transfer}: {jlbl}{_kg(float(t.berat_kg))} dari {proc.kode_proses} "
            f"→ {await label_tujuan(db, t.lokasi_tujuan, t.silo_id)}{hpp}"
        )
    return "\n".join(lines)
