"""Menu navigasi — laci yang dibuka dari ikon sandwich.

**Dulu bilah lima tab di bawah**, dan alasannya masih benar: ibu jari
menjangkau bagian bawah layar, bukan bagian atas. Yang berubah adalah
jumlah layarnya. Tab yang dipaksa memuat enam tujuan menyempitkan tiap
sasaran jadi ~60px dengan label sembilan piksel — dan label sembilan
piksel tak terbaca di gudang yang kena matahari.

**Yang hilang bersama tab diganti; satu hal justru bertambah.** Dengan tab,
layar yang sedang dibuka selalu terlihat — maka judul layar naik ke bilah
atas, karena laci yang menyembunyikan posisi orang lebih buruk daripada tab
yang sempit. Sebaliknya laci memberi ruang yang tak pernah ada di tab:
KETERANGAN satu baris tiap tujuan, dan ANGKA yang lebih dari satu macam.

**Harganya disebut apa adanya:** tombol di sudut atas kiri adalah titik
terjauh dari ibu jari saat telepon dipegang satu tangan. Kalau kelak terasa
mengganggu, obatnya bukan kembali ke tab melainkan menambah usap dari tepi
kiri — tombolnya tetap ada untuk yang tak tahu usapan itu.

**Lencananya menghitung yang MENUNGGU ORANG, bukan semua yang berjalan.** Lot
yang sedang dikeringkan menunggu waktu; kalau ikut dihitung, lencananya tidak
pernah nol — dan lencana yang tidak pernah nol mengajari orang mengabaikannya.
"""
from __future__ import annotations

import logging

from app.database import SessionLocal
from app.models import User
from app.web.layar import ADMIN, MEJA, POLESAN, SUPER

log = logging.getLogger("web.nav")

