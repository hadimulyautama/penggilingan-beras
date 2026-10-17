"""Pekerjaan yang belum tertutup — isi layar "Berjalan".

Dibagi dua, dan pembagian itulah inti layar ini:

  · **Menunggu Anda** — ada orang yang harus bertindak SEKARANG. Inilah yang
    dihitung lencana di bilah navigasi;
  · **Sedang berjalan** — menunggu WAKTU, bukan orang: gabah yang sedang
    dikeringkan, giling yang sedang berputar. Tidak dihitung.

Kalau keduanya dijadikan satu angka, lencananya tidak pernah nol — dan lencana
yang tidak pernah nol mengajari orang mengabaikan lencana.

Tiap baris membawa `aksi`: id aksi yang MENUTUPnya. Layar memakainya untuk
membuka lembar aksi yang benar dalam satu ketukan. Itu bedanya dengan laporan
status gudang — laporan memberi tahu, layar ini menyelesaikan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.services import keputusan as K
from app.penggilingan.gudang1.services.bobot import (
    Bobot, dari_batch, dari_batches, dari_nilai)
from app.services.jasa import nama_pemilik, nama_pemilik_banyak
from app.models import (
    DryingLot,
    MillingProcess,
    MillingProcessVerification,
    MillingQcLog,
    PermintaanPk,
    PurchaseBatch,
    SiloStorage,
    Supplier,
    User,
)


@dataclass
class Tombol:
    """Satu tujuan yang bisa ditekan LANGSUNG dari kartunya.

    Antrean adalah pekerjaan yang paling sering dilakukan — tiap truk yang
    datang. Membentangkan kartu lalu menyuruh orang membuka lembar melayang
    lalu memilih dari daftar tarik-turun adalah tiga ketukan dan satu layar
    yang menutupi barisnya sendiri, untuk satu keputusan: gabah ini mau ke
    mana. Tombolnya ditaruh di kartunya.
    """

    nama: str
    ket: str
    post: str
    data: dict
    utama: bool = False
    #: Alasan ia tak bisa ditekan. Kosong = boleh. Yang tak boleh tetap
    #: DITAMPILKAN berikut alasannya: tujuan yang hilang diam-diam membuat
    #: orang mengira mesinnya tak ada, lalu mencarinya di layar lain.
    mati: str = ""


@dataclass
class Baris:
    kode: str
    isi: str
    keadaan: str
    #: Aksi yang menutup baris ini. None = tidak ada yang bisa dikerjakan
    #: sekarang; barisnya tampil tanpa panah dan tidak bisa ditekan.
    aksi: str | None = None
    #: Yang menandai baris ini di dalam formulirnya — nomor tiket, kode lot,
    #: kode batch. Dibawa serta supaya lembar aksinya sudah terisi.
    #:
    #: Tanpa ini, orang yang menekan sebuah baris ditanya lagi baris mana yang
    #: ia maksud — padahal ia baru saja menunjuknya. Itu membatalkan seluruh
    #: guna layar ini.
    nilai: str | None = None
    sejak: datetime | None = None
    #: Fase barang: di mana ia berada sekarang. Layar Catat mewarnai kartunya
    #: menurut ini — "baru" (belum ditindak) · "dryer" · "silo" · "giling".
    #: Warnanya berurut mengikuti perjalanan barangnya sendiri, jadi posisinya
    #: terbaca sekilas tanpa membaca hurufnya.
    fase: str = "baru"
    #: Tindakan yang mungkin pada keadaan ini: (id aksi, nama, keterangan).
    #:
    #: Kosong berarti hanya ada satu, yaitu `aksi` — dan yang satu itu dibuka
    #: langsung tanpa menanyakan apa pun. Sebuah lot yang sedang dikeringkan
    #: punya dua (perbarui kadar air / selesai pengeringan); yang sedang
    #: didinginkan cuma satu, dan menampilkan daftar berisi satu pilihan
    #: adalah satu ketukan yang tak membawa keputusan apa pun.
    pilihan: list[tuple[str, str, str]] = field(default_factory=list)

    # ── Bentuk kartu yang bisa DIPINDAI ──
    #
    # `isi` yang berisi beberapa kalimat bertumpuk bukan keterangan melainkan
    # dinding: ukurannya sama, warnanya sama, tebalnya sama, jadi mata tak
    # punya tempat mendarat dan tak ada yang terbaca sampai orang berhenti
    # mengeja. Kolom-kolom di bawah ini memberi tiap jenis keterangan
    # bentuknya sendiri. Semuanya opsional — baris yang belum memakainya
    # tetap tampil seperti dulu lewat `isi`.

    #: Nama yang dibaca lebih dulu: pemasok, mesin, silo. Kosong = pakai kode.
    judul: str | None = None
    #: (angka, satuan) — satu-satunya angka di baris judul, rata kanan. Mata
    #: memindai kolom kanan jauh lebih cepat daripada baris demi baris.
    utama: tuple[str, str] | None = None
    #: Baris kecil di bawah judul: kode, kondisi, plat.
    sub: str | None = None
    #: Pasangan label–nilai yang padat mendatar.
    fakta: list[tuple[str, str]] = field(default_factory=list)
    #: Rincian batch: (nama, berat, waktu). Menjorok dan lebih redup — ia
    #: detail, bukan judul.
    anak: list[tuple[str, str, str]] = field(default_factory=list)
    #: Rincian dengan judul kelompok. Baris bisa membawa penanda tampilan
    #: tambahan setelah (nama, berat, keterangan), mis. asal lot di bawah silo.
    anak_grup: list[tuple[str, list[tuple[str, ...]]]] = field(default_factory=list)
    #: Satu-satunya baris berwarna, untuk yang menuntut perhatian.
    nota: str | None = None
    #: Seberapa keras nota itu bicara. "hati" untuk keadaan yang MENAHAN
    #: pekerjaan — mesin yang belum dinyalakan, proses yang dijeda. Keduanya
    #: sebelumnya digambar setipis keterangan biasa, jadi kartu yang berhenti
    #: terbaca sama dengan kartu yang berjalan; dan yang terbaca sama akan
    #: dilewati sama.
    nota_jenis: str | None = None
    #: Yang TERBACA dari angka-angkanya, bukan dari keadaan prosesnya:
    #: gabah belum merata, sensor mesin melenceng. Terpisah dari `nota` karena
    #: keduanya bisa muncul bersamaan — lot yang dijeda pun bisa isinya belum
    #: merata — dan menggabungkannya membuat yang satu menutupi yang lain.
    catatan: list[str] = field(default_factory=list)
    #: Tujuan yang bisa ditekan langsung, tanpa lembar melayang. Kalau berisi,
    #: `pilihan` tak dipakai — satu kartu satu cara dikerjakan.
    tombol: list[Tombol] = field(default_factory=list)

    # ── Bentuk PADAT, untuk Beranda ──
    #
    # Beranda memuat benda yang sama dengan layar Sedang berjalan — daftar
    # yang sama, bukan salinannya — hanya dipadatkan jadi satu baris: nama,
    # satu angka, satu keterangan. Gunanya Beranda adalah memuat seluruh
    # pabrik dalam satu layar tanpa menggulir; kartu penuh membatalkan itu.

    #: Penanda blok di layar antrean. Kosong = blok utama.
    #:
    #: Barisnya tetap tinggal di `menunggu`, bukan dipindah ke daftar sendiri:
    #: gabah yang menumpuk TETAP pekerjaan yang menunggu orang, dan
    #: mengeluarkannya dari daftar itu akan mengecilkan lencana antrean —
    #: lencana yang tak menghitung pekerjaan yang ada adalah lencana yang
    #: mengajari orang bahwa gudangnya sudah beres padahal belum.
    kelompok: str | None = None

    #: Satu kalimat pengganti `fakta` + `anak` di kartu padat. Kosong = pakai
    #: `sub`, karena baris yang tak punya apa-apa untuk diringkas memang tak
    #: perlu dipaksa punya.
    ringkas: str | None = None
    #: Gudang asal baris ini — "g1" / "g2", atau None bila memang tak punya
    #: (jenis timbang yang belum dipetakan belum punya gudang tujuan, dan
    #: menebaknya berarti mengarahkan orang ke gudang yang mungkin salah).
    #:
    #: Dicap oleh FUNGSI PENYUSUNNYA, sekali di ujung, bukan di tiap
    #: pemanggilan `Baris(...)`: seratus tempat yang harus mengingat menyebutkan
    #: gudangnya adalah seratus tempat yang bisa lupa, dan yang lupa akan
    #: menghilang dari penyaring tanpa satu tanda pun. Dipakai pil penyaring
    #: gudang di layar Sedang berjalan (Pos Produksi & Meja).
    gudang: str | None = None

    #: Sudah sejauh mana, 0..1 — hanya untuk yang punya ukuran "sejauh mana".
    #: Pengeringan punya; giling dan silo tidak, dan memberi mereka batang
    #: kemajuan palsu lebih buruk daripada tak memberi apa-apa.
    maju: float | None = None

    #: Neraca bobot LIVE (belum final) — beras/samping/susut atas bahan
    #: baku SEJAUH INI. Hanya penyosohan: giling tak punya pecahan hasil
    #: (PK saja), dan "susut" atas bahan yang belum semuanya keluar mesin
    #: akan terbaca sebagai kehilangan padahal cuma belum diproses — label
    #: di layar WAJIB menyebutnya "sementara", bukan angka akhir.
    #:
    #: `NeracaSosoh` dari `gudang2.polishing.neraca_sosoh()` — SATU sumber
    #: dengan kartu Riwayat Penyosohan (`riwayat_sosoh.html`), supaya angka
    #: yang sama tak pernah berselisih walau markupnya digambar dua kali.
    neraca: object | None = None

    #: Pemilik titipan — None = pabrik. Dipakai `grup_baris()` untuk
    #: memisahkan kartu titipan dari kartu pabrik yang kebetulan memakai
    #: `aksi` yang sama (mis. "Packing jasa" vs "Tunggu packing", keduanya
    #: `aksi="catat_packing"`) — penyaringan yang `aksi`/`kelompok` sendirian
    #: tak bisa menjawab, sebab keduanya menyebut PEKERJAAN, bukan PEMILIK.
    jasa_id: int | None = None
    #: Kolom antrean bahan baku. Metadata ini hanya untuk ringkasan tabel;
    #: rincian kartu tetap memakai sumber dan susunan yang sudah ada.
    tiket_kode: str | None = None
    komoditas: str | None = None
    kendaraan: str | None = None
    status_jasa: bool | None = None
    nama_tabel: str | None = None


@dataclass
class Berjalan:
    """Tiga golongan, dan batasnya satu kalimat.

    · `menunggu` — gabah yang BELUM PUNYA TEMPAT: tiket yang belum ditindak,
      batch yang penempatannya gagal, gabah yang menumpuk di lantai. Inilah
      daftar yang seharusnya kosong saat pulang; kalau masih berisi, ada gabah
      yang bermalam tanpa tempat.

    · `berjalan` — mesin yang sedang bekerja. Tak bisa dipercepat siapa pun.

    · `transit` — gabah yang sudah punya tempat tetapi tak sedang diapa-apakan:
      menunggu mesin dinyalakan, menunggu diangkut ke silo, menunggu digiling.
      Bukan antrean karena tempatnya sudah ada; bukan pula berjalan karena tak
      ada mesin yang menyala untuknya — menyebutnya berjalan akan membuat kata
      itu berhenti berarti apa-apa.
    """

    menunggu: list[Baris] = field(default_factory=list)
    berjalan: list[Baris] = field(default_factory=list)
    transit: list[Baris] = field(default_factory=list)
    #: Kerja MEJA, bukan kerja gudang: harga yang belum diverifikasi, mutu
    #: yang belum diperiksa, output giling yang belum dicocokkan. Hanya
    #: terlihat oleh yang boleh melihat uang — operator tidak pernah, dan
    #: admin yang sedang memakai Mode operator pun tidak.
    #:
    #: Dipisah dari `menunggu` karena ia bukan pekerjaan yang sama: gabahnya
    #: mungkin sudah lama duduk di silo. Dicampur, barisnya terbaca seperti
    #: tiket yang tertinggal — dan orang akan mencari gabah yang sebenarnya
    #: sudah lama ditempatkan.
    meja: list[Baris] = field(default_factory=list)
    #: Apakah pabrik ini MENCATAT mutu (`setelan.fitur_mutu`). Dibawa di sini
    #: karena penyusunnya sudah membacanya untuk memutuskan apakah baris qc_*
    #: dipancarkan sama sekali — membacanya lagi di layar berarti satu kueri
    #: tambahan pada tiap halaman, dan dua tempat yang bisa menjawab berbeda.
    mutu_aktif: bool = True
    #: Apakah pintu "Stok Produk" ditawarkan pada pembaca ini. Operator
    #: selepan: tidak — lihat `lencana()`.
    pintu_produk: bool = True
    #: Berapa lot yang berasnya sudah keluar mesin tetapi BELUM dipacking.
    #: Lencana pintu Stok Produk; nol berarti tak ada lencana.
    jumlah_produk: int = 0
    #: Kabar yang belum pernah tergambar di mata orang ini. Disimpan di sini —
    #: bukan dihitung ulang di tiap layar — karena seluruh laci disusun dari
    #: satu benda: layar yang lupa salah satu angkanya menggambar laci yang
    #: berbeda dari laci di layar sebelahnya.
    jumlah_kabar: int = 0
    #: Ada kabar MERAH yang belum dibaca — lencananya berganti warna, bukan
    #: cuma berganti angka. Lihat `kabar.ada_merah`.
    kabar_merah: bool = False
    #: Dua bendera dropdown "Riwayat Proses" (lihat `submenu()`). Bawaannya
    #: `True` sama alasannya dengan `pintu_produk`: kegagalan menghitungnya
    #: tak boleh diam-diam menyembunyikan pilihan yang sah.
    boleh_riwayat_sosoh: bool = True
    #: Penggilingan/Pengeringan/Transfer — ketiganya Gudang 1, satu bendera.
    boleh_riwayat_g1: bool = True

    @property
    def jumlah_menunggu(self) -> int:
        """Lencana antrean. Kerja meja TIDAK ikut — ia punya layar & lencana
        sendiri, dan menghitungnya di sini membuat lencana antrean menagih
        pekerjaan yang tak ada di dalamnya."""
        return len(self.menunggu)

    def jumlah_grup(self) -> dict[str, int]:
        """Berapa kartu per GRUP antrean — isi sub-menu "Antrian tunggu".

        Dihitung dari daftar yang sama yang akan digambar, bukan dengan kueri
        tersendiri: angka sub-menu yang disusun terpisah dari isinya akan
        menyebut 3 pada pintu yang begitu dibuka memperlihatkan 2, dan orang
        berhenti mempercayai angkanya setelah sekali itu.
        """
        n = {kunci: 0 for kunci, _ in GRUP_ANTREAN}
        for b in self.menunggu:
            n[grup_baris(b)] += 1
        return n

    def jumlah_grup_keputusan(self) -> dict[str, int]:
        """Berapa kartu per KATEGORI — isi sub-menu "Menunggu keputusan".

        Kembaran `jumlah_grup`, dan sama sebabnya. `self.meja` membawa mutu
        DAN non-mutu bercampur (pemisahannya baru terjadi saat `/keputusan`
        dan `/mutu` merender); baris mutu dilompati di sini — kategori mutu
        sudah tak ada di `GRUP_KEPUTUSAN` sejak sumbernya, tetapi kartu mutu
        sendiri tetap ada di `self.meja` dan wajib tak ikut terhitung.
        """
        n = {kunci: 0 for kunci, _ in GRUP_KEPUTUSAN}
        for b in self.meja:
            if K.golongan_mutu(b.aksi):
                continue
            n[grup_keputusan(b)] += 1
        return n

    @property
    def jumlah_keputusan(self) -> int:
        """Lencana "Menunggu keputusan" — TANPA golongan mutu.

        Mutu pindah ke layarnya sendiri 24 September 2026 (permintaan pemilik).
        Kalau angka ini tetap menghitung keenamnya, pintunya menjanjikan 8
        sementara layarnya menggambar 6 — dan lencana yang tak pernah bisa
        dinolkan mengajari orang mengabaikan lencana.
        """
        return sum(1 for b in self.meja if not K.golongan_mutu(b.aksi))

    @property
    def jumlah_mutu(self) -> int:
        """Lencana "Mutu & QC"."""
        return sum(1 for b in self.meja if K.golongan_mutu(b.aksi))

    @property
    def jumlah_berjalan(self) -> int:
        """Isi layar Sedang berjalan — mesin menyala DAN gabah transit."""
        return len(self.berjalan) + len(self.transit)

    def lencana(self) -> dict:
        """Seluruh angka laci sekaligus — dan pintu yang tak boleh ditawarkan.

        Satu benda, bukan empat kata kunci yang disalin ke tiap `render`:
        layar yang lupa salah satunya menampilkan laci yang berbeda dari laci
        di layar sebelahnya, dan yang dibaca orang bukan "layar ini tidak
        menghitung" melainkan "pekerjaannya sudah habis".

        `PINTU_MATI` — pintu yang disembunyikan untuk permintaan ini. Pabrik
        yang mematikan pencatatan mutu tak boleh ditawari pintu yang SELALU
        kosong; halamannya sendiri tetap bisa dibuka lewat alamat, dan di sana
        ia menyebut sebabnya.
        """
        mati = ([] if self.mutu_aktif else ["mutu"])
        # ── "Stok Produk" pindah jadi sub-menu "Stok" (keputusan pemilik 5
        #    Oktober 2026: "buat stock menjadi main menu memiliki sub menu.
        #    yaitu stock PK dan stock produk.") ──
        #
        # Pintu sendirinya DIPENSIUNKAN untuk SEMUA orang, bukan cuma operator
        # selepan seperti sebelumnya — ia sekarang hanya terjangkau lewat
        # sub-menu "Stok" (`submenu()` di bawah) atau langsung lewat
        # alamatnya. Halaman `/stok-produk` sendiri TIDAK berubah; yang
        # berubah cuma pintunya di laci.
        mati.append("stok_produk")
        # "Titipan pelanggan" (barang jasa, 6 Oktober 2026) — pintu sendirinya
        # SELALU padam juga, dengan alasan yang sama persis: terjangkau lewat
        # sub-menu "Stok", tidak berdiri sendiri di laci.
        mati.append("stok_produk_jasa")
        # "Stok PK Jasa" — padanan `stok_produk_jasa` untuk PK, pola yang sama.
        mati.append("stok_pk_jasa")
        # "Stok Karung"/"Karung Jasa" (7 Oktober 2026) — pola yang sama lagi:
        # berdiri sendiri di laci hanya menawarkan jalan kedua ke sub-menu
        # "Stok", tak pernah ditawarkan sebagai pintu sendiri.
        mati.append("stok_karung")
        mati.append("stok_karung_jasa")
        # "Penggilingan"/"Pengeringan"/"Transfer" — sub-menu "Riwayat Proses"
        # (7 Oktober 2026), pola yang SAMA: berdiri sendiri di laci hanya
        # menawarkan jalan kedua ke tempat yang sudah terjangkau lewat
        # dropdown "Riwayat Proses" (kunci `riwayat_sosoh`, lihat `submenu()`
        # di bawah). TANPA kondisi, sama `stok_pk_jasa` — selalu padam untuk
        # SIAPA PUN, sebab tak ada bentuk "pintu ini berdiri sendiri" yang
        # masuk akal begitu dropdown-nya ada.
        mati.append("riwayat_giling")
        mati.append("riwayat_pengeringan")
        mati.append("riwayat_transfer")
        # "List audit" — permintaan pemilik 7 Oktober 2026: jangan tampil di
        # laci, cukup lewat tombol di Pengaturan. Pola sama yang lain di
        # atas: pintunya sendiri padam, halamannya (`/audit`) tak berubah
        # sama sekali — cuma jalan masuknya pindah dari laci ke Pengaturan,
        # sebab halaman ini bukan pekerjaan harian (dibuka sesekali untuk
        # menelusuri jejak, bukan tiap jam seperti antrean).
        mati.append("audit")
        # "Jasa" — permintaan pemilik 7 Oktober 2026: "singkirkan dulu saja.
        # tidak usah ditampilkan dulu sampai saya tau memanfaatkannya untuk
        # apa." BEDA dari yang lain di atas: bukan karena ia terjangkau
        # lewat jalan lain (tak ada dropdown/tombol pengganti) — pintunya
        # cuma dipadamkan sementara, atas permintaan eksplisit, sampai
        # pemilik memutuskan kelak. Halaman `/jasa` sendiri TAK disentuh:
        # masih bisa dibuka lewat alamatnya, dan `Berjalan.untuk_staff()`
        # dkk. yang membacanya tak berubah sama sekali.
        mati.append("jasa")
        # "Kabar" — permintaan pemilik 7 Oktober 2026, sama pola dengan
        # "Jasa" barusan: disembunyikan sementara, tanpa jalan pengganti.
        # Lencananya (`jumlah_kabar`/`kabar_merah`) TETAP dihitung — kelak
        # kalau pintunya dibuka lagi, lencananya tak perlu dikabel ulang.
        mati.append("kabar")
        # Operator selepan tak ditawari pintu Stok Produk SAMA SEKALI —
        # termasuk lewat sub-menu "Stok" (lihat `submenu()`): beras dan hasil
        # samping lahir di Gudang 2, dan produknya sendiri (PK) sudah berkartu
        # di layar Stok. Pintu yang selalu kosong mengajari orang berhenti
        # membuka pintu. Batas ini SEMENTARA dan pemilik yang memutuskan
        # kelak: "Stok Produk" yang tak memuat PK akan terasa setengah, sebab
        # PK adalah produk Gudang 1 (catatan QA 26 September 2026).
        if not self.pintu_produk:
            # Barang Keluar ikut padam untuk operator selepan, dan sebabnya
            # SAMA: barang jadi berdiri di Gudang 2, dan perintah muatnya
            # dibuat Admin. Pintu yang selalu kosong mengajari orang berhenti
            # membuka pintu. Satu syarat untuk keduanya — dua syarat terpisah
            # untuk alasan yang sama akan berbeda jawabannya pada perubahan
            # berikutnya.
            mati.append("barang_keluar")
        return {"MENUNGGU": self.jumlah_menunggu, "BERJALAN": self.jumlah_berjalan,
                "KEPUTUSAN": self.jumlah_keputusan, "MUTU": self.jumlah_mutu,
                "PRODUK": self.jumlah_produk, "KABAR": self.jumlah_kabar,
                "KABAR_MERAH": self.kabar_merah,
                "MUTU_AKTIF": self.mutu_aktif, "PINTU_MATI": tuple(mati),
                "SUBMENU": self.submenu()}

    def submenu(self) -> dict[str, list[tuple[str, str, int]]]:
        """Sub-menu laci per pintu: {kunci: [(alamat, nama, jumlah)]}.

        Keputusan pemilik 2 Oktober 2026: *"bisa tidak antrian tunggu jika di
        klik muncul dropdown sub menu?"* — ya, dan isinya grup antrean. Dan
        5 Oktober 2026: *"ringkas menu. buat stock menjadi main menu
        memiliki sub menu."* — pintu "Stok" dan "Menunggu keputusan"
        menyusul dengan mekanisme yang sama, dua bentuk berbeda: yang
        pertama dan kedua MEMFILTER satu halaman (`?grup=`/`?kategori=`),
        yang ketiga (Stok) menggabungkan DUA HALAMAN berbeda yang sudah
        lengkap sendiri-sendiri.

        Disusun DI SINI, bersama lencana yang lain, dan sebabnya sudah tertulis
        di `lencana()`: seluruh laci lahir dari satu benda. Sub-menu yang
        disusun di layar masing-masing akan hilang di layar yang lupa
        menyusunnya, dan laci yang berbeda antar-layar dibaca sebagai
        "pekerjaannya sudah habis", bukan sebagai "layar ini tidak menghitung".

        Grup KOSONG tidak ditawarkan — kecuali tak ada satu pun yang berisi,
        dan di situ sub-menunya memang tak ada sama sekali: pintu yang terbuka
        jadi daftar berisi empat nol lebih buruk daripada pintu biasa.
        """
        n = self.jumlah_grup()
        isi = [(f"/aksi?grup={k}", nama, n[k]) for k, nama in GRUP_ANTREAN if n[k]]
        # ⚠ BUTUH DUA GRUP BERISI, bukan satu. Dengan satu grup, membuka pintu
        # antrean cuma menawarkan "Semua" dan satu nama yang isinya sama persis
        # — dropdown yang tak punya pilihan, dan ia MERAMPAS satu ketukan dari
        # orang yang tinggal ingin membuka halamannya. Di hari yang seluruh
        # antreannya satu macam, pintunya kembali jadi pintu biasa.
        #
        # Syarat yang sama dipakai pil di dalam halaman (`GRUP_PIL|length > 1`),
        # dan itu disengaja: laci yang berdropdown sementara halamannya tak
        # berpil akan terbaca seperti saringan yang hilang.
        out: dict[str, list[tuple[str, str, int]]] = {}
        if len(isi) >= 2:
            # Sub-menu hanya menawarkan kategori pekerjaan. "Lainnya" sudah
            # menjadi pelengkap yang menampung setiap kartu yang tidak cocok
            # dengan kategori lain (`grup_baris()`), jadi jangan menambahkan
            # pilihan "Semua" yang mengulang seluruh antrean.
            out["aksi"] = isi

        # "Menunggu keputusan" — permintaan pemilik 2 Oktober 2026: "lakukan
        # yang sama ke menunggu keputusan", diperjelas "buat sub menu juga
        # sesuai kategori". Syarat dan bentuknya SAMA PERSIS dengan Antrian
        # tunggu di atas; sumber datanya beda (`meja`, kategori
        # `keputusan.py` — per JENIS, bukan golongan) dan alamatnya
        # `?kategori=`, bukan `?grup=`.
        nk = self.jumlah_grup_keputusan()
        isik = [(f"/keputusan?kategori={k}", nama, nk[k])
               for k, nama in GRUP_KEPUTUSAN if nk[k]]
        if len(isik) >= 2:
            out["keputusan"] = [("/keputusan", "Semua", self.jumlah_keputusan),
                                *isik]

        # "Stok" — permintaan pemilik 5 Oktober 2026: "ringkas menu. buat
        # stock menjadi main menu memiliki sub menu. yaitu stock PK dan
        # stock produk." BEDA bentuknya dari dua sub-menu di atas: dua
        # tujuannya BUKAN filter atas satu halaman yang sama, melainkan DUA
        # HALAMAN yang masing-masing sudah lengkap sendiri — jadi tak ada
        # baris "Semua" di sini, sebab tak ada daftar utuh yang lebih besar
        # dari keduanya untuk dituju.
        #
        # Angka di tiap baris sengaja 0 — TERMASUK "Stok Produk" (permintaan
        # pemilik 7 Oktober 2026: "tidak perlu ada angkanya"). Sampai hari
        # itu "Stok Produk" sendirian memakai `jumlah_produk` (beras yang
        # belum dipacking) sebagai lencananya; sekarang pintu "Stok" tak
        # pernah punya lencana sama sekali, konsisten di keempat tujuannya.
        # `{% if sub_jml %}` di templat membuang badge "0" itu, bukan
        # menggambarnya sebagai kebisingan. `jumlah_produk` sendiri TETAP
        # dihitung (`b.jumlah_produk`) — cuma tak lagi disebut di sini;
        # layar `/stok-produk` sendiri yang menyebutnya di dalam halaman.
        isi_stok: list[tuple[str, str, int]] = [
            ("/stok", "Stok PK", 0),
            # "Stok PK Jasa" — padanan "Produk Jasa" tapi untuk BAHAN,
            # permintaan pemilik 6 Oktober 2026. TIDAK digerbangi
            # `pintu_produk`: PK jasa berdiri di Gudang 1 MAUPUN Gudang 2
            # (tak seperti Stok Produk, yang G2-saja), jadi operator selepan
            # yang sudah melihat PK titipan di "Stok PK" tetap berhak
            # melihatnya di sini juga.
            ("/stok-pk-jasa", "Stok PK Jasa", 0),
        ]
        if self.pintu_produk:
            isi_stok.append(("/stok-produk", "Stok Produk", 0))
            # "Produk Jasa" — ketiga, keputusan pemilik 6 Oktober 2026 (nama
            # "Titipan pelanggan" semula, diganti atas permintaan pemilik).
            # Angkanya 0 dengan alasan yang sama dengan "Stok PK": halaman
            # murni informasi, tak menagih pekerjaan apa pun.
            isi_stok.append(("/stok-produk-jasa", "Produk Jasa", 0))
            # "Stok Karung"/"Karung Jasa" — keputusan pemilik 7 Oktober 2026.
            # Gerbang SAMA dengan Stok Produk (`pintu_produk`): karung
            # dipakai mengemas beras jadi, pekerjaan Gudang 2 — peran yang
            # sama yang melihat Stok Produk berhak melihat karungnya.
            isi_stok.append(("/stok-karung", "Stok Karung", 0))
            isi_stok.append(("/stok-karung-jasa", "Karung Jasa", 0))
        if len(isi_stok) >= 2:
            out["stok"] = isi_stok

        # "Riwayat Proses" — permintaan pemilik 7 Oktober 2026: satu menu,
        # sub-menu "Penyosohan"/"Penggilingan"/"Pengeringan"/"Transfer".
        # Pola SAMA dengan "Stok" di atas (empat HALAMAN utuh, bukan filter
        # satu halaman) — TANPA baris "Semua", sebab tak ada daftar gabungan
        # yang lebih besar dari keempatnya untuk dituju.
        #
        # Urutannya URUTAN ALUR PRODUKSI (permintaan pemilik 7 Oktober 2026,
        # koreksi susulan): Pengeringan (gabah basah→kering) → Penggilingan
        # (kering→PK) → Penyosohan (PK→beras) → Transfer (PK Gudang 1→Gudang
        # 2, perpindahannya sendiri) — BUKAN urutan "G2 dulu baru G1" yang
        # kebetulan lebih mudah ditulis kodenya.
        #
        # Isinya dibagi per PEMILIK GUDANG, bukan ditawarkan utuh ke semua
        # orang: Penyosohan menjawab pertanyaan Gudang 2, ketiga sisanya
        # menjawab pertanyaan Gudang 1, dan operator tak terikat satu gudang
        # tetap hanya melihat gudang yang SEDANG ia kerjakan (sama seperti
        # `pintu_produk`). Admin/Superadmin (kedua bendera `True`) melihat
        # keempatnya — mereka memegang kedua gudang. Karena urutannya kini
        # menyelang-nyeling G1/G2 (bukan satu blok per gudang berturut-turut
        # seperti sebelumnya), tiap baris diperiksa gerbangnya satu-satu —
        # bukan dua blok `if` seperti "Stok" di atas.
        #
        # Operator yang cuma berhak atas SATU pilihan (lazimnya operator
        # Gudang 2, hanya "Penyosohan") berhenti di `len < 2`: dropdown-nya
        # tak terbentuk, dan kunci `riwayat_sosoh` — yang SEKALIGUS kunci
        # TAB induk — kembali jadi tautan biasa ke `/riwayat-sosoh`, persis
        # perilakunya sebelum sub-menu ini ada.
        isi_riwayat: list[tuple[str, str, int]] = []
        if self.boleh_riwayat_g1:
            isi_riwayat.append(("/riwayat-pengeringan", "Pengeringan", 0))
            isi_riwayat.append(("/riwayat-giling", "Penggilingan", 0))
        if self.boleh_riwayat_sosoh:
            isi_riwayat.append(("/riwayat-sosoh", "Penyosohan", 0))
        if self.boleh_riwayat_g1:
            isi_riwayat.append(("/riwayat-transfer", "Transfer", 0))
        if len(isi_riwayat) >= 2:
            # Kunci `riwayat_sosoh`, BUKAN `riwayat_proses` — tak ada kunci
            # TAB bernama itu; "Riwayat Proses" cuma LABEL laci pintu
            # `riwayat_sosoh`, sama seperti "Stok" cuma label pintu `stok`.
            out["riwayat_sosoh"] = isi_riwayat

        isi_qc: list[tuple[str, str, int]] = []
        if self.boleh_riwayat_g1:
            isi_qc.extend([
                ("/riwayat-qc/gabah-basah", "Gabah basah", 0),
                ("/riwayat-qc/gabah-kering", "Gabah kering", 0),
                ("/riwayat-qc/pk-hasil-giling", "PK Hasil Giling", 0),
            ])
        if self.boleh_riwayat_sosoh:
            isi_qc.extend([
                ("/riwayat-qc/pk-luar", "PK Luar", 0),
                ("/riwayat-qc/beras-hasil-sosoh", "Beras Hasil Sosoh", 0),
            ])
        if len(isi_qc) >= 2:
            out["riwayat_qc"] = isi_qc
        return out


# ═════════════════ GRUP ANTREAN — sub-menu "Antrian tunggu" ═════════════════
#
# Keputusan pemilik 2 Oktober 2026: *"antrian tunggu bisa banyak sekali"*, dan
# obatnya *"jika di klik muncul dropdown sub menu"* — *"sub menu pertama bahan
# baku, kedua tunggu packing, tunggu dipindah."*
#
# ⚠ DIKUNCI PADA `aksi`, BUKAN PADA `kelompok`. `kelompok` sudah dipakai untuk
# hal lain (tiga blok di dalam halaman: menumpuk di lantai, tiket belum
# dicatat, sisanya) dan ia RANCU untuk keperluan ini: `kelompok="tumpukan"`
# berarti "gabah menunggu giliran giling" di Gudang 1 — bahan baku — dan "PK
# menunggu dipindah ke silo" di Gudang 2. Satu nilai, dua grup yang berbeda.
#
# `aksi` tidak rancu, sebab ia memang menyebut APA YANG DITUNGGU kartu itu —
# dan itu pertanyaan yang sama dengan "grup mana". Kartu tanpa `aksi` (kartu
# DIAM, yang dicatat orang lain) jatuh ke `kelompok` sebagai kaki kedua.
#
# ⚠ GRUP TERAKHIR ADALAH KOMPLEMEN, bukan daftar. Apa pun yang tak terpetakan
# jatuh ke sana — termasuk kartu jenis baru yang lahir besok. Itu disengaja dan
# penting: daftar yang harus lengkap adalah daftar yang suatu hari tidak, dan
# kartu yang tak masuk grup mana pun akan HILANG dari layar yang justru
# menagihnya. Pelajaran 1 Oktober 2026 — menyaring tanpa menyebutkan sama
# buruknya dengan menjumlahkan.

#: Urutannya URUTAN BACA, dan ia mengikuti aliran barang: yang baru datang,
#: yang menunggu diangkut, yang menunggu dikemas, lalu sisanya.
GRUP_ANTREAN = (
    ("bahan", "Tiket Timbang"),
    ("pindah", "Tunggu dipindah"),
    ("packing", "Packing"),
    # Keluhan pemilik 6 Oktober 2026: "di halaman tunggu packing tidak bisa
    # dibedakan mana jasa mana yang tidak" — kartu beras titipan pelanggan
    # dan kartu beras pabrik sama-sama `aksi="catat_packing"`, jadi tanpa
    # grup sendiri keduanya bercampur di "Tunggu packing" tanpa tanda apa
    # pun. Lihat `jasa_id` di `Baris` dan cabang khusus di `grup_baris()`.
    ("packing_jasa", "Packing jasa"),
    # Bukan nama yang bagus, dan sengaja tidak disamarkan: di sini berdiri
    # perintah muat barang keluar dan pekerjaan lain yang belum punya grup.
    # Nama yang terlalu
    # percaya diri ("Administrasi") akan membuat orang berhenti mencari di
    # sini, dan isinya justru hal yang tak boleh tertinggal.
    ("lain", "Lainnya"),
)

#: `aksi` → grup. Inilah daftar yang dibaca lebih dulu.
_GRUP_AKSI = {
    # ── Bahan baku: barang yang baru datang, atau menunggu diproses ──
    "gabah_masuk": "bahan",          # tiket timbang gabah belum dicatat
    "catat_pk_luar": "bahan",        # tiket timbang PK luar belum dicatat
    "pindah_tumpukan": "bahan",      # batch gabah → dryer / silo / lantai
    "masukkan_pk": "bahan",          # PK menunggu ditempatkan di Gudang 2
    "mulai_penyosohan": "bahan",     # silo Gudang 2 berisi, siap disosoh
    "mulai_pengeringan": "bahan",
    "mulai_giling": "bahan",
    # ── Tunggu dipindah ──
    "pindah_tumpukan_silo": "pindah",   # PK tumpukan Gudang 2 → silo
    "pindah_silo": "pindah",            # lot dingin → silo (hari ini di transit)
    "acc_permintaan_pk": "pindah",
    "kirim_permintaan_pk": "pindah",    # sudah disetujui, tinggal dimuat
    "tutup_permintaan_pk": "pindah",
    # ── Tunggu packing ──
    "catat_packing": "packing",
}

#: Kaki kedua: `kelompok`, untuk kartu DIAM yang tak punya `aksi` sama sekali
#: (dicatat Admin, bukan oleh yang melihatnya).
_GRUP_KELOMPOK = {
    "tiket": "bahan",
    "produk": "packing",
    "permintaan": "pindah",
}


def grup_baris(b: Baris) -> str:
    """Grup sub-menu sebuah kartu antrean. SATU tempat yang memutuskan.

    Dipakai penyaring halaman MAUPUN penghitung angka sub-menunya. Dua tempat
    yang memutuskan sendiri akan menyebut 3 pada sub-menu yang begitu dibuka
    memperlihatkan 2 — dan sesudah sekali itu, angkanya tak dipercaya lagi.
    """
    # ⚠ DIPERIKSA SEBELUM `_GRUP_AKSI`: kartu beras titipan pelanggan memakai
    # `aksi="catat_packing"` yang SAMA dengan kartu pabrik (sheet yang
    # dibukanya memang sama) — yang membedakan grupnya bukan `aksi`,
    # melainkan `jasa_id`, sumbu yang sebelumnya tak pernah dibaca
    # `grup_baris()`. Tanpa cabang ini "Packing jasa" di `GRUP_ANTREAN` tak
    # akan pernah kemasukan satu kartu pun.
    if b.aksi == "catat_packing" and b.jasa_id is not None:
        return "packing_jasa"
    if b.aksi and b.aksi in _GRUP_AKSI:
        return _GRUP_AKSI[b.aksi]
    # ⚠ `kelompok="tumpukan"` TIDAK dipetakan di sini, dan itu bukan kelalaian:
    # di Gudang 1 ia gabah yang menunggu giliran (bahan baku), di Gudang 2 ia PK
    # yang menunggu dipindah ke silo. Keduanya sudah terjawab lewat `aksi` di
    # atas — `pindah_tumpukan` vs `pindah_tumpukan_silo` — dan memetakannya di
    # sini lagi akan menjawab salah satunya dengan salah.
    if b.kelompok and b.kelompok in _GRUP_KELOMPOK:
        return _GRUP_KELOMPOK[b.kelompok]
    return "lain"


# ═════════════ GRUP KEPUTUSAN — sub-menu "Menunggu keputusan" ═════════════
#
# Permintaan pemilik 2 Oktober 2026: "lakukan yang sama ke menunggu
# keputusan" — lalu diperjelas: "maksud saya buat sub menu juga sesuai
# kategori". Bukan golongan kasar ("Permintaan PK" menggabung dua jenis) —
# PER KATEGORI, satu-satu, persis blok yang sudah tampil di halaman
# `/keputusan` sendiri.
#
# ⚠ KARENA ITU DITURUNKAN DARI `keputusan.blok(mutu=False)`, BUKAN
# `keputusan.GOLONGAN`. Keduanya sumber yang sah dan sama-sama berasal dari
# `K.JENIS`, tetapi beda butirannya: `blok()` MEMANG per-kategori (satu
# baris per (aksi, judul) — persis yang dibaca `JENIS_KEPUTUSAN` untuk
# menggambar blok halaman), sedangkan `GOLONGAN` mengelompokkan beberapa
# kategori jadi satu ember ("permintaan" memuat DUA aksi berbeda). Memakai
# `blok()` membuat sub-menu dan halaman menunjuk kategori yang PERSIS SAMA —
# satu sumber, dua pembaca, tak mungkin berselisih namanya.
#
# Nama kategorinya pun TAK ditulis ulang tangan — diambil langsung dari
# `judul` yang sama yang menggambar kepala tiap blok halaman. Peta `_GRUP_AKSI`
# (Antrian tunggu) sempat salah ketik TIGA nama aksi sebelum ketahuan;
# membaca `judul` apa adanya dari sumbernya tak bisa salah ketik.
#
# HANYA kategori NON-MUTU. Mutu punya layarnya sendiri (`/mutu`, keputusan
# pemilik 24 September 2026) — kategori mutu di sini akan menjanjikan
# pekerjaan yang tak pernah digambar di halaman ini.
GRUP_KEPUTUSAN: tuple[tuple[str, str], ...] = K.blok(mutu=False) + (("lain", "Lainnya"),)

#: aksi yang sudah punya kategorinya sendiri — dibaca sekali, bukan digelung
#: per baris. SAMA dengan `layar_keputusan.JENIS_KEPUTUSAN`; keduanya
#: `keputusan.blok(mutu=False)` apa adanya, jadi tak bisa berbeda isi.
_AKSI_KATEGORI_KEPUTUSAN: frozenset[str] = frozenset(a for a, _ in GRUP_KEPUTUSAN[:-1])


def grup_keputusan(b: Baris) -> str:
    """Kategori sub-menu sebuah kartu "Menunggu keputusan" — id AKSI-nya
    sendiri, bukan golongan. Komplemen "lain" sama alasannya dengan
    `grup_baris`: jenis keputusan yang lahir besok (jaring `keputusan.html`)
    tetap kebagian kategori, bukan hilang."""
    aksi = b.aksi or ""
    return aksi if aksi in _AKSI_KATEGORI_KEPUTUSAN else "lain"


def _lama(sejak: datetime | None) -> str:
    """Sudah berapa lama — dalam kata, bukan cap waktu.

    "2 jam 40 menit" memberi tahu apakah sesuatu tertinggal; "08:12" menuntut
    pembacanya menghitung sendiri sambil berdiri di gudang.
    """
    if sejak is None:
        return ""
    detik = (now_local() - sejak).total_seconds()
    if detik < 0:
        return ""
    jam, menit = int(detik // 3600), int((detik % 3600) // 60)
    if jam >= 24:
        hari = jam // 24
        return f"{hari} hari {jam % 24} jam"
    if jam:
        return f"{jam} jam {menit} menit"
    return f"{menit} menit"


def _sumber_bobot(t) -> str:
    """Dari mana angka bobotnya datang — berikut sebabnya bila nota KALAH.

    Sejak aturan bobot 25 September 2026, kata "timbangan" bisa berarti dua
    hal yang sangat berbeda: tiket ini memang tak bernota, atau ADA notanya
    tetapi barangnya kurang melewati batas. Yang kedua adalah kabar yang
    seseorang perlu tindak lanjuti ke pemasok — dan tanpa menyebutkannya,
    selisih 300 kg cuma jadi angka yang tak seorang pun tahu asalnya.
    """
    sumber = str(t.get("sumber_berat") or "-")
    sebab = t.get("sebab_bobot") or ""
    return f"{sumber} · {sebab}" if sebab else sumber


def _kg(n) -> str:
    return f"{float(n or 0):,.0f} kg".replace(",", ".")


def _kg_tepat(n) -> str:
    """Seperti `_kg`, tetapi TAK PERNAH MEMBULATKAN KE ATAS.

    Dipakai angka yang akan DIKETIK ULANG orang sebagai batas — sisa tumpukan
    yang hendak dipindah ke silo. `_kg` membulatkan setengah ke atas, jadi
    2.999,6 kg terbaca "3.000 kg"; operator mengetik 3.000, dan pagarnya
    menolak angka yang barusan ditawarkan layar kepadanya. Laporan operator
    30 September 2026, dan siasat yang mereka temukan adalah menyisakan 1 kg
    di tiap tumpukan.

    Desimalnya muncul HANYA bila ada. "3.000,0 kg" pada angka yang memang
    bulat cuma membuat tiap kartu terbaca seperti hasil pengukuran yang
    meragukan, dan yang membaca berhenti mempercayai desimal di mana pun.
    """
    v = float(n or 0)
    if abs(v - round(v)) < 0.05:
        return f"{round(v):,.0f} kg".replace(",", ".")
    return f"{v:,.1f} kg".replace(",", "X").replace(".", ",").replace("X", ".")


def _utama(bb: Bobot) -> tuple[str, str] | None:
    """Angka besar kartu dari sebuah Bobot — None bila belum ada angkanya.
    Tak pernah "0": angka nol untuk bobot yang belum diketahui itulah yang
    membuat semua orang mengira datanya salah (QA P6)."""
    t = bb.angka_teks()
    return (t, "kg") if t is not None else None


def lama_kata(detik: float) -> str:
    """Rentang waktu dalam kata. Nol pun disebut — "baru saja" memberi tahu
    bahwa jamnya memang dihitung, bukan bahwa ia tak diketahui.

    Namanya dinaikkan dari `_jam` (2 Oktober 2026) ketika Riwayat sosoh
    membutuhkannya untuk lama satu proses. Berkas ini sudah memuat DUA
    pemformat yang hampir sama (`_lama` menghitung dari "sejak kapan", yang ini
    dari detik); yang ketiga — di modul lain, untuk kalimat yang sama —
    akan berbeda kata-katanya begitu salah satu disentuh."""
    detik = int(detik or 0)
    if detik < 60:
        return "baru saja"
    jam, menit = detik // 3600, (detik % 3600) // 60
    if jam >= 24:
        return f"{jam // 24} hari {jam % 24} jam"
    if jam:
        return f"{jam} jam {menit} menit"
    return f"{menit} menit"


def _tgl(d) -> str:
    return d.strftime("%d/%m") if d else "—"


async def _asal(db: AsyncSession, batch_ids) -> list[tuple[str, str, str]]:
    """Asal-usul barang: siapa pemasoknya, berapa, dan kapan masuk.

    Wajib ada di TIAP kartu, atas keputusan pemilik. Kode batch saja tak
    memberi tahu apa pun tentang gabah siapa yang sedang di dalam mesin —
    dan begitu ada keluhan mutu, pemasok dan tanggal masuk itulah dua hal
    pertama yang dicari. Menuntut orang membuka laporan untuk mengetahuinya
    berarti pertanyaan itu tak pernah benar-benar terjawab di lapangan.
    """
    if not batch_ids:
        return []
    baris = (await db.execute(
        select(PurchaseBatch.kode_batch, PurchaseBatch.berat_total_kg,
               PurchaseBatch.tanggal_pembelian, Supplier.nama_supplier,
               PurchaseBatch.sumber_berat, PurchaseBatch.berat_perkiraan_kg,
               PurchaseBatch.jasa_id)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id, isouter=True)
        .where(PurchaseBatch.id.in_(list(batch_ids)))
        .order_by(PurchaseBatch.id)
    )).all()
    # ⚠ Satu tempat yang memberi nama ke SEPULUH kartu. `isouter` sudah ada, jadi
    # barisnya tak pernah hilang — tetapi tanpa kaki kedua ini ia mencetak "?"
    # untuk setiap batch jasa, dan "?" di baris yang justru menjawab "gabah
    # siapa" membuat kartunya tak bisa dikerjakan. Satu perbaikan di sini
    # menutup kesepuluh kartu sekaligus; membetulkannya per kartu berarti
    # sembilan kesempatan melewatkan satu.
    peta = await nama_pemilik_banyak(db, {b[6] for b in baris})
    return [(f"{nama or peta.get(jasa_id) or '?'} · {kode}",
             dari_nilai(kg, sumber, perk).teks(), f"masuk {_tgl(tgl)}")
            for kode, kg, tgl, nama, sumber, perk, jasa_id in baris]


#: Sebanyak-banyaknya baris asal yang ditampilkan satu kartu. Sesudah daftarnya
#: dibatasi pada isian berjalan (23 Sep 2026) batas ini jarang menggigit —
#: tetapi bila menggigit, jumlah yang tak tampil DISEBUT, bukan didiamkan.
BATAS_ASAL = 6

#: Toleransi saldo silo dianggap nol. Berat disimpan Numeric(12,2), jadi satu
#: perseratus kg sudah lebih halus daripada yang bisa ditimbang siapa pun; yang
#: dijaga toleransi ini adalah galat penjumlahan float, bukan berat sungguhan.
_EPS_KG = 0.01


@dataclass(frozen=True)
class IsianSilo:
    """Isian silo yang SEDANG BERJALAN — bukan seluruh riwayatnya.

    `baris` = asal PK yang masuk SESUDAH terakhir kali silo ini mencapai nol.
    `masuk_kg` dan `disosoh_kg` menerangkan selisih di dalam isian itu, supaya
    judul kartu (isi sekarang) tak terbaca sebagai rincian yang tak menjumlah.
    `lebih` = berapa baris yang tak ditampilkan karena `BATAS_ASAL`.
    """

    baris: list[tuple[str, str, str]] = field(default_factory=list)
    lebih: int = 0
    masuk_kg: float = 0.0
    disosoh_kg: float = 0.0


async def _isian_silo(
    db: AsyncSession, silo_id: int, *, sampai: datetime | None = None,
) -> IsianSilo:
    """Asal-usul PK dalam isian silo Gudang 2 pada waktu yang diminta.

    Aturan pemilik berlaku sama di sini: tiap kartu menyebut asal barangnya.
    Bedanya PK punya dua asal. Yang buatan sendiri lahir dari satu lot giling
    (LOT-…), dan lot itulah satu-satunya benang yang menyambungkan beras putih
    di ujung sana kembali ke gabah dan pemasoknya. Yang beli luar membawa
    pemasoknya sendiri (PKB-…).

    Yang disebut adalah apa yang masuk pada isian yang berjalan pada waktu
    `sampai` (atau sekarang bila tidak diisi) — pemasukan sesudah terakhir
    kali silo ini mencapai nol — berapa dan kapan, bukan berapa yang masih
    tersisa dari masing-masing. Stok silo disimpan
    sebagai satu jumlah, bukan lapisan, jadi sisa per lot memang tak bisa
    dihitung; mengarangnya berarti menaruh angka yang tak bisa dipertanggung-
    jawabkan tepat di tempat orang mencari pertanggungjawaban.

    BATAS WAKTUNYA lahir 23 September 2026 dari galat yang dilaporkan pemilik
    21:33 dan diukur QA (`QA/alat/p17/v_riwayat_silo.py`). Sebelumnya fungsi ini
    tak punya batas sama sekali: ia menyebut SEGALA yang pernah masuk sejak
    kapan pun. Di dalam satu isian itu cuma keterangan yang kurang jelas —
    judul lebih kecil dari jumlah daftar karena sebagian sudah masuk mesin.
    Tetapi SESUDAH silo kosong, lot lama bukan "sebagian terpakai" lagi: ia
    habis. Menyebutnya sebagai asal isi silo sekarang adalah keterangan yang
    SALAH. Dan ia menumpuk tiap putaran, sampai `BATAS_ASAL` memilih enam baris
    sekadar karena urutan, bukan karena artinya.

    Garis waktunya memakai patokan yang SAMA dengan `hitung_stok_silo` —
    pemasukan langsung, pemindahan dari tumpukan, dan penyosohan yang
    `berat_akhir_kg`-nya sudah terisi. Dua hitungan dengan patokan berbeda
    akan berselisih justru pada kartu yang dipakai memutuskan kapan menyosoh.
    Baris yang dibatalkan tak ikut: saringan cermin bertanda menyaringnya di
    tingkat sesi ORM, jadi fungsi ini melihat kenyataan yang sama.
    """
    from app.models import InternalTransfer, PkGudang2Intake
    from app.penggilingan.gudang2.models import (PkPurchaseBatch, PkTumpukanToSilo,
                                                 PolishingProcess, PolishingSiloUsage)

    # ── Garis waktu pergerakan silo: penambah dan pengurang bercampur ──
    #
    # Dua jalan masuk: langsung, atau lewat tumpukan. Yang lewat tumpukan bisa
    # parsial, jadi beratnya diambil dari baris pemindahannya — bukan dari
    # intake asalnya, yang mungkin belum seluruhnya pindah.
    gerak: list[tuple[datetime, float, tuple | None]] = []
    for i in (await db.execute(
        select(PkGudang2Intake)
        .where(PkGudang2Intake.silo_id == silo_id,
               *([PkGudang2Intake.waktu_masuk <= sampai] if sampai else []),
               # `silo_id` sudah menyebut silonya; menyaring lagi dengan
               # kata tujuannya akan membuang baris silo ketiga diam-diam.
               PkGudang2Intake.silo_id.is_not(None))
    )).scalars().all():
        kg = float(i.berat_kg or 0)
        gerak.append((i.waktu_masuk, kg,
                      (i.tanggal_masuk, kg, i.internal_transfer_id, i.pk_purchase_batch_id)))
    for pindah, i in (await db.execute(
        select(PkTumpukanToSilo, PkGudang2Intake)
        .join(PkGudang2Intake, PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id)
        .where(PkTumpukanToSilo.silo_id == silo_id,
               *([PkTumpukanToSilo.waktu <= sampai] if sampai else []))
    )).all():
        kg = float(pindah.berat_kg or 0)
        gerak.append((pindah.waktu, kg,
                      (pindah.tanggal, kg, i.internal_transfer_id, i.pk_purchase_batch_id)))
    # Pengurangnya penyosohan. `PolishingSiloUsage` tak punya cap waktu sendiri,
    # jadi waktunya diambil dari prosesnya: SELESAI-nya, sebab di situlah
    # `berat_akhir_kg` terisi dan di situlah `hitung_stok_silo` mulai
    # menguranginya. Proses yang belum selesai belum mengurangi apa pun.
    for u, pr in (await db.execute(
        select(PolishingSiloUsage, PolishingProcess)
        .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.silo_id == silo_id,
               PolishingSiloUsage.berat_akhir_kg.isnot(None),
               *([PolishingProcess.waktu_selesai <= sampai] if sampai else []))
    )).all():
        gerak.append((pr.waktu_selesai or pr.waktu_mulai,
                      -float(u.berat_terpakai_kg or 0), None))
    if not gerak:
        return IsianSilo()

    # Pengurang lebih dulu bila waktunya sama persis: silo yang dikosongkan lalu
    # diisi ulang pada saat yang sama harus terbaca sebagai TERISI ULANG, bukan
    # sebagai masih memegang isian lama.
    _AWAL = datetime.min.replace(tzinfo=timezone.utc)
    urut = sorted(gerak, key=lambda g: (g[0] or _AWAL, 0 if g[1] < 0 else 1))

    # ── Titik nol terakhir ──
    # Ditelusuri maju sekali jalan, bukan mundur: hasilnya sama, dan saldo
    # berjalan lebih mudah dibaca. Keadaan awal silo memang nol, jadi silo yang
    # belum pernah kosong berakhir dengan `batas = -1` — seluruh riwayatnya
    # terdaftar, dan itu benar.
    saldo, batas = 0.0, -1
    for n, (_, delta, _) in enumerate(urut):
        saldo += delta
        if saldo <= _EPS_KG:
            batas = n

    isian = urut[batas + 1:]
    masuk = [m for _, _, m in isian if m is not None]
    masuk_kg = sum(m[1] for m in masuk)
    disosoh_kg = -sum(d for _, d, _ in isian if d < 0)
    if not masuk:
        return IsianSilo(masuk_kg=masuk_kg, disosoh_kg=disosoh_kg)

    # Pemiliknya ikut diambil: PK titipan yang dipindah dari Gudang 1 tak boleh
    # berjudul "Giling sendiri" di kartu silo. Pabrik memang yang menggilingnya,
    # tetapi barangnya bukan miliknya — dan kartu inilah yang dibaca operator
    # Gudang 2 saat memutuskan silo mana yang disosoh.
    lot = {i: (kode, jid) for i, kode, jid in (await db.execute(
        select(InternalTransfer.id, MillingProcess.kode_proses,
               InternalTransfer.jasa_id)
        .join(MillingProcess, MillingProcess.id == InternalTransfer.milling_process_id)
        .where(InternalTransfer.id.in_([m[2] for m in masuk if m[2]]))
    )).all()} if any(m[2] for m in masuk) else {}
    # PK beli luar TITIPAN (`PkPurchaseBatch.jasa_id` terisi, `supplier_id`
    # NULL — migrasi 0064/0065) tak punya pemasok sama sekali: judulnya
    # harus datang dari pemiliknya, bukan dari `Supplier.nama_supplier`
    # yang memang kosong untuk baris ini. Dibaca BERSAMA `lot` lewat
    # `peta_pemilik` yang sama — tanpanya baris ini jatuh ke `nama or '?'`
    # dan menampilkan "?" (laporan lapangan 12 Oktober 2026).
    luar = {b: (kode, nama, jid) for b, kode, nama, jid in (await db.execute(
        select(PkPurchaseBatch.id, PkPurchaseBatch.kode_batch, Supplier.nama_supplier,
               PkPurchaseBatch.jasa_id)
        .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
        .where(PkPurchaseBatch.id.in_([m[3] for m in masuk if m[3]]))
    )).all()} if any(m[3] for m in masuk) else {}
    peta_pemilik = await nama_pemilik_banyak(
        db, {j for _, j in lot.values()} | {j for _, _, j in luar.values() if j})

    keluar = []
    for tgl, kg, trf_id, batch_id in sorted(masuk, key=lambda m: (m[0] or date.min), reverse=True):
        if trf_id and trf_id in lot:
            kode_lot, jid = lot[trf_id]
            judul = (f"{peta_pemilik[jid]} · {kode_lot}" if jid in peta_pemilik
                     else f"Giling sendiri · {kode_lot}")
        elif batch_id and batch_id in luar:
            kode, nama, jid = luar[batch_id]
            judul = (f"{peta_pemilik[jid]} · {kode}" if jid and jid in peta_pemilik
                     else f"{nama or '?'} · {kode}")
        else:
            continue
        # Tanpa tanggal masuk di sini — kode lot/batch (LOT-YYMMDD,
        # PKB-YYYYMMDD-NN) sudah memuat tanggalnya sendiri; menyebutnya lagi
        # di baris ini cuma mengulang (keputusan pemilik 11 Oktober 2026).
        keluar.append((judul, _kg(kg), ""))
    return IsianSilo(baris=keluar[:BATAS_ASAL], lebih=max(0, len(keluar) - BATAS_ASAL),
                     masuk_kg=masuk_kg, disosoh_kg=disosoh_kg)


async def _asal_pk(db: AsyncSession, silo_id: int) -> list[tuple[str, str, str]]:
    """Baris asal saja, untuk pemakai yang tak butuh ringkasan selisihnya."""
    return (await _isian_silo(db, silo_id)).baris


async def _isian_silo_broken(
    db: AsyncSession, silo_id: int, *, sampai: datetime | None = None,
) -> IsianSilo:
    """Asal-usul broken dalam isian silo BROKEN, sebangun `_isian_silo`.

    Bedanya dari PK: broken cuma punya SATU jalan masuk (`broken_ke_silo`,
    bukan langsung+tumpukan), dan pemiliknya sudah TERSALIN di barisnya
    sendiri (`jasa_id`) — tak perlu join ke tabel lain untuk tahu kodenya,
    beda dari PK yang kodenya (LOT-…/PKB-…) ada di `InternalTransfer`/
    `PkPurchaseBatch` terpisah.

    Dasarnya tetap sama: isian sejak terakhir kali silo ini mencapai nol,
    dibatasi `sampai` (snapshot saat proses mulai) sama seperti PK.
    """
    from app.models import BrokenKeSilo
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage

    gerak: list[tuple[datetime, float, tuple | None]] = []
    for r in (await db.execute(
        select(BrokenKeSilo)
        .where(BrokenKeSilo.silo_id == silo_id,
               *([BrokenKeSilo.waktu <= sampai] if sampai else []))
    )).scalars().all():
        kg = float(r.berat_kg or 0)
        gerak.append((r.waktu, kg, (r.tanggal, kg, r.kode_pindah, r.jasa_id)))
    for u, pr in (await db.execute(
        select(PolishingSiloUsage, PolishingProcess)
        .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
        .where(PolishingSiloUsage.silo_id == silo_id,
               PolishingSiloUsage.berat_akhir_kg.isnot(None),
               *([PolishingProcess.waktu_selesai <= sampai] if sampai else []))
    )).all():
        gerak.append((pr.waktu_selesai or pr.waktu_mulai,
                      -float(u.berat_terpakai_kg or 0), None))
    if not gerak:
        return IsianSilo()

    _AWAL = datetime.min.replace(tzinfo=timezone.utc)
    urut = sorted(gerak, key=lambda g: (g[0] or _AWAL, 0 if g[1] < 0 else 1))
    saldo, batas = 0.0, -1
    for n, (_, delta, _) in enumerate(urut):
        saldo += delta
        if saldo <= _EPS_KG:
            batas = n

    isian = urut[batas + 1:]
    masuk = [m for _, _, m in isian if m is not None]
    masuk_kg = sum(m[1] for m in masuk)
    disosoh_kg = -sum(d for _, d, _ in isian if d < 0)
    if not masuk:
        return IsianSilo(masuk_kg=masuk_kg, disosoh_kg=disosoh_kg)

    peta_pemilik = await nama_pemilik_banyak(db, {m[3] for m in masuk if m[3]})
    keluar = []
    for tgl, kg, kode, jid in sorted(masuk, key=lambda m: (m[0] or date.min), reverse=True):
        judul = (f"{peta_pemilik[jid]} · {kode}" if jid in peta_pemilik
                 else f"Giling sendiri · {kode}")
        # Tanpa tanggal masuk — kode pindah (BKS-YYYYMMDD-NN) sudah
        # memuat tanggalnya sendiri, pola yang sama dengan `_isian_silo`.
        keluar.append((judul, _kg(kg), ""))
    return IsianSilo(baris=keluar[:BATAS_ASAL], lebih=max(0, len(keluar) - BATAS_ASAL),
                     masuk_kg=masuk_kg, disosoh_kg=disosoh_kg)


async def _isian_silo_banyak(
    db: AsyncSession,
    permintaan: list[tuple[int, bool, datetime | None]],
) -> dict[tuple[int, bool, datetime | None], IsianSilo]:
    """`_isian_silo`/`_isian_silo_broken` dalam bentuk BORONGAN.

    Dipakai Riwayat Sosoh (`polishing.riwayat_sosoh`), yang menjaga jumlah
    kuerinya TETAP berapa pun banyak kartu di halaman (P-S-02 — satu kueri
    per baris pernah membuat halaman Stok Produk 1,77 detik pada 500 baris).
    Memanggil `_isian_silo`/`_isian_silo_broken` di dalam gelung per kartu×
    silo akan mengeluarkan kelas kesalahan yang sama persis.

    `permintaan` = daftar (silo_id, broken, sampai) — SATU per kartu×silo,
    `sampai`-nya waktu_mulai proses MASING-MASING (bukan "sekarang"): silo
    yang sama bisa dipakai proses berbeda pada waktu berbeda, jadi "sejak nol
    terakhir"-nya wajib dihitung per permintaan, bukan sekali untuk silonya
    saja. Hasilnya dict berkunci TEPAT elemen `permintaan` — pemanggil
    mencocokkan balik dengan kuncinya sendiri.

    Logikanya sengaja DIDUPLIKASI dari versi satuan, bukan dipanggil
    lewatnya — bentuk kuerinya beda (`IN (...)` borongan vs `==` satuan,
    sekali untuk seluruh permintaan vs sekali per silo), pola yang sama
    dengan `BrokenKeSilo` berdiri sendiri dari `PkTumpukanToSilo`: dua
    kebutuhan yang kebetulan mirip tapi bentuk aksesnya berbeda.
    """
    from app.models import BrokenKeSilo, InternalTransfer, PkGudang2Intake
    from app.penggilingan.gudang2.models import (PkPurchaseBatch, PkTumpukanToSilo,
                                                 PolishingProcess, PolishingSiloUsage)

    if not permintaan:
        return {}

    silo_pk = {s for s, broken, _ in permintaan if not broken}
    silo_broken = {s for s, broken, _ in permintaan if broken}
    silo_semua = silo_pk | silo_broken

    # ── Pengambilan TANPA batas waktu di SQL ──
    # `sampai` beda per permintaan (proses yang berbeda, bahkan untuk silo
    # yang sama), jadi disaring di Python sesudah diambil, bukan di kueri.
    # Yang dijaga tetap di sini jumlah KUERI-nya (enam, berapa pun banyak
    # kartu), bukan jumlah barisnya — dan baris riwayat satu silo selama
    # pabrik berdiri masih jauh dari berat bagi memori satu permintaan HTTP.
    gerak_pk: dict[int, list[tuple]] = {s: [] for s in silo_pk}
    if silo_pk:
        for i in (await db.execute(
            select(PkGudang2Intake)
            .where(PkGudang2Intake.silo_id.in_(silo_pk),
                   PkGudang2Intake.silo_id.is_not(None))
        )).scalars().all():
            kg = float(i.berat_kg or 0)
            gerak_pk[i.silo_id].append((i.waktu_masuk, kg,
                (i.tanggal_masuk, kg, i.internal_transfer_id, i.pk_purchase_batch_id)))
        for pindah, i in (await db.execute(
            select(PkTumpukanToSilo, PkGudang2Intake)
            .join(PkGudang2Intake, PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id)
            .where(PkTumpukanToSilo.silo_id.in_(silo_pk))
        )).all():
            kg = float(pindah.berat_kg or 0)
            gerak_pk[pindah.silo_id].append((pindah.waktu, kg,
                (pindah.tanggal, kg, i.internal_transfer_id, i.pk_purchase_batch_id)))

    gerak_broken: dict[int, list[tuple]] = {s: [] for s in silo_broken}
    if silo_broken:
        for r in (await db.execute(
            select(BrokenKeSilo).where(BrokenKeSilo.silo_id.in_(silo_broken))
        )).scalars().all():
            kg = float(r.berat_kg or 0)
            gerak_broken[r.silo_id].append((r.waktu, kg, (r.tanggal, kg, r.kode_pindah, r.jasa_id)))

    # Pengurang — SATU kueri untuk SELURUH silo (PK maupun broken: tabelnya
    # silo-agnostik, sama seperti di versi satuan).
    if silo_semua:
        for u, pr in (await db.execute(
            select(PolishingSiloUsage, PolishingProcess)
            .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
            .where(PolishingSiloUsage.silo_id.in_(silo_semua),
                   PolishingSiloUsage.berat_akhir_kg.isnot(None))
        )).all():
            kurang = (pr.waktu_selesai or pr.waktu_mulai,
                      -float(u.berat_terpakai_kg or 0), None)
            if u.silo_id in gerak_pk:
                gerak_pk[u.silo_id].append(kurang)
            if u.silo_id in gerak_broken:
                gerak_broken[u.silo_id].append(kurang)

    # ── Per permintaan: saring ke `sampai`-nya sendiri, cari titik nol ──
    # terakhir — bagian MURNI dari `_isian_silo`, diulang di sini sebab
    # dipanggil per permintaan, bukan per silo.
    _AWAL = datetime.min.replace(tzinfo=timezone.utc)

    def _masuk_sejak_nol(gerak_silo, sampai):
        gerak = [g for g in gerak_silo if not sampai or (g[0] or _AWAL) <= sampai]
        if not gerak:
            return [], 0.0, 0.0
        urut = sorted(gerak, key=lambda g: (g[0] or _AWAL, 0 if g[1] < 0 else 1))
        saldo, batas = 0.0, -1
        for n, (_, delta, _) in enumerate(urut):
            saldo += delta
            if saldo <= _EPS_KG:
                batas = n
        isian = urut[batas + 1:]
        masuk = [m for _, _, m in isian if m is not None]
        masuk_kg = sum(m[1] for m in masuk)
        disosoh_kg = -sum(d for _, d, _ in isian if d < 0)
        return masuk, masuk_kg, disosoh_kg

    per_permintaan: dict[tuple, tuple] = {
        key: _masuk_sejak_nol((gerak_broken if key[1] else gerak_pk).get(key[0], []), key[2])
        for key in permintaan
    }

    # ── Label — borongan atas UNION seluruh permintaan sekaligus ──
    trf_ids: set[int] = set()
    batch_ids: set[int] = set()
    broken_jasa_ids: set[int] = set()
    for (s, broken, _), (masuk, _, _) in per_permintaan.items():
        if broken:
            broken_jasa_ids.update(m[3] for m in masuk if m[3])
        else:
            trf_ids.update(m[2] for m in masuk if m[2])
            batch_ids.update(m[3] for m in masuk if m[3])

    lot = {i: (kode, jid) for i, kode, jid in (await db.execute(
        select(InternalTransfer.id, MillingProcess.kode_proses, InternalTransfer.jasa_id)
        .join(MillingProcess, MillingProcess.id == InternalTransfer.milling_process_id)
        .where(InternalTransfer.id.in_(trf_ids))
    )).all()} if trf_ids else {}
    # PK beli luar TITIPAN tak punya pemasok (`supplier_id` NULL,
    # `jasa_id` terisi) — pemiliknya dibaca lewat `peta_pemilik`, sama
    # dengan `_isian_silo`; lihat catatan panjang di sana.
    luar = {b: (kode, nama, jid) for b, kode, nama, jid in (await db.execute(
        select(PkPurchaseBatch.id, PkPurchaseBatch.kode_batch, Supplier.nama_supplier,
               PkPurchaseBatch.jasa_id)
        .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
        .where(PkPurchaseBatch.id.in_(batch_ids))
    )).all()} if batch_ids else {}
    peta_pemilik = await nama_pemilik_banyak(
        db, {j for _, j in lot.values()} | broken_jasa_ids
        | {j for _, _, j in luar.values() if j})

    hasil: dict[tuple, IsianSilo] = {}
    for key, (masuk, masuk_kg, disosoh_kg) in per_permintaan.items():
        _, broken, _ = key
        if not masuk:
            hasil[key] = IsianSilo(masuk_kg=masuk_kg, disosoh_kg=disosoh_kg)
            continue
        keluar = []
        if broken:
            for tgl, kg, kode, jid in sorted(masuk, key=lambda m: (m[0] or date.min), reverse=True):
                judul = (f"{peta_pemilik[jid]} · {kode}" if jid in peta_pemilik
                         else f"Giling sendiri · {kode}")
                keluar.append((judul, _kg(kg), ""))
        else:
            for tgl, kg, trf_id, batch_id in sorted(masuk, key=lambda m: (m[0] or date.min), reverse=True):
                if trf_id and trf_id in lot:
                    kode_lot, jid = lot[trf_id]
                    judul = (f"{peta_pemilik[jid]} · {kode_lot}" if jid in peta_pemilik
                             else f"Giling sendiri · {kode_lot}")
                elif batch_id and batch_id in luar:
                    kode, nama, jid = luar[batch_id]
                    judul = (f"{peta_pemilik[jid]} · {kode}" if jid and jid in peta_pemilik
                             else f"{nama or '?'} · {kode}")
                else:
                    continue
                keluar.append((judul, _kg(kg), ""))
        hasil[key] = IsianSilo(baris=keluar[:BATAS_ASAL], lebih=max(0, len(keluar) - BATAS_ASAL),
                               masuk_kg=masuk_kg, disosoh_kg=disosoh_kg)
    return hasil


def _nota_isian(isian: IsianSilo) -> str | None:
    """Kalimat yang memberi nama pada selisih judul↔daftar, atau None.

    Dua hal yang perlu disebut, dan hanya bila memang ada:
    berapa yang masuk pada isian ini berbanding berapa yang sudah masuk mesin,
    dan berapa baris asal yang tak ditampilkan. Selisih nol tak perlu kalimat —
    kalimat yang selalu muncul berhenti dibaca, dan kartu yang penuh keterangan
    tak bersisa tempat untuk keterangan yang benar-benar menahan pekerjaan.
    """
    bagian = []
    if isian.disosoh_kg > _EPS_KG:
        bagian.append(f"isian ini: {_kg(isian.masuk_kg)} masuk · "
                      f"{_kg(isian.disosoh_kg)} sudah disosoh")
    if isian.lebih:
        bagian.append(f"+{isian.lebih} asal lagi tak ditampilkan")
    return " · ".join(bagian) or None


def _pemasok_ringkas(anak: list[tuple[str, str, str]]) -> str:
    """Nama pemasok untuk baris ringkas — tanpa mengulang yang sama.

    Satu lot bisa berisi gabah dari tiga pemasok; menyebut ketiganya di baris
    sub membuat baris itu lebih panjang daripada kartunya. Dua disebut, sisanya
    dihitung.
    """
    nama = []
    for label, _, _ in anak:
        n = label.split(" · ")[0]
        if n not in nama:
            nama.append(n)
    if not nama:
        return ""
    if len(nama) <= 2:
        return " & ".join(nama)
    return f"{nama[0]}, {nama[1]} +{len(nama) - 2} lagi"


#: Pemilik yang BELUM ADA barisnya: tiket jasa yang akan melahirkan pesanan baru.
#:
#: Pesanan lahir saat operator menerima tiketnya (`purchase.
#: pesanan_jasa_dari_tiket`), jadi saat kartunya digambar pemiliknya belum punya
#: id.
#:
#: ⚠⚠ TAK LAGI DIKONSTRUKSI oleh `_tiket_belum_ditaut` sejak pesan kerja 13
#: (11 Oktober 2026) — fungsi itu kini mengoper `tiket=t` apa adanya ke
#: `_tujuan_gabah`, dan kecocokan pemiliknya dijawab `jasa.
#: cocok_pemilik_tiket` lewat PELANGGAN, bukan tanda ini. Tanda ini dulu
#: membuang satu-satunya fakta yang menentukan jawabannya — pesanan baru itu
#: milik SIAPA — sehingga tombol tempat yang sebenarnya boleh digabung
#: (pelanggan sama, pesanan lain) ikut mati.
#:
#: Konstanta ini TETAP berdiri sebagai contoh kanonik "tanda bukan-int" untuk
#: uji penjaga `cocok_pemilik`'s `isinstance(a, int)` — jangan dihapus hanya
#: karena tak ada lagi pemanggil produksi yang menulisnya: sebuah teks, bukan
#: angka, dan `cocok_pemilik` WAJIB tetap menjawabnya False tanpa meledak
#: seandainya nilai semacam ini muncul lagi dari jalur lain suatu hari.
PEMILIK_BARU = "pesanan-baru"


async def _cocok(db: AsyncSession, jasa_id: int | None, tiket: dict | None,
                 j: int | None) -> bool:
    """`cocok_pemilik`/`cocok_pemilik_tiket`, dipilih menurut yang tersedia.

    `tiket` menang bila ADA — pemanggil yang punya tiket mentah (belum tentu
    berpesanan) tak pernah juga mengoper `jasa_id` sungguhan untuk sisi yang
    sama, lihat pemanggilnya di `_tujuan_gabah`.
    """
    if tiket is not None:
        from app.services.jasa import cocok_pemilik_tiket
        return await cocok_pemilik_tiket(db, t=tiket, jasa_id_lain=j)
    from app.services.jasa import cocok_pemilik
    return await cocok_pemilik(db, jasa_id, j)


async def _sisi_kita(db: AsyncSession, jasa_id: int | None,
                     tiket: dict | None) -> str | None:
    """Sebutan untuk barang yang SEDANG ditempatkan — sisi "ini" di kalimat
    penolakan dua-sisi. `None` berarti pabrik."""
    if tiket is not None:
        from app.penggilingan.gudang1.services.timbang_link import (
            adalah_jasa, nama_pihak)
        return nama_pihak(tiket) if adalah_jasa(tiket) else None
    return await nama_pemilik(db, jasa_id)


async def _mati_pemilik_dryer(db: AsyncSession, dryer_id: int,
                              jasa_id: int | None, *,
                              tiket: dict | None = None) -> str:
    """Kalimat sebab bila mesin ini berisi gabah pemilik LAIN — "" bila boleh.

    ⚠ "pemilik LAIN" dijawab `cocok_pemilik`/`cocok_pemilik_tiket` (sama
    persis ATAU sama pelanggan), BUKAN `!= jasa_id` apa adanya — lihat ⚠⚠ di
    docstring keduanya untuk cacat lapangan yang memotivasi ini.

    `tiket` (dict mentah dari `tiket_masuk_aktif`) dioper oleh pemanggil yang
    BELUM tahu pesanannya sudah lahir atau belum — `_tiket_belum_ditaut`,
    satu-satunya. Pemanggil lain (yang sudah pegang `PurchaseBatch.jasa_id`
    sungguhan) tetap mengoper `jasa_id` apa adanya, `tiket=None`.
    """
    isi = (await db.execute(
        select(PurchaseBatch.jasa_id).where(
            PurchaseBatch.dryer_id == dryer_id,
            PurchaseBatch.status_batch == "di_dryer").distinct()
    )).scalars().all()
    lain = {j for j in isi if not await _cocok(db, jasa_id, tiket, j)}
    if not lain:
        return ""
    peta = await nama_pemilik_banyak(db, lain)
    sebut = ", ".join(peta.get(j) or "gabah pabrik" for j in lain)
    # ⭐ DUA SISI, bukan satu — laporan lapangan 11 Oktober 2026: kalimat yang
    # cuma menyebut isi mesin ("Berisi barang Didik") membuat operator
    # membandingkannya dengan nama di kartunya sendiri ("Didik juga!") dan
    # menyimpulkan aplikasinya rusak. Kadang memang rusak (pesan kerja ini);
    # kadang BUKAN, sebab dua "Didik" bisa dua pelanggan berbeda yang
    # kebetulan senama — dan tanpa menyebut KEDUA sisi, operator tak bisa
    # membedakan dua keadaan itu dari kalimatnya saja.
    sisi_kita = await _sisi_kita(db, jasa_id, tiket)
    return (f"Berisi barang {sebut} — barang ini {sisi_kita or 'pabrik'} — "
            "kepemilikan berbeda tak boleh digabung")


async def _pemilik_silo(db: AsyncSession, silo_id: int,
                        jasa_id: int | None, *,
                        tiket: dict | None = None) -> tuple[str | None, str]:
    """(sebutan pemilik isi silo, sebab tombolnya dimatikan).

    Satu silo tak pernah berisi dua pemilik — penjaganya di `masuk_silo` — jadi
    "pemilik isi silo" selalu tunggal bila silonya berisi.

    ⚠ "pemilik LAIN" dijawab `cocok_pemilik`/`cocok_pemilik_tiket`, BUKAN
    `== {jasa_id}` apa adanya — sebangun `_mati_pemilik_dryer` di atas,
    termasuk alasan parameter `tiket`-nya.
    """
    isi = (await db.execute(
        select(SiloStorage.jasa_id).where(
            SiloStorage.silo_id == silo_id,
            SiloStorage.status == "terisi").distinct()
    )).scalars().all()
    if not isi:
        return None, ""
    pemilik = {j for j in isi}
    sebutan = await nama_pemilik(db, next(iter(pemilik))) if len(pemilik) == 1 else None
    lain = {j for j in pemilik if not await _cocok(db, jasa_id, tiket, j)}
    if not lain:
        return sebutan, ""
    peta = await nama_pemilik_banyak(db, lain)
    sebut = ", ".join(peta.get(j) or "gabah pabrik" for j in lain)
    sisi_kita = await _sisi_kita(db, jasa_id, tiket)  # ⭐ DUA SISI — lihat catatan di atas.
    return sebutan, (f"Berisi barang {sebut} — barang ini {sisi_kita or 'pabrik'} "
                     "— kepemilikan berbeda tak boleh digabung")


async def _tujuan_gabah(db: AsyncSession, kondisi: str, *,
                        post: str, data: dict,
                        jasa_id: int | None = None,
                        tiket: dict | None = None) -> list[Tombol]:
    """Tujuan yang sah untuk gabah sekondisi ini — mesinnya disebut satu per satu.

    Alasan sebuah tujuan dimatikan diambil dari ATURAN YANG SAMA yang menolak
    di server (`masuk_dryer`): mesin tak aktif, mesin masih dipakai lot, dan
    isinya beda kondisi. Kalau alasannya disusun ulang di sini, cepat atau
    lambat layar melarang yang sebenarnya boleh — atau lebih buruk,
    mempersilakan yang akan ditolak.

    `jasa_id` = pemilik gabah yang sedang ditempatkan, DIPAKAI bila
    pemanggilnya sudah pegang baris `PurchaseBatch`/dkk sungguhan. `tiket`
    (dict mentah tiket timbang) dipakai sebagai gantinya oleh pemanggil yang
    BELUM tahu pesanannya sudah lahir atau belum — lihat ⚠⚠ di
    `jasa.cocok_pemilik_tiket` untuk cacat lapangan 11 Oktober 2026 yang
    melahirkan jalur ini: memaksa pemanggil itu menebak `jasa_id` dulu
    (sentinel, atau `None` dari tes `pelanggan_id` yang salah) adalah
    SUMBER cacatnya, bukan sekadar gejalanya.

    Tempat yang berisi barang pemilik LAIN dimatikan berikut sebabnya,
    aturan yang sama dengan penjaga basah/kering di atasnya — dan untuk
    alasan yang sama: tombol yang pasti ditolak lebih buruk daripada tombol
    yang tak ada, sebab yang menekannya sudah berdiri di depan mesin dengan
    gabah di tangan.

    Kapasitas sengaja TIDAK diperiksa di sini: ia bergantung pada total muatan
    dan pesan penolakannya sudah menyebut sisanya dengan tepat. Menebaknya di
    layar hanya menambah tempat yang bisa salah.
    """
    from app.penggilingan.gudang1.services.drying import (
        active_drying_lot, dryers_g1, isi_dryer)
    from app.penggilingan.peta_jenis import intake_dari_jenis

    if tiket is not None:
        from app.penggilingan.gudang1.services.timbang_link import adalah_jasa
        ini_jasa = adalah_jasa(tiket)
    else:
        ini_jasa = jasa_id is not None

    jenis = "GABAH_BASAH" if kondisi == "basah" else "GABAH_KERING"
    info = intake_dari_jenis(jenis)
    sah = info.tujuan_pilihan if info else ()
    # Gabah basah JASA kehilangan pilihan "tumpuk" — basah yang menunggu akan
    # rusak, dan ini barang orang lain. Aturannya dibaca dari SATU tempat yang
    # juga dipakai penjaganya (`tumpukan.tujuan_sah`): daftar pilihan yang
    # disusun terpisah dari aturan penolakannya cepat atau lambat menawarkan
    # yang akan ditolak.
    #
    # ⚠ `ini_jasa`, BUKAN `jasa_id is not None` apa adanya — cacat lapangan
    # 11 Oktober 2026: tiket jasa bernama bebas dulu terbaca `jasa_id=None`
    # (tes `pelanggan_id` yang salah, lihat `cocok_pemilik_tiket`), jadi
    # pilihan "tumpuk" ikut DITAWARKAN untuk gabah basah titipan pelanggan —
    # padahal aturan pemilik eksplisit melarangnya.
    if ini_jasa and kondisi == "basah":
        from app.penggilingan.gudang1.services.tumpukan import tujuan_sah
        sah = tuple(t for t in sah if t in tujuan_sah(kondisi, 1))
    keluar: list[Tombol] = []

    if "dryer" in sah:
        for d in await dryers_g1(db):
            isi = await isi_dryer(db, d.id)
            lot = await active_drying_lot(db, d.id)
            mati = ""
            if d.status != "aktif":
                mati = f"Mesin sedang {d.status}"
            elif lot is not None:
                mati = f"Masih dipakai lot {lot.kode_lot} — kosongkan ke silo dulu"
            elif isi and isi[0] != kondisi:
                mati = f"Berisi gabah {isi[0]} — tak boleh dicampur gabah {kondisi}"
            else:
                mati = await _mati_pemilik_dryer(db, d.id, jasa_id, tiket=tiket) or mati
            ket = ("Mesin kosong" if not isi
                   else f"Bergabung dengan {_kg(isi[1])} gabah {isi[0]}")
            keluar.append(Tombol(
                nama=f"Ke {d.nama}", ket=ket, post=post,
                data=dict(data, tujuan=f"dryer:{d.id}"),
                utama=(kondisi == "basah" and not mati), mati=mati))

    if "silo" in sah:
        from app.penggilingan.gudang1.services.silo import _silo_content_kg, silos_g1
        silo = await silos_g1(db)
        # Disorot HANYA bila memang cuma ada satu. Dua tombol tersorot
        # sekaligus bukan rekomendasi melainkan hiasan — dan sorotan yang
        # muncul di mana-mana berhenti menandakan apa pun. Kalau silonya lebih
        # dari satu, memang operator yang memutuskan; layar tak tahu mana yang
        # lebih baik, dan berpura-pura tahu lebih buruk daripada diam.
        for si in silo:
            kg = await _silo_content_kg(db, si.id)
            pemilik_silo, mati_silo = await _pemilik_silo(db, si.id, jasa_id, tiket=tiket)
            keluar.append(Tombol(
                nama=f"Ke {si.nama_silo}", post=post,
                ket=("Silo kosong" if not kg
                     else f"Bergabung dengan {_kg(kg)} gabah kering"
                          + (f" milik {pemilik_silo}" if pemilik_silo else "")),
                mati=mati_silo,
                data=dict(data, tujuan=f"silo:{si.id}"),
                utama=(kondisi == "kering" and len(silo) == 1)))

    if "tumpuk" in sah:
        keluar.append(Tombol(
            nama="Ditumpuk di lantai", ket="Tempatnya ditentukan menyusul",
            post=post, data=dict(data, tujuan="tumpuk")))
    return keluar


async def _tiket_belum_ditaut(db: AsyncSession) -> list[Baris]:
    from app.penggilingan.gudang1.services.timbang_link import (
        adalah_jasa, nama_pihak, tiket_masuk_aktif)
    from app.penggilingan.peta_jenis import intake_dari_jenis

    baris = []
    for t in await tiket_masuk_aktif(db):
        # Komoditas tiket dibaca dari PETA JENIS, bukan ditebak dari awalan
        # kodenya. Taksonomi jenis di Timbangan berbasis data dan bisa
        # bertambah; menebak dari nama berarti komoditas baru diam-diam
        # dianggap gabah kering — dan gabah basah yang salah dikenali akan
        # ditawari masuk silo.
        info = intake_dari_jenis(t.get("jenis_kode", ""))
        if info is None or info.model != "gabah":
            continue                      # PK & lainnya punya alurnya sendiri
        nama = nama_pihak(t)
        bobot = t.get("berat_hpp_kg")
        # Basah atau kering disebut lebih dulu: itulah yang menentukan tujuan
        # yang boleh dipilih. Tanpa itu operator harus membuka tiketnya untuk
        # tahu, atau menebak — dan menebak di sini berarti gabah basah masuk
        # silo.
        # Nama komoditas apa adanya dari proses timbang. Kodenya dipakai
        # hanya bila tabel jenisnya tak punya barisnya — dan itu keadaan
        # janggal yang memang harus terlihat, bukan disamarkan.
        komoditas = t.get("jenis_nama") or t.get("jenis_kode") or "?"
        kondisi = info.kondisi or "basah"
        isi = f"{komoditas} · {nama} · {t.get('nomor_polisi') or '-'}"
        if bobot:
            isi += f" · {_kg(bobot)} ({_sumber_bobot(t)})"
        baris.append(Baris(
            kode=t["kode"], isi=isi, aksi="gabah_masuk", nilai=str(t["id"]),
            # Tiket yang MUNCUL di antrean sudah berarti belum ditindak —
            # kepingan fasenya mengatakannya. "Catat & tentukan tempatnya"
            # di bawahnya cuma mengulang hal yang sama dengan kata lain,
            # dan dua kalimat bermakna sama membuat orang mencari bedanya
            # lalu menemukan tak ada. Yang susulan tetap bicara: itu
            # keterangan yang sungguh menambah sesuatu.
            keadaan=("tiket sudah ditutup — susulan" if t.get("susulan") else ""),
            # Pemasoknya yang jadi judul, bukan kata "Tiket timbang": yang
            # dicari mata saat menyusuri antrean adalah siapa, bukan jenis
            # kartunya — jenisnya sudah dikatakan oleh warnanya.
            judul=nama,
            utama=(_kg(bobot).removesuffix(" kg"), "kg") if bobot else None,
            sub=f"{t['kode']} · {komoditas}"
                + (f" · {t.get('nomor_polisi')}" if t.get("nomor_polisi") else ""),
            fakta=([("Sumber berat", _sumber_bobot(t))] if bobot else [])
                  + [("Masuk", _tgl(t.get("tanggal")))],
            # Satu tindakan pun tetap dibentangkan, bukan langsung dilempar
            # ke lembar. Ketukan pertama yang berbeda-beda artinya di tiap
            # kartu memaksa orang menebak apa yang akan terjadi sebelum
            # menekan — dan yang menebak akan berhenti menekan.
            # Tujuannya ditekan LANGSUNG dari kartu — tak ada lembar melayang
            # untuk satu keputusan yang cuma punya beberapa jawaban.
            # ⚠⚠ `tiket=t`, BUKAN `jasa_id=` yang ditebak dari `pelanggan_id`.
            # Pesan kerja 13 (11 Oktober 2026): `t.get("pelanggan_id")` dipakai
            # sebagai penentu "ini jasa atau bukan" adalah cacat kembar dari
            # `adalah_jasa()` (2 Oktober 2026) — salah untuk pelanggan BARU
            # yang diketik bebas (`pelanggan_id`-nya NULL sampai
            # `find_or_create_pelanggan` membuatnya nanti). `_tujuan_gabah`
            # kini menentukan pemiliknya sendiri lewat `cocok_pemilik_tiket`
            # (bandingannya PELANGGAN, bukan tanda `PEMILIK_BARU`) — lihat ⚠⚠
            # di sana.
            tombol=await _tujuan_gabah(
                db, kondisi, post="/api/actions/gabah-masuk",
                data={"timbangan_transaksi_id": t["id"]}, tiket=t),
            tiket_kode=t["kode"], komoditas=komoditas,
            kendaraan=" · ".join(x for x in
                                  (t.get("nomor_polisi"), t.get("nama_sopir")) if x),
            status_jasa=adalah_jasa(t),
            nama_tabel=_nama_tabel_bahan(nama, jasa=adalah_jasa(t)),
        ))
    return baris


def _nama_tabel_bahan(nama: str | None, *, jasa: bool) -> str | None:
    """Nama ringkas tabel; kode jasa tetap tersimpan pada detail kartu."""
    if not nama or not jasa:
        return nama
    nama = nama.removeprefix("JASA · ").strip()
    if nama.startswith("JAS-"):
        _, pemisah, pemilik = nama.partition(" ")
        if pemisah:
            return pemilik.strip()
    return nama


async def _metadata_tiket(db: AsyncSession, ids) -> dict[int, dict]:
    """Ambil ringkasan tiket yang sudah ditautkan, sekali per daftar."""
    ids = sorted({int(x) for x in ids if x is not None})
    if not ids:
        return {}
    from sqlalchemy import bindparam, text

    hasil = await db.execute(
        text("""
            SELECT t.id, t.kode, t.nomor_polisi, t.nama_sopir, j.nama AS jenis_nama
              FROM timbangan_transaksi t
              LEFT JOIN timbangan_jenis j ON j.kode = t.jenis_kode
             WHERE t.id IN :ids
        """).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    )
    return {int(row.id): dict(row._mapping) for row in hasil}


async def _tiket_pk_luar(db: AsyncSession, *, boleh_catat: bool) -> list[Baris]:
    """Tiket timbang PK luar yang belum dicatat.

    **Pindah dari `web/meja_api.py` ke sini 24 September 2026, dan inilah
    jawaban keluhan pemilik** — "ada PK masuk dan sudah ditimbang, kenapa tidak
    ada di antrian tunggu?". Selama ini tiket PK hanya dipancarkan `meja_api`,
    dan hanya app Meja yang memanggilnya; di Pos Produksi — tempat seluruh
    tangkapan layar pemilik diambil — `_tiket_belum_ditaut` memancarkan HANYA
    `model == "gabah"`, jadi tiket PK tak pernah sampai ke antrean mana pun di
    sana, dipetakan maupun tidak.

    Ukuran seberapa jauh ia hilang (QA, 24 Sep 2026): tak ada SATU layar pun di
    Pos Produksi yang menyebut tiket itu, untuk peran mana pun. Operator tak
    bisa mengerjakannya sama sekali (katalognya sudah dicabut dari laci, dan
    sumber daftar tiket PK menjawab 403); Admin bisa, tetapi hanya bila ia sudah
    tahu harus membuka katalog → "Catat PK luar datang" → daftar di dalam
    borang. Tak ada apa pun yang memberitahunya ada PK menunggu.

    `boleh_catat` memisahkan dua pembaca, dan bukan karena selera:

      · **Admin ke atas** — kartu bertindakan. Aksinya `catat_pk_luar` sudah
        ada, dan gerbang perannya (`PERAN_ADMIN_KEATAS` di
        `create_pk_purchase_dari_timbang`) memang menerima mereka.
      · **Operator Gudang 2** — kartu DIAM. Penempatan PK datang bukan tugasnya;
        itu keputusan pemilik 12 September 2026, dan tidak diubah di sini. Tapi
        barangnya berdiri di halamannya, jadi ia tak boleh jadi orang terakhir
        yang tahu. Kartu diam menyebut keadaannya tanpa menawarkan borang yang
        akan menolak isinya — menawarkan tombol yang pasti ditolak lebih buruk
        daripada tak menawarkan apa pun.
    """
    from app.penggilingan.gudang1.services.timbang_link import (
        adalah_jasa, nama_pihak, tiket_masuk_aktif)
    from app.penggilingan.peta_jenis import is_pk

    baris = []
    for t in await tiket_masuk_aktif(db):
        if not is_pk(t.get("jenis_kode", "")):
            continue
        nama = nama_pihak(t)
        bobot = t.get("berat_hpp_kg")
        isi = f"PK luar · {nama} · {t.get('nomor_polisi') or '-'}"
        if bobot:
            isi += f" · {_kg(bobot)} ({_sumber_bobot(t)})"
        baris.append(Baris(
            kode=t["kode"], isi=isi,
            # Kepingan keadaan hanya dipasang pada kartu diam: di kartu yang
            # BISA ditekan, kalimat "dicatat Admin" cuma mengulang apa yang
            # tombolnya sudah katakan.
            keadaan="" if boleh_catat else "dicatat Admin — barangnya di halaman Anda",
            aksi="catat_pk_luar" if boleh_catat else None,
            nilai=str(t["id"]) if boleh_catat else None,
            fase="baru", judul=nama,
            utama=(_kg(bobot).removesuffix(" kg"), "kg") if bobot else None,
            sub=f"{t['kode']} · PK luar · {t.get('nomor_polisi') or '-'}",
            fakta=([("Sumber berat", _sumber_bobot(t))] if bobot else [])
                  + [("Masuk", _tgl(t.get("tanggal")))],
            kelompok="tiket",
            pilihan=([("catat_pk_luar", "Catat PK luar datang",
                       "Jenis PK & kadar air — bobot dari tiket", str(t["id"]))]
                     if boleh_catat else []),
            tiket_kode=t["kode"],
            komoditas=t.get("jenis_nama") or t.get("jenis_kode") or "PK luar",
            kendaraan=" · ".join(x for x in
                                  (t.get("nomor_polisi"), t.get("nama_sopir")) if x),
            status_jasa=adalah_jasa(t),
            nama_tabel=_nama_tabel_bahan(nama, jasa=adalah_jasa(t)),
        ))
    return baris


async def _tiket_jenis_tak_dikenal(
    db: AsyncSession, *, jenis_diizinkan: set[str] | None = None,
) -> list[Baris]:
    """Tiket timbang MASUK yang jenisnya BELUM DIPETAKAN produksi — kartu DIAM.

    Sampai 23 September 2026 tiket semacam ini lenyap dari setiap antrean tanpa
    satu pun tanda: `_tiket_belum_ditaut` hanya memancarkan yang
    `model == "gabah"`, `_tiket_pk_luar` hanya yang `is_pk`, dan yang bukan
    keduanya tak diambil siapa pun. Hanya laporan Rekonsiliasi menyebutnya — dan
    laporan dibuka orang SESUDAH ia curiga, bukan sebelum. Sementara itu
    barangnya sudah turun dari truk dan berdiri di halaman.

    Jaringnya pertama kali dipasang di `meja_api` (commit 7c26a0f) dan itu
    **salah alamat**: hanya Meja memanggilnya, jadi Pos Produksi tetap bisu.
    Dipindah ke sini 24 September 2026 bersama `_tiket_pk_luar`.

    BERAS_MASUK & BROKEN_MASUK punya jalur khusus ke stok barang jadi. Jenis
    itu ditampilkan di Gudang 2 dengan tombol penerimaan stok, bukan sebagai
    komoditas yang belum dikenal.

    TANPA tindakan: yang benar memang belum ada. Yang bisa dikerjakan orang ada
    di luar layar ini — memetakan jenisnya di produksi, atau membatalkan
    tiketnya di Pos Timbang.

    Admin ke atas saja. Operator tak punya jalan keluar untuk kartu ini:
    pemetaan jenis bukan wewenangnya, dan kartu yang tak bisa ia kerjakan
    maupun teruskan hanya menambah angka pada lencananya.
    """
    from app.penggilingan.gudang1.services.timbang_link import (
        adalah_jasa, nama_pihak, tiket_masuk_aktif)
    from app.penggilingan.peta_jenis import intake_dari_jenis

    baris = []
    for t in await tiket_masuk_aktif(db):
        kode_jenis = t.get("jenis_kode") or "?"
        produk_masuk = {
            "BERAS_MASUK": ("catat_beras_timbang_masuk", "Terima beras sebagai stok bertumpuk"),
            "BROKEN_MASUK": ("catat_broken_timbang_masuk", "Terima broken sebagai stok bertumpuk"),
        }.get(kode_jenis) if jenis_diizinkan and kode_jenis in jenis_diizinkan else None
        if kode_jenis in {"BERAS_MASUK", "BROKEN_MASUK"} and produk_masuk is None:
            continue  # Jalur produk ini hanya ditampilkan di antrean Gudang 2.
        if intake_dari_jenis(kode_jenis) is not None:
            continue                       # dipetakan → sudah ada jalurnya
        nama = nama_pihak(t)
        bobot = t.get("berat_hpp_kg")
        # Nama jenisnya dari tabel jenis Pos Timbang bila ada; kodenya bila
        # tidak. Keduanya disebut: nama yang dibaca orang, kode yang dipakai
        # memetakannya nanti.
        jenis_nama = t.get("jenis_nama") or kode_jenis
        isi = f"{jenis_nama} · {nama} · {t.get('nomor_polisi') or '-'}"
        if bobot:
            isi += f" · {_kg(bobot)} ({_sumber_bobot(t)})"
        tindakan = {}
        if produk_masuk:
            tindakan = {
                "aksi": produk_masuk[0],
                "nilai": str(t["id"]),
                "pilihan": [(produk_masuk[0], produk_masuk[1],
                             "Barang masuk ke stok bertumpuk; pemindahan ke silo dilakukan dari kartu stok.",
                             str(t["id"]))],
            }
        baris.append(Baris(
            kode=t["kode"], isi=isi,
            keadaan=("menunggu dicatat sebagai stok" if produk_masuk else
                     f"jenis \u201c{kode_jenis}\u201d belum dikenal produksi"),
            # `aksi` & `nilai` sengaja TIDAK disebut, bukan disebut bernilai
            # None: `test_setiap_kartu_membentang_di_tempat` membaca AST-nya dan
            # hanya melihat NAMA argumennya, jadi `aksi=None` terbaca seperti
            # kartu bertindakan yang lupa membawa `pilihan`. Diamnya kartu ini
            # dinyatakan dengan tidak menyebutnya sama sekali.
            fase="baru", judul=nama,
            utama=(_kg(bobot).removesuffix(" kg"), "kg") if bobot else None,
            sub=f"{t['kode']} · {jenis_nama} · {t.get('nomor_polisi') or '-'}",
            fakta=[("Jenis timbang", kode_jenis)]
                  + ([("Sumber berat", str(t.get("sumber_berat") or "-"))] if bobot else [])
                  + [("Masuk", _tgl(t.get("tanggal")))],
            kelompok="tiket",
            tiket_kode=t["kode"], komoditas=jenis_nama,
            kendaraan=" · ".join(x for x in
                                  (t.get("nomor_polisi"), t.get("nama_sopir")) if x),
            status_jasa=adalah_jasa(t),
            nama_tabel=_nama_tabel_bahan(nama, jasa=adalah_jasa(t)),
            **tindakan,
        ))
    return baris


async def _lot(db: AsyncSession, *, pendinginan_selesai: bool) -> list[DryingLot]:
    belum_silo = ~exists().where(SiloStorage.drying_lot_id == DryingLot.id)
    syarat = (DryingLot.waktu_selesai_pendinginan.is_not(None)
              if pendinginan_selesai else DryingLot.waktu_selesai_pendinginan.is_(None))
    return list((await db.execute(
        select(DryingLot).where(
            DryingLot.status == "selesai",
            DryingLot.dryer_id.is_not(None),
            syarat, belum_silo,
        ).order_by(DryingLot.id.desc())
    )).scalars().all())


def _cap_gudang(b: Berjalan, gid: str) -> Berjalan:
    """Cap seluruh baris `b` dengan gudangnya. Sekali di ujung penyusunnya.

    Baris yang SUDAH bergudang tidak ditimpa: tiket berjenis tak dikenal
    sengaja tak punya gudang, dan mengecapnya dengan gudang penyusunnya berarti
    menebak — lalu mengarahkan orang ke gudang yang mungkin salah.
    """
    for daftar in (b.menunggu, b.berjalan, b.transit, b.meja):
        for x in daftar:
            if x.gudang is None:
                x.gudang = gid
    return b


async def untuk_gudang1(db: AsyncSession, *, boleh_qc: bool = False) -> Berjalan:
    """Pekerjaan operator Gudang 1, dari truk masuk sampai giling ditutup.

    `boleh_qc` — pembacanya boleh mencatat mutu (admin ke atas). Mutu dicatat
    dari kartu giling yang SEDANG BERJALAN sejak 24 September 2026 (keputusan
    pemilik), dan tombol yang ditawarkan kepada orang yang akan ditolak rutenya
    lebih buruk daripada tombol yang tak ada: ia mengajari orang bahwa
    aplikasinya suka menolak.
    """
    b = Berjalan()

    b.menunggu += await _tiket_belum_ditaut(db)

    # Di dryer gabah punya DUA keadaan: masih satu-dua batch yang menunggu,
    # dan sudah menjadi lot. Yang pertama menunggu operator menyalakan mesin —
    # kalau tak ditampilkan, gabah bisa bermalam di dryer tanpa dipanaskan dan
    # tak ada satu layar pun yang menyebutnya.
    from app.penggilingan.gudang1.services.drying import (
        _loose_dryer_batches, dryers_g1, mode_disarankan)

    # SATU KARTU PER MESIN, bukan satu kartu untuk semua.
    #
    # Sebelumnya batch yang menunggu diambil tanpa menyebut mesinnya, lalu
    # dijumlahkan jadi satu kartu "Mesin pengering". Selama pabrik cuma punya
    # satu mesin, hasilnya kebetulan benar. Begitu ada dua, kartunya
    # menjumlahkan gabah dari mesin yang berbeda — bobot yang tak pernah ada
    # di satu tempat, dan mode yang disarankan dari jumlah itu. Padahal
    # `_loose_dryer_batches` sendiri sudah memperingatkannya di docstring-nya.
    for mesin in await dryers_g1(db):
        isi_mesin = await _loose_dryer_batches(db, mesin.id)
        if not isi_mesin:
            continue
        bt = dari_batches(isi_mesin)
        total = bt.angka()
        kondisi = {x.kondisi_gabah for x in isi_mesin}
        b.transit.append(Baris(
            kode="",
            isi=f"{len(isi_mesin)} batch di {mesin.nama} · {bt.teks()}",
            keadaan="nyalakan mesinnya",
            aksi="mulai_pengeringan", fase="dryer",
            # Mesinnya ikut, jadi lembarnya tak menanyakan lagi mesin mana —
            # kartunya sudah menunjuknya.
            nilai=str(mesin.id),
            sejak=min((x.created_at for x in isi_mesin if x.created_at), default=None),
            judul=mesin.nama,
            utama=_utama(bt),
            sub=f"{len(isi_mesin)} batch"
                + (f" · gabah {'/'.join(sorted(kondisi))}" if kondisi else ""),
            fakta=[("Mode terdekat", mode_disarankan(total)),
                   ("Target", "belum ditetapkan")],
            anak=await _asal(db, [x.id for x in isi_mesin]),
            # Gabah yang bermalam di mesin tanpa dipanaskan tidak diam saja —
            # ia menurun mutunya. Karena itu ini satu-satunya baris transit
            # yang berteriak: yang lain (silo menunggu giliran) memang boleh
            # menunggu berhari-hari tanpa ada yang salah.
            nota=("Mesin belum dinyalakan — gabah sudah menunggu "
                  + (_lama(min((x.created_at for x in isi_mesin if x.created_at),
                               default=None)) or "sejak dicatat")),
            nota_jenis="hati",
            pilihan=[("mulai_pengeringan", "Mulai pengeringan",
                      "Sebutkan target kadar air & mode yang disetel di mesin")],
            ringkas=f"{len(isi_mesin)} batch menunggu mesin dinyalakan"
                    f" · mode terdekat {mode_disarankan(total)}",
        ))

    # Gabah yang TERCATAT tetapi belum ditempatkan di mana pun.
    #
    # Terjadi saat penempatan otomatis gagal — dryer sedang dipakai, misalnya.
    # Batch-nya tetap tersimpan (dan memang harus: gabahnya sudah turun dari
    # truk), lalu berstatus 'baru' dan tidak berada di dryer, silo, maupun
    # tumpukan. Tanpa baris ini, gabah itu berdiri di halaman tanpa ada satu
    # layar pun yang menyebutnya.
    batch_baru = (await db.execute(
        select(PurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id, isouter=True)
        .where(PurchaseBatch.status_batch == "baru")
        .order_by(PurchaseBatch.id.desc())
    )).all()
    tiket_batch = await _metadata_tiket(
        db, (b_.timbangan_transaksi_id for b_, _ in batch_baru))
    for b_, nama_pemasok in batch_baru:
        tiket = tiket_batch.get(b_.timbangan_transaksi_id or -1, {})
        # Pemiliknya menggantikan nama pemasok untuk barang titipan. Jatuh ke
        # kode batch adalah pilihan terakhir: kode tak memberi tahu apa pun
        # tentang siapa yang menunggu barangnya.
        nama_pemasok = (nama_pemasok or await nama_pemilik(db, b_.jasa_id)
                        or b_.kode_batch)
        b.menunggu.append(Baris(
            kode=b_.kode_batch,
            isi=f"{dari_batch(b_).teks()} · gabah {b_.kondisi_gabah}",
            keadaan="tentukan tempatnya",
            aksi="pindah_tumpukan", nilai=b_.kode_batch, fase="baru",
            sejak=b_.created_at,
            judul=nama_pemasok,
            utama=_utama(dari_batch(b_)),
            sub=f"{b_.kode_batch} · gabah {b_.kondisi_gabah} · "
                f"masuk {_tgl(b_.tanggal_pembelian)}",
            tombol=await _tujuan_gabah(
                db, b_.kondisi_gabah, post="/api/actions/pindah-tumpukan",
                data={"kode_batch": b_.kode_batch}, jasa_id=b_.jasa_id),
            tiket_kode=tiket.get("kode"),
            komoditas=tiket.get("jenis_nama") or f"Gabah {b_.kondisi_gabah}",
            kendaraan=" · ".join(x for x in
                                  (b_.no_polisi_truk or tiket.get("nomor_polisi"),
                                   tiket.get("nama_sopir")) if x),
            status_jasa=b_.jasa_id is not None,
            nama_tabel=_nama_tabel_bahan(
                nama_pemasok, jasa=b_.jasa_id is not None),
        ))

    # Tumpukan lebih dulu dari yang lain: isinya menandakan pembelian berlebih,
    # dan itu keadaan yang paling ingin diketahui — bukan yang paling dalam
    # daftar. Kosong berarti tak ada baris sama sekali, seperti seharusnya.
    from app.penggilingan.gudang1.services import tumpukan as tmp
    tumpukan_baris = await tmp.isi(db)
    tiket_tumpukan = await _metadata_tiket(
        db, (b_.timbangan_transaksi_id for b_ in tumpukan_baris))
    for b_ in tumpukan_baris:
        tiket = tiket_tumpukan.get(b_.timbangan_transaksi_id or -1, {})
        wajib_dryer = b_.kondisi_gabah == "basah"
        pemilik_ = await nama_pemilik(db, b_.jasa_id)
        nama_pemasok = pemilik_ or (await db.execute(
            select(Supplier.nama_supplier).where(Supplier.id == b_.supplier_id)
        )).scalars().first() or b_.kode_batch
        # ⚠ KALIMATNYA BERBEDA UNTUK BARANG JASA, dan kartunya TIDAK
        # disembunyikan.
        #
        # Tumpukan di app ini adalah ALARM, bukan ruang tunggu: aturan Direksi
        # yang tertulis di `tumpukan.py` berbunyi "kalau ada tumpukan, berarti
        # ada pembelian yang berlebih". Aturan itu untuk gabah yang DIBELI, dan
        # di situ masih benar. Barang jasa bukan pembelian — tiga pelanggan yang
        # menunggu giliran akan berdiri sebagai tiga "pembelian berlebih", dan
        # daftar yang menagih pekerjaan yang tidak salah akan berhenti dibaca
        # (bahaya yang sudah ditulis sendiri di `rekonsiliasi.py`).
        #
        # Disembunyikan pun salah: pelanggan yang menunggu MEMANG pekerjaan.
        # Jadi yang berubah kalimatnya.
        if b_.jasa_id is not None:
            keadaan_ = ("harus ke dryer — belum kering" if wajib_dryer
                        else "menunggu giliran giling")
        else:
            keadaan_ = ("harus ke dryer — belum kering" if wajib_dryer
                        else "tentukan tempatnya")
        b.menunggu.append(Baris(
            kode=b_.kode_batch,
            isi=(f"menunggu giliran · {dari_batch(b_).teks()} · gabah {b_.kondisi_gabah}"
                 if b_.jasa_id is not None else
                 f"menumpuk · {dari_batch(b_).teks()} · gabah {b_.kondisi_gabah}"),
            keadaan=keadaan_,
            aksi="pindah_tumpukan", nilai=b_.kode_batch, sejak=b_.created_at,
            fase="tumpuk",
            judul=nama_pemasok,
            utama=_utama(dari_batch(b_)),
            sub=f"{b_.kode_batch} · gabah {b_.kondisi_gabah} · "
                f"masuk {_tgl(b_.tanggal_pembelian)}",
            nota=("Gabah basah tak boleh ke silo — harus dikeringkan dulu."
                  if wajib_dryer else None),
            kelompok="tumpukan",
            tombol=await _tujuan_gabah(
                db, b_.kondisi_gabah, post="/api/actions/pindah-tumpukan",
                data={"kode_batch": b_.kode_batch}, jasa_id=b_.jasa_id),
            tiket_kode=tiket.get("kode"),
            komoditas=tiket.get("jenis_nama") or f"Gabah {b_.kondisi_gabah}",
            kendaraan=" · ".join(x for x in
                                  (b_.no_polisi_truk or tiket.get("nomor_polisi"),
                                   tiket.get("nama_sopir")) if x),
            status_jasa=b_.jasa_id is not None,
            nama_tabel=_nama_tabel_bahan(
                nama_pemasok, jasa=b_.jasa_id is not None),
        ))

    from app.penggilingan.gudang1.services.drying import _lot_batches

    for lot in await _lot(db, pendinginan_selesai=True):
        asal = await _asal(db, [x.id for x in await _lot_batches(db, lot.id)])
        b.transit.append(Baris(
            kode=lot.kode_lot, isi="sudah dingin, dryer perlu dikosongkan",
            keadaan="pindahkan ke silo", aksi="pindah_silo",
            nilai=lot.kode_lot, fase="dryer",
            judul="Sudah dingin",
            sub=f"{lot.kode_lot} · gabahnya masih di mesin"
                + (f" · {_pemasok_ringkas(asal)}" if asal else ""),
            anak=asal,
            ringkas="gabahnya masih di mesin — pindahkan ke silo",
            sejak=lot.waktu_selesai_pendinginan,
            # Dingin boleh dinyatakan berkali-kali — gabah yang sudah
            # dinyatakan dingin bisa ternyata masih panas setelah dicek.
            pilihan=[
                ("pindah_silo", "Pindah ke silo", "Kosongkan mesin pengering"),
                ("selesai_pendinginan", "Dinginkan lagi",
                 "Kalau setelah dicek ternyata masih panas"),
            ],
        ))

    for lot in await _lot(db, pendinginan_selesai=False):
        asal = await _asal(db, [x.id for x in await _lot_batches(db, lot.id)])
        b.berjalan.append(Baris(
            kode=lot.kode_lot, isi="pengeringan selesai, sedang didinginkan",
            keadaan="nyatakan bila sudah dingin", aksi="selesai_pendinginan",
            nilai=lot.kode_lot, fase="dryer",
            sejak=lot.waktu_selesai_pengeringan,
            judul="Pendinginan",
            sub=f"{lot.kode_lot} · gabah tetap di mesin"
                + (f" · {_pemasok_ringkas(asal)}" if asal else ""),
            anak=asal,
            ringkas="pengeringan selesai · menunggu dingin",
            pilihan=[("selesai_pendinginan", "Nyatakan sudah dingin",
                      "Lot siap dipindah ke silo")],
        ))

    # Giling yang sudah ditutup tetapi belum di-QC / belum diverifikasi TIDAK
    # masuk sini: itu pekerjaan staff, bukan operator. Lihat `untuk_staff`.
    for lot in (await db.execute(
        select(DryingLot).where(DryingLot.status == "proses")
        .order_by(DryingLot.id.desc())
    )).scalars().all():
        # Kadar air terakhir disebut di kartunya sendiri — KEDUANYA.
        #
        # Operator yang hendak memutuskan "sudah cukup kering atau belum" tak
        # perlu membuka laporan untuk melihat angka terakhir. Dan bacaan mesin
        # ikut ditampilkan, bukan hanya rata-rata alat tes: keduanya mengukur
        # hal yang sama dengan alat berbeda, dan yang menarik justru saat
        # keduanya tidak sepakat.
        from app.penggilingan.gudang1.services.drying import _latest_log

        log = await _latest_log(db, lot.id)
        ka = []
        if log is not None and log.kadar_air_tes_manual is not None:
            ka.append(f"alat tes {float(log.kadar_air_tes_manual):.1f}%")
        if log is not None and log.kadar_air_indikator is not None:
            ka.append(f"mesin {float(log.kadar_air_indikator):g}%")
        # Yang sedang BERHENTI tidak boleh terbaca seperti yang sedang jalan:
        # ia tak menunggu operator, ia menunggu montir — dan selama ia diam
        # tak ada gabah yang bergerak.
        from app.penggilingan.gudang1.services.jeda import jeda_terbuka, tertahan_detik

        macet = await jeda_terbuka(db, "pengeringan", lot.id)
        tertahan = await tertahan_detik(db, "pengeringan", lot.id)
        tambahan = []
        if tertahan >= 60:
            tambahan.append(f"tertahan {tertahan / 3600:.1f} jam")
        # Berat & isi lotnya, supaya kartunya menyebut punya siapa.
        from app.penggilingan.gudang1.services.drying import _lot_batches

        isi_lot = await _lot_batches(db, lot.id)
        bl = dari_batches(isi_lot)
        kg_lot = bl.angka()
        from app.penggilingan.gudang1.services.drying import (
            kadar_air_awal, kemajuan, peringatan_kadar_air)
        from app.services.setelan import target_kadar_air

        target_n = (float(lot.target_kadar_air) if lot.target_kadar_air is not None
                    else await target_kadar_air(db))
        target = f"{target_n:g}%"
        asal_lot = await _asal(db, [x.id for x in isi_lot])
        # Alat tes yang menggerakkan batang kemajuan — itulah ukuran yang
        # dipakai memutuskan. Bacaan mesin cuma pembanding; kalau ia ikut
        # menggerakkan batang, dryer yang sensornya melenceng akan menyeret
        # kemajuan seluruh lot tanpa ada yang tahu.
        kini = None
        if log is not None:
            if log.kadar_air_tes_manual is not None:
                kini = float(log.kadar_air_tes_manual)
            elif log.kadar_air_indikator is not None:
                kini = float(log.kadar_air_indikator)
        maju = kemajuan(await kadar_air_awal(db, lot.id), kini, target_n)
        fakta = []
        if log is not None and log.kadar_air_tes_manual is not None:
            fakta.append(("Alat tes", f"{float(log.kadar_air_tes_manual):.1f}%"))
        if log is not None and log.kadar_air_indikator is not None:
            fakta.append(("Mesin", f"{float(log.kadar_air_indikator):g}%"))
        fakta.append(("Target", target))
        if lot.mode_dryer:
            fakta.append(("Mode", lot.mode_dryer))
        if tertahan >= 60:
            fakta.append(("Tertahan", f"{tertahan / 3600:.1f} jam"))
        b.berjalan.append(Baris(
            kode=lot.kode_lot,
            isi=(f"⏸ berhenti — {macet.sebab}" if macet else "sedang dikeringkan")
                + (" · " + " · ".join(ka) if ka else " · kadar air belum dicatat")
                + ("".join(" · " + t for t in tambahan)),
            judul=("Pengeringan dijeda" if macet else "Pengeringan"),
            utama=_utama(bl),
            sub=f"{lot.kode_lot} · {len(isi_lot)} batch"
                + (f" · {_pemasok_ringkas(asal_lot)}" if asal_lot else ""),
            fakta=fakta,
            anak=asal_lot,
            # Jam tertahan disebut di notanya sendiri: "menunggu dilanjutkan"
            # tak memberi tahu apakah itu lima menit atau sejak kemarin, dan
            # justru itulah yang menentukan apakah seseorang harus turun
            # tangan sekarang.
            nota=(f"Dijeda {lama_kata(tertahan)} — {macet.sebab}" if macet else None),
            nota_jenis="hati" if macet else None,
            maju=maju,
            # Dulu hanya muncul di kabar sekejap sesudah menyimpan, lalu
            # hilang bersamanya. Padahal justru inilah yang menerangkan
            # mengapa kadar airnya tak kunjung turun.
            catatan=peringatan_kadar_air(log),
            ringkas=(f"⏸ {macet.sebab}"
                     + (f" · tertahan {tertahan / 3600:.1f} jam" if tertahan >= 60 else "")
                     if macet else
                     (" · ".join(ka) + f" → target {target}" if ka
                      else "kadar air belum dicatat")),
            keadaan=("menunggu dilanjutkan" if macet else "menunggu kadar air turun"),
            aksi=("lanjutkan_proses" if macet else "kadar_air"),
            nilai=(f"pengeringan:{lot.kode_lot}" if macet else lot.kode_lot),
            fase="dryer",
            sejak=lot.waktu_mulai_pengeringan,
            # Tiap pilihan menyebut nilainya SENDIRI. Satu kartu memang satu
            # proses, tetapi tiap aksi menamainya dengan bentuknya sendiri —
            # kadar air memakai kode lot, hentikan/lanjutkan memakai
            # "pengeringan:<kode>". Satu nilai untuk semuanya berarti salah
            # satunya tak pernah cocok, dan lembarnya bertanya lagi proses
            # mana yang dimaksud padahal kartunya sudah menunjuknya.
            pilihan=([
                ("lanjutkan_proses", "Lanjutkan pengeringan",
                 "Mesin jalan lagi — bisa nanti, bisa besok",
                 f"pengeringan:{lot.kode_lot}"),
                ("kadar_air", "Perbarui kadar air", "Catat hasil ukur terbaru",
                 lot.kode_lot),
                ("selesai_pengeringan", "Selesai pengeringan",
                 "Lot langsung masuk fase pendinginan", lot.kode_lot),
            ] if macet else [
                ("kadar_air", "Perbarui kadar air", "Catat hasil ukur terbaru",
                 lot.kode_lot),
                ("hentikan_proses", "Hentikan sementara",
                 "Mesin rusak, listrik padam, jam kerja habis",
                 f"pengeringan:{lot.kode_lot}"),
                ("selesai_pengeringan", "Selesai pengeringan",
                 "Lot langsung masuk fase pendinginan", lot.kode_lot),
            ]),
        ))

    # Silo berisi gabah kering yang belum digiling.
    #
    # Sebelumnya TIDAK ADA baris untuk ini di layar mana pun: gabah yang sudah
    # aman di silo tak lagi disebut sampai seseorang ingat menggilingnya.
    # Diam-diam itu keadaan paling mahal — gabah kering yang menunggu tidak
    # rusak, tetapi uang yang tertanam di dalamnya juga tidak bergerak.
    from app.models import Silo
    from app.penggilingan.gudang1.services.silo import (
        _g1_warehouse_id, _silo_active_rows, _silo_content_bobot,
        giling_berjalan_untuk_silo)

    wid = await _g1_warehouse_id(db)
    for silo in (await db.execute(
        select(Silo).where(Silo.warehouse_id == wid, Silo.aktif.is_(True)).order_by(Silo.nama_silo)
    )).scalars().all():
        if not await _silo_active_rows(db, silo.id):
            continue
        # ── "ada di antara SUMBER proses yang berjalan", bukan "silo_id-nya" ──
        #
        # Satu lot boleh datang dari beberapa silo (keputusan pemilik 24
        # September 2026), dan `MillingProcess.silo_id` cuma menyebut yang
        # pertama. Dulu di sini ia yang ditanya, jadi silo KEDUA tetap
        # berkartu "siap digiling" — lengkap dengan tombolnya — padahal
        # gabahnya sudah di dalam mesin. Yang menekannya memulai giling kedua
        # atas gabah yang sama, dan dua rendemen lahir dari satu muatan.
        if await giling_berjalan_untuk_silo(db, silo.id) is not None:
            continue
        huruf = silo.nama_silo.replace("Silo ", "")
        # Masuk `berjalan`, BUKAN `menunggu` — sengaja, dan ini soal lencana.
        #
        # Silo penuh memang menunggu orang, tetapi bisa menunggu berhari-hari
        # tanpa ada yang salah: giling dijadwalkan, bukan didesak. Kalau ia
        # ikut dihitung, lencana tak pernah kembali nol — dan lencana yang tak
        # pernah nol mengajari orang mengabaikan lencana.
        bs = await _silo_content_bobot(db, silo.id)
        kg_silo = bs.angka()
        # Isi silo bisa datang dua jalan: batch beli-kering yang masuk
        # langsung, dan lot hasil pengeringan sendiri. Keduanya ditelusuri
        # ke batch-nya, karena hanya di situ nama pemasok dan tanggal masuk
        # tersimpan.
        baris_silo = await _silo_active_rows(db, silo.id)
        bid_silo = [r.purchase_batch_id for r in baris_silo if r.purchase_batch_id]
        for r in baris_silo:
            if r.drying_lot_id:
                bid_silo += [x.id for x in await _lot_batches(db, r.drying_lot_id)]
        asal_silo = await _asal(db, set(bid_silo))
        b.transit.append(Baris(
            kode=silo.nama_silo, isi=f"gabah kering · {bs.teks()}",
            keadaan="mulai giling bila siap", aksi="mulai_giling",
            nilai=huruf, fase="silo",
            judul=silo.nama_silo,
            utama=_utama(bs),
            sub="gabah kering · menunggu giliran digiling"
                + (f" · {_pemasok_ringkas(asal_silo)}" if asal_silo else ""),
            anak=asal_silo,
            ringkas="gabah kering · menunggu giliran digiling",
            # Kartunya menyebut SATU silo, tapi borangnya membuka semuanya:
            # silo ini sudah tercentang, dan yang lain boleh ikut dicentang —
            # hasilnya tetap satu lot. Keterangannya menyebut itu, sebab
            # tombol yang membuka lebih banyak daripada yang dijanjikannya
            # membuat orang menutup borangnya lagi karena merasa salah tekan.
            pilihan=[("mulai_giling", "Mulai giling",
                      "Silo ini sudah dicentang · silo lain boleh ikut, "
                      "hasilnya tetap satu lot (LOT-…)")],
        ))

    giling_jalan = (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "proses")
        .order_by(MillingProcess.id.desc())
    )).scalars().all()
    # Rata-rata QC seluruh proses yang menyala, SATU kueri — kartu ini disusun
    # ulang tiap kali lencana laci dihitung, yaitu di tiap halaman.
    from app.penggilingan.gudang1.services.milling import qc_rata_banyak
    from app.services.setelan import fitur_mutu

    qc_aktif = await fitur_mutu(db) if giling_jalan else False
    rata_qc = (await qc_rata_banyak(db, [p.id for p in giling_jalan])
               if qc_aktif else {})
    for p in giling_jalan:
        from app.penggilingan.gudang1.services.jeda import jeda_terbuka, tertahan_detik

        macet = await jeda_terbuka(db, "giling", p.id)
        tertahan = await tertahan_detik(db, "giling", p.id)
        from app.models import MillingProcessSource

        sumber = (await db.execute(
            select(MillingProcessSource.purchase_batch_id,
                   MillingProcessSource.drying_lot_id)
            .where(MillingProcessSource.milling_process_id == p.id))).all()
        bid_giling = [x[0] for x in sumber if x[0]]
        for _, lid in sumber:
            if lid:
                bid_giling += [x.id for x in await _lot_batches(db, lid)]
        asal_giling = await _asal(db, set(bid_giling))
        fakta_g = [("Bahan", _kg(p.berat_gabah_masuk_kg)
                    + ("" if p.bobot_masuk_final else " · belum final, menunggu timbang"))]
        if tertahan >= 60:
            fakta_g.append(("Tertahan", f"{tertahan / 3600:.1f} jam"))
        # Mutu yang SUDAH dicatat selama proses ini berjalan. Sampai 24
        # September 2026 angka-angka itu tersimpan tanpa pernah dibaca kembali
        # oleh satu layar pun — `milling_qc_logs` cuma ditulis dan dihitung
        # jumlahnya. Yang dicatat tanpa pernah terbaca sama saja dengan yang
        # tak dicatat, kecuali ia memakan waktu orang.
        _rata = rata_qc.get(p.id)
        if _rata is not None and _rata.ada:
            fakta_g.append(("Mutu", _rata.teks()))

        # ── SILO dan HASIL: dua hal yang kartunya tak pernah sebut ──
        #
        # Laporan operator Gudang 1, 28 September 2026: "hasil giling ditulis
        # lebih dari jumlah gabah bisa tersimpan, tetapi angka yg tertera sama
        # seperti berat gabah." Diperiksa QA: angkanya TIDAK dipotong — 11.000
        # tersimpan apa adanya, dan layar Stok menyebutnya benar. Yang keliru
        # kartunya: angka besarnya BAHAN MASUK, dan hasilnya tak pernah muncul
        # sama sekali. Operator menekan "Perbarui hasil giling", kembali ke
        # kartunya, melihat 10.000 — dan menyimpulkan angkanya diganti.
        #
        # Ini KETIGA KALINYA kartu ini kurang informasi; silonya juga tak
        # pernah disebut (temuan QA 27 September). Keduanya dikerjakan
        # sekaligus, dan bentuknya disamakan dengan kartu penyosohan: dua
        # gudang yang mengerjakan hal serupa tak boleh berkartu beda bentuk,
        # sebab orangnya berpindah antar gudang.
        from app.penggilingan.gudang1.services.milling import (_produced_pk,
                                                               hitung_rendemen)
        from app.penggilingan.gudang1.services.silo import silo_ids_proses

        nama_silo_g = []
        for sid in await silo_ids_proses(db, p):
            si = await db.get(Silo, sid)
            if si:
                nama_silo_g.append(si.nama_silo.replace("Silo ", ""))
        if nama_silo_g:
            fakta_g.insert(0, ("Silo", " + ".join(nama_silo_g)))
        hasil_pk = await _produced_pk(db, p.id)
        if hasil_pk:
            rend = hitung_rendemen(hasil_pk, p.berat_gabah_masuk_kg)
            fakta_g.append(("Hasil", _kg(hasil_pk)
                            + (f" · rendemen {rend:.1f}%" if rend is not None else "")))

        b.berjalan.append(Baris(
            kode=p.kode_proses,
            isi=(f"⏸ berhenti — {macet.sebab}" if macet else "digiling")
                + f" · {_kg(p.berat_gabah_masuk_kg)} gabah masuk"
                + (f" · tertahan {tertahan / 3600:.1f} jam" if tertahan >= 60 else ""),
            judul=("Giling dijeda" if macet else "Giling"),
            utama=((_kg(p.berat_gabah_masuk_kg).removesuffix(" kg"), "kg")
                   if p.berat_gabah_masuk_kg is not None else None),
            sub=f"{p.kode_proses} · bahan masuk"
                + (f" · {_pemasok_ringkas(asal_giling)}" if asal_giling else ""),
            anak=asal_giling,
            fakta=fakta_g,
            nota=(f"Dijeda {lama_kata(tertahan)} — {macet.sebab}" if macet else None),
            nota_jenis="hati" if macet else None,
            ringkas=(f"⏸ {macet.sebab}"
                     + (f" · tertahan {tertahan / 3600:.1f} jam" if tertahan >= 60 else "")
                     if macet else
                     (f"{_kg(p.berat_gabah_masuk_kg)} bahan · hasil {_kg(hasil_pk)}"
                      if hasil_pk else f"{_kg(p.berat_gabah_masuk_kg)} bahan masuk")),
            keadaan=("menunggu dilanjutkan" if macet else "catat hasil, tutup bila selesai"),
            aksi=("lanjutkan_proses" if macet else "hasil_giling"),
            nilai=(f"giling:{p.kode_proses}" if macet else p.kode_proses),
            fase="giling",
            sejak=p.waktu_mulai,
            pilihan=([
                ("lanjutkan_proses", "Lanjutkan giling",
                 "Mesin jalan lagi — bisa nanti, bisa besok",
                 f"giling:{p.kode_proses}"),
                # "Bebaskan silo" — keputusan pemilik 5 Oktober 2026: silo
                # bisa habis duluan sementara gabahnya MASIH DI MESIN, jadi
                # tombol ini TAK menutup prosesnya (beda dari "Selesai
                # giling" di bawahnya) — lihat `milling.tutup_silo_giling`.
                ("tutup_silo_giling", "Bebaskan silo",
                 "Boleh diisi gabah baru — proses tetap berjalan",
                 p.kode_proses),
                ("selesai_giling", "Selesai giling", "Tutup proses & kosongkan silo",
                 p.kode_proses),
            ] if macet else [
                ("hasil_giling", "Perbarui hasil giling", "Catat PK kumulatif terbaru",
                 p.kode_proses),
                *([("qc_giling", "Catat mutu sekarang",
                    "Contoh dari beras yang baru keluar mesin — hasilnya dirata-rata",
                    p.kode_proses)] if (boleh_qc and qc_aktif) else []),
                # Mix bahan — laporan lapangan 7 Oktober 2026: silo lain
                # dipakai di tengah proses, bukan cuma saat mulai.
                ("tambah_silo_giling", "Tambah silo (mix bahan)",
                 "Silo lain ikut jadi bahan — harus sepemilik",
                 p.kode_proses),
                ("hentikan_proses", "Hentikan sementara",
                 "Mesin rusak, limbah penuh, jam kerja habis",
                 f"giling:{p.kode_proses}"),
                ("tutup_silo_giling", "Bebaskan silo",
                 "Boleh diisi gabah baru — proses tetap berjalan",
                 p.kode_proses),
                ("selesai_giling", "Selesai giling", "Tutup proses & kosongkan silo",
                 p.kode_proses),
            ]),
        ))

    # ── PK yang sudah DISETUJUI Admin untuk dikirim ke Gudang 2 ──
    #
    # TUGAS, dan tugasnya Gudang 1 (keputusan pemilik 27 September 2026):
    # "gudang 1 yang mengirim", "jika sudah disetujui", "jadi gudang 1 mulai
    # proses kirim". Itu menjawab pertanyaan yang ditinggalkan QA sebagai
    # skenario B1 — di lapangan siapa yang sebenarnya mengangkat karungnya.
    #
    # Sehari sebelumnya kartu ini sempat jadi kabar tanpa tombol, dan tombolnya
    # pindah ke Gudang 2. Aturannya SAMA dan tidak berubah — yang mencatat
    # "berat yang dimuat" harus orang yang melihat karungnya naik, dan hanya
    # satu tangan yang boleh menekan. Yang berubah keterangan lapangannya:
    # orang itu Gudang 1.
    #
    # Ia berpagar pada BARISNYA, bukan pada peran: `can_transfer_pk` tak
    # disentuh. Yang muncul di sini hanya permintaan berstatus `disetujui` —
    # yang masih menunggu keputusan Admin TIDAK ditampilkan, sebab kartu yang
    # belum boleh dikerjakan akan ditekan juga, dan yang menekannya menerima
    # penolakan atas pekerjaan yang memang bukan haknya hari itu.
    from app.models import PermintaanPk
    from app.services import permintaan_pk as _pmt

    # Digugurkan lebih dulu, DI SINI JUGA. Penggugurnya dulu cuma dipanggil
    # saat kartu Admin disusun, jadi operator Gudang 1 tetap melihat perintah
    # memuat lot yang sudah habis lewat jalan lain — sampai kebetulan ada
    # Admin yang membuka layarnya. Kartu yang tak bisa dikerjakan akan ditekan
    # juga, dan penolakannya datang sesudah orangnya berjalan ke tumpukan.
    await _pmt.gugurkan_yang_habis(db)
    for baris, kode_lot in (await db.execute(
        select(PermintaanPk, MillingProcess.kode_proses)
        .join(MillingProcess, MillingProcess.id == PermintaanPk.milling_process_id)
        .where(PermintaanPk.status == _pmt.DISETUJUI)
        .order_by(PermintaanPk.waktu_setuju)
    )).all():
        from app.penggilingan.gudang2.service import label_tujuan

        lok = await label_tujuan(db, baris.tujuan, baris.silo_id)
        kg = float(baris.berat_setuju_kg or 0)
        b.menunggu.append(Baris(
            kode=kode_lot,
            isi=f"Admin menyetujui {_kg(kg)} ke {lok} — tinggal dimuat",
            keadaan="menunggu dikirim Gudang 1",
            aksi="kirim_permintaan_pk", nilai=str(baris.id), fase="pindah_pk",
            sejak=baris.waktu_setuju or baris.waktu_minta,
            judul="Kirim PK ke Gudang 2",
            utama=(_kg(kg).removesuffix(" kg"), "kg"),
            sub=f"{kode_lot} · tujuan {lok}",
            kelompok="permintaan",
            nota="Catat yang BENAR-BENAR dimuat. Boleh kurang dari yang "
                 "disetujui; lebih tidak.",
            pilihan=[("kirim_permintaan_pk", "Kirim ke Gudang 2",
                      "Barangnya berpindah sekarang juga", str(baris.id))]))
    # Perintah muat yang memuat PK MENTAH mendarat di sini: PK berdiri di
    # Gudang 1, dan yang mengangkatnya operator selepan. Perintah berisi barang
    # jadi saja tak pernah sampai ke layar ini — `gudang_perintah` menghitungnya
    # dari barangnya, bukan dari siapa yang memerintah.
    b.menunggu += await _kartu_barang_keluar(db, gudang="g1")
    # Pintu "Stok Produk" tak ditawarkan kepada operator selepan — lihat
    # catatan di `Berjalan.lencana()`.
    b.pintu_produk = False
    return _cap_gudang(b, "g1")


#: Di mana gabahnya BERADA saat harganya masih ditagih. Fase inilah yang
#: mewarnai kartu dan mengisi kepingannya — dan sebelum ini tak pernah
#: disetel sama sekali, jadi terpakai bawaannya, "Belum ada tindakan". Itu
#: bohong: gabahnya bisa sudah dua hari di dalam mesin pengering. Kepingan
#: yang berbohong lebih buruk daripada kepingan yang tak ada, karena ia
#: dipercaya.
_FASE_BATCH = {
    "baru": "baru", "ditumpuk": "tumpuk",
    "di_dryer": "dryer", "dikeringkan": "dryer",
    "di_silo": "silo", "digiling": "giling",
}

_DI_MANA = {
    "baru": "belum ditempatkan", "ditumpuk": "menumpuk di lantai",
    "di_dryer": "sudah di mesin pengering", "dikeringkan": "sedang dikeringkan",
    "di_silo": "sudah di silo", "digiling": "sudah digiling",
}


async def untuk_gudang2(db: AsyncSession) -> Berjalan:
    """Pekerjaan Gudang 2: PK yang datang dari luar, dan penyosohan.

    Sampai sekarang seluruh alur ini hanya bisa dijangkau lewat katalog
    "Catat pekerjaan lain" — daftar kata kerja yang harus dibaca operator
    untuk menemukan satu, persis keadaan yang sudah dibuang dari Gudang 1.
    Operator Gudang 2 tak punya satu pun kartu, jadi tak ada satu layar pun
    yang menyebut PK yang sedang menunggu ditempatkan atau penyosohan yang
    sedang berputar.

    Bendanya sama dengan Gudang 1 — barang yang ADA di gudang — jadi
    golongannya pun mengikuti aturan yang sama: yang belum punya tempat
    masuk `menunggu`, yang mesinnya menyala `berjalan`, yang sudah bertempat
    tetapi diam `transit`, dan yang menunggu keputusan `meja`.
    """
    from app.penggilingan.gudang2.models import (
        PkPurchaseBatch, PkPurchaseVerification, PolishingProcess)
    from app.models import Silo
    from app.penggilingan.gudang2.service import (
        _g2_warehouse_id, hitung_stok_silo)
    from app.services.setelan import fitur_mutu

    b = Berjalan()

    # Kartu silo dan kartu penyosohan menanyakan silo yang SAMA. Tanpa ini
    # asal-usulnya dikueri dua kali per silo — dan seluruh fungsi ini ikut
    # jalan tiap kali lencana laci dihitung, yaitu di tiap halaman.
    memo: dict[int, IsianSilo] = {}

    async def asal_silo(silo_id: int) -> IsianSilo:
        if silo_id not in memo:
            memo[silo_id] = await _isian_silo(db, silo_id)
        return memo[silo_id]

    # ── Tiket timbang PK yang belum dicatat ──
    #
    # Barisnya lahir SEBELUM batch-nya ada: truknya sudah ditimbang dan pergi,
    # PK-nya di halaman, dan belum ada satu catatan pun yang menyebutnya. Tanpa
    # baris ini antrean melompati langkah pertama dan baru menyebut PK sesudah
    # seseorang sempat mencatatnya — padahal justru pencatatan itu yang
    # terlewat. (Keluhan pemilik 23 Sep 2026; lihat `_tiket_pk_luar`.)
    b.menunggu += await _tiket_pk_luar(db, boleh_catat=True)
    b.menunggu += await _tiket_jenis_tak_dikenal(
        db, jenis_diizinkan={"BERAS_MASUK", "BROKEN_MASUK"})

    # ── PK luar yang sudah diterima tetapi belum masuk silo/tumpukan ──
    #
    # "Diterima" bukan "sudah punya tempat": PK yang masuk PASTI diterima,
    # dan penempatannya langkah tersendiri. Yang menandai belum bertempat
    # adalah tak adanya baris `pk_gudang2_intakes` — patokan yang sama dengan
    # yang dipakai daftar pilihan aksinya sendiri, supaya kartu dan lembarnya
    # tak pernah berbeda isi.
    from app.models import PkGudang2Intake

    belum_masuk = ~exists().where(
        PkGudang2Intake.pk_purchase_batch_id == PkPurchaseBatch.id)
    pk_baru = (await db.execute(
        select(PkPurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
        .where(PkPurchaseBatch.status_batch == "diterima", belum_masuk)
        .order_by(PkPurchaseBatch.id.desc())
    )).all()
    tiket_pk = await _metadata_tiket(
        db, (pk.timbangan_transaksi_id for pk, _ in pk_baru))
    for pk, nama in pk_baru:
        tiket = tiket_pk.get(pk.timbangan_transaksi_id or -1, {})
        b.menunggu.append(Baris(
            kode=pk.kode_batch, isi=f"PK luar · {dari_batch(pk).teks()}",
            aksi="masukkan_pk", nilai=pk.kode_batch, fase="baru",
            sejak=pk.created_at,
            judul=nama or pk.kode_batch,
            utama=_utama(dari_batch(pk)),
            sub=f"{pk.kode_batch} · PK luar · masuk {_tgl(pk.tanggal_pembelian)}",
            keadaan="belum masuk tumpukan",
            pilihan=[("masukkan_pk", "Masukkan ke gudang",
                      "Langsung ke tumpukan — pindah ke silo belakangan", pk.kode_batch)],
            tiket_kode=tiket.get("kode"),
            komoditas=(tiket.get("jenis_nama") or
                       (f"PK luar · {pk.jenis_pk}" if pk.jenis_pk else "PK luar")),
            kendaraan=" · ".join(x for
                                  x in (pk.no_polisi_truk or tiket.get("nomor_polisi"),
                                        tiket.get("nama_sopir")) if x),
            status_jasa=pk.jasa_id is not None,
            nama_tabel=_nama_tabel_bahan(
                nama or pk.kode_batch, jasa=pk.jasa_id is not None),
        ))

    # ── Penyosohan yang sedang berputar ──
    b.berjalan += await _kartu_penyosohan_g2(db, asal_silo)

    # ── Silo Gudang 2 berisi PK, menunggu disosoh ──
    b.transit += await _kartu_silo_g2(db, asal_silo)

    # ── Beras yang sudah keluar mesin tetapi belum dipacking ──
    #
    # Admin ikut melihatnya: ia yang membaca angka stok Gudang 2, dan sampai 26
    # September 2026 angka itu menyebut NOL sepanjang jam-jam antara sosoh
    # selesai dan packing dicatat.
    curah = await _kartu_beras_curah(db)
    b.menunggu += curah
    b.jumlah_produk = len(curah)

    # ── Kerja meja: MUTU PK luar ──
    #
    # Harga keluar dari Pos Produksi 28 September 2026 (keputusan pemilik), dan
    # kartu "Verifikasi harga PK luar" ikut dibuang. Yang tersisa mutunya —
    # dan potongan bobotnya, yang pindah ke borang QC sebab ia satu-satunya
    # penulis potongan yang tersisa. Lihat `api.act_qc_pk_luar`.
    sudah_qc = set((await db.execute(
        select(PkPurchaseVerification.pk_purchase_batch_id)
        .where(PkPurchaseVerification.kadar_air.is_not(None))
    )).scalars().all())
    baris_pk_luar = (await db.execute(
        select(PkPurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
        # Ditolak = sudah kembali ke truknya, tak pernah diterima — menagih
        # mutunya cuma mengundang orang men-QC barang yang sudah tak ada
        # (keputusan pemilik 4 Oktober 2026, sejak status ini dipakai
        # sungguhan oleh `create_pk_rejection_dari_timbang`).
        .where(PkPurchaseBatch.status_batch != "ditolak")
        .order_by(PkPurchaseBatch.id.desc())
    )).all() if await fitur_mutu(db) else []
    # PK luar TITIPAN tak punya pemasok — sub-baris ini jatuh ke "?" tanpa
    # pemiliknya diikutkan (laporan lapangan 12 Oktober 2026, sama dengan
    # `_isian_silo`).
    peta_pemilik_qc = await nama_pemilik_banyak(
        db, {pk.jasa_id for pk, _ in baris_pk_luar if pk.jasa_id})
    for pk, nama in baris_pk_luar:
        if pk.id in sudah_qc:
            continue
        pemilik = (peta_pemilik_qc[pk.jasa_id]
                  if pk.jasa_id and pk.jasa_id in peta_pemilik_qc else (nama or "?"))
        b.meja.append(Baris(
            kode=pk.kode_batch, isi="mutu PK luar belum dicatat",
            keadaan="", aksi="qc_pk_luar", nilai=pk.kode_batch, fase="silo_g2",
            sejak=pk.created_at,
            judul="Mutu PK luar belum dicatat",
            sub=f"{pk.kode_batch} · {pemilik} · "
                f"masuk {_tgl(pk.tanggal_pembelian)}",
            pilihan=[("qc_pk_luar", "Catat kualitas PK luar",
                      "Kadar air & butir patah", pk.kode_batch)],
        ))
    return _cap_gudang(b, "g2")


async def _kartu_penyosohan_g2(db: AsyncSession, asal_silo) -> list[Baris]:
    """Kartu penyosohan yang sedang berputar — berikut keadaan BERHENTI-nya.

    Sejak 12 September 2026 penyosohan pun bisa dijeda (keputusan pemilik).
    Bentuk kartunya mengikuti kartu giling: yang dijeda berganti judul,
    membawa nota "hati" berisi sebab & lamanya, dan pilihan pertamanya
    Lanjutkan. Kartu berhenti yang tampil sama dengan kartu berjalan akan
    dilewati sama.
    """
    from app.models import Silo
    from app.penggilingan.gudang1.services.jeda import jeda_terbuka, tertahan_detik
    from app.penggilingan.gudang2.models import (PolishingOutputLog,
                                                 PolishingProcess,
                                                 PolishingSiloUsage)

    keluar: list[Baris] = []
    for pr in (await db.execute(
        select(PolishingProcess).where(PolishingProcess.status == "proses")
        .order_by(PolishingProcess.id.desc())
    )).scalars().all():
        # Dari silo mana ia makan — dan lewat silo itu, dari lot giling mana.
        # Inilah satu-satunya tempat beras putih masih bisa disambungkan ke
        # gabahnya; sesudah proses ditutup, yang tersisa cuma angka hasil.
        asal_pr: list[tuple[str, str, str]] = []
        rinci_bahan: list[tuple[str, str, str, str]] = []
        komposisi_total = {k: 0.0 for k in (
            "pk", "beras_putih", "broken", "menir", "reject", "belum_dikenal")}
        # ── Baris yang tak ikut terbawa, bahkan sebelum digabung ──
        #
        # `asal_silo()` sendiri sudah membatasi `BATAS_ASAL` baris PER SILO
        # (dengan `.lebih` menghitung sisanya) — benar untuk kartu silo
        # TUNGGAL, tetapi kartu ini menggabung BEBERAPA silo sekaligus
        # ("Silo B + Silo A"). Tanpa menjumlah `.lebih` di sini, baris yang
        # sudah terpangkas di dalam `asal_silo()` lenyap tanpa jejak sama
        # sekali — tak ada yang menyebutnya, beda dari kartu silo tunggal
        # yang menyebutnya lewat `_nota_isian`.
        asal_lebih = 0
        silo_nama: list[str] = []
        ditambah = 0.0
        for u in (await db.execute(
            select(PolishingSiloUsage)
            .where(PolishingSiloUsage.polishing_process_id == pr.id)
        )).scalars().all():
            awal_u = float(u.berat_awal_kg or 0)
            masuk_u = float(u.berat_masuk_kg or 0)
            ditambah += masuk_u
            s = await db.get(Silo, u.silo_id)
            if s:
                silo_nama.append(s.nama_silo)
                total_u = awal_u + masuk_u
                sisa_u = (float(u.berat_akhir_kg)
                          if u.berat_akhir_kg is not None else None)
                dibebaskan = sisa_u is not None
                # Status silo dibuat eksplisit di halaman detil: status proses
                # keseluruhan bisa tetap berjalan meski salah satu silo sudah
                # ditutup dan boleh dipakai kembali. Jangan biarkan baris aktif
                # hanya menampilkan label generik "Total isi silo".
                status_u = (
                    "Dilepaskan · kosong, siap diisi" if dibebaskan and sisa_u <= 0.01
                    else f"Dilepaskan · sisa {_kg(sisa_u)}" if dibebaskan
                    else "Aktif · masih dipakai proses"
                )
                from app.penggilingan.gudang2.service import komposisi_bahan_silo
                komposisi = await komposisi_bahan_silo(
                    db, u.silo_id,
                    sampai=(u.updated_at if dibebaskan else now_local()),
                    kecuali_proses_id=pr.id, target_kg=total_u,
                )
                for jenis, kg in komposisi.items():
                    komposisi_total[jenis] = komposisi_total.get(jenis, 0.0) + kg
                label_bahan = {
                    "pk": "PK", "beras_putih": "Beras putih",
                    "broken": "Broken", "menir": "Menir",
                    "reject": "Reject",
                    "belum_dikenal": "Belum teridentifikasi",
                }
                rinci_bahan.append((s.nama_silo, _kg(total_u), status_u,
                                    "dibebaskan" if dibebaskan else "silo"))
                for jenis, judul in label_bahan.items():
                    kg = komposisi.get(jenis, 0.0)
                    if kg > 0.001:
                        rinci_bahan.append((judul, _kg(kg), "", "sosoh-bahan"))
                # Asal lot hanya ditelusuri untuk PK. Beras putih dan hasil
                # samping tetap ditampilkan sebagai jumlah komposisi per silo.
                peran_lot = "lot-dibebaskan" if dibebaskan else "lot"
                if komposisi.get("pk", 0) > 0.001:
                    isian_u = await _isian_silo(
                        db, u.silo_id, sampai=now_local()
                    )
                    asal_lebih += isian_u.lebih
                    rinci_bahan.extend(
                        (nama, kg, jam, peran_lot) for nama, kg, jam in isian_u.baris
                    )
                    if not isian_u.baris:
                        rinci_bahan.append((
                            "Asal lot tidak tercatat", "", "", peran_lot
                        ))
                    for a in isian_u.baris:
                        if a not in asal_pr:
                            asal_pr.append(a)
        pemasok_pr = _pemasok_ringkas(asal_pr)
        macet = await jeda_terbuka(db, "penyosohan", pr.id)
        tertahan = await tertahan_detik(db, "penyosohan", pr.id)
        fakta = [("Silo", " + ".join(silo_nama) or "—")]
        bahan_kg = sum(komposisi_total.values())
        for jenis, judul in (
            ("pk", "Total PK"), ("beras_putih", "Total bahan beras putih"),
            ("broken", "Total bahan broken"), ("menir", "Total bahan menir"),
            ("reject", "Total bahan reject"),
        ):
            fakta.append((judul, _kg(komposisi_total.get(jenis, 0.0))))
        if komposisi_total.get("belum_dikenal", 0.0) > 0.01:
            fakta.append(("Bahan belum teridentifikasi",
                          _kg(komposisi_total["belum_dikenal"])))
        if ditambah > 0.001:
            fakta.append(("Ditambah saat proses", _kg(ditambah)))
        if tertahan >= 60:
            fakta.append(("Tertahan", f"{tertahan / 3600:.1f} jam"))

        # ── Hasil yang sudah tercatat, per jenis, DAN entrinya satu per satu ──
        #
        # Sejak 28 September 2026 tiap entri berdiri sendiri (permintaan
        # operator: tiap ganti spek punya hasilnya sendiri). Yang hilang
        # bersama kumulatif adalah kemampuan MEMBACA ULANG apa yang sudah
        # diketik — dengan kumulatif, angka di layar adalah totalnya.
        #
        # Entrinya dirinci di bagian kartu yang dibuka. Ringkasan kartu tidak
        # mengulang angka hasil: operator dapat memeriksa setiap catatan dari
        # bagian "Hasil sosoh keluar" saat membuka proses.
        entri = list((await db.execute(
            select(PolishingOutputLog)
            .where(PolishingOutputLog.polishing_process_id == pr.id)
            .order_by(PolishingOutputLog.waktu_update.desc(),
                      PolishingOutputLog.id.desc())
        )).scalars().all())
        # Dihitung TANPA SYARAT (dulu hanya `if entri:`) — neraca di bawah
        # butuh peta ini juga saat belum ada satu entri pun (bahan sudah
        # berdiri, hasil belum dicatat), bukan cuma saat merangkai fakta
        # "Hasil".
        per_jenis: dict[str, float] = {}
        spek_per_jenis: dict[str, set[str]] = {}
        for e in entri:
            # Kanonisasi untuk data warisan: label jenis lama bisa berbeda
            # kapitalisasi/spasi, tetapi harus tetap menjadi satu total.
            jenis = str(e.jenis or "").strip().lower()
            if not jenis:
                continue
            per_jenis[jenis] = per_jenis.get(jenis, 0.0) + float(e.berat_kg or 0)
            if e.spek:
                spek_per_jenis.setdefault(jenis, set()).add(e.spek.strip())
        # ── Neraca LIVE — pesan kerja 7 Oktober 2026: "progress bar seperti
        # yang di kartu riwayat proses" ──
        #
        # SATU fungsi dengan kartu Riwayat Penyosohan (`neraca_sosoh`,
        # dipakai `riwayat_sosoh.html`) — angka yang menilai pekerjaan tak
        # boleh dihitung dua cara. Bedanya cuma penanda: proses ini BELUM
        # selesai, jadi "susut" di sini sebagian besar cuma "belum keluar
        # mesin", bukan kehilangan sungguhan — macro-nya (`_benda.html`)
        # WAJIB menyebut "sementara", sama seperti `beras_curah()` menyebut
        # "belum final" untuk alasan yang sama.
        from app.penggilingan.gudang2.polishing import GRADES, neraca_sosoh
        neraca = neraca_sosoh(bahan_kg, per_jenis) if bahan_kg > 0.5 else None
        # Satu baris kumulatif per jenis pada kartu; log tiap prosesan tetap
        # tersimpan sendiri untuk jejak audit dan pembatalan.
        #
        # Beras SELALU di atas, hasil samping SELALU di bawah (permintaan
        # pemilik 11 Oktober 2026) — bukan cuma alfabetis, yang menyelipkan
        # "bekatul" di antara "beras_b" dan "medium". Peran keempatnya
        # mewarnai nama baris beda warna per kategori (`.anak__baris--beras`
        # / `--samping`), sebangun `--fase-giling`/`--fase-samping` yang
        # sudah dipakai membedakan warna kartu Hasil vs hasil samping.
        rinci_hasil = [
            (jenis + (f" · {', '.join(sorted(spek_per_jenis.get(jenis, set())))}"
                      if spek_per_jenis.get(jenis) else ""),
             _kg(berat), "", "beras" if jenis in GRADES else "samping")
            for jenis, berat in sorted(
                per_jenis.items(),
                key=lambda kv: (0 if kv[0] in GRADES else 1, kv[0]),
            )
        ]

        # ── Bahan per silo dan hasil keluar ──
        # Asal lot sudah ditempatkan langsung di bawah silo PK masing-masing;
        # silo broken tetap menjadi baris terakhir tanpa daftar asal lot.
        anak_grup = [("Bahan baku masuk per silo", rinci_bahan)]
        if rinci_hasil:
            anak_grup.append(("Hasil sosoh keluar", rinci_hasil))

        _anak_penuh = rinci_bahan + rinci_hasil
        anak = _anak_penuh
        # Seluruh rincian yang tersedia ditampilkan; hanya asal silo yang
        # memang melewati BATAS_ASAL yang dilaporkan sebagai baris tersembunyi.
        anak_lebih = asal_lebih
        anak_grup_tampil = anak_grup

        keluar.append(Baris(
            kode=pr.kode_proses,
            isi=(f"⏸ berhenti — {macet.sebab}" if macet else "sedang disosoh"),
            keadaan=("menunggu dilanjutkan" if macet
                     else "catat hasil, tutup bila selesai"),
            aksi=("lanjutkan_penyosohan" if macet else "hasil_penyosohan"),
            nilai=(f"penyosohan:{pr.kode_proses}" if macet else pr.kode_proses),
            fase="sosoh",
            sejak=pr.waktu_mulai,
            judul=("Penyosohan dijeda" if macet else "Penyosohan"),
            # Angka utama adalah seluruh bahan yang sedang berada di silo
            # proses ini, termasuk PK, beras putih, hasil samping, dan bahan
            # yang belum teridentifikasi. Angka tunggal ini jadi ringkasan
            # kartu; rincian per jenis tetap ada di halaman detail.
            utama=(_kg(bahan_kg).removesuffix(" kg"), "kg"),
            sub=(f"{pr.kode_proses} · {pemasok_pr}" if pemasok_pr
                 else f"{pr.kode_proses} · mesin sosoh menyala"),
            fakta=fakta,
            neraca=neraca,
            # Entri hasil MENDAHULUI asal PK-nya: yang dicari orang saat kartu
            # ini dibuka adalah "apa yang sudah saya catat", bukan "dari mana
            # PK-nya" — asalnya sudah disebut fakta Silo di atas.
            anak=anak,
            anak_grup=anak_grup_tampil,
            # Dijeda menang bila keduanya ada: mesin berhenti lebih penting
            # diketahui daripada daftar yang terpotong. Di luar itu, baris
            # yang tak tampil WAJIB disebut — kalimat sama bentuknya dengan
            # `_nota_isian`, supaya tak ada dua cara menyebut hal yang sama.
            nota=(f"Dijeda {lama_kata((now_local() - macet.mulai).total_seconds())} — "
                  f"{macet.sebab}" if macet
                  else (f"+{anak_lebih} baris lagi tak ditampilkan" if anak_lebih else None)),
            nota_jenis="hati" if macet else None,
            ringkas=(f"⏸ {macet.sebab}"
                     + (f" · tertahan {tertahan / 3600:.1f} jam" if tertahan >= 60 else "")
                     if macet else
                     (f"menyosoh PK {pemasok_pr}" if pemasok_pr else "mesin sosoh menyala")),
            pilihan=([
                ("lanjutkan_penyosohan", "Lanjutkan penyosohan",
                 "Mesin jalan lagi — bisa nanti, bisa besok",
                 f"penyosohan:{pr.kode_proses}"),
                ("tambah_silo_penyosohan", "Tambah silo (mix bahan)",
                 "Silo yang dibebaskan boleh ditambahkan kembali", pr.kode_proses),
                ("selesai_penyosohan", "Selesai penyosohan",
                 "Tutup proses, per silo", pr.kode_proses),
            ] if macet else [
                ("hasil_penyosohan", "Perbarui hasil penyosohan",
                 "Beras putih, menir, bekatul — kumulatif", pr.kode_proses),
                # Mix bahan — laporan lapangan 7 Oktober 2026: silo lain
                # dipakai di tengah proses, bukan cuma saat mulai.
                ("tambah_silo_penyosohan", "Tambah silo (mix bahan)",
                 "Silo yang dibebaskan boleh ditambahkan kembali — harus sepemilik", pr.kode_proses),
                ("hentikan_penyosohan", "Hentikan sementara",
                 "Mesin rusak, listrik padam, jam kerja habis",
                 f"penyosohan:{pr.kode_proses}"),
                ("selesai_penyosohan", "Selesai penyosohan",
                 "Tutup proses, per silo", pr.kode_proses),
            ]),
        ))
    return keluar


async def _kartu_silo_g2(db: AsyncSession, asal_silo) -> list[Baris]:
    """Silo Gudang 2 yang berisi PK — menunggu disosoh."""
    from app.models import Silo
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.penggilingan.gudang2.service import _g2_warehouse_id, hitung_stok_silo

    from app.penggilingan.gudang2.models import PolishingSiloUsage

    keluar: list[Baris] = []
    # ── Silo MANA yang sedang di dalam mesin, bukan sekadar "ada yang jalan" ──
    #
    # Sampai 24 September 2026 yang dibaca di sini cuma satu bendera global:
    # "adakah penyosohan berstatus proses?". Tombolnya dicabut untuk SEMUA silo,
    # tetapi kartunya tetap dipancarkan — termasuk untuk silo yang justru sedang
    # berada di dalam mesin itu. Akibatnya PK yang sama tergambar DUA KALI
    # dengan dua cerita yang bertentangan: Antrian tunggu bilang "menunggu
    # disosoh", Sedang berjalan bilang "sedang disosoh". Laporan pemilik 24
    # September 13:57, dan aturan app ini sendiri sudah menamainya: "kartu yang
    # sama di dua tempat adalah dua tempat di kepala orang, dan cepat atau
    # lambat keduanya berbeda isi" — di sini keduanya SUDAH berbeda isi.
    #
    # HIMPUNAN, bukan satu nilai: satu proses boleh memakai DUA silo sekaligus
    # ("Mulai penyosohan" menerima A / B / AB).
    #
    # DAN "di dalam mesin" bukan sama dengan "dipakai proses yang berjalan".
    # Silo yang sisanya SUDAH dicatat (`berat_akhir_kg` terisi) sudah keluar
    # dari mesin, sementara prosesnya masih berputar atas silo satunya. Sampai
    # temuan QA 24 September ia ikut disembunyikan: operator menutup Silo A
    # dengan sisa 500 kg, dan 500 kg itu LENYAP dari antreannya — berdiri di
    # silo, tak tersebut di layar mana pun, sampai penyosohan Silo B ditutup
    # juga. Yang hilang dari layar adalah yang tak dikerjakan siapa pun.
    baris_pakai = (await db.execute(
        select(PolishingSiloUsage.silo_id, PolishingSiloUsage.berat_akhir_kg)
        .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
        .where(PolishingProcess.status == "proses")
    )).all()
    dipakai = {sid for sid, akhir in baris_pakai if akhir is None}
    #: Sisanya sudah dicatat, mesinnya masih memakai silo lain — berkartu,
    #: tanpa tombol, dan keterangannya menyebut keadaan itu apa adanya.
    sisa_dicatat = {sid for sid, akhir in baris_pakai if akhir is not None} - dipakai
    # Bendera global TETAP dipakai, dan di sini ia masih benar: mesinnya satu,
    # jadi silo LAIN memang belum bisa dimulai selama ada yang jalan.
    # Kode prosesnya ikut diambil, bukan cuma "ada atau tidak": kartu silo yang
    # kehilangan tombolnya WAJIB menyebut apa yang memakainya. Sejak 28
    # September 2026 pintu katalognya pun dicabut (satu pekerjaan, satu pintu),
    # jadi ini satu-satunya tempat orang bisa membaca sebabnya — dan kartu
    # tanpa tombol tanpa keterangan dibaca sebagai app yang rusak.
    kode_jalan = (await db.execute(
        select(PolishingProcess.kode_proses)
        .where(PolishingProcess.status == "proses")
        .order_by(PolishingProcess.id.desc())
    )).scalars().first()
    sedang = bool(dipakai) or bool(kode_jalan)
    wid2 = await _g2_warehouse_id(db)
    for silo in (await db.execute(
        select(Silo).where(Silo.warehouse_id == wid2, Silo.aktif.is_(True)).order_by(Silo.nama_silo)
    )).scalars().all():
        kg = await hitung_stok_silo(db, silo.id)
        if not kg:
            continue
        # Silo yang sedang DI DALAM mesin tak punya kartu antrean sama sekali.
        # Ia sudah punya wakilnya di Sedang berjalan — kartu Penyosohan, yang
        # menyebutkan silonya. Kartu kedua untuk barang yang sama itulah yang
        # melahirkan keluhan pemilik.
        #
        # STOKNYA TIDAK BERUBAH: `hitung_stok_silo` tetap menghitung PK ini
        # sebagai isi silo sampai prosesnya ditutup dan sisanya dicatat —
        # barangnya memang masih di sana. Yang berubah cuma ANTREAN.
        if silo.id in dipakai:
            continue
        huruf = silo.nama_silo.replace("Silo ", "")
        isian = await asal_silo(silo.id)
        asal = isian.baris
        pemasok = _pemasok_ringkas(asal)
        keluar.append(Baris(
            kode=silo.nama_silo, isi=f"Bahan campuran · {_kg(kg)}",
            # Tiga keadaan, tiga kalimat. Silo yang sisanya sudah dicatat
            # BUKAN silo yang sedang menunggu mesin: yang membacanya perlu tahu
            # bahwa angka ini sisa isian yang baru saja ditutup, bukan muatan
            # yang belum tersentuh.
            keadaan=("sisanya sudah dicatat · mesin masih memakai silo lain"
                     if silo.id in sisa_dicatat
                     else (f"mesin sosoh sedang dipakai {kode_jalan}"
                           if kode_jalan else "mesin sosoh sedang dipakai")
                     if sedang
                     else "mulai penyosohan bila siap"),
            aksi=None if sedang else "mulai_penyosohan",
            nilai=huruf, fase="silo_g2",
            judul=f"{silo.nama_silo} · Gudang 2",
            utama=(_kg(kg).removesuffix(" kg"), "kg"),
            # Kalimat bawahnya ikut menyebutnya: "menunggu disosoh" atas sisa
            # 500 kg yang baru ditutup terbaca seperti muatan penuh yang belum
            # tersentuh, dan operator yang membacanya akan mencari 500 kg yang
            # ia kira baru masuk.
            sub=((("sisa isian yang sudah ditutup · menunggu giliran berikutnya"
                   if silo.id in sisa_dicatat else "PK menunggu disosoh"))
                 + (f" · {pemasok}" if pemasok else "")),
            anak=asal,
            # ── Selisih dalam isian ini, dengan NAMA ──
            # Judul kartu = isi SEKARANG; daftar di bawahnya = yang masuk pada
            # isian yang sedang berjalan. Keduanya benar dan berbeda, dan tanpa
            # baris ini pemilik membacanya sebagai rincian yang tak menjumlah
            # (laporan 23 Sep 21:18). Selisih nol tak perlu kalimat — kalimat
            # yang selalu muncul berhenti dibaca.
            # Kalimat yang menjelaskan KENAPA tombolnya tak ada, dan ia
            # mendahului catatan selisih: yang membaca kartu tanpa tombol
            # mencari sebabnya lebih dulu. Sesudah pintu katalognya dicabut
            # (28 September 2026), tak ada tempat lain untuk membacanya.
            nota=(f"Mesin sosoh sedang dipakai {kode_jalan} — silo ini "
                  "menunggu giliran."
                  if sedang and kode_jalan and silo.id not in sisa_dicatat
                  else _nota_isian(isian)),
            ringkas=(f"Bahan dari {pemasok}"
                     if pemasok else "Bahan menunggu disosoh"),
            pilihan=([] if sedang else [
                ("mulai_penyosohan", "Mulai penyosohan",
                 "Seluruh isi silo jadi satu proses", huruf)]),
        ))
    return keluar


async def _kartu_tumpukan_g2(db: AsyncSession) -> list[Baris]:
    """PK di tumpukan Gudang 2, satu kartu per intake yang masih bersisa.

    Inilah antrean operator Gudang 2 (keputusan pemilik 12 September 2026):
    memindahkan PK dari lantai ke silo adalah tugas operator, boleh sebagian,
    dan sisanya tetap berdiri sebagai kartu yang sama dengan sisa terbaru.
    Silo yang sedang dipoles pun boleh menerima, jadi kartunya selalu bisa
    ditekan.
    """
    from app.models import InternalTransfer, PkGudang2Intake
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import _sisa_tumpukan_intake

    keluar: list[Baris] = []
    for it in (await db.execute(
        select(PkGudang2Intake).where(PkGudang2Intake.tujuan == "ditumpuk")
        .order_by(PkGudang2Intake.id)
    )).scalars().all():
        sisa = await _sisa_tumpukan_intake(db, it.id)
        if sisa is not None and sisa <= 0:
            continue
        if it.pk_purchase_batch_id:
            pk, nama = (await db.execute(
                select(PkPurchaseBatch, Supplier.nama_supplier)
                .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
                .where(PkPurchaseBatch.id == it.pk_purchase_batch_id)
            )).first() or (None, None)
            kode = pk.kode_batch if pk else f"intake {it.id}"
            judul, sumber = (nama or kode), "PK luar"
        else:
            kode_lot = (await db.execute(
                select(MillingProcess.kode_proses)
                .join(InternalTransfer, InternalTransfer.milling_process_id == MillingProcess.id)
                .where(InternalTransfer.id == it.internal_transfer_id)
            )).scalar() if it.internal_transfer_id else None
            kode = kode_lot or f"intake {it.id}"
            judul, sumber = kode, "giling sendiri"
        # `_kg_tepat`, BUKAN `_kg`: angka ini diketik ulang operator sebagai
        # batas, dan pembulatan ke atas membuat layar menawarkan satu kilogram
        # yang tak ada lalu menolaknya.
        keluar.append(Baris(
            kode=kode,
            isi=f"PK di tumpukan · {_kg_tepat(sisa) if sisa is not None else 'menunggu timbang'}",
            keadaan="menunggu dipindah ke silo — boleh sebagian",
            aksi="pindah_tumpukan_silo", nilai=str(it.id), fase="tumpuk",
            sejak=it.waktu_masuk, judul=judul, kelompok="tumpukan",
            utama=((_kg_tepat(sisa).removesuffix(" kg"), "kg")
                   if sisa is not None else None),
            sub=f"{kode} · {sumber} · masuk {_tgl(it.tanggal_masuk)}",
            pilihan=[("pindah_tumpukan_silo", "Pindah ke silo",
                      "Sebagian atau seluruhnya, pilih silo tujuan", str(it.id))],
        ))
    return keluar


async def _kartu_beras_curah(db: AsyncSession) -> list[Baris]:
    """Beras yang sudah keluar mesin sosoh tetapi belum dipacking.

    Halaman yang harus dibuka sendiri tak menjawab keluhan pemilik: yang
    hilang selama ini KABARNYA, bukan tempat menyimpannya. Berton-ton beras
    berdiri di lantai sementara tak satu pun layar menyebutnya, dan
    notifikasi penutupan penyosohan menjanjikan "perlu verifikasi output"
    tanpa ada satu tombol pun yang menawarkannya. Temuan QA 26 September 2026.

    Yang MASIH BERJALAN tidak berkartu: angkanya belum final, dan kartu
    antrean yang menagih pekerjaan atas angka yang masih akan berubah membuat
    orang mengemas dua kali. Ia tetap terbaca di halaman Stok Produk, dengan
    keterangan yang menyebut keadaannya.

    ⚠ Titipan pelanggan TAK DISEMBUNYIKAN, tapi KALIMATNYA BERBEDA — pola yang
    sama dengan kartu tumpukan gabah. Keluhan pemilik 6 Oktober 2026: di
    halaman "Tunggu packing" tak bisa dibedakan mana jasa mana yang bukan.
    `grup_baris()` menjatuhkannya ke grup "Packing jasa" sendiri (lihat
    `jasa_id` di `Baris`), dan `sub`-nya menyebut pemiliknya terang-terangan
    (`· TITIPAN <nama>`, pola yang sama dengan picker `/pk-g1-tersedia`) —
    sebab satu grup bisa saja berisi lebih dari satu pelanggan sekaligus.
    """
    from app.services.stok import adalah_beras, beras_curah, nama_produk

    daftar = [b for b in await beras_curah(db, termasuk_berjalan=False)
              if b.sisa_kg > 0]            # minus = pertanyaan, bukan pekerjaan
    nama = await nama_pemilik_banyak(db, {b.jasa_id for b in daftar if b.jasa_id})

    keluar: list[Baris] = []
    for b in daftar:
        # ⚠ Judul & warna dulu SELALU "Beras" / hijau sosoh, berapa pun
        # `b.jenis`-nya — keluhan pemilik 6 Oktober 2026: kartu bekatul dan
        # menir pun terbaca "Beras menunggu dipacking", membingungkan.
        # `nama_produk()` sudah ada untuk ini (dipakai Stok Produk); `fase`
        # di sini bukan tahap proses (semuanya sudah sosoh selesai) melainkan
        # KELAS BARANG — sama seperti `--fase-samping` di app.css: beras
        # tetap hijau ("sosoh"), hasil samping (bekatul/menir/broken/reject)
        # ungu.
        nm = nama_produk(b.jenis)
        keluar.append(Baris(
            kode=b.kode_proses,
            isi=f"{nm} · {_kg(b.sisa_kg)} belum dikemas",
            keadaan="menunggu dipacking",
            # Penunjuknya membawa LOT dan JENIS sekaligus (28 September
            # 2026). Dengan kode proses saja, jenisnya hilang di perjalanan dan
            # borang menanyakannya lagi — padahal kartu ini yang menyebutnya.
            aksi="catat_packing", nilai=f"{b.kode_proses}|{b.jenis}",
            fase=("sosoh" if adalah_beras(b.jenis) else "samping"),
            sejak=b.selesai,
            judul=f"{nm} menunggu dipacking",
            utama=(_kg(b.sisa_kg).removesuffix(" kg"), "kg"),
            sub=f"{b.kode_proses} · {nm}"
                + (f" · dari {_kg(b.keluar_kg)}" if b.dikemas_kg else "")
                + (f" · TITIPAN {nama.get(b.jasa_id, '?')}" if b.jasa_id else ""),
            kelompok="produk", gudang="g2", jasa_id=b.jasa_id,
            pilihan=[("catat_packing", "Catat packing barang jadi",
                      "Memindahkan dari curah ke barang jadi",
                      f"{b.kode_proses}|{b.jenis}")]
                     # ── Sisa dicurah — laporan lapangan 7 Oktober 2026 ──
                     #
                     # Tak seluruh hasil berakhir dikarungi; sebagian memang
                     # tetap dijual/disimpan curah. Sebelum ini kartu "Tunggu
                     # packing" hanya menawarkan SATU jalan (mengemas), jadi
                     # mencatat sisanya sebagai curah menuntut membuka
                     # katalog umum dan mengetik kode prosesnya sendiri —
                     # dua langkah untuk pekerjaan yang kartunya sendiri
                     # sudah tahu kode & jenisnya.
                     #
                     # ⚠ Hanya bekatul & broken: keduanya SATU-SATUNYA jenis
                     # yang punya jalan curah (`catat_bekatul`/`catat_broken`
                     # → `byproduct_stock`) — menir & reject tak punya
                     # (`stok.py`'s `curah_saja`). Menawarkan tombol yang
                     # pasti ditolak lebih buruk daripada tak menawarkannya.
                     + ([(("catat_bekatul" if b.jenis == "bekatul" else "catat_broken"),
                         "Sisa dicurah",
                         "Tidak dikemas — tetap dijual/disimpan curah",
                         b.kode_proses)] if b.jenis in ("bekatul", "broken") else [])))
    return keluar


async def _kartu_barang_keluar(db: AsyncSession, *, gudang: str,
                               untuk_admin: bool = False) -> list[Baris]:
    """Perintah muat yang menunggu tangan operator — atau verifikasi Admin.

    Sampai hari ini rantai barang keluar berjalan LEWAT KATALOG AKSI saja:
    operator harus membuka menu dan memilih "Muat semua sesuai perintah", dan
    perintah yang terbit pukul tujuh pagi baru dilihat pukul sebelas. Di
    seluruh app ini pekerjaan muncul SENDIRI sebagai kartu; barang keluar
    satu-satunya yang tidak — dan pekerjaan yang harus dicari adalah pekerjaan
    yang terlambat.

    `untuk_admin` memilih SISI MANA yang digambar, bukan sekadar menyaring:
      · False → perintah yang belum dimuat, untuk operator, di Antrian tunggu;
      · True  → muatan yang sudah berangkat, untuk Admin, di Menunggu keputusan.

    Satu fungsi untuk keduanya supaya kalimat dan urutannya tak bisa berselisih
    — dua penyusun untuk satu rantai akan menyebut angka berbeda tentang truk
    yang sama.
    """
    from app.penggilingan.inventory.models import OUT_DIMUAT, OUT_PERINTAH
    from app.services import barang_keluar as bk

    keadaan = OUT_DIMUAT if untuk_admin else OUT_PERINTAH
    keluar: list[Baris] = []
    for rec, items in await bk.daftar(db, status=(keadaan,), batas=30):
        # Gudang mana yang harus melihatnya dihitung dari BARANGNYA, bukan
        # dipilih Admin: perintah yang mendarat di layar yang salah akan berdiri
        # di sana sampai seseorang menelepon. Kartu Admin tak disaring gudang —
        # ia melihat seluruhnya.
        if not untuk_admin and gudang not in bk.gudang_perintah(items):
            continue
        macam = len(items)
        perintah = sum(float(i.berat_perintah_kg or 0) for i in items)
        dimuat = sum(float(i.berat_kg or 0) for i in items)
        pembeli = rec.nama_pembeli or "—"
        truk = f" · {rec.no_polisi}" if rec.no_polisi else ""

        if untuk_admin:
            kurang = perintah - dimuat
            # Selisihnya di RINGKASAN, bukan di dalam laci: yang memilih dari
            # meja inilah yang memutuskan mana yang perlu diperiksa lebih dulu.
            ringkas = (f"kurang {_kg(kurang)} dari perintah"
                       if kurang > 0.5 else "sesuai perintah")
            keluar.append(Baris(
                kode=rec.kode,
                isi=f"{pembeli}{truk} · {macam} macam · {_kg(dimuat)} dimuat",
                keadaan="menunggu verifikasi Admin",
                aksi="verifikasi_keluar", nilai=str(rec.id), fase="keluar",
                sejak=rec.waktu_muat,
                judul="Muatan menunggu diverifikasi",
                utama=(_kg(dimuat).removesuffix(" kg"), "kg"),
                sub=f"{rec.kode} · {pembeli}{truk}",
                ringkas=ringkas,
                kelompok="keluar", gudang=gudang,
                nota="Tempelkan kode timbang keluarnya bila tiketnya sudah ada.",
                pilihan=[("verifikasi_keluar", "Verifikasi barang keluar",
                          "Tutup catatannya, tempelkan kode timbang",
                          str(rec.id))]))
            continue

        sudah = (f" · {_kg(dimuat)} sudah dicatat" if dimuat > 0.5 else "")
        keluar.append(Baris(
            kode=rec.kode,
            isi=f"{pembeli}{truk} · {macam} macam · {_kg(perintah)}{sudah}",
            keadaan="menunggu dimuat",
            # Penunjuknya id barisnya, dan borangnya terkunci dari kartu — yang
            # menekan kartu ini sudah memilih truknya, dan menanyakannya lagi
            # adalah kesempatan memilih yang salah.
            aksi="muat_semua", nilai=str(rec.id), fase="keluar",
            sejak=rec.waktu_perintah,
            judul="Muat barang keluar",
            utama=(_kg(perintah).removesuffix(" kg"), "kg"),
            sub=f"{rec.kode} · {pembeli}{truk}",
            ringkas=rec.catatan_perintah or None,
            kelompok="keluar", gudang=gudang,
            # TIGA pilihan, dan urutannya yang menentukan: "muat semua" paling
            # atas sebab ia keadaan yang paling sering, dan borang yang menuntut
            # operator mengetik ulang angka yang sudah tertulis di kartunya akan
            # diketik asal-asalan sambil berdiri di samping truk.
            pilihan=[
                ("muat_semua", "Muat semua sesuai perintah",
                 f"Seluruh {macam} macam, {_kg(perintah)}", str(rec.id)),
                ("muat_barang", "Catat muatan per barang",
                 "Untuk yang dimuat kurang dari perintahnya", None),
                ("selesai_muat", "Selesai muat — truk berangkat",
                 "Sisa yang tak dimuat hangus", str(rec.id)),
            ]))
    return keluar


async def untuk_operator_gudang2(db: AsyncSession) -> Berjalan:
    """Layar OPERATOR Gudang 2, menurut pemilik 12 September 2026:

      · `menunggu` = stok PK di silo Gudang 2 (→ mulai penyosohan);
      · `berjalan` = mesin yang menyala saja;
      · tidak ada kerja meja.

    ⚠ Sampai 4 Oktober 2026 `menunggu` JUGA memuat tumpukan (per intake →
    pindah ke silo). Keputusan pemilik 5 Oktober 2026 memindahkannya ke
    tombol "Masukkan ke silo" di kartu PK-nya sendiri di layar Stok
    (`stok.LotPkG2`): *"operator memilih bahan dari halaman stok untuk masuk
    ke silo. tidak perlu lagi dari antrian tunggu."* `_kartu_tumpukan_g2`
    TETAP hidup — ia yang memasok opsi picker `/actions/tumpukan-sisa`, baik
    dari tombol Stok maupun dari katalog "Catat pekerjaan lain" — hanya
    berhenti ditambahkan ke `b.menunggu` DI SINI.

    TRANSIT lahir 25 September 2026, dan cuma untuk satu hal: permintaan PK
    yang sedang dalam perjalanan dari Gudang 1. Keputusan 12 September yang
    mengosongkan Transit berbicara tentang STOK MILIKNYA SENDIRI — PK yang
    sudah di sini adalah antrean, bukan barang yang dipantau. Permintaan yang
    sedang berjalan bukan stoknya: ia belum ada di gudang ini.

    Yang menentukan tempat kartu permintaan bukan di mana barangnya berada,
    melainkan SIAPA yang memegang langkah berikutnya — dan sejak 27 September
    2026 TAK SATU PUN langkah sesudah "Minta" miliknya: Admin yang menyetujui,
    Gudang 1 yang mengirim ("gudang 1 yang mengirim", "jika sudah disetujui",
    "jadi gudang 1 mulai proses kirim" — pemilik), Admin lagi yang menutup.

    Jadi ketiga keadaannya berdiri di TRANSIT, tanpa tombol. Lencana antrean
    menagih pekerjaan, dan kartu yang tak bisa dikerjakan siapa pun di layar
    ini akan membuat lencananya tak pernah kembali nol — lencana yang tak
    pernah nol mengajari orang mengabaikan lencana.

    ⚠ Kartu `disetujui` sempat berdiri di ANTREAN dengan tombol "Muat & kirim"
    selama satu hari (26 September), ketika tangan yang memuat disangka Gudang
    2. Kalau kelak ada yang memindahkannya ke antrean lagi, yang pertama harus
    diperiksa adalah siapa yang mengangkat karungnya di lapangan — bukan enak
    atau tidaknya tata letak.

    ⚠ `untuk_gudang2` di bawah BUKAN kode mati. Kalimat di sini dulu berbunyi
    "berbeda dari `untuk_gudang2`, yang dipakai Meja", dan app Meja dihapus 24
    September 2026 — pembaca berikutnya yang membersihkan sisa-sisanya akan
    membaca kalimat itu sebagai penanda kode mati lalu menghapusnya, dan layar
    Gudang 2 milik Admin ikut mati bersamanya. Temuan QA 25 September.
    PEMAKAINYA SEKARANG, keduanya di Pos Produksi sendiri:
    `layar_gudang` (halaman /gudang/g2) dan `untuk_admin` (antrean gabungan).
    Bedanya tetap sama seperti dulu: di sana PK luar yang belum bertempat
    adalah antrean (entry Admin), dan silo berisi PK adalah transit yang
    dipantau.
    """
    memo: dict[int, IsianSilo] = {}

    async def asal_silo(silo_id: int) -> IsianSilo:
        if silo_id not in memo:
            memo[silo_id] = await _isian_silo(db, silo_id)
        return memo[silo_id]

    b = Berjalan()

    # ── Permintaan PK yang sedang dalam perjalanan ke sini ──
    #
    # Yang meminta menekan tombol lalu tak pernah diberi kabar lagi sampai
    # barangnya muncul — atau tidak muncul; itu bagian yang paling kurang dari
    # seluruh alur menurut pemilik (25 September 2026). Kalimat keadaan di
    # kartu Stok menjawab sebagian: ia terbaca saat orangnya kebetulan membuka
    # Stok dan kebetulan menyusuri lot yang ia minta. Kartu ini menjawab
    # sisanya — ia berdiri di layar yang sama tempat ia menunggu pekerjaan
    # berikutnya.
    #
    # TANPA TOMBOL, dan itu disengaja: tak satu pun langkah alur ini miliknya
    # sesudah menekan Minta (keputusan pemilik 27 September 2026 — Gudang 1
    # yang mengirim). Kartu bertombol yang ditekan lalu ditolak mengajari orang
    # bahwa layarnya tak bisa dipercaya.
    from app.models import PermintaanPk
    from app.services import permintaan_pk as _pmt
    from app.services.stok import _keadaan_minta

    for baris, kode_lot in (await db.execute(
        select(PermintaanPk, MillingProcess.kode_proses)
        .join(MillingProcess, MillingProcess.id == PermintaanPk.milling_process_id)
        .where(PermintaanPk.status.in_(_pmt.HIDUP))
        .order_by(PermintaanPk.waktu_minta)
    )).all():
        from app.penggilingan.gudang2.service import label_tujuan

        kg = float(baris.berat_kirim_kg or baris.berat_setuju_kg or 0)
        lok = (await label_tujuan(db, baris.tujuan, baris.silo_id)
               if baris.tujuan else "")


        b.transit.append(Baris(
            kode=kode_lot,
            isi=f"PK dari Gudang 1 · {_keadaan_minta(baris.status)}",
            keadaan=_keadaan_minta(baris.status),
            # `aksi` sengaja TIDAK disebut sama sekali, bukan disebut None:
            # baris yang membawa `aksi` wajib membawa `pilihan` juga (kartu
            # yang ditekan harus membentang, bukan melempar lembar), dan
            # kartu ini memang tak punya tindakan apa pun.
            fase="pindah_pk",
            sejak=baris.waktu_minta,
            judul="Permintaan PK Anda",
            utama=((_kg(kg).removesuffix(" kg"), "kg") if kg else None),
            sub=(f"{kode_lot}" + (f" · tujuan {lok}" if lok else "")),
            ringkas=_keadaan_minta(baris.status),
            # Yang sudah dikirim sudah BISA DIPAKAI — itu kabar, bukan sekadar
            # keadaan, dan ia yang menentukan apakah orangnya bisa mulai
            # menyosoh hari ini atau menunggu besok.
            nota=("Sudah ada di gudang ini — boleh langsung disosoh."
                  if baris.status == _pmt.DIKIRIM else None)))

    # ── Yang BERAKHIR TANPA BARANG: ditolak, atau gugur ──
    #
    # Dua keadaan yang kartunya lenyap begitu statusnya berubah, dan satu-satunya
    # di seluruh rantai yang tak punya jejak di layar mana pun (temuan QA 26
    # September 2026). Yang lain berkartu: `diminta` di meja Admin, `disetujui`
    # di antrean sini, `dikirim` di meja Admin lagi.
    #
    # Permintaan yang lenyap tanpa kabar membuat orangnya menekannya lagi besok,
    # dan Admin menolaknya lagi; keduanya mengira pihak satunya yang lalai. Itu
    # alasan yang sama yang membuat `sebab` diwajibkan pada `tolak()` — sebabnya
    # sudah tertulis sejak awal, yang belum ada cuma yang membacakannya.
    #
    # Di TRANSIT dan TANPA TOMBOL: tak ada yang bisa dikerjakan atas permintaan
    # yang sudah berakhir. Meminta lagi tetap bisa, dari kartu lotnya di layar
    # Stok — tempat yang sama dengan permintaan pertamanya, jadi tak ada pintu
    # kedua yang harus dihafal.
    for baris in await _pmt.baru_ditutup(db):
        kode_lot = (await db.execute(
            select(MillingProcess.kode_proses)
            .where(MillingProcess.id == baris.milling_process_id)
        )).scalar_one_or_none() or "lot"
        ditolak = baris.status == _pmt.DITOLAK
        b.transit.append(Baris(
            kode=kode_lot,
            isi=f"Permintaan {'ditolak Admin' if ditolak else 'gugur'} — "
                f"{baris.sebab or 'tanpa sebab tercatat'}",
            keadaan="ditolak Admin" if ditolak else "gugur sendiri",
            fase="pindah_pk",
            sejak=baris.waktu_tutup or baris.waktu_minta,
            judul=("Permintaan Anda ditolak" if ditolak
                   else "Permintaan Anda gugur"),
            sub=kode_lot,
            ringkas=baris.sebab or None,
            kelompok="permintaan", gudang="g2",
            nota="Masih perlu lot ini? Minta lagi dari kartunya di layar Stok."))

    # Tiket PK yang belum dicatat: kartu DIAM. Penempatan PK datang bukan tugas
    # operator (pemilik, 12 September 2026) dan itu tidak diubah — tapi
    # barangnya berdiri di halamannya, dan ia tak boleh jadi orang terakhir yang
    # tahu. Ia berdiri PALING ATAS di antreannya karena ia yang paling baru
    # turun dari truk.
    b.menunggu += await _tiket_pk_luar(db, boleh_catat=False)
    # `_kartu_tumpukan_g2` TIDAK lagi ditambahkan di sini sejak 5 Oktober 2026
    # — lihat catatan panjang di docstring fungsi ini. Fungsinya tetap dipakai
    # oleh picker `/actions/tumpukan-sisa`.
    b.menunggu += await _kartu_silo_g2(db, asal_silo)
    # Beras yang menunggu dipacking: pekerjaan yang sungguh menunggu orang ini,
    # jadi ia di ANTREAN — beda dengan permintaan PK di Transit, yang menunggu
    # tangan orang lain.
    curah = await _kartu_beras_curah(db)
    b.menunggu += curah
    b.jumlah_produk = len(curah)
    # Perintah muat: pekerjaan yang sungguh menunggu tangan orang ini, jadi ia
    # di ANTREAN. Sampai 29 September 2026 rantai barang keluar berjalan lewat
    # katalog aksi saja — perintah yang terbit pukul tujuh pagi baru dilihat
    # pukul sebelas, sebab tak ada satu kartu pun yang menyebutnya.
    b.menunggu += await _kartu_barang_keluar(db, gudang="g2")
    b.berjalan += await _kartu_penyosohan_g2(db, asal_silo)
    return _cap_gudang(b, "g2")


async def untuk_staff(db: AsyncSession) -> Berjalan:
    """Yang tertahan menunggu keputusan staff/Direksi — bukan pekerjaan fisik.

    Semuanya masuk `meja`. Barisnya menyebut DI MANA gabahnya sekarang,
    karena pertanyaan pertama yang timbul saat melihat kode batch lama adalah
    "ini yang mana, dan apa sudah dikerjakan?" — dan jawabannya tak boleh
    menuntut orang membuka layar lain.
    """
    from app.services.setelan import fitur_mutu

    # Sekali, di muka: kalau pabrik ini memang tak mencatat mutu, tak ada
    # gunanya menghitung berapa yang belum dicatat.
    mutu_aktif = await fitur_mutu(db)
    b = Berjalan(mutu_aktif=mutu_aktif)

    # QC gabah menjadi pekerjaan di meja Mutu & QC, sejajar dengan QC giling
    # dan PK luar. Satu kartu per truk membuka formulir untuk batch itu.
    if mutu_aktif:
        from app.models import PurchaseBatchQc, PurchaseBatchQcSample

        jumlah_qc = (select(func.count(PurchaseBatchQcSample.id))
                     .select_from(PurchaseBatchQcSample)
                     .join(PurchaseBatchQc, PurchaseBatchQc.id ==
                           PurchaseBatchQcSample.purchase_batch_qc_id)
                     .where(PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
                     .correlate(PurchaseBatch).scalar_subquery())
        rows = (await db.execute(
            select(PurchaseBatch, Supplier.nama_supplier, jumlah_qc.label("jumlah_qc"))
            .join(Supplier, Supplier.id == PurchaseBatch.supplier_id, isouter=True)
            .join(PurchaseBatchQc, PurchaseBatchQc.purchase_batch_id ==
                  PurchaseBatch.id, isouter=True)
            .where(PurchaseBatch.dibatalkan_pada.is_(None),
                   PurchaseBatchQc.ditutup_pada.is_(None),
                   PurchaseBatch.kondisi_gabah.in_(("basah", "kering")), jumlah_qc < 5)
            .order_by(PurchaseBatch.id.desc())
        )).all()
        pemilik_qc = await nama_pemilik_banyak(
            db, {batch.jasa_id for batch, _, _ in rows if batch.jasa_id})
        for batch, pemasok, jumlah in rows:
            kondisi = batch.kondisi_gabah
            pemilik = (pemilik_qc.get(batch.jasa_id)
                       if batch.jasa_id else pemasok) or "?"
            berat = _kg(float(batch.berat_total_kg or 0)).removesuffix(" kg")
            if kondisi == "basah":
                b.meja.append(Baris(
                    kode=batch.kode_batch, isi=f"QC gabah basah · {jumlah}/5 pencatatan",
                    keadaan="", aksi="qc_gabah_basah", nilai=batch.kode_batch,
                    sejak=batch.created_at, fase="baru",
                    judul="Mutu gabah basah belum dicatat",
                    utama=(berat, "kg"),
                    sub=f"{batch.kode_batch} · {pemilik} · truk {batch.no_polisi_truk or 'tanpa plat'}",
                    pilihan=([("qc_gabah_basah", f"Catat QC ke-{jumlah + 1} dari 5",
                               "Satu pemeriksaan · dua pembacaan kadar air", batch.kode_batch)]
                             + ([ ("qc_gabah_tutup", "Tutup proses QC",
                                   f"Selesaikan sekarang dengan {jumlah} pencatatan", batch.kode_batch)]
                                if jumlah else [])),
                ))
            else:
                b.meja.append(Baris(
                    kode=batch.kode_batch, isi=f"QC gabah kering · {jumlah}/5 pencatatan",
                    keadaan="", aksi="qc_gabah_kering", nilai=batch.kode_batch,
                    sejak=batch.created_at, fase="baru",
                    judul="Mutu gabah kering belum dicatat",
                    utama=(berat, "kg"),
                    sub=f"{batch.kode_batch} · {pemilik} · truk {batch.no_polisi_truk or 'tanpa plat'}",
                    pilihan=([("qc_gabah_kering", f"Catat QC ke-{jumlah + 1} dari 5",
                               "Satu pemeriksaan · dua pembacaan kadar air", batch.kode_batch)]
                             + ([ ("qc_gabah_tutup", "Tutup proses QC",
                                   f"Selesaikan sekarang dengan {jumlah} pencatatan", batch.kode_batch)]
                                if jumlah else [])),
                ))

    # Tiket berjenis tak dikenal — satu-satunya baris FISIK di fungsi ini, dan
    # ia di sini karena jalan keluarnya memang kerja meja: memetakan jenisnya,
    # atau membatalkan tiketnya di Pos Timbang. Ia masuk `menunggu`, bukan
    # `meja`: yang tertahan bukan keputusan uang melainkan barang yang berdiri
    # di halaman tanpa satu catatan pun.
    b.menunggu += await _tiket_jenis_tak_dikenal(db)

    # Kartu "Harga gabah belum diverifikasi" DIBUANG 28 September 2026:
    # harga keluar dari Pos Produksi (keputusan pemilik). `flag_unverified`
    # sendiri TIDAK ikut dibuang — ia kolom peninggalan yang masih dibaca
    # penjaga bobot di `timbang_link`, dan barisnya tetap berdiri untuk
    # keuangan. Yang berhenti cuma menagihnya di layar.

    from app.models import MillingProcessSource
    from app.penggilingan.gudang1.services.drying import _lot_batches

    selesai = (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "selesai")
        .order_by(MillingProcess.id.desc())
    )).scalars().all()
    for p in selesai:
        sumber = (await db.execute(
            select(MillingProcessSource.purchase_batch_id,
                   MillingProcessSource.drying_lot_id)
            .where(MillingProcessSource.milling_process_id == p.id))).all()
        bid = [x[0] for x in sumber if x[0]]
        for _, lid in sumber:
            if lid:
                bid += [x.id for x in await _lot_batches(db, lid)]
        asal = await _asal(db, set(bid))
        ada_qc = (await db.execute(
            select(func.count()).select_from(MillingQcLog)
            .where(MillingQcLog.milling_process_id == p.id)
        )).scalar_one() if mutu_aktif else 1
        if not ada_qc:
            b.meja.append(Baris(
                kode=p.kode_proses, isi="giling selesai, mutu belum diperiksa",
                keadaan="", aksi="qc_giling", nilai=p.kode_proses,
                sejak=p.waktu_selesai, fase="giling",
                judul="Mutu belum diperiksa",
                sub=f"{p.kode_proses} · giling sudah ditutup"
                    + (f" · {_pemasok_ringkas(asal)}" if asal else ""),
                anak=asal,
                pilihan=[("qc_giling", "Catat hasil QC",
                          "Kadar air, butir patah, susut")]))
        # Kartu "Output belum diverifikasi" DIHAPUS 24 September 2026, keputusan
        # pemilik: "yang mencatat hasil giling hanya operator. jika ada
        # kesalahan sudah ada di perbaiki hasil giling."
        #
        # Yang ditagihnya adalah pencocokan ulang oleh admin atas angka yang
        # SUDAH dicatat orang yang berdiri di mesinnya. Tagihan semacam itu
        # tumbuh satu baris tiap giling ditutup, dan yang tumbuh tiap hari
        # tanpa pernah habis mengajari orang mengabaikan daftarnya.
        #
        # Aksinya sendiri TIDAK dihapus: `verify_output` tetap jadi tombol
        # "Perbaiki hasil giling" di kartu layar Stok — di situlah angkanya
        # dibaca, dan di situ pula ia dibetulkan bila keliru. Dan angka operator
        # kini dipakai apa adanya oleh stok, HPP, dan rendemen (lihat
        # `milling._produced_pk` dan `transfer.hpp_per_kg_pk`), bukan menunggu
        # disahkan lebih dulu.

    # ── Giling selesai yang bobot masuknya tak cocok dengan bahannya ──
    #
    # Korban lama P6-03 (truk ditimbang SESUDAH giling ditutup, sebelum
    # perbaikan) atau tiket yang direvisi sengaja — dari data keduanya sama.
    # Ditaruh di meja karena memang keputusan manusia: yang korban
    # dibetulkan, yang revisi sengaja dibiarkan (rekonsiliasi butir ⑪).
    from app.penggilingan.gudang1.services.koreksi_bobot import giling_tak_cocok
    for x in await giling_tak_cocok(db):
        b.meja.append(Baris(
            kode=x["kode_proses"],
            isi=f"bobot masuk tercatat {_kg(x['tercatat_kg'])}, bahannya kini "
                f"{_kg(x['seharusnya_kg'])} ({float(x['kurang_persen'] or 0):+.1f}%)",
            keadaan="", aksi="betulkan_bobot_giling", nilai=x["kode_proses"],
            sejak=x.get("mulai"), fase="giling",
            judul="Bobot masuk giling tak cocok",
            sub=f"{x['kode_proses']} · giling sudah ditutup",
            nota="Korban P6-03 atau tiket yang direvisi sengaja? Betulkan hanya "
                 "bila truknya memang ditimbang sesudah giling ditutup.",
            pilihan=[("betulkan_bobot_giling", "Betulkan bobot masuk",
                      "Disamakan dengan bobot bahan, rendemen dihitung ulang")]))

    # ── Lot PK yang DIMINTA operator Gudang 2 ──
    #
    # Keputusan pemilik 24 September 2026: operator polesan melihat lot PK
    # Gudang 1 dan boleh MEMINTA satu dipindah.
    #
    # Kartunya pindah dari `menunggu` ke `MEJA` pada 26 September 2026,
    # permintaan pemilik: "di view admin buat saja block paling atas di
    # menunggu keputusan yang berisi kartu lot yang diminta oleh gudang 2".
    # Dan itu memang tempatnya sejak alurnya jadi empat langkah: yang ditunggu
    # bukan pekerjaan fisik melainkan KEPUTUSAN — disetujui berapa, ke mana,
    # atau ditolak dengan sebabnya. Judul bloknya di `services.keputusan.JENIS`,
    # paling atas, sebab permintaan yang menggantung menahan gudang sebelah.
    #
    # Yang sudah tak bisa dikerjakan digugurkan lebih dulu (lotnya habis lewat
    # jalan lain), supaya kartunya hilang di pemuatan yang SAMA dengan
    # sebabnya — bukan satu putaran poller kemudian.
    from app.services import permintaan_pk as _pmt

    from app.penggilingan.gudang1.services.milling import _pk_breakdown

    await _pmt.gugurkan_yang_habis(db)
    # DUA keadaan berhenti di meja Admin, dan keduanya menunggu tangan yang
    # sama: yang baru diminta (perlu diputuskan) dan yang sudah dikirim Gudang
    # 1 (perlu ditutup). Yang di antaranya — `disetujui` — ada di tangan
    # Gudang 1, dan menampilkannya di sini hanya akan membuat Admin menunggui
    # pekerjaan yang bukan miliknya.
    for baris, nama_minta, kode_lot in (await db.execute(
        select(PermintaanPk, User.nama, MillingProcess.kode_proses)
        .join(User, User.id == PermintaanPk.diminta_oleh)
        .join(MillingProcess, MillingProcess.id == PermintaanPk.milling_process_id)
        .where(PermintaanPk.status.in_((_pmt.DIMINTA, _pmt.DIKIRIM)))
        .order_by(PermintaanPk.waktu_minta)
    )).all():
        bd = await _pk_breakdown(db, baris.milling_process_id)
        dikirim = baris.status == _pmt.DIKIRIM
        if dikirim:
            from app.penggilingan.gudang2.service import label_tujuan

            lok = await label_tujuan(db, baris.tujuan, baris.silo_id)
            kg_kirim = float(baris.berat_kirim_kg or 0)
            b.meja.append(Baris(
                kode=kode_lot,
                isi=f"Gudang 1 sudah mengirim {_kg(kg_kirim)} ke {lok}",
                keadaan="menunggu ditutup Admin",
                aksi="tutup_permintaan_pk", nilai=str(baris.id), fase="pindah_pk",
                sejak=baris.waktu_kirim or baris.waktu_minta,
                judul="Kiriman PK menunggu ditutup",
                utama=(_kg(kg_kirim).removesuffix(" kg"), "kg"),
                sub=f"{kode_lot} · diminta {nama_minta or '?'} · {lok}",
                kelompok="permintaan", gudang="g1",
                # Barangnya SUDAH pindah. Yang tersisa mengakui angkanya — dan
                # angka Admin yang berlaku, jadi kartunya harus mengatakan itu
                # sebelum ditekan, bukan sesudah.
                nota=(f"Disetujui {_kg(float(baris.berat_setuju_kg or 0))}, "
                      f"dimuat {_kg(kg_kirim)}. Angka Anda yang berlaku; bila "
                      "berbeda, perpindahannya ikut dibetulkan."),
                pilihan=[("tutup_permintaan_pk", "Tutup permintaan",
                          "Boleh mengubah bobotnya", str(baris.id))]))
            continue
        # ── ANGKA BESARNYA = YANG DIMINTA, bukan sisa lot ──
        #
        # Temuan QA 28 September 2026: kartu ini dulu memajang sisa lot sebagai
        # angka besarnya dan tak menyebut berapa yang diminta sama sekali —
        # sebab permintaannya memang belum membawa angka. Admin menebak batas
        # atas muatan, atau bertanya lewat WhatsApp.
        #
        # Yang diputuskan Admin di kartu ini "berapa yang disetujui", jadi
        # angka yang dibacanya lebih dulu harus angka yang sedang diminta.
        # Sisa lot tetap disebut — ia batasnya — tetapi sebagai keterangan,
        # bukan sebagai judul.
        kg_minta = float(baris.berat_minta_kg or 0)
        b.meja.append(Baris(
            kode=kode_lot,
            isi=(f"{nama_minta or 'Operator Gudang 2'} minta "
                 + (f"{_kg(kg_minta)} dari lot ini" if kg_minta
                    else "lot ini dipindah")),
            keadaan="menunggu keputusan Anda",
            aksi="acc_permintaan_pk", nilai=str(baris.id), fase="pindah_pk",
            sejak=baris.waktu_minta,
            judul="Diminta Gudang 2",
            utama=((_kg(kg_minta) if kg_minta else _kg(bd.tersedia))
                   .removesuffix(" kg"), "kg"),
            sub=f"{kode_lot} · diminta {nama_minta or '?'}",
            # Batasnya disebut apa adanya. Permintaan lama (sebelum 28
            # September) tak punya angka; kartunya kembali ke bentuk lama
            # dengan sendirinya, tanpa mengarang angka yang tak pernah ada.
            nota=(f"Lot ini tersisa {_kg(bd.tersedia)}." if kg_minta else None),
            kelompok="permintaan",
            # Dicap DI SINI, bukan oleh `_cap_gudang`: `untuk_staff` tak
            # memanggilnya (kartunya lintas gudang). Kartu tanpa cap lenyap
            # dari ?gudang=g1 DAN ?gudang=g2 sekaligus — invarian "Semua ==
            # g1 + g2" patah, dan patahnya tak terlihat sampai seseorang
            # menekan pilnya. Barangnya di Gudang 1 dan yang dikerjakan orang
            # atasnya adalah memindahkan dari sana; sama dengan `transfer_pk`.
            gudang="g1",
            pilihan=[
                # ACC, bukan "pindahkan": yang memuat kini Gudang 1. Yang
                # ditetapkan di sini tujuan dan bobotnya — dua hal yang cuma
                # Admin tahu, dan yang tak boleh ditebak orang yang sedang
                # berdiri di samping tumpukan.
                ("acc_permintaan_pk", "Setujui permintaan",
                 "Tetapkan tujuan & bobot; Gudang 1 yang memuat", str(baris.id)),
                ("tolak_permintaan_pk", "Tolak permintaan",
                 "Sebabnya ikut terkirim ke operator", str(baris.id)),
            ]))

    # ── Muatan yang sudah berangkat, menunggu verifikasi ──
    #
    # Ia di MEJA, bukan di antrean: barangnya sudah di atas truk dan tak ada
    # yang perlu diangkat lagi. Yang tertahan keputusan — apakah angkanya
    # diakui apa adanya, dan tiket timbang mana yang ditempelkan.
    #
    # Dicap "g2" dengan alasan yang sama dengan kartu di atas: `untuk_staff`
    # tak memanggil `_cap_gudang`, dan kartu tanpa cap lenyap dari kedua pilnya
    # sekaligus. Barang jadi berdiri di Gudang 2 dan dari sanalah ia berangkat.
    b.meja += await _kartu_barang_keluar(db, gudang="g2", untuk_admin=True)

    # ── Tiket timbang KELUAR yang belum tertaut transaksi mana pun ──
    #
    # DITAHAN dari tampilan (keputusan pemilik 6 Oktober 2026): kartunya
    # belum punya tombol atau tindak lanjut yang berguna — lihat "DIAM, tanpa
    # tombol" di docstring `_kartu_tiket_keluar_menganggur` — jadi untuk
    # sekarang ia cuma menagih tanpa menawarkan jalan keluar. Fungsinya
    # TETAP ADA, tak dihapus, untuk disambung lagi begitu ada tindak lanjutnya
    # (lihat juga `_kode`/`auto_tautkan` di `barang_keluar.py`, yang sudah
    # menautkan tiket seperti ini secara otomatis — mungkin kartu ini
    # akhirnya cuma perlu menyebut yang auto-taut TAK bisa selesaikan).
    #
    # b.meja += await _kartu_tiket_keluar_menganggur(db)
    return b


async def _kartu_tiket_keluar_menganggur(db: AsyncSession) -> list[Baris]:
    """Tiket timbang keluar yang tak tertaut transaksi barang keluar mana pun.

    Umurnya dibatasi: tiket hari ini wajar belum tertaut — truknya baru saja
    keluar dan Admin belum sampai ke mejanya. Yang sudah lewat sehari itulah
    yang benar-benar terlewat, dan kartu yang menagih pekerjaan yang belum
    waktunya akan diabaikan bersama yang sungguhan.
    """
    from app.database import now_local
    from app.penggilingan.gudang1.services.timbang_link import tiket_keluar_aktif

    batas = now_local().date()
    keluar: list[Baris] = []
    for t in await tiket_keluar_aktif(db):
        tgl = t.get("tanggal")
        if tgl is not None and tgl >= batas:
            continue                     # hari ini — belum terlambat
        berat = float(t.get("berat_kg") or 0)
        nama = t.get("jenis_nama") or t.get("kategori") or t.get("jenis_kode") or "?"
        keluar.append(Baris(
            kode=t["kode"],
            isi=f"{nama} · {_kg(berat)} · {t.get('pihak') or '?'}",
            keadaan="belum tertaut transaksi barang keluar",
            fase="keluar", sejak=t.get("timbang1_waktu"),
            judul="Tiket timbang keluar terlewat",
            utama=(_kg(berat).removesuffix(" kg"), "kg"),
            sub=f"{t['kode']} · {nama}",
            kelompok="keluar", gudang="g2",
            nota="Tautkan lewat kartu verifikasi muatannya. Kalau tiket ini "
                 "memang tak berpasangan, batalkan di Pos Timbang."))
    return keluar


async def untuk(db: AsyncSession, user: User) -> Berjalan:
    """Gabungkan sesuai peran — server yang memutuskan, bukan layar."""
    from app.peran import can_see_financials

    from app.web.api import _is_g1_operator, _is_g2_operator

    b = Berjalan()
    # Boleh mencatat mutu = boleh melihat uang (admin ke atas). Dihitung sekali:
    # kartu giling yang sama disusun lewat dua cabang di bawah.
    boleh_qc = can_see_financials(user)
    if await _is_g1_operator(user):
        g = await untuk_gudang1(db, boleh_qc=boleh_qc)
        b.menunggu += g.menunggu
        b.berjalan += g.berjalan
        # Transit ikut. Sebelumnya tidak, dan akibatnya blok Transit di layar
        # Sedang berjalan selalu kosong: gabah yang menunggu di dryer dan silo
        # dikeluarkan dari antrean tanpa pernah sampai ke tempat barunya —
        # hilang dari kedua layar sekaligus.
        b.transit += g.transit
    if can_see_financials(user):
        s = await untuk_staff(db)
        # Pencatatan mutu bisa dimatikan seluruhnya di Pengaturan. Yang membaca
        # setelannya `untuk_staff`; benderanya ikut ke sini supaya laci tak
        # menawarkan pintu "Mutu & QC" yang isinya pasti kosong.
        b.mutu_aktif = s.mutu_aktif
        b.meja += s.meja
        b.berjalan += s.berjalan
        # `menunggu` ikut sejak 24 September 2026: `untuk_staff` kini juga
        # memancarkan tiket berjenis tak dikenal, dan daftar yang tak diambil
        # adalah daftar yang tak pernah tergambar.
        b.menunggu += s.menunggu
        # Staff & Direksi tak terikat satu gudang; keadaan fisik G1 tetap
        # perlu terlihat, tetapi sebagai kabar — bukan sebagai tugas mereka.
        if not await _is_g1_operator(user):
            g1 = await untuk_gudang1(db, boleh_qc=boleh_qc)
            b.berjalan += g1.berjalan
            b.transit += g1.transit
    # Gudang 2 tak lagi "menyusul": PK luar dan penyosohan punya kartunya
    # sendiri sekarang. Admin ke atas ikut melihatnya — mereka memegang kedua
    # gudang, dan pekerjaan yang tak terlihat oleh siapa pun akan terlewat.
    if can_see_financials(user):
        g2 = await untuk_gudang2(db)
        b.menunggu += g2.menunggu
        b.berjalan += g2.berjalan
        b.transit += g2.transit
        b.meja += g2.meja
        b.jumlah_produk = g2.jumlah_produk
    elif await _is_g2_operator(user):
        # Operator Gudang 2 melihat layarnya sendiri: antrean = stok PK di
        # silo, berjalan = mesin. Tumpukan pindah ke tombol di kartu Stok
        # sejak 5 Oktober 2026 (lihat `untuk_operator_gudang2`). Penempatan
        # PK datang bukan tugasnya (keputusan pemilik 12 September 2026).
        g2 = await untuk_operator_gudang2(db)
        b.menunggu += g2.menunggu
        b.berjalan += g2.berjalan
        b.transit += g2.transit
        b.jumlah_produk = g2.jumlah_produk

    # ── Pintu "Stok Produk": semua, KECUALI operator Gudang 1 ──
    #
    # Keputusan pemilik 26 September 2026. Ditetapkan DI SINI, bukan diwarisi
    # dari daftar yang digabung di atas: `untuk()` menyusun `Berjalan` baru dan
    # hanya menyalin daftarnya, jadi bendera yang dipasang `untuk_gudang1`
    # tak pernah sampai — dan Admin, yang daftar Gudang 1-nya ikut digabung,
    # justru akan kehilangan pintunya.
    b.pintu_produk = not (await _is_g1_operator(user)
                          and not can_see_financials(user))

    # ── Dropdown "Riwayat Proses": per gudang yang SEDANG dikerjakan ──
    #
    # Pola sama `pintu_produk` di atas — dihitung di sini, bukan diwarisi,
    # sebab `_is_g1_operator`/`_is_g2_operator` memeriksa gudang yang SEDANG
    # dikerjakan, dan operator yang berpindah gudang harus langsung melihat
    # dropdown yang sesuai pada permintaan BERIKUTNYA, bukan menunggu bendera
    # lama. Admin/Superadmin: keduanya `True` (`admin_keatas` di masing-masing
    # fungsi) — mereka memegang kedua gudang.
    b.boleh_riwayat_sosoh = await _is_g2_operator(user)
    b.boleh_riwayat_g1 = await _is_g1_operator(user)

    # ── Lencana Kabar ──
    #
    # DI SINI, bersama lencana yang lain, dan bukan di layar Kabar: laci itu
    # satu benda di seluruh aplikasi, dan gunanya justru terlihat dari layar
    # LAIN. Lencana yang cuma muncul di halamannya sendiri tak memberi tahu
    # siapa pun bahwa ada yang perlu dibuka.
    #
    # Kegagalannya tak boleh menjatuhkan seluruh laci: kabar adalah tambahan,
    # sedangkan antrean dan keputusan adalah pekerjaan. Yang gagal dihitung
    # digambar nol — lencana yang hilang lebih baik daripada halaman yang mati.
    try:
        from app.services import kabar as _kabar
        b.jumlah_kabar = await _kabar.jumlah_baru(db, user)
        if b.jumlah_kabar:
            b.kabar_merah = await _kabar.ada_merah(db, user)
    except Exception:
        import logging
        logging.getLogger("berjalan").exception(
            "Lencana Kabar gagal dihitung (laci tetap tampil)")
    return b
