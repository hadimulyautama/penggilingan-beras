"""Logika Gudang 2 (Penyosohan) — PK masuk, silo/tumpukan, pindah tumpukan→silo.

Acuan WAJIB: LOGIKA_SILO_GUDANG2.md.
- Silo G2 = KOLAM CAMPURAN (banyak sumber).
- Stok silo/tumpukan DITURUNKAN (bukan kolom saldo).
- Tumpukan WAJIB masuk silo dulu sebelum disosoh.
- Pindah tumpukan→silo HANYA operator Gudang 2 (admin fallback), bisa parsial, cap 60t.
- HPP silo = weighted-average bahan yang SUDAH di silo (kecuali HPP belum tersedia).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.peran import PERAN_ADMIN_KEATAS
from app.config import settings
from app.database import input_time
from app.models import (
    InternalTransfer,
    PkGudang2Intake,
    PkPurchaseBatch,
    PkPurchaseVerification,
    PkRejection,
    PkTumpukanToSilo,
    PolishingSiloUsage,
    Silo,
    Supplier,
    User,
    Warehouse,
)
from app.models.peristiwa import PK_LUAR_MASUK, PK_MASUK_G2, PK_TUMPUKAN_KE_SILO
from app.services import peristiwa as buku
from app.services.activity_log import log_activity
from app.services.codegen import (
    next_pk_purchase_code,
    next_rejection_code,
    next_tumpukan_move_code,
)
from app.services.notification import create_notification
from app.penggilingan.gudang1.services.purchase import find_or_create_supplier
from app.penggilingan.gudang1.services.bobot import dari_batch
from app.penggilingan.gudang1.services.timbang_link import bobot_awal_dari_tiket
from app.penggilingan.gudang1.services.timbang_link import (
    TiketSudahDipakai,
    ambil_tiket,
    kunci_tiket_untuk_ditaut,
)
from app.penggilingan.peta_jenis import intake_dari_jenis

#: JENIS tempat PK di Gudang 2. Yang disimpan ini, bukan nama silonya —
#: silo MANA ada di kolom `silo_id`. Lihat migrasi 0057.
SILO, DITUMPUK = "silo", "ditumpuk"

#: Kata LAMA yang masih berdiri di baris sebelum 24 September 2026, dan masih
#: dikirim halaman yang belum dimuat ulang. Diterima saat MEMBACA masukan,
#: tidak pernah ditulis lagi.
_KATA_LAMA = {"silo_a": "A", "silo_b": "B"}


class Gudang2Error(Exception):
    """Kesalahan Gudang 2 dengan pesan siap-tampil (args[0])."""


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
            select(Warehouse.id).where(Warehouse.nama_gudang.like("Gudang 2%"))
        )
    ).scalars().first()
    if wid is None:
        raise Gudang2Error("Data Gudang 2 belum ada.")
    return wid


async def get_g2_silo(db: AsyncSession, letter: str) -> Silo | None:
    wid = await _g2_warehouse_id(db)
    return (
        await db.execute(
            select(Silo).where(
                Silo.warehouse_id == wid, Silo.nama_silo == f"Silo {letter}"
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
    huruf = _KATA_LAMA.get(teks.lower(), teks)
    huruf = huruf[5:].strip() if huruf.lower().startswith("silo ") else huruf
    return await get_g2_silo(db, huruf.upper())


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


async def hitung_stok_silo(db: AsyncSession, silo_id: int) -> float:
    """Stok PK sebuah silo G2 = masuk langsung + masuk dari tumpukan − terpakai."""
    masuk_langsung = (
        await db.execute(
            select(func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0)).where(
                # Disaring dengan `silo_id` SAJA. Menambahkan syarat atas
                # kata tujuannya akan membuang baris silo ketiga tanpa satu
                # pun galat — silonya berisi, tetapi stoknya terbaca 0, lalu
                # ia hilang dari borang. Itu jenis kerusakan yang paling sulit
                # dilihat: tak ada yang salah di layar mana pun.
                PkGudang2Intake.silo_id == silo_id,
            )
        )
    ).scalar_one()
    masuk_dari_tumpukan = (
        await db.execute(
            select(func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0)).where(
                PkTumpukanToSilo.silo_id == silo_id
            )
        )
    ).scalar_one()
    # Terpakai penyosohan (hanya proses yang berat_akhir-nya sudah diisi).
    terpakai = (
        await db.execute(
            select(func.coalesce(func.sum(PolishingSiloUsage.berat_terpakai_kg), 0)).where(
                PolishingSiloUsage.silo_id == silo_id,
                PolishingSiloUsage.berat_akhir_kg.isnot(None),
            )
        )
    ).scalar_one()
    return float(masuk_langsung) + float(masuk_dari_tumpukan) - float(terpakai)


async def hitung_stok_tumpukan(db: AsyncSession) -> float:
    """Stok tumpukan G2 = total masuk sbg tumpukan − total sudah dipindah ke silo."""
    masuk = (
        await db.execute(
            select(func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0)).where(
                PkGudang2Intake.tujuan == "ditumpuk"
            )
        )
    ).scalar_one()
    sudah_dipindah = (
        await db.execute(
            select(func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0))
        )
    ).scalar_one()
    return float(masuk) - float(sudah_dipindah)


async def _sisa_tumpukan_intake(db: AsyncSession, intake_id: int) -> float:
    """Sisa PK sebuah intake tumpukan yang belum dipindah ke silo."""
    intake = await db.get(PkGudang2Intake, intake_id)
    if intake is None:
        raise Gudang2Error("Data tumpukan tidak ditemukan.")
    dipindah = (
        await db.execute(
            select(func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0)).where(
                PkTumpukanToSilo.pk_gudang2_intake_id == intake_id
            )
        )
    ).scalar_one()
    if intake.berat_kg is None:
        # Belum punya angka (truk belum ditimbang kedua, tanpa tara — P6-02).
        # Sisanya pun belum bisa disebut: None, bukan 0. Nol berarti habis.
        return None
    return float(intake.berat_kg) - float(dipindah)


async def hitung_hpp_wavg_silo(db: AsyncSession, silo_id: int) -> float | None:
    """HPP rata-rata tertimbang bahan yang SUDAH di silo (kecuali HPP belum tersedia)."""
    n1, b1 = (
        await db.execute(
            select(
                func.coalesce(func.sum(PkGudang2Intake.berat_kg * PkGudang2Intake.hpp_per_kg), 0),
                func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0),
            ).where(
                # `silo_id` saja — lihat catatan di `hitung_stok_silo`.
                PkGudang2Intake.silo_id == silo_id,
                PkGudang2Intake.flag_hpp_belum_tersedia.is_(False),
            )
        )
    ).one()
    n2, b2 = (
        await db.execute(
            select(
                func.coalesce(func.sum(PkTumpukanToSilo.berat_kg * PkGudang2Intake.hpp_per_kg), 0),
                func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0),
            )
            .select_from(PkTumpukanToSilo)
            .join(PkGudang2Intake, PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id)
            .where(
                PkTumpukanToSilo.silo_id == silo_id,
                PkGudang2Intake.flag_hpp_belum_tersedia.is_(False),
            )
        )
    ).one()
    total_berat = float(b1) + float(b2)
    if total_berat <= 0:
        return None
    return (float(n1) + float(n2)) / total_berat


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
    supplier, created = await find_or_create_supplier(db, nama_supplier)
    kode = await next_pk_purchase_code(db, now.date())
    batch = PkPurchaseBatch(
        kode_batch=kode, supplier_id=supplier.id, berat_total_kg=berat_kg,
        no_polisi_truk=no_polisi, jenis_pk=jenis, kadar_air_awal_persen=kadar_air,
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
) -> PkPurchaseResult:
    """Catat PK luar MASUK DARI tiket TIMBANG (jenis BERAS_PK). Supplier/bobot/nopol dari
    timbang — hanya pilih tiket + jenis PK (timbang tak membedakan ks/kl/dst). STAFF/ADMIN
    saja. Bobot boleh belum ada ('menunggu') → disinkron dari tiket. Referensi bobot = tiket.

    **Jalur PERISTIWA (Tahap 3, aksi kedua)** — persis kembaran gabah masuk:
    kunci tiket → nomor atomik → peristiwa `pk_luar_masuk` (kunci kiriman
    idempoten) → `proyeksi_pk_luar_masuk` → cermin `pk_purchase_batches` →
    jejak & notifikasi → commit. Gagal di mana pun = tak ada yang tersimpan.
    """
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
    berat, sumber, berat_perkiraan = await bobot_awal_dari_tiket(db, tiket)
    ada_bobot = berat is not None

    now = input_time(tanggal, jam)
    if tiket.get("supplier_id"):
        supplier = await db.get(Supplier, tiket["supplier_id"])
        created = False
    else:
        nama = tiket.get("nama_supplier") or tiket.get("pihak_nama") or "Tanpa Nama"
        supplier, created = await find_or_create_supplier(db, nama)

    if kunci_kiriman:
        ada = await _pk_batch_dari_kunci(db, kunci_kiriman)
        if ada is not None:
            return PkPurchaseResult(batch=ada, supplier_nama=supplier.nama_supplier, supplier_created=False)
    else:
        urutan = await buku.jumlah_jenis(db, PK_LUAR_MASUK, "timbangan_transaksi_id",
                                         timbangan_transaksi_id)
        kunci_kiriman = f"{PK_LUAR_MASUK}:tiket:{timbangan_transaksi_id}:{urutan + 1}"

    kode = await next_pk_purchase_code(db, now.date())
    muatan = {
        "kode_batch": kode, "timbangan_transaksi_id": timbangan_transaksi_id,
        "tiket_kode": tiket.get("kode"), "supplier_id": supplier.id,
        "nama_supplier": supplier.nama_supplier, "berat_kg": berat, "sumber_berat": sumber,
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
            return PkPurchaseResult(batch=ada, supplier_nama=supplier.nama_supplier, supplier_created=False)

    # Cermin untuk layar & laporan lama, ditambah penunjuk ke peristiwanya.
    batch = PkPurchaseBatch(
        kode_batch=kode, supplier_id=supplier.id, berat_total_kg=berat,
        no_polisi_truk=tiket.get("nomor_polisi"), jenis_pk=jenis, kadar_air_awal_persen=kadar_air,
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
        new_value=f"{kode} | {supplier.nama_supplier} | {b_str} PK {jenis} | timbang {tiket['kode']}",
    )
    await create_notification(
        db, tipe="verifikasi_pk_luar",
        pesan=(f"🟡 PK luar {kode} ({supplier.nama_supplier}, {b_str}, {jenis}, "
               f"dari timbang {tiket['kode']}) MASUK — menunggu QC & verifikasi harga."),
        target_role="admin", prioritas="kuning",
        table_name="pk_purchase_batches", record_id=batch.id,
    )
    await db.commit()
    await db.refresh(batch)
    return PkPurchaseResult(batch=batch, supplier_nama=supplier.nama_supplier,
                            supplier_created=created)


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


@dataclass
class PkPriceResult:
    batch: PkPurchaseBatch
    berat_bersih_kg: float
    total_biaya: float | None
    hpp_per_kg: float | None


_BUTIR_KUNING = {"bersih", "sedang", "banyak"}


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


async def log_pk_qc(
    db: AsyncSession, *, user: User, kode: str,
    kadar_air: float | None = None, broken: float | None = None,
    penyusutan_persen: float | None = None, butir_kuning: str | None = None,
    catatan_lab: str | None = None,
) -> PkQcResult:
    """Input KUALITAS PK luar (uji lab) sebagai PROPERTI batch — bukan keputusan.
    PK yang masuk sudah pasti diterima; ini hanya mencatat kualitasnya (kadar air,
    broken%, penyusutan/bekatul lab%, butir kuning, catatan). Staff/admin, kapan
    saja. Harga TIDAK disentuh di sini (langkah terpisah)."""
    if user.role not in PERAN_ADMIN_KEATAS:
        raise Gudang2Error("🔒 Input kualitas PK luar hanya oleh Staff/Admin.")
    batch = (
        await db.execute(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == kode))
    ).scalars().first()
    if batch is None:
        raise Gudang2Error(f"PK luar {kode} tidak ditemukan.")
    if butir_kuning:
        butir_kuning = butir_kuning.lower().strip()
        if butir_kuning not in _BUTIR_KUNING:
            raise Gudang2Error("Butir kuning harus: bersih, sedang, atau banyak.")
    if all(v is None for v in (kadar_air, broken, penyusutan_persen, butir_kuning, catatan_lab)):
        raise Gudang2Error("Sebutkan hasil ujinya (kadar air / broken / penyusutan / butir kuning / catatan).")

    verif = await _get_or_make_pk_verif(db, batch.id)
    verif.kadar_air = kadar_air
    verif.broken_persen = broken
    verif.penyusutan_persen = penyusutan_persen
    verif.butir_kuning = butir_kuning
    verif.catatan_lab = catatan_lab
    verif.keputusan = "terima"  # PK masuk selalu diterima
    await log_activity(
        db, table_name="pk_purchase_verifications", record_id=batch.id, action="UPDATE",
        changed_by=user.id, field_name="qc",
        new_value=f"ka={kadar_air} broken={broken} susut={penyusutan_persen} bk={butir_kuning}",
    )
    await db.commit()
    await db.refresh(batch)
    return PkQcResult(batch=batch, kadar_air=kadar_air, broken=broken,
                      penyusutan=penyusutan_persen, butir_kuning=butir_kuning)


async def verify_pk_price(
    db: AsyncSession, *, user: User, kode: str,
    metode: str | None = None, nilai: float | None = None,
    potongan_kg: float | None = None, potongan_alasan: str | None = None,
) -> PkPriceResult:
    """Verifikasi HARGA PK luar — terpisah & tanpa terikat waktu (seperti harga
    gabah G1). Staff/admin, kapan saja. Membereskan flag_unverified & mengisi
    HPP; bila PK sudah terlanjur masuk silo/tumpuk, snapshot HPP intake diperbarui."""
    if user.role not in PERAN_ADMIN_KEATAS:
        raise Gudang2Error("🔒 Verifikasi harga PK luar hanya oleh Staff/Admin.")
    batch = (
        await db.execute(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == kode))
    ).scalars().first()
    if batch is None:
        raise Gudang2Error(f"PK luar {kode} tidak ditemukan.")
    if metode not in ("per_kg", "total") or nilai is None:
        raise Gudang2Error("Sebutkan metode harga (per kg / total) & nilainya.")
    # Perkiraan tidak pernah dipakai untuk rupiah (keputusan pemilik, P6).
    bobot = dari_batch(batch)
    if not bobot.pasti:
        raise Gudang2Error(
            f"Bobot {kode} masih "
            f"{'perkiraan dari tara truk' if batch.sumber_berat == 'perkiraan' else 'menunggu timbang kedua'}"
            " — harga menunggu bobot pasti. Perkiraan tidak pernah dipakai untuk rupiah.")

    berat_bersih = float(batch.berat_total_kg or 0) - float(potongan_kg or 0)
    if metode == "total":
        total_biaya = float(nilai)
        hpp = total_biaya / berat_bersih if berat_bersih else None
    else:
        hpp = float(nilai)
        total_biaya = hpp * berat_bersih

    verif = await _get_or_make_pk_verif(db, batch.id)
    verif.potongan_kg = potongan_kg
    verif.potongan_alasan = potongan_alasan
    verif.harga_per_kg = hpp
    verif.total_biaya = total_biaya
    verif.metode_harga = metode
    verif.verified_by = user.id
    verif.waktu_verifikasi = input_time(None)
    verif.status_verifikasi = "terverifikasi"
    batch.flag_unverified = False

    # Backfill: bila PK sudah dimasukkan (intake) sebelum harga diverifikasi,
    # perbarui snapshot HPP-nya agar nilai stok G2 ikut benar.
    intakes = (
        await db.execute(
            select(PkGudang2Intake).where(
                PkGudang2Intake.pk_purchase_batch_id == batch.id
            )
        )
    ).scalars().all()
    for it in intakes:
        it.hpp_per_kg = hpp
        it.flag_hpp_belum_tersedia = hpp is None
    await log_activity(
        db, table_name="pk_purchase_verifications", record_id=batch.id, action="UPDATE",
        changed_by=user.id, field_name="harga",
        new_value=f"metode={metode} potongan={potongan_kg} hpp={hpp}",
    )
    await db.commit()
    await db.refresh(batch)
    return PkPriceResult(batch=batch, berat_bersih_kg=berat_bersih,
                         total_biaya=total_biaya, hpp_per_kg=hpp)


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
    usage.berat_masuk_kg = float(usage.berat_masuk_kg or 0) + float(berat_kg)
    return kode


async def _add_intake(
    db: AsyncSession, *, user: User, sumber_tipe: str, tujuan: str,
    berat_kg: float | None, hpp_per_kg: float | None, tanggal, jam,
    pk_purchase_batch_id: int | None = None, internal_transfer_id: int | None = None,
    kunci_kiriman: str | None = None, transfer_peristiwa_id: int | None = None,
    commit: bool = True, bobot_final: bool = True,
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
        ke_proses = await _catat_masuk_selama_proses(db, silo_id, berat_kg)
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
    )
    db.add(intake)
    await db.flush()
    getattr(e, "proyeksi", None) and setattr(e.proyeksi, "intake_id", intake.id)
    await log_activity(
        db, table_name="pk_gudang2_intakes", record_id=intake.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{sumber_tipe} | "
                  f"{f'{berat_kg:.0f}kg' if berat_kg is not None else 'bobot menunggu timbang'}"
                  f" → {tujuan_norm} | hpp={hpp_per_kg}",
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
    """Masukkan PK luar (yang sudah MASUK/diterima) ke silo/tumpukan G2.

    PK masuk = pasti diterima, jadi boleh langsung ditempatkan operator; input
    kualitas & verifikasi harga jalan terpisah (HPP intake di-backfill saat harga
    diverifikasi bila saat masuk belum ada)."""
    if not kode:
        raise Gudang2Error("Sebutkan kode PK luarnya, contoh: `masukkan PKL-... ke silo B`")
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
    bobot = dari_batch(batch)
    potongan = float(verif.potongan_kg or 0) if verif else 0.0
    berat = (bobot.angka() - potongan) if bobot.diketahui else None
    hpp = float(verif.harga_per_kg) if verif and verif.harga_per_kg is not None else None
    res = await _add_intake(
        db, user=user, sumber_tipe="beli_luar", tujuan=tujuan, berat_kg=berat,
        hpp_per_kg=hpp, tanggal=tanggal, jam=jam, pk_purchase_batch_id=batch.id,
        kunci_kiriman=kunci_kiriman, bobot_final=bobot.pasti,
    )
    batch.status_batch = "di_silo" if res.intake.tujuan != "ditumpuk" else "ditumpuk"
    await db.commit()
    return res


_SQL_RESINKRON_INTAKE = text("""
    UPDATE pk_gudang2_intakes i
       SET berat_kg = b.berat_total_kg - COALESCE(v.potongan_kg, 0),
           bobot_final = true
      FROM pk_purchase_batches b
      LEFT JOIN pk_purchase_verifications v ON v.pk_purchase_batch_id = b.id
     WHERE i.pk_purchase_batch_id = b.id
       AND i.dibatalkan_pada IS NULL              -- cermin bertanda
       AND i.bobot_final = false
       AND b.dibatalkan_pada IS NULL
       AND b.sumber_berat IN ('nota', 'timbangan', 'manual')
       AND b.berat_total_kg IS NOT NULL
       AND b.berat_total_kg - COALESCE(v.potongan_kg, 0) > 0
