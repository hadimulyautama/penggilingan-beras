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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dryer, Jasa, Pelanggan, Silo


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

    Satu proses sosoh jasa menghasilkan barang DUA pemilik:

        beras (semua grade), menir, broken, reject  →  pesanan (kembali)
        bekatul                                     →  pabrik  (beralih milik)

    ⚠ KEPUTUSANNYA DITARUH SEKALI, DI HULU — dan itu yang membuat seluruh
    hilirnya bersih. Keputusan pemilik 12: *"bekatul tidak kembali bukan berarti
    barangnya tidak boleh keluar. bekatul otomatis berubah kepemilikan jadi
    milik kami."* Jadi bekatul jasa adalah stok pabrik BIASA: ia masuk Stok
    Produk, boleh diperintahkan keluar, boleh dijual, lewat jalur yang sama
    dengan bekatul lain.
    
    Karena keputusan itu diambil DI SINI, saringan seragam `WHERE jasa_id IS
    NULL` di seluruh pembaca stok selamat tanpa satu pun cabang khusus: bekatul
    ber-`jasa_id` NULL memang HARUS muncul di perintah penjualan biasa.

    ⚠ Ini kebalikan dari yang mudah dikira. Naluri pertama saat menulis saringan
    adalah "sembunyikan segala yang berbau jasa"; bekatul justru pengecualiannya,
    dan ia lolos dengan sendirinya — bukan karena ada `if bekatul` di hilir.

    `hasil_ditahan` adalah CUPLIKAN kesepakatan pesanan itu, dibaca dari
    barisnya — BUKAN daftar yang ditulis di sini. Kalau kebijakannya dibaca dari
    kode, mengubahnya suatu hari akan mengubah arti seluruh pesanan lama,
    termasuk yang notanya sudah dipegang pelanggan.
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

    DUA jalan masuk ikut dibaca: PK yang masuk langsung ke silo
    (`pk_gudang2_intakes.silo_id`) dan PK yang masuk sebagai tumpukan lalu
    dipindah (`pk_tumpukan_to_silo` → intake asalnya). Membaca satu saja berarti
    silo yang isinya datang lewat tumpukan terbaca "milik pabrik" — dan jalur
    tumpukan justru jalur bawaan PK jasa.

    `pk_tumpukan_to_silo` sengaja TIDAK diberi kolom `jasa_id` sendiri:
    pemiliknya sudah ada di intake asalnya, dan kolom kedua yang berarti hal
    sama adalah kolom yang suatu hari berselisih dengan yang pertama.

    Himpunan HAMPA berarti silonya kosong — BUKAN "milik pabrik" (itu `{None}`).
    Pemanggil yang memperlakukan keduanya sama akan menolak silo kosong, atau
    menerima silo campuran, tergantung arah salahnya.
    """
    from app.models import PkGudang2Intake, PkTumpukanToSilo
    # Impor malas: `gudang2.service` mengimpor berkas ini di kepalanya, jadi
    # impor di tingkat modul akan melingkar.
    from app.penggilingan.gudang2.service import hitung_stok_silo

    if float(await hitung_stok_silo(db, silo_id)) <= 0.001:
        return set()

    # Muatan TERBARU, dari kedua jalan masuk, diurutkan bersama. `waktu_masuk`
    # untuk yang langsung, `waktu` pemindahan untuk yang lewat tumpukan — yang
    # dibandingkan kapan barangnya ADA DI SILO, bukan kapan ia tiba di pabrik.
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

    calon = [b for b in (langsung, lewat_tumpukan) if b is not None]
    if not calon:
        # Stoknya positif tetapi tak ada satu pun muatan yang menjelaskannya —
        # keadaan yang seharusnya mustahil. Dikembalikan sebagai "milik pabrik"
        # supaya penjaganya memilih sisi yang AMAN: penuangan berikutnya ditolak
        # bila barangnya bertuan, bukan diterima diam-diam.
        return {None}
    terbaru = max(calon, key=lambda b: b[0])
    return {int(terbaru[1]) if terbaru[1] is not None else None}


