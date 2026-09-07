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


@dataclass
class Berjalan:
    menunggu: list[Baris] = field(default_factory=list)
    berjalan: list[Baris] = field(default_factory=list)

    @property
    def jumlah_menunggu(self) -> int:
        return len(self.menunggu)


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
                     else "belum ditaut ke batch"),
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
        b.menunggu.append(Baris(
            kode=", ".join(x.kode_batch for x in menunggu_dryer[:3])
                 + ("…" if len(menunggu_dryer) > 3 else ""),
            isi=f"{len(menunggu_dryer)} batch di dryer · {_kg(total)}"
                + (f" · {'/'.join(sorted(kondisi))}" if kondisi else ""),
            keadaan="belum dikeringkan — nyalakan mesin pengering",
            aksi="mulai_pengeringan", fase="dryer",
            sejak=min((x.created_at for x in menunggu_dryer if x.created_at), default=None),
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
            keadaan="belum ditempatkan — dryer, silo, atau tumpukan",
            aksi="pindah_tumpukan", nilai=b_.kode_batch, fase="baru",
            sejak=b_.created_at,
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
                     else "pindahkan ke dryer atau silo"),
            aksi="pindah_tumpukan", nilai=b_.kode_batch, sejak=b_.created_at,
            fase="baru",
        ))

    for lot in await _lot(db, pendinginan_selesai=True):
        b.menunggu.append(Baris(
            kode=lot.kode_lot, isi="sudah dingin, dryer perlu dikosongkan",
            keadaan="siap dipindah ke silo", aksi="pindah_silo",
            nilai=lot.kode_lot, fase="dryer",
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
        b.menunggu.append(Baris(
            kode=lot.kode_lot, isi="pengeringan selesai, sedang didinginkan",
            keadaan="nyatakan pendinginan selesai", aksi="selesai_pendinginan",
            nilai=lot.kode_lot, fase="dryer",
            sejak=lot.waktu_selesai_pengeringan,
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
        b.berjalan.append(Baris(
            kode=lot.kode_lot,
            isi=(f"⏸ berhenti — {macet.sebab}" if macet else "sedang dikeringkan")
                + (" · " + " · ".join(ka) if ka else " · kadar air belum dicatat")
                + ("".join(" · " + t for t in tambahan)),
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
        b.berjalan.append(Baris(
            kode=silo.nama_silo, isi=f"gabah kering · {_kg(await _silo_content_kg(db, silo.id))}",
            keadaan="siap digiling", aksi="mulai_giling", nilai=huruf, fase="silo",
        ))

    for p in (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "proses")
        .order_by(MillingProcess.id.desc())
    )).scalars().all():
        from app.penggilingan.gudang1.services.jeda import jeda_terbuka, tertahan_detik

        macet = await jeda_terbuka(db, "giling", p.id)
        tertahan = await tertahan_detik(db, "giling", p.id)
        b.berjalan.append(Baris(
            kode=p.kode_proses,
            isi=(f"⏸ berhenti — {macet.sebab}" if macet else "digiling")
                + f" · {_kg(p.berat_gabah_masuk_kg)} gabah masuk"
                + (f" · tertahan {tertahan / 3600:.1f} jam" if tertahan >= 60 else ""),
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
    if can_see_financials(user):
        s = await untuk_staff(db)
        b.menunggu += s.menunggu
        b.berjalan += s.berjalan
        # Staff & Direksi tak terikat satu gudang; keadaan fisik G1 tetap
        # perlu terlihat, tetapi sebagai kabar — bukan sebagai tugas mereka.
        if not await _is_g1_operator(user):
            b.berjalan += (await untuk_gudang1(db)).berjalan
    if await _is_g2_operator(user):
        pass    # Gudang 2 menyusul — lihat catatan di docs/RANCANGAN.md §11.
    return b
