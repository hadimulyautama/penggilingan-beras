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
from datetime import date, datetime, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.services import keputusan as K
from app.penggilingan.gudang1.services.bobot import (
    Bobot, dari_batch, dari_batches, dari_nilai)
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

    @property
    def jumlah_menunggu(self) -> int:
        """Lencana antrean. Kerja meja TIDAK ikut — ia punya layar & lencana
        sendiri, dan menghitungnya di sini membuat lencana antrean menagih
        pekerjaan yang tak ada di dalamnya."""
        return len(self.menunggu)

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
        # Operator selepan tak ditawari pintu Stok Produk: beras dan hasil
        # samping lahir di Gudang 2, dan produknya sendiri (PK) sudah berkartu
        # di layar Stok. Pintu yang selalu kosong mengajari orang berhenti
        # membuka pintu. Batas ini SEMENTARA dan pemilik yang memutuskan
        # kelak: "Stok Produk" yang tak memuat PK akan terasa setengah, sebab
        # PK adalah produk Gudang 1 (catatan QA 26 September 2026).
        if not self.pintu_produk:
            mati.append("stok_produk")
        return {"MENUNGGU": self.jumlah_menunggu, "BERJALAN": self.jumlah_berjalan,
                "KEPUTUSAN": self.jumlah_keputusan, "MUTU": self.jumlah_mutu,
                "PRODUK": self.jumlah_produk,
                "MUTU_AKTIF": self.mutu_aktif, "PINTU_MATI": tuple(mati)}


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


def _utama(bb: Bobot) -> tuple[str, str] | None:
    """Angka besar kartu dari sebuah Bobot — None bila belum ada angkanya.
    Tak pernah "0": angka nol untuk bobot yang belum diketahui itulah yang
    membuat semua orang mengira datanya salah (QA P6)."""
    t = bb.angka_teks()
    return (t, "kg") if t is not None else None


def _jam(detik: float) -> str:
    """Lama tertahan dalam kata. Nol pun disebut — "baru saja" memberi tahu
    bahwa jamnya memang dihitung, bukan bahwa ia tak diketahui."""
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
               PurchaseBatch.sumber_berat, PurchaseBatch.berat_perkiraan_kg)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id, isouter=True)
        .where(PurchaseBatch.id.in_(list(batch_ids)))
        .order_by(PurchaseBatch.id)
    )).all()
    return [(f"{nama or '?'} · {kode}", dari_nilai(kg, sumber, perk).teks(), f"masuk {_tgl(tgl)}")
            for kode, kg, tgl, nama, sumber, perk in baris]


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


