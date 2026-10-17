"""Stok PK Gudang 1 — hasil giling yang masih ada, dirinci per lot.

Satu angka gabungan menjawab "berapa" tetapi tidak menjawab "yang mana", dan
di gudang pertanyaan kedua yang lebih sering muncul: PK mana yang sudah lama
menumpuk, PK mana yang gabahnya dari pemasok yang sedang dipersoalkan. Maka
barisnya adalah LOT GILING — satuan yang sama dengan yang tertulis di kartu
dan di catatan, jadi orang tak perlu menerjemahkan apa pun.

Gudang 2 menyusul di bawah, per KODE BAHAN juga (keputusan pemilik 5 Oktober
2026) — satu kartu per pemasukan yang masih menumpuk, sama seperti lot di
atas. Yang beda cuma SILO-nya, dan alasannya ditulis panjang di sana: PK dari
beberapa asal dituang ke silo yang sama, jadi "sisa lot ini berapa" memang
tak punya jawaban begitu ia masuk silo — makanya silo tak didaftar di sini
sama sekali, tumpukannya saja.

Barang jadi Gudang 2 (beras putih, menir, bekatul) dan kemasan masih belum
ikut. Keduanya subjek lain — yang KELUAR dari penyosohan, bukan yang menunggu
disosoh — dan menempelkannya di halaman yang sama akan membuat satu layar
menjawab dua pertanyaan sekaligus.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local, tanggal_lokal
from hmu_core.komoditas import buat_produk
from app.models import MillingProcess
from app.services.mutu_pk import LABEL_KUALITATIF as _LABEL_KUALITATIF, rincian_kualitatif
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
    #: Angka dan kategori QC dirata-rata per komponen. Catatan lab memakai
    #: isian terakhir yang terisi.
    #:
    #: RATA-RATA per KOLOM, atas catatan yang mengisi kolom itu — bukan catatan
    #: terbaru. Mutu dicatat berulang selama giling berjalan (keputusan pemilik
    #: 24 September 2026), dan tombolnya sendiri menjanjikan rata-rata; kartu
    #: yang menggambar nilai terbaru membuat satu lot punya dua angka mutu yang
    #: berbeda di dua layar. Hitungannya `milling.qc_rata_banyak`.
    mutu: list[tuple[str, str]] = field(default_factory=list)
    #: Rata-rata skor kadar air, broken, dan susut dari komponen yang tercatat.
    nilai_kualitas: float | None = None
    komponen_kualitas: int = 0
    kelas_kualitas: str | None = None

    #: Sudah DIMINTA operator Gudang 2 (nama peminta), atau None.
    #:
    #: Kartu yang sudah diminta tak menawarkan tombol "Minta lot ini" lagi: tombol
    #: yang ditekan dua kali karena layarnya tak berubah adalah tombol yang
    #: mengajari orang menekan dua kali. Pagar sungguhannya tetap di basis data
    #: (indeks parsial `uq_permintaan_pk_hidup`) — layar tak bisa menjaga dua
    #: permintaan yang tiba pada detik yang sama.
    diminta_oleh: str | None = None
    #: KEADAAN permintaannya, dalam kalimat yang bisa dibaca peminta.
    #:
    #: Sampai 25 September 2026 yang meminta menekan tombol lalu tak pernah
    #: diberi kabar lagi — barangnya muncul, atau tidak, dan ia tak punya cara
    #: tahu sedang di tangan siapa. Itu bagian yang paling kurang dari seluruh
    #: alur ini menurut pemilik, dan ia tak butuh kartu baru: satu kalimat di
    #: kartu yang sudah ia tatap tiap hari sudah cukup.
    diminta_keadaan: str = ""
    #: Id permintaannya — dipakai tombol "Muat & kirim" di kartu Stok.
    #: Sejak 26 September 2026 operator Gudang 2 memulai perpindahannya dari
    #: kartu itu (permintaan pemilik), jadi layar perlu menyebut permintaan
    #: MANA yang sedang ia kerjakan.
    diminta_id: int | None = None
    #: True saat permintaannya sudah DISETUJUI Admin — kartunya berubah warna,
    #: dan tombol "Muat & kirim" muncul untuk yang meminta.
    diminta_siap: bool = False

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
    #: Pesanan jasa yang memiliki PK ini — None = milik pabrik.
    #:
    #: ⚠ Lot jasa TETAP DIDAFTAR di sini, dan itu disengaja: barangnya memang
    #: berdiri di lantai Gudang 1, dan daftar stok yang menyembunyikannya akan
    #: berselisih dengan apa yang dilihat orang di gudang — jenis kebohongan yang
    #: paling cepat membuat layar berhenti dipercaya. Yang TIDAK boleh adalah ia
    #: ikut ke daftar barang yang bisa DIJUAL, dan itu disaring di borang barang
    #: keluar (`aksi_inventory.barang_bisa_keluar`, `pk_siap_keluar`) berikut
    #: penjaganya di `barang_keluar.tersedia`.
    jasa_id: int | None = None
    #: "JAS-2610-007 Pak Budi" — dicetak di kartunya. None untuk barang pabrik.
    pemilik: str | None = None


def _tgl(d) -> str:
    # `timestamptz` dibaca asyncpg sebagai UTC. Tanggal WIB sebelum pukul 07
    # akan tampak sebagai hari sebelumnya jika `.strftime` langsung dipakai.
    if hasattr(d, "tzinfo"):
        d = tanggal_lokal(d)
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
        from app.services.jasa import nama_pemilik

        # Pemasok bila dibeli, PEMILIK bila dititipkan. Tanpa kaki kedua ini
        # kartu PK dari gabah jasa berbunyi "?" di baris yang justru menjawab
        # pertanyaan kartunya — "gabah siapa, berapa".
        sup = await db.get(Supplier, b.supplier_id) if b.supplier_id else None
        return _baris_bahan(b, (sup.nama_supplier if sup
                                else await nama_pemilik(db, b.jasa_id)))

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
        .where(Supplier.id.in_({b.supplier_id for b in batch.values()
                                if b.supplier_id is not None}))
    )).all()) if batch else {}
    # Jawabannya harus SAMA PERSIS dengan versi satuan, termasuk untuk batch
    # tanpa pemasok: yang di sana memakai `nama_pemilik`, di sini petanya.
    from app.services.jasa import nama_pemilik_banyak

    nama_pemilik_ = await nama_pemilik_banyak(
        db, {b.jasa_id for b in batch.values()}) if batch else {}

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
            bahan.append(_baris_bahan(b, nama_pemasok.get(b.supplier_id)
                                      or nama_pemilik_.get(b.jasa_id)))

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
    keluar.extend(rincian_kualitatif(rata))
    if getattr(rata, "catatan_lab", None):
        keluar.append(("Catatan lab", rata.catatan_lab))
    return keluar


def _nilai_kualitas(mutu: list[tuple[str, str]]) -> tuple[float | None, int]:
    """Rata-rata skor QC PK; komponen yang belum pernah diukur tidak dihitung.

    Angka sumbernya adalah rata-rata QC yang sama dengan yang tercetak di
    kartu. Skor bukan rata-rata persen mentah: tiap komponen lebih dulu
    dipetakan ke skala 0–100 menurut batas mutu, baru skor komponen yang
    tersedia dirata-ratakan.
    """
    skor: list[float] = []
    for label, nilai in mutu:
        try:
            angka = float(str(nilai).strip().replace("%", "").replace(",", "."))
        except (TypeError, ValueError):
            continue
        nama = label.strip().lower()
        if nama == "kadar air":
            if angka < 11:
                skor.append(0)
            elif angka < 12:
                skor.append(50)
            elif angka < 13:
                skor.append(90)
            elif angka < 14:
                skor.append(100)
            elif angka < 14.5:
                skor.append(90)
            elif angka < 15:
                skor.append(80)
            elif angka < 15.5:
                skor.append(70)
            elif angka < 16:
                skor.append(60)
            elif angka <= 16.5:
                skor.append(50)
            else:
                skor.append(10)
        elif nama in ("butir patah", "broken"):
            if angka < 20:
                skor.append(100)
            elif angka < 25:
                skor.append(90)
            elif angka < 30:
                skor.append(80)
            elif angka < 35:
                skor.append(70)
            elif angka <= 40:
                skor.append(60)
            elif angka <= 50:
                skor.append(50)
            else:
                skor.append(10)
        elif nama == "susut":
            if angka <= 12:
                skor.append(100)
            elif angka <= 13:
                skor.append(90)
            elif angka <= 14:
                skor.append(80)
            elif angka <= 15:
                skor.append(70)
            elif angka <= 16:
                skor.append(60)
            elif angka <= 17:
                skor.append(50)
            else:
                skor.append(10)
    return (sum(skor) / len(skor), len(skor)) if skor else (None, 0)


def _kelas_kualitas(nilai: float | None) -> str | None:
    """Label kualitatif skor PK; rentang tengah C1/C2 mengikuti persetujuan."""
    if nilai is None:
        return None
    if nilai >= 96:
        return "A1"
    if nilai >= 91:
        return "A2"
    if nilai >= 86:
        return "B1"
    if nilai >= 80:
        return "B2"
    if nilai >= 76:
        return "C1"
    if nilai >= 70:
        return "C2"
    if nilai >= 50:
        return "D"
    return "F"


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


from app.models.permintaan import DISETUJUI


def _keadaan_minta(status: str) -> str:
    """Permintaan itu sedang di tangan siapa — dikalimatkan untuk PEMINTANYA.

    Bukan nama keadaannya ("disetujui"), melainkan apa artinya bagi yang
    membaca: siapa yang sedang memegangnya, dan apa yang ia tunggu.
    """
    from app.models.permintaan import DIKIRIM, DIMINTA, DISETUJUI

    return {
        DIMINTA: "menunggu keputusan Admin",
        DISETUJUI: "disetujui — menunggu dikirim Gudang 1",
        DIKIRIM: "sudah dikirim — menunggu ditutup Admin",
    }.get(status, "")


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
    from app.services.jasa import nama_pemilik_banyak

    peta_minta = await diminta_peta(db, [p.id for p in proses])
    # Sebutan pemilik untuk SELURUH lot sekaligus — satu kueri, bukan satu per
    # lot. Layar ini membaca setiap giling yang pernah ada (temuan QA P-S-02).
    peta_pemilik = await nama_pemilik_banyak(db, {p.jasa_id for p in proses})

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
        nilai_kualitas, komponen_kualitas = _nilai_kualitas(peta_mutu.get(proc.id, []))
        keluar.append(LotPk(
            kode=proc.kode_proses,
            tersedia=bd.tersedia,
            jasa_id=proc.jasa_id,
            pemilik=peta_pemilik.get(proc.jasa_id) if proc.jasa_id else None,
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
            nilai_kualitas=nilai_kualitas,
            komponen_kualitas=komponen_kualitas,
            kelas_kualitas=_kelas_kualitas(nilai_kualitas),
            bahan=bahan,
            tanggal=_tgl(proc.waktu_selesai or proc.waktu_mulai),
            lama=_hari(proc.waktu_selesai or proc.waktu_mulai),
            berjalan=proc.status == "proses",
            diminta_oleh=(peta_minta[proc.id].oleh if proc.id in peta_minta else None),
            diminta_keadaan=(_keadaan_minta(peta_minta[proc.id].status)
                             if proc.id in peta_minta else ""),
            diminta_id=(peta_minta[proc.id].id if proc.id in peta_minta else None),
            diminta_siap=(proc.id in peta_minta
                          and peta_minta[proc.id].status == DISETUJUI),
            belum_dicatat=belum,
        ))
    return keluar


# ─────────────────────────── Gudang 2 — Penyosohan ───────────────────────────
#
# Sampai 5 Oktober 2026 Tumpukan digambar sebagai SATU kartu beranak: total
# di kepala, rincian per pemasukan di laci bawahnya, dan laci itu tak
# menyebut mutu sama sekali. Keputusan pemilik: *"pk di gudang 2 juga harus
# disajikan sama seperti di gudang 1. jangan dibungkus dengan kartu tumpukan.
# bagaimana kami bisa tau kualitas per kode bahan. tetap harus ditampilkan
# per kode bahan."* Satu kartu total menjawab "berapa", tapi membungkus
# pertanyaan yang justru paling sering diajukan di lantai: PK kode mana yang
# mutunya begini, PK kode mana yang harus ditahan.
#
# Jadi Tumpukan kini SATU KARTU PER PEMASUKAN — `LotPkG2`, satuan yang sama
# dengan `LotPk` Gudang 1 — bukan lagi satu kartu per TEMPAT. Tiap pemasukan
# tetap berdiri sendiri sampai dipindahkan (begitu juga sisanya, dihitung
# oleh `_sisa_tumpukan_intake`/sisa yang dibatch di bawah), jadi "berapa yang
# ada per kode" di sini sama sahnya dengan lot di Gudang 1 — dan karena itu
# memakai aturan Gudang 1 yang SAMA ("habis = tak didaftar").
#
# ⚠ SILO TETAP TIDAK IKUT (keputusan pemilik 4 Oktober 2026, tak berubah):
# "di gudang 2 tidak boleh ada stock di silo — dimasukkan ke silo hanya untuk
# kepentingan proses." Isinya pun bukan sesuatu yang DIUKUR — tak ada alat
# ukur fisik di silo — melainkan DIHITUNG dari masuk dikurangi keluar
# (`hitung_stok_silo`). Silo tetap dipakai dan dihitung di tempat yang memang
# bertanya "proses apa yang sedang berjalan" (layar Sedang berjalan,
# `berjalan.py`) — yang berubah cuma BENTUK kartu Tumpukan di sini.


async def riwayat_qc_pk(db: AsyncSession, *, kode: str | None = None,
                        intake_id: int | None = None) -> dict:
    """QC stok mengikuti lot asal, termasuk setelah dipindah ke Gudang 2.

    Dipanggil sesudah akses ke stok diperiksa oleh layar. Tidak dibatasi 200
    baris: seluruh pengukuran lot ikut membentuk rata-rata di kartu kualitas.
    PK luar dan hasil giling memakai log pemeriksaan tanpa batas putaran.
    """
    from app.models import InternalTransfer, MillingQcLog, User
    from app.penggilingan.gudang2.models import PkGudang2Intake

    proses_id = None
    batch_id = None
    if intake_id is not None:
        intake = await db.get(PkGudang2Intake, intake_id)
        if intake and intake.internal_transfer_id:
            transfer = await db.get(InternalTransfer, intake.internal_transfer_id)
            proses_id = transfer.milling_process_id if transfer else None
        elif intake:
            batch_id = intake.pk_purchase_batch_id
    elif kode:
        proses_id = await db.scalar(select(MillingProcess.id).where(
            MillingProcess.kode_proses == kode))

    from app.models import PkPurchaseQcLog
    model, kunci, identitas = ((MillingQcLog, MillingQcLog.milling_process_id, proses_id)
                               if proses_id else
                               (PkPurchaseQcLog, PkPurchaseQcLog.pk_purchase_batch_id, batch_id))
    hasil = (await db.execute(select(model, User.nama)
        .outerjoin(User, User.id == model.input_by).where(kunci == identitas)
        .order_by(model.waktu, model.id))).all() if identitas else []
    rows = []
    for nomor, (qc, nama) in enumerate(hasil, 1):
        rows.append(dict(nomor=nomor, waktu=qc.waktu, pencatat=nama,
                         ka=_persen(qc.kadar_air) if qc.kadar_air is not None else "—",
                         broken=_persen(qc.broken_persen) if qc.broken_persen is not None else "—",
                         susut=_persen(qc.susut_persen) if qc.susut_persen is not None else "—",
                         kualitatif=rincian_kualitatif(qc, termasuk_kosong=True),
                         catatan_lab=qc.catatan_lab, asal_lama=getattr(qc,"asal_lama",False),
                         keterangan=getattr(qc,"kondisi",None) or "—"))
    return {"rows": list(reversed(rows)), "hasil_terbaru_saja": False,
            "ada_data_lama": any(x["asal_lama"] for x in rows)}



@dataclass
class LotPkG2:
    """Satu pemasukan PK yang masih menumpuk di Gudang 2, beserta mutunya.

    Padanan `LotPk` untuk Gudang 2: satuannya KODE BAHAN (satu pemasukan =
    satu kartu), bukan lagi satu tempat penyimpanan beranak — lihat alasannya
    di atas. Tiap kartu tahu asal pemasukan PK-nya (satu PKB atau satu
    transfer G1). Untuk transfer dari giling sendiri, daftar batch gabah
    proses asal tetap tersedia agar asal bahan bisa dibaca di halaman detail.
    """

    #: "Kelompok Tani Sumber Rejeki · PKB-20261004-03", atau
    #: "Giling sendiri · LOT-20260930-05" bila asalnya transfer G1.
    kode: str
    tersedia: float
    #: False = truknya belum ditimbang kedua, `tersedia` masih perkiraan /
    #: tak diketahui (P6-02). Beda dari `LotPk.belum_dicatat`: di sana hasil
    #: gilingnya tak pernah dicatat; di sini beratnya memang belum ADA.
    bobot_final: bool = True
    tanggal: str | None = None
    lama: str = ""
    #: "JAS-2610-007 Pak Budi" bila pemasukan ini titipan — None untuk
    #: barang pabrik.
    pemilik: str | None = None
    #: ID pesanan jasa bila stok ini titipan; dipakai untuk membedakan
    #: pemilik jasa secara pasti pada halaman detail.
    jasa_id: int | None = None
    #: (label, nilai) — Kadar air/Butir patah/Susut serta Butir kuning/Gabah/
    #: Merang/Catatan lab untuk kedua asal. Kosong =
    #: belum pernah dinilai (PK dari giling sendiri yang belum dicatat
    #: mutunya oleh Gudang 1).
    mutu: list[tuple[str, str]] = field(default_factory=list)
    nilai_kualitas: float | None = None
    komponen_kualitas: int = 0
    kelas_kualitas: str | None = None
    #: Id `PkGudang2Intake` — dipakai tombol "Masukkan ke silo" di kartu
    #: Stok, pre-isi lewat mekanisme `?buka=&nilai=` yang sama dengan
    #: "Minta lot ini" Gudang 1.
    intake_id: int = 0
    qc_kode: str | None = None
    #: Berat SAAT MASUK tumpukan — bukan sisanya. 0.0 bila `bobot_final`
    #: False (belum punya angka sama sekali, lihat catatan di atas).
    #:
    #: Permintaan pemilik 5 Oktober 2026: "berapa yang sudah masuk silo dari
    #: berat awal yang ada." Selisihnya (`berat_awal - tersedia`) adalah
    #: jawabannya — kartu ini tak menyimpan angka "sudah ke silo" sendiri,
    #: sebab dua angka yang mengklaim hal sama akan berselisih begitu salah
    #: satunya disentuh; lihat `_sisa_tumpukan_intake` untuk sisanya.
    berat_awal: float = 0.0
    #: Kelas PK: "KS" (dari gabah basah, kami keringkan sendiri), "KL" (dari
    #: gabah yang sudah kering saat dibeli), "Campuran"/"Semi KS" (PK beli
    #: luar — `PkPurchaseBatch.jenis_pk`), atau "MIX" (giling sendiri, dari
    #: silo yang berisi gabah basah DAN kering — `milling.kelas_pk`). None =
    #: tak diketahui.
    #:
    #: Permintaan pemilik 5 Oktober 2026: "kondisi kl atau ks." Dua sumber
    #: BEDA ISTILAH untuk pertanyaan yang sama — PK beli luar diketik
    #: langsung oleh yang menerimanya; PK giling sendiri DITURUNKAN dari
    #: kondisi gabah sumbernya, sama seperti `LotPk.kelas` di Gudang 1, dan
    #: harus menjawab SAMA dengan yang digambar kartu lot asalnya di sana.
    kelas: str | None = None
    #: Batch gabah sumber proses giling sendiri, untuk ditampilkan pada
    #: halaman detail stok Gudang 2.
    bahan: list[tuple[str, str, str]] = field(default_factory=list)


async def pk_gudang2(db: AsyncSession) -> list[LotPkG2]:  # noqa: C901
    """Tiap pemasukan PK yang masih menumpuk di Gudang 2, terbaru dulu.

    Silo TIDAK didaftar di sini (lihat catatan di atas): isinya bukan stok
    yang sah menurut aturan pemilik, dan angkanya cuma hasil hitungan
    masuk-keluar, bukan ukuran fisik. Yang habis di Tumpukan juga tak
    didaftar — sama seperti lot Gudang 1, baris nol cuma mengajari orang
    melewatkan barisnya.

    Dibatch, bukan satu kueri per pemasukan — pola "SATU kueri, bukan satu
    per baris" yang sama dipakai `pk_gudang1`: jumlah pemasukan tumbuh terus,
    dan layar ini dibuka tiap hari.
    """
    from app.models import InternalTransfer, OutgoingItem, PkGudang2Intake, Supplier
    from app.penggilingan.gudang2.models import (PkPurchaseBatch,
                                                 PkPurchaseVerification,
                                                 PkTumpukanToSilo)
    from app.penggilingan.gudang2.service import (_JENIS_PK_LABEL,
                                                   hitung_stok_tumpukan)
    from app.services.jasa import nama_pemilik_banyak
    from sqlalchemy import func

    tump = float(await hitung_stok_tumpukan(db))
    if tump <= 0:
        # ⚠ `hitung_stok_tumpukan` menjumlah `berat_kg`, dan SQL `SUM`
        # mengabaikan NULL — truk yang belum ditimbang kedua (P6-02) ikut
        # TERABAIKAN, bukan ikut terhitung sebagai nol. Jadi tumpukan yang
        # isinya CUMA pemasukan berbobot-belum-diketahui terbaca "kosong"
        # oleh ukuran itu, padahal barangnya sudah ada di lantai — pagar
        # cepat ini tak boleh percaya begitu saja sebelum memastikan tak
        # ada pemasukan begitu (kueri kedua ini HANYA berjalan saat `tump`
        # memang nol, jadi jalur umum — tumpukan sungguh berisi — tak
        # membayar kueri tambahan ini sama sekali).
        ada_belum_ditimbang = (await db.execute(
            select(PkGudang2Intake.id)
            .where(PkGudang2Intake.tujuan == "ditumpuk",
                  PkGudang2Intake.berat_kg.is_(None))
            .limit(1)
        )).scalars().first()
        if not ada_belum_ditimbang:
            return []

    intakes = list((await db.execute(
        select(PkGudang2Intake)
        .where(PkGudang2Intake.tujuan == "ditumpuk")
        .order_by(PkGudang2Intake.id.desc())
    )).scalars().all())
    if not intakes:
        return []
    ids = [i.id for i in intakes]

    # Sudah berapa yang dipindah ke silo per pemasukan — SATU kueri terkelompok,
    # bukan `_sisa_tumpukan_intake` dipanggil bergilir (itu sendiri 1+ kueri
    # per pemasukan, lewat `db.get` plus sum).
    dipindah = dict((await db.execute(
        select(PkTumpukanToSilo.pk_gudang2_intake_id,
              func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0))
        .where(PkTumpukanToSilo.pk_gudang2_intake_id.in_(ids))
        .group_by(PkTumpukanToSilo.pk_gudang2_intake_id)
    )).all())

    # ── Asal & mutu PK beli luar — satu kueri untuk SELURUH batch sekaligus ──
    batch_ids = [i.pk_purchase_batch_id for i in intakes if i.pk_purchase_batch_id]
    #: (kode_batch, nama_pemasok, kelas) — kelas diterjemahkan dari
    #: `jenis_pk` lewat `_JENIS_PK_LABEL` SAMA PERSIS dengan yang dipakai
    #: borang `catat_pk_luar`, supaya kartu Stok tak pernah menyebut kelas
    #: yang berbeda dari yang diketik orang yang menerimanya.
    batch_info: dict[int, tuple[str, str | None, str | None]] = {}
    verif_info: dict[int, PkPurchaseVerification] = {}
    if batch_ids:
        for b, nama in (await db.execute(
            select(PkPurchaseBatch, Supplier.nama_supplier)
            .join(Supplier, Supplier.id == PkPurchaseBatch.supplier_id, isouter=True)
            .where(PkPurchaseBatch.id.in_(batch_ids))
        )).all():
            batch_info[b.id] = (b.kode_batch, nama,
                                _JENIS_PK_LABEL.get((b.jenis_pk or "").lower()))
        for v in (await db.execute(
            select(PkPurchaseVerification)
            .where(PkPurchaseVerification.pk_purchase_batch_id.in_(batch_ids))
        )).scalars().all():
            verif_info[v.pk_purchase_batch_id] = v

    # ── Asal & mutu PK giling sendiri — lewat lot Gudang 1 yang mengirimnya ──
    transfer_ids = [i.internal_transfer_id for i in intakes if i.internal_transfer_id]
    kode_proc: dict[int, str] = {}              # internal_transfer_id -> kode_proses
    proc_dari_transfer: dict[int, MillingProcess] = {}  # internal_transfer_id -> proses
    if transfer_ids:
        for t_id, proc in (await db.execute(
            select(InternalTransfer.id, MillingProcess)
            .join(MillingProcess, MillingProcess.id == InternalTransfer.milling_process_id)
            .where(InternalTransfer.id.in_(transfer_ids))
        )).all():
            kode_proc[t_id] = proc.kode_proses
            proc_dari_transfer[t_id] = proc
    proses_giling = list(proc_dari_transfer.values())
    peta_mutu_giling = (await _mutu_banyak(db, [p.id for p in proses_giling])
                       if proses_giling else {})
    # Kondisi MASUK bahan sumbernya — jawaban SAMA yang dipakai `LotPk.kelas`
    # di Gudang 1 untuk lot yang persis sama; dua layar yang menghitungnya
    # sendiri-sendiri akan berselisih pada lot yang bahannya campuran.
    peta_bahan_giling = (await _bahan_banyak(db, proses_giling)
                        if proses_giling else {})

    peta_pemilik = await nama_pemilik_banyak(
        db, {i.jasa_id for i in intakes if i.jasa_id is not None})

    # ── Sudah DIAMBIL (pengambilan jasa) — FIFO, sama seperti dipindah ──
    #
    # Laporan lapangan 12 Oktober 2026: PK titipan yang sudah diambil
    # pemiliknya lewat perintah barang keluar TETAP tampil di kartu Stok/
    # Stok PK Jasa seolah masih ada — picker "Barang yang diambil" sudah
    # benar (`hitung_stok_tumpukan` ikut menyaring `keluar`, migrasi 0076),
    # tetapi kartu PER PEMASUKAN di sini cuma menyaring `dipindah` ke silo,
    # tak pernah menyaring yang sudah KELUAR pabrik sama sekali — dua
    # pembaca stok tumpukan yang sama berselisih.
    #
    # `outgoing_items` (pk_g2 dari tumpukan, `silo_id IS NULL`) tak
    # menunjuk SATU pemasukan tertentu — PK yang diambil cuma tahu
    # beratnya, bukan dari truk mana asalnya. Jadi dikurangkan FIFO per
    # pemilik (`jasa_id`, None = pabrik), pemasukan TERTUA dulu, sama
    # persis urutan `pindah_kepemilikan_barang_jadi` — tak ada alasan
    # pemasukan yang MANA yang "aman" disentuh: `keluar` selalu dikonsumsi
    # dari yang paling lama berdiri.
    keluar_jasa = dict((await db.execute(
        select(OutgoingItem.jasa_id, func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .where(OutgoingItem.item_type == "pk_g2", OutgoingItem.silo_id.is_(None))
        .group_by(OutgoingItem.jasa_id)
    )).all())
    diambil_fifo: dict[int, float] = {}
    by_pemilik: dict[int | None, list[PkGudang2Intake]] = {}
    for i in intakes:
        by_pemilik.setdefault(i.jasa_id, []).append(i)
    for jid, grup in by_pemilik.items():
        sisa_ambil = float(keluar_jasa.get(jid, 0) or 0)
        if sisa_ambil <= 0:
            continue
        for i in sorted(grup, key=lambda x: (x.waktu_masuk, x.id)):
            if sisa_ambil <= 0:
                break
            sisa_sesudah_pindah = float(i.berat_kg or 0) - float(dipindah.get(i.id, 0))
            if sisa_sesudah_pindah <= 0:
                continue
            ambil = min(sisa_sesudah_pindah, sisa_ambil)
            diambil_fifo[i.id] = ambil
            sisa_ambil -= ambil

    keluar: list[LotPkG2] = []
    for i in intakes:
        if i.berat_kg is None:
            # Truk belum ditimbang kedua (P6-02) — belum punya angka sama
            # sekali, bukan nol. Tetap didaftar: barangnya sudah ada di
            # lantai, dan layar yang menyembunyikannya membuat orang
            # mengira tak ada apa-apa untuk dipindahkan.
            sisa, bobot_final, berat_awal = 0.0, False, 0.0
        else:
            berat_awal = float(i.berat_kg)
            sisa = (berat_awal - float(dipindah.get(i.id, 0))
                    - float(diambil_fifo.get(i.id, 0)))
            bobot_final = True
            # Kartu tampil dengan kg bulat. Sisa <= 0,5 kg akan terbaca "0 kg"
            # dan membuat operator mengira stok kosong tetapi kartunya masih ada.
            if sisa <= 0.5:
                continue                 # habis dipindah atau diambil — tak didaftar

        if i.internal_transfer_id:
            kode = kode_proc.get(i.internal_transfer_id)
            judul = f"Giling sendiri · {kode}" if kode else "Giling sendiri"
            proc = proc_dari_transfer.get(i.internal_transfer_id)
            mutu = peta_mutu_giling.get(proc.id, []) if proc else []
            bahan, kondisi = peta_bahan_giling.get(proc.id, ([], [])) if proc else ([], [])
            kelas = kelas_pk(kondisi)
        elif i.pk_purchase_batch_id:
            kode_batch, nama, kelas = batch_info.get(
                i.pk_purchase_batch_id, ("?", None, None))
            judul = f"{nama or '?'} · {kode_batch}"
            bahan, mutu = [], []
            v = verif_info.get(i.pk_purchase_batch_id)
            if v is not None:
                for label, nilai in (("Kadar air", v.kadar_air),
                                     ("Butir patah", v.broken_persen),
                                     ("Susut", v.penyusutan_persen)):
                    if nilai is not None:
                        mutu.append((label, _persen(nilai)))
                for label, nilai in (("Butir kuning", v.butir_kuning),
                                     ("Gabah", v.gabah), ("Merang", v.merang)):
                    if nilai:
                        mutu.append((label, _LABEL_KUALITATIF.get(nilai, nilai)))
                if v.catatan_lab:
                    mutu.append(("Catatan lab", v.catatan_lab))
        else:
            judul, bahan, mutu, kelas = "PK", [], [], None  # baris peninggalan tanpa penunjuk

        nilai_kualitas, komponen_kualitas = _nilai_kualitas(mutu)
        keluar.append(LotPkG2(
            kode=judul, tersedia=sisa, bobot_final=bobot_final,
            tanggal=_tgl(i.tanggal_masuk), lama=_hari(i.waktu_masuk),
            pemilik=peta_pemilik.get(i.jasa_id) if i.jasa_id else None,
            jasa_id=i.jasa_id,
            mutu=mutu, nilai_kualitas=nilai_kualitas,
            komponen_kualitas=komponen_kualitas,
            kelas_kualitas=_kelas_kualitas(nilai_kualitas),
            intake_id=i.id, qc_kode=kode_batch if i.pk_purchase_batch_id and not i.internal_transfer_id else None,
            berat_awal=berat_awal, kelas=kelas, bahan=bahan,
        ))
    return keluar


#: Grade beras putih yang dihitung sebagai PRODUK; sisanya hasil samping.
GRADES_BERAS = ("premium", "medsuper", "medium", "sayur")
NAMA_KATEGORI = {"beras_b": "Beras B (olah ulang)", "menir": "Menir",
             "broken": "Broken", "bekatul": "Bekatul", "reject": "Reject"}
#: Grade beras yang keluar dari mesin sosoh. Yang di luar daftar ini hasil
#: SAMPING (menir, broken, bekatul, reject) — beda rumahnya, beda perlakuannya.
BERAS_JENIS = ("premium", "medsuper", "medium", "sayur", "beras_b")


def adalah_beras(jenis: str | None) -> bool:
    """Beras, atau hasil samping? SATU tempat yang menjawab.

    Permintaan pemilik 28 September 2026: layar Stok Produk dipisah dua blok —
    beras sendiri, hasil samping sendiri. Alasannya terbaca dari barangnya:
    beras dijual per karung bermerk dan mutunya dipersoalkan pembeli; menir,
    broken, bekatul, reject dijual curah, harganya lain, dan pembelinya lain.
    Satu daftar berurutan membuat keduanya dibaca dengan ukuran yang sama.

    BUKAN `jenis in BERAS_JENIS` langsung, dan itu bukan kerapian: `beras_putih`
    — beras yang mutunya BELUM ditetapkan — tak ada di daftar itu, sebab daftar
    itu dipakai mencari standar mutu dan beras tanpa mutu tak punya standar.
    Memakainya untuk memilah blok akan menjatuhkan beras tanpa mutu ke blok
    hasil samping: berton-ton beras putih terbaca sebagai bekatul, di layar yang
    lahir justru karena ada beras yang tak punya rumah.
    """
    j = (jenis or "").strip().lower()
    return j in BERAS_JENIS or j == "beras_putih"


@dataclass
class BerasCurah:
    """Beras yang sudah keluar dari mesin sosoh tetapi BELUM dikemas.

    Sampai 26 September 2026 barang ini tak punya rumah. `polishing_output_logs`
    dibaca tepat dua tempat di seluruh repo — pembanding internal saat mencatat
    hasil, dan satu baris ringkasan di laporan Riwayat produksi — dan tak satu
    pun layar stok membacanya. Beras baru MENJADI stok ketika seseorang
    menjalankan "Catat packing"; sebelum itu, berton-ton beras berdiri di lantai
    sementara aplikasi menyebut stok Gudang 2 nol.

    Ketimpangannya dengan Gudang 1 yang membuatnya terasa hilang: lot giling
    yang selesai BERKARTU lengkap di layar Stok, dan PK-nya terhitung siap
    kirim. Output Gudang 1 adalah stok; output Gudang 2 tinggal baris log.
    Padahal keduanya sama-sama barang yang berdiri di lantai gudang.

    Temuan QA 26 September; keputusan pemilik: halaman "Stok Produk" sendiri.
    """

    kode_proses: str
    jenis: str
    #: Kumulatif yang tercatat keluar mesin.
    keluar_kg: float
    #: Yang sudah dipindahkan ke barang jadi lewat packing.
    dikemas_kg: float
    #: Yang masih berdiri sebagai curah — inilah angka stoknya.
    sisa_kg: float
    #: Kapan sosohnya ditutup. None berarti MASIH BERJALAN.
    selesai: object | None = None
    #: Pemilik proses sosohnya — None = pabrik. Dibawa sejak 6 Oktober 2026
    #: supaya pembaca (kartu Antrian tunggu) bisa membedakan titipan
    #: pelanggan dari hasil pabrik; sebelum ini keduanya tampil identik.
    jasa_id: int | None = None

    @property
    def berjalan(self) -> bool:
        return self.selesai is None


async def output_sosoh_banyak(db: AsyncSession, proc_ids=None
                              ) -> dict[int, dict[str, float]]:
    """Kumulatif terakhir per (proses, jenis) — SATU kueri untuk semuanya.

    Lahir 28 September 2026 atas pengukuran QA: layar Stok Produk memanggil
    `output_sosoh` sekali per proses penyosohan, jadi 500 penyosohan berarti
    500 kueri, dan halamannya 1,77 detik. Di HP lewat 4G itu bukan lagi halaman
    yang bisa dibuka.

    ⚠ MENJUMLAH, bukan mengambil yang terbaru — dan inilah baris yang
    menentukan benar-salahnya seluruh Stok Produk. Sampai 28 September 2026
    `berat_kg` kumulatif, jadi yang benar adalah baris TERAKHIR; sejak migrasi
    0060 tiap entri berdiri sendiri (permintaan operator: tiap ganti spek punya
    hasilnya sendiri). Yang lupa diubah akan menyebut 200 kg untuk broken yang
    sungguhnya 500 kg, dan persamaan kartunya patah tanpa satu pesan pun.

    Bentuk tunggal `output_sosoh` cuma bungkus fungsi ini, jadi keduanya tak
    mungkin berselisih — dijaga `test_bentuk_borongan_sama_dengan_bentuk_tunggal`.

    `proc_ids=None` berarti SELURUH proses; itu yang dipakai layar Stok Produk,
    yang memang menjumlah seluruh riwayat untuk kepala kartunya.
    """
    from app.penggilingan.gudang2.models import PolishingOutputLog

    from sqlalchemy import func

    q = (select(PolishingOutputLog.polishing_process_id,
                PolishingOutputLog.jenis,
                func.coalesce(func.sum(PolishingOutputLog.berat_kg), 0))
         .group_by(PolishingOutputLog.polishing_process_id,
                   PolishingOutputLog.jenis))
    if proc_ids is not None:
        ids = list(proc_ids)
        if not ids:
            return {}
        q = q.where(PolishingOutputLog.polishing_process_id.in_(ids))
    keluar: dict[int, dict[str, float]] = {}
    for pid, jenis, kg in (await db.execute(q)).all():
        keluar.setdefault(pid, {})[jenis] = float(kg)
    return keluar


async def output_sosoh(db: AsyncSession, proc_id: int) -> dict[str, float]:
    """Kumulatif terakhir per jenis untuk satu proses penyosohan.

    SATU tempat membaca `polishing_output_logs` sebagai "berapa yang keluar",
    dipakai layar Stok Produk MAUPUN laporan Riwayat produksi. Sebelum 26
    September 2026 polanya ditulis dua kali — sekali di `polishing`, sekali di
    `report` — dan dua pembaca yang menyusun sendiri aturan "ambil baris
    terbaru per jenis" akan berselisih pada perubahan berikutnya.

    Yang membaca BANYAK proses sekaligus memakai `output_sosoh_banyak`; ini
    tinggal bungkusnya, supaya aturannya tetap satu.
    """
    return (await output_sosoh_banyak(db, [proc_id])).get(proc_id, {})


async def _dipindah_silo_proc(db: AsyncSession, proc_ids: list[int]
                              ) -> dict[tuple[int, str], float]:
    """Σ `beras_ke_silo.berat_kg` per (proses, jenis) — graded beras yang
    sudah dipindah jadi bahan Silo Beras (sosoh ulang), keputusan pemilik
    8 Oktober 2026.

    Dipakai `beras_curah()` — kartu "Tunggu packing" tak boleh terus
    menagih kg yang operator sudah tangani lewat "Masukkan ke silo beras",
    sebangun alasan `dikemas` dikurangkan di sana. Kuncinya (proses, jenis)
    bukan cuma proses — satu proses bisa memindahkan beberapa grade
    sekaligus.

    ⚠ `stok_produk()` (ledger `/stok-produk`) SENGAJA TAK memakai fungsi ini.
    Broken punya jalan yang SAMA (`broken_ke_silo`) tetapi hanya tersambung
    ke `stok_produk()` lewat `hitung_stok_broken_curah()` — jalur `curah_saja`
    yang sudah ada SEBELUM silo broken lahir. Beras grade tak punya jalur
    "curah_saja" serupa (ia selalu masuk cabang generik `else`), dan
    menganyam suku baru ke cabang itu — yang sudah tiga kali punya catatan
    bug di komentarnya sendiri — berisiko menggeser invarian `hasil = curah +
    dikemas + keluar` yang dijaga `test_persamaan_empat_suku_bertahan_di_
    setiap_langkah`. Dibiarkan sebagai kesenjangan yang SAMA besarnya dengan
    yang sudah diterima untuk broken (`_isian_silo` juga tak membaca
    `broken_ke_silo`) — bukan baru, bukan diperbesar oleh fitur ini.
    """
    from app.penggilingan.gudang2.models import BerasKeSilo

    if not proc_ids:
        return {}
    keluar: dict[tuple[int, str], float] = {}
    for pid, jenis, kg in (await db.execute(
        select(BerasKeSilo.polishing_process_id, BerasKeSilo.jenis,
               func.coalesce(func.sum(BerasKeSilo.berat_kg), 0))
        .where(BerasKeSilo.polishing_process_id.in_(proc_ids))
        .group_by(BerasKeSilo.polishing_process_id, BerasKeSilo.jenis)
    )).all():
        keluar[(pid, jenis)] = float(kg)
    return keluar


async def beras_curah(db: AsyncSession, *, termasuk_berjalan: bool = True
                      ) -> list[BerasCurah]:
    """Beras yang belum dipacking manual, per lot × jenis.

    Stok curah = yang KELUAR mesin − yang SUDAH DIKEMAS. Dua angka yang
    dua-duanya sudah tercatat; yang belum ada cuma pengurangannya.

    Bekatul, reject, menir, dan broken mengikuti aturan packing otomatis
    (`_UKURAN_KEMASAN_OTOMATIS`) dan tidak menjadi pekerjaan di antrean packing.
    Jumlah karung penuh serta sisa curahnya dihitung di `stok_produk`; meminta
    operator mencatat packing untuk jenis-jenis ini akan menduplikasi pekerjaan.

    Proses yang MASIH BERJALAN ikut, dan itu disengaja — berasnya memang sudah
    berdiri di lantai. Tetapi angkanya BELUM FINAL, dan layar wajib
    mengatakannya sekeras kartu penyosohan mengatakannya ("hasil & rendemen
    belum final"). Yang menyembunyikannya membuat orang menghitung stok atas
    angka yang masih akan berubah; yang menyebutnya seolah pasti lebih buruk
    lagi. `berjalan` pada tiap barisnya yang membedakan.
    """
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.penggilingan.inventory.finished_goods import _packed_kg, get_standard

    q = select(PolishingProcess).order_by(PolishingProcess.id.desc())
    if not termasuk_berjalan:
        q = q.where(PolishingProcess.status == "selesai")
    keluar: list[BerasCurah] = []
    for proc in (await db.execute(q)).scalars().all():
        for jenis, kg in (await output_sosoh(db, proc.id)).items():
            if jenis in _UKURAN_KEMASAN_OTOMATIS:
                continue
            if jenis in BERAS_JENIS:
                std = await get_standard(db, jenis)
                dikemas = await _packed_kg(db, proc.id, "beras_putih",
                                           std.id if std else None)
            else:
                dikemas = await _packed_kg(db, proc.id, jenis, None)
            # Grade yang sudah dipindah jadi bahan Silo Beras juga "sudah punya
            # rumah" — pola yang sama dengan dikemas di atas (keputusan pemilik
            # 8 Oktober 2026). Lihat docstring `_dipindah_silo_proc`.
            dipindah = (await _dipindah_silo_proc(db, [proc.id])).get(
                (proc.id, jenis), 0.0) if jenis in BERAS_JENIS else 0.0
            sisa = float(kg) - dikemas - dipindah
            # Nol berarti sudah habis dikemas — bukan kabar, jadi tak berkartu.
            # Yang MINUS justru kabar: lebih banyak dikemas daripada yang keluar
            # mesin, dan itu pertanyaan untuk orangnya, bukan angka untuk
            # disembunyikan.
            if abs(sisa) < 0.5:
                continue
            keluar.append(BerasCurah(
                kode_proses=proc.kode_proses, jenis=jenis, keluar_kg=float(kg),
                dikemas_kg=dikemas, sisa_kg=sisa,
                selesai=(proc.waktu_selesai if proc.status == "selesai" else None),
                jasa_id=proc.jasa_id))
    keluar.sort(key=lambda x: (_URUT_BARANG.get(x.jenis, 99), x.kode_proses))
    return keluar


def jenis_produk(kategori: str | None, mutu_kode: str | None) -> str:
    """Satu nama untuk satu barang, dipakai SEMUA pembaca produk jadi.

    Aturannya sudah ada sejak lama, ditulis satu baris di
    `inventory/finished_goods.py`: beras putih dikenali lewat kode standar
    mutunya (premium / medsuper / medium / sayur), kategori lain lewat
    `product_skus.kategori` (beras_b, menir, broken, bekatul, reject). Yang
    baru cuma tempatnya.

    DIANGKAT KE SINI 26 September 2026 atas peringatan QA, dan bukan demi
    kerapian: aturan ini sekarang dibaca empat tempat — penolakan packing,
    kartu barang jadi, kartu Stok Produk, dan hitungan barang keluar. Kalau ia
    hidup empat kali, empat layar akan menyebut angka berbeda tentang beras
    yang sama, dan bedanya baru ketahuan ketika ada yang membandingkan.

    `mutu_kode` kosong pada beras putih berarti mutunya tak pernah ditetapkan;
    ia jatuh ke keranjang `beras_putih` sendiri, bukan ditebak jadi salah satu
    grade — tebakan di sini akan menambah stok pada kartu yang salah.
    """
    kategori = (kategori or "").strip().lower()
    if kategori == "beras_putih":
        mutu = (mutu_kode or "").strip().lower()
        if not mutu:
            return "beras_putih"
        # Identitas bersama: beras putih adalah jenis barang, mutunya atribut.
        # Kode hasil tetap kode mutu lama agar stok dan histori tetap kompatibel.
        try:
            return buat_produk("beras_putih", kualitas=mutu).atribut["kualitas"]
        except ValueError:
            return mutu
    return kategori


def kategori_dan_mutu(jenis: str) -> tuple[str, str | None]:
    """Kebalikan `jenis_produk`: dari nama barang kembali ke (kategori, mutu).

    Dipakai borang packing sejak 28 September 2026, supaya orang tak ditanya
    ulang hal yang sudah tertulis di kartunya. Keduanya WAJIB tetap sepasang —
    `jenis_produk(*kategori_dan_mutu(j)) == j` untuk setiap jenis yang dikenal,
    dan itu dijaga uji, bukan diingat.

    Yang tak dikenal dikembalikan apa adanya sebagai kategori: jenis baru yang
    lupa didaftarkan lebih baik lewat dan ditolak pemeriksa kemasan dengan
    kalimat yang menyebut namanya, daripada diam-diam berubah jadi beras putih.
    """
    jenis = (jenis or "").strip().lower()
    if jenis in GRADES_BERAS:
        return "beras_putih", jenis
    return jenis, None


def _tanpa_karung(bahan: str | None) -> str:
    """"Karung biasa" → "biasa". Untuk rincian DI DALAM kartu yang sudah
    menyebut kategorinya.

    Hanya awalannya yang dibuang, dan hanya bila memang ada: bahan kemasan baru
    yang bukan karung (misal "Sak plastik") harus lewat apa adanya. Menyapu
    kata itu di mana pun ia berdiri akan mengubah nama bahan jadi kalimat yang
    tak pernah dipilih siapa pun di master.
    """
    b = (bahan or "").strip()
    return b[7:].strip() if b.lower().startswith("karung ") else b


def nama_produk(jenis: str) -> str:
    """Nama yang dibaca orang untuk `jenis_produk`."""
    return _NAMA_GRADE.get(jenis) or NAMA_KATEGORI.get(jenis) or jenis.title()


_NAMA_GRADE = {"premium": "Beras Premium", "medsuper": "Beras Medium Super",
               "medium": "Beras Medium", "sayur": "Beras Sayur",
               "beras_putih": "Beras putih · mutu di catatan lama kosong"}


#: Selisih yang MASIH WAJAR antara yang ditimbang dan yang dihitung nominal.
#:
#: Berat kemasan dihitung `jumlah_karung × ukuran` — angka nominal — sedangkan
#: hasil penyosohan DITIMBANG. Keduanya hampir tak pernah sama persis, jadi
#: selisih kecil bukan kebocoran. Ambangnya diambil dari yang sudah dipakai
#: rekonsiliasi packing sejak sebelumnya (2% atau 50 kg, mana yang lebih
#: besar) supaya dua tempat tak pernah berselisih pendapat tentang "selisih
#: ini wajar atau tidak".
def toleransi_nominal(hasil_kg: float) -> float:
    return max(abs(float(hasil_kg)) * 0.02, 50.0)


@dataclass
class RincianProduk:
    """Satu baris rincian di dalam kartu kategori."""

    kode: str
    kg: float
    waktu: object | None = None
    ket: str | None = None
    #: Proses yang belum tutup: angkanya masih akan bertambah.
    berjalan: bool = False


@dataclass
class KartuProduk:
    """SATU kartu untuk SATU kategori produk — apa pun berapa kali disosoh.

    Keputusan pemilik 26 September 2026: "stok produk setiap kategori dijadikan
    1 kartu saja dengan informasi inti total jumlah stock. tetapi di setiap
    kartu ada informasi dari masing-masing penyosohan dan informasi stock yang
    sudah keluar. artinya total hasil penyosohan adalah total jumlah stock
    ditambah stock yang keluar." Dan: "misal. premium dijadikan 1 kartu saja."

    Jadi kartunya BUKAN per lot. Premium satu kartu, dengan rincian per
    penyosohan di dalamnya.

    ⚠ PERSAMAANNYA PUNYA EMPAT SUKU, BUKAN DUA. Kalimat pemilik menyebut dua
    ("stok + keluar"), tetapi "stok" di Gudang 2 terbelah dua keadaan yang
    sangat berbeda:

        hasil = belum dikemas + sudah dikemas + sudah keluar

    Belahan "belum dikemas" WAJIB tampil. Kalau ia tak digambar, kartunya
    menunjukkan selisih yang akan dikira kebocoran — padahal justru beras curah
    itulah sebab seluruh keluhan yang melahirkan halaman ini.

    ANGKA DI KEPALA KARTU ADALAH `sisa_kg`, bukan `hasil_kg`. Kartu yang
    kepalanya tak sama dengan kakinya akan dihitung ulang orang dengan
    kalkulator, sekali, lalu tak dipercaya lagi.
    """

    jenis: str
    nama: str
    #: Kumulatif yang tercatat keluar mesin sosoh, seluruh proses.
    hasil_kg: float
    hasil: list[RincianProduk]
    #: Bagian `hasil_kg` yang datang dari proses yang BELUM tutup.
    belum_final_kg: float
    #: Yang sudah punya rumah resmi dan masih di gudang. Untuk beras: sudah
    #: dikemas. Untuk bekatul: sudah tercatat di `byproduct_stock`.
    dikemas_kg: float
    #: Yang masih berdiri tanpa rumah resmi — inilah yang selama ini hilang.
    curah_kg: float
    keluar_kg: float
    keluar: list[RincianProduk]
    #: `dikemas_kg + curah_kg`, dan sama dengan `hasil_kg - keluar_kg`.
    sisa_kg: float
    #: Untuk broken: stok fisik per bentuk, terpisah dari `dikemas_kg` dan
    #: `curah_kg` yang tetap menjaga persamaan hasil sosoh.
    kemasan_stok_kg: float = 0.0
    curah_stok_kg: float = 0.0
    ukuran_kemasan_otomatis: int = 0
    jumlah_karung_otomatis: int = 0
    dikemas_otomatis_kg: float = 0.0
    curah_otomatis_kg: float = 0.0
    #: Berapa baris rincian yang TIDAK digambar, dan berapa kg jumlahnya.
    #: Dipisah dari daftarnya supaya kartunya tetap menyebut seluruhnya tanpa
    #: mengirim seluruhnya — lihat `BATAS_RINCI_HASIL`.
    hasil_lagi: int = 0
    hasil_lagi_kg: float = 0.0
    keluar_lagi: int = 0
    keluar_lagi_kg: float = 0.0
    #: Kategori yang tak pernah dikemas (bekatul). Kartunya tanpa kata "kemas".
    curah_saja: bool = False


    @property
    def alarm(self) -> bool:
        """Yang MINUS itu alarm, yang plus kecil itu wajar — dan bedanya wajib
        terlihat. Satu tanda seru untuk dua keadaan yang berlawanan arah akan
        membuat operator mengabaikan dua-duanya.

        Minus artinya yang dikemas atau dikeluarkan melebihi yang pernah keluar
        dari mesin mana pun: ada beras yang dibukukan tanpa pernah diproduksi.
        """
        return self.curah_kg < -toleransi_nominal(self.hasil_kg)

    @property
    def beda_timbangan(self) -> bool:
        """Minus yang masih di dalam ambang nominal-vs-timbang: bukan alarm,
        dan bukan pula stok. Disebut apa adanya supaya tak dikira kebocoran."""
        return -toleransi_nominal(self.hasil_kg) <= self.curah_kg < -0.5


_UKURAN_KEMASAN_OTOMATIS = {
    "bekatul": 40,
    "reject": 50,
    "menir": 50,
    "broken": 50,
}


def _packing_otomatis(jenis: str, berat_kg: float) -> tuple[int, int, float, float]:
    """Pisahkan hasil samping menjadi karung penuh dan sisa curah.

    Broken memakai karung 50 kg sebagai ukuran otomatis utama. Ukuran 25 kg
    tetap tersedia untuk pencatatan kemasan broken secara khusus.
    """
    ukuran = _UKURAN_KEMASAN_OTOMATIS.get(jenis, 0)
    berat = float(berat_kg or 0)
    if not ukuran:
        return 0, 0, 0.0, berat
    jumlah = max(int(berat // ukuran), 0)
    dikemas = float(jumlah * ukuran)
    return ukuran, jumlah, dikemas, berat - dikemas


#: Berapa baris rincian yang digambar sebelum sisanya diringkas jadi satu
#: kalimat. Diukur QA 28 September 2026: tanpa batas, 500 penyosohan menjadi
#: 508 baris pada SATU kartu, halamannya 119 KB dan 1,77 detik — di HP lewat
#: 4G itu bukan lagi halaman yang bisa dibuka. Dan itu baru satu dari sembilan
#: jenis.
#:
#: Sisanya DIRINGKAS, bukan disembunyikan di balik "lihat selengkapnya":
#: melipat baris tetap menuntut seluruhnya dikirim ke telepon, dan yang diukur
#: QA adalah byte-nya. Yang benar-benar perlu melihat seluruh riwayat membuka
#: Laporan, yang memang untuk itu.
BATAS_RINCI_HASIL, BATAS_RINCI_KELUAR = 10, 6


def _fifo_sisa(baris: list[RincianProduk], keluar_kg: float) -> list[RincianProduk]:
    """Rincian asal stok yang MASIH ada, menurut anggapan FIFO.

    Yang keluar lebih dulu dianggap yang disosoh lebih dulu, jadi `keluar_kg`
    "dimakan" dari baris TERTUA. Yang habis dibuang; yang termakan sebagian
    ditampilkan SISANYA, bukan angka aslinya.

    DITURUNKAN, tidak disimpan — sama seperti `silo_ids_proses` menurunkan
    jawabannya: himpunan yang disimpan dua kali adalah himpunan yang kelak
    berselisih.

    ⚠ INI ANGGAPAN, BUKAN PENELUSURAN, dan pemakainya wajib diberi tahu.
    `finished_goods_stock` memang tahu karungnya dari penyosohan mana
    (`source_type='polishing'` + `source_id`), tetapi `outgoing_items` TIDAK
    punya taut ke penyosohan maupun ke baris stok yang dipakai — jadi begitu
    karung naik ke truk, hubungannya dengan penyosohan asalnya putus. Aplikasi
    tidak tahu, dan tidak bisa tahu, karung dari POL mana yang berangkat.

    Karena itu kepalanya berbunyi "Perkiraan asal stok (FIFO)", bukan "Hasil
    penyosohan" polos. Yang menangani keluhan pembeli akan memakai daftar ini
    untuk mencari batch-nya; kalau ia menyangka ini catatan padahal perkiraan,
    ia akan menyalahkan penyosohan yang salah — dan di beras, keluhan mutu
    berujung ke pemasok dan ke uang.

    Penelusuran sungguhan kurang SATU kolom: `outgoing_items.
    finished_goods_stock_id`. Belum dikerjakan (pemilik belum meminta), dan
    tidak ada di sini yang membuatnya sulit ditambahkan kelak — fungsi ini
    menerima daftar dan mengembalikan daftar.
    """
    sisa_makan = max(float(keluar_kg), 0.0)
    keluar: list[RincianProduk] = []
    # Dari yang TERTUA — `waktu` bisa kosong pada baris lama, dan yang tak
    # bertanggal diperlakukan paling tua: ia memang yang paling dulu dicatat.
    for r in sorted(baris, key=lambda x: (x.waktu is not None, x.waktu or 0)):
        if sisa_makan <= 0.001:
            keluar.append(r)
            continue
        if r.kg <= sisa_makan + 0.001:
            sisa_makan -= r.kg              # habis terjual, hilang dari daftar
            continue
        keluar.append(RincianProduk(
            kode=r.kode, kg=r.kg - sisa_makan, waktu=r.waktu,
            ket=r.ket, berjalan=r.berjalan))
        sisa_makan = 0.0
    # Yang terbaru lebih dulu: itu yang ada di gudang sekarang, dan yang
    # dicari orang saat menelusuri keluhan adalah yang baru dikirimkannya.
    keluar.reverse()
    return keluar


async def stok_produk(db: AsyncSession, *,
                      jasa_id: int | list[int] | None = None) -> list[KartuProduk]:
    """Satu kartu per kategori, dengan persamaan empat sukunya.

    Tiga sumber angkanya, semuanya sudah ada sebelum hari ini:

      hasil    `polishing_output_logs`, kumulatif TERAKHIR per (proses, jenis)
               — lewat `output_sosoh`, satu pembaca untuk semua.
      dikemas  `finished_goods_stock` × `product_skus` (+ standar mutu untuk
               beras putih); untuk bekatul `byproduct_stock`.
      keluar   `outgoing_items`: `finished_goods` lewat SKU + standar mutu,
               `byproduct_curah` lewat `jenis_byproduct`. `pk_langsung` BUKAN
               milik halaman ini — itu PK Gudang 1, bahan, bukan produk.

    Yang MASIH BERJALAN ikut dihitung dan ditandai (`belum_final_kg`,
    `RincianProduk.berjalan`). Berasnya memang sudah berdiri di lantai; tetapi
    kartu yang menyebut angka belum final seolah pasti akan membuat orang
    mengemas dua kali. Kartu penyosohan sudah jujur soal ini, dan blok ini
    tidak boleh lebih berani daripadanya.

    `jasa_id` — keputusan pemilik 6 Oktober 2026: bawaannya `None` berarti
    PABRIK (`PolishingProcess.jasa_id IS NULL`, bukan "tanpa saringan" seperti
    sebelumnya — proses jasa yang tak disaring membuat "hasil sosoh" pabrik
    diam-diam memuat output pesanan orang lain, dan "curah" pabrik terbaca
    lebih besar daripada yang sebenarnya). Mengisi `jasa_id` menjawab
    pertanyaan yang berbeda: kartu MILIK PESANAN ITU SAJA, dipakai halaman
    "Titipan pelanggan" (`/stok-produk-jasa`) — satu rumus, dua pertanyaan,
    pola yang sama dengan `hitung_stok_finished_goods`.

    ⚠⚠ BEKATUL BOLEH MUNCUL untuk `jasa_id` terisi SEJAK 6 Oktober 2026 —
    PEMBALIKAN dari sebelumnya. Dulu bekatul beralih milik ke pabrik otomatis
    saat dibukukan (keputusan pemilik 12); laporan lapangan ("bekatulnya kok
    tidak ada di halaman produk jasa") membalik keputusan itu — bekatul
    sekarang mengikuti pola broken/menir/reject: tetap milik pesanan sampai
    dipindah lewat `pindah_kepemilikan_bekatul_curah`/`pindah_kepemilikan_
    barang_jadi`. Yang menentukan `pemilik_hasil(proc.jasa_id, hasil_ditahan,
    "bekatul")` per PROSES (bukan tebakan dari `jasa_id` di sini) — pesanan
    lama yang `hasil_ditahan`-nya belum dibackfill (migrasi
    `0073_bekatul_bukan_ditahan`) tetap menahan bekatulnya ke pabrik, dan
    bekatul proses PABRIK (bukan jasa) selalu pabrik, titik.

    ⚠ `jasa_id` BOLEH DAFTAR, bukan cuma satu angka — keputusan pemilik 6
    Oktober 2026: "Titipan pelanggan" dikelompokkan per PELANGGAN, bukan per
    PESANAN. Satu pelanggan boleh punya beberapa `Jasa` (SATU PESANAN,
    BEBERAPA KEDATANGAN berarti kedatangan ulang dari pelanggan yang sama
    tetap pesanan BARU — lihat docstring `Jasa`), dan kartu stoknya wajib
    menyatu jadi SATU seksi, bukan pecah sebanyak jumlah pesanannya.
    """
    from app.penggilingan.gudang2.models import HasilSampingKeSilo, PolishingProcess
    from sqlalchemy import func

    from app.penggilingan.inventory.finished_goods import (
        hitung_stok_bekatul, hitung_stok_broken_curah)
    from app.penggilingan.inventory.models import (
        ByproductStock, FinishedGoodsStock, OutgoingItem, OutgoingRecord,
        ProductSku, RiceQualityStandard)

    def milik_proc(k):
        if jasa_id is None:
            return k.jasa_id.is_(None)
        if isinstance(jasa_id, (list, tuple, set, frozenset)):
            return k.jasa_id.in_(jasa_id)
        return k.jasa_id == jasa_id

    # SATU kueri untuk seluruh proses, dan SATU lagi untuk seluruh catatan
    # hasilnya — bukan dua kueri per proses. Gelungnya sendiri yang dulu
    # mengeluarkan 500 kueri untuk menghasilkan sembilan kartu (ukuran QA 28
    # September 2026: 1,77 detik pada 500 penyosohan).
    #
    # `Jasa.hasil_ditahan` ikut di-JOIN (NULL untuk proses pabrik, tak
    # masalah — `pemilik_hasil()` memeriksa `jasa_id is None` lebih dulu)
    # supaya bekatul per proses bisa ditanyakan pemiliknya di bawah, bukan
    # ditebak dari `jasa_id is not None` begitu saja — lihat ⚠ di loop.
    from app.models import Jasa
    from app.services.jasa import pemilik_hasil

    baris_proses = list((await db.execute(
        select(PolishingProcess, Jasa.hasil_ditahan)
        .outerjoin(Jasa, Jasa.id == PolishingProcess.jasa_id)
        .where(milik_proc(PolishingProcess))
        .order_by(PolishingProcess.id.desc())
    )).all())
    proses = [p for p, _ in baris_proses]
    ditahan_proc = {p.id: dt for p, dt in baris_proses}
    #: Proses milik kartu INI — dipakai di bawah untuk "sudah dicatat atau
    #: belum", yang WAJIB tak peduli pemiliknya SEKARANG. Lihat catatan
    #: panjang di dekat `dikemas_proc`.
    proc_ids = [p.id for p in proses]
    catatan = await output_sosoh_banyak(db, [p.id for p in proses])

    hasil: dict[str, list[RincianProduk]] = {}
    berjalan: dict[str, float] = {}
    for proc in proses:
        jalan = proc.status != "selesai"
        for jenis, kg in catatan.get(proc.id, {}).items():
            # ⚠ Bekatul BUKAN pengecualian tetap lagi sejak 6 Oktober 2026 —
            # `pemilik_hasil()` yang menjawab, dibaca dari cuplikan kesepakatan
            # proses INI, bukan ditebak dari jasa_id saja. Kartu PABRIK
            # (`jasa_id is None`) tak pernah sampai sini untuk proses jasa
            # (sudah tersaring `milik_proc` di atas) — jadi cabang ini hanya
            # berarti untuk kartu JASA: bekatul proses ini masuk hasil
            # PESANAN hanya kalau kesepakatannya memang tak menahannya.
            if jenis == "bekatul" and jasa_id is not None:
                if pemilik_hasil(proc.jasa_id, ditahan_proc.get(proc.id) or "",
                                 "bekatul") is None:
                    continue
            hasil.setdefault(jenis, []).append(RincianProduk(
                kode=proc.kode_proses, kg=float(kg),
                waktu=(proc.waktu_selesai if not jalan else proc.waktu_mulai),
                berjalan=jalan,
                ket=("mesin masih menyosoh — belum final" if jalan else None)))
            if jalan:
                berjalan[jenis] = berjalan.get(jenis, 0.0) + float(kg)

    # ⚠⚠ BEKATUL PABRIK JUGA LAHIR DARI PROSES JASA, dan `proses` di atas
    # SUDAH menyaringnya habis (`milik_proc(PolishingProcess)` = `jasa_id IS
    # NULL` untuk kartu pabrik) — jadi tanpa blok ini, bekatul yang disosoh
    # bersama PK titipan tak pernah masuk `hasil["bekatul"]`, walau begitu
    # dibukukan ia memang stok pabrik (`jasa.pemilik_hasil()`, keputusan
    # pemilik 12). Sisi "dibukukan" di bawah TAK menyaring asal prosesnya
    # sama sekali (`ByproductStock`/`FinishedGoodsStock` ber-`jasa_id` NULL
    # memang dari proses manapun) — jadi tanpa penyeimbang ini "hasil mesin"
    # selalu lebih kecil dari yang sebenarnya, dan kartunya menuduh "dibukukan
    # melebihi hasil mesin" atas bekatul yang sebenarnya cuma kurang terhitung
    # di sisi hasil. Hanya untuk KARTU PABRIK (`jasa_id is None`) — kartu
    # jasa sudah membuang bekatul sama sekali di atas.
    #
    # Dibaca lewat `pemilik_hasil()`, bukan "pokoknya bekatul jasa = pabrik"
    # yang ditulis ulang di sini: keputusannya DITARUH SEKALI di hulu, dan
    # `hasil_ditahan` per pesanan itulah satu-satunya yang berhak menjawab
    # "bekatul proses ini milik siapa" — menghardkodenya di sini akan diam-diam
    # berselisih dari hulu begitu ada pesanan yang kesepakatannya berbeda.
    #: Proses JASA yang bekatulnya ikut "hasil" kartu PABRIK lewat blok di
    #: atas — dipakai lagi di bawah (`dikemas_proc`/`masuk_curah_proc`) supaya
    #: "sudah dicatat" kartu pabrik ikut menghitung baris yang sumbernya
    #: proses-proses ini juga, bukan cuma proses pabrik sendiri.
    proc_ids_bekatul_extra: set[int] = set()
    if jasa_id is None:
        from app.models import Jasa
        from app.services.jasa import pemilik_hasil

        proses_jasa = list((await db.execute(
            select(PolishingProcess, Jasa.hasil_ditahan)
            .join(Jasa, Jasa.id == PolishingProcess.jasa_id)
            .where(PolishingProcess.jasa_id.isnot(None))
            .order_by(PolishingProcess.id.desc())
        )).all())
        catatan_jasa = await output_sosoh_banyak(
            db, [proc.id for proc, _ in proses_jasa])
        for proc, ditahan in proses_jasa:
            kg = catatan_jasa.get(proc.id, {}).get("bekatul")
            if not kg or pemilik_hasil(proc.jasa_id, ditahan, "bekatul") is not None:
                continue
            jalan = proc.status != "selesai"
            hasil.setdefault("bekatul", []).append(RincianProduk(
                kode=proc.kode_proses, kg=float(kg),
                waktu=(proc.waktu_selesai if not jalan else proc.waktu_mulai),
                berjalan=jalan,
                ket=("mesin masih menyosoh — belum final" if jalan
                     else "dari proses jasa — bekatulnya milik pabrik")))
            if jalan:
                berjalan["bekatul"] = berjalan.get("bekatul", 0.0) + float(kg)
            proc_ids_bekatul_extra.add(proc.id)

    # ── Yang sudah dikemas (seluruh riwayat, bukan sisanya) ──
    dikemas: dict[str, float] = {}
    for kategori, mutu, kg in (await db.execute(
        select(ProductSku.kategori, RiceQualityStandard.kode,
               func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
        .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
        .join(RiceQualityStandard,
              RiceQualityStandard.id == FinishedGoodsStock.rice_quality_standard_id,
              isouter=True)
        # PABRIK saja (`jasa_id=None` bawaan) — beras pelanggan punya notanya
        # sendiri. Milik SATU pesanan saat `jasa_id` terisi.
        .where(milik_proc(FinishedGoodsStock))
        .group_by(ProductSku.kategori, RiceQualityStandard.kode)
    )).all():
        j = jenis_produk(kategori, mutu)
        dikemas[j] = dikemas.get(j, 0.0) + float(kg)

    #: Bekatul/broken curah yang SAAT INI milik kartu ini (`byproduct_stock`,
    #: kepemilikan SEKARANG — bukan `masuk_curah_proc` di atas, yang per
    #: proses). Dipakai HANYA untuk ikut menentukan jenis APA yang kartunya
    #: dibangun di bawah — lihat catatan di titik pakainya: tanpa ini, kartu
    #: yang SELURUH isinya curah yang baru DITERIMA lewat pindah kepemilikan
    #: (tak punya hasil mesin sendiri, tak punya karung, tak punya penjualan)
    #: tak pernah masuk `set(hasil) | set(dikemas) | set(keluar)` sama sekali
    #: — kartunya bukan cuma salah angka, ia tak pernah DIBANGUN. Persis
    #: gejala "di stok produk juga tidak bertambah": bukan angkanya nol,
    #: barisnya sendiri tak ada.
    masuk_curah_now: dict[str, float] = {}
    for jp, kg in (await db.execute(
        select(ByproductStock.jenis_produk,
               func.coalesce(func.sum(ByproductStock.berat_kg), 0))
        .where(ByproductStock.jenis_produk.in_(("bekatul", "broken")),
               milik_proc(ByproductStock))
        .group_by(ByproductStock.jenis_produk)
    )).all():
        masuk_curah_now[jp] = float(kg)

    # ── Yang sudah keluar ──
    #
    # Dua item_type, dan `pk_langsung` sengaja tak diambil: ia PK dari Gudang 1
    # yang dijual tanpa disosoh, jadi ia tak pernah menjadi produk halaman ini.
    # Menjumlahkannya di sini akan membuat kartu beras kehilangan stok atas
    # barang yang bukan berasnya.
    #
    # ⚠ Disaring `milik_proc(OutgoingItem)` juga sejak pengambilan jasa ikut
    # lewat rantai yang SAMA (`OutgoingItem.jasa_id`, migrasi 0080 — dulu
    # `OutgoingRecord.jasa_id`): tanpa saringan ini, pengambilan pelanggan
    # ikut mengurangi "keluar" pabrik, dan curah pabrik terbaca lebih kecil
    # daripada yang sebenarnya.
    keluar: dict[str, list[RincianProduk]] = {}
    #: Yang keluar DARI CURAH, dipisah dari yang keluar dari karung: keduanya
    #: mengurangi belahan stok yang berbeda, dan menjumlahkannya jadi satu akan
    #: membuat salah satu belahan terlihat minus tanpa sebab.
    keluar_curah: dict[str, float] = {}
    for tipe, mutu, kategori, byp, kode, pembeli, tgl, kg in (await db.execute(
        select(OutgoingItem.item_type, RiceQualityStandard.kode,
               ProductSku.kategori, OutgoingItem.jenis_byproduct,
               OutgoingRecord.kode, OutgoingRecord.nama_pembeli,
               OutgoingRecord.waktu, OutgoingItem.berat_kg)
        .join(OutgoingRecord, OutgoingRecord.id == OutgoingItem.outgoing_record_id)
        .join(ProductSku, ProductSku.id == OutgoingItem.product_sku_id, isouter=True)
        .join(RiceQualityStandard,
              RiceQualityStandard.id == OutgoingItem.rice_quality_standard_id,
              isouter=True)
        # `milik_proc(OutgoingItem)` — BUKAN `OutgoingRecord` (migrasi 0080):
        # truk boleh menggabung beberapa pesanan satu pelanggan, dan
        # `OutgoingRecord.jasa_id` NULL pada transaksi semacam itu akan
        # membuat pengambilannya hilang dari "keluar" sama sekali.
        .where(OutgoingItem.item_type.in_(("finished_goods", "byproduct_curah")),
               milik_proc(OutgoingItem))
        .order_by(OutgoingRecord.waktu.desc())
    )).all():
        if tipe == "byproduct_curah":
            j = jenis_produk((byp or "").lower(), None)
        else:
            j = jenis_produk(kategori, mutu)
        if not j:
            continue
        keluar.setdefault(j, []).append(RincianProduk(
            kode=kode, kg=float(kg), waktu=tgl,
            ket=(pembeli or None) if tipe == "finished_goods"
                else " · ".join(x for x in (pembeli, "curah") if x)))
        if tipe == "byproduct_curah":
            keluar_curah[j] = keluar_curah.get(j, 0.0) + float(kg)

    pindah_silo: dict[str, float] = {}
    for jenis_silo, kg in (await db.execute(
        select(HasilSampingKeSilo.jenis,
               func.coalesce(func.sum(HasilSampingKeSilo.berat_kg), 0))
        .where(HasilSampingKeSilo.jenis.in_(("menir", "reject")),
               milik_proc(HasilSampingKeSilo))
        .group_by(HasilSampingKeSilo.jenis)
    )).all():
        pindah_silo[jenis_silo] = float(kg)

    # ── "Sudah dicatat", per PROSES — bukan per pemilik SEKARANG ──
    #
    # Laporan lapangan 7 Oktober 2026, langsung sesudah "Pindah kepemilikan"
    # bekatul curah dipakai sungguhan: *"angka dari stock jasa tidak
    # berkurang dan di stok produk juga tidak bertambah."* Sebabnya bukan di
    # `pindah_kepemilikan_bekatul_curah` — fungsi itu (dan `hitung_stok_
    # bekatul`/`hitung_stok_broken_curah`) sudah benar, dibuktikan uji
    # `test_pindah_kepemilikan_produk.py`. Yang salah adalah `curah` DI
    # BAWAH ini, yang sampai hari ini dihitung `h − (byproduct_stock/
    # finished_goods_stock MILIK KARTU INI SEKARANG) `.
    #
    # "Pindah kepemilikan" memecah baris TANPA mengubah `source_id` satu
    # baris pun (lihat `pindah_kepemilikan_barang_jadi`/`_broken_curah`/
    # `_bekatul_curah` di `finished_goods.py`: baris baru warisan persis
    # `source_type`/`source_id` baris asalnya) — jadi begitu sebagian baris
    # berpindah `jasa_id`, baris itu LENYAP dari "milik kartu ini SEKARANG",
    # dan rumus lama membacanya seolah belum pernah dicatat sama sekali.
    # Yang bergeser bukan totalnya (`sisa_kg` kartu kehilangan itu tetap
    # persis sama) — melainkan SUKUNYA, dari "dikemas" ke "curah", pada
    # KEDUA sisi sekaligus: kartu yang kehilangan baris membaca "belum
    # dicatat" bertambah TANPA mengurangi apa pun, dan kartu yang
    # menerimanya membaca "dikemas" bertambah tapi "belum dicatat"-nya ikut
    # berkurang sebesar itu juga — totalnya diam di kedua sisi. Persis
    # gejala yang dilaporkan.
    #
    # "Sudah dicatat atau belum" adalah pertanyaan tentang PROSESNYA (mesin
    # mana yang mengeluarkannya) — dan itu TAK PERNAH berubah lewat pindah
    # kepemilikan. Yang berubah cuma SIAPA PEMILIKNYA SEKARANG, dan itu
    # pertanyaan yang berbeda — `dikemas`/`punya_rumah` di bawah TETAP
    # memakai kepemilikan SAAT INI (lewat `milik_proc`/`hitung_stok_*`)
    # karena memang begitu jawabannya seharusnya: "berapa yang masih SAYA
    # pegang". Dua pertanyaan, dua rumus — mencampurnya jadi satu adalah
    # cacatnya.
    dikemas_proc: dict[str, float] = {}
    masuk_curah_proc: dict[str, float] = {}
    if proc_ids:
        for kategori, mutu, kg in (await db.execute(
            select(ProductSku.kategori, RiceQualityStandard.kode,
                   func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .join(RiceQualityStandard,
                  RiceQualityStandard.id == FinishedGoodsStock.rice_quality_standard_id,
                  isouter=True)
            .where(FinishedGoodsStock.source_type == "polishing",
                   FinishedGoodsStock.source_id.in_(proc_ids))
            .group_by(ProductSku.kategori, RiceQualityStandard.kode)
        )).all():
            j = jenis_produk(kategori, mutu)
            dikemas_proc[j] = dikemas_proc.get(j, 0.0) + float(kg)

        for jp, kg in (await db.execute(
            select(ByproductStock.jenis_produk,
                   func.coalesce(func.sum(ByproductStock.berat_kg), 0))
            .where(ByproductStock.jenis_produk.in_(("bekatul", "broken")),
                   ByproductStock.source_type == "polishing",
                   ByproductStock.source_id.in_(proc_ids))
            .group_by(ByproductStock.jenis_produk)
        )).all():
            masuk_curah_proc[jp] = float(kg)

    # Bekatul proses jasa yang ikut "hasil" kartu pabrik (blok di atas) ikut
    # pula di sini — tanpanya "tercatat" kartu pabrik selalu lebih kecil
    # daripada "hasil"-nya, dan bekatul itu terbaca "belum dicatat" padahal
    # sudah lama tercatat punya pemilik pabrik.
    if jasa_id is None and proc_ids_bekatul_extra:
        extra_fg = float((await db.execute(
            select(func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(ProductSku.kategori == "bekatul",
                   FinishedGoodsStock.source_type == "polishing",
                   FinishedGoodsStock.source_id.in_(proc_ids_bekatul_extra))
        )).scalar_one())
        dikemas_proc["bekatul"] = dikemas_proc.get("bekatul", 0.0) + extra_fg
        extra_byp = float((await db.execute(
            select(func.coalesce(func.sum(ByproductStock.berat_kg), 0))
            .where(ByproductStock.jenis_produk == "bekatul",
                   ByproductStock.source_type == "polishing",
                   ByproductStock.source_id.in_(proc_ids_bekatul_extra))
        )).scalar_one())
        masuk_curah_proc["bekatul"] = masuk_curah_proc.get("bekatul", 0.0) + extra_byp

    kartu: list[KartuProduk] = []
    for jenis in sorted(set(hasil) | set(dikemas) | set(keluar) | set(masuk_curah_now),
                        key=lambda j: (_URUT_BARANG.get(j, 99), j)):
        baris_hasil = hasil.get(jenis, [])
        h = sum(r.kg for r in baris_hasil)
        baris_keluar = keluar.get(jenis, [])
        k = sum(r.kg for r in baris_keluar)
        # ── Bekatul DAN broken punya DUA rumah sekaligus ──
        #
        # Keputusan pemilik 28 September (bekatul) dan `catat_broken` 6
        # Oktober (broken): sebagian dijual/disimpan curah (`byproduct_
        # stock`), sebagian dikarungi (`finished_goods_stock`). Menir dan
        # reject TIDAK punya jalan curah ini — `catat_bekatul`/`catat_broken`
        # adalah SATU-SATUNYA penulis `byproduct_stock` di seluruh repo
        # (lihat impor di atas), jadi `curah_saja` HARUS persis mengikuti
        # dua nama itu, bukan ditulis ulang sebagai daftar sendiri yang bisa
        # hanyut darinya.
        curah_saja = jenis in ("bekatul", "broken")
        kemasan_stok = 0.0
        curah_stok = 0.0
        if curah_saja:
            # Yang dijaga di sini persis satu hal: yang dikarungi tak boleh
            # HILANG dari stok hanya karena ia berpindah rumah. Kalau baris
            # ini tetap membaca `byproduct_stock` saja, mengarungi 1.000 kg
            # akan menurunkan "belum dicatat" sebesar 1.000 tanpa menaikkan
            # apa pun — barangnya menguap dari layar, padahal ia berdiri di
            # gudang dalam karung.
            #
            # Rumusnya tetap berbentuk sama, cuma sukunya dua:
            #   dibukukan = curah + dikarungi
            #   punya rumah = (curah masuk − curah keluar)
            #                 + (dikarungi − keluar berkarung)
            #   belum dicatat = hasil mesin − dibukukan
            # Saat belum ada satu karung pun, ia kembali persis rumus lama.
            #
            # `curah_saja` TETAP benar sebagai nama kolomnya: kartunya berkata
            # "Tercatat / Belum dicatat", bukan "Dikemas / Curah", dan itu tetap
            # kalimat yang tepat untuk barang yang boleh berumah di dua tempat.
            # Belahan karungnya terbaca di rincian per merk di dalam laci.
            #
            # ⚠⚠ "dibukukan" DI SINI memakai `dikemas_proc`/`masuk_curah_proc`
            # (PER PROSES, bukan lagi `milik_proc`/`dikemas.get` biasa) — lihat
            # catatan panjang di dekat deklarasinya. "Punya rumah" (`punya_
            # rumah`, lewat `hitung_stok_bekatul`/`hitung_stok_broken_curah`)
            # TETAP memakai kepemilikan SAAT INI, sebab itu memang jawaban
            # yang benar untuk "berapa yang masih SAYA pegang".
            fungsi_stok = (hitung_stok_bekatul if jenis == "bekatul"
                           else hitung_stok_broken_curah)
            dikarungi = dikemas.get(jenis, 0.0)
            keluar_karung = k - keluar_curah.get(jenis, 0.0)
            curah_stok = await fungsi_stok(db, jasa_id=jasa_id)
            kemasan_stok = dikarungi - keluar_karung
            punya_rumah = curah_stok + kemasan_stok
            curah = (h - masuk_curah_proc.get(jenis, 0.0)
                     - dikemas_proc.get(jenis, 0.0))
        else:
            total_kemas = dikemas.get(jenis, 0.0)
            # Yang keluar berkarung mengurangi belahan "dikemas"; yang keluar
            # curah (menir atau broken yang dijual langsung dari lantai)
            # mengurangi belahan curah. Keduanya dijumlah utuh di `keluar_kg`.
            punya_rumah = total_kemas - (k - keluar_curah.get(jenis, 0.0))
            kemasan_stok = punya_rumah
            # `dikemas_proc`, bukan `total_kemas` — "belum dicatat" bertanya
            # tentang PROSESNYA, dan pemindahan kepemilikan (`pindah_
            # kepemilikan_barang_jadi`, berlaku untuk SKU apa pun, termasuk
            # beras/menir/reject) tak boleh membuatnya seolah belum pernah
            # dikemas sama sekali. Lihat catatan panjang di dekat deklarasinya.
            curah = h - dikemas_proc.get(jenis, 0.0) - keluar_curah.get(jenis, 0.0)
        sisa = punya_rumah + curah - pindah_silo.get(jenis, 0.0)
        if (abs(sisa) < 0.5 and abs(h) < 0.5 and abs(k) < 0.5):
            continue
        ukuran_auto, jumlah_auto, dikemas_auto, curah_auto = _packing_otomatis(
            jenis, sisa
        )
        # ── FIFO: daftarnya menyusut bersama barangnya ──
        #
        # Temuan QA 28 September 2026: kepala kartu sudah benar (sisa 3.000 kg)
        # tetapi daftar "Hasil penyosohan" tetap memuat 8 baris berjumlah 24.000
        # kg — satu kartu memuat dua angka yang bertentangan, dan yang besar
        # dicetak sebagai daftar rinci yang terlihat berwibawa.
        #
        # Usul pemilik menjawab KEDUANYA sekaligus, dan itu sebabnya ia tepat:
        # daftar yang menyusut sendiri tak pernah jadi panjang. Beras yang
        # keluar lebih dulu adalah beras yang disosoh lebih dulu, jadi yang
        # MASIH di gudang datang dari penyosohan yang PALING BARU.
        rinci = _fifo_sisa(baris_hasil, k + pindah_silo.get(jenis, 0.0))

        kartu.append(KartuProduk(
            jenis=jenis, nama=nama_produk(jenis), hasil_kg=h,
            hasil=rinci[:BATAS_RINCI_HASIL],
            hasil_lagi=max(len(rinci) - BATAS_RINCI_HASIL, 0),
            hasil_lagi_kg=sum(r.kg for r in rinci[BATAS_RINCI_HASIL:]),
            keluar_lagi=max(len(baris_keluar) - BATAS_RINCI_KELUAR, 0),
            keluar_lagi_kg=sum(r.kg for r in baris_keluar[BATAS_RINCI_KELUAR:]),
            belum_final_kg=berjalan.get(jenis, 0.0),
            dikemas_kg=punya_rumah, curah_kg=curah,
            kemasan_stok_kg=kemasan_stok, curah_stok_kg=curah_stok,
            ukuran_kemasan_otomatis=ukuran_auto,
            jumlah_karung_otomatis=jumlah_auto,
            dikemas_otomatis_kg=dikemas_auto,
            curah_otomatis_kg=curah_auto,
            # `keluar_kg` TETAP SELURUHNYA walau daftarnya dipotong: memotong
            # daftar tak boleh memotong persamaannya, dan seluruh kartu ini
            # berdiri di atas hasil = keluar + dikemas + curah.
            keluar_kg=k, keluar=baris_keluar[:BATAS_RINCI_KELUAR], sisa_kg=sisa,
            curah_saja=curah_saja))
    return kartu


#: Urutan tampil: beras terbaik lebih dulu, hasil samping menyusul.
_URUT_BARANG = {j: n for n, j in enumerate(
    ("premium", "medsuper", "medium", "sayur", "beras_putih", "beras_b",
     "bekatul", "menir", "broken", "reject"))}


@dataclass
class BarangJadiG2:
    """Isi gudang barang jadi: yang dijual, dan hasil sampingnya.

    Keduanya memuat barang PABRIK *dan* barang TITIPAN (pesanan jasa) —
    masing-masing baris menyebut pemiliknya lewat `jasa_id`/`pemilik`. Lihat
    catatan panjang di `barang_jadi_g2()` untuk kenapa menyaringnya di sini
    salah tempat, dan `CLAUDE.md` § "Stok Produk — barang jasa".
    """

    produk: list[dict]
    samping: list[dict]


async def barang_jadi_g2(db: AsyncSession) -> BarangJadiG2:
    """Stok barang jadi Gudang 2 — satu kartu per SKU × mutu × PEMILIK.

    Satu kartu = satu SKU × mutu (jenis · merk · kemasan · ukuran) × pemilik;
    stoknya masuk − keluar lewat `hitung_stok_finished_goods`, rinciannya per
    proses penyosohan asal supaya "dari sosohan mana" tetap terjawab saat ada
    keluhan mutu. Bekatul curah berdiri sendiri: ia tak pernah dikemas.

    ⚠⚠ BARANG TITIPAN (pesanan jasa) IKUT DIDAFTAR DI SINI, dan itu disengaja
    — keputusan pemilik 6 Oktober 2026, pola yang SAMA dengan `LotPk`/
    `LotPkG2` di sisi PK (lihat catatan `jasa_id` pada keduanya). Barangnya
    memang berdiri di gudang yang sama; daftar stok yang menyembunyikannya
    akan berselisih dengan apa yang dilihat orang di lantai — jenis
    kebohongan yang paling cepat membuat layar berhenti dipercaya.

    Yang TIDAK boleh adalah ia ikut ke borang yang MENJUAL
    (`aksi_inventory.stok_barang_jadi`, `barang_bisa_keluar`) — keduanya
    WAJIB menyaring `jasa_id is None` sendiri, di tempat pemakaiannya,
    persis seperti sisi PK sudah melakukannya
    (`aksi_inventory.barang_bisa_keluar` membuang `l.jasa_id is not None`).
    Melewatkan satu pemakai saja berarti beras pelanggan muncul di borang
    penjualan.

    Kunci kartunya ikut `jasa_id` (bukan cuma SKU × mutu): 40 karung Bu Sri
    tak boleh menyatu dengan karung pabrik jadi satu baris — angka gabungan
    begitu lebih buruk daripada tak menampilkannya sama sekali, sebab ia
    terbaca sebagai milik pabrik.

    ⚠ BEKATUL KARUNG ikut aturan ini apa adanya sejak 6 Oktober 2026 (lihat
    `HASIL_DITAHAN_BAWAAN`): `jasa_id` dibaca langsung dari barisnya, sama
    seperti kategori lain — bukan lagi selalu NULL. Blok bekatul CURAH di
    bawah (baris sintetis, bukan `FinishedGoodsStock`) TETAP pabrik-saja —
    ia memberi makan layar Stok Gudang 2, bukan Produk Jasa; lihat catatan
    di baris itu sendiri.

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
        Brand, ByproductStock, CustomerReturn, FinishedGoodsStock, PackageSize,
        PackagingMaterial, ProductSku, RiceQualityStandard)
    from app.services.jasa import nama_pemilik_banyak

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
        # PABRIK *dan* TITIPAN — lihat catatan ⚠⚠ di atas. Penyaringan untuk
        # borang penjualan terjadi DI PEMAKAINYA, bukan di sini.
        .order_by(FinishedGoodsStock.waktu.desc())
    )).all()

    nama_pemilik = await nama_pemilik_banyak(db, {fg.jasa_id for fg, *_ in baris})

    tiket_ids = {fg.source_id for fg, *_ in baris
                 if fg.source_type == "timbangan" and fg.source_id is not None}
    tiket_masuk = {}
    if tiket_ids:
        tiket_masuk = dict((await db.execute(
            text("SELECT id, kode FROM timbangan_transaksi WHERE id IN :ids")
            .bindparams(bindparam("ids", expanding=True)),
            {"ids": list(tiket_ids)},
        )).all())

    # Penerimaan retur menunjuk CustomerReturn, bukan proses sosoh/tiket.
    # Tampilkan asalnya di rincian kartu agar tanggal masuk stok, tiket asal,
    # pelanggan, dan kendaraan tidak tertukar.
    retur_ids = {fg.source_id for fg, *_ in baris
                 if fg.source_type == "retur" and fg.source_id is not None}
    retur_asal = {}
    if retur_ids:
        retur_asal = {r.id: r for r in (await db.execute(
            select(CustomerReturn).where(CustomerReturn.id.in_(retur_ids))
        )).scalars().all()}

    kartu: dict[tuple, dict] = {}
    for fg, sku, merk, kemasan, ukuran, mutu_kode, mutu_nama, pol in baris:
        kunci = (sku.id, fg.rice_quality_standard_id, fg.jasa_id)
        k = kartu.get(kunci)
        if k is None:
            stok_ = await bj.hitung_stok_finished_goods(
                db, sku.id, fg.rice_quality_standard_id, jasa_id=fg.jasa_id)
            if stok_["karung"] <= 0 and stok_["kg"] <= 0:
                kartu[kunci] = None
                continue
            # Satu aturan, satu tempat — `jenis_produk`. Namanya masih dari
            # standar mutunya kalau ada, sebab di sini yang dibaca orang adalah
            # nama panjangnya, bukan kodenya.
            jenis = jenis_produk(sku.kategori, mutu_kode)
            nama = (mutu_nama or "Beras putih") if sku.kategori == "beras_putih" \
                else NAMA_KATEGORI.get(sku.kategori, sku.kategori.title())
            if merk:
                nama += f" · {merk}"
            k = kartu[kunci] = {
                "jenis": jenis, "nama": nama, "kemasan": f"{kemasan} {ukuran} kg",
                # Pesanan jasa yang memiliki kartu ini — None = milik pabrik.
                # "JAS-2610-007 Pak Budi" dicetak di layar, sebangun `LotPk.pemilik`.
                "jasa_id": fg.jasa_id, "pemilik": nama_pemilik.get(fg.jasa_id),
                # ── Dua medan TAMBAHAN, bukan pengganti ──
                #
                # Permintaan pemilik 28 September 2026 atas rincian kemasan di
                # kartu Stok Produk: "kita sudah tau kalau itu premium. jadi
                # informasi yang sudah dikemas tidak perlu lagi informasi
                # premium. dan kata 'karung' dihapus saja agar readability
                # lebih baik."
                #
                # Benar: barisnya berada DI DALAM kartu Premium, jadi menyebut
                # "Premium" tiga kali di satu layar cuma menambah lebar tanpa
                # menambah kabar — dan lebar itu yang membuat barisnya patah
                # dua di ponsel.
                #
                # `nama` dan `kemasan` TIDAK diubah: hitungan ini dibaca layar
                # Barang jadi juga, dan di SANA kategorinya tidak diketahui dari
                # tempatnya — kartunya berdiri sendiri, jadi "Premium · Lele"
                # memang keterangan yang dibutuhkan. Satu layar minta lebih
                # pendek; itu bukan alasan memendekkan layar sebelah.
                "merk": merk or "",
                # "Karung biasa" → "biasa". Yang dibuang kata GENERIKNYA, bukan
                # ukurannya: di dalam kartu beras, semua yang dikemas memang
                # berkarung.
                "bahan": _tanpa_karung(kemasan),
                "ukuran": int(ukuran), "karung": stok_["karung"], "kg": stok_["kg"],
                # Id-nya ikut sejak 28 September 2026: borang "Barang jadi
                # keluar" memilih DARI DAFTAR INI, dan satu-satunya cara
                # menunjuk kartu ini tanpa ambiguitas adalah pasangan idnya.
                # Merk & mutu yang sama bisa punya dua kemasan, dan kemasan
                # yang sama bisa punya dua merk.
                "sku_id": sku.id, "std_id": fg.rice_quality_standard_id,
                "asal": [], "_pol": {}}
        if k is None:
            continue
        if pol:
            a = k["_pol"].setdefault(pol, [0, 0.0])
            a[0] += int(fg.jumlah_karung)
            a[1] += float(fg.berat_total_kg)
        elif fg.source_type == "timbangan" and fg.source_id is not None:
            # Pembelian beras putih dari Pos Timbang masuk langsung sebagai
            # FinishedGoodsStock, bukan sebagai hasil sosohan. Tanpa asal
            # tiket di laci, stok agregat naik tetapi operator tak bisa
            # menelusuri tiket dan berat yang baru diterima.
            kode = tiket_masuk.get(fg.source_id) or f"ID {fg.source_id}"
            k["asal"].append((f"Tiket {kode}",
                              f"{float(fg.berat_total_kg):,.0f} kg".replace(",", "."),
                              f"Masuk dari Timbangan · {_tgl(fg.waktu)}"))
        elif fg.source_type == "retur" and fg.source_id is not None:
            retur = retur_asal.get(fg.source_id)
            if retur:
                pelanggan = retur.nama_pelanggan or "Pelanggan tidak tercatat"
                armada = retur.nomor_polisi or "Plat tidak tercatat"
                k["asal"].append((
                    f"Retur {retur.kode} · {pelanggan} · {armada}",
                    f"{float(fg.berat_total_kg):,.0f} kg".replace(",", "."),
                    f"Masuk stok {_tgl(retur.waktu)} · tiket {retur.kode_tiket}"))
    produk, samping = [], []
    for k in kartu.values():
        if k is None:
            continue
        k["asal"].extend(
            (pol, f"{berat:,.0f} kg".replace(",", "."), f"{n} karung")
            for pol, (n, berat) in k.pop("_pol").items())
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
            # `merk` & `bahan` ikut sejak kartu Stok Produk memakainya (28
            # September 2026). Tanpa keduanya barisnya tergambar kosong —
            # bukan galat, cuma titik tanpa keterangan di dalam laci.
            # `ukuran` 0 berarti "bukan karung"; templatnya tak mencetaknya.
            "jenis": "bekatul", "nama": "Bekatul", "kemasan": "curah", "ukuran": 0,
            "merk": "", "bahan": "curah",
            # PABRIK saja, sengaja — baris ini memberi makan layar Stok
            # Gudang 2 (bukan Produk Jasa, lihat ⚠ di docstring fungsi ini).
            # Bekatul curah milik PESANAN tersebut lewat `hitung_stok_
            # bekatul(jasa_id=...)` sendiri di `layar_produk.
            # halaman_stok_produk_jasa`, bukan lewat baris sintetis ini.
            "jasa_id": None, "pemilik": None,
            "karung": 0, "kg": curah,
            "asal": [(kode, f"{float(kg):,.0f} kg".replace(",", "."), "curah")
                     for kode, kg in per_pol][:8]})
    for daftar in (produk, samping):
        daftar.sort(key=lambda k: (_URUT_BARANG.get(k["jenis"], 99),
                                   k["nama"], k["ukuran"]))
    return BarangJadiG2(produk=produk, samping=samping)
