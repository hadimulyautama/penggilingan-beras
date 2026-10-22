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
from app.services import keputusan as K
from app.services.berjalan import Baris, _kg, _lama
from app.web.layar import GUDANG, NAMA_GUDANG

#: Tiga golongan keputusan yang disebut Beranda, dan alasannya satu: "3 menunggu"
#: tak memberi tahu apakah yang tertahan harga, output, atau mutu — dan ketiganya
#: dikerjakan orang yang berbeda dengan urgensi yang berbeda.
#:
#: DITURUNKAN dari `services.keputusan.JENIS`, tidak diketik lagi di sini.
#: Sejak 24 September 2026 golongan "mutu" bukan cuma rincian di Beranda
#: melainkan LAYAR tersendiri (`/mutu`), dan dua daftar yang memegang pembagian
#: yang sama akan hanyut — yang satu mendapat jenis ketujuh, yang lain tidak.
#: Namanya dipertahankan: ia sudah dibaca templat dan uji.
GOLONGAN_KEPUTUSAN: dict[str, tuple[str, ...]] = dict(K.GOLONGAN)


@dataclass
class Papan:
    """Yang dibaca Beranda pemegang kedua gudang."""

    perhatian: list[dict] = field(default_factory=list)
    gudang: list[dict] = field(default_factory=list)
    #: Golongan "harga" dibuang 28 September 2026 bersama seluruh harga;
    #: yang memimpin rincian kini permintaan lot PK.
    n_permintaan: int = 0
    n_output: int = 0
    n_mutu: int = 0


def _ribuan(n) -> str:
    return "{:,}".format(int(n or 0)).replace(",", ".")


_HARI = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
_BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember")


