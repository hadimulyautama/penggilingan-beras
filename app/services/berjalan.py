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
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    DryingLot,
    MillingProcess,
    MillingProcessVerification,
    MillingQcLog,
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

    #: Satu kalimat pengganti `fakta` + `anak` di kartu padat. Kosong = pakai
    #: `sub`, karena baris yang tak punya apa-apa untuk diringkas memang tak
    #: perlu dipaksa punya.
    ringkas: str | None = None
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

    @property
    def jumlah_menunggu(self) -> int:
        """Lencana antrean. Kerja meja TIDAK ikut — ia punya layar & lencana
        sendiri, dan menghitungnya di sini membuat lencana antrean menagih
        pekerjaan yang tak ada di dalamnya."""
        return len(self.menunggu)

    @property
    def jumlah_keputusan(self) -> int:
        return len(self.meja)

    @property
    def jumlah_berjalan(self) -> int:
        """Isi layar Sedang berjalan — mesin menyala DAN gabah transit."""
        return len(self.berjalan) + len(self.transit)


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


def _kg(n) -> str:
    return f"{float(n or 0):,.0f} kg".replace(",", ".")


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
               PurchaseBatch.tanggal_pembelian, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id, isouter=True)
        .where(PurchaseBatch.id.in_(list(batch_ids)))
        .order_by(PurchaseBatch.id)
    )).all()
    return [(f"{nama or '?'} · {kode}", _kg(kg), f"masuk {_tgl(tgl)}")
            for kode, kg, tgl, nama in baris]


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
            isi += f" · {_kg(bobot)} ({t.get('sumber_berat')})"
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
            fakta=([("Sumber berat", str(t.get("sumber_berat") or "-"))] if bobot else [])
                  + [("Masuk", _tgl(t.get("tanggal")))],
            # Satu tindakan pun tetap dibentangkan, bukan langsung dilempar
            # ke lembar. Ketukan pertama yang berbeda-beda artinya di tiap
            # kartu memaksa orang menebak apa yang akan terjadi sebelum
            # menekan — dan yang menebak akan berhenti menekan.
            # Tujuannya ditekan LANGSUNG dari kartu — tak ada lembar melayang
            # untuk satu keputusan yang cuma punya beberapa jawaban.
            tombol=await _tujuan_gabah(
                db, kondisi, post="/miniapp/actions/gabah-masuk",
                data={"timbangan_transaksi_id": t["id"]}),
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


