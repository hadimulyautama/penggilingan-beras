"""Menu navigasi — laci yang dibuka dari ikon sandwich.

**Dulu bilah lima tab di bawah**, dan alasannya masih benar: ibu jari
menjangkau bagian bawah layar, bukan bagian atas. Yang berubah adalah
jumlah layarnya. Tab yang dipaksa memuat enam tujuan menyempitkan tiap
sasaran jadi ~60px dengan label sembilan piksel — dan label sembilan
piksel tak terbaca di gudang yang kena matahari.

**Yang hilang bersama tab diganti; satu hal justru bertambah.** Dengan tab,
layar yang sedang dibuka selalu terlihat — maka judul layar naik ke bilah
atas, karena laci yang menyembunyikan posisi orang lebih buruk daripada tab
yang sempit. Sebaliknya laci memberi ruang yang tak pernah ada di tab: ANGKA
yang lebih dari satu macam.

Kalimat di atas dulu menyebut dua hal yang bertambah; yang satu lagi
KETERANGAN satu baris tiap tujuan, dan ia DICABUT 28 September 2026 atas
permintaan pemilik: "sidebar cukup nama halamannya saja", "deskripsi tambahan
tidak perlu". Kolom `ket` di bawah tetap ada — ia menjelaskan tiap pintu
kepada yang membaca kodenya, dan itu masih berguna; yang berhenti cuma
menggambarnya di layar. Angkanya tetap, atas permintaan yang sama.

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
#: ── MEDAN KEENAM: IKON, dan ia pindah ke sini 29 September 2026 ──
#:
#: Sebelumnya ikon laci adalah rantai `if/elif` tertulis-tangan di
#: `base.html`, dan cabang terakhirnya `{% else %}⚙`. Akibatnya LIMA pintu
#: memakai gerigi yang sama — Catat pekerjaan lain, Stok Produk, Barang
#: Keluar, List audit, Pengaturan — dan ikon yang dipakai lima pintu berhenti
#: menjadi ikon: mata tak bisa membedakan apa pun dengannya. Pemilik
#: mengeluhkannya sebagai "ikonnya salah"; yang salah bukan bentuknya.
#:
#: Tempatnya di sini, bukan di templat, dan alasannya bukan kerapian. Templat
#: itu SENDIRI sudah menuliskan prinsipnya beberapa baris di atas rantai itu,
#: untuk hal yang lain: "Daftar KUNCI, bukan syarat per layar di dalam templat
#: ini — app yang menambah layar bersyarat besok tak perlu menyunting berkas
#: bersama." `hmu_tampilan` dipakai lebih dari satu aplikasi; menambah layar
#: seharusnya tak menuntut menyunting berkas milik bersama demi satu huruf.
#:
#: ⚠ BUKAN EMOJI, dan ini syarat teknis bukan selera. Emoji tampil BERWARNA
#: dan bentuknya berbeda di tiap merek HP; dua belas ikon monokrom ditambah
#: satu emoji akan terbaca seperti kesalahan. Semuanya dari blok yang sudah
#: terbukti tampil di app ini — Geometric Shapes (U+25xx) dan Arrows (U+21xx).
#:
#: ⚠ DAN WAJIB DIUJI DI HP SUNGGUHAN. Sebagian mesin Android tak punya glif
#: untuk sebagian tanda ini dan menggambar kotak kosong. Kalau ada yang kotak,
#: ganti — jangan biarkan, sebab kotak kosong lebih buruk daripada gerigi yang
#: dipakai bersama.
TAB = (
    ("beranda",    "/",           "Beranda",        "Seberapa jauh hari ini", None, "⌂"),
    ("aksi",       "/aksi",       "Antrian tunggu", "Yang menunggu Anda", None, "≡"),
    ("berjalan",   "/berjalan",   "Sedang berjalan", "Mesin yang menyala", None, "◷"),
    # Kerja MEJA, bukan kerja gudang — dan karena itu bukan antrean. Gabah
    # di baris-barisnya sudah lama punya tempat; yang belum selesai adalah
    # keputusannya. Sejak awal pekerjaan admin.
    ("keputusan",  "/keputusan",  "Menunggu keputusan",
     "Harga gabah & PK luar, pencocokan output", MEJA, "✓"),
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
     "Mutu giling & PK luar yang belum dicatat", MEJA, "◎"),
    # Stok berdiri SEBELUM Laporan: ia keadaan sekarang, sedangkan laporan
    # bercerita tentang yang sudah lewat. Operator ikut melihatnya — berapa
    # yang ada di gudang bukan angka uang, dan yang mengangkatnya tiap hari
    # berhak tahu berapa yang sudah terkumpul.
    #
    # ── Sub-menu "Stok PK" / "Stok Produk" — keputusan pemilik 5 Oktober
    #    2026 ──
    #
    # "ringkas menu. buat stock menjadi main menu memiliki sub menu. yaitu
    # stock PK dan stock produk." Pintu ini jadi `<summary>` berdropdown
    # (`Berjalan.submenu()`, kunci "stok") kapan pun "Stok Produk" ikut
    # ditawarkan — klik membuka dua pilihan, bukan langsung ke `/stok`.
    # Operator selepan (yang tak ditawari "Stok Produk" sama sekali) tetap
    # melihatnya sebagai pintu biasa; itu bukan dikecualikan di sini, sebab
    # aturan ≥2-pilihan di `submenu()` sudah menjamin pintu tanpa dropdown
    # untuk satu tujuan.
    ("stok",       "/stok",       "Stok",           "Bahan: gabah & PK yang masih ada", None, "▦"),
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
    # ⚠ BARIS INI TETAP DI `TAB` TETAPI TAK PERNAH LAGI BERDIRI SENDIRI DI
    # LACI (keputusan 5 Oktober 2026, lihat catatan di atas "stok"): pintunya
    # kini SELALU masuk `PINTU_MATI` (`Berjalan.lencana()`), untuk SIAPA PUN
    # — bukan cuma operator selepan seperti sebelumnya. Barisnya dipertahankan
    # di sini karena `JUDUL` (judul bilah atas halaman `/stok-produk`) dan
    # `TAB_KUNCI` (penentu "halaman ini punya laci") dibaca dari seluruh
    # daftar `TAB`, bukan cuma yang tampil di laci — menghapus barisnya akan
    # membuat `/stok-produk` kehilangan judul DAN seluruh bingkai navigasinya,
    # padahal halamannya sendiri sama sekali tidak berubah.
    ("stok_produk", "/stok-produk", "Stok Produk",
     "Beras dan hasil samping yang sudah jadi", None, "◧"),
    # ── Stok Produk · Titipan jasa — keputusan pemilik 6 Oktober 2026 ──
    #
    # "buat saja halaman khusus stock produk dan stock hasil samping dari
    # jasa. masuk di sub menu stock. tapi pisahkan per pelanggan pemilik
    # barang." `/stok-produk` memuat PABRIK saja; barang titipan (beras &
    # hasil samping milik pesanan jasa) dapat halamannya sendiri di sini,
    # supaya keduanya tak pernah bercampur arti.
    #
    # SELALU di `PINTU_MATI` (lihat `Berjalan.lencana()`), sama seperti
    # "stok_produk" — pintu berdiri sendiri di laci hanya menawarkan jalan
    # kedua ke tempat yang sudah terjangkau lewat sub-menu "Stok".
    ("stok_produk_jasa", "/stok-produk-jasa", "Produk Jasa",
     "Beras & hasil samping milik pesanan jasa", None, "◫"),
    # ── Barang Keluar — permintaan pemilik 28 September 2026 ──
    #
    # "kita butuh satu halaman untuk transaksi barang keluar."
    #
    # Tempatnya SESUDAH Stok Produk dan bukan di antara antrean: ia DAFTAR,
    # bukan antrean. Yang menagih pekerjaan tetap Antrian tunggu (kartu muat)
    # dan Menunggu keputusan (kartu verifikasi); halaman ini menjawab
    # pertanyaan yang tak bisa dijawab keduanya — "truk yang tadi siang bawa
    # apa saja?" — sebab keduanya menyusun menurut pekerjaan, bukan menurut
    # truk.
    #
    # Pintunya padam untuk operator selepan lewat `PINTU_MATI`, sama seperti
    # Stok Produk: barang jadi berdiri di Gudang 2.
    ("barang_keluar", "/barang-keluar", "Barang Keluar",
     "Perintah muat, muatan, dan riwayatnya", None, "⇥"),
    # ── Jasa — keputusan pemilik 1 Oktober 2026 ──
    #
    # Pesanan jasa LAHIR di Pos Timbang (pelanggan + pesanannya) dan diterima
    # operator lewat kartu Antrian tunggu. Jadi halaman ini tempat MENAMPILKAN,
    # bukan tempat menerima — dan itu sebabnya ia daftar, bukan antrean: yang
    # menagih pekerjaan tetap Antrian tunggu.
    #
    # Yang dijawabnya tak bisa dijawab layar lain: barang orang lain tersebar
    # di enam tempat (halaman, pengering, silo, PK G1, PK G2, barang jadi), dan
    # saringan stok justru MEMBUANGNYA dari tiap layar stok — benar untuk stok
    # pabrik, dan karena itu barang pelanggan tak punya satu pun layar sampai
    # halaman ini ada.
    #
    # MEJA: menutup dan membatalkan pesanan kerja meja, dan "berapa ton barang
    # orang lain di gudang" bukan angka yang operator butuh sambil mengangkat.
    #
    # ⚠ IKONNYA dari Geometric Shapes (U+25xx), BUKAN emoji — sebagian mesin
    # Android menggambar emoji sebagai kotak kosong, dan ikon yang jadi kotak
    # pada satu ponsel membuat pintunya tak bernama di situ. "◇" dipilih karena
    # belum dipakai pintu lain: barang yang dititipkan, bukan dimiliki.
    ("jasa",       "/jasa",       "Jasa",
     "Barang titipan pelanggan: sisa & pengambilannya", MEJA, "◇"),
    # ── Riwayat sosoh — keputusan pemilik 2 Oktober 2026 ──
    #
    # "berisi kartu proses sosoh yang selesai berikut seluruh informasinya dan
    # hasilnya. terkhusus berapa persen yang jadi beras, berapa persen broken,
    # berapa persen menir, berapa persen bekatul, lalu berapa persen susut
    # debu/bobot."
    #
    # Yang dijawabnya tak dijawab satu pun layar lain, dan itu sebabnya ia
    # pintu sendiri alih-alih blok di Stok Produk: SUSUT bukan stok. Layar stok
    # menyebut apa yang ADA; susut justru yang TIDAK ada — ia cuma terbaca
    # sebagai selisih antara yang masuk mesin dan yang keluar darinya, dan
    # selisih itu tak disimpan di kolom mana pun.
    #
    # Tempatnya SESUDAH Jasa dan sebelum Laporan: ia riwayat, sederajat dengan
    # Laporan, bukan antrean. Dan ia dibuka beberapa kali sepekan — bukan tiap
    # jam — jadi ia turun dari blok stok yang di atasnya.
    #
    # PERANNYA DISEBUT TIGA, bukan `None` + PINTU_MATI (keputusan pemilik:
    # "hanya super admin, admin dan operator gudang 2 yang bisa lihat").
    # Keduanya sama-sama menyembunyikan pintunya dari operator selepan, tetapi
    # yang ini menuliskan siapa yang BOLEH, bukan siapa yang dikecualikan —
    # dan daftar pengecualian harus disunting ulang tiap kali view baru lahir,
    # sedangkan daftar yang boleh tidak.
    #
    # ⚠ Pintu yang disembunyikan BUKAN penjagaan: rutenya menjaga sendiri
    # (`layar_sosoh` menuntut `_is_g2_operator`, yang berarti admin ke atas
    # ATAU operator yang sedang bekerja di Gudang 2).
    #
    # ⚠ IKON "◭" dari Geometric Shapes (U+25ED) — blok yang sama dengan enam
    # ikon lain yang sudah terbukti tampil di app ini (◇ ◷ ◧ ◎ ▦ ▤), BUKAN
    # emoji. Dipilih karena SILUETNYA satu-satunya segitiga di laci ini:
    # lingkaran, kotak, dan belah ketupat sudah terpakai, dan ikon yang
    # sesiluet dengan tetangganya berhenti membedakan apa pun pada layar yang
    # kena matahari. Setengahnya terisi — kebetulan yang menolong, sebab yang
    # dijawab halaman ini memang pembagian satu bahan baku.
    #
    # ⚠ WAJIB DILIHAT DI HP SUNGGUHAN. Kalau ia tergambar sebagai kotak kosong
    # pada mesin Android tertentu, gantinya "△" (U+25B3) — segitiga yang sama
    # tetapi ada di hampir setiap fon. Jangan dibiarkan kotak: ikon yang jadi
    # kotak membuat pintunya tak bernama di perangkat itu.
    ("riwayat_sosoh", "/riwayat-sosoh", "Riwayat sosoh",
     "Tiap penyosohan selesai: hasil, persen, dan susutnya",
     (SUPER, ADMIN, POLESAN), "◭"),
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
    ("laporan",    "/laporan",    "Laporan",        "Yang sudah terjadi hari ini", None, "▤"),
    ("kabar",      "/kabar",      "Kabar",
     "Yang perlu Anda ketahui, 7 hari terakhir", None, "✉"),
    ("audit",      "/audit",      "List audit",     "Semua catatan, bisa disaring",
     MEJA, "↺"),
    # ── DIPINDAH KE BAWAH 29 September 2026 ──
    # Permintaan pemilik: "catat pekerjaan lain posisinya diatas pengaturan
    # saja." Ia memang bukan pekerjaan harian lagi: sejak barang keluar,
    # packing, bekatul, dan pembatalan punya pintunya masing-masing, yang
    # tersisa di katalog ini tinggal QC, pembelian karung, dan pencocokan
    # tiket — hal yang dibuka beberapa kali seminggu, bukan tiap jam.
    #
    # Urutan laci ini URUTAN SEBERAPA SERING, bukan urutan alur kerja:
    # yang paling sering dibuka berdiri paling dekat ibu jari.
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
    # Subjudulnya ikut dibetulkan 29 September 2026: "Harga" sudah tak ada di
    # Pos Produksi sama sekali, dan "barang keluar" kini punya halamannya
    # sendiri. Subjudul yang menjanjikan pekerjaan yang tak ada di dalamnya
    # membuat orang membuka pintu ini untuk mencarinya.
    ("aksi_lain",  "/aksi-lain",  "Catat pekerjaan lain",
     "QC, pembelian karung, pembatalan", (SUPER, ADMIN), "✎"),
    ("pengaturan", "/pengaturan", "Pengaturan",     "Data diri, sandi, alat", None, "⚙"),
)

#: Judul yang naik ke bilah atas. Diambil dari daftar yang sama supaya nama
#: layar tak pernah berbeda antara menu dan judulnya.
JUDUL = {k: nama for k, _, nama, _, _, _ in TAB}


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
            "MUTU_AKTIF": True, "PINTU_MATI": (),
            # Sub-menu KOSONG saat kuerinya gagal, sama alasannya dengan
            # `PINTU_MATI`: pintu antrean tetap bisa diklik dan tetap membuka
            # halamannya. Sub-menu yang gagal dihitung tak boleh mengurung
            # orang di muka pintu.
            "SUBMENU": {}}