#: (kunci layar, alamat, label). Label SELALU tertulis di layar — ikon saja
#: adalah ujian ingatan bagi orang yang tidak setiap hari memegang aplikasi.
#:
#: Lima tab menyempitkan tiap sasaran jadi ~72px pada layar 390px. Masih di
#: atas batas aman untuk ibu jari (tingginya tetap 56px), tetapi labelnya
#: harus pendek: "Pengaturan" patah dua baris di lebar itu, dan label yang
#: patah lebih buruk daripada label yang disingkat.
#: Kolom kelima: VIEW mana yang ditawari pintu ini (lihat `app.web.layar`).
#: `None` = keempatnya.
#:
#: Dulu kolom ini berisi satu kata, "admin", dan templat mengabaikan isinya —
#: ia cuma memeriksa "kolomnya terisi atau tidak" lalu membandingkan peran
#: dengan `PERAN_ADMIN_KEATAS`. Jadi kolomnya sebenarnya boolean yang menyamar
#: sebagai nama peran, dan tak ada cara menulis "Super Admin saja" maupun
#: "operator polesan saja". Sekarang isinya dipakai apa adanya.
#:
#: List audit BUKAN milik operator. Ia memuat seluruh jejak pencatatan
#: berikut tombol yang membatalkannya — dan orang yang bisa membatalkan
#: catatannya sendiri membuat jejak itu tak ada gunanya sebagai jejak.
#:
#: Menyembunyikan pintunya di sini BUKAN penjagaan: alamatnya tetap bisa
#: diketik, dan yang menjaga sungguhan adalah `butuh_admin` di rutenya.
#: Yang dikerjakan di sini cuma menghindari menawarkan pintu yang akan
#: ditolak.
TAB = (
    ("beranda",    "/",           "Beranda",        "Seberapa jauh hari ini", None),
    ("aksi",       "/aksi",       "Antrian tunggu", "Yang menunggu Anda", None),
    ("berjalan",   "/berjalan",   "Sedang berjalan", "Mesin yang menyala", None),
    # BUKAN untuk operator selepan. Katalog ini ada karena dulu sebagian
    # pekerjaan tak punya kartu; di Gudang 1 keadaan itu sudah lewat. Dari 13
    # aksi yang diterima operator selepan, 12 memang dikerjakan dari kartu di
    # Antrian tunggu — termasuk "Gabah masuk", yang WAJIB memilih tiket
    # timbang, dan tiap tiket yang belum ditaut sudah berdiri sebagai kartu.
    # Menyisakan katalognya berarti pintu kedua ke pekerjaan yang sudah punya
    # pintu, dan pintu kedua membuat orang ragu pintu mana yang benar.
    #
    # Yang ke-13 adalah "Batalkan input terakhir" — satu-satunya yang tak
    # punya kartu, karena yang dibatalkan bukan benda di gudang melainkan
    # catatan yang baru saja dibuat. Ia dipindahkan ke kaki Antrian tunggu,
    # tempat catatan itu dibuat. Menghapus katalog tanpa memindahkannya
    # berarti tiap salah ketik berubah jadi panggilan telepon ke Admin.
    #
    # Operator polesan menyusul 21 September 2026, atas permintaan pemilik:
    # seluruh penyosohan, tumpukan → silo, dan PK yang menunggu ditempatkan
    # sudah berkartu. Yang tersisa tanpa kartu — packing, bekatul curah,
    # batalkan — ikut ke kaki Antrian tunggu, sama seperti selepan.
    ("aksi_lain",  "/aksi-lain",  "Catat pekerjaan lain",
     "Harga, QC, barang keluar, batalkan", (SUPER, ADMIN)),
    # Kerja MEJA, bukan kerja gudang — dan karena itu bukan antrean. Gabah
    # di baris-barisnya sudah lama punya tempat; yang belum selesai adalah
    # keputusannya. Sejak awal pekerjaan admin.
    ("keputusan",  "/keputusan",  "Menunggu keputusan",
     "Harga gabah & PK luar, pencocokan output", MEJA),
    # Pecah dari "Menunggu keputusan" atas permintaan pemilik 24 September
    # 2026. Gerbangnya sama — MEJA — karena ini kerja meja, bukan kerja
    # gudang: OPERATOR TIDAK MELIHAT HALAMAN INI SAMA SEKALI. Yang ia lihat
    # adalah mutu barangnya, di kartu Stok dan kartu proses yang berjalan;
    # menilai mutu dan MENAGIH penilaiannya dua pekerjaan berbeda.
    #
    # Pintunya ikut padam saat pencatatan mutu dimatikan di Pengaturan —
    # lewat `PINTU_MATI`, bukan lewat daftar ini: TAB dibaca sekali saat app
    # dimuat, sedangkan setelan itu bisa berubah kapan saja.
    ("mutu",       "/mutu",       "Mutu & QC",
     "Mutu giling & PK luar yang belum dicatat", MEJA),
    # Stok berdiri SEBELUM Laporan: ia keadaan sekarang, sedangkan laporan
    # bercerita tentang yang sudah lewat. Operator ikut melihatnya — berapa
    # yang ada di gudang bukan angka uang, dan yang mengangkatnya tiap hari
    # berhak tahu berapa yang sudah terkumpul.
    ("stok",       "/stok",       "Stok",           "Bahan: gabah & PK yang masih ada", None),
    # ── Stok Produk — keputusan pemilik 26 September 2026 ──
    #
    # "bagusnya ada halaman baru yaitu Stok Produk, dan kartu hasil sosoh
    # berada di situ."
    #
    # Pembagiannya bersih, dan itu kekuatannya: /stok memuat BAHAN (gabah di
    # silo Gudang 1, PK di Gudang 2), /stok-produk memuat HASIL (beras dan
    # hasil samping). Subjudul keduanya sengaja menyebut bedanya — dua pintu
    # bernama Stok yang subjudulnya tak membedakan akan ditekan bergantian
    # oleh orang yang mencari satu angka.
    #
    # Pintunya padam untuk operator selepan lewat `PINTU_MATI`, bukan lewat
    # daftar peran ini: keduanya sama-sama berperan `operator`, dan yang
    # membedakan gudang tempatnya bekerja hari ini.
    ("stok_produk", "/stok-produk", "Stok Produk",
     "Beras dan hasil samping yang sudah jadi", None),
    # ── Kabar — keputusan pemilik 26 September 2026 ──
    #
    # Aplikasi ini sudah LIMA TEMPAT menulis notifikasi (harga gabah belum
    # diverifikasi, pengeringan telat, penyosohan selesai, packing, rantai
    # permintaan PK) dan sampai hari itu tak satu pun layar membacanya. Kabar
    # yang ditulis tanpa pembaca sama saja tak ditulis.
    #
    # Tempatnya SESUDAH Laporan dan bukan di puncak laci, dan itu disengaja:
    # yang menagih pekerjaan tetap Antrian tunggu dan Menunggu keputusan. Kabar
    # adalah yang SUDAH TERJADI dan perlu diketahui — sedudukan dengan Laporan,
    # bukan dengan antrean. Pintu kabar yang berdiri di atas antrean akan
    # ditekan lebih dulu tiap pagi, dan pekerjaan hari itu terbaca belakangan.
    ("laporan",    "/laporan",    "Laporan",        "Yang sudah terjadi hari ini", None),
    ("kabar",      "/kabar",      "Kabar",
     "Yang perlu Anda ketahui, 7 hari terakhir", None),
    ("audit",      "/audit",      "List audit",     "Semua catatan, bisa disaring",
     MEJA),
    ("pengaturan", "/pengaturan", "Pengaturan",     "Data diri, sandi, alat", None),
)