def sapaan_dan_tanggal(nama: str | None) -> tuple[str, str]:
    """("Selamat pagi, Wahid", "Rabu, 21 Oktober 2026") untuk sambutan Beranda.

    Jam SERVER (`now_local()`, zona `settings.app_timezone`) yang memutuskan
    pagi/siang/sore/malam — bukan jam peramban, yang bisa berbeda dari jam
    gudang sungguhan bila jam perangkatnya sendiri salah setel.
    """
    kini = now_local()
    sebutan = ("pagi" if kini.hour < 11 else "siang" if kini.hour < 15
               else "sore" if kini.hour < 18 else "malam")
    depan = (nama or "").strip().split(" ")[0] or "Anda"
    tgl = kini.date()
    tanggal = f"{_HARI[tgl.weekday()]}, {tgl.day} {_BULAN[tgl.month - 1]} {tgl.year}"
    return f"Selamat {sebutan}, {depan}", tanggal


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

    DUA sumbernya, dan keduanya menahan pekerjaan: mesin yang dijeda, dan
    tumpukan Gudang 2 yang melewati batas.

    Yang ketiga — "harga menggantung lebih dari dua hari" — dibuang 28
    September 2026 bersama seluruh harga (keputusan pemilik).
    """
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
                           "href": f"/gudang/{gid}" if gid else "/berjalan", "gudang": gid,
                           "duplikat_proses": True})

    tump = float(await hitung_stok_tumpukan(db))
    maks = float(settings.g2_tumpukan_maks_kg or 0)
    if maks and tump > maks:
        keluar.append({"judul": "Tumpukan PK Gudang 2 melebihi batas",
                       "ket": f"{_kg(tump)} dari {_kg(maks)}",
                       "href": "/gudang/g2", "gudang": "g2"})

    # Dua butir "Harga … menggantung" DIBUANG 28 September 2026: harga keluar
    # dari Pos Produksi (keputusan pemilik). `flag_unverified` kini tak pernah
    # kembali ke False, jadi keduanya akan menyebut SELURUH gabah dan PK luar
    # yang pernah masuk — daftar yang tak pernah habis, di blok yang gunanya
    # justru memilih yang mendesak saja.
    return keluar


async def angka_gudang(db) -> dict:
    """Angka mentah per gudang — untuk petak pabrik dan baris gudang."""
    from app.models import PurchaseBatch
    from app.penggilingan.gudang1.services import tumpukan as tmp
    from app.penggilingan.gudang1.services.milling import stok_pk_g1_pemilik
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
    # STOK PABRIK: barang titipan tidak dihitung. Petak Beranda menjawab
    # "berapa yang pabrik punya", dan angka yang memuat barang pelanggan
    # membuat pabrik melihat barang orang lain sebagai persediaannya.
    tump_g1 = await tmp.jumlah_kg(db, pemilik="pabrik")
    tump_g1_jasa = await tmp.jumlah_kg(db, pemilik="jasa")
    # ── "berapa yang PABRIK punya", bukan "berapa yang ada di lantai" ──
    #
    # Petak Beranda menjawab pertanyaan MILIK. PK titipan yang menunggu diambil
    # pemiliknya bukan persediaan pabrik, dan angka yang mencampurnya membuat
    # pabrik melihat barang orang lain sebagai miliknya — lalu merencanakan
    # dengan angka itu.
    #
    # Isi FISIK-nya tetap terbaca di layar Stok Gudang 2, per tempat, berikut
    # pemiliknya: yang disembunyikan hanya dari hitungan milik, bukan dari mata.
    # ⚠ DAN TITIPANNYA DISEBUT DI SEBELAHNYA, tidak dihilangkan.
    #
    # Menyaring saja ternyata tidak cukup, dan itu laporan dari lapangan (2
    # Oktober 2026): PK titipan yang selesai digiling TAK TERBACA di mana pun
    # pada layar yang orang buka lebih dulu — Beranda menyebut "PK 0 kg"
    # sementara tujuh ton barang pelanggan berdiri di lantai Gudang 1. Operator
    # Gudang 2 lalu menyimpulkan barangnya tak bisa dipindahkan ke sana, padahal
    # rantai permintaan→kirim menerimanya dengan baik.
    #
    # Jadi aturannya bukan "sembunyikan barang orang lain" melainkan "jangan
    # pernah menghitungnya sebagai milik pabrik". Angkanya DUA, berdampingan,
    # dan yang kedua bernama terang-terangan TITIPAN — pola yang sama dengan
    # `jasa_kg` pada gabah masuk.
    silo_g2 = silo_g2_jasa = 0.0
    for huruf in ("A", "B"):
        silo = await get_g2_silo(db, huruf)
        if silo is None:
            continue
        silo_g2 += float(await hitung_stok_silo(db, silo.id, pemilik="pabrik"))
        silo_g2_jasa += float(await hitung_stok_silo(db, silo.id, pemilik="jasa"))
    tump_g2 = float(await hitung_stok_tumpukan(db, pemilik="pabrik"))
    tump_g2_jasa = float(await hitung_stok_tumpukan(db, pemilik="jasa"))
    pk_g1, pk_g1_jasa = await stok_pk_g1_pemilik(db)
    return {
        "masuk_kg": float(gabah_kg or 0) + float(pk_kg or 0),
        "masuk_n": int(gabah_n or 0) + int(pk_n or 0),
        "g1": {"stok_pk": pk_g1, "tumpukan": tump_g1,
               "jasa_pk": pk_g1_jasa, "jasa_tumpukan": tump_g1_jasa},
        "g2": {"stok_pk": silo_g2 + tump_g2, "tumpukan": tump_g2,
               "jasa_pk": silo_g2_jasa + tump_g2_jasa,
               "jasa_tumpukan": tump_g2_jasa},
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
        # Titipan disebut TERPISAH dan diberi namanya. Barisnya pintu menuju
        # gudangnya, dan pintu yang menyebut "PK 0 kg" untuk lantai yang penuh
        # membuat orang tak masuk — itu persisnya yang terjadi 2 Oktober 2026.
        if a[gid].get("jasa_pk"):
            ket += f" · titipan {_ribuan(a[gid]['jasa_pk'])} kg"
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
    stok_jasa = a["g1"].get("jasa_pk", 0.0) + a["g2"].get("jasa_pk", 0.0)
    tump = a["g1"]["tumpukan"] + a["g2"]["tumpukan"]
    return [
        {"label": "Masuk hari ini", "nilai": _ribuan(a["masuk_kg"]), "sat": " kg",
         "ket": f"{a['masuk_n']} batch · gabah & PK", "nada": ""},
        # Angka petaknya tetap MILIK PABRIK — ia yang dipakai merencanakan
        # penjualan. Titipannya menempel di keterangannya, tanpa nada bahaya:
        # barang orang lain di gudang bukan masalah, ia cuma harus terlihat.
        {"label": "Stok PK", "nilai": _ribuan(stok), "sat": " kg",
         "ket": ("seluruh gudang" if not stok_jasa else
                 f"seluruh gudang · + titipan {_ribuan(stok_jasa)} kg"),
         "nada": ""},
        {"label": "Mesin menyala", "nilai": mesin, "sat": " proses",
         "ket": (f"{jeda} dijeda" if jeda else "semua jalan") if mesin else "tak ada",
         "nada": "bahaya" if jeda else ""},
        {"label": "Menumpuk", "nilai": _ribuan(tump), "sat": " kg",
         "ket": "gabah & PK di lantai",
         "nada": "bahaya" if a["tumpukan_g2_maks"] and a["g2"]["tumpukan"] > a["tumpukan_g2_maks"]
                 else ""},
    ]


async def papan(db, berjalan: list, meja: list, angka: dict | None = None) -> Papan:
    """Seluruh papan sekaligus — satu perhitungan, dua pembaca (Pos Produksi &
    Meja).

    `angka` boleh dititipkan pemanggil yang sudah menghitungnya untuk petak
    teratas halaman yang sama (`layar.petak_beranda`): dua perhitungan pada
    satu halaman bukan cuma dua kali kerja, ia juga bisa menyebut dua angka
    berbeda bila ada yang menulis di antaranya.
    """
    perh = await perhatian(db, berjalan)
    a = angka if angka is not None else await angka_gudang(db)
    n = hitung_keputusan(meja)
    return Papan(perhatian=perh, gudang=baris_gudang(a, berjalan, perh),
                 n_permintaan=n.get("permintaan", 0),
                 n_output=n.get("output", 0), n_mutu=n.get("mutu", 0))
