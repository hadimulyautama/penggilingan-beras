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

    @property
    def jumlah_menunggu(self) -> int:
        return len(self.menunggu)

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
        isi = f"{komoditas} · {nama} · {t.get('nomor_polisi') or '-'}"
        if bobot:
            isi += f" · {_kg(bobot)} ({t.get('sumber_berat')})"
        baris.append(Baris(
            kode=t["kode"], isi=isi, aksi="gabah_masuk", nilai=str(t["id"]),
            keadaan=("tiket sudah ditutup — susulan" if t.get("susulan")
                     else "catat & tentukan tempatnya"),
            # Pemasoknya yang jadi judul, bukan kata "Tiket timbang": yang
            # dicari mata saat menyusuri antrean adalah siapa, bukan jenis
            # kartunya — jenisnya sudah dikatakan oleh warnanya.
            judul=nama,
            utama=(_kg(bobot).removesuffix(" kg"), "kg") if bobot else None,
            sub=f"{t['kode']} · {komoditas}"
                + (f" · {t.get('nomor_polisi')}" if t.get("nomor_polisi") else ""),
            fakta=[("Sumber berat", str(t.get("sumber_berat") or "-"))] if bobot else [],
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
    from app.penggilingan.gudang1.services.drying import _loose_dryer_batches

    menunggu_dryer = await _loose_dryer_batches(db)
    if menunggu_dryer:
        total = sum(float(x.berat_total_kg or 0) for x in menunggu_dryer)
        kondisi = {x.kondisi_gabah for x in menunggu_dryer}
        from app.penggilingan.gudang1.services.drying import mode_disarankan

        b.transit.append(Baris(
            kode="",
            isi=f"{len(menunggu_dryer)} batch di dryer · {_kg(total)}",
            keadaan="nyalakan mesinnya",
            aksi="mulai_pengeringan", fase="dryer",
            sejak=min((x.created_at for x in menunggu_dryer if x.created_at), default=None),
            judul="Mesin pengering",
            utama=(_kg(total).removesuffix(" kg"), "kg"),
            sub=f"{len(menunggu_dryer)} batch"
                + (f" · gabah {'/'.join(sorted(kondisi))}" if kondisi else ""),
            fakta=[("Mode terdekat", mode_disarankan(total)),
                   ("Target", "belum ditetapkan")],
            anak=[(x.kode_batch, _kg(x.berat_total_kg), "") for x in menunggu_dryer],
            ringkas=f"{len(menunggu_dryer)} batch menunggu mesin dinyalakan"
                    f" · mode terdekat {mode_disarankan(total)}",
        ))

    # Gabah yang TERCATAT tetapi belum ditempatkan di mana pun.
    #
    # Terjadi saat penempatan otomatis gagal — dryer sedang dipakai, misalnya.
    # Batch-nya tetap tersimpan (dan memang harus: gabahnya sudah turun dari
    # truk), lalu berstatus 'baru' dan tidak berada di dryer, silo, maupun
    # tumpukan. Tanpa baris ini, gabah itu berdiri di halaman tanpa ada satu
    # layar pun yang menyebutnya.
    for b_ in (await db.execute(
        select(PurchaseBatch).where(PurchaseBatch.status_batch == "baru")
        .order_by(PurchaseBatch.id.desc())
    )).scalars().all():
        b.menunggu.append(Baris(
            kode=b_.kode_batch,
            isi=f"{_kg(b_.berat_total_kg)} · gabah {b_.kondisi_gabah}",
            keadaan="tentukan tempatnya",
            aksi="pindah_tumpukan", nilai=b_.kode_batch, fase="baru",
            sejak=b_.created_at,
            judul=b_.kode_batch,
            utama=(_kg(b_.berat_total_kg).removesuffix(" kg"), "kg"),
            sub=f"gabah {b_.kondisi_gabah} · belum punya tempat",
        ))

    # Tumpukan lebih dulu dari yang lain: isinya menandakan pembelian berlebih,
    # dan itu keadaan yang paling ingin diketahui — bukan yang paling dalam
    # daftar. Kosong berarti tak ada baris sama sekali, seperti seharusnya.
    from app.penggilingan.gudang1.services import tumpukan as tmp
    for b_ in await tmp.isi(db):
        wajib_dryer = b_.kondisi_gabah == "basah"
        b.menunggu.append(Baris(
            kode=b_.kode_batch,
            isi=f"menumpuk · {_kg(b_.berat_total_kg)} · gabah {b_.kondisi_gabah}",
            keadaan=("harus ke dryer — belum kering" if wajib_dryer
                     else "tentukan tempatnya"),
            aksi="pindah_tumpukan", nilai=b_.kode_batch, sejak=b_.created_at,
            fase="baru",
            judul=b_.kode_batch,
            utama=(_kg(b_.berat_total_kg).removesuffix(" kg"), "kg"),
            sub=f"menumpuk di lantai · gabah {b_.kondisi_gabah}",
            nota=("Gabah basah tak boleh ke silo — harus dikeringkan dulu."
                  if wajib_dryer else None),
        ))

    for lot in await _lot(db, pendinginan_selesai=True):
        b.transit.append(Baris(
            kode=lot.kode_lot, isi="sudah dingin, dryer perlu dikosongkan",
            keadaan="pindahkan ke silo", aksi="pindah_silo",
            nilai=lot.kode_lot, fase="dryer",
            judul="Sudah dingin",
            sub=f"{lot.kode_lot} · gabahnya masih di mesin",
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
        b.berjalan.append(Baris(
            kode=lot.kode_lot, isi="pengeringan selesai, sedang didinginkan",
            keadaan="nyatakan bila sudah dingin", aksi="selesai_pendinginan",
            nilai=lot.kode_lot, fase="dryer",
            sejak=lot.waktu_selesai_pengeringan,
            judul="Pendinginan",
            sub=f"{lot.kode_lot} · gabah tetap di mesin",
            ringkas="pengeringan selesai · menunggu dingin",
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
        from app.penggilingan.gudang1.services.drying import kadar_air_awal, kemajuan
        from app.services.setelan import target_kadar_air

        target_n = (float(lot.target_kadar_air) if lot.target_kadar_air is not None
                    else await target_kadar_air(db))
        target = f"{target_n:g}%"
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
            sub=f"{lot.kode_lot} · {len(isi_lot)} batch",
            fakta=fakta,
            anak=[(f"{x.kode_batch}", _kg(x.berat_total_kg), "") for x in isi_lot],
            nota=(f"⏸ Dijeda — {macet.sebab}. Menunggu dilanjutkan."
                  if macet else None),
            maju=maju,
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
            pilihan=([
                ("lanjutkan_proses", "Lanjutkan pengeringan",
                 "Mesin jalan lagi — bisa nanti, bisa besok"),
                ("kadar_air", "Perbarui kadar air", "Catat hasil ukur terbaru"),
                ("selesai_pengeringan", "Selesai pengeringan",
                 "Lot langsung masuk fase pendinginan"),
            ] if macet else [
                ("kadar_air", "Perbarui kadar air", "Catat hasil ukur terbaru"),
                ("hentikan_proses", "Hentikan sementara",
                 "Mesin rusak, listrik padam, jam kerja habis"),
                ("selesai_pengeringan", "Selesai pengeringan",
                 "Lot langsung masuk fase pendinginan"),
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
        b.transit.append(Baris(
            kode=silo.nama_silo, isi=f"gabah kering · {_kg(kg_silo)}",
            keadaan="mulai giling bila siap", aksi="mulai_giling",
            nilai=huruf, fase="silo",
            judul=silo.nama_silo,
            utama=(_kg(kg_silo).removesuffix(" kg"), "kg"),
            sub="gabah kering · menunggu giliran digiling",
            ringkas="gabah kering · menunggu giliran digiling",
        ))

    for p in (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "proses")
        .order_by(MillingProcess.id.desc())
    )).scalars().all():
        from app.penggilingan.gudang1.services.jeda import jeda_terbuka, tertahan_detik

        macet = await jeda_terbuka(db, "giling", p.id)
        tertahan = await tertahan_detik(db, "giling", p.id)
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
            sub=f"{p.kode_proses} · bahan masuk",
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
                 "Mesin jalan lagi — bisa nanti, bisa besok"),
                ("selesai_giling", "Selesai giling", "Tutup proses & kosongkan silo"),
            ] if macet else [
                ("hasil_giling", "Perbarui hasil giling", "Catat PK kumulatif terbaru"),
                ("hentikan_proses", "Hentikan sementara",
                 "Mesin rusak, limbah penuh, jam kerja habis"),
                ("selesai_giling", "Selesai giling", "Tutup proses & kosongkan silo"),
            ]),
        ))
    return b


async def untuk_staff(db: AsyncSession) -> Berjalan:
    """Yang tertahan menunggu keputusan staff/Direksi — bukan pekerjaan fisik."""
    b = Berjalan()

    for batch, nama in (await db.execute(
        select(PurchaseBatch, Supplier.nama_supplier)
        .join(Supplier, Supplier.id == PurchaseBatch.supplier_id)
        .where(PurchaseBatch.flag_unverified.is_(True))
        .order_by(PurchaseBatch.id.desc())
    )).all():
        b.menunggu.append(Baris(
            kode=batch.kode_batch, isi=f"{nama} · {_kg(batch.berat_total_kg)}",
            keadaan="harga belum diverifikasi", aksi="verify_gabah",
            nilai=batch.kode_batch,
            sejak=batch.created_at,
        ))

    selesai = (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "selesai")
        .order_by(MillingProcess.id.desc())
    )).scalars().all()
    for p in selesai:
        ada_qc = (await db.execute(
            select(func.count()).select_from(MillingQcLog)
            .where(MillingQcLog.milling_process_id == p.id)
        )).scalar_one()
        if not ada_qc:
            b.menunggu.append(Baris(
                kode=p.kode_proses, isi="giling selesai, mutu belum diperiksa",
                keadaan="menunggu QC", aksi="qc_giling", nilai=p.kode_proses,
                sejak=p.waktu_selesai))
        ada_v = (await db.execute(
            select(MillingProcessVerification.id)
            .where(MillingProcessVerification.milling_process_id == p.id)
        )).scalars().first()
        if not ada_v:
            b.menunggu.append(Baris(
                kode=p.kode_proses, isi="output giling belum diverifikasi",
                keadaan="menunggu verifikasi output", aksi="verify_output",
                nilai=p.kode_proses, sejak=p.waktu_selesai))
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
        b.menunggu += s.menunggu
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
