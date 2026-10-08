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

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.peran import PERAN_ADMIN_KEATAS
from app.config import settings
from app.database import input_time
from app.models import (
    Jasa,
    BrokenKeSilo,
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
from app.models.peristiwa import PK_LUAR_MASUK, PK_MASUK_G2, PK_TUMPUKAN_KE_SILO
from app.services import peristiwa as buku
from app.services.activity_log import log_activity
from app.services.codegen import (
    next_broken_move_code,
    next_pk_purchase_code,
    next_rejection_code,
    next_tumpukan_move_code,
)
from app.services.jasa import (
    JasaError,
    kunci_silo,
    pastikan_satu_jasa_bernama,
    pemilik_silo_g2,
)
from app.services.notification import create_notification
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


async def hitung_stok_silo(db: AsyncSession, silo_id: int, *,
                           pemilik: str = "semua") -> float:
    """Stok sebuah silo G2 — rumusnya bercabang menurut `Silo.jenis_isi`.

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

    ⚠ Silo broken (`jenis_isi='broken'`, keputusan pemilik 6 Oktober 2026)
    dijawab fungsi lain (`_hitung_stok_silo_broken`): tak punya jalan masuk
    "langsung" seperti PK — satu-satunya jalan masuknya `broken_ke_silo`, dari
    stok curah. `PolishingSiloUsage` sendiri SILO-AGNOSTIK (tak peduli isinya
    PK atau broken), jadi `mulai_penyosohan`/`selesai_penyosohan`/`rendemen_
    proses` memakai silo broken tanpa satu baris kode pun berubah di sana —
    yang perlu bercabang cuma jawaban "berapa isinya SEKARANG", di sini.
    """
    silo = await db.get(Silo, silo_id)
    if silo is not None and silo.jenis_isi == "broken":
        return await _hitung_stok_silo_broken(db, silo_id, pemilik=pemilik)
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
    masuk_langsung = (
        await db.execute(
            select(func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0)).where(
                # Disaring dengan `silo_id` SAJA (di luar saringan pemilik di
                # atas). Menambahkan syarat atas kata tujuannya akan membuang
                # baris silo ketiga tanpa satu pun galat — silonya berisi, tetapi
                # stoknya terbaca 0, lalu ia hilang dari borang. Itu jenis
                # kerusakan yang paling sulit dilihat: tak ada yang salah di
                # layar mana pun.
                *syarat_langsung,
            )
        )
    ).scalar_one()
    masuk_dari_tumpukan = (await db.execute(q_tumpukan)).scalar_one()
    terpakai = (await db.execute(q_terpakai)).scalar_one()
    keluar = (await db.execute(q_keluar)).scalar_one()
    return (float(masuk_langsung) + float(masuk_dari_tumpukan)
            - float(terpakai) - float(keluar))


async def _hitung_stok_silo_broken(db: AsyncSession, silo_id: int, *,
                                   pemilik: str = "semua") -> float:
    """Stok silo BROKEN = dipindah dari curah (`broken_ke_silo`) − terpakai sosoh ulang.

    Dipanggil dari `hitung_stok_silo` — lihat catatan di sana untuk arti
    `pemilik`. `terpakai` memakai kueri yang SAMA dengan silo PK:
    `PolishingSiloUsage` tak membedakan isi silonya.
    """
    def milik(k):
        return k.jasa_id.is_(None) if pemilik == "pabrik" else k.jasa_id.isnot(None)

    q_masuk = (select(func.coalesce(func.sum(BrokenKeSilo.berat_kg), 0))
               .where(BrokenKeSilo.silo_id == silo_id))
    q_terpakai = (
        select(func.coalesce(func.sum(PolishingSiloUsage.berat_terpakai_kg), 0))
        .where(PolishingSiloUsage.silo_id == silo_id,
               PolishingSiloUsage.berat_akhir_kg.isnot(None)))
    if pemilik != "semua":
        q_masuk = q_masuk.where(milik(BrokenKeSilo))
        q_terpakai = q_terpakai.join(
            PolishingProcess,
            PolishingProcess.id == PolishingSiloUsage.polishing_process_id
        ).where(milik(PolishingProcess))
    masuk = (await db.execute(q_masuk)).scalar_one()
    terpakai = (await db.execute(q_terpakai)).scalar_one()
    return float(masuk) - float(terpakai)


