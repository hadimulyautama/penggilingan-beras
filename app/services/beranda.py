"""Papan Beranda untuk pemegang KEDUA gudang — perhitungannya, bukan markupnya.

Lahir di `web/meja_api.py` (12 September 2026) sebagai isi Beranda Meja: urutan
yang dibalik, gudang sebagai DAFTAR, dan satu blok "Perlu perhatian" yang hanya
digambar bila ada yang menyimpang. Pindah ke sini 24 September 2026 — celah ke-5
menjelang app meja dihapus.

Dan pindah, bukan disalin. Beranda Pos Produksi yang menghitung sendiri
penyimpangannya adalah Beranda yang cepat atau lambat menyebut angka berbeda
dari Beranda Meja tentang pabrik yang sama — dan bedanya tak akan ada yang
menyadari, sebab tak ada yang membuka keduanya berdampingan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select

from app.config import settings
from app.database import now_local
from app.services.berjalan import Baris, _kg, _lama
from app.web.layar import GUDANG, NAMA_GUDANG

#: Tiga golongan keputusan yang disebut Beranda, dan alasannya satu: "3 menunggu"
#: tak memberi tahu apakah yang tertahan harga, output, atau mutu — dan ketiganya
#: dikerjakan orang yang berbeda dengan urgensi yang berbeda.
#:
#: Di sini, bukan di templat, supaya bisa DIUJI terhadap `AKSI_DIKENAL`: golongan
#: yang ketinggalan satu jenis membuat rinciannya tak berjumlah sama dengan
#: lencananya, dan angka yang tak berjumlah membuat orang berhenti mempercayai
#: keduanya. `betulkan_bobot_giling` masuk "output" — yang ditahannya memang
#: pencocokan hasil giling.
GOLONGAN_KEPUTUSAN: dict[str, tuple[str, ...]] = {
    "harga": ("verify_gabah", "harga_pk_luar"),
    "output": ("verify_output", "betulkan_bobot_giling"),
    "mutu": ("qc_giling", "qc_pk_luar"),
}


@dataclass
class Papan:
    """Yang dibaca Beranda pemegang kedua gudang."""

    perhatian: list[dict] = field(default_factory=list)
    gudang: list[dict] = field(default_factory=list)
    n_harga: int = 0
    n_output: int = 0
    n_mutu: int = 0


def _ribuan(n) -> str:
    return "{:,}".format(int(n or 0)).replace(",", ".")


def hitung_keputusan(meja: list) -> dict[str, int]:
    """Berapa keputusan per golongan. Menerima `Baris` maupun dict (JSON Meja)."""
    def aksi(x) -> str:
        return (x.get("aksi") if isinstance(x, dict) else x.aksi) or ""

    return {n: sum(1 for x in meja if aksi(x) in daftar)
            for n, daftar in GOLONGAN_KEPUTUSAN.items()}


async def perhatian(db, berjalan: list[Baris]) -> list[dict]:
    """Penyimpangan lintas gudang — HANYA yang benar-benar menyimpang.

    Blok yang selalu berisi mengajari orang mengabaikannya, dan warna yang
    dipakai untuk keadaan normal berhenti berarti apa-apa. Kosong = tak digambar.

    Tiga sumbernya, dan ketiganya menahan pekerjaan atau uang: mesin yang dijeda,
    tumpukan Gudang 2 yang melewati batas, dan harga yang menggantung lebih dari
    dua hari.
    """
    from app.models import PurchaseBatch
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan

    keluar = []
    for b in berjalan:
        nota = b.get("nota") if isinstance(b, dict) else b.nota
        jenis = b.get("nota_jenis") if isinstance(b, dict) else b.nota_jenis
        if jenis == "hati" and nota:
            gid = (b.get("gudang") if isinstance(b, dict) else b.gudang) or ""
            judul = b.get("judul") if isinstance(b, dict) else b.judul
            kode = b.get("kode") if isinstance(b, dict) else b.kode
            keluar.append({"judul": f"{judul} — {kode}", "ket": nota,
                           "href": f"/gudang/{gid}" if gid else "/berjalan", "gudang": gid})

    tump = float(await hitung_stok_tumpukan(db))
    maks = float(settings.g2_tumpukan_maks_kg or 0)
    if maks and tump > maks:
        keluar.append({"judul": "Tumpukan PK Gudang 2 melebihi batas",
                       "ket": f"{_kg(tump)} dari {_kg(maks)}",
                       "href": "/gudang/g2", "gudang": "g2"})

    batas = now_local() - timedelta(days=2)
    for g in (await db.execute(
        select(PurchaseBatch)
        .where(PurchaseBatch.flag_unverified.is_(True), PurchaseBatch.created_at < batas)
    )).scalars().all():
        keluar.append({"judul": f"Harga {g.kode_batch} menggantung",
                       "ket": f"{NAMA_GUDANG['g1']} · gabah · {_lama(g.created_at)}",
                       "href": "/keputusan", "gudang": "g1"})
    for p in (await db.execute(
        select(PkPurchaseBatch)
        .where(PkPurchaseBatch.flag_unverified.is_(True), PkPurchaseBatch.created_at < batas)
    )).scalars().all():
        keluar.append({"judul": f"Harga {p.kode_batch} menggantung",
                       "ket": f"{NAMA_GUDANG['g2']} · PK luar · {_lama(p.created_at)}",
                       "href": "/keputusan", "gudang": "g2"})
    return keluar


async def angka_gudang(db) -> dict:
    """Angka mentah per gudang — untuk petak pabrik dan baris gudang."""
    from app.models import PurchaseBatch
    from app.penggilingan.gudang1.services import tumpukan as tmp
    from app.penggilingan.gudang1.services.milling import stok_pk_g1
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import (get_g2_silo, hitung_stok_silo,
                                                  hitung_stok_tumpukan)

    hari = now_local().date()
    gabah_kg, gabah_n = (await db.execute(
        select(func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0), func.count(PurchaseBatch.id))
        .where(PurchaseBatch.tanggal_pembelian == hari)
    )).one()
    pk_kg, pk_n = (await db.execute(
        select(func.coalesce(func.sum(PkPurchaseBatch.berat_total_kg), 0), func.count(PkPurchaseBatch.id))
        .where(PkPurchaseBatch.tanggal_pembelian == hari, PkPurchaseBatch.status_batch != "ditolak")
    )).one()
    tump_g1 = sum(float(b.berat_total_kg or 0) for b in await tmp.isi(db))
    silo_g2 = 0.0
    for huruf in ("A", "B"):
        silo = await get_g2_silo(db, huruf)
        silo_g2 += float(await hitung_stok_silo(db, silo.id)) if silo else 0.0
    tump_g2 = float(await hitung_stok_tumpukan(db))
    return {
        "masuk_kg": float(gabah_kg or 0) + float(pk_kg or 0),
        "masuk_n": int(gabah_n or 0) + int(pk_n or 0),
        "g1": {"stok_pk": float(await stok_pk_g1(db)), "tumpukan": tump_g1},
        "g2": {"stok_pk": silo_g2 + tump_g2, "tumpukan": tump_g2},
        "tumpukan_g2_maks": float(settings.g2_tumpukan_maks_kg or 0),
    }


def baris_gudang(a: dict, berjalan: list, perhatian_: list[dict]) -> list[dict]:
    """Satu baris per gudang, dari DAFTAR — sepuluh gudang = sepuluh baris.

    Rinciannya (petak, mesin, transit) ada di halaman gudang itu sendiri;
    barisnya cuma pintu. Keputusan pemilik 12 September 2026: Beranda yang
    menumpuk satu blok per gudang jadi tiga layar begitu gudangnya dua.
    """
    perh = {p["gudang"] for p in perhatian_}
    keluar = []
    for gid, nama, fungsi in GUDANG:
        def milik(b, gid=gid):
            return (b.get("gudang") if isinstance(b, dict) else b.gudang) == gid

        ket = f"PK {_ribuan(a[gid]['stok_pk'])} kg"
        if a[gid]["tumpukan"]:
            ket += f" · menumpuk {_ribuan(a[gid]['tumpukan'])} kg"
        keluar.append({"id": gid, "nama": nama, "fungsi": fungsi, "ket": ket,
                       "mesin": sum(1 for b in berjalan if milik(b)),
                       "perhatian": gid in perh})
    return keluar


def petak_pabrik(a: dict, berjalan: list) -> list[dict]:
    """Empat angka PABRIK — tetap empat berapa pun jumlah gudangnya."""
    def jenis(b):
        return b.get("nota_jenis") if isinstance(b, dict) else b.nota_jenis

    mesin = len(berjalan)
    jeda = sum(1 for b in berjalan if jenis(b) == "hati")
    stok = a["g1"]["stok_pk"] + a["g2"]["stok_pk"]
    tump = a["g1"]["tumpukan"] + a["g2"]["tumpukan"]
    return [
        {"label": "Masuk hari ini", "nilai": _ribuan(a["masuk_kg"]), "sat": " kg",
         "ket": f"{a['masuk_n']} batch · gabah & PK", "nada": ""},
        {"label": "Stok PK", "nilai": _ribuan(stok), "sat": " kg", "ket": "seluruh gudang",
         "nada": ""},
        {"label": "Mesin menyala", "nilai": mesin, "sat": " proses",
         "ket": (f"{jeda} dijeda" if jeda else "semua jalan") if mesin else "tak ada",
         "nada": "bahaya" if jeda else ""},
        {"label": "Menumpuk", "nilai": _ribuan(tump), "sat": " kg",
         "ket": "gabah & PK di lantai",
         "nada": "bahaya" if a["tumpukan_g2_maks"] and a["g2"]["tumpukan"] > a["tumpukan_g2_maks"]
                 else ""},
    ]


async def papan(db, berjalan: list, meja: list) -> Papan:
    """Seluruh papan sekaligus — satu perhitungan, dua pembaca (Pos Produksi &
    Meja)."""
    perh = await perhatian(db, berjalan)
    a = await angka_gudang(db)
    n = hitung_keputusan(meja)
    return Papan(perhatian=perh, gudang=baris_gudang(a, berjalan, perh),
                 n_harga=n["harga"], n_output=n["output"], n_mutu=n["mutu"])
