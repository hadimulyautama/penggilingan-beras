"""Stok PK Gudang 1 — hasil giling yang masih ada, dirinci per lot.

Satu angka gabungan menjawab "berapa" tetapi tidak menjawab "yang mana", dan
di gudang pertanyaan kedua yang lebih sering muncul: PK mana yang sudah lama
menumpuk, PK mana yang gabahnya dari pemasok yang sedang dipersoalkan. Maka
barisnya adalah LOT GILING — satuan yang sama dengan yang tertulis di kartu
dan di catatan, jadi orang tak perlu menerjemahkan apa pun.

Gudang 2 (beras putih, menir, bekatul) sengaja belum ikut: pemilik memutuskan
Gudang 1 dulu. Kodenya tidak ditinggalkan menganggur di sini — riwayat git
menyimpannya, dan kode menganggur yang menunggu dipakai lagi selalu sudah
basi saat gilirannya tiba.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import MillingProcess
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
        """Nama pemasok SENDIRIAN di baris atas; kode-kodenya turun ke bawah.

        Digabung ("Kelompok Tani Sumber Rejeki · GB-20260904-10") baris itu
        membungkus di ponsel dan kodenya terlempar ke baris kedua sendirian —
        yang dipindai mata justru namanya, dan nama yang terpotong oleh kode
        membuat daftar ini berhenti bisa dibaca sekilas.
        """
        sup = await db.get(Supplier, b.supplier_id)
        nama = (sup.nama_supplier if sup else None) or "?"
        k = (b.kondisi_gabah or "").strip().lower()
        # Kode pengeringannya TIDAK ikut. Tiga kode dalam satu baris
        # memaksanya membungkus sampai tiga baris di ponsel, dan dari ketiganya
        # ia yang paling sedikit menjawab pertanyaan kartu ini — "gabah siapa,
        # berapa". Jalur pengeringannya tetap terbaca dari laporan lot.
        ket = f"{b.kode_batch} · masuk {_tgl(b.tanggal_pembelian)}"
        if k in KELAS_PK:
            ket += f" · {KELAS_PK[k]}"
        return (nama, _kg(b.berat_total_kg), ket)

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


async def pk_gudang1(db: AsyncSession) -> list[LotPk]:
    """Tiap lot giling yang PK-nya masih tersisa di Gudang 1, terbaru dulu.

    Yang sudah habis terkirim tidak ditampilkan: stok adalah apa yang ADA, dan
    daftar yang memuat baris nol mengajari orang melewatkan barisnya.
    """
    from app.penggilingan.gudang1.services.milling import _pk_breakdown, hitung_rendemen

    keluar: list[LotPk] = []
    for proc in (await db.execute(
        select(MillingProcess).order_by(MillingProcess.id.desc())
    )).scalars().all():
        bd = await _pk_breakdown(db, proc.id)
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
        bahan, kondisi = await _bahan(db, proc)
        keluar.append(LotPk(
            kode=proc.kode_proses,
            tersedia=bd.tersedia,
            dihasilkan=bd.produced,
            dikirim=bd.transferred,
            bahan_kg=float(proc.berat_gabah_masuk_kg or 0),
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
            bahan=bahan,
            tanggal=_tgl(proc.waktu_selesai or proc.waktu_mulai),
            lama=_hari(proc.waktu_selesai or proc.waktu_mulai),
            berjalan=proc.status == "proses",
            belum_dicatat=belum,
        ))
    return keluar
