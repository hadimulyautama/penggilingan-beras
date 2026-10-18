"""Tiket timbang sampai ke antrean POS PRODUKSI — per peran, lewat HTTP.

Inti temuan QA 24 September 2026. Keluhan pemilik: "ada PK masuk dan sudah
ditimbang, kenapa tidak ada di antrian tunggu?" — dan seluruh tangkapan layarnya
Pos Produksi. Perbaikan pertama (7c26a0f) memasang jaringnya di
`web/meja_api.py`, modul yang HANYA dipanggil app Meja, jadi ia tidak menyentuh
keluhan itu sama sekali. Yang menyaring di Pos Produksi adalah
`berjalan._tiket_belum_ditaut`: ia memancarkan HANYA `model == "gabah"`.

Ukuran QA pada 67381eb, lewat HTTP, mencari kode tiketnya di tiap permukaan:
tak ada SATU layar pun di Pos Produksi yang menyebut tiket PK itu, untuk peran
mana pun.

Yang diuji di sini karena itu bukan "fungsinya benar" melainkan "halamannya
menyebutnya" — untuk admin ke atas DAN untuk operator Gudang 2, masing-masing
dengan bentuk yang benar.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES
        (:kode, :tanggal, 'MASUK', :jenis, 'DUA_KALI', :pihak,
         :nopol, 12000, :waktu, :netto, 0, 'SELESAI', 'AKTIF')
    RETURNING id
""")


async def _tiket(db, kode, jenis, *, pihak="UD Sumber Tani"):
    from app.database import now_local

    return (await db.execute(_SQL_TIKET, {
        "kode": kode, "tanggal": now_local().date(), "jenis": jenis,
        "pihak": pihak, "nopol": "B 9911 XY",
        "waktu": datetime.now(timezone.utc), "netto": 9800,
    })).scalar_one()


@pytest_asyncio.fixture
async def pabrik(pg):
    """Dua gudang + dua silo G2 — antrean kedua gudang menolak basis data tanpa
    master gudang, dan tiketnya tak akan pernah sampai ke layar."""
    from app.models import Silo, Warehouse

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
        db.add_all([g1, g2])
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=g2.id),
                    Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        await db.commit()
        return {"g1": g1.id, "g2": g2.id}


async def _klien(pg, *, role: str, gudang_id: int | None = None) -> httpx.AsyncClient:
    from app.main import app
    from app.models import ProduksiAkun, User
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = User(nama=f"Uji {role}", role=role, status="aktif",
                 default_warehouse_id=gudang_id)
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=f"uji{u.id}",
                         password_hash=S.hash_sandi("rahasia123"), status="aktif",
                         mode_perangkat=mode_bawaan(role))
        db.add(a)
        await db.commit()
        token = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji")
    c.cookies.set(security.NAMA_COOKIE, token)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    return c


def _jumlah_kartu(html, kode):
    # Kode dapat muncul pada sel, label, dan atribut pencarian satu kartu.
    # Hitung wadah yang dapat dicari, bukan kemunculan kata di markup.
    from html.parser import HTMLParser
    class Kartu(HTMLParser):
        jumlah = 0
        def handle_starttag(self, tag, attrs):
            if kode.lower() in dict(attrs).get("data-cari", "").split():
                self.jumlah += 1
    kartu = Kartu()
    kartu.feed(html)
    return kartu.jumlah


async def test_tiket_pk_tampil_di_antrian_tunggu_admin(pg, pabrik):
    """Yang GAGAL di 67381eb: halaman ini tak menyebut tiket PK sama sekali."""
    async with pg() as db:
        await _tiket(db, "TRX-PK-ADM-01", "BERAS_PK")
        await db.commit()

    c = await _klien(pg, role="superadmin")
    async with c:
        r = await c.get("/aksi")
    assert r.status_code == 200, r.text[:300]
    assert "TRX-PK-ADM-01" in r.text, "tiket PK tak sampai ke Antrian tunggu Pos Produksi"
    # Bloknya sendiri, bukan tenggelam di "Bisa dikerjakan sekarang".
    assert "Tiket Timbang" in r.text
    # Bertindakan untuk admin: aksinya sudah ada dan gerbangnya menerimanya.
    assert "buka=catat_pk_luar" in r.text
    # TIDAK dua kali — itu risiko terbesar pemindahan ini.
    assert _jumlah_kartu(r.text, "TRX-PK-ADM-01") == 1, "tiket terangkut dua kali"