async def hitung_stok_tumpukan(db: AsyncSession, *,
                               pemilik: str = "semua") -> float:
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
    q_masuk = (select(func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0))
               .where(PkGudang2Intake.tujuan == "ditumpuk"))
    q_pindah = select(func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0))
    q_keluar = (select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
                .join(OutgoingRecord,
                      OutgoingRecord.id == OutgoingItem.outgoing_record_id)
                .where(OutgoingItem.item_type == "pk_g2",
                       OutgoingItem.silo_id.is_(None)))
    if pemilik != "semua":
        syarat = (PkGudang2Intake.jasa_id.is_(None) if pemilik == "pabrik"
                  else PkGudang2Intake.jasa_id.isnot(None))
        syarat_keluar = (OutgoingRecord.jasa_id.is_(None) if pemilik == "pabrik"
                         else OutgoingRecord.jasa_id.isnot(None))
        q_masuk = q_masuk.where(syarat)
        q_pindah = q_pindah.join(
            PkGudang2Intake,
            PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id
        ).where(syarat)
        q_keluar = q_keluar.where(syarat_keluar)
    masuk = (await db.execute(q_masuk)).scalar_one()
    sudah_dipindah = (await db.execute(q_pindah)).scalar_one()
    keluar = (await db.execute(q_keluar)).scalar_one()
    return float(masuk) - float(sudah_dipindah) - float(keluar)


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

    # Cermin untuk layar & laporan lama, ditambah penunjuk ke peristiwanya.
    batch = PkPurchaseBatch(
        # TEPAT SATU dari keduanya — `ck_pk_purchase_batches_beli_atau_jasa`.
        kode_batch=kode, supplier_id=supplier.id if supplier else None,
        jasa_id=jasa_ini.id if jasa_ini else None, berat_total_kg=berat,
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

    kode = await next_pk_purchase_code(db, now.date())
    batch = PkPurchaseBatch(
        kode_batch=kode, supplier_id=supplier.id if supplier else None,
        jasa_id=jasa_ini.id if jasa_ini else None, berat_total_kg=berat,
        no_polisi_truk=tiket.get("nomor_polisi"), jenis_pk=None,
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


class PkPriceResult:
    batch: PkPurchaseBatch
    berat_bersih_kg: float
    total_biaya: float | None
    hpp_per_kg: float | None


#: Skala kualitatif bersama — butir kuning, gabah, dan merang (jerami/malai)
#: semuanya dinilai dengan kosakata yang sama: bersih/sedikit/sedang/banyak.
#: "sedikit" ditambahkan 5 Oktober 2026 (keputusan pemilik) — dulu cuma tiga
#: titik, melompat dari "bersih" langsung ke "sedang".
_SKALA_KUALITATIF = {"bersih", "sedikit", "sedang", "banyak"}


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
        await db.execute(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == kode))
    ).scalars().first()
    if batch is None:
        raise Gudang2Error(f"PK luar {kode} tidak ditemukan.")
    # Satu pagar untuk ketiganya — kosakatanya memang satu skala.
    for label, nilai in (("Butir kuning", butir_kuning), ("Gabah", gabah), ("Merang", merang)):
        if nilai and nilai.lower().strip() not in _SKALA_KUALITATIF:
            raise Gudang2Error(f"{label} harus: bersih, sedikit, sedang, atau banyak.")
    butir_kuning = butir_kuning.lower().strip() if butir_kuning else None
    gabah = gabah.lower().strip() if gabah else None
    merang = merang.lower().strip() if merang else None
    if all(v is None for v in (kadar_air, broken, penyusutan_persen, butir_kuning,
                               gabah, merang, catatan_lab)):
        raise Gudang2Error("Sebutkan hasil ujinya (kadar air / broken / penyusutan / "
                           "butir kuning / gabah / merang / catatan).")

    verif = await _get_or_make_pk_verif(db, batch.id)
    verif.kadar_air = kadar_air
    verif.broken_persen = broken
    verif.penyusutan_persen = penyusutan_persen
    verif.butir_kuning = butir_kuning
    verif.gabah = gabah
    verif.merang = merang
    verif.catatan_lab = catatan_lab
    verif.keputusan = "terima"  # PK masuk selalu diterima
    await log_activity(
        db, table_name="pk_purchase_verifications", record_id=batch.id, action="UPDATE",
        changed_by=user.id, field_name="qc",
        new_value=(f"ka={kadar_air} broken={broken} susut={penyusutan_persen} "
                  f"bk={butir_kuning} gabah={gabah} merang={merang}"),
    )
    await db.commit()
    await db.refresh(batch)
    return PkQcResult(batch=batch, kadar_air=kadar_air, broken=broken,
                      penyusutan=penyusutan_persen, butir_kuning=butir_kuning,
                      gabah=gabah, merang=merang)


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
    # ⚠ PK tak boleh masuk silo BROKEN (keputusan pemilik 6 Oktober 2026 —
    # "broken memang tidak dituang ke silo PK", dan sebaliknya berlaku sama).
    # Tanpa pagar ini, PK yang masuk ke silo broken akan ikut dihitung oleh
    # `_hitung_stok_silo_broken` sebagai broken — barang yang bukan.
    if silo.jenis_isi != "pk":
        raise Gudang2Error(
            f"Silo {silo.nama_silo} bukan silo PK — pilih silo lain untuk PK.")
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
            await pastikan_satu_jasa_bernama(
                db, list(await pemilik_silo_g2(db, silo_id)) + [jasa_id])
        except JasaError as e:
            raise Gudang2Error(f"❌ {e.args[0]}") from None
        ke_proses = await _catat_masuk_selama_proses(db, silo_id, berat_kg)
        # PK jasa TIDAK boleh menyusup ke proses sosoh yang sedang berjalan:
        # prosesnya tak bisa membawa pemilik (`polishing_process` belum punya
        # `jasa_id`), jadi barangnya akan terbukukan sebagai hasil pabrik.
        if ke_proses and jasa_id is not None:
            raise Gudang2Error(
                f"❌ Silo itu sedang disosoh ({ke_proses}) — PK jasa tak boleh "
                "ditambahkan ke proses yang berjalan. Pilih tempat lain.")
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