async def untuk_gudang1(db: AsyncSession) -> Berjalan:
    """Pekerjaan operator Gudang 1, dari truk masuk sampai giling ditutup."""
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
        total = sum(float(x.berat_total_kg or 0) for x in isi_mesin)
        kondisi = {x.kondisi_gabah for x in isi_mesin}
        b.transit.append(Baris(
            kode="",
            isi=f"{len(isi_mesin)} batch di {mesin.nama} · {_kg(total)}",
            keadaan="nyalakan mesinnya",
            aksi="mulai_pengeringan", fase="dryer",
            # Mesinnya ikut, jadi lembarnya tak menanyakan lagi mesin mana —
            # kartunya sudah menunjuknya.
            nilai=str(mesin.id),
            sejak=min((x.created_at for x in isi_mesin if x.created_at), default=None),
            judul=mesin.nama,
            utama=(_kg(total).removesuffix(" kg"), "kg"),
            sub=f"{len(isi_mesin)} batch"
                + (f" · gabah {'/'.join(sorted(kondisi))}" if kondisi else ""),
            fakta=[("Mode terdekat", mode_disarankan(total)),
                   ("Target", "belum ditetapkan")],
            anak=await _asal(db, [x.id for x in isi_mesin]),
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
            isi=f"{_kg(b_.berat_total_kg)} · gabah {b_.kondisi_gabah}",
            keadaan="tentukan tempatnya",
            aksi="pindah_tumpukan", nilai=b_.kode_batch, fase="baru",
            sejak=b_.created_at,
            judul=nama_pemasok,
            utama=(_kg(b_.berat_total_kg).removesuffix(" kg"), "kg"),
            sub=f"{b_.kode_batch} · gabah {b_.kondisi_gabah} · "
                f"masuk {_tgl(b_.tanggal_pembelian)}",
            tombol=await _tujuan_gabah(
                db, b_.kondisi_gabah, post="/miniapp/actions/pindah-tumpukan",
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
            isi=f"menumpuk · {_kg(b_.berat_total_kg)} · gabah {b_.kondisi_gabah}",
            keadaan=("harus ke dryer — belum kering" if wajib_dryer
                     else "tentukan tempatnya"),
            aksi="pindah_tumpukan", nilai=b_.kode_batch, sejak=b_.created_at,
            fase="baru",
            judul=nama_pemasok,
            utama=(_kg(b_.berat_total_kg).removesuffix(" kg"), "kg"),
            sub=f"{b_.kode_batch} · gabah {b_.kondisi_gabah} · "
                f"masuk {_tgl(b_.tanggal_pembelian)}",
            nota=("Gabah basah tak boleh ke silo — harus dikeringkan dulu."
                  if wajib_dryer else None),
            tombol=await _tujuan_gabah(
                db, b_.kondisi_gabah, post="/miniapp/actions/pindah-tumpukan",
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
        kg_lot = sum(float(x.berat_total_kg or 0) for x in isi_lot)
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
            utama=(_kg(kg_lot).removesuffix(" kg"), "kg") if kg_lot else None,
            sub=f"{lot.kode_lot} · {len(isi_lot)} batch"
                + (f" · {_pemasok_ringkas(asal_lot)}" if asal_lot else ""),
            fakta=fakta,
            anak=asal_lot,
            nota=(f"⏸ Dijeda — {macet.sebab}. Menunggu dilanjutkan."
                  if macet else None),
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
        _g1_warehouse_id, _silo_active_rows, _silo_content_kg)

    wid = await _g1_warehouse_id(db)
    for silo in (await db.execute(
        select(Silo).where(Silo.warehouse_id == wid).order_by(Silo.nama_silo)
    )).scalars().all():
        if not await _silo_active_rows(db, silo.id):
            continue
        sibuk = (await db.execute(
            select(MillingProcess.id).where(
                MillingProcess.silo_id == silo.id, MillingProcess.status == "proses")
        )).first()
        if sibuk:
            continue
        huruf = silo.nama_silo.replace("Silo ", "")
        # Masuk `berjalan`, BUKAN `menunggu` — sengaja, dan ini soal lencana.
        #
        # Silo penuh memang menunggu orang, tetapi bisa menunggu berhari-hari
        # tanpa ada yang salah: giling dijadwalkan, bukan didesak. Kalau ia
        # ikut dihitung, lencana tak pernah kembali nol — dan lencana yang tak
        # pernah nol mengajari orang mengabaikan lencana.
        kg_silo = await _silo_content_kg(db, silo.id)
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
            kode=silo.nama_silo, isi=f"gabah kering · {_kg(kg_silo)}",
            keadaan="mulai giling bila siap", aksi="mulai_giling",
            nilai=huruf, fase="silo",
            judul=silo.nama_silo,
            utama=(_kg(kg_silo).removesuffix(" kg"), "kg"),
            sub="gabah kering · menunggu giliran digiling"
                + (f" · {_pemasok_ringkas(asal_silo)}" if asal_silo else ""),
            anak=asal_silo,
            ringkas="gabah kering · menunggu giliran digiling",
            pilihan=[("mulai_giling", "Mulai giling",
                      "Seluruh isi silo jadi satu lot (LOT-…)")],
        ))

    for p in (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "proses")
        .order_by(MillingProcess.id.desc())
    )).scalars().all():
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
        fakta_g = [("Bahan", _kg(p.berat_gabah_masuk_kg))]
        if tertahan >= 60:
            fakta_g.append(("Tertahan", f"{tertahan / 3600:.1f} jam"))
        b.berjalan.append(Baris(
            kode=p.kode_proses,
            isi=(f"⏸ berhenti — {macet.sebab}" if macet else "digiling")
                + f" · {_kg(p.berat_gabah_masuk_kg)} gabah masuk"
                + (f" · tertahan {tertahan / 3600:.1f} jam" if tertahan >= 60 else ""),
            judul=("Giling dijeda" if macet else "Giling"),
            utama=(_kg(p.berat_gabah_masuk_kg).removesuffix(" kg"), "kg"),
            sub=f"{p.kode_proses} · bahan masuk"
                + (f" · {_pemasok_ringkas(asal_giling)}" if asal_giling else ""),
            anak=asal_giling,
            fakta=fakta_g,
            nota=(f"⏸ Dijeda — {macet.sebab}. Menunggu dilanjutkan."
                  if macet else None),
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
                ("hentikan_proses", "Hentikan sementara",
                 "Mesin rusak, limbah penuh, jam kerja habis",
                 f"giling:{p.kode_proses}"),
                ("selesai_giling", "Selesai giling", "Tutup proses & kosongkan silo",
                 p.kode_proses),
            ]),
        ))
    return b


