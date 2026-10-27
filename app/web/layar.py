"""Satu tampilan induk; peran efektif menentukan data dan tindakan yang diizinkan.

Empat kode view tetap dipakai untuk cakupan gudang dan simulasi peran.
Struktur layar memakai susunan Super Admin; bagian tanpa izin terkunci.
Gerbang di endpoint tetap memeriksa pelaku sebelum membaca atau menulis.
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

#: (id, nama, fungsi) tiap gudang — daftar, bukan tata letak.
#:
#: Lahir di `meja_api` karena Meja layar pertama yang memperlakukan gudang
#: sebagai DAFTAR (keputusan pemilik 12 September 2026: "jika punya banyak
#: gudang pasti bingung"). Dipindah ke sini 24 September 2026 saat Pos Produksi
#: mulai memakainya juga — dua salinan daftar gudang berarti gudang ketiga yang
#: muncul di satu layar dan tidak di layar sebelahnya.
#:
#: Ia sengaja TIDAK diturunkan dari tabel `warehouses`: yang di sini adalah dua
#: FUNGSI pabrik yang dikenal kode (selepan & penyosohan, masing-masing dengan
#: alur dan layarnya sendiri), bukan sembarang baris gudang yang bisa ditambah
#: orang di Pengaturan.
GUDANG: tuple[tuple[str, str, str], ...] = (
    ("g1", "Gudang 1", "Selepan"),
    ("g2", "Gudang 2", "Penyosohan"),
)
NAMA_GUDANG: dict[str, str] = {k: n for k, n, _ in GUDANG}
FUNGSI_GUDANG: dict[str, str] = {k: f for k, _, f in GUDANG}


def boleh_lihat_gudang(view: str, gid: str) -> bool:
    """Bolehkah view ini membuka halaman ringkasan gudang `gid`?

    Dipakai gerbang halaman `/gudang/{gid}`. Operator TIDAK dilarang melihat
    gudangnya sendiri — Beranda-nya sudah memuat petak yang sama — tapi ia tak
    boleh membuka gudang SEBELAH: angka gudang lain bukan pekerjaannya, dan
    layar yang menawarkannya mengajari orang membaca kabar yang tak bisa ia
    tindaklanjuti.
    """
    return {"g1": gudang1, "g2": gudang2}[gid](view) if gid in NAMA_GUDANG else False


def gudang1(view: str) -> bool:
    """Apakah view ini berurusan dengan Gudang 1 (selepan)."""
    return view == 'pelanggan' or view in (SUPER, ADMIN, SELEPAN)


def gudang2(view: str) -> bool:
    """Apakah view ini berurusan dengan Gudang 2 (polesan)."""
    return view == 'pelanggan' or view in (SUPER, ADMIN, POLESAN)


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
    from app.web.portal.security import CustomerReader
    if isinstance(user, CustomerReader):
        return "pelanggan"
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


# Ringkasan memakai dua blok yang sama. Nilai gudang yang tidak dapat dibaca
# tidak ditanyakan ke database dan diganti penanda akses terkunci.


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
             # Barang titipan ikut di angkanya (itu memang yang turun dari truk)
             # tetapi DISEBUT di keterangannya: petak yang satu angkanya berarti
             # dua hal akan dipakai untuk keduanya, lalu salah untuk keduanya.
             ket=f"{gabah.get('batch', 0) or 0} batch"
                 + (f" · {_ribuan(gabah.get('jasa_kg', 0))} kg jasa"
                    if gabah.get("jasa_batch") else "")),
        _sel("Pengeringan", kering, sat=" lot",
             ket="berjalan" if kering else "tak ada",
             nada="hati" if kering else ""),
        _sel("Silo terisi", terisi, sat=f" / {len(silo)}",
             nada="aman" if terisi else ""),
        # Titipan pelanggan DISEBUT, tidak dihilangkan — sama seperti pada
        # "Gabah masuk" di atas. Angkanya tetap milik pabrik; yang bertambah
        # cuma kalimat yang mengaku ada barang lain di lantai. Tanpa itu petak
        # ini menyebut 0 kg untuk gudang yang penuh (laporan 2 Okt 2026).
        _sel("Stok PK", _ribuan(total), sat=" kg",
             ket=(f"tumpukan maks {int(maks / 1000)} ton · " if maks else "")
                 + f"{giling} giling berjalan"
                 + (f" · + titipan {_ribuan(stok.get('jasa_total', 0))} kg"
                    if stok.get("jasa_total") else ""),
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
        _g2_warehouse_id, hitung_stok_silo, hitung_stok_tumpukan)

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
    from app.models import Silo
    silos = (await db.execute(select(Silo).where(
        Silo.warehouse_id == await _g2_warehouse_id(db), Silo.aktif.is_(True))
        .order_by(Silo.nama_silo))).scalars().all()
    for silo in silos:
        isi.append(float(await hitung_stok_silo(db, silo.id)))
    terisi = sum(1 for v in isi if v > 0)
    tump = float(await hitung_stok_tumpukan(db))
    maks = float(settings.g2_tumpukan_maks_kg or 0)

    return [
        _sel("PK masuk", _ribuan(pk_kg), sat=" kg", ket=f"{int(pk_n or 0)} batch"),
        _sel("Penyosohan", sosoh, sat=" proses",
             ket="berjalan" if sosoh else "tak ada",
             nada="hati" if sosoh else ""),
        _sel("Silo terisi", terisi, sat=f" / {len(silos)}",
             ket=f"{_ribuan(sum(isi))} kg", nada="aman" if terisi else ""),
        _sel("Tumpukan PK", _ribuan(tump), sat=" kg",
             ket=(f"maks {int(maks / 1000)} ton" if maks else ""),
             nada="bahaya" if maks and tump > maks else ""),
    ]


def _petak_stok(a: dict, gid: str, label: str) -> dict:
    """Petak "Stok PK" satu gudang, dari angka `services.beranda`.

    Isinya disebutkan di keterangannya — "menumpuk N kg" — karena stok yang
    sebagian di lantai dan sebagian di silo adalah dua keadaan berbeda bagi
    orang yang harus memutuskan apa yang dikerjakan lebih dulu. Kosakatanya
    sama dengan baris gudang di Beranda Meja, bukan kalimat kedua untuk hal
    yang sama.
    """
    tump = a[gid]["tumpukan"]
    maks = a["tumpukan_g2_maks"] if gid == "g2" else 0
    jasa = a[gid].get("jasa_pk") or 0
    # Dua keterangan, dirangkai dengan pemisah yang sama seperti baris gudang
    # di Beranda Meja — satu kosakata untuk satu fakta, bukan kalimat kedua.
    ket = " · ".join(x for x in (
        f"menumpuk {_ribuan(tump)} kg" if tump else "",
        f"titipan {_ribuan(jasa)} kg" if jasa else "") if x)
    return _sel(label, _ribuan(a[gid]["stok_pk"]), sat=" kg", ket=ket,
                nada="bahaya" if maks and tump > maks else "")


async def petak_beranda(db, view: str, o: dict, angka: dict | None = None) -> list[dict]:
    """Dua blok yang sama bagi semua peran; nilai mengikuti izin gudang.

    Placeholder tidak menjalankan kueri gudang yang tidak boleh dibaca.
    Dengan begitu penyamaan bentuk tidak memperluas akses data operator.
    """
    def terkunci(label):
        return [_sel(nama, "—", ket="Tidak memiliki akses gudang ini")
                for nama in label]

    g1 = (_petak_g1(o) if gudang1(view) else terkunci(
        ("Gabah masuk", "Pengeringan", "Silo terisi", "Stok PK")))
    g2 = (await _petak_g2(db) if gudang2(view) else terkunci(
        ("PK masuk", "Penyosohan", "Silo terisi", "Tumpukan PK")))
    if view == TAMU:
        return []
    return [dict(judul="Gudang 1 — Selepan", sel=g1, terkunci=not gudang1(view)),
            dict(judul="Gudang 2 — Penyosohan", sel=g2, terkunci=not gudang2(view))]
