"""Sub-menu "Packing jasa" — beras titipan dipisah dari beras pabrik
(6 Oktober 2026).

Keluhan pemilik: "di halaman tunggu packing tidak bisa dibedakan mana jasa
mana yang tidak." Kartu beras belum dikemas (`_kartu_beras_curah`) memakai
`aksi="catat_packing"` yang SAMA untuk pabrik maupun titipan — sheet yang
dibukanya memang sama — jadi `grup_baris()` butuh sumbu baru (`Baris.
jasa_id`) untuk memisahkannya, bukan sekadar menambah entri `_GRUP_AKSI`.
"""
from __future__ import annotations

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


async def test_kartu_titipan_jatuh_ke_grup_packing_jasa(pg, dua_lot):
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
    assert svc.grup_baris(jasa) == "packing_jasa"
    assert f"TITIPAN {dua_lot['pemilik']}" in jasa.sub


async def test_grup_packing_jasa_terdaftar_dan_tak_mengganggu_urutan(pg, dua_lot):
    from app.services import berjalan as svc

    kunci = [k for k, _ in svc.GRUP_ANTREAN]
    assert "packing_jasa" in kunci
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
                          ("broken", 200), ("menir", 100)):
            db.add(PolishingOutputLog(polishing_process_id=p.id, jenis=jenis,
                                      berat_kg=kg, waktu_update=now_local(),
                                      input_by=u.id))
        await db.commit()
        return {"kode": p.kode_proses}


async def test_sisa_dicurah_hanya_untuk_bekatul_dan_broken(pg, empat_jenis):
    """Tombol "Sisa dicurah" cuma muncul untuk bekatul & broken — satu-
    satunya jenis yang punya jalan curah sendiri (`catat_bekatul`/
    `catat_broken` → `byproduct_stock`). Menir & beras tak punya jalan itu;
    menawarkan tombol yang pasti ditolak borang lebih buruk daripada tak
    menawarkannya sama sekali (lihat komentar `_kartu_beras_curah`)."""
    from app.services import berjalan as svc

    async with pg() as db:
        kartu = await svc._kartu_beras_curah(db)
    per_jenis = {b.nilai.split("|", 1)[1]: b for b in kartu}
    assert set(per_jenis) == {"medium", "bekatul", "broken", "menir"}

    for jenis in ("medium", "menir"):
        b = per_jenis[jenis]
        assert [p[0] for p in b.pilihan] == ["catat_packing"], \
            f"{jenis} tak punya jalan curah, tombolnya harus absen: {b.pilihan}"

    for jenis, aksi_curah in (("bekatul", "catat_bekatul"), ("broken", "catat_broken")):
        b = per_jenis[jenis]
        assert [p[0] for p in b.pilihan] == ["catat_packing", aksi_curah], \
            f"{jenis} harus menawarkan '{aksi_curah}': {b.pilihan}"
        sisa = b.pilihan[1]
        assert sisa[1] == "Sisa dicurah"
        assert sisa[3] == empat_jenis["kode"], \
            "nilai tombol curah wajib kode_proses TELANJANG, bukan kode|jenis"


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
    c.headers[csrf.NAMA_HEADER] = t
    return c


async def test_filter_grup_via_http_memisah_pabrik_dan_titipan(pg, dua_lot):
    """`/aksi?grup=packing_jasa` menunjukkan HANYA titipan; `?grup=packing`
    menunjukkan HANYA pabrik — dibuktikan lewat HTTP sungguhan, sebab
    penjaga yang cuma memanggil fungsinya bisa lulus pada hari templatnya
    berhenti menggambar (pelajaran `TempatPk.pemilik`)."""
    c = await _klien(pg, peran="admin")
    try:
        r_jasa = await c.get("/aksi?grup=packing_jasa")
        r_pabrik = await c.get("/aksi?grup=packing")
    finally:
        await c.aclose()

    assert r_jasa.status_code == 200 and r_pabrik.status_code == 200
    assert dua_lot["kode_jasa"] in r_jasa.text
    assert dua_lot["kode_pabrik"] not in r_jasa.text
    assert "Bu Sri" in r_jasa.text

    assert dua_lot["kode_pabrik"] in r_pabrik.text
    assert dua_lot["kode_jasa"] not in r_pabrik.text


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