_SQL_RESINKRON_INTAKE = text("""
    UPDATE pk_gudang2_intakes i
       SET berat_kg = b.berat_total_kg,
           bobot_final = true
      FROM pk_purchase_batches b
     WHERE i.pk_purchase_batch_id = b.id
       AND i.dibatalkan_pada IS NULL              -- cermin bertanda
       AND i.bobot_final = false
       AND b.dibatalkan_pada IS NULL
       AND b.sumber_berat IN ('nota', 'timbangan', 'manual')
       AND b.berat_total_kg IS NOT NULL
       AND b.berat_total_kg > 0
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
    # ── Isi silo tujuan harus SEPEMILIK dengan tumpukan yang dipindah ──
    #
    # Titik campur keempat: N tumpukan → 1 silo Gudang 2. `pk_tumpukan_to_silo`
    # tak punya kolom `jasa_id` sendiri dan tak perlu — pemiliknya ada di intake
    # asalnya, dan kolom kedua yang berarti hal sama adalah kolom yang suatu
    # hari berselisih dengan yang pertama.
    await kunci_silo(db, silo.id)
    try:
        await pastikan_satu_jasa_bernama(
            db, list(await pemilik_silo_g2(db, silo.id)) + [intake.jasa_id])
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
    ke_proses = await _catat_masuk_selama_proses(db, silo.id, kirim)
    # Sama seperti di `_add_intake`: PK jasa tak boleh menyusup ke proses sosoh
    # yang sedang berjalan — prosesnya belum bisa membawa pemilik.
    if ke_proses and intake.jasa_id is not None:
        raise Gudang2Error(
            f"❌ Silo {nama_silo} sedang disosoh ({ke_proses}) — PK jasa tak "
            "boleh ditambahkan ke proses yang berjalan.")
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


#: Selisih yang masih diterima antara berat yang DIKETIK dan sisa tumpukan
#: yang sebenarnya. Satu kilogram: di bawah ketelitian jembatan timbang, dan
#: cukup menampung pembulatan label mana pun (yang terbesar setengah kilogram).
#: Bukan angka kenyamanan — lihat alasan panjangnya di `pindah_tumpukan_ke_silo`.
TOLERANSI_PINDAH_KG = 1.0


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
    # PK tak boleh masuk silo BROKEN — lihat catatan di `_tujuan_and_silo`.
    if silo.jenis_isi != "pk":
        raise Gudang2Error(
            f"Silo {nama_silo} bukan silo PK — pilih silo lain untuk tumpukan ini.")
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
                                          kirim=kirim, now=now, kunci_kiriman=kunci_kiriman)
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
    if silo.jenis_isi != "broken":
        raise Gudang2Error(
            f"Silo {nama_silo} bukan silo broken — pilih silo yang isinya "
            "memang broken.")
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
        await pastikan_satu_jasa_bernama(
            db, list(await pemilik_silo_g2(db, silo.id)) + [row.jasa_id])
    except JasaError as e:
        raise Gudang2Error(f"❌ Silo {nama_silo}: {e.args[0]}") from None

    now = input_time(tanggal, jam)
    kode = await next_broken_move_code(db)
    ke_proses = await _catat_masuk_selama_proses(db, silo.id, kirim)
    # Sama seperti PK: broken jasa tak boleh menyusup ke proses sosoh yang
    # sedang berjalan — prosesnya belum bisa membawa pemilik.
    if ke_proses and row.jasa_id is not None:
        raise Gudang2Error(
            f"❌ Silo {nama_silo} sedang disosoh ({ke_proses}) — broken jasa "
            "tak boleh ditambahkan ke proses yang berjalan.")

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
    """SATU aksi: masukkan broken ke silo. Sumbernya otomatis — curah dulu
    (FIFO), lalu BONGKAR KARUNG bila curah kurang. Sisa dari karung yang
    dibongkar tapi tak terpakai tetap jadi curah di stok.

    Mengganti dua langkah lama ("Catat broken (curah)" lalu "Pindah broken ke
    silo"): keduanya menuntut operator menjawab pertanyaan yang salah —
    "berapa yang MASIH BELUM TERCATAT" — padahal yang ingin ia katakan cuma
    "berapa yang masuk silo sekarang". Laporan pemilik 7 Oktober 2026:
    mengetik 5.000 kg berakhir sebagai "tercatat melebihi hasil mesin 500 kg"
    tanpa operator pernah salah ketik — sebabnya murni bentuk borangnya.

    ⚠ `kode_pol` WAJIB — TIDAK ADA fallback "proses terbaru". `_proc_by_kode`
    (dipakai `catat_broken`/`catat_bekatul`) jatuh ke proses PALING BARU
    DIBUAT bila kode-nya kosong, tanpa peduli proses itu punya broken sama
    sekali — pintu masuk cacat yang sama persis tak boleh terulang di sini.
    """
    from app.penggilingan.inventory.finished_goods import _proc_by_kode
    from app.penggilingan.inventory.models import (ByproductStock, FinishedGoodsStock,
                                                   PackageSize, ProductSku)

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
    if silo.jenis_isi != "broken":
        raise Gudang2Error(
            f"Silo {nama_silo} bukan silo broken — pilih silo yang isinya "
            "memang broken.")
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
        await pastikan_satu_jasa_bernama(
            db, list(await pemilik_silo_g2(db, silo.id)) + [jasa_id])
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
    if ke_proses and jasa_id is not None:
        raise Gudang2Error(
            f"❌ Silo {nama_silo} sedang disosoh ({ke_proses}) — broken jasa "
            "tak boleh ditambahkan ke proses yang berjalan.")

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