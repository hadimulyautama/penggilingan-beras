"""Satu-satunya batasan jasa: KEPEMILIKAN.

Keputusan pemilik 1 Oktober 2026, dan ia sengaja dikutip utuh karena setengahnya
sudah pernah dipahami terbalik: *"multi silo giling dan multi silo sosoh
memungkinkan. yang tidak memungkinkan adalah menggabungkan barang jika
kepemilikan berbeda. itu saja batasannya."*

Jadi `pastikan_satu_jasa()` **bukan larangan mencampur** — ia larangan mencampur
PEMILIK. Barang sepemilik boleh dicampur sebebas barang pabrik: satu pesanan jasa
boleh mengisi satu silo dengan gabah dari pengering DAN gabah kering yang dibawa
langsung, lalu menggilingnya bersama; atau mengisi dua silo lalu menggiling
keduanya jadi satu lot. Ketiga bentuk itu sudah bisa hari ini dan tak satu pun
perlu dibangun.

⚠ DAN PENCABUTAN LARANGAN CAMPUR UNTUK GABAH PABRIK TETAP BERLAKU. Migrasi 0031
mencabutnya dengan alasan yang masih tertulis di `silo.masuk_silo`: silo yang
wajib kosong memacetkan pengering setiap kali kedua silo terisi, dan kemacetan
itulah yang melahirkan tumpukan. Memasang ulang larangan itu "sekalian" akan
merugikan pabrik di jalur yang tak ada hubungannya dengan jasa.

⚠ DITOLAK, BUKAN DIPERINGATKAN. Silo boleh memperingatkan campur ASAL
(`campur_asal`) sebab akibatnya cuma angka yang perlu dibaca hati-hati. Di sini
akibatnya barang orang lain ikut tergiling, dan tak ada pembetulan pembukuan yang
bisa mengembalikannya.

⚠ PEMBANDINGNYA `jasa_id`, BUKAN `pelanggan_id`. Dua pesanan milik pelanggan yang
sama tetap terpisah: bobot kembalinya berbeda, dan mencampurnya membuat pesanan
pertama tampak lunas oleh barang pesanan kedua.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dryer, Jasa, Pelanggan, Silo
from app.models.jasa import BERJALAN, DIBATALKAN, SELESAI


class JasaError(Exception):
    """Kesalahan jasa dengan pesan siap-tampil (args[0])."""


#: Dipakai di beberapa penolakan. Satu kalimat, satu tempat: kalimat penolakan
#: yang disalin akan berbeda di salah satu cabangnya, dan yang membacanya di
#: lapangan akan menyangka keduanya aturan yang berlainan.
_PESAN_CAMPUR = (
    "Barang milik pemilik berbeda tidak boleh digabung. "
    "Kosongkan tempatnya dulu, atau pakai tempat lain."
)


def _sebut(pemilik: set[int | None], nama: dict[int, str]) -> str:
    """Daftar pemilik yang bertabrakan, dalam kata yang dibaca orang."""
    bagian = [("milik pabrik" if j is None else nama.get(j, f"pesanan #{j}"))
              for j in sorted(pemilik, key=lambda x: (x is not None, x or 0))]
    return " dan ".join(bagian)


async def nama_pemilik(db: AsyncSession, jasa_id: int | None) -> str | None:
    """"JAS-2610-007 Pak Budi" — atau None untuk barang pabrik.

    Satu bentuk sebutan untuk SELURUH layar. Dua layar yang menyusun sebutan
    pemilik sendiri-sendiri akan menyebut barang yang sama dengan dua nama, dan
    yang membacanya tak punya cara tahu keduanya satu pesanan.
    """
    if jasa_id is None:
        return None
    baris = (await db.execute(
        select(Jasa.kode, Pelanggan.nama_pelanggan)
        .join(Pelanggan, Pelanggan.id == Jasa.pelanggan_id)
        .where(Jasa.id == jasa_id)
    )).first()
    if baris is None:
        return f"pesanan #{jasa_id}"
    kode, nama = baris
    return f"{kode} {nama}".strip()


async def nama_pemilik_banyak(db: AsyncSession, jasa_ids) -> dict[int, str]:
    """`nama_pemilik` untuk banyak pesanan sekaligus — satu kueri, bukan N.

    Kartu stok dan kartu antrean membaca seluruh barisnya dalam satu tarikan;
    memanggil versi satuan di dalam gelung akan mengeluarkan satu kueri per
    baris, kelas kesalahan yang sudah pernah ditemukan QA (P-S-02).
    """
    ids = {int(i) for i in jasa_ids if i is not None}
    if not ids:
        return {}
    return {jid: f"{kode} {nama}".strip() for jid, kode, nama in (await db.execute(
        select(Jasa.id, Jasa.kode, Pelanggan.nama_pelanggan)
        .join(Pelanggan, Pelanggan.id == Jasa.pelanggan_id)
        .where(Jasa.id.in_(ids))
    )).all()}


async def jasa_ids_per_pelanggan_dengan_hasil(db: AsyncSession) -> dict[int, list[int]]:
    """{pelanggan_id: [jasa_id, ...]} — SELURUH pesanan yang pernah menghasilkan
    sosoh, dikelompokkan per PELANGGAN, bukan per pesanan.

    Satu sumber untuk `/stok-produk-jasa` (`layar_produk.
    halaman_stok_produk_jasa`) DAN picker katalog umum
    (`aksi_inventory.produk_jasa_tersedia`): keduanya menyajikan broken
    curah sebagai SATU angka per pelanggan (koreksi pemilik 6 Oktober 2026,
    "pemisahannya bukan per proses. tapi per pelanggan"), dan tombol pindah
    kepemilikan di halaman itu membawa SELURUH `jasa_id` pelanggannya — bila
    picker mengelompokkannya sendiri secara berbeda (per pesanan, misalnya),
    nilai tombolnya tak akan pernah cocok dengan satu pun pilihan picker,
    dan medan "item" di borang gagal terisi otomatis tanpa satu pun galat
    (lihat `isiDariBaris` di `aksi.js` — ia mencocokkan nilai APA ADANYA).
    """
    from app.penggilingan.gudang2.models import PolishingProcess

    # `ORDER BY` eksplisit — tanpanya urutan `jasa_id` dalam daftar tak
    # terjamin stabil antar permintaan (Postgres tak menjanjikan apa pun
    # tanpa pengurut), dan nilai tombol (`cr:broken|1,2` vs `|2,1`) yang
    # berubah-ubah pada data yang sama membuat uji yang membandingkan
    # STRING jadi flaky — walau maknanya tetap sama (keduanya himpunan id).
    baris = (await db.execute(
        select(Jasa.pelanggan_id, Jasa.id)
        .where(Jasa.id.in_(
            select(PolishingProcess.jasa_id.distinct())
            .where(PolishingProcess.jasa_id.isnot(None))
        ))
        .order_by(Jasa.id)
    )).all()
    out: dict[int, list[int]] = {}
    for pelanggan_id, jasa_id in baris:
        out.setdefault(pelanggan_id, []).append(jasa_id)
    return out


def pastikan_satu_jasa(pemilik) -> int | None:
    """Pemilik tunggal dari sekumpulan `jasa_id`. Campuran → DITOLAK.

    Tiga keadaan, dan yang ketiga yang paling mudah terlewat:

        semua NULL                  → NULL (milik pabrik, perilaku hari ini)
        semua `jasa_id` yang sama   → `jasa_id` itu
        campuran NULL & non-NULL    → DITOLAK
        dua `jasa_id` berbeda       → DITOLAK

    Campuran NULL dan non-NULL ditolak sekeras dua pesanan berbeda: gabah pabrik
    yang ikut tergiling bersama gabah pelanggan membuat SELURUH keluarannya tak
    bisa dibagi — tak ada cara memisahkan beras siapa, dan rendemen yang dipakai
    menagih jadi rendemen atas bahan yang sebagian bukan milik penagihnya.

    Sinkron, tanpa `db`: ia aturan murni atas angka, dan aturan yang butuh basis
    data tak bisa diuji tanpa basis data. Yang membaca pemiliknya adalah
    pemanggilnya — dan pemanggil itulah yang juga memasang KUNCI barisnya.
    """
    himpunan = {(int(j) if j is not None else None) for j in pemilik}
    if len(himpunan) <= 1:
        return himpunan.pop() if himpunan else None
    raise JasaError(_PESAN_CAMPUR)


async def pastikan_satu_jasa_bernama(db: AsyncSession, pemilik) -> int | None:
    """`pastikan_satu_jasa` yang penolakannya MENYEBUT pemiliknya.

    "Barang milik pemilik berbeda tidak boleh digabung" memberitahu aturannya
    tanpa memberitahu apa yang harus dilakukan. Operator yang berdiri di depan
    silo perlu tahu barang SIAPA yang sudah ada di dalamnya — itu yang
    menentukan apakah ia memakai silo lain atau memanggil orang lain.
    """
    try:
        return pastikan_satu_jasa(pemilik)
    except JasaError:
        himpunan = {(int(j) if j is not None else None) for j in pemilik}
        nama = await nama_pemilik_banyak(db, himpunan)
        raise JasaError(
            f"{_PESAN_CAMPUR} Yang bertabrakan: {_sebut(himpunan, nama)}."
        ) from None


def pemilik_hasil(jasa_id: int | None, hasil_ditahan: str, jenis: str) -> int | None:
    """Siapa yang MEMILIKI hasil `jenis` dari proses milik `jasa_id`.

    SATU aturan untuk SEMUA jenis hasil — beras, menir, broken, reject,
    bekatul — ditentukan oleh satu hal saja: apakah `jenis` ada di
    `hasil_ditahan` pesanan itu. Ada di daftar → pabrik yang menahannya; tidak
    → kembali ke pesanan. Tak ada cabang "bekatul selalu begini" di sini, dan
    itu DISENGAJA: lihat ⚠⚠ di `HASIL_DITAHAN_BAWAAN` (`app/models/jasa.py`)
    untuk kenapa bekatul sempat (sampai 6 Oktober 2026) SELALU ada di daftar
    tahan bawaan, lalu dicabut — keputusan bisnisnya hidup di SATU tempat
    (daftar itu), bukan di cabang kode yang tersebar.

    Sejak bekatul dicabut dari bawaan, bekatul jasa BARU mengikuti pola
    broken/menir/reject apa adanya: tetap milik pesanan sampai dipindahkan
    lewat `pindah_kepemilikan_bekatul_curah` / `pindah_kepemilikan_barang_
    jadi` — bukan lagi otomatis.

    `hasil_ditahan` adalah CUPLIKAN kesepakatan pesanan itu, dibaca dari
    barisnya — BUKAN daftar yang ditulis di sini. Kalau kebijakannya dibaca dari
    kode, mengubahnya suatu hari akan mengubah arti seluruh pesanan lama,
    termasuk yang notanya sudah dipegang pelanggan — itulah kenapa migrasi
    `0073_bekatul_bukan_ditahan` membackfill BARIS-barisnya satu per satu,
    bukan mengandalkan kode ini dibaca ulang.
    """
    if jasa_id is None:
        return None
    ditahan = {k.strip().lower() for k in (hasil_ditahan or "").split(",") if k.strip()}
    return None if (jenis or "").strip().lower() in ditahan else jasa_id


async def pemilik_hasil_proses(
    db: AsyncSession, proses_jasa_id: int | None, jenis: str
) -> int | None:
    """`pemilik_hasil` yang membaca cuplikan kesepakatannya sendiri.

    Dipisah dari yang sinkron supaya aturannya tetap bisa diuji tanpa basis
    data — dan supaya pembaca yang sudah memegang barisnya tak perlu membacanya
    dua kali.
    """
    if proses_jasa_id is None:
        return None
    pesanan = await db.get(Jasa, proses_jasa_id)
    if pesanan is None:
        return None
    return pemilik_hasil(proses_jasa_id, pesanan.hasil_ditahan, jenis)


async def kunci_silo(db: AsyncSession, silo_id: int) -> None:
    """Kunci baris `silos` sebelum isinya diperiksa.

    ⚠ TANPA INI PENJAGANYA BOHONG. Dua operator bisa menuang ke silo yang sama
    pada detik yang sama: keduanya membaca "isinya milik pabrik", keduanya lolos,
    dan silo berisi barang dua pemilik — keadaan yang seluruh pekerjaan ini ada
    untuk mencegahnya. Pemeriksaan di depan tanpa kunci selalu bisa disalip;
    pelajaran yang sama sudah dibayar di P-K-05 (satu lot di dua silo) dan P-K-06
    (6 ton PK jadi 12 ton).

    Barisnya `silos` — INDUK tempatnya — bukan baris isinya: yang diperebutkan
    adalah "apa yang ada di dalam silo ini", dan baris yang hendak ditambahkan
    belum ada untuk dikunci. Pola yang sama dipakai `kunci_tiket_untuk_ditaut()`.

    SELECT … FOR UPDATE, bukan `UPDATE … WHERE`: di sini tak ada kolom klaim yang
    bisa direbut (silo menerima banyak baris, bukan satu), jadi yang dibutuhkan
    adalah antrean — yang kedua menunggu yang pertama commit, lalu MEMBACA ULANG
    isinya dan ditolak oleh pemeriksaan yang sama.
    """
    await db.execute(
        select(Silo.id).where(Silo.id == silo_id).with_for_update())


async def kunci_dryer(db: AsyncSession, dryer_id: int) -> None:
    """Kunci baris `dryers` sebelum isinya diperiksa — lihat `kunci_silo`.

    Pengering adalah tempat pencampuran yang SESUNGGUHNYA untuk gabah basah:
    lotnya baru terbentuk saat "mulai pengeringan", sedangkan gabahnya sudah
    bercampur sejak masuk mesin. Menjaga pembentukan lot saja berarti menolak
    pada saat penolakannya tak berguna lagi — gabah dua pemilik sudah di dalam
    satu mesin, dan tak ada tombol yang memisahkannya kembali.
    """
    await db.execute(
        select(Dryer.id).where(Dryer.id == dryer_id).with_for_update())


async def pemilik_silo_g2(db: AsyncSession, silo_id: int) -> set[int | None]:
    """Pemilik isi sebuah silo Gudang 2 SEKARANG — himpunan hampa bila kosong.

    ⚠ YANG DITANYAKAN "SEKARANG", BUKAN "PERNAH", dan perbedaannya pernah jadi
    cacat di fungsi ini sendiri. Baris intake TIDAK dihapus saat PK-nya disosoh
    habis — `hitung_stok_silo` menguranginya dengan `polishing_silo_usage`, dan
    riwayatnya tetap berdiri. Membaca seluruh intake yang pernah masuk berarti
    silo yang sudah dikosongkan tetap terbaca "milik Pak Budi" SELAMANYA: silo
    itu lalu menolak PK pabrik mana pun, tanpa seorang pun bisa menebak sebabnya
    dari layar.

    Dua langkah, dan keduanya memakai otoritas yang sudah ada:

      1. **Kosong atau tidak** dijawab `hitung_stok_silo` — satu-satunya tempat
         yang tahu aritmetika isi silo G2 (masuk langsung + masuk dari tumpukan
         − terpakai sosoh). Menyalin rumusnya ke sini berarti dua jawaban untuk
         satu silo, dan yang salah tak akan terlihat sampai ada yang menolak
         penuangan yang sah.
      2. **Milik siapa** dijawab intake TERBARU yang masuk ke silo ini — dan itu
         cukup justru karena penjaga di berkas ini: silo tak pernah berisi dua
         pemilik sekaligus, jadi apa pun yang ada di dalamnya sekarang milik
         pemilik yang sama dengan muatan terakhir yang masuk. Pergantian pemilik
         hanya bisa terjadi SESUDAH silonya nol.

    DUA jalan masuk PK ikut dibaca: PK yang masuk langsung ke silo
    (`pk_gudang2_intakes.silo_id`) dan PK yang masuk sebagai tumpukan lalu
    dipindah (`pk_tumpukan_to_silo` → intake asalnya). Membaca satu saja berarti
    silo yang isinya datang lewat tumpukan terbaca "milik pabrik" — dan jalur
    tumpukan justru jalur bawaan PK jasa.

    `pk_tumpukan_to_silo` sengaja TIDAK diberi kolom `jasa_id` sendiri:
    pemiliknya sudah ada di intake asalnya, dan kolom kedua yang berarti hal
    sama adalah kolom yang suatu hari berselisih dengan yang pertama.

    ⚠ SATU jalan masuk BROKEN ikut dibaca juga (`broken_ke_silo`, keputusan
    pemilik 6 Oktober 2026) — silo broken tak punya jalan "langsung" maupun
    "lewat tumpukan", cuma satu jalan: dipindah dari stok curah. `jasa_id`-nya
    sendiri (disalin dari sumbernya saat dipindah), bukan lewat join. Tanpa
    baris ini, silo broken SELALU terbaca "milik pabrik" — dan broken
    pelanggan yang dituang ke sana akan ikut tersosoh bersama broken pabrik.

    Himpunan HAMPA berarti silonya kosong — BUKAN "milik pabrik" (itu `{None}`).
    Pemanggil yang memperlakukan keduanya sama akan menolak silo kosong, atau
    menerima silo campuran, tergantung arah salahnya.
    """
    from app.models import BrokenKeSilo, PkGudang2Intake, PkTumpukanToSilo
    # Impor malas: `gudang2.service` mengimpor berkas ini di kepalanya, jadi
    # impor di tingkat modul akan melingkar.
    from app.penggilingan.gudang2.service import hitung_stok_silo

    if float(await hitung_stok_silo(db, silo_id)) <= 0.001:
        return set()

    # Muatan TERBARU, dari ketiga jalan masuk, diurutkan bersama. `waktu_masuk`
    # untuk yang langsung, `waktu` pemindahan untuk yang lewat tumpukan atau
    # broken — yang dibandingkan kapan barangnya ADA DI SILO, bukan kapan ia
    # tiba di pabrik.
    langsung = (await db.execute(
        select(PkGudang2Intake.waktu_masuk, PkGudang2Intake.jasa_id)
        .where(PkGudang2Intake.silo_id == silo_id)
        .order_by(PkGudang2Intake.waktu_masuk.desc(), PkGudang2Intake.id.desc())
        .limit(1)
    )).first()
    lewat_tumpukan = (await db.execute(
        select(PkTumpukanToSilo.waktu, PkGudang2Intake.jasa_id)
        .join(PkGudang2Intake,
              PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id)
        .where(PkTumpukanToSilo.silo_id == silo_id)
        .order_by(PkTumpukanToSilo.waktu.desc(), PkTumpukanToSilo.id.desc())
        .limit(1)
    )).first()
    lewat_broken = (await db.execute(
        select(BrokenKeSilo.waktu, BrokenKeSilo.jasa_id)
        .where(BrokenKeSilo.silo_id == silo_id)
        .order_by(BrokenKeSilo.waktu.desc(), BrokenKeSilo.id.desc())
        .limit(1)
    )).first()

    calon = [b for b in (langsung, lewat_tumpukan, lewat_broken) if b is not None]
    if not calon:
        # Stoknya positif tetapi tak ada satu pun muatan yang menjelaskannya —
        # keadaan yang seharusnya mustahil. Dikembalikan sebagai "milik pabrik"
        # supaya penjaganya memilih sisi yang AMAN: penuangan berikutnya ditolak
        # bila barangnya bertuan, bukan diterima diam-diam.
        return {None}
    terbaru = max(calon, key=lambda b: b[0])
    return {int(terbaru[1]) if terbaru[1] is not None else None}




# ═══════════════════════ SISA & "SELESAI" ═══════════════════════
#
# ⚠ SATU PENOLONG, DIPAKAI KARTU MAUPUN PEMERIKSAAN SELESAI. Dua hitungan
# "berapa sisa pesanan ini" akan berselisih, dan yang berselisih di sini berarti
# pesanan tampak lunas di satu layar dan menggantung di layar lain — lalu
# barangnya diserahkan atas dasar yang salah.
#
# ⚠⚠ DAN TIDAK PERNAH DIJUMLAH JADI SATU ANGKA. Gabah yang sudah jadi PK tak
# lagi ada sebagai gabah; menjumlahkan gabah + PK + beras berarti menghitung
# beras yang sama dua sampai tiga kali, dan angka itu akan dipakai orang untuk
# memutuskan berapa yang harus diserahkan. Yang dikembalikan RINCIAN PER FASE;
# `ada` cuma menjawab "masih ada sesuatu atau tidak".


@dataclass(frozen=True)
class SisaJasa:
    """Apa yang MASIH ADA di pabrik untuk satu pesanan, per fase.

    Tiap angka berdiri sendiri dan dibaca dari tempat barangnya berada
    sekarang — bukan diturunkan dari bobot masuk dikurangi yang keluar. Bobot
    gabah setelah dikeringkan TIDAK PERNAH DIUKUR (butuh flowing scale, pabrik
    belum punya), jadi hitungan "masuk − keluar" akan mengarang selisih yang
    tak seorang pun bisa pertanggungjawabkan.
    """

    #: Gabah yang belum masuk mesin apa pun — di halaman, menumpuk, atau baru
    #: tercatat.
    gabah_kg: float = 0.0
    #: Gabah yang sedang di pengering (termasuk yang lotnya sudah terbentuk).
    dryer_kg: float = 0.0
    #: Isi silo Gudang 1 yang menunggu digiling.
    silo_kg: float = 0.0
    #: PK hasil giling yang masih di Gudang 1.
    pk_g1_kg: float = 0.0
    #: PK yang sudah di Gudang 2 (silo maupun tumpukan), belum disosoh.
    pk_g2_kg: float = 0.0
    #: Broken hasil sosoh pesanan ini yang BELUM dikemas — baik yang masih
    #: tercatat curah (`byproduct_stock`) maupun yang sudah dipindah ke silo
    #: broken menunggu disosoh ulang. Begitu dikemas ia pindah ke
    #: `barang_jadi_kg`; begitu disosoh ulang ia hilang dari sini dan muncul
    #: lagi sebagai hasil BARU (beras/broken/dst, fase berikutnya) — lihat
    #: `BrokenKeSilo` dan `_hitung_stok_silo_broken`. Tanpa suku pengurang
    #: "terpakai sosoh ulang" di sini, broken yang sudah dituang ke silo akan
    #: terhitung DUA KALI: sekali di sini, sekali lagi sebagai hasil barunya.
    broken_kg: float = 0.0
    #: Beras & hasil samping berkemasan yang belum diambil pemiliknya.
    barang_jadi_kg: float = 0.0

    @property
    def ada(self) -> bool:
        """Masih ada barang pesanan ini di pabrik?

        Ambangnya 1 kg, bukan nol: bobot disimpan `Numeric(12,2)` dan dijumlah
        dari beberapa baris, jadi sisa 0,02 kg adalah galat pembulatan — bukan
        barang. Pesanan yang tak bisa ditutup karena dua puluh gram akan
        ditutup orang dengan cara lain.
        """
        return self.total > 1.0

    @property
    def total(self) -> float:
        """Jumlah seluruh fase — HANYA untuk menjawab "ada atau tidak".

        ⚠ JANGAN ditampilkan sebagai "sisa barang Anda". Satu muatan bisa
        terhitung dua kali di sini bila ia sedang berpindah fase, dan angka itu
        akan dibaca pelanggan sebagai janji.
        """
        return (self.gabah_kg + self.dryer_kg + self.silo_kg
                + self.pk_g1_kg + self.pk_g2_kg + self.broken_kg
                + self.barang_jadi_kg)

    @property
    def fase(self) -> str:
        """Sampai mana pesanan ini — DITURUNKAN, tidak disimpan.

        Keputusan pemilik: kedalaman tidak dinyatakan di muka. *"jika hanya jadi
        pk dan pk ternyata keluar berarti hanya sampai pk. jika diproses sampai
        beras putih berarti sampai beras putih."* Jadi "sampai mana" dijawab
        dengan melihat di mana barangnya BERADA, bukan dengan membaca kolom yang
        bisa berselisih dengan kenyataannya.

        Yang disebut fase TERJAUH yang masih berisi: pesanan yang berasnya sudah
        sebagian dikemas sementara sisanya masih PK memang sudah "sampai beras".
        """
        if self.barang_jadi_kg > 1.0:
            return "beras"
        if self.broken_kg > 1.0:
            return "broken"
        if self.pk_g2_kg > 1.0:
            return "pk_g2"
        if self.pk_g1_kg > 1.0:
            return "pk"
        if self.silo_kg > 1.0:
            return "silo"
        if self.dryer_kg > 1.0:
            return "pengeringan"
        if self.gabah_kg > 1.0:
            return "gabah"
        return "kosong"


#: Status batch gabah yang barangnya BELUM masuk mesin apa pun.
_GABAH_MENUNGGU = ("baru", "ditumpuk")
#: Status batch gabah yang barangnya ada di pengering.
_GABAH_DI_DRYER = ("di_dryer", "dikeringkan")


async def sisa_jasa(db: AsyncSession, jasa_id: int) -> SisaJasa:
    """Apa yang masih ada di pabrik untuk pesanan ini, per fase.

    Tiap fase dibaca dengan aturan HIDUP yang sama yang dipakai layar masing-
    masing — status batch, `silo_storage.status`, sisa PK per lot, isi Gudang 2
    dikurangi yang sudah disosoh, barang jadi dikurangi yang sudah diambil.
    Menyusun aturan sendiri di sini berarti sisa di kartu jasa berbeda dari sisa
    di layar stok, dan yang membacanya tak punya cara tahu mana yang benar.
    """
    from app.models import (ByproductStock, FinishedGoodsStock, MillingProcess,
                            OutgoingItem, OutgoingRecord, PkGudang2Intake,
                            PolishingProcess, PolishingSiloUsage, PurchaseBatch,
                            Silo, SiloStorage)
    from app.penggilingan.gudang1.services.bobot import dari_batch
    from app.penggilingan.gudang1.services.milling import pk_breakdown_banyak

    async def _batch(status) -> float:
        baris = (await db.execute(
            select(PurchaseBatch).where(
                PurchaseBatch.jasa_id == jasa_id,
                PurchaseBatch.status_batch.in_(status))
        )).scalars().all()
        # `dari_batch` — bobot yang SAMA yang dipakai seluruh app (nota vs
        # timbangan, perkiraan tara). Membaca `berat_total_kg` mentah di sini
        # akan menyebut angka lain untuk muatan yang sama.
        return sum(dari_batch(b).angka() for b in baris)

    gabah = await _batch(_GABAH_MENUNGGU)
    dryer = await _batch(_GABAH_DI_DRYER)

    # Isi silo Gudang 1: baris yang masih `terisi`, lewat penolong yang sama
    # yang dipakai kartu silo.
    from app.penggilingan.gudang1.services.silo import _row_bobot

    silo = 0.0
    for r in (await db.execute(
        select(SiloStorage).where(SiloStorage.jasa_id == jasa_id,
                                  SiloStorage.status == "terisi")
    )).scalars().all():
        silo += (await _row_bobot(db, r)).angka()

    # PK Gudang 1: sisa per lot giling, dari penolong yang sama yang dipakai
    # layar Stok (`tersedia = dihasilkan − dikirim − dijual`).
    proses = (await db.execute(
        select(MillingProcess).where(MillingProcess.jasa_id == jasa_id)
    )).scalars().all()
    pk_g1 = 0.0
    if proses:
        rincian = await pk_breakdown_banyak(db, [p.id for p in proses])
        pk_g1 = sum(max(rincian[p.id].tersedia, 0.0) for p in proses)

    # PK Gudang 2 = yang masuk − yang sudah dipakai sosoh. Pemindahan
    # tumpukan→silo tidak mengubah totalnya: ia perpindahan di dalam gudang.
    masuk_g2 = float((await db.execute(
        select(func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0))
        .where(PkGudang2Intake.jasa_id == jasa_id)
    )).scalar_one())
    disosoh = float((await db.execute(
        select(func.coalesce(func.sum(PolishingSiloUsage.berat_terpakai_kg), 0))
        .join(PolishingProcess,
              PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
        .where(PolishingProcess.jasa_id == jasa_id,
               PolishingSiloUsage.berat_akhir_kg.isnot(None))
    )).scalar_one())
    pk_g2 = max(masuk_g2 - disosoh, 0.0)

    # Broken = yang tercatat curah (`byproduct_stock`, lahir dari `catat_
    # broken`) − yang sudah disosoh ULANG (silo broken, lewat usage yang sama
    # yang dipakai pk_g2 di atas, disaring ke silo ber-`jenis_isi='broken'`
    # saja). `broken_ke_silo` SENGAJA tak ikut dikurangkan sendiri: ia memang
    # memindahkan broken dari curah ke silo, tapi totalnya tetap milik pesanan
    # ini sampai disosoh ulang sungguhan — sama seperti pindah tumpukan→silo
    # tak mengubah total `pk_g2` di atas.
    masuk_broken = float((await db.execute(
        select(func.coalesce(func.sum(ByproductStock.berat_kg), 0))
        .where(ByproductStock.jenis_produk == "broken",
               ByproductStock.jasa_id == jasa_id)
    )).scalar_one())
    disosoh_ulang = float((await db.execute(
        select(func.coalesce(func.sum(PolishingSiloUsage.berat_terpakai_kg), 0))
        .join(PolishingProcess,
              PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
        .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
        .where(PolishingProcess.jasa_id == jasa_id,
               Silo.jenis_isi == "broken",
               PolishingSiloUsage.berat_akhir_kg.isnot(None))
    )).scalar_one())
    broken = max(masuk_broken - disosoh_ulang, 0.0)

    # Barang jadi = yang dibukukan atas pesanan ini − yang sudah diambil.
    jadi = float((await db.execute(
        select(func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
        .where(FinishedGoodsStock.jasa_id == jasa_id)
    )).scalar_one())
    diambil = float((await db.execute(
        select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .join(OutgoingRecord, OutgoingRecord.id == OutgoingItem.outgoing_record_id)
        .where(OutgoingRecord.jasa_id == jasa_id,
               OutgoingRecord.status != "batal")
    )).scalar_one())
    # Pengambilan PK langsung ikut dikurangkan dari PK G1 oleh
    # `pk_breakdown` (ia menghitung `dijual langsung`), jadi di sini hanya
    # selisih barang jadinya yang dijepit di nol.
    return SisaJasa(
        gabah_kg=gabah, dryer_kg=dryer, silo_kg=silo,
        pk_g1_kg=pk_g1, pk_g2_kg=pk_g2, broken_kg=broken,
        barang_jadi_kg=max(jadi - diambil, 0.0),
    )


async def pernah_ada_barang(db: AsyncSession, jasa_id: int) -> bool:
    """Pernah ada barang masuk untuk pesanan ini?

    ⚠ INI SETENGAH DARI ATURAN "SELESAI", dan setengah yang mudah dilupakan.
    Pesanan yang baru dibuat sementara truknya belum datang juga punya sisa NOL
    — dan tanpa syarat ini ia akan terbaca "selesai" pada detik ia lahir.
    Rancangan lama menghindari jebakan itu dengan syarat ganda yang rumit;
    dengan kedalaman fleksibel, yang dibutuhkan cuma pertanyaan ini.

    Dijawab dari TAUTAN, bukan dari bobot: batch yang tiketnya belum ditimbang
    kedua memang belum punya angka, dan "bobotnya nol" bukan berarti truknya
    tak pernah datang.
    """
    from app.models import PkGudang2Intake, PkPurchaseBatch, PurchaseBatch

    # TIGA jalan barang bisa tiba untuk sebuah pesanan, dan ketiganya dihitung:
    # gabah masuk, PK dari luar, dan PK yang diterima Gudang 2 (dari transfer
    # Gudang 1 — pada pesanan yang hulunya memang sudah dicatat, maupun pada
    # pencatatan yang lahir di Gudang 2).
    #
    # ⚠ Memeriksa dua yang pertama saja pernah membuat pesanan yang barangnya
    # SUDAH ada di silo Gudang 2 terbaca "belum pernah menerima barang" — lalu
    # ia bisa DIBATALKAN, dan barangnya tertinggal tanpa pemilik yang berjalan:
    # saringan stok tetap membuangnya dari stok pabrik, jadi ia hilang dari
    # kedua sisi. Ditemukan uji penutupan.
    for kolom in (PurchaseBatch.id, PkPurchaseBatch.id, PkGudang2Intake.id):
        tabel = kolom.parent.class_
        if (await db.execute(
            select(kolom).where(tabel.jasa_id == jasa_id).limit(1)
        )).first():
            return True
    return False


async def boleh_ditutup(db: AsyncSession, jasa_id: int) -> tuple[bool, str]:
    """(boleh, sebab bila tidak) — aturan "SELESAI" dalam satu kalimat.

        SELESAI = pernah ada barang masuk untuk pesanan ini,
                  DAN tak ada lagi barang ber-`jasa_id` ini di pabrik.

    Diperiksa sendiri:

        pesanan baru, truk belum datang  → belum pernah ada barang → BELUM ✓
        gabah menumpuk                   → barang ada             → BELUM ✓
        sudah jadi PK, belum diambil     → barang ada             → BELUM ✓
        diambil sebagian                 → barang ada             → BELUM ✓
        semua terangkut                  → tak ada apa pun        → SELESAI ✓

    Tak perlu tahu kedalamannya, tak perlu tahu berapa yang seharusnya keluar,
    dan tak ada nol yang bermakna dua.
    """
    if not await pernah_ada_barang(db, jasa_id):
        return False, ("Belum ada barang masuk untuk pesanan ini — belum ada "
                       "yang bisa diselesaikan.")
    sisa = await sisa_jasa(db, jasa_id)
    if sisa.ada:
        bagian = [f"{nama} {kg:,.0f} kg".replace(",", ".")
                  for nama, kg in (("gabah", sisa.gabah_kg),
                                   ("di pengering", sisa.dryer_kg),
                                   ("di silo", sisa.silo_kg),
                                   ("PK Gudang 1", sisa.pk_g1_kg),
                                   ("PK Gudang 2", sisa.pk_g2_kg),
                                   ("broken", sisa.broken_kg),
                                   ("barang jadi", sisa.barang_jadi_kg))
                  if kg > 1.0]
        return False, ("Masih ada barang pesanan ini di pabrik: "
                       + " · ".join(bagian) + ".")
    return True, ""


# ═══════════════════════ DAFTAR & PENUTUPAN ═══════════════════════

@dataclass(frozen=True)
class KartuJasa:
    """Satu pesanan jasa untuk layar Jasa."""

    id: int
    kode: str
    pelanggan: str
    status: str
    #: Fase TERJAUH yang masih berisi — diturunkan, tidak disimpan.
    fase: str
    sisa: SisaJasa
    #: Sudah berapa hari sejak barang terakhir pesanan ini bergerak masuk.
    #: Itu yang menjawab "sudah berapa lama menunggu diambil" — pertanyaan yang
    #: dibawa orang saat membuka layar ini.
    umur_hari: int
    #: Boleh ditutup sekarang? Berikut sebabnya bila tidak — kalimat yang sama
    #: yang akan dilihat orang kalau ia menekan tombolnya.
    boleh_tutup: bool
    sebab: str


#: Nama fase di layar. Kuncinya dari `SisaJasa.fase`.
FASE_JASA = {
    "gabah": "Gabah menunggu",
    "pengeringan": "Di pengering",
    "silo": "Di silo, menunggu giling",
    "pk": "Sudah jadi PK (Gudang 1)",
    "pk_g2": "PK di Gudang 2",
    "beras": "Sudah jadi beras — menunggu diambil",
    "kosong": "Tak ada barang di pabrik",
}


async def daftar_jasa(db: AsyncSession, *, status: str | None = None
                      ) -> list[KartuJasa]:
    """Pesanan jasa untuk layar Jasa — berjalan dulu, terbaru di atas.

    `status` kosong berarti yang BERJALAN saja. Yang sudah selesai dan
    dibatalkan tetap bisa dibuka, tetapi tidak ikut secara bawaan: daftar yang
    memuat seluruh riwayat akan menenggelamkan pekerjaan hari ini di bawah
    pesanan tahun lalu — pelajaran yang sama sudah dibayar daftar tiket timbang.
    """
    from app.database import now_local
    from app.models import Jasa, Pelanggan

    q = (select(Jasa, Pelanggan.nama_pelanggan)
         .join(Pelanggan, Pelanggan.id == Jasa.pelanggan_id)
         .order_by(Jasa.id.desc()))
    q = q.where(Jasa.status == (status or BERJALAN))
    keluar: list[KartuJasa] = []
    sekarang = now_local()
    for pesanan, nama in (await db.execute(q)).all():
        sisa = await sisa_jasa(db, pesanan.id)
        boleh, sebab = await boleh_ditutup(db, pesanan.id)
        acuan = pesanan.created_at or sekarang
        keluar.append(KartuJasa(
            id=pesanan.id, kode=pesanan.kode, pelanggan=nama or "-",
            status=pesanan.status, fase=sisa.fase, sisa=sisa,
            umur_hari=max((sekarang - acuan).days, 0),
            boleh_tutup=boleh, sebab=sebab,
        ))
    return keluar


async def tutup_pesanan(db: AsyncSession, *, user, jasa_id: int) -> str:
    """Tutup pesanan jasa — hanya bila aturan "selesai" memang terpenuhi.

    Penutupannya DIPERIKSA, bukan dipercayakan ke layar: tombolnya memang hanya
    muncul saat boleh, tetapi tombol yang disembunyikan bukan tombol yang
    dijaga — dan halaman di ponsel berumur panjang.
    """
    from app.database import now_local
    from app.models import Jasa
    from app.services.activity_log import log_activity

    pesanan = await db.get(Jasa, int(jasa_id))
    if pesanan is None:
        raise JasaError("Pesanan jasa tidak ditemukan.")
    if pesanan.status != BERJALAN:
        raise JasaError(f"Pesanan {pesanan.kode} sudah {pesanan.status}.")
    boleh, sebab = await boleh_ditutup(db, pesanan.id)
    if not boleh:
        raise JasaError(f"{pesanan.kode} belum bisa ditutup. {sebab}")
    pesanan.status = SELESAI
    await log_activity(
        db, table_name="jasa", record_id=pesanan.id, action="UPDATE",
        changed_by=user.id, field_name="status", old_value=BERJALAN,
        new_value=SELESAI)
    await db.commit()
    return f"✓ Pesanan jasa {pesanan.kode} ditutup — SELESAI."


async def batalkan_pesanan(db: AsyncSession, *, user, jasa_id: int,
                           sebab: str) -> str:
    """Batalkan pesanan jasa — hanya yang belum pernah menerima barang.

    ⚠ BUKAN jalan keluar untuk pesanan yang barangnya sudah ada. Pesanan yang
    dibatalkan sementara gabahnya di silo akan meninggalkan barang tanpa
    pemilik yang berjalan: saringan stok tetap membuangnya dari stok pabrik
    (jasa_id-nya masih terisi), jadi barangnya hilang dari KEDUA sisi — tak
    terhitung milik pabrik, tak terhitung milik siapa pun.
    
    Yang sudah menerima barang diselesaikan lewat pengambilan, atau — kalau
    memang keliru — pembatalan pencatatan barangnya satu per satu lewat
    Batalkan input, yang memang punya penjaganya sendiri.
    """
    from app.database import now_local
    from app.models import Jasa
    from app.services.activity_log import log_activity

    sebab = (sebab or "").strip()
    if not sebab:
        raise JasaError(
            "Sebutkan sebab pembatalannya — pesanan yang hilang tanpa "
            "keterangan akan ditanyakan pelanggannya, dan tak ada yang bisa "
            "menjawab.")
    pesanan = await db.get(Jasa, int(jasa_id))
    if pesanan is None:
        raise JasaError("Pesanan jasa tidak ditemukan.")
    if pesanan.status != BERJALAN:
        raise JasaError(f"Pesanan {pesanan.kode} sudah {pesanan.status}.")
    if await pernah_ada_barang(db, pesanan.id):
        raise JasaError(
            f"{pesanan.kode} sudah pernah menerima barang — tak bisa "
            "dibatalkan. Selesaikan lewat pengambilan, atau batalkan "
            "pencatatan barangnya satu per satu lewat Batalkan input.")
    pesanan.status = DIBATALKAN
    pesanan.dibatalkan_pada = now_local()
    pesanan.catatan = ((pesanan.catatan or "") + f"\nDibatalkan: {sebab}").strip()
    await log_activity(
        db, table_name="jasa", record_id=pesanan.id, action="UPDATE",
        changed_by=user.id, field_name="status", old_value=BERJALAN,
        new_value=f"{DIBATALKAN}: {sebab[:80]}")
    await db.commit()
    return f"✓ Pesanan jasa {pesanan.kode} dibatalkan."


# ═══════════════════════════ NOTA JASA ═══════════════════════════
#
# Satu-satunya yang dilihat orang yang tak pernah membuka isi app ini — dan ia
# yang menentukan apakah jasa ini terasa bisa dipercaya.
#
# ⚠ TANPA SATU PUN ANGKA UANG. Pemilik barang berhak tahu BOBOTNYA; berapa
# nilainya urusan keuangan, dan menaruhnya di sini membuka pintu yang keputusan
# pemilik tentang biaya sengaja menutup.


def _kg_nota(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def nota_jasa(db: AsyncSession, jasa_id: int) -> str:
    """Nota satu pesanan: apa yang dibawa, apa yang kembali, dan selisihnya.

    TIGA hal dalam bentuknya yang tidak boleh digeser:

    1. **Bekatul di LUAR "Total kembali".** Bekatulnya tidak kembali, jadi
       menjumlahkannya ke sana akan berbohong tentang apa yang diterima.
    2. **Bekatul PER PROSES SOSOH**, bukan satu angka gabungan — itu yang
       pemilik sebutkan: *"pemilik barang juga harus tau hasil bekatul dari tiap
       proses barang miliknya."*
    3. **Selisihnya SATU baris yang TIDAK DIRINCI.** Sekam tak bisa dideteksi
       (bisa terhisap penyedot debu) dan bobot gabah setelah dikeringkan tidak
       diukur sama sekali (butuh flowing scale, pabrik belum punya). Jadi air
       yang menguap, sekam, dan susut proses adalah satu jumlah yang tak bisa
       dipecah.

       ⚠ JANGAN menulis "susut pengeringan & sekam" sebagai satu baris berlabel
       dua sebab: itu mengaku terlalu banyak — ia menyiratkan pabrik tahu bagian
       mana air dan bagian mana sekam. Pabrik tidak tahu. Nota yang menyebut
       sebab yang tak terukur akan ditanyai rinciannya, dan tak ada jawaban yang
       bisa diberikan.

       Angka yang jujur tentang ketidaktahuannya lebih mudah dipertahankan
       daripada rincian yang terdengar pasti. Dan baris itulah penjelasan yang
       menahan sengketa pada hari pelanggan melihat 9,6 ton jadi 5,8 ton.
    """
    from app.models import (FinishedGoodsStock, Jasa, OutgoingItem,
                            OutgoingRecord, Pelanggan, PkPurchaseBatch,
                            PolishingProcess, ProductSku, PurchaseBatch,
                            RiceQualityStandard)
    from app.penggilingan.gudang1.services.bobot import dari_batch
    from app.penggilingan.inventory.models import ByproductStock
    from app.services.stok import jenis_produk, nama_produk

    baris = (await db.execute(
        select(Jasa, Pelanggan.nama_pelanggan)
        .join(Pelanggan, Pelanggan.id == Jasa.pelanggan_id)
        .where(Jasa.id == jasa_id)
    )).first()
    if baris is None:
        raise JasaError("Pesanan jasa tidak ditemukan.")
    pesanan, nama = baris

    baris_out: list[str] = [f"Pesanan {pesanan.kode} · {nama or '-'}"]
    keadaan = {BERJALAN: "Berjalan", SELESAI: "Selesai",
               DIBATALKAN: "Dibatalkan"}.get(pesanan.status, pesanan.status)
    baris_out.append(f"Keadaan: {keadaan}")
    baris_out.append("─" * 58)

    # ── DIBAWA: bobot MASUK, satu-satunya angka yang pasti ──
    masuk = 0.0
    baris_out.append("Dibawa")
    for b in (await db.execute(
        select(PurchaseBatch).where(PurchaseBatch.jasa_id == jasa_id)
        .order_by(PurchaseBatch.id)
    )).scalars().all():
        kg = dari_batch(b).angka()
        masuk += kg
        baris_out.append(f"   gabah {b.kondisi_gabah:<7} {_kg_nota(kg):>12}   "
                         f"{b.kode_batch}")
    for b in (await db.execute(
        # PK yang DITOLAK tak pernah diterima — kembali ke truknya saat
        # datang, jadi tak boleh tertulis sebagai "dibawa" di nota pelanggan
        # (keputusan pemilik 4 Oktober 2026, saat `status_batch="ditolak"`
        # mulai dipakai sungguhan oleh `create_pk_rejection_dari_timbang`).
        select(PkPurchaseBatch).where(PkPurchaseBatch.jasa_id == jasa_id,
                                      PkPurchaseBatch.status_batch != "ditolak")
        .order_by(PkPurchaseBatch.id)
    )).scalars().all():
        kg = float(b.berat_total_kg or 0)
        masuk += kg
        baris_out.append(f"   beras PK        {_kg_nota(kg):>12}   {b.kode_batch}")
    if masuk <= 0:
        baris_out.append("   (belum ada barang masuk)")
    baris_out.append("─" * 58)

    # ── KEMBALI: yang sudah DIAMBIL pemiliknya ──
    #
    # Yang dihitung PENGAMBILAN, bukan yang terbukukan: nota menjawab "apa yang
    # sudah Anda terima". Yang masih di gudang disebut terpisah di bawah — ia
    # belum diterima siapa pun, dan menjumlahkannya ke "kembali" akan membuat
    # nota berbohong tepat di angka yang paling diperiksa.
    kembali = 0.0
    baris_out.append("Kembali (sudah diambil)")
    for kategori, mutu, kg, kode in (await db.execute(
        select(ProductSku.kategori, RiceQualityStandard.kode,
               func.coalesce(func.sum(OutgoingItem.berat_kg), 0),
               func.min(OutgoingRecord.kode))
        .join(OutgoingRecord, OutgoingRecord.id == OutgoingItem.outgoing_record_id)
        .join(ProductSku, ProductSku.id == OutgoingItem.product_sku_id)
        .join(RiceQualityStandard,
              RiceQualityStandard.id == OutgoingItem.rice_quality_standard_id,
              isouter=True)
        .where(OutgoingRecord.jasa_id == jasa_id,
               OutgoingRecord.status != "batal",
               OutgoingItem.berat_kg > 0)
        .group_by(ProductSku.kategori, RiceQualityStandard.kode)
    )).all():
        kg = float(kg or 0)
        kembali += kg
        baris_out.append(
            f"   {nama_produk(jenis_produk(kategori, mutu)):<16}"
            f"{_kg_nota(kg):>12}   {kode or ''}")
    if kembali <= 0:
        baris_out.append("   (belum ada yang diambil)")
    baris_out.append("─" * 58)
    baris_out.append(f"Total kembali{_kg_nota(kembali):>23}")

    # ── MASIH DI PABRIK ──
    sisa = await sisa_jasa(db, jasa_id)
    if sisa.ada:
        baris_out.append("")
        baris_out.append(f"Masih di pabrik ({FASE_JASA.get(sisa.fase, sisa.fase)})")
        for sebut, kg in (("gabah", sisa.gabah_kg), ("di pengering", sisa.dryer_kg),
                          ("di silo", sisa.silo_kg), ("PK Gudang 1", sisa.pk_g1_kg),
                          ("PK Gudang 2", sisa.pk_g2_kg),
                          ("barang jadi", sisa.barang_jadi_kg)):
            if kg > 1.0:
                baris_out.append(f"   {sebut:<16}{_kg_nota(kg):>12}")

    # ── SELISIH: satu baris, TIDAK dirinci ──
    if masuk > 0:
        selisih = masuk - kembali - sisa.total
        if selisih > 1.0:
            baris_out.append("─" * 58)
            baris_out.append(f"Selisih{_kg_nota(selisih):>29}")
            baris_out.append("  susut pengeringan, sekam & susut proses")
            baris_out.append("  — tidak diukur terpisah")

    # ── BEKATUL, PER PROSES — untuk diketahui, bukan untuk "Total kembali" ──
    #
    # ⚠ DUA RUMAH dijumlah bersama (curah `ByproductStock` + dikarungi
    # `FinishedGoodsStock`, sebangun catatan panjang di `stok.stok_produk`)
    # — sampai baris ini dibetulkan 6 Oktober 2026, bekatul yang dipacking
    # langsung tak pernah tersebut di sini.
    #
    # ⚠⚠ DIBACA DARI `source_id` proses, BUKAN `ByproductStock.jasa_id`/
    # `FinishedGoodsStock.jasa_id` — angka ini menjawab "berapa bekatul
    # KELUAR dari proses sosoh barang Anda", bukan "berapa yang MASIH milik
    # Anda". Sejak bekatul dicabut dari `HASIL_DITAHAN_BAWAAN` (pembalikan
    # keputusan 12), sebagian baris ini bisa jadi MASIH milik pesanan
    # (belum dipindah) — kalimatnya sengaja tak lagi mengaku "beralih milik
    # ke pabrik", sebab itu kini belum tentu benar.
    bekatul = (await db.execute(
        select(PolishingProcess.kode_proses, ByproductStock.berat_kg)
        .join(PolishingProcess, PolishingProcess.id == ByproductStock.source_id)
        .where(ByproductStock.jenis_produk == "bekatul",
               ByproductStock.source_type == "polishing",
               PolishingProcess.jasa_id == jasa_id)
        .order_by(PolishingProcess.kode_proses)
    )).all()
    bekatul_karung = (await db.execute(
        select(PolishingProcess.kode_proses, FinishedGoodsStock.berat_total_kg)
        .join(PolishingProcess, PolishingProcess.id == FinishedGoodsStock.source_id)
        .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
        .where(ProductSku.kategori == "bekatul",
               FinishedGoodsStock.source_type == "polishing",
               PolishingProcess.jasa_id == jasa_id)
        .order_by(PolishingProcess.kode_proses)
    )).all()
    per_proses: dict[str, float] = {}
    for kode, kg in [*bekatul, *bekatul_karung]:
        per_proses[kode] = per_proses.get(kode, 0.0) + float(kg or 0)
    if per_proses:
        baris_out.append("─" * 58)
        baris_out.append("BEKATUL, dari proses sosoh barang Anda — untuk diketahui")
        jum = 0.0
        for kode in sorted(per_proses):
            kg = per_proses[kode]
            jum += kg
            baris_out.append(f"   {kode:<16}{_kg_nota(kg):>12}")
        baris_out.append(f"   {'Jumlah':<16}{_kg_nota(jum):>12}")
    return "\n".join(baris_out)