""")


async def resinkron_intake_g2(db: AsyncSession) -> int:
    """Lengkapi berat PK yang masuk Gudang 2 SEBELUM bobotnya pasti (P6-02).

    Intake menyalin bobot batch saat masuk. Bila saat itu bobotnya masih
    perkiraan atau belum diketahui, salinannya ditandai belum final; begitu
    batch-nya punya netto sungguhan (poller langkah 1), salinannya disamakan
    di sini. Stok silo & tumpukan dihitung dari intake, jadi keduanya ikut
    benar tanpa ada yang mencatat ulang. → jumlah intake yang dilengkapi.
    """
    res = await db.execute(_SQL_RESINKRON_INTAKE)
    await db.commit()
    return res.rowcount or 0


# ─────────────────────────── Pindah tumpukan → silo ───────────────────────────
@dataclass
class PindahResult:
    kode_pindah: str
    nama_silo: str
    berat_kg: float
    sisa_tumpukan_intake: float
    #: Kode penyosohan yang sedang memakai silo itu, bila PK-nya dituang di
    #: tengah proses — ia ikut dihitung sebagai bahan proses tersebut.
    ke_proses: str | None = None


async def _catat_pindah(
    db: AsyncSession, *, user: User, intake: PkGudang2Intake, silo: Silo, nama_silo: str,
    kirim: float, now, kunci_kiriman: str | None = None,
) -> tuple[PkTumpukanToSilo, str | None]:
    """SATU titik tulis pemindahan tumpukan → silo (jalur peristiwa, Tahap 3
    aksi kelima): nomor atomik → catat ke proses yang sedang memakai silo →
    peristiwa `pk_tumpukan_ke_silo` (kunci kiriman idempoten) → proyeksi →
    cermin `pk_tumpukan_to_silo` → jejak. Tidak commit."""
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
    ke_proses = await _catat_masuk_selama_proses(db, silo.id, kirim)
    muatan = {
        "kode_pindah": kode, "intake_id": intake.id, "intake_peristiwa_id": intake.peristiwa_id,
        "silo_id": silo.id, "nama_silo": nama_silo, "berat_kg": kirim, "ke_proses": ke_proses,
        "tanggal": now.date(), "waktu": now,
    }
    e = await buku.catat(db, jenis=PK_TUMPUKAN_KE_SILO, pelaku_id=user.id, kunci_kiriman=kunci_kiriman,
                         muatan=muatan, waktu=now)
    move = PkTumpukanToSilo(
        kode_pindah=kode, pk_gudang2_intake_id=intake.id, silo_id=silo.id, berat_kg=kirim,
        tanggal=now.date(), waktu=now, input_by=user.id, peristiwa_id=e.id,
    )
    db.add(move)
    await db.flush()
    getattr(e, "proyeksi", None) and setattr(e.proyeksi, "move_id", move.id)
    await log_activity(
        db, table_name="pk_tumpukan_to_silo", record_id=move.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {kirim:.0f}kg → Silo {nama_silo}"
                  + (f" | ditambah ke {ke_proses}" if ke_proses else ""),
    )
    await segarkan_status_silo(db, move.silo_id)
    return move, ke_proses


async def pindah_tumpukan_ke_silo(
    db: AsyncSession, *, user: User, intake_id: int, nama_silo: str | None,
    berat: float | None = None, tanggal=None, jam=None, kunci_kiriman: str | None = None,
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
        raise Gudang2Error("Sebutkan silo tujuannya (A atau B).")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")
    intake = (await db.execute(
        select(PkGudang2Intake).where(PkGudang2Intake.id == intake_id).with_for_update()
    )).scalars().first()
    if intake is None:
        raise Gudang2Error("Tumpukan sumber tidak ditemukan.")
    if intake.tujuan != "ditumpuk":
        raise Gudang2Error("Sumber bukan tumpukan — hanya PK di tumpukan yang bisa dipindah.")

    sisa = await _sisa_tumpukan_intake(db, intake_id)

    if sisa is None:

        raise Gudang2Error(

            "Bobot PK di tumpukan ini belum diketahui — truknya belum ditimbang "

            "kedua. Tunggu timbangnya, lalu pindahkan.")
    if sisa <= 0:
        raise Gudang2Error("Tumpukan ini sudah habis dipindah.")
    kirim = sisa if berat is None else min(float(berat), sisa)
    if berat is not None and float(berat) > sisa:
        raise Gudang2Error(
            f"Berat pindah ({float(berat):.0f} kg) melebihi sisa tumpukan ({sisa:.0f} kg)."
        )

    now = input_time(tanggal, jam)
    move, ke_proses = await _catat_pindah(db, user=user, intake=intake, silo=silo, nama_silo=nama_silo,
                                          kirim=kirim, now=now, kunci_kiriman=kunci_kiriman)
    await db.commit()
    await db.refresh(move)
    return PindahResult(
        kode_pindah=move.kode_pindah, nama_silo=nama_silo, berat_kg=float(move.berat_kg),
        sisa_tumpukan_intake=sisa - float(move.berat_kg), ke_proses=ke_proses,
    )


@dataclass
class PindahPoolResult:
    nama_silo: str
    moved_kg: float
    kodes: list[str]
    sisa_tumpukan: float


async def pindah_tumpukan(
    db: AsyncSession, *, user: User, nama_silo: str | None, berat: float | None = None,
    tanggal=None, jam=None,
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
                                      kirim=take, now=now)
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
        baris = f"• Silo {letter}: {_kg(stok)}{cap}"
        if financial:
            hpp = await hitung_hpp_wavg_silo(db, silo.id)
            if hpp is not None:
                baris += f" · HPP rata2 {_rp(hpp)}/kg"
        lines.append(baris)
    if not nama_silo:
        tump = await hitung_stok_tumpukan(db)
        lines.append(
            f"• Tumpukan: {_kg(tump)} / maks {settings.g2_tumpukan_maks_kg / 1000:g} ton"
        )
    return "\n".join(lines)