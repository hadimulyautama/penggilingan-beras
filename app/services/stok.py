"""Stok PK Gudang 1 — hasil giling yang masih ada, dirinci per lot.

Satu angka gabungan menjawab "berapa" tetapi tidak menjawab "yang mana", dan
di gudang pertanyaan kedua yang lebih sering muncul: PK mana yang sudah lama
menumpuk, PK mana yang gabahnya dari pemasok yang sedang dipersoalkan. Maka
barisnya adalah LOT GILING — satuan yang sama dengan yang tertulis di kartu
dan di catatan, jadi orang tak perlu menerjemahkan apa pun.

Gudang 2 menyusul di bawah, tetapi dengan satuan yang BERBEDA — per tempat,
bukan per lot — dan alasannya ditulis panjang di sana: PK dari beberapa asal
dituang ke silo yang sama, jadi "sisa lot ini berapa" memang tak punya
jawaban di sana.

Barang jadi Gudang 2 (beras putih, menir, bekatul) dan kemasan masih belum
ikut. Keduanya subjek lain — yang KELUAR dari penyosohan, bukan yang menunggu
disosoh — dan menempelkannya di halaman yang sama akan membuat satu layar
menjawab dua pertanyaan sekaligus.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import MillingProcess
from app.penggilingan.gudang1.services.bobot import dari_batch
from app.penggilingan.gudang1.services.milling import KELAS_PK, kelas_pk


@dataclass
class LotPk:
    """Sisa PK satu lot giling, beserta asal gabahnya."""

    kode: str
    #: Yang masih ada di Gudang 1 = dihasilkan − dikirim − dijual langsung.
    tersedia: float
    dihasilkan: float
    dikirim: float
    #: Berat gabah yang masuk — penyebut rendemen.
    bahan_kg: float = 0.0
    #: False = ada bahan yang masih perkiraan / belum ditimbang saat giling
    #: dimulai; angkanya bagian yang diketahui saja, dibetulkan poller (P6).
    bahan_final: bool = True
    #: Berapa persen gabah keluar jadi PK. None bila bahannya tak diketahui.
    rendemen: float | None = None
    #: Kelas PK yang keluar dari lot ini: "KS", "KL", atau "MIX".
    #:
    #: Disimpan sebagai daftar, bukan diringkas jadi satu kata seperti
    #: "campuran". "Gabah campuran" terbaca seperti nama varietas, padahal yang
    #: dimaksud adalah dua asal-usul yang berbeda dalam satu lot: gabah yang
    #: datang basah lalu kami keringkan sendiri (jadi PK KS) bercampur gabah
    #: yang datang sudah kering (jadi PK KL). Saat digiling keduanya sama-sama
    #: kering; yang membedakan adalah kelas PK yang keluar.
    #:
    #: Sengaja tidak memakai `pk_jenis`: ia membaca penunjuk TUNGGAL di
    #: `MillingProcess`, bentuk peninggalan masa ketika satu silo tak boleh
    #: dicampur. Begitu boleh, penunjuk itu menyebut salah satu sumber dan
    #: mendiamkan sisanya — dan lot bercampur akan mengaku basah saja.
    kelas: str | None = None
    #: Rincian bahan: (pemasok · kode batch, berat, kapan gabahnya masuk).
    #: Bentuknya sama dengan rincian di kartu-kartu lain, supaya mata membaca
    #: keduanya dengan cara yang sama.
    bahan: list[tuple[str, str, str]] = field(default_factory=list)
    tanggal: str | None = None
    #: Sudah berapa lama PK ini menumpuk — dalam HARI, mis. "0 hari", "12 hari".
    #:
    #: Dihitung sejak giling DITUTUP: sebelum itu PK-nya masih keluar dari
    #: mesin, jadi "menumpuk" belum berarti apa-apa. Untuk yang mesinnya masih
    #: menyala, dihitung sejak mulai — itu tetap menjawab "sudah sejak kapan
    #: barang ini ada di lantai", yang memang pertanyaannya.
    #:
    #: Satuannya HARI, bukan jam-menit seperti kartu antrean. Antrean bertanya
    #: "apakah ini tertahan sekarang" — dan di sana selisih dua jam berarti
    #: sesuatu. Stok bertanya "sudah berapa lama uang ini diam", dan pada
    #: pertanyaan itu jam dan menit cuma kebisingan yang berubah tiap kali
    #: halaman dibuka.
    lama: str = ""
    #: Masih menyala mesinnya. PK-nya sudah ada, tapi angkanya belum final.
    berjalan: bool = False
    #: Mutu PK: (label, nilai) — kadar air, butir patah, susut. Kosong berarti
    #: belum pernah dinilai.
    #:
    #: RATA-RATA per KOLOM, atas catatan yang mengisi kolom itu — bukan catatan
    #: terbaru. Mutu dicatat berulang selama giling berjalan (keputusan pemilik
    #: 24 September 2026), dan tombolnya sendiri menjanjikan rata-rata; kartu
    #: yang menggambar nilai terbaru membuat satu lot punya dua angka mutu yang
    #: berbeda di dua layar. Hitungannya `milling.qc_rata_banyak`.
    mutu: list[tuple[str, str]] = field(default_factory=list)

    #: Sudah DIMINTA operator Gudang 2 (nama peminta), atau None.
    #:
    #: Kartu yang sudah diminta tak menawarkan tombol "Minta lot ini" lagi: tombol
    #: yang ditekan dua kali karena layarnya tak berubah adalah tombol yang
    #: mengajari orang menekan dua kali. Pagar sungguhannya tetap di basis data
    #: (indeks parsial `uq_permintaan_pk_terbuka`) — layar tak bisa menjaga dua
    #: permintaan yang tiba pada detik yang sama.
    diminta_oleh: str | None = None

    #: Giling sudah DITUTUP tetapi hasilnya tak pernah dicatat — bukan nol,
    #: melainkan tidak diketahui.
    #:
    #: "Selesai giling" tidak meminta berat PK; ia hanya menutup prosesnya. Jadi
    #: operator bisa menutup giling tanpa satu pun angka hasil, dan lot itu
    #: dulu HILANG dari layar ini karena tersedianya nol. Yang hilang dari layar
    #: tidak hilang dari lantai gudang: PK-nya ada, cuma tak ada yang tahu
    #: berapa. Lebih baik baris yang mengaku tidak tahu daripada gudang yang
    #: tampak kosong.
    belum_dicatat: bool = False


def _tgl(d) -> str:
    return d.strftime("%d/%m") if d else "?"


def _hari(sejak) -> str:
    """"0 hari", "1 hari", "12 hari". Kosong bila waktunya tak diketahui."""
    if sejak is None:
        return ""
    detik = (now_local() - sejak).total_seconds()
    if detik < 0:
        return ""
    return f"{int(detik // 86400)} hari"


def _kg(n) -> str:
    return f"{float(n or 0):,.0f} kg".replace(",", ".")


def _baris_bahan(b, nama_pemasok: str | None) -> tuple[str, str, str]:
    """Nama pemasok SENDIRIAN di baris atas; kode-kodenya turun ke bawah.

    Digabung ("Kelompok Tani Sumber Rejeki · GB-20260904-10") baris itu
    membungkus di ponsel dan kodenya terlempar ke baris kedua sendirian —
    yang dipindai mata justru namanya, dan nama yang terpotong oleh kode
    membuat daftar ini berhenti bisa dibaca sekilas.

    Di lingkup modul supaya versi satuan dan versi banyak-sekaligus memakai
    bentuk yang SAMA. Dua tempat yang menyusun baris yang sama akan berbeda
    suatu hari, dan yang membacanya tak akan tahu mana yang benar.
    """
    nama = nama_pemasok or "?"
    k = (b.kondisi_gabah or "").strip().lower()
    # Kode pengeringannya TIDAK ikut. Tiga kode dalam satu baris memaksanya
    # membungkus sampai tiga baris di ponsel, dan dari ketiganya ia yang
    # paling sedikit menjawab pertanyaan kartu ini — "gabah siapa, berapa".
    ket = f"{b.kode_batch} · masuk {_tgl(b.tanggal_pembelian)}"
    if k in KELAS_PK:
        ket += f" · {KELAS_PK[k]}"
    return (nama, dari_batch(b).teks(), ket)


async def _bahan(db: AsyncSession, proc) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Daftar batch gabah yang masuk sebuah lot giling — SATU BARIS PER BATCH.

    Beratnya berat PEMBELIAN — berat saat gabahnya ditimbang masuk. Bukan
    pilihan: `drying_lot_batches` cuma penghubung, tanpa kolom berat, jadi
    berapa kilo TIAP batch yang akhirnya masuk silo setelah dikeringkan memang
    tak pernah tercatat; yang tercatat berat MUATANNYA. Membaginya rata akan
    terlihat rapi dan tidak benar.

    Karena itu jumlah baris-baris ini TIDAK sama persis dengan "Bahan" di
    atasnya: selisihnya susut pengeringan, dan itu memang nyata. Kata "dibeli"
    dulu ditempel di tiap barisnya sebagai pagar terhadap salah-jumlah; pemilik
    membuangnya karena membuat baris jadi ramai. Yang tersisa sebagai penjelas
    adalah tanggal "masuk" di baris bawahnya — itu tanggal timbang, bukan
    tanggal giling.

    Sebelumnya bahan dari satu pengeringan digabung jadi satu baris bernama dua
    pemasok sekaligus. Hasilnya: kepala berbunyi "BATCH ASAL · 1" sementara
    barisnya berbunyi "2 batch", nama pemasoknya berdempet sampai membungkus
    baris, dan bobot per batch — yang justru diminta — tak muncul sama sekali.
    """
    from app.models import MillingProcessSource, PurchaseBatch, Supplier
    from app.penggilingan.gudang1.models.gudang1 import DryingLotBatch
    from app.penggilingan.gudang1.services.milling import sumber_batch

    async def _baris(b) -> tuple[str, str, str]:
        sup = await db.get(Supplier, b.supplier_id)
        return _baris_bahan(b, sup.nama_supplier if sup else None)

    baris = (await db.execute(
        select(MillingProcessSource)
        .where(MillingProcessSource.milling_process_id == proc.id)
        .order_by(MillingProcessSource.id))).scalars().all()

    bahan: list[tuple[str, str, str]] = []
    kondisi: set[str] = set()
    terlihat: set[int] = set()

    async def _tambah(b) -> None:
        if b is None or b.id in terlihat:
            return                      # satu batch tak boleh terdaftar dua kali
        terlihat.add(b.id)
        k = (b.kondisi_gabah or "").strip().lower()
        if k:
            kondisi.add(k)
        bahan.append(await _baris(b))

    if not baris:
        # Proses lama sebelum penautan timbang: penunjuknya yang dipakai.
        for b, _harga, _lewat in await sumber_batch(db, proc):
            await _tambah(b)
    else:
        for s in baris:
            if s.drying_lot_id:
                for b in (await db.execute(
                    select(PurchaseBatch)
                    .join(DryingLotBatch,
                          DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                    .where(DryingLotBatch.drying_lot_id == s.drying_lot_id)
                    .order_by(PurchaseBatch.id))).scalars().all():
                    await _tambah(b)
            elif s.purchase_batch_id:
                await _tambah(await db.get(PurchaseBatch, s.purchase_batch_id))

    return bahan, [k for k in ("basah", "kering") if k in kondisi]


async def _bahan_banyak(db: AsyncSession, proses) -> dict[int, tuple[list, list[str]]]:  # noqa: C901
    """`_bahan` untuk banyak lot giling sekaligus — empat kueri, bukan 4×N.

    Jawabannya harus SAMA PERSIS dengan versi satuan, termasuk urutan baris
    dan aturan "satu batch tak boleh terdaftar dua kali". Percepatan yang
    mengubah isi laporan bukan percepatan. Temuan QA P-S-02.
    """
    from app.models import MillingProcessSource, PurchaseBatch, Supplier
    from app.penggilingan.gudang1.models.gudang1 import DryingLotBatch

    daftar = list(proses)
    if not daftar:
        return {}
    ids = [p.id for p in daftar]

    sumber = list((await db.execute(
        select(MillingProcessSource)
        .where(MillingProcessSource.milling_process_id.in_(ids))
        .order_by(MillingProcessSource.id))).scalars().all())
    per_proses: dict[int, list] = {}
    for s in sumber:
        per_proses.setdefault(s.milling_process_id, []).append(s)

    # Batch di balik tiap lot pengeringan, terurut id — urutan yang sama
    # dengan `ORDER BY PurchaseBatch.id` pada versi satuan.
    lot_ids = {s.drying_lot_id for s in sumber if s.drying_lot_id}
    lot_batch: dict[int, list[int]] = {}
    batch_ids = {s.purchase_batch_id for s in sumber if s.purchase_batch_id}
    if lot_ids:
        for lot_id, bid in (await db.execute(
            select(DryingLotBatch.drying_lot_id, DryingLotBatch.purchase_batch_id)
            .join(PurchaseBatch, PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
            .where(DryingLotBatch.drying_lot_id.in_(lot_ids))
            .order_by(PurchaseBatch.id)
        )).all():
            lot_batch.setdefault(lot_id, []).append(bid)
            batch_ids.add(bid)

    # Penunjuk tunggal proses lama yang tak punya baris sumber sama sekali.
    tanpa_sumber = [p for p in daftar if not per_proses.get(p.id)]
    for p in tanpa_sumber:
        if p.purchase_batch_id:
            batch_ids.add(p.purchase_batch_id)
        if p.drying_lot_id:
            lot_ids.add(p.drying_lot_id)
    if tanpa_sumber:
        lot_lagi = {p.drying_lot_id for p in tanpa_sumber if p.drying_lot_id}
        if lot_lagi - set(lot_batch):
            for lot_id, bid in (await db.execute(
                select(DryingLotBatch.drying_lot_id, DryingLotBatch.purchase_batch_id)
                .join(PurchaseBatch,
                      PurchaseBatch.id == DryingLotBatch.purchase_batch_id)
                .where(DryingLotBatch.drying_lot_id.in_(lot_lagi))
                .order_by(PurchaseBatch.id)
            )).all():
                lot_batch.setdefault(lot_id, []).append(bid)
                batch_ids.add(bid)

    batch = {b.id: b for b in (await db.execute(
        select(PurchaseBatch).where(PurchaseBatch.id.in_(batch_ids))
    )).scalars()} if batch_ids else {}
    nama_pemasok = dict((await db.execute(
        select(Supplier.id, Supplier.nama_supplier)
        .where(Supplier.id.in_({b.supplier_id for b in batch.values()}))
    )).all()) if batch else {}

    hasil: dict[int, tuple[list, list[str]]] = {}
    for p in daftar:
        bahan: list = []
        kondisi: set[str] = set()
        terlihat: set[int] = set()

        def _tambah(bid: int | None) -> None:
            b = batch.get(bid) if bid else None
            if b is None or b.id in terlihat:
                return
            terlihat.add(b.id)
            k = (b.kondisi_gabah or "").strip().lower()
            if k:
                kondisi.add(k)
            bahan.append(_baris_bahan(b, nama_pemasok.get(b.supplier_id)))

        baris_sumber = per_proses.get(p.id)
        if baris_sumber:
            for sb in baris_sumber:
                if sb.drying_lot_id:
                    for bid in lot_batch.get(sb.drying_lot_id, []):
                        _tambah(bid)
                elif sb.purchase_batch_id:
                    _tambah(sb.purchase_batch_id)
        elif p.drying_lot_id:
            for bid in lot_batch.get(p.drying_lot_id, []):
                _tambah(bid)
        elif p.purchase_batch_id:
            _tambah(p.purchase_batch_id)

        hasil[p.id] = (bahan, [k for k in ("basah", "kering") if k in kondisi])
    return hasil


def _persen(v) -> str:
    """Satu angka di belakang koma — SAMA seperti `QcRata.teks()` menulisnya.

    Kartu giling berjalan menyebut "KA 13,0%" dan kartu Stok dulu menyebut "13%"
    untuk bilangan yang sama. Dua tulisan berbeda atas satu angka membuat orang
    mengira ia melihat dua pengukuran, dan itu persis kesalahpahaman yang
    hendak ditutup temuan T-2.
    """
    return f"{float(v):.1f}%".replace(".", ",")


#: Kolom QC yang ditampilkan, beserta labelnya dan nama medannya di `QcRata`.
#: Satu tempat, dipakai versi satuan maupun versi banyak-sekaligus.
_KOLOM_MUTU = (("Kadar air", "kadar_air"),
               ("Butir patah", "broken"),
               ("Susut", "susut"))


def _mutu_dari(rata) -> list[tuple[str, str]]:
    """Baris mutu kartu Stok dari rata-rata QC satu lot.

    **RATA-RATA, bukan catatan terakhir** (keputusan pemilik 24 September 2026).
    Sampai hari itu kartu ini menggambar nilai TERBARU per kolom sementara
    tombol "Catat mutu sekarang" dan kalimat balasannya menjanjikan rata-rata —
    jadi orang diberi tahu satu angka lalu diperlihatkan angka lain untuk lot
    yang sama, di layar berikutnya. Temuan QA 24 September (T-2).

    Alasan pemilik memilih rata-rata: tiap catatan adalah TUSUKAN di titik yang
    berbeda selama giling berjalan, bukan pembetulan atas yang sebelumnya. Yang
    menusuk tiga kali membayar waktu untuk tiga pengukuran; membuang dua di
    antaranya membuat dua tusukan itu sia-sia.

    Rata-ratanya PER KOLOM dan hanya atas catatan yang MENGISI kolom itu —
    borangnya menerima "isi minimal salah satu", jadi catatan yang cuma
    menyebut broken tak boleh ikut membagi rata-rata kadar air. Hitungannya
    sendiri di `milling.qc_rata_banyak`, tempat ia diuji.
    """
    if rata is None or not getattr(rata, "ada", False):
        return []
    keluar: list[tuple[str, str]] = []
    for label, medan in _KOLOM_MUTU:
        v = getattr(rata, medan, None)
        if v is not None:
            keluar.append((label, _persen(v)))
    return keluar


async def _mutu(db: AsyncSession, proc_id: int) -> list[tuple[str, str]]:
    """Rata-rata QC PER KOLOM. Lihat catatan pada `LotPk.mutu`."""
    return (await _mutu_banyak(db, [proc_id])).get(proc_id, [])


async def _mutu_banyak(db: AsyncSession, proc_ids) -> dict[int, list]:
    """`_mutu` untuk banyak proses sekaligus. Satu kueri, bukan satu per lot.

    Hitungannya dipinjam dari `milling.qc_rata_banyak` — SATU jawaban untuk
    "berapa mutu lot ini", yang sama dengan yang disebut kartu giling berjalan
    dan kalimat balasan aksinya. Dua tempat yang menghitung rata-rata
    sendiri-sendiri akan berselisih, dan yang salah adalah yang lebih jarang
    dibaca.
    """
    from app.penggilingan.gudang1.services.milling import qc_rata_banyak

    ids = list(proc_ids)
    if not ids:
        return {}
    peta = await qc_rata_banyak(db, ids)
    return {pid: _mutu_dari(peta.get(pid)) for pid in ids}


async def pk_gudang1(db: AsyncSession) -> list[LotPk]:
    """Tiap lot giling yang PK-nya masih tersisa di Gudang 1, terbaru dulu.

    Yang sudah habis terkirim tidak ditampilkan: stok adalah apa yang ADA, dan
    daftar yang memuat baris nol mengajari orang melewatkan barisnya.
    """
    from app.penggilingan.gudang1.services.milling import (
        hitung_rendemen,
        pk_breakdown_banyak,
    )

    proses = list((await db.execute(
        select(MillingProcess).order_by(MillingProcess.id.desc())
    )).scalars().all())
    # Satu panggilan untuk SELURUH proses, bukan empat kueri per proses.
    # Layar ini membaca setiap giling yang pernah ada, jadi dengan data
    # setahun gelung lamanya sendirian mengeluarkan ribuan kueri untuk
    # menghasilkan belasan baris. Temuan QA P-S-02.
    rincian = await pk_breakdown_banyak(db, [p.id for p in proses])
    # Nilai QC untuk seluruh lot sekaligus. Satu kueri, bukan satu per lot.
    peta_mutu = await _mutu_banyak(db, [p.id for p in proses])
    peta_bahan = await _bahan_banyak(db, proses)
    # Permintaan yang masih terbuka, satu kueri untuk seluruh lot.
    from app.services.permintaan_pk import diminta_peta

    peta_minta = await diminta_peta(db, [p.id for p in proses])

    keluar: list[LotPk] = []
    for proc in proses:
        bd = rincian[proc.id]
        # Nol karena HABIS berbeda dari nol karena TAK DICATAT. Yang habis
        # terkirim memang tak perlu didaftar; yang tak pernah dicatat justru
        # harus, karena itulah satu-satunya tempat kelalaiannya kelihatan.
        belum = (proc.status == "selesai" and bd.produced <= 0
                 and bd.transferred <= 0)
        if bd.tersedia <= 0 and not belum:
            continue
        # `sumber_batch` adalah SATU-SATUNYA jawaban "apa isi lot ini" — yang
        # sama dipakai HPP. Harga yang ikut dikembalikannya sengaja dibuang di
        # sini, bukan disaring di templat: layar ini dilihat operator juga.
        bahan, kondisi = peta_bahan[proc.id]
        keluar.append(LotPk(
            kode=proc.kode_proses,
            tersedia=bd.tersedia,
            dihasilkan=bd.produced,
            dikirim=bd.transferred,
            bahan_kg=float(proc.berat_gabah_masuk_kg or 0),
            bahan_final=bool(proc.bobot_masuk_final),
            # Penyebutnya dipinjam, bukan dipilih sendiri: dua layar yang
            # memakai penyebut berbeda akan menyebut rendemen berbeda untuk
            # lot yang sama.
            #
            # Yang hasilnya tak dicatat TIDAK punya rendemen. Rumusnya akan
            # menjawab 0,0% dengan patuh — pembagian yang benar atas pembilang
            # yang tidak diketahui — dan "0,0%" terbaca sebagai giling yang
            # gagal total, bukan sebagai catatan yang belum diisi.
            rendemen=(None if belum
                      else hitung_rendemen(bd.produced, proc.berat_gabah_masuk_kg)),
            kelas=kelas_pk(kondisi),
            mutu=peta_mutu.get(proc.id, []),
            bahan=bahan,
            tanggal=_tgl(proc.waktu_selesai or proc.waktu_mulai),
            lama=_hari(proc.waktu_selesai or proc.waktu_mulai),
            berjalan=proc.status == "proses",
            diminta_oleh=(peta_minta[proc.id].oleh if proc.id in peta_minta else None),
            belum_dicatat=belum,
        ))
    return keluar


# ─────────────────────────── Gudang 2 — Penyosohan ───────────────────────────
#
# Gudang 1 mendaftar stoknya per LOT GILING, karena di sana satuan yang
# tertulis di kartu dan di catatan memang lot. Gudang 2 tidak bisa begitu:
# PK dari beberapa asal dituang ke silo yang sama dan stoknya disimpan sebagai
# SATU jumlah, bukan lapisan. Menampilkannya per lot berarti mengarang sisa
# per lot — angka yang tak bisa dipertanggungjawabkan, tepat di tempat orang
# mencari pertanggungjawaban.
#
# Maka satuannya TEMPAT: silo A, silo B, tumpukan. Asal-usulnya tetap disebut
# di dalam kartunya sebagai riwayat "apa yang pernah masuk ke sini", persis
# yang sudah dipakai kartu silo di layar Sedang berjalan.


@dataclass
class TempatPk:
    """Satu tempat penyimpanan PK di Gudang 2, beserta isinya."""

    kode: str
    tersedia: float
    #: Kapasitas tempat ini dalam kg. None = tak berbatas / tak tercatat.
    maks: float | None = None
    #: Apa yang PERNAH masuk ke sini: (asal, berat, kapan). Bukan sisa
    #: per asal — lihat catatan di atas.
    isi: list[tuple[str, str, str]] = field(default_factory=list)
    #: Penuh berapa persen. None bila kapasitasnya tak diketahui.
    persen: float | None = None


async def _isi_tumpukan(db: AsyncSession) -> list[tuple[str, str, str]]:
    """Asal PK yang masih menumpuk di lantai Gudang 2.

    Berbeda dari silo, tumpukan MEMANG bisa dirinci: tiap pemasukan tetap
    berdiri sendiri sampai dipindahkan, dan sisanya dihitung per pemasukan
    oleh `_sisa_tumpukan_intake`. Yang sisanya nol tak disebut — daftar yang
    memuat baris nol mengajari orang melewatkan barisnya.
    """
    from app.models import InternalTransfer, PkGudang2Intake
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import _sisa_tumpukan_intake
    from app.models import Supplier

    keluar: list[tuple[str, str, str]] = []
    for i in (await db.execute(
        select(PkGudang2Intake)
        .where(PkGudang2Intake.tujuan == "ditumpuk")
        .order_by(PkGudang2Intake.id.desc())
    )).scalars().all():
        sisa = await _sisa_tumpukan_intake(db, i.id)
        if sisa <= 0:
            continue
        judul = "PK"
        if i.internal_transfer_id:
            kode = (await db.execute(
                select(MillingProcess.kode_proses)
                .join(InternalTransfer,
                      InternalTransfer.milling_process_id == MillingProcess.id)
                .where(InternalTransfer.id == i.internal_transfer_id)
            )).scalars().first()
            judul = f"Giling sendiri · {kode}" if kode else "Giling sendiri"
        elif i.pk_purchase_batch_id:
            baris = (await db.execute(
                select(PkPurchaseBatch.kode_batch, Supplier.nama_supplier)
                .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
                .where(PkPurchaseBatch.id == i.pk_purchase_batch_id)
            )).first()
            if baris:
                judul = f"{baris[1] or '?'} · {baris[0]}"
        keluar.append((judul, _kg(sisa), f"masuk {_tgl(i.tanggal_masuk)}"))
    return keluar[:8]


async def pk_gudang2(db: AsyncSession) -> list[TempatPk]:
    """PK yang masih ada di Gudang 2 — per tempat, silo dulu lalu tumpukan.

    Tempat KOSONG tetap ditampilkan, dan di sinilah aturan Gudang 1 sengaja
    dibalik. Di sana barisnya lot: lot yang habis memang tak ada lagi, jadi
    menyembunyikannya benar. Di sini barisnya tempat, dan tempat yang kosong
    tetap ADA — silo yang hilang dari daftar terbaca sebagai silo yang rusak
    atau data yang gagal dimuat, dan operator akan mencarinya di layar lain.
    """
    from app.config import settings
    from app.penggilingan.gudang2.service import (
        get_g2_silo, hitung_stok_silo, hitung_stok_tumpukan)
    from app.services.berjalan import _asal_pk

    keluar: list[TempatPk] = []
    for huruf in ("A", "B"):
        silo = await get_g2_silo(db, huruf)
        if silo is None:
            continue
        stok = float(await hitung_stok_silo(db, silo.id))
        maks = (float(silo.kapasitas_ton) * 1000
                if silo.kapasitas_ton is not None else None)
        keluar.append(TempatPk(
            kode=f"Silo {huruf}", tersedia=stok, maks=maks,
            isi=(await _asal_pk(db, silo.id)) if stok > 0 else [],
            persen=(stok / maks * 100 if maks else None),
        ))

    tump = float(await hitung_stok_tumpukan(db))
    maks_t = float(settings.g2_tumpukan_maks_kg or 0) or None
    keluar.append(TempatPk(
        kode="Tumpukan", tersedia=tump, maks=maks_t,
        isi=(await _isi_tumpukan(db)) if tump > 0 else [],
        persen=(tump / maks_t * 100 if maks_t else None),
    ))
    return keluar


#: Grade beras putih yang dihitung sebagai PRODUK; sisanya hasil samping.
GRADES_BERAS = ("premium", "medsuper", "medium", "sayur")
NAMA_KATEGORI = {"beras_b": "Beras B (olah ulang)", "menir": "Menir",
             "broken": "Broken", "bekatul": "Bekatul", "reject": "Reject"}
#: Urutan tampil: beras terbaik lebih dulu, hasil samping menyusul.
_URUT_BARANG = {j: n for n, j in enumerate(
    ("premium", "medsuper", "medium", "sayur", "beras_putih", "beras_b",
     "bekatul", "menir", "broken", "reject"))}


@dataclass
class BarangJadiG2:
    """Isi gudang barang jadi: yang dijual, dan hasil sampingnya."""

    produk: list[dict]
    samping: list[dict]


async def barang_jadi_g2(db: AsyncSession) -> BarangJadiG2:
    """Stok barang jadi Gudang 2 — satu kartu per SKU × mutu.

    Satu kartu = satu SKU × mutu (jenis · merk · kemasan · ukuran); stoknya
    masuk − keluar lewat `hitung_stok_finished_goods`, rinciannya per proses
    penyosohan asal supaya "dari sosohan mana" tetap terjawab saat ada keluhan
    mutu. Bekatul curah berdiri sendiri: ia tak pernah dikemas.

    DI SINI, bukan di dalam endpoint, sejak 23 September 2026. Hitungan ini
    dulu terkunci di `gudang2_api.stok`, jadi satu-satunya layar yang bisa
    menggambarkannya adalah aplikasi Gudang 2 — dan Pos Produksi, yang memegang
    kedua gudang, tak punya layar barang jadi sama sekali. Meja pun hanya dapat
    rupa teksnya lewat laporan. Aturan yang sama dengan `stok_kemasan_rinci`:
    satu hitungan, beberapa pembaca; dua hitungan untuk satu pertanyaan akan
    berselisih pada perubahan berikutnya.
    """
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.penggilingan.inventory import finished_goods as bj
    from app.penggilingan.inventory.models import (
        Brand, ByproductStock, FinishedGoodsStock, PackageSize, PackagingMaterial,
        ProductSku, RiceQualityStandard)

    baris = (await db.execute(
        select(FinishedGoodsStock, ProductSku, Brand.nama, PackagingMaterial.nama,
               PackageSize.ukuran_kg, RiceQualityStandard.kode, RiceQualityStandard.nama,
               PolishingProcess.kode_proses)
        .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
        .join(PackagingMaterial, PackagingMaterial.id == ProductSku.packaging_material_id)
        .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
        .join(Brand, Brand.id == ProductSku.brand_id, isouter=True)
        .join(RiceQualityStandard,
              RiceQualityStandard.id == FinishedGoodsStock.rice_quality_standard_id,
              isouter=True)
        .join(PolishingProcess,
              (PolishingProcess.id == FinishedGoodsStock.source_id)
              & (FinishedGoodsStock.source_type == "polishing"), isouter=True)
        .order_by(FinishedGoodsStock.waktu.desc())
    )).all()

    kartu: dict[tuple, dict] = {}
    for fg, sku, merk, kemasan, ukuran, mutu_kode, mutu_nama, pol in baris:
        kunci = (sku.id, fg.rice_quality_standard_id)
        k = kartu.get(kunci)
        if k is None:
            stok_ = await bj.hitung_stok_finished_goods(db, sku.id, fg.rice_quality_standard_id)
            if stok_["karung"] <= 0 and stok_["kg"] <= 0:
                kartu[kunci] = None
                continue
            if sku.kategori == "beras_putih":
                jenis = (mutu_kode or "").lower() or "beras_putih"
                nama = mutu_nama or "Beras putih"
            else:
                jenis = sku.kategori
                nama = NAMA_KATEGORI.get(sku.kategori, sku.kategori.title())
            if merk:
                nama += f" · {merk}"
            k = kartu[kunci] = {
                "jenis": jenis, "nama": nama, "kemasan": f"{kemasan} {ukuran} kg",
                "ukuran": int(ukuran), "karung": stok_["karung"], "kg": stok_["kg"],
                "asal": [], "_pol": {}}
        if k is None:
            continue
        if pol:
            a = k["_pol"].setdefault(pol, [0, 0.0])
            a[0] += int(fg.jumlah_karung)
            a[1] += float(fg.berat_total_kg)
    produk, samping = [], []
    for k in kartu.values():
        if k is None:
            continue
        k["asal"] = [(pol, f"{kg:,.0f} kg".replace(",", "."), f"{n} karung")
                     for pol, (n, kg) in k.pop("_pol").items()]
        (produk if k["jenis"] in GRADES_BERAS or k["jenis"] == "beras_putih"
         else samping).append(k)

    # Bekatul curah — masuk − keluar, rincian per proses.
    curah = await bj.hitung_stok_bekatul(db)
    if curah > 0:
        per_pol = (await db.execute(
            select(PolishingProcess.kode_proses, ByproductStock.berat_kg)
            .join(PolishingProcess, PolishingProcess.id == ByproductStock.source_id)
            .where(ByproductStock.jenis_produk == "bekatul",
                   ByproductStock.source_type == "polishing")
            .order_by(ByproductStock.waktu.desc())
        )).all()
        samping.append({
            "jenis": "bekatul", "nama": "Bekatul", "kemasan": "curah", "ukuran": 0,
            "karung": 0, "kg": curah,
            "asal": [(kode, f"{float(kg):,.0f} kg".replace(",", "."), "curah")
                     for kode, kg in per_pol][:8]})
    for daftar in (produk, samping):
        daftar.sort(key=lambda k: (_URUT_BARANG.get(k["jenis"], 99),
                                   k["nama"], k["ukuran"]))
    return BarangJadiG2(produk=produk, samping=samping)
