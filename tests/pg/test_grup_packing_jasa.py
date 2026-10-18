"""Packing pabrik dan jasa satu submenu; identitas titipan tetap jelas.

Keputusan pemilik 18 Oktober 2026 menggantikan pemisahan submenu 6 Oktober.
"""
from __future__ import annotations
from tests.pg.formulir import cap_formulir

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def dua_lot(pg, pemakai):
    """Satu lot pabrik (1.000 kg medium), satu lot titipan Bu Sri (500 kg
    medium) — keduanya BELUM dikemas sama sekali."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Jasa, Pelanggan, User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.flush()
        jasa = Jasa(kode="JAS-2610-001", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.flush()

        p_pabrik = PolishingProcess(kode_proses="POL-UJIG-01", status="selesai",
                                    waktu_mulai=now_local(), waktu_selesai=now_local(),
                                    created_by=u.id)
        p_jasa = PolishingProcess(kode_proses="POL-UJIG-02", status="selesai",
                                  waktu_mulai=now_local(), waktu_selesai=now_local(),
                                  created_by=u.id, jasa_id=jasa.id)
        db.add_all([p_pabrik, p_jasa])
        await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p_pabrik.id, jenis="medium",
                                  berat_kg=1_000, waktu_update=now_local(), input_by=u.id))
        db.add(PolishingOutputLog(polishing_process_id=p_jasa.id, jenis="medium",
                                  berat_kg=500, waktu_update=now_local(), input_by=u.id))
        await db.commit()
        return {"user": pemakai.id, "kode_pabrik": p_pabrik.kode_proses,
                "kode_jasa": p_jasa.kode_proses, "pemilik": "JAS-2610-001 Bu Sri"}


async def test_kartu_pabrik_dan_titipan_satu_grup_identitas_tetap_ada(pg, dua_lot):
    from app.services import berjalan as svc

    async with pg() as db:
        kartu = await svc._kartu_beras_curah(db)
    assert len(kartu) == 2
    pabrik = next(b for b in kartu if b.kode == dua_lot["kode_pabrik"])
    jasa = next(b for b in kartu if b.kode == dua_lot["kode_jasa"])

    assert pabrik.jasa_id is None
    assert svc.grup_baris(pabrik) == "packing"
    assert "TITIPAN" not in pabrik.sub

    assert jasa.jasa_id is not None
    assert svc.grup_baris(jasa) == "packing"
    assert f"TITIPAN {dua_lot['pemilik']}" in jasa.sub


async def test_packing_jasa_tak_lagi_submenu_terpisah(pg, dua_lot):
    from app.services import berjalan as svc

    kunci = [k for k, _ in svc.GRUP_ANTREAN]
    assert "packing_jasa" not in kunci
    # Tiga grup pertama yang pemilik sebut tak boleh bergeser — keputusan
    # pemilik 2 Oktober 2026, dijaga juga oleh test_grup_antrean.py.
    assert kunci[:3] == ["bahan", "pindah", "packing"]
    assert kunci[-1] == "lain", "komplemen wajib tetap baris terakhir"


@pytest.fixture
async def empat_jenis(pg, pemakai):
    """Satu penyosohan SELESAI, empat jenis hasil sekaligus: medium (beras),
    bekatul, broken, menir — supaya tombol "Sisa dicurah" (laporan lapangan
    7 Oktober 2026) bisa diuji ADA dan TAK ADA pada jenis berbeda dari SATU
    proses yang sama."""
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        p = PolishingProcess(kode_proses="POL-UJIS-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=u.id)
        db.add(p)
        await db.flush()
        for jenis, kg in (("medium", 1_000), ("bekatul", 300),
                          ("broken", 200), ("menir", 100), ("reject", 50)):
            db.add(PolishingOutputLog(polishing_process_id=p.id, jenis=jenis,
                                      berat_kg=kg, waktu_update=now_local(),
                                      input_by=u.id))
        await db.commit()
        return {"kode": p.kode_proses}


async def test_hasil_samping_otomatis_tidak_masuk_antrean_packing(pg, empat_jenis):
    """Hasil samping punya aturan packing otomatis; operator hanya diminta
    packing beras. Keempat jenis samping tak boleh tampil di antrean atau
    picker `beras-belum-dikemas`."""
    from app.services import berjalan as svc
    from app.services.stok import beras_curah

    async with pg() as db:
        kartu = await svc._kartu_beras_curah(db)
        pilihan = await beras_curah(db, termasuk_berjalan=False)
    assert [(b.nilai, b.aksi) for b in kartu] == [
        (f"{empat_jenis['kode']}|medium", "catat_packing")]
    assert [(b.jenis, b.sisa_kg) for b in pilihan] == [("medium", 1_000)]


async def _klien(pg, *, peran: str = "admin") -> "httpx.AsyncClient":
    import httpx

    from app.main import app
    from app.models import ProduksiAkun, User
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = User(nama=f"Uji {peran}", role=peran, status="aktif")
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=f"gpj{u.id}",
                         password_hash=S.hash_sandi("rahasia123"),
                         status="aktif", mode_perangkat=mode_bawaan(peran))
        db.add(a)
        await db.commit()
        tok = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji", follow_redirects=True)
    t = csrf.terbitkan_baru()
    c.cookies.set(security.NAMA_COOKIE, tok)
    c.cookies.set(csrf.NAMA_COOKIE, t)
    c.headers[csrf.NAMA_HEADER] = cap_formulir(c)
    return c


async def test_filter_packing_dan_tautan_lama_memuat_kedua_pemilik(pg, dua_lot):
    """Keduanya tampil bersama, termasuk bila membuka bookmark submenu lama."""
    c = await _klien(pg, peran="admin")
    try:
        r_jasa = await c.get("/aksi?grup=packing_jasa")
        r_pabrik = await c.get("/aksi?grup=packing")
    finally:
        await c.aclose()

    assert r_jasa.status_code == 200 and r_pabrik.status_code == 200
    assert dua_lot["kode_jasa"] in r_jasa.text
    assert dua_lot["kode_pabrik"] in r_jasa.text
    assert "Bu Sri" in r_jasa.text

    assert dua_lot["kode_pabrik"] in r_pabrik.text
    assert dua_lot["kode_jasa"] in r_pabrik.text
    assert 'href="/aksi?grup=packing_jasa"' not in r_pabrik.text


async def test_tombol_kartu_membawa_saringan_grup_yang_aktif(pg, dua_lot):
    """⭐ Laporan lapangan 7 Oktober 2026: memilih sub-menu Antrian tunggu
    lalu menekan kartu yang membuka borang membuat halaman kembali
    menampilkan SEMUA kartu sesudah borang ditutup/disimpan — bukan tetap
    di sub-menu yang dipilih.

    Akarnya `_benda.html`: tautan pembuka borang menulis `{{ alamat }}
    ?buka=...` dari nol, membuang `?grup=` yang sedang aktif di alamat
    peramban. `PINDAH.segarkan()` lalu menyegarkan alamat SAAT ITU — yang
    sudah telanjur polos tanpa `grup=`. Dibuktikan di sini bahwa tautan
    kartu di halaman TERSARING sudah membawa `grup=` ketika dibuka.
    """
    c = await _klien(pg, peran="admin")
    try:
        r = await c.get("/aksi?grup=packing")
    finally:
        await c.aclose()
    assert r.status_code == 200
    # Kartu `catat_packing` pabrik ini lewat cabang `{% elif b.aksi %}` —
    # tautannya wajib menyebut KEDUANYA: grup yang sedang aktif, dan aksi
    # yang akan dibuka. `&amp;` sebab href di-escape HTML seperti biasa.
    assert "href=\"/aksi?grup=packing&amp;buka=catat_packing" in r.text, \
        "tautan kartu kehilangan saringan ?grup= yang sedang aktif"