#: Di mana gabahnya BERADA saat harganya masih ditagih. Fase inilah yang
#: mewarnai kartu dan mengisi kepingannya — dan sebelum ini tak pernah
#: disetel sama sekali, jadi terpakai bawaannya, "Belum ada tindakan". Itu
#: bohong: gabahnya bisa sudah dua hari di dalam mesin pengering. Kepingan
#: yang berbohong lebih buruk daripada kepingan yang tak ada, karena ia
#: dipercaya.
_FASE_BATCH = {
    "baru": "baru", "ditumpuk": "baru",
    "di_dryer": "dryer", "dikeringkan": "dryer",
    "di_silo": "silo", "digiling": "giling",
}

_DI_MANA = {
    "baru": "belum ditempatkan", "ditumpuk": "menumpuk di lantai",
    "di_dryer": "sudah di mesin pengering", "dikeringkan": "sedang dikeringkan",
    "di_silo": "sudah di silo", "digiling": "sudah digiling",
}


async def untuk_staff(db: AsyncSession) -> Berjalan:
    """Yang tertahan menunggu keputusan staff/Direksi — bukan pekerjaan fisik.

    Semuanya masuk `meja`. Barisnya menyebut DI MANA gabahnya sekarang,
    karena pertanyaan pertama yang timbul saat melihat kode batch lama adalah
    "ini yang mana, dan apa sudah dikerjakan?" — dan jawabannya tak boleh
    menuntut orang membuka layar lain.
    """
    b = Berjalan()

    for batch, nama in (await db.execute(
        select(PurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id)
        .where(PurchaseBatch.flag_unverified.is_(True))
        .order_by(PurchaseBatch.id.desc())
    )).all():
        di_mana = _DI_MANA.get(batch.status_batch or "", batch.status_batch or "")
        b.meja.append(Baris(
            kode=batch.kode_batch, isi=f"{nama} · {_kg(batch.berat_total_kg)}",
            # Keadaannya kosong: judul bloknya sudah mengatakannya.
            keadaan="", aksi="verify_gabah",
            nilai=batch.kode_batch,
            sejak=batch.created_at,
            fase=_FASE_BATCH.get(batch.status_batch or "", "baru"),
            judul=nama,
            utama=(_kg(batch.berat_total_kg).removesuffix(" kg"), "kg"),
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
        )).scalar_one()
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
        ada_v = (await db.execute(
            select(MillingProcessVerification.id)
            .where(MillingProcessVerification.milling_process_id == p.id)
        )).scalars().first()
        if not ada_v:
            b.meja.append(Baris(
                kode=p.kode_proses, isi="output giling belum diverifikasi",
                keadaan="", aksi="verify_output",
                nilai=p.kode_proses, sejak=p.waktu_selesai, fase="giling",
                judul="Output belum diverifikasi",
                sub=f"{p.kode_proses} · giling sudah ditutup"
                    + (f" · {_pemasok_ringkas(asal)}" if asal else ""),
                anak=asal,
                pilihan=[("verify_output", "Verifikasi output giling",
                          "Berat PK final — rendemen terhitung dari sini")]))
    return b


async def untuk(db: AsyncSession, user: User) -> Berjalan:
    """Gabungkan sesuai peran — server yang memutuskan, bukan layar."""
    from app.bots.common import can_see_financials

    from app.web.miniapp import _is_g1_operator, _is_g2_operator

    b = Berjalan()
    if await _is_g1_operator(user):
        g = await untuk_gudang1(db)
        b.menunggu += g.menunggu
        b.berjalan += g.berjalan
        # Transit ikut. Sebelumnya tidak, dan akibatnya blok Transit di layar
        # Sedang berjalan selalu kosong: gabah yang menunggu di dryer dan silo
        # dikeluarkan dari antrean tanpa pernah sampai ke tempat barunya —
        # hilang dari kedua layar sekaligus.
        b.transit += g.transit
    if can_see_financials(user):
        s = await untuk_staff(db)
        b.meja += s.meja
        b.berjalan += s.berjalan
        # Staff & Direksi tak terikat satu gudang; keadaan fisik G1 tetap
        # perlu terlihat, tetapi sebagai kabar — bukan sebagai tugas mereka.
        if not await _is_g1_operator(user):
            g1 = await untuk_gudang1(db)
            b.berjalan += g1.berjalan
            b.transit += g1.transit
    if await _is_g2_operator(user):
        pass    # Gudang 2 menyusul — lihat catatan di docs/RANCANGAN.md §11.
    return b
