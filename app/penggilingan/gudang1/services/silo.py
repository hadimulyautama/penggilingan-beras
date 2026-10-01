"""Logika bisnis silo Gudang 1 (penyimpanan gabah kering)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import input_time, now_local
from app.models import (
    DryingLot,
    DryingLotBatch,
    MillingProcess,
    MillingProcessSource,
    PurchaseBatch,
    Silo,
    SiloMovingLog,
    SiloStorage,
    Supplier,
    Warehouse,
)
from app.services.activity_log import log_activity
from app.penggilingan.gudang1.services.bobot import (
    NOL, Bobot, dari_batch, dari_batches)
from app.penggilingan.gudang1.services.bobot import jumlah as jumlah_bobot
from app.services.codegen import next_drying_lot_code
from app.services.jasa import (
    JasaError,
    kunci_silo,
    nama_pemilik,
    pastikan_satu_jasa_bernama,
)


def _silo_cap_kg(silo) -> float | None:
    return float(silo.kapasitas_ton) * 1000 if silo.kapasitas_ton is not None else None


def _ensure_cap(silo, nama: str, existing_kg: float, new_kg: float) -> None:
    """Tidak lagi menolak apa pun — silo tidak punya batas.

    Keputusan Direksi 2 September 2026: silo tidak perlu berbatas. Angka
    `kapasitas_ton` TETAP disimpan dan tetap ditampilkan di layar sebagai
    keterangan ("terisi 9,7 dari 20 ton"), karena orang perlu tahu seberapa
    penuh — tetapi ia tidak boleh lagi MENOLAK gabah yang sudah terlanjur
    datang dan berdiri di halaman.

    Fungsinya dipertahankan, bukan dihapus dari pemanggilnya: kalau suatu hari
    batas itu dikembalikan, tempatnya sudah jelas ada di sini — dan pemanggil
    tidak perlu dicari ulang satu per satu.
    """
    return None


class SiloError(Exception):
    """Kesalahan proses silo dengan pesan siap-tampil (args[0])."""


async def _g1_warehouse_id(db: AsyncSession) -> int:
    wid = (
        await db.execute(
            select(Warehouse.id).where(Warehouse.nama_gudang.like("Gudang 1%"))
        )
    ).scalars().first()
    if wid is None:
        raise SiloError("Data gudang 1 belum ada.")
    return wid


async def silos_g1(db: AsyncSession) -> list[Silo]:
    """Semua silo gabah kering Gudang 1, urut nama.

    Jumlahnya BUKAN dua. Ia ditentukan baris yang ada di tabel, dan Direksi
    boleh menambahnya — jadi tak ada satu pun tempat yang boleh menyebut
    "A dan B" sebagai kebenaran.
    """
    wid = await _g1_warehouse_id(db)
    return list((await db.execute(
        select(Silo).where(Silo.warehouse_id == wid).order_by(Silo.nama_silo)
    )).scalars().all())


async def silo_g1_by_id(db: AsyncSession, silo_id: int) -> Silo | None:
    wid = await _g1_warehouse_id(db)
    return (await db.execute(
        select(Silo).where(Silo.id == silo_id, Silo.warehouse_id == wid)
    )).scalars().first()


async def get_g1_silo(db: AsyncSession, letter: str) -> Silo | None:
    wid = await _g1_warehouse_id(db)
    stmt = select(Silo).where(
        Silo.warehouse_id == wid, Silo.nama_silo == f"Silo {letter}"
    )
    return (await db.execute(stmt)).scalars().first()


async def _active_storage(db: AsyncSession, silo_id: int) -> SiloStorage | None:
    stmt = select(SiloStorage).where(
        SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi"
    )
    return (await db.execute(stmt)).scalars().first()


async def _lot_bobot(db: AsyncSession, lot_id: int) -> Bobot:
    """Bobot seluruh batch sebuah lot pengeringan, berikut kepastiannya."""
    batches = (await db.execute(
        select(PurchaseBatch)
        .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
        .where(DryingLotBatch.drying_lot_id == lot_id)
    )).scalars().all()
    return dari_batches(batches)


async def _lot_kg(db: AsyncSession, lot_id: int) -> float:
    """Angka yang DIKETAHUI saja. Yang butuh kepastian memakai `_lot_bobot`."""
    return (await _lot_bobot(db, lot_id)).angka()


async def _silo_active_rows(db: AsyncSession, silo_id: int) -> list[SiloStorage]:
    """Semua penyimpanan aktif (terisi) di silo — bisa >1 baris untuk kering
    yang menunggu (tiap batch 1 baris, tanpa lot)."""
    return list(
        (
            await db.execute(
                select(SiloStorage).where(
                    SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi"
                )
            )
        ).scalars().all()
    )


async def giling_berjalan_untuk_silo(db: AsyncSession, silo_id: int) -> MillingProcess | None:
    """Giling yang SEDANG berjalan dan salah satu sumbernya ada di silo ini.

    SATU-SATUNYA cara yang benar menanyakan "silo ini sedang digiling?" sejak
    satu lot boleh datang dari beberapa silo (keputusan pemilik 24 September
    2026). Sebelumnya tiga tempat menanyakannya lewat `MillingProcess.silo_id`,
    dan kolom itu cuma menyebut silo PERTAMA: silo kedua tetap berkartu "siap
    digiling" — bertombol — padahal gabahnya sudah di mesin. Orang bisa memulai
    giling kedua atas gabah yang sama, dan dua rendemen lahir dari satu muatan.
    Itu keluhan pemilik 24 September tentang Gudang 2, di sisi Gudang 1.

    Kaki KEDUA (`silo_id`) tetap ada demi proses LAMA yang lahir sebelum
    `milling_process_sources`: ia tak punya baris sumber sama sekali, dan tanpa
    kaki ini giling lama yang sedang berputar akan terbaca "tidak ada".
    """
    from sqlalchemy import or_

    lewat_sumber = (
        select(MillingProcessSource.milling_process_id)
        .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
        .where(SiloStorage.silo_id == silo_id)
    )
    return (await db.execute(
        select(MillingProcess).where(
            MillingProcess.status == "proses",
            or_(MillingProcess.silo_id == silo_id,
                MillingProcess.id.in_(lewat_sumber)),
        ).limit(1)
    )).scalars().first()


async def silo_ids_proses(db: AsyncSession, proc: MillingProcess) -> list[int]:
    """Silo mana saja yang jadi sumber sebuah proses giling — id-nya, terurut.

    Diturunkan, TIDAK disimpan: sumbernya sudah tercatat baris per baris, dan
    himpunan yang disimpan dua kali adalah himpunan yang kelak berselisih.
    """
    ids = list((await db.execute(
        select(SiloStorage.silo_id)
        .join(MillingProcessSource,
              MillingProcessSource.silo_storage_id == SiloStorage.id)
        .where(MillingProcessSource.milling_process_id == proc.id)
        .distinct()
    )).scalars().all())
    # Proses lama tanpa baris sumber: penunjuk tunggalnya yang menjawab.
    if not ids and proc.silo_id:
        ids = [proc.silo_id]
    return sorted(i for i in ids if i)


async def _row_bobot(db: AsyncSession, row: SiloStorage) -> Bobot:
    if row.drying_lot_id:
        return await _lot_bobot(db, row.drying_lot_id)
    if row.purchase_batch_id:
        return dari_batch(await db.get(PurchaseBatch, row.purchase_batch_id))
    return NOL


async def _row_kg(db: AsyncSession, row: SiloStorage) -> float:
    return (await _row_bobot(db, row)).angka()


async def _silo_content_bobot(db: AsyncSession, silo_id: int) -> Bobot:
    """Isi silo SEKARANG berikut kepastiannya — layar memakai ini supaya
    truk yang belum ditimbang terbaca "≥ X kg · 1 truk belum ditimbang",
    bukan menghilang ke dalam jumlah (QA P6)."""
    return jumlah_bobot([await _row_bobot(db, r) for r in await _silo_active_rows(db, silo_id)])


async def _silo_content_kg(db: AsyncSession, silo_id: int) -> float:
    return (await _silo_content_bobot(db, silo_id)).angka()


async def _lot_suppliers(db: AsyncSession, lot_id: int) -> list[str]:
    """Asal bahan sebuah lot — pemasoknya, atau pemiliknya bila dititipkan.

    ⚠ DULU INNER JOIN, DAN ITU MENGHILANGKAN BARIS. Sejak `supplier_id` boleh
    NULL (migrasi 0064), lot berisi gabah jasa menampilkan daftar KOSONG di
    kartu silo — bukan angka salah, barisnya hilang, dan yang membacanya
    menyimpulkan silonya kosong. Kembarannya ada di `drying.py` dengan catatan
    yang sama; keduanya harus tetap sepakat.
    """
    rows = (await db.execute(
        select(Supplier.nama_supplier, PurchaseBatch.jasa_id)
        .select_from(DryingLotBatch)
        .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
        .outerjoin(Supplier, PurchaseBatch.supplier_id == Supplier.id)
        .where(DryingLotBatch.drying_lot_id == lot_id)
        .distinct()
    )).all()
    keluar: list[str] = []
    for nama, jasa_id in rows:
        sebutan = nama or await nama_pemilik(db, jasa_id) or "?"
        if sebutan not in keluar:
            keluar.append(sebutan)
    return keluar


@dataclass
class IsiSilo:
    """Satu baris isi silo."""
    asal: str          # 'pengeringan' | 'beli_kering'
    sebutan: str       # kode lot atau kode batch
    kg: float
    lot_id: int | None = None
    #: Pesanan jasa yang memiliki baris ini — None = milik pabrik.
    jasa_id: int | None = None
    #: "JAS-2610-007 Pak Budi", atau None untuk barang pabrik. Disimpan di
    #: barisnya supaya layar tak perlu bertanya lagi per baris.
    pemilik: str | None = None


#: Label ASAL untuk barang PABRIK. Kata "beli" hanya sah di sini.
#:
#: ⚠ Nilai `asal` di basis data tetap `beli_kering` untuk barang jasa juga, dan
#: itu disengaja: mengubah nilai enum menyentuh pembaca lain tanpa perlu, dan
#: nilai baru yang cuma dipakai satu layar adalah nilai yang pembaca berikutnya
#: tidak tahu harus diapakan. Yang dibetulkan LABELnya.
_LABEL_ASAL_PABRIK = {"pengeringan": "hasil pengeringan sendiri",
                      "beli_kering": "gabah beli kering"}

#: Label ASAL untuk barang JASA. Barang jasa TIDAK DIBELI, dan bukan "sendiri".
#:
#: Dua kata salah dalam satu kalimat kalau label pabrik dipakai apa adanya:
#: silo berisi gabah Pak Budi dari pengering + gabah Pak Budi yang dibawa
#: kering akan dilaporkan "hasil pengeringan sendiri & gabah beli kering" —
#: padahal tak ada yang dibeli dan tak ada yang milik sendiri. Dan kalimat itu
#: justru dibaca saat memutuskan apa yang digiling.
_LABEL_ASAL_JASA = {"pengeringan": "hasil pengeringan",
                    "beli_kering": "gabah kering dibawa langsung"}


def label_asal(asal: str, jasa_id: int | None) -> str:
    """Sebutan asal sebuah baris isi silo, mengikuti pemiliknya."""
    peta = _LABEL_ASAL_PABRIK if jasa_id is None else _LABEL_ASAL_JASA
    return peta.get(asal, asal)


async def isi_silo(db: AsyncSession, silo_id: int) -> list[IsiSilo]:
    """Rincian isi satu silo, satu baris penyimpanan satu entri.

    `asal` hanya dua: 'pengeringan' (lot yang dikeringkan sendiri di sini) dan
    'beli_kering' (gabah yang datang sudah kering). Pemisahan itulah yang
    menentukan apakah silo tercampur — bukan berapa banyak barisnya, karena
    dua lot pengeringan yang menumpuk masih satu asal.

    Ada sampai laporan karena isi silo yang tercampur harus TERBACA. Sebelum
    ini laporan hanya mengambil baris lot yang pertama ditemukan: gabah kering
    yang menumpuk di silo yang sama hilang dari laporan berikut beratnya, dan
    yang membaca mengira silo itu berisi lot saja.
    """
    rinci: list[IsiSilo] = []
    for r in await _silo_active_rows(db, silo_id):
        # Pemiliknya dibaca dari BARIS SILO-nya, bukan dari lot/batch di
        # belakangnya: baris itulah yang berada di dalam silo, dan `jasa_id`
        # di sana memang disimpan supaya pertanyaan "silo ini isinya milik
        # siapa" tak perlu dua join setiap kali ditanyakan.
        pemilik = await nama_pemilik(db, r.jasa_id)
        if r.drying_lot_id:
            lot = await db.get(DryingLot, r.drying_lot_id)
            rinci.append(IsiSilo("pengeringan", lot.kode_lot if lot else "lot",
                                 await _lot_kg(db, r.drying_lot_id), r.drying_lot_id,
                                 jasa_id=r.jasa_id, pemilik=pemilik))
        elif r.purchase_batch_id:
            b = await db.get(PurchaseBatch, r.purchase_batch_id)
            if b:
                rinci.append(IsiSilo("beli_kering", b.kode_batch,
                                     dari_batch(b).angka(),
                                     jasa_id=r.jasa_id, pemilik=pemilik))
    return rinci


def _tercampur(rinci: list[IsiSilo]) -> bool:
    """Dua ASAL berbeda dalam satu silo — DAN barangnya milik pabrik.

    ⚠ TANDA ⚠️ TERCAMPUR TIDAK DIPAKAI UNTUK SILO SEPEMILIK, dan itu keputusan
    pemilik, bukan kerapian: satu pesanan jasa memang boleh mengisi satu silo
    dengan gabah dari pengering DAN gabah kering yang dibawa langsung, lalu
    menggilingnya bersama. Pencampurannya dikehendaki orang yang punya
    barangnya.

    Tanda seru di situ melaporkan keadaan normal sebagai kejanggalan — dan
    tanda seru yang sering salah berhenti dibaca, termasuk pada hari ia benar.

    Untuk gabah PABRIK tandanya TETAP: di sana campuran asal memang kabar yang
    perlu dibaca sebelum memutuskan apa yang digiling.
    """
    if len({x.asal for x in rinci}) <= 1:
        return False
    pemilik = {x.jasa_id for x in rinci}
    return not (len(pemilik) == 1 and None not in pemilik)


def _sebut_isi(rinci: list[IsiSilo]) -> str:
    """Kalimat pendek untuk peringatan: apa yang sudah ada di dalam.

    Dikelompokkan per (pemilik, asal) — bukan per asal saja. Silo yang isinya
    satu pemilik akan menyebut pemiliknya SEKALI di depan, sebab itulah fakta
    yang menentukan apa yang boleh masuk berikutnya.
    """
    per: dict[tuple[str | None, str], float] = {}
    for x in rinci:
        kunci = (x.pemilik, x.asal)
        per[kunci] = per.get(kunci, 0.0) + x.kg
    pemilik = {x.pemilik for x in rinci}
    satu_pemilik = len(pemilik) == 1 and None not in pemilik
    bagian = [f"{label_asal(a, None if p is None else 1)} {_fmt_kg(kg)}"
              + ("" if satu_pemilik or p is None else f" ({p})")
              for (p, a), kg in per.items()]
    awalan = f"{pemilik.pop()} · " if satu_pemilik else ""
    return awalan + ", ".join(bagian)


def _fmt_kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


# ─────────────────────────── Masuk silo ───────────────────────────
@dataclass
class MasukResult:
    nama_silo: str
    isi: str
    kg: float
    tipe: str  # dari_pengeringan | langsung_kering
    digabung: bool = False  # True bila batch kering digabung ke lot silo yang ada
    #: Apa yang SUDAH ada di silo sebelum ini masuk — supaya peringatan
    #: menyebut isinya, bukan sekadar bahwa silo 'sudah berisi'. Silo yang
    #: mencampur hasil pengeringan sendiri dengan gabah beli kering adalah
    #: keadaan yang berbeda dari dua lot pengeringan yang menumpuk.
    isi_sebelumnya: str = ""
    #: True bila penggabungan ini mempertemukan DUA ASAL yang berbeda.
    campur_asal: bool = False
    #: Kode proses giling yang SEDANG BERJALAN di silo itu, bila ada. Gabah ini
    #: sudah didaftar sebagai sumber tambahannya — tetapi orang harus tahu,
    #: karena ia menambah bahan ke proses yang sedang jalan, bukan menyiapkan
    #: proses berikutnya.
    giling_berjalan: str | None = None
    #: Berat baris yang BARU masuk. Berbeda dari `kg`, yang pada gabah kering
    #: berarti seluruh isi silo sesudah penggabungan.
    kg_baris: float = 0.0
    #: "JAS-2610-007 Pak Budi" bila silo ini berisi barang titipan — None untuk
    #: barang pabrik. Dipakai kalimat balasan: operator yang baru menuang barang
    #: pelanggan perlu melihat nama itu di layar, bukan mengingat pilihannya.
    pemilik: str | None = None


async def masuk_silo(
    db: AsyncSession,
    *,
    user,
    nama_silo: str | None,
    kode_lot: str | None,
    kode_batch: str | None,
    tanggal=None, jam=None,
) -> MasukResult:
    if not nama_silo:
        raise SiloError("Sebutkan silo A atau B, contoh: `masukkan PGR-... ke silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise SiloError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    now = input_time(tanggal, jam)
    digabung = False
    campur_asal = False
    # ── SILONYA DIKUNCI sebelum isinya dibaca ──
    #
    # Penjaga pemilik di bawah berdiri di atas apa yang terbaca di sini. Tanpa
    # kunci, dua operator yang menuang barang dua pemilik ke silo yang sama pada
    # detik yang sama sama-sama membaca silo yang masih kosong, keduanya lolos,
    # dan silo berisi barang dua orang — keadaan yang tak bisa dibatalkan dengan
    # pembukuan. Lihat catatan panjang di `jasa.kunci_silo`.
    await kunci_silo(db, silo.id)
    # Dibaca SEBELUM apa pun ditambahkan — sesudahnya, yang baru masuk sudah
    # ikut terhitung dan peringatannya jadi menuduh dirinya sendiri.
    sebelum = await isi_silo(db, silo.id)
    isi_sebelumnya = _sebut_isi(sebelum)
    pemilik_sebelum = [x.jasa_id for x in sebelum]

    if kode_lot:
        # ── Dari pengeringan: silo BOLEH sudah berisi. ──
        #
        # Dulu "1 silo = 1 lot, silo harus kosong". Aturan itu punya sebab yang
        # sah: selama isi silo dipakai sebagai identitas apa-yang-digiling,
        # silo campuran membuat penggilingan mengambil sebagian saja. Sebab itu
        # hilang sejak isi proses giling didaftar sendiri di
        # `milling_process_sources` (migrasi 0031).
        #
        # Dan aturan itu punya harga yang nyata: dryer tidak boleh menerima
        # gabah baru selama lotnya belum pindah ke silo. Silo yang wajib kosong
        # berarti dryer macet setiap kali kedua silo terisi — dan kemacetan
        # itulah yang melahirkan tumpukan gabah, hal yang justru ingin
        # dihindari.
        # ── Lotnya DIKUNCI sebelum diperiksa ──
        #
        # Tanpa kunci, dua operator yang memasukkan lot yang sama ke silo
        # berbeda sama-sama lolos: keduanya memeriksa "belum ada di silo mana
        # pun" sebelum salah satunya menulis. Hasilnya satu lot berada di Silo
        # A dan Silo B sekaligus — keadaan yang tak mungkin ada di gudang.
        # Temuan QA P-K-05.
        #
        # Indeks unik parsial di migrasi 0040 menutupnya sebagai lapisan
        # terakhir; kunci ini yang membuat penolakannya jadi kalimat yang bisa
        # dibaca, bukan IntegrityError yang muncul sebagai galat 500.
        lot = (
            await db.execute(
                select(DryingLot).where(DryingLot.kode_lot == kode_lot)
                .with_for_update()
            )
        ).scalars().first()
        if lot is None:
            raise SiloError(f"Pengeringan {kode_lot} tidak ditemukan.")
        if lot.status != "selesai":
            raise SiloError(f"Pengeringan {kode_lot} belum selesai.")
        # Pendinginan SELESAI harus dinyatakan operator DULU (bukan dipicu oleh
        # pemindahan ini) — supaya downtime dryer terukur: lot bisa selesai dingin
        # sambil tetap di dryer menunggu silo kosong.
        if lot.waktu_selesai_pendinginan is None:
            raise SiloError(
                f"Pengeringan {kode_lot} belum dinyatakan selesai pendinginan. "
                f"Nyatakan `pendinginan selesai {kode_lot}` dulu."
            )
        dup = (
            await db.execute(
                select(SiloStorage.id).where(
                    SiloStorage.drying_lot_id == lot.id, SiloStorage.status == "terisi"
                )
            )
        ).first()
        if dup:
            raise SiloError(f"Pengeringan {kode_lot} sudah ada di silo.")
        kg = await _lot_kg(db, lot.id)
        # ── Pemilik isi silo harus TUNGGAL ──
        #
        # DITOLAK, bukan diperingatkan. Peringatan `campur_asal` di bawah
        # sengaja cuma peringatan sebab akibatnya angka yang perlu dibaca
        # hati-hati; di sini akibatnya barang orang lain ikut tergiling, dan
        # tak ada pembetulan pembukuan yang mengembalikannya.
        try:
            pemilik_baris = await pastikan_satu_jasa_bernama(
                db, pemilik_sebelum + [lot.jasa_id])
        except JasaError as e:
            raise SiloError(f"❌ Silo {nama_silo}: {e.args[0]}") from None
        # Isi yang sudah ada ikut disebut. `_ensure_cap` memang tidak menolak
        # apa pun hari ini, tetapi memberinya angka 0 berarti menanam
        # kebohongan yang baru terbaca pada hari batas itu dikembalikan.
        _ensure_cap(silo, nama_silo, sum(x.kg for x in sebelum), kg)
        baris = SiloStorage(
            silo_id=silo.id, drying_lot_id=lot.id, tipe_masuk="dari_pengeringan",
            tanggal_masuk=now, input_by=user.id, status="terisi",
            jasa_id=pemilik_baris,
        )
        db.add(baris)
        kg_baris = kg
        batch_ids = (
            await db.execute(
                select(DryingLotBatch.purchase_batch_id).where(
                    DryingLotBatch.drying_lot_id == lot.id
                )
            )
        ).scalars().all()
        for bid in batch_ids:
            b = await db.get(PurchaseBatch, bid)
            if b:
                b.status_batch = "di_silo"
        # Pendinginan sudah dinyatakan selesai (dijaga di atas) — pindah ini
        # murni perpindahan fisik dryer → silo, tidak menyentuh waktu pendinginan.
        # Silo yang sudah berisi TETAP menerima — tetapi itu tidak ideal, dan
        # penandanya dibawa keluar supaya layar bisa memperingatkan. Idealnya
        # silo tujuan sudah kosong karena satu proses milling baru selesai.
        # Dibaca dari `sebelum`, BUKAN dihitung ulang di sini. Menghitung
        # ulang sesudah `db.add` membuat baris yang baru saja ditambahkan ikut
        # terhitung — autoflush menuliskannya lebih dulu — sehingga silo yang
        # kosong pun dilaporkan "sudah berisi sebelumnya". Peringatan palsu
        # melatih orang mengabaikan peringatan yang sungguhan.
        digabung = bool(sebelum)
        # ⚠ Peringatan campur-asal TIDAK dipasang untuk silo sepemilik jasa:
        # satu pesanan memang boleh mengisi satu silo dari pengering DAN dengan
        # gabah kering yang dibawa langsung. Alasan lengkapnya di `_tercampur`.
        campur_asal = (pemilik_baris is None
                       and any(x.asal == "beli_kering" for x in sebelum))
        isi, tipe = kode_lot, "dari_pengeringan"

    elif kode_batch:
        # ── Gabah kering langsung: batch jadi lot di silo; boleh menumpuk. ──
        batch = (
            await db.execute(
                select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode_batch)
            )
        ).scalars().first()
        if batch is None:
            raise SiloError(f"Batch {kode_batch} tidak ditemukan.")
        if batch.kondisi_gabah != "kering":
            raise SiloError(
                f"Batch {kode_batch} gabah basah — harus dikeringkan dulu, "
                "tidak bisa langsung ke silo."
            )
        in_lot = (
            await db.execute(
                select(DryingLotBatch.id).where(DryingLotBatch.purchase_batch_id == batch.id)
            )
        ).first()
        if in_lot or batch.status_batch == "di_silo":
            raise SiloError(f"Batch {kode_batch} sudah masuk pengeringan atau silo.")
        kg_new = dari_batch(batch).angka()

        # Gabah kering MENUNGGU lepas di silo (SiloStorage batch, TANPA lot).
        #
        # Larangan mencampurnya dengan lot pengeringan sudah dicabut. Sebabnya
        # dulu sah: selama isi silo dipakai sebagai identitas apa-yang-digiling,
        # campuran membuat penggilingan mengambil sebagian saja. Sejak isi
        # proses giling didaftar sendiri (`milling_process_sources`, migrasi
        # 0031), seluruh isi silo ikut terhitung — dan larangan itu tinggal
        # memaksa gabah menganggur di silo lain yang belum tentu ada.
        try:
            pemilik_baris = await pastikan_satu_jasa_bernama(
                db, pemilik_sebelum + [batch.jasa_id])
        except JasaError as e:
            raise SiloError(f"❌ Silo {nama_silo}: {e.args[0]}") from None
        existing_kg = await _silo_content_kg(db, silo.id)
        _ensure_cap(silo, nama_silo, existing_kg, kg_new)
        baris = SiloStorage(
            silo_id=silo.id, purchase_batch_id=batch.id, drying_lot_id=None,
            tipe_masuk="langsung_kering", tanggal_masuk=now,
            input_by=user.id, status="terisi",
            jasa_id=pemilik_baris,
        )
        db.add(baris)
        kg_baris = kg_new
        batch.status_batch = "di_silo"
        # "Digabung" kini berarti silo memang sudah berisi sesuatu — apa pun
        # isinya, lot pengeringan maupun gabah kering yang datang lebih dulu.
        digabung = bool(sebelum)
        # Lihat catatan di cabang lot: sepemilik bukan kejanggalan.
        campur_asal = (pemilik_baris is None
                       and any(x.asal == "pengeringan" for x in sebelum))
        isi, tipe = batch.kode_batch, "langsung_kering"
        kg = existing_kg + kg_new
    else:
        raise SiloError(
            "Sebutkan pengeringan atau batch yang dimasukkan, contoh:\n"
            "`masukkan PGR-20260702-01 ke silo A`"
        )

    silo.status = "terisi"

    # ── Gabah yang datang saat silo SEDANG DIGILING ──
    #
    # Gilingnya tidak berhenti dan tidak diulang — bahannya yang bertambah.
    # Menolak gabah di sini akan menghentikan mesin yang sedang jalan; membiarkan
    # gabahnya masuk tanpa dicatat lebih buruk lagi: ia tetap tergiling secara
    # fisik, sementara `berat_gabah_masuk_kg` tinggal di angka lama — dan
    # rendemen proses itu terbaca melambung tanpa ada yang tahu sebabnya.
    #
    # Maka ia didaftar sebagai SUMBER tambahan proses yang sedang berjalan,
    # tepat seperti isi silo yang lain saat giling dimulai.
    # Pertanyaannya "silo ini ada di antara sumber proses yang berjalan?" —
    # `silo_id` cuma menyebut silo pertama, jadi gabah yang datang ke silo
    # KEDUA sebuah giling dulu tak ikut didaftar: ia tergiling, tapi
    # `berat_gabah_masuk_kg` tinggal di angka lama dan rendemennya melambung.
    giling = await giling_berjalan_untuk_silo(db, silo.id)
    giling_kode = None
    if giling is not None:
        await db.flush()          # baris barunya perlu id sebelum ditaut
        # Bahan tambahan dibaca berikut KEPASTIANNYA, seperti saat giling
        # dimulai (QA P6): yang belum punya angka dicatat NULL — bukan 0,
        # yang ditolak CHECK berat_positif — dan prosesnya ditandai belum
        # final supaya poller melengkapinya begitu truknya ditimbang.
        bobot_baris = await _row_bobot(db, baris)
        kg_baris = bobot_baris.angka()
        db.add(MillingProcessSource(
            milling_process_id=giling.id, silo_storage_id=baris.id,
            drying_lot_id=baris.drying_lot_id,
            purchase_batch_id=baris.purchase_batch_id, berat_kg=bobot_baris.kg,
        ))
        # Baris baru ini kini ADA DI DALAM mesin: klaimnya ikut dipasang, supaya
        # ia tak bisa direbut proses lain dan supaya `selesai_giling`
        # melepaskannya bersama yang lain.
        baris.milling_process_id = giling.id
        # ── Ditambah oleh BASIS DATA, bukan dibaca-lalu-ditulis ──
        #
        # `x = x + n` di Python membaca nilai lama ke memori lebih dulu. Dua
        # pemasukan yang datang bersamaan sama-sama membaca angka yang sama,
        # lalu masing-masing menulis "lama + miliknya" — jadi tambahan yang
        # satu MENGHAPUS tambahan yang lain. Temuan QA P-K-14, dan kerusakannya
        # sunyi: berat bahan tercatat kurang, rendemen terbaca melambung, dan
        # tak ada satu pun pesan.
        #
        # Ditambah lewat SQL, angkanya tak pernah singgah di Python.
        # Bahan yang belum pasti menurunkan tanda finalnya; yang pasti tak
        # menaikkannya — hanya poller yang boleh menyatakan final lagi.
        tanda = {} if bobot_baris.pasti else {"bobot_masuk_final": False}
        await db.execute(
            update(MillingProcess)
            .where(MillingProcess.id == giling.id)
            .values(berat_gabah_masuk_kg=(
                func.coalesce(MillingProcess.berat_gabah_masuk_kg, 0) + kg_baris), **tanda)
        )
        await db.refresh(giling, ["berat_gabah_masuk_kg", "bobot_masuk_final"])
        giling_kode = giling.kode_proses
        await log_activity(
            db, table_name="milling_process", record_id=giling.id, action="UPDATE",
            changed_by=user.id, field_name="berat_gabah_masuk_kg",
            new_value=f"{giling.kode_proses} +{isi} ({kg_baris:.0f}kg) — "
                      f"masuk saat giling berjalan",
        )

    # Id barisnya baru ada sesudah flush, dan yang di atas hanya dijalankan
    # bila kebetulan ada giling berjalan. Tanpa baris ini, `baris.id` bisa
    # None — dan jejak audit yang menunjuk None tak bisa dibatalkan sama
    # sekali.
    await db.flush()

    # ── Yang dicatat id BARIS penyimpanan, bukan id SILO ──
    #
    # Dulu `record_id=silo.id`. Pembatalan lalu mencari "baris terbaru di silo
    # itu" — yaitu milik siapa pun yang terakhir mengisi. Budi membatalkan
    # entrinya sendiri dan yang hilang adalah entri Sari, tanpa satu pun
    # pesan. Temuan QA P-K-08.
    #
    # Id baris menunjuk satu hal dan hanya satu hal, jadi pembatalan tak perlu
    # menebak lagi. Baris lama yang terlanjur mencatat id silo dikenali dari
    # ketiadaan tag `aksi` dan tetap ditangani cara lama.
    await log_activity(
        db,
        table_name="silo_storage",
        record_id=baris.id,
        action="UPDATE" if digabung else "INSERT",
        field_name="gabung" if digabung else None,
        aksi="silo_gabung" if digabung else "silo_masuk",
        changed_by=user.id,
        new_value=f"Silo {nama_silo} <- {isi} ({tipe}{'+gabung' if digabung else ''}, {kg:.0f}kg)",
    )
    await db.commit()
    return MasukResult(nama_silo=nama_silo, isi=isi, kg=kg, tipe=tipe,
                       digabung=digabung, isi_sebelumnya=isi_sebelumnya,
                       campur_asal=campur_asal, giling_berjalan=giling_kode,
                       kg_baris=kg_baris,
                       pemilik=await nama_pemilik(db, pemilik_baris))


# ─────────────────── Log pemindahan dryer -> silo ───────────────────
async def _lot_active_storage(db: AsyncSession, lot_id: int) -> SiloStorage | None:
    return (
        await db.execute(
            select(SiloStorage).where(
                SiloStorage.drying_lot_id == lot_id, SiloStorage.status == "terisi"
            )
        )
    ).scalars().first()


async def moving_started(
    db: AsyncSession, *, user, nama_silo: str | None, kode_lot: str | None
) -> tuple[str, str | None]:
    """Catat log 'mulai pemindahan' ke silo. Gabah masih di dryer."""
    if not kode_lot:
        raise SiloError(
            "Sebutkan pengeringannya, contoh: `mulai pindah PGR-20260702-01 ke silo A`"
        )
    lot = (
        await db.execute(select(DryingLot).where(DryingLot.kode_lot == kode_lot))
    ).scalars().first()
    if lot is None:
        raise SiloError(f"Pengeringan {kode_lot} tidak ditemukan.")
    silo = await get_g1_silo(db, nama_silo) if nama_silo else None
    now = now_local()
    ml = SiloMovingLog(
        drying_lot_id=lot.id,
        silo_id=silo.id if silo else None,
        tipe="mulai",
        waktu=now,
        input_by=user.id,
    )
    db.add(ml)
    await db.flush()
    # CATATAN: pendinginan selesai TIDAK diset di sini — itu keputusan operator
    # terpisah (`pendinginan selesai PGR-...`) demi ukuran downtime dryer.
    await log_activity(
        db, table_name="silo_moving_logs", record_id=ml.id, action="INSERT",
        changed_by=user.id, new_value=f"mulai pindah {lot.kode_lot}",
    )
    await db.commit()
    return lot.kode_lot, nama_silo


@dataclass
class MovingDoneResult:
    kode_lot: str
    nama_silo: str
    kondisi: str  # "intake" (baru masuk) | "already" (sudah tercatat sebelumnya)
    kg: float | None


async def moving_finished(
    db: AsyncSession, *, user, nama_silo: str | None, kode_lot: str | None
) -> MovingDoneResult:
    """Pemindahan ke silo selesai. Kondisional: intake bila belum, else log saja."""
    if not kode_lot:
        raise SiloError(
            "Sebutkan pengeringannya, contoh: `pemindahan PGR-20260702-01 ke silo A selesai`"
        )
    lot = (
        await db.execute(select(DryingLot).where(DryingLot.kode_lot == kode_lot))
    ).scalars().first()
    if lot is None:
        raise SiloError(f"Pengeringan {kode_lot} tidak ditemukan.")

    # Bila silo tujuan tak disebut ("pemindahan selesai"), ambil dari log
    # 'mulai pindah' sebelumnya.
    if not nama_silo:
        ml_mulai = (
            await db.execute(
                select(SiloMovingLog)
                .where(
                    SiloMovingLog.drying_lot_id == lot.id,
                    SiloMovingLog.tipe == "mulai",
                    SiloMovingLog.silo_id.is_not(None),
                )
                .order_by(SiloMovingLog.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if ml_mulai:
            silo_mulai = await db.get(Silo, ml_mulai.silo_id)
            if silo_mulai:
                nama_silo = silo_mulai.nama_silo.replace("Silo ", "")

    existing = await _lot_active_storage(db, lot.id)
    if existing:
        # Sudah tercatat di silo -> cukup log 'selesai'.
        silo = await db.get(Silo, existing.silo_id)
        ml = SiloMovingLog(
            drying_lot_id=lot.id, silo_id=existing.silo_id, tipe="selesai",
            waktu=now_local(), input_by=user.id,
        )
        db.add(ml)
        await db.flush()
        await log_activity(
            db, table_name="silo_moving_logs", record_id=ml.id, action="INSERT",
            changed_by=user.id, new_value=f"selesai pindah {lot.kode_lot}",
        )
        await db.commit()
        nama = silo.nama_silo.replace("Silo ", "") if silo else "-"
        return MovingDoneResult(kode_lot=lot.kode_lot, nama_silo=nama, kondisi="already", kg=None)

    # Belum di silo -> lakukan intake (state: di silo + dryer kosong).
    res = await masuk_silo(db, user=user, nama_silo=nama_silo, kode_lot=kode_lot, kode_batch=None)
    silo = await get_g1_silo(db, res.nama_silo)
    ml = SiloMovingLog(
        drying_lot_id=lot.id, silo_id=silo.id if silo else None, tipe="selesai",
        waktu=now_local(), input_by=user.id,
    )
    db.add(ml)
    await db.flush()
    await log_activity(
        db, table_name="silo_moving_logs", record_id=ml.id, action="INSERT",
        changed_by=user.id, new_value=f"selesai pindah {lot.kode_lot} (intake)",
    )
    await db.commit()
    return MovingDoneResult(
        kode_lot=lot.kode_lot, nama_silo=res.nama_silo, kondisi="intake", kg=res.kg
    )


# ─────────────────────────── Keluar silo ───────────────────────────
async def keluar_silo(db: AsyncSession, *, user, nama_silo: str | None, tanggal=None, jam=None) -> str:
    if not nama_silo:
        raise SiloError("Sebutkan silo yang dikosongkan, contoh: `kosongkan silo A`")
    silo = await get_g1_silo(db, nama_silo)
    if silo is None:
        raise SiloError(f"Silo {nama_silo} Gudang 1 tidak ditemukan.")
    storage = await _active_storage(db, silo.id)
    if storage is None:
        raise SiloError(f"Silo {nama_silo} sudah kosong.")
    keluar = input_time(tanggal, jam)
    if storage.tanggal_masuk and keluar < storage.tanggal_masuk:
        raise SiloError(
            f"Tanggal keluar lebih awal dari masuk silo "
            f"({storage.tanggal_masuk:%d-%m-%Y %H:%M})."
        )
    storage.status = "kosong"
    storage.tanggal_keluar = keluar
    silo.status = "kosong"
    await log_activity(
        db,
        table_name="silo_storage",
        record_id=silo.id,
        action="UPDATE",
        changed_by=user.id,
        field_name="status",
        new_value="kosong",
    )
    await db.commit()
    return nama_silo


# ─────────────────────────── Laporan silo ───────────────────────────
async def laporan_silo(db: AsyncSession, nama_silo: str | None = None) -> str:
    """Status silo Gudang 1 (isi, supplier, kapasitas). `nama_silo` mem-filter
    ke satu silo (mis. 'A') bila disebut."""
    wid = await _g1_warehouse_id(db)
    stmt = select(Silo).where(Silo.warehouse_id == wid)
    if nama_silo:
        stmt = stmt.where(func.upper(Silo.nama_silo).like(f"%{nama_silo.upper()}%"))
    silos = (await db.execute(stmt.order_by(Silo.nama_silo))).scalars().all()
    if not silos:
        if nama_silo:
            return f"Silo {nama_silo} tidak ditemukan di Gudang 1."
        return "Belum ada silo di Gudang 1."
    now = now_local()
    judul = f"🏗️ Status Silo {nama_silo}:" if nama_silo else "🏗️ Status silo Gudang 1:"
    lines = [judul]
    for silo in silos:
        cap = (
            f"maks {float(silo.kapasitas_ton):g} ton"
            if silo.kapasitas_ton is not None
            else "kapasitas belum diatur"
        )
        rows = await _silo_active_rows(db, silo.id)
        if not rows:
            lines.append(f"• {silo.nama_silo}: kosong ({cap})")
            continue

        # SELURUH isi disebut, bukan baris pertama yang kebetulan ditemukan.
        # Silo boleh menampung hasil pengeringan sendiri bersama gabah yang
        # dibeli sudah kering — dan justru karena boleh, komposisinya harus
        # terbaca di sini. Yang membaca laporan tidak berdiri di depan silo.
        rinci = await isi_silo(db, silo.id)
        total = sum(x.kg for x in rinci)
        tua = min((r.tanggal_masuk for r in rows), default=now)
        jam = (now - tua).total_seconds() / 3600

        bagian: list[str] = []
        for x in rinci:
            if x.asal == "pengeringan":
                sups = ", ".join(await _lot_suppliers(db, x.lot_id)) if x.lot_id else ""
                bagian.append(x.sebutan + (f" ({sups})" if sups else "")
                              + f" {_fmt_kg(x.kg)}")
            else:
                # Kata "beli" hanya untuk barang pabrik — barang jasa tidak
                # dibeli. Labelnya mengikuti pemiliknya; nilai `asal` di basis
                # data tetap `beli_kering`. Lihat `label_asal`.
                bagian.append(f"{x.sebutan} ({label_asal(x.asal, x.jasa_id)})"
                              f" {_fmt_kg(x.kg)}")

        # Satu pemilik jasa → sebut pemiliknya di kepala baris, dan JANGAN beri
        # tanda bahaya: campuran itu dikehendaki orang yang punya barangnya.
        pemilik_silo = {x.jasa_id for x in rinci}
        sebutan_pemilik = ""
        if len(pemilik_silo) == 1 and None not in pemilik_silo:
            sebutan_pemilik = f" · {rinci[0].pemilik}"
        tanda = " ⚠️ TERCAMPUR" if _tercampur(rinci) else ""
        lines.append(
            f"• {silo.nama_silo}: terisi{tanda}{sebutan_pemilik} — {_fmt_kg(total)}, "
            f"{jam:.0f} jam ({cap})"
        )
        for b in bagian:
            lines.append(f"    – {b}")
        if _tercampur(rinci):
            lines.append("    _Hasil pengeringan sendiri & gabah beli kering "
                         "dalam satu silo — digiling sebagai satu proses._")
        elif sebutan_pemilik and len({x.asal for x in rinci}) > 1:
            lines.append("    _Satu pemilik, digiling sebagai satu proses._")
        if not any(x.asal == "pengeringan" for x in rinci):
            lines.append(f"  _Ketik `giling {silo.nama_silo}` untuk membentuk "
                         "lot & giling._")
    return "\n".join(lines)
