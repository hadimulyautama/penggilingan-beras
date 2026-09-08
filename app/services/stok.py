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

from app.models import MillingProcess
from app.services.berjalan import _lama


#: Kondisi gabah saat DIBELI → kelas PK yang keluar darinya.
#:
#: Pemilik memutuskan layar memakai kelas PK-nya saja: "basah"/"kering" adalah
#: keadaan gabah kemarin, sedangkan yang dijual dan dibicarakan orang adalah
#: KS dan KL. Dua kosakata untuk satu hal di kartu yang sama memaksa pembacanya
#: menerjemahkan, dan yang menerjemahkan sesekali salah menerjemahkan.
KELAS = {"basah": "KS", "kering": "KL"}

#: Lebih dari satu kelas dalam satu lot. Bukan "campuran" — itu terbaca seperti
#: nama varietas — melainkan penanda bahwa isinya memang dua kelas.
KELAS_CAMPUR = "MIX"


def kelas_pk(kondisi: list[str]) -> str | None:
    """KS / KL / MIX dari daftar kondisi beli bahannya."""
    kode = [KELAS[k] for k in kondisi if k in KELAS]
    if not kode:
        return None
    return kode[0] if len(set(kode)) == 1 else KELAS_CAMPUR


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
    #: Sudah berapa lama PK ini menumpuk, dalam kata — "3 hari 4 jam".
    #:
    #: Dihitung sejak giling DITUTUP: sebelum itu PK-nya masih keluar dari
    #: mesin, jadi "menumpuk" belum berarti apa-apa. Untuk yang mesinnya masih
    #: menyala, dihitung sejak mulai — itu tetap menjawab "sudah sejak kapan
    #: barang ini ada di lantai", yang memang pertanyaannya.
    lama: str = ""
    #: Masih menyala mesinnya. PK-nya sudah ada, tapi angkanya belum final.
    berjalan: bool = False


def _tgl(d) -> str:
    return d.strftime("%d/%m") if d else "?"


def _kg(n) -> str:
    return f"{float(n or 0):,.0f} kg".replace(",", ".")


async def _bahan(db: AsyncSession, proc) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Bahan satu lot giling: berapa yang MASUK dari tiap sumber, dan dari siapa.

    Beratnya diambil dari `milling_process_sources.berat_kg` — berat yang
    benar-benar masuk mesin — BUKAN dari `purchase_batches.berat_total_kg`.
    Keduanya pernah tertukar di kartu ini, dan akibatnya kelihatan: satu batch
    berbunyi 8.250 kg di sebelah "Dari gabah 8.000 kg", padahal 8.250 itu berat
    seluruh kiriman truknya dan hanya 4.000 yang masuk lot ini. Sisanya bisa
    tertinggal di silo atau ikut giling lain — batch memang boleh terbelah.

    Angka yang tak bisa dijumlahkan menjadi angka di atasnya akan dicurigai
    sebagai salah hitung, dan orang berhenti percaya pada seluruh kartunya.
    Sekarang jumlah baris-baris ini SAMA DENGAN "Dari gabah".

    Proses lama sebelum penautan timbang tak punya baris sumber; untuk mereka
    tak ada berat yang bisa dipertanggungjawabkan per batch, jadi yang disebut
    berat pembeliannya — dengan kata "dibeli" supaya tak disangka berat masuk.
    """
    from app.models import (MillingProcessSource, PurchaseBatch, Supplier)
    from app.penggilingan.gudang1.models.gudang1 import DryingLot, DryingLotBatch
    from app.penggilingan.gudang1.services.milling import sumber_batch

    async def _nama(b) -> str:
        sup = await db.get(Supplier, b.supplier_id)
        return (sup.nama_supplier if sup else None) or "?"

    baris = (await db.execute(
        select(MillingProcessSource)
        .where(MillingProcessSource.milling_process_id == proc.id)
        .order_by(MillingProcessSource.id))).scalars().all()

    bahan: list[tuple[str, str, str]] = []
    kondisi: set[str] = set()

    if not baris:
        for b, _harga, _lewat in await sumber_batch(db, proc):
            k = (b.kondisi_gabah or "").strip().lower()
            if k:
                kondisi.add(k)
            bahan.append((f"{await _nama(b)} · {b.kode_batch}",
                          f"dibeli {_kg(b.berat_total_kg)}",
                          f"masuk {_tgl(b.tanggal_pembelian)}"
                          + (f" · {KELAS[k]}" if k in KELAS else "")))
        return bahan, [k for k in ("basah", "kering") if k in kondisi]

    for s in baris:
        if s.drying_lot_id:
            batches = (await db.execute(
                select(PurchaseBatch)
                .join(DryingLotBatch,
                      DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .where(DryingLotBatch.drying_lot_id == s.drying_lot_id))).scalars().all()
        elif s.purchase_batch_id:
            b = await db.get(PurchaseBatch, s.purchase_batch_id)
            batches = [b] if b else []
        else:
            batches = []
        if not batches:
            continue
        for b in batches:
            k = (b.kondisi_gabah or "").strip().lower()
            if k:
                kondisi.add(k)
        k1 = (batches[0].kondisi_gabah or "").strip().lower()
        if len(batches) == 1:
            b = batches[0]
            nama = f"{await _nama(b)} · {b.kode_batch}"
            ket = (f"masuk {_tgl(b.tanggal_pembelian)}"
                   + (f" · {KELAS[k1]}" if k1 in KELAS else ""))
        else:
            # Satu muatan silo yang berasal dari satu pengeringan bisa berisi
            # beberapa batch, dan yang tercatat adalah berat MUATANNYA — bukan
            # per batch. Membaginya rata akan terlihat rapi dan tidak benar.
            lot = await db.get(DryingLot, s.drying_lot_id)
            nama_sup: list[str] = []
            for b in batches:
                n = await _nama(b)
                if n not in nama_sup:
                    nama_sup.append(n)
            ringkas = " & ".join(nama_sup[:2]) + (
                f" +{len(nama_sup) - 2}" if len(nama_sup) > 2 else "")
            nama = f"{ringkas} · {lot.kode_lot if lot else '?'}"
            ket = f"{len(batches)} batch" + (f" · {KELAS[k1]}" if k1 in KELAS else "")
        bahan.append((nama, _kg(s.berat_kg), ket))
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
        if bd.tersedia <= 0:
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
            rendemen=hitung_rendemen(bd.produced, proc.berat_gabah_masuk_kg),
            kelas=kelas_pk(kondisi),
            bahan=bahan,
            tanggal=_tgl(proc.waktu_selesai or proc.waktu_mulai),
            lama=_lama(proc.waktu_selesai or proc.waktu_mulai),
            berjalan=proc.status == "proses",
        ))
    return keluar