#: Judul yang naik ke bilah atas. Diambil dari daftar yang sama supaya nama
#: layar tak pernah berbeda antara menu dan judulnya.
JUDUL = {k: nama for k, _, nama, _, _ in TAB}


async def jumlah_menunggu(user: User | None) -> int:
    """Berapa hal yang menunggu tindakan orang ini. 0 = lencana disembunyikan.

    Database yang sedang terganggu TIDAK boleh menjatuhkan halaman yang
    sebenarnya bisa tampil tanpa angka ini — bilahnya tetap berguna tanpa
    lencana, dan halaman yang memang butuh database akan gagal pada kuerinya
    sendiri.
    """
    if user is None:
        return 0
    try:
        from app.services import berjalan
        async with SessionLocal() as db:
            return (await berjalan.untuk(db, user)).jumlah_menunggu
    except Exception:
        log.exception("Jumlah pekerjaan menunggu gagal dihitung (bilah tetap tampil)")
        return 0


async def jumlah_keputusan(user: User | None) -> int:
    """Lencana layar Menunggu keputusan.

    Terpisah dari lencana antrean: satu angka untuk dua daftar yang berbeda
    isi akan menagih pekerjaan di layar yang tak memuatnya — dan orang yang
    membuka layar lalu menemukannya kosong berhenti mempercayai lencana.
    """
    if user is None:
        return 0
    try:
        from app.peran import can_see_financials
        from app.services import berjalan
        if not can_see_financials(user):
            return 0
        async with SessionLocal() as db:
            return (await berjalan.untuk(db, user)).jumlah_keputusan
    except Exception:
        log.exception("Jumlah keputusan gagal dihitung (laci tetap tampil)")
        return 0


async def lencana(user: User | None) -> dict:
    """Kedua lencana laci dari SATU kueri.

    Dipakai layar yang tak punya daftar `Berjalan` di tangannya. Yang sudah
    punya memakai `b.jumlah_menunggu` / `b.jumlah_keputusan` langsung —
    memanggil ini di sana berarti menyusun ulang seluruh daftar untuk kedua
    kalinya hanya demi dua angka.

    Satu fungsi untuk keduanya supaya layar baru tak bisa lupa salah satunya:
    lencana yang hilang di sebagian layar lebih membingungkan daripada
    lencana yang tak pernah ada.
    """
    if user is None:
        return _KOSONG()
    try:
        from app.services import berjalan
        async with SessionLocal() as db:
            b = await berjalan.untuk(db, user)
        # Angkanya disusun `Berjalan.lencana()` — satu tempat untuk keempatnya,
        # supaya layar yang memakai jalur ini dan layar yang memegang daftarnya
        # sendiri tak pernah menggambar laci yang berbeda. Operator tak perlu
        # disaring lagi di sini: `untuk()` hanya mengisi `meja` untuk yang boleh
        # melihat uang, jadi kedua angka meja sudah nol dengan sendirinya.
        return b.lencana()
    except Exception:
        log.exception("Lencana gagal dihitung (laci tetap tampil)")
        return _KOSONG()


def _KOSONG() -> dict:
    """Laci tanpa angka — dipakai saat penggunanya tak ada atau kueri gagal.

    `PINTU_MATI` sengaja KOSONG di sini: kegagalan kueri tak boleh menyembunyikan
    pintu. Pintu yang hilang terbaca sebagai "layarnya sudah tak ada", dan itu
    lebih membingungkan daripada pintu yang dibuka lalu ternyata kosong.
    """
    return {"MENUNGGU": 0, "BERJALAN": 0, "KEPUTUSAN": 0, "MUTU": 0,
            "PRODUK": 0, "KABAR": 0, "KABAR_MERAH": False,
            "MUTU_AKTIF": True, "PINTU_MATI": ()}