async def _isian_silo(db: AsyncSession, silo_id: int) -> IsianSilo:
    """Asal-usul PK yang SEDANG ada di sebuah silo Gudang 2.

    Aturan pemilik berlaku sama di sini: tiap kartu menyebut asal barangnya.
    Bedanya PK punya dua asal. Yang buatan sendiri lahir dari satu lot giling
    (LOT-…), dan lot itulah satu-satunya benang yang menyambungkan beras putih
    di ujung sana kembali ke gabah dan pemasoknya. Yang beli luar membawa
    pemasoknya sendiri (PKB-…).

    Yang disebut adalah apa yang masuk pada ISIAN YANG SEDANG BERJALAN —
    pemasukan sesudah terakhir kali silo ini mencapai nol — berapa dan kapan,
    bukan berapa yang masih tersisa dari masing-masing. Stok silo disimpan
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
        .where(PkTumpukanToSilo.silo_id == silo_id)
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
               PolishingSiloUsage.berat_akhir_kg.isnot(None))
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

    lot = dict((await db.execute(
        select(InternalTransfer.id, MillingProcess.kode_proses)
        .join(MillingProcess, MillingProcess.id == InternalTransfer.milling_process_id)
        .where(InternalTransfer.id.in_([m[2] for m in masuk if m[2]]))
    )).all()) if any(m[2] for m in masuk) else {}
    luar = {b: (kode, nama) for b, kode, nama in (await db.execute(
        select(PkPurchaseBatch.id, PkPurchaseBatch.kode_batch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
        .where(PkPurchaseBatch.id.in_([m[3] for m in masuk if m[3]]))
    )).all()} if any(m[3] for m in masuk) else {}

    keluar = []
    for tgl, kg, trf_id, batch_id in sorted(masuk, key=lambda m: (m[0] or date.min), reverse=True):
        if trf_id and trf_id in lot:
            judul = f"Giling sendiri · {lot[trf_id]}"
        elif batch_id and batch_id in luar:
            kode, nama = luar[batch_id]
            judul = f"{nama or '?'} · {kode}"
        else:
            continue
        keluar.append((judul, _kg(kg), f"masuk {_tgl(tgl)}"))
    return IsianSilo(baris=keluar[:BATAS_ASAL], lebih=max(0, len(keluar) - BATAS_ASAL),
                     masuk_kg=masuk_kg, disosoh_kg=disosoh_kg)


async def _asal_pk(db: AsyncSession, silo_id: int) -> list[tuple[str, str, str]]:
    """Baris asal saja, untuk pemakai yang tak butuh ringkasan selisihnya."""
    return (await _isian_silo(db, silo_id)).baris


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


async def _tujuan_gabah(db: AsyncSession, kondisi: str, *,
                        post: str, data: dict) -> list[Tombol]:
    """Tujuan yang sah untuk gabah sekondisi ini — mesinnya disebut satu per satu.

    Alasan sebuah tujuan dimatikan diambil dari ATURAN YANG SAMA yang menolak
    di server (`masuk_dryer`): mesin tak aktif, mesin masih dipakai lot, dan
    isinya beda kondisi. Kalau alasannya disusun ulang di sini, cepat atau
    lambat layar melarang yang sebenarnya boleh — atau lebih buruk,
    mempersilakan yang akan ditolak.

    Kapasitas sengaja TIDAK diperiksa di sini: ia bergantung pada total muatan
    dan pesan penolakannya sudah menyebut sisanya dengan tepat. Menebaknya di
    layar hanya menambah tempat yang bisa salah.
    """
    from app.penggilingan.gudang1.services.drying import (
        active_drying_lot, dryers_g1, isi_dryer)
    from app.penggilingan.peta_jenis import intake_dari_jenis

    jenis = "GABAH_BASAH" if kondisi == "basah" else "GABAH_KERING"
    info = intake_dari_jenis(jenis)
    sah = info.tujuan_pilihan if info else ()
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
            keluar.append(Tombol(
                nama=f"Ke {si.nama_silo}", post=post,
                ket=("Silo kosong" if not kg
                     else f"Bergabung dengan {_kg(kg)} gabah kering"),
                data=dict(data, tujuan=f"silo:{si.id}"),
                utama=(kondisi == "kering" and len(silo) == 1)))

    if "tumpuk" in sah:
        keluar.append(Tombol(
            nama="Ditumpuk di lantai", ket="Tempatnya ditentukan menyusul",
            post=post, data=dict(data, tujuan="tumpuk")))
    return keluar


async def _tiket_belum_ditaut(db: AsyncSession) -> list[Baris]:
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif
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
        nama = t.get("nama_supplier") or t.get("pihak_nama") or "?"
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
            tombol=await _tujuan_gabah(
                db, kondisi, post="/api/actions/gabah-masuk",
                data={"timbangan_transaksi_id": t["id"]}),
        ))
    return baris


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
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif
    from app.penggilingan.peta_jenis import is_pk

    baris = []
    for t in await tiket_masuk_aktif(db):
        if not is_pk(t.get("jenis_kode", "")):
            continue
        nama = t.get("nama_supplier") or t.get("pihak_nama") or "?"
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
        ))
    return baris


async def _tiket_jenis_tak_dikenal(db: AsyncSession) -> list[Baris]:
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

    Bukan kekeliruan yang akan habis sendiri: `peta_jenis.PETA_MASUK` memang
    belum memetakan BERAS_MASUK & BROKEN_MASUK (keputusan pemiliknya sudah ada —
    pembelian, tanpa antrean giling — tapi jalurnya belum dibangun), dan
    taksonomi jenis di Pos Timbang berbasis DATA: jenis baru bisa lahir di sana
    kapan saja tanpa produksi tahu. Jadi ini keadaan tetap yang harus terlihat,
    bukan galat sementara.

    TANPA tindakan: yang benar memang belum ada. Yang bisa dikerjakan orang ada
    di luar layar ini — memetakan jenisnya di produksi, atau membatalkan
    tiketnya di Pos Timbang.

    Admin ke atas saja. Operator tak punya jalan keluar untuk kartu ini:
    pemetaan jenis bukan wewenangnya, dan kartu yang tak bisa ia kerjakan
    maupun teruskan hanya menambah angka pada lencananya.
    """
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif
    from app.penggilingan.peta_jenis import intake_dari_jenis

    baris = []
    for t in await tiket_masuk_aktif(db):
        kode_jenis = t.get("jenis_kode") or "?"
        if intake_dari_jenis(kode_jenis) is not None:
            continue                       # dipetakan → sudah ada jalurnya
        nama = t.get("nama_supplier") or t.get("pihak_nama") or "?"
        bobot = t.get("berat_hpp_kg")
        # Nama jenisnya dari tabel jenis Pos Timbang bila ada; kodenya bila
        # tidak. Keduanya disebut: nama yang dibaca orang, kode yang dipakai
        # memetakannya nanti.
        jenis_nama = t.get("jenis_nama") or kode_jenis
        isi = f"{jenis_nama} · {nama} · {t.get('nomor_polisi') or '-'}"
        if bobot:
            isi += f" · {_kg(bobot)} ({_sumber_bobot(t)})"
        baris.append(Baris(
            kode=t["kode"], isi=isi,
            # Kepingan keadaan, bukan tombol: ia menerangkan kenapa kartu ini
            # tak bisa ditekan, di tempat orang mencari sebabnya.
            keadaan=f"jenis \u201c{kode_jenis}\u201d belum dikenal produksi",
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
    for b_, nama_pemasok in (await db.execute(
        select(PurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id, isouter=True)
        .where(PurchaseBatch.status_batch == "baru")
        .order_by(PurchaseBatch.id.desc())
    )).all():
        nama_pemasok = nama_pemasok or b_.kode_batch
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
                data={"kode_batch": b_.kode_batch}),
        ))

    # Tumpukan lebih dulu dari yang lain: isinya menandakan pembelian berlebih,
    # dan itu keadaan yang paling ingin diketahui — bukan yang paling dalam
    # daftar. Kosong berarti tak ada baris sama sekali, seperti seharusnya.
    from app.penggilingan.gudang1.services import tumpukan as tmp
    for b_ in await tmp.isi(db):
        wajib_dryer = b_.kondisi_gabah == "basah"
        nama_pemasok = (await db.execute(
            select(Supplier.nama_supplier).where(Supplier.id == b_.supplier_id)
        )).scalars().first() or b_.kode_batch
        b.menunggu.append(Baris(
            kode=b_.kode_batch,
            isi=f"menumpuk · {dari_batch(b_).teks()} · gabah {b_.kondisi_gabah}",
            keadaan=("harus ke dryer — belum kering" if wajib_dryer
                     else "tentukan tempatnya"),
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
                data={"kode_batch": b_.kode_batch}),
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
            nota=(f"Dijeda {_jam(tertahan)} — {macet.sebab}" if macet else None),
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
        select(Silo).where(Silo.warehouse_id == wid).order_by(Silo.nama_silo)
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
            nota=(f"Dijeda {_jam(tertahan)} — {macet.sebab}" if macet else None),
            nota_jenis="hati" if macet else None,
            ringkas=(f"⏸ {macet.sebab}"
                     + (f" · tertahan {tertahan / 3600:.1f} jam" if tertahan >= 60 else "")
                     if macet else f"{_kg(p.berat_gabah_masuk_kg)} bahan masuk"),
            keadaan=("menunggu dilanjutkan" if macet else "catat hasil, tutup bila selesai"),
            aksi=("lanjutkan_proses" if macet else "hasil_giling"),
            nilai=(f"giling:{p.kode_proses}" if macet else p.kode_proses),
            fase="giling",
            sejak=p.waktu_mulai,
            pilihan=([
                ("lanjutkan_proses", "Lanjutkan giling",
                 "Mesin jalan lagi — bisa nanti, bisa besok",
                 f"giling:{p.kode_proses}"),
                ("selesai_giling", "Selesai giling", "Tutup proses & kosongkan silo",
                 p.kode_proses),
            ] if macet else [
                ("hasil_giling", "Perbarui hasil giling", "Catat PK kumulatif terbaru",
                 p.kode_proses),
                *([("qc_giling", "Catat mutu sekarang",
                    "Contoh dari beras yang baru keluar mesin — hasilnya dirata-rata",
                    p.kode_proses)] if (boleh_qc and qc_aktif) else []),
                ("hentikan_proses", "Hentikan sementara",
                 "Mesin rusak, limbah penuh, jam kerja habis",
                 f"giling:{p.kode_proses}"),
                ("selesai_giling", "Selesai giling", "Tutup proses & kosongkan silo",
                 p.kode_proses),
            ]),
        ))

    # ── PK yang sudah DISETUJUI Admin untuk dikirim ke Gudang 2 ──
    #
    # Kemampuan baru operator Gudang 1 (keputusan pemilik 25 September 2026),
    # dan ia berpagar pada BARISNYA, bukan pada peran: `can_transfer_pk` tak
    # disentuh sama sekali. Yang muncul di sini hanya permintaan berstatus
    # `disetujui` — yang masih menunggu keputusan Admin TIDAK ditampilkan,
    # sebab kartu yang belum boleh dikerjakan akan ditekan juga, dan yang
    # menekannya menerima penolakan atas pekerjaan yang memang bukan haknya
    # hari itu.
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
            aksi="kirim_permintaan_pk", nilai=str(baris.id), fase="giling",
            sejak=baris.waktu_setuju or baris.waktu_minta,
            judul="Kirim PK ke Gudang 2",
            utama=(_kg(kg).removesuffix(" kg"), "kg"),
            sub=f"{kode_lot} · tujuan {lok}",
            kelompok="permintaan",
            nota="Catat yang BENAR-BENAR dimuat. Boleh kurang dari yang "
                 "disetujui; lebih tidak.",
            pilihan=[("kirim_permintaan_pk", "Kirim ke Gudang 2",
                      "Barangnya berpindah sekarang juga", str(baris.id))]))
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
    for pk, nama in (await db.execute(
        select(PkPurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
        .where(PkPurchaseBatch.status_batch == "diterima", belum_masuk)
        .order_by(PkPurchaseBatch.id.desc())
    )).all():
        b.menunggu.append(Baris(
            kode=pk.kode_batch, isi=f"PK luar · {dari_batch(pk).teks()}",
            aksi="masukkan_pk", nilai=pk.kode_batch, fase="baru",
            sejak=pk.created_at,
            judul=nama or pk.kode_batch,
            utama=_utama(dari_batch(pk)),
            sub=f"{pk.kode_batch} · PK luar · masuk {_tgl(pk.tanggal_pembelian)}",
            keadaan="belum masuk silo maupun tumpukan",
            pilihan=[("masukkan_pk", "Masukkan ke gudang",
                      "Tentukan tumpukan atau silo tujuannya", pk.kode_batch)],
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

    # ── Kerja meja: harga & mutu PK luar ──
    for pk, nama in (await db.execute(
        select(PkPurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
        .where(PkPurchaseBatch.flag_unverified.is_(True))
        .order_by(PkPurchaseBatch.id.desc())
    )).all():
        b.meja.append(Baris(
            kode=pk.kode_batch, isi=f"{nama} · {dari_batch(pk).teks()}",
            keadaan="", aksi="harga_pk_luar", nilai=pk.kode_batch,
            fase=("baru" if pk.status_batch == "baru" else "silo"),
            sejak=pk.created_at,
            judul=nama or pk.kode_batch,
            utama=_utama(dari_batch(pk)),
            sub=f"{pk.kode_batch} · PK luar · masuk {_tgl(pk.tanggal_pembelian)}",
            pilihan=[("harga_pk_luar", "Verifikasi harga PK luar",
                      "Sesudah ini nilainya beku", pk.kode_batch)],
        ))

    sudah_qc = set((await db.execute(
        select(PkPurchaseVerification.pk_purchase_batch_id)
        .where(PkPurchaseVerification.kadar_air.is_not(None))
    )).scalars().all())
    for pk, nama in (await db.execute(
        select(PkPurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
        .order_by(PkPurchaseBatch.id.desc())
    )).all() if await fitur_mutu(db) else []:
        if pk.id in sudah_qc:
            continue
        b.meja.append(Baris(
            kode=pk.kode_batch, isi="mutu PK luar belum dicatat",
            keadaan="", aksi="qc_pk_luar", nilai=pk.kode_batch, fase="silo_g2",
            sejak=pk.created_at,
            judul="Mutu PK luar belum dicatat",
            sub=f"{pk.kode_batch} · {nama or '?'} · "
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
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage

    keluar: list[Baris] = []
    for pr in (await db.execute(
        select(PolishingProcess).where(PolishingProcess.status == "proses")
        .order_by(PolishingProcess.id.desc())
    )).scalars().all():
        # Dari silo mana ia makan — dan lewat silo itu, dari lot giling mana.
        # Inilah satu-satunya tempat beras putih masih bisa disambungkan ke
        # gabahnya; sesudah proses ditutup, yang tersisa cuma angka hasil.
        asal_pr: list[tuple[str, str, str]] = []
        silo_nama: list[str] = []
        ditambah = 0.0
        for u in (await db.execute(
            select(PolishingSiloUsage)
            .where(PolishingSiloUsage.polishing_process_id == pr.id)
        )).scalars().all():
            ditambah += float(u.berat_masuk_kg or 0)
            s = await db.get(Silo, u.silo_id)
            if s:
                silo_nama.append(s.nama_silo)
            for a in (await asal_silo(u.silo_id)).baris:
                if a not in asal_pr:
                    asal_pr.append(a)
        pemasok_pr = _pemasok_ringkas(asal_pr)
        macet = await jeda_terbuka(db, "penyosohan", pr.id)
        tertahan = await tertahan_detik(db, "penyosohan", pr.id)
        fakta = [("Silo", " + ".join(silo_nama) or "—")]
        if ditambah:
            # PK yang dituang selama mesin jalan ikut jadi penyebut rendemen
            # — angka yang ikut menilai pekerjaan tak boleh disembunyikan.
            fakta.append(("Ditambah", _kg(ditambah)))
        if tertahan >= 60:
            fakta.append(("Tertahan", f"{tertahan / 3600:.1f} jam"))
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
            sub=(f"{pr.kode_proses} · {pemasok_pr}" if pemasok_pr
                 else f"{pr.kode_proses} · mesin sosoh menyala"),
            fakta=fakta,
            anak=asal_pr[:6],
            nota=(f"Dijeda {_jam((now_local() - macet.mulai).total_seconds())} — "
                  f"{macet.sebab}" if macet else None),
            nota_jenis="hati" if macet else None,
            ringkas=(f"⏸ {macet.sebab}"
                     + (f" · tertahan {tertahan / 3600:.1f} jam" if tertahan >= 60 else "")
                     if macet else
                     (f"menyosoh PK {pemasok_pr}" if pemasok_pr else "mesin sosoh menyala")),
            pilihan=([
                ("lanjutkan_penyosohan", "Lanjutkan penyosohan",
                 "Mesin jalan lagi — bisa nanti, bisa besok",
                 f"penyosohan:{pr.kode_proses}"),
                ("selesai_penyosohan", "Selesai penyosohan",
                 "Tutup proses, per silo", pr.kode_proses),
            ] if macet else [
                ("hasil_penyosohan", "Perbarui hasil penyosohan",
                 "Beras putih, menir, bekatul — kumulatif", pr.kode_proses),
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
    sedang = bool(dipakai) or bool((await db.execute(
        select(PolishingProcess.id).where(PolishingProcess.status == "proses")
    )).first())
    wid2 = await _g2_warehouse_id(db)
    for silo in (await db.execute(
        select(Silo).where(Silo.warehouse_id == wid2).order_by(Silo.nama_silo)
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
            kode=silo.nama_silo, isi=f"PK · {_kg(kg)}",
            # Tiga keadaan, tiga kalimat. Silo yang sisanya sudah dicatat
            # BUKAN silo yang sedang menunggu mesin: yang membacanya perlu tahu
            # bahwa angka ini sisa isian yang baru saja ditutup, bukan muatan
            # yang belum tersentuh.
            keadaan=("sisanya sudah dicatat · mesin masih memakai silo lain"
                     if silo.id in sisa_dicatat
                     else "mesin sosoh sedang dipakai" if sedang
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
            nota=_nota_isian(isian),
            ringkas=(f"PK dari {pemasok}" if pemasok else "PK menunggu disosoh"),
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
        keluar.append(Baris(
            kode=kode, isi=f"PK di tumpukan · {_kg(sisa) if sisa is not None else 'menunggu timbang'}",
            keadaan="menunggu dipindah ke silo — boleh sebagian",
            aksi="pindah_tumpukan_silo", nilai=str(it.id), fase="tumpuk",
            sejak=it.waktu_masuk, judul=judul, kelompok="tumpukan",
            utama=((_kg(sisa).removesuffix(" kg"), "kg") if sisa is not None else None),
            sub=f"{kode} · {sumber} · masuk {_tgl(it.tanggal_masuk)}",
            pilihan=[("pindah_tumpukan_silo", "Pindah ke silo",
                      "Sebagian atau seluruhnya, ke Silo A / B", str(it.id))],
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
    """
    from app.services.stok import beras_curah

    keluar: list[Baris] = []
    for b in await beras_curah(db, termasuk_berjalan=False):
        if b.sisa_kg <= 0:
            continue                    # minus = pertanyaan, bukan pekerjaan
        keluar.append(Baris(
            kode=b.kode_proses,
            isi=f"{b.jenis} · {_kg(b.sisa_kg)} belum dikemas",
            keadaan="menunggu dipacking",
            aksi="catat_packing", nilai=b.kode_proses, fase="sosoh",
            sejak=b.selesai,
            judul="Beras menunggu dipacking",
            utama=(_kg(b.sisa_kg).removesuffix(" kg"), "kg"),
            sub=f"{b.kode_proses} · {b.jenis}"
                + (f" · dari {_kg(b.keluar_kg)}" if b.dikemas_kg else ""),
            kelompok="produk", gudang="g2",
            pilihan=[("catat_packing", "Catat packing barang jadi",
                      "Memindahkan dari curah ke barang jadi", b.kode_proses)]))
    return keluar


async def untuk_operator_gudang2(db: AsyncSession) -> Berjalan:
    """Layar OPERATOR Gudang 2, menurut pemilik 12 September 2026:

      · `menunggu` = SELURUH stok PK di Gudang 2 — yang di lantai (tumpukan,
        per intake → pindah ke silo) dan yang di silo (→ mulai penyosohan);
      · `berjalan` = mesin yang menyala saja;
      · tidak ada kerja meja.

    TRANSIT lahir 25 September 2026, dan cuma untuk satu hal: permintaan PK
    yang sedang dalam perjalanan dari Gudang 1. Keputusan 12 September yang
    mengosongkan Transit berbicara tentang STOK MILIKNYA SENDIRI — PK yang
    sudah di sini adalah antrean, bukan barang yang dipantau. Permintaan yang
    sedang berjalan bukan stoknya: ia belum ada di gudang ini, dan tak ada
    satu pun tombol untuknya.

    Karena itu ia TIDAK di `menunggu`: lencana antrean menagih pekerjaan, dan
    kartu yang tak bisa dikerjakan siapa pun di layar ini akan membuat
    lencananya tak pernah kembali nol — lencana yang tak pernah nol mengajari
    orang mengabaikan lencana.

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
    # sesudah menekan Minta. Kartu bertombol yang ditekan lalu ditolak
    # mengajari orang bahwa layarnya tak bisa dipercaya.
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
            fase="giling",
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

    # Tiket PK yang belum dicatat: kartu DIAM. Penempatan PK datang bukan tugas
    # operator (pemilik, 12 September 2026) dan itu tidak diubah — tapi
    # barangnya berdiri di halamannya, dan ia tak boleh jadi orang terakhir yang
    # tahu. Ia berdiri PALING ATAS di antreannya karena ia yang paling baru
    # turun dari truk.
    b.menunggu += await _tiket_pk_luar(db, boleh_catat=False)
    b.menunggu += await _kartu_tumpukan_g2(db)
    b.menunggu += await _kartu_silo_g2(db, asal_silo)
    # Beras yang menunggu dipacking: pekerjaan yang sungguh menunggu orang ini,
    # jadi ia di ANTREAN — beda dengan permintaan PK di Transit, yang menunggu
    # tangan orang lain.
    curah = await _kartu_beras_curah(db)
    b.menunggu += curah
    b.jumlah_produk = len(curah)
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

    # Tiket berjenis tak dikenal — satu-satunya baris FISIK di fungsi ini, dan
    # ia di sini karena jalan keluarnya memang kerja meja: memetakan jenisnya,
    # atau membatalkan tiketnya di Pos Timbang. Ia masuk `menunggu`, bukan
    # `meja`: yang tertahan bukan keputusan uang melainkan barang yang berdiri
    # di halaman tanpa satu catatan pun.
    b.menunggu += await _tiket_jenis_tak_dikenal(db)

    for batch, nama in (await db.execute(
        select(PurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id)
        .where(PurchaseBatch.flag_unverified.is_(True))
        .order_by(PurchaseBatch.id.desc())
    )).all():
        di_mana = _DI_MANA.get(batch.status_batch or "", batch.status_batch or "")
        b.meja.append(Baris(
            kode=batch.kode_batch, isi=f"{nama} · {dari_batch(batch).teks()}",
            # Keadaannya kosong: judul bloknya sudah mengatakannya.
            keadaan="", aksi="verify_gabah",
            nilai=batch.kode_batch,
            sejak=batch.created_at,
            fase=_FASE_BATCH.get(batch.status_batch or "", "baru"),
            judul=nama,
            utama=_utama(dari_batch(batch)),
            sub=f"{batch.kode_batch} · gabah {batch.kondisi_gabah} · "
                f"masuk {_tgl(batch.tanggal_pembelian)}",
            fakta=[("Gabahnya", di_mana)],
            pilihan=[("verify_gabah", "Verifikasi harga",
                      "Sesudah ini bobotnya dibekukan — revisi nota tak lagi masuk")],
        ))

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
    # Gudang 1 dan boleh MEMINTA satu dipindah; yang mencatat perpindahan tetap
    # Admin. Kartunya di `menunggu`, bukan `meja`: tak ada yang diputuskan di
    # sini — barangnya ada, catatannya belum. Bentuknya sama dengan kartu tiket
    # PK luar, dan `meja` adalah tempat keputusan harga/mutu/output.
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
            b.menunggu.append(Baris(
                kode=kode_lot,
                isi=f"Gudang 1 sudah mengirim {_kg(kg_kirim)} ke {lok}",
                keadaan="menunggu ditutup Admin",
                aksi="tutup_permintaan_pk", nilai=str(baris.id), fase="giling",
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
        b.menunggu.append(Baris(
            kode=kode_lot,
            isi=f"{nama_minta or 'Operator Gudang 2'} minta lot ini dipindah",
            keadaan="menunggu keputusan Anda",
            aksi="acc_permintaan_pk", nilai=str(baris.id), fase="giling",
            sejak=baris.waktu_minta,
            judul="Diminta Gudang 2",
            utama=(_kg(bd.tersedia).removesuffix(" kg"), "kg"),
            sub=f"{kode_lot} · diminta {nama_minta or '?'}",
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
    return b


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
        # Operator Gudang 2 melihat layarnya sendiri: antrean = stok PK
        # (tumpukan + silo), berjalan = mesin. Penempatan PK datang bukan
        # tugasnya (keputusan pemilik 12 September 2026).
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
    return b
