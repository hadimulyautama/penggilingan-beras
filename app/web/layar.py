"""Siapa melihat layar yang mana — empat view, satu penentu.

Sampai sekarang aplikasi ini punya DUA tampilan yang menyamar sebagai empat:
"admin ke atas" dan "selebihnya". Akibatnya dua pasang orang melihat layar
yang bukan miliknya.

  · **Super Admin dan Admin** melihat layar yang sama persis, padahal daftar
    peran di halaman Pengguna sudah lama menuliskan bedanya: Super Admin
    "semua di atas, DITAMBAH mengelola orang, akun, dan alat". Yang tertulis
    di daftar peran tetapi tak terlihat di layar bukan aturan — ia niat.

  · **Operator selepan dan operator polesan** juga melihat layar yang sama,
    dan layar itu dibentuk untuk selepan: Beranda menyebut gabah masuk,
    pengeringan, silo gabah, stok PK — empat angka yang tak satu pun berasal
    dari gudang tempat operator polesan bekerja. Halaman Stok lebih jauh lagi:
    seluruh isinya lot giling Gudang 1.

Yang menentukan view HANYA di sini. Satu tempat, karena tiap layar yang
menebak sendiri perannya adalah satu tempat lagi yang bisa menebak berbeda —
dan yang berbeda diam-diam tak akan ada yang menyadarinya.

**Ini soal TAMPILAN, bukan wewenang.** Gerbang yang menolak sungguhan tetap
di rutenya masing-masing (`butuh_admin`, `can_see_financials`, `wajib(...)`).
Yang dikerjakan modul ini cuma memilih apa yang ditawarkan; menyembunyikan
pintu tak pernah menjadi kunci.
"""
from __future__ import annotations

from app.models import User
from hmu_identitas import peran as P

#: Empat view — namanya milik paket `hmu_identitas.peran` sejak Tahap 2,
#: supaya Meja dan Gudang 2 (yang menerima `view` dari sini) membaca nama
#: yang sama persis. TAMU = operator yang belum diberi gudang: bukan view
#: kelima, melainkan keadaan yang harus terbaca sebagai kesalahan pendaftaran.
SUPER, ADMIN, SELEPAN, POLESAN, TAMU = P.V_SUPER, P.V_ADMIN, P.V_SELEPAN, P.V_POLESAN, P.V_TAMU
NAMA_VIEW = P.NAMA_VIEW

#: View yang memegang kedua gudang sekaligus — dan karena itu melihat uang.
MEJA = P.VIEW_MEJA


def gudang1(view: str) -> bool:
    """Apakah view ini berurusan dengan Gudang 1 (selepan)."""
    return view in (SUPER, ADMIN, SELEPAN)


def gudang2(view: str) -> bool:
    """Apakah view ini berurusan dengan Gudang 2 (polesan)."""
    return view in (SUPER, ADMIN, POLESAN)


async def view_untuk(user: User | None) -> str:
    """View orang ini — dari peran EFEKTIF, bukan peran tersimpan.

    Peran efektif itu yang penting: Super Admin yang sedang memakai "Lihat
    sebagai operator Gudang 2" harus mendapat layar operator polesan yang
    sesungguhnya, lengkap dengan yang HILANG darinya. Samaran yang masih
    menyisakan angka uang di Beranda bukan samaran, dan pemilik yang
    memakainya akan pulang mengira operatornya melihat hal yang tak pernah
    ia lihat.
    """
    if user is None:
        return TAMU
    if P.operator_saja(user.role):
        # Dipinjam dari katalog aksi supaya jawaban "operator gudang mana"
        # tak pernah berselisih antara menu aksi dan layar yang memuatnya.
        from app.web.api import _is_g1_operator, _is_g2_operator

        if await _is_g2_operator(user):
            return P.view(user.role, P.G2)
        if await _is_g1_operator(user):
            return P.view(user.role, P.G1)
        return P.view(user.role, P.TANPA)
    return P.view(user.role, P.SEMUA)


# ───────────────────────── Petak Beranda per view ─────────────────────────
#
# Beranda adalah layar yang paling sering dibuka dan paling jarang dibaca
# sampai habis: orang melihatnya beberapa detik, lalu bertindak. Maka empat
# angka pertamanya harus angka PEKERJAANNYA SENDIRI. Operator polesan yang
# disambut "Gabah masuk 41.200 kg" membaca kabar dari gudang sebelah, lalu
# belajar bahwa baris teratas Beranda bukan untuknya — dan sesudah itu ia tak
# membacanya lagi.
#
# Bentuk petaknya SATU untuk semua view. Yang berganti isinya, bukan
# gambarnya: layar yang tata letaknya ikut berbeda per peran adalah empat
# layar yang harus dirawat empat kali.


def _ribuan(n) -> str:
    return "{:,}".format(int(n or 0)).replace(",", ".")


def _sel(label, nilai, *, sat="", ket="", nada="") -> dict:
    return {"label": label, "nilai": nilai, "sat": sat, "ket": ket, "nada": nada}