async def test_tiket_pk_tampil_diam_untuk_operator_gudang2(pg, pabrik):
    """Barangnya berdiri di halamannya, jadi ia tak boleh jadi orang terakhir
    yang tahu — tetapi penempatan PK datang bukan tugasnya (pemilik, 12 Sep
    2026), jadi kartunya DIAM."""
    async with pg() as db:
        await _tiket(db, "TRX-PK-OPS-01", "BERAS_PK")
        await db.commit()

    c = await _klien(pg, role="operator", gudang_id=pabrik["g2"])
    async with c:
        r = await c.get("/aksi")
    assert r.status_code == 200, r.text[:300]
    assert "TRX-PK-OPS-01" in r.text, "operator G2 tak melihat PK di halamannya"
    assert _jumlah_kartu(r.text, "TRX-PK-OPS-01") == 1
    # Diam: tak ada tautan yang membuka borangnya.
    assert "buka=catat_pk_luar" not in r.text
    # Dan sebabnya tertulis, di tempat orang mencarinya.
    assert "dicatat Admin" in r.text


async def test_operator_selepan_tak_kebagian_tiket_pk(pg, pabrik):
    """PK mendarat di Gudang 2. Operator selepan yang melihatnya membaca kabar
    dari gudang sebelah — dan kabar yang tak bisa ditindaklanjuti membuat orang
    berhenti membaca antreannya."""
    async with pg() as db:
        await _tiket(db, "TRX-PK-SLP-01", "BERAS_PK")
        await db.commit()

    c = await _klien(pg, role="operator", gudang_id=pabrik["g1"])
    async with c:
        r = await c.get("/aksi")
    assert r.status_code == 200
    assert "TRX-PK-SLP-01" not in r.text


async def test_tiket_gabah_tetap_hanya_di_jalur_gabah(pg, pabrik):
    """Satu tiket satu kartu. GABAH_KERING tak boleh ikut jalur PK, dan
    BERAS_PK tak boleh ikut jalur gabah — kalau bercampur, antreannya
    menyebut dua truk untuk satu truk."""
    from app.services import berjalan as svc

    async with pg() as db:
        await _tiket(db, "TRX-GB-01", "GABAH_KERING")
        await _tiket(db, "TRX-PK-02", "BERAS_PK")
        await db.commit()

    async with pg() as db:
        gabah = [b.kode for b in await svc._tiket_belum_ditaut(db)]
        pk = [b.kode for b in await svc._tiket_pk_luar(db, boleh_catat=True)]
    assert gabah == ["TRX-GB-01"]
    assert pk == ["TRX-PK-02"]

    # Dan di layar: satu kartu masing-masing, bukan dua.
    c = await _klien(pg, role="superadmin")
    async with c:
        t = (await c.get("/aksi")).text
    assert _jumlah_kartu(t, "TRX-GB-01") == 1 and _jumlah_kartu(t, "TRX-PK-02") == 1


async def test_jenis_tak_dikenal_kartu_diam_untuk_admin(pg, pabrik):
    """Admin ke atas saja: pemetaan jenis bukan wewenang operator, dan kartu
    yang tak bisa ia kerjakan maupun teruskan hanya menambah angka lencananya."""
    async with pg() as db:
        await _tiket(db, "TRX-TDK-01", "JENIS_UJI_ASING")
        await db.commit()

    c = await _klien(pg, role="superadmin")
    async with c:
        t = (await c.get("/aksi")).text
    assert "TRX-TDK-01" in t and _jumlah_kartu(t, "TRX-TDK-01") == 1
    assert "belum dikenal produksi" in t

    op = await _klien(pg, role="operator", gudang_id=pabrik["g2"])
    async with op:
        assert "TRX-TDK-01" not in (await op.get("/aksi")).text


async def test_tiket_yang_sudah_dicatat_keluar_dari_antrean(pg, pabrik):
    """Syarat `_SQL_AKTIF` tak boleh hilang dalam pemindahan: tiket yang sudah
    tertaut batch berhenti ditawarkan. Jaring yang tak pernah habis berhenti
    dipercaya."""
    from app.services import berjalan as svc

    async with pg() as db:
        tid = await _tiket(db, "TRX-PK-TUTUP-01", "BERAS_PK")
        await db.commit()

    async with pg() as db:
        assert [b.kode for b in await svc._tiket_pk_luar(db, boleh_catat=True)] \
            == ["TRX-PK-TUTUP-01"]

    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi = 'DIBATALKAN' "
                              "WHERE id = :i"), {"i": tid})
        await db.commit()

    async with pg() as db:
        assert await svc._tiket_pk_luar(db, boleh_catat=True) == []