def _petak_g1(o: dict) -> list[dict]:
    """Empat angka Gudang 1 — persis yang sudah ada sejak Beranda dibuat.

    Tidak diutak-atik. Pemilik menyebutnya sendiri: "sejauh ini optimal untuk
    gudang selepan". Yang optimal tidak diperbaiki hanya karena tetangganya
    sedang dibuat.
    """
    gabah = o.get("gabah_hari_ini", {}) or {}
    silo = o.get("silo", []) or []
    stok = o.get("stok_pk", {}) or {}
    terisi = sum(1 for s in silo if s.get("terisi"))
    kering = len(o.get("pengeringan", []) or [])
    giling = len(o.get("giling", []) or [])
    maks = stok.get("maks", 0) or 0
    total = stok.get("total", 0) or 0
    return [
        _sel("Gabah masuk", _ribuan(gabah.get("total_kg", 0)), sat=" kg",
             ket=f"{gabah.get('batch', 0) or 0} batch"),
        _sel("Pengeringan", kering, sat=" lot",
             ket="berjalan" if kering else "tak ada",
             nada="hati" if kering else ""),
        _sel("Silo terisi", terisi, sat=f" / {len(silo)}",
             nada="aman" if terisi else ""),
        _sel("Stok PK", _ribuan(total), sat=" kg",
             ket=(f"tumpukan maks {int(maks / 1000)} ton · " if maks else "")
                 + f"{giling} giling berjalan",
             nada="bahaya" if maks and total > maks else ""),
    ]


async def _petak_g2(db) -> list[dict]:
    """Empat angka Gudang 2 — cerminnya, bukan salinannya.

    Urutannya sengaja mengikuti perjalanan barang yang sama seperti Gudang 1:
    apa yang MASUK hari ini, mesin apa yang MENYALA, di mana barangnya
    TERSIMPAN, berapa yang MENUMPUK. Operator yang pindah gudang membaca
    layar yang letaknya sudah ia kenal.
    """
    from sqlalchemy import func, select

    from app.config import settings
    from app.database import now_local
    from app.penggilingan.gudang2.models import PkPurchaseBatch, PolishingProcess
    from app.penggilingan.gudang2.service import (
        get_g2_silo, hitung_stok_silo, hitung_stok_tumpukan)

    hari = now_local().date()
    pk_kg, pk_n = (await db.execute(
        select(func.coalesce(func.sum(PkPurchaseBatch.berat_total_kg), 0),
               func.count(PkPurchaseBatch.id))
        .where(PkPurchaseBatch.tanggal_pembelian == hari,
               PkPurchaseBatch.status_batch != "ditolak")
    )).one()
    sosoh = (await db.execute(
        select(func.count(PolishingProcess.id))
        .where(PolishingProcess.status == "proses")
    )).scalar() or 0

    isi: list[float] = []
    for huruf in ("A", "B"):
        silo = await get_g2_silo(db, huruf)
        isi.append(float(await hitung_stok_silo(db, silo.id)) if silo else 0.0)
    terisi = sum(1 for v in isi if v > 0)
    tump = float(await hitung_stok_tumpukan(db))
    maks = float(settings.g2_tumpukan_maks_kg or 0)

    return [
        _sel("PK masuk", _ribuan(pk_kg), sat=" kg", ket=f"{int(pk_n or 0)} batch"),
        _sel("Penyosohan", sosoh, sat=" proses",
             ket="berjalan" if sosoh else "tak ada",
             nada="hati" if sosoh else ""),
        _sel("Silo terisi", terisi, sat=" / 2",
             ket=f"{_ribuan(sum(isi))} kg", nada="aman" if terisi else ""),
        _sel("Tumpukan PK", _ribuan(tump), sat=" kg",
             ket=(f"maks {int(maks / 1000)} ton" if maks else ""),
             nada="bahaya" if maks and tump > maks else ""),
    ]


def _ganti_label(sel: dict, label: str) -> dict:
    """Salinan petak dengan label lain.

    Dipakai view yang memuat KEDUA gudang: "Stok PK" dua kali dalam satu
    baris adalah dua angka yang tak bisa dibedakan tanpa menghitung
    posisinya, dan yang harus dihitung posisinya tidak terbaca sekilas.
    """
    return {**sel, "label": label}


async def petak_beranda(db, view: str, o: dict) -> list[dict]:
    """Blok-blok petak Beranda untuk view ini.

    Satu blok = satu judul + empat angka, dua kolom. Operator selalu dapat
    SATU blok tanpa judul: ia cuma punya satu gudang, dan judul yang menamai
    satu-satunya isi layar tidak membedakan apa pun.

    Jumlah petaknya selalu GENAP. Petaknya digambar dua kolom, jadi blok
    berisi satu petak tampil sebagai kotak setengah lebar dengan lubang di
    sebelahnya — dan lubang itu terbaca sebagai sesuatu yang gagal dimuat.
    """
    if view == SELEPAN:
        return [{"judul": None, "sel": _petak_g1(o)}]
    if view == POLESAN:
        return [{"judul": None, "sel": await _petak_g2(db)}]
    if view == ADMIN:
        # Admin tidak menjalankan mesin. Yang ia butuh dari lantai cuma dua
        # pertanyaan per gudang: apa yang MASUK hari ini, dan berapa yang
        # MENUMPUK. Sisanya — mesin mana yang menyala — sudah ada di daftar
        # "Sedang berjalan" tepat di bawahnya, dan menyebutnya dua kali
        # membuat baris teratas berhenti jadi ringkasan.
        g1, g2 = _petak_g1(o), await _petak_g2(db)
        return [{"judul": None, "sel": [
            g1[0], _ganti_label(g1[3], "Stok PK G1"),
            g2[0], _ganti_label(g2[3], "Stok PK G2"),
        ]}]
    if view == SUPER:
        # Seluruh pabrik, dua blok bernama. Pemilik satu-satunya yang memang
        # perlu melihat keduanya sekaligus — dan satu-satunya yang tak bisa
        # bertanya kepada siapa pun kalau salah satunya luput.
        return [
            {"judul": "Gudang 1 — Selepan", "sel": _petak_g1(o)},
            {"judul": "Gudang 2 — Penyosohan", "sel": await _petak_g2(db)},
        ]
    return []
