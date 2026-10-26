"""Akun operator baru tersimpan pribadi dan login memperoleh cookie 30 hari."""
from http.cookies import SimpleCookie

from sqlalchemy import select, text

from app.models import ProduksiAkun
from app.web import security
from tests.pg.test_kelola_akun_http import _klien, _orang_biasa, _super, _token


async def test_buat_operator_dan_login_memakai_sesi_30_hari(pg, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "sesi_hari", 30)
    pelaku = await _super(pg)
    uid = await _orang_biasa(pg)
    async with _klien(await _token(pg, pelaku)) as c:
        r = await c.post("/pengguna/buat", data={
            "user_id": uid, "username": "operator_baru", "_csrf": c._csrf})
        assert r.status_code == 200
        async with pg() as db:
            a = await db.scalar(select(ProduksiAkun).where(ProduksiAkun.user_id == uid))
            assert a.mode_perangkat == "pribadi" and not a.sesi_pendek
            # Sandi pengujian saja, supaya uji tidak bergantung tata letak
            # blok sandi awal sekali-tampil pada respons /pengguna/buat.
            a.password_hash = security.hash_sandi("OperatorUji2026")
            a.harus_ganti_sandi = False
            await db.commit()
        r = await c.post("/masuk", data={
            "username": "operator_baru", "sandi": "OperatorUji2026", "_csrf": c._csrf})
        assert r.status_code == 303
        cookies = SimpleCookie()
        for header in r.headers.get_list("set-cookie"):
            cookies.load(header)
        assert int(cookies[security.NAMA_COOKIE]["max-age"]) == 30 * 24 * 3600


async def test_default_database_pribadi_dan_akun_bersama_tetap_bersama(pg):
    uid = await _orang_biasa(pg)
    async with pg() as db:
        # Melewati default ORM untuk menguji DEFAULT hasil migrasi.
        await db.execute(text("""
            INSERT INTO produksi_akun (user_id, username, password_hash)
            VALUES (:uid, 'operator_default_sql', 'sandi-uji-tidak-dipakai')
        """), {"uid": uid})
        await db.commit()
        a = await db.scalar(select(ProduksiAkun).where(ProduksiAkun.user_id == uid))
        assert a.mode_perangkat == "pribadi"
        a.mode_perangkat = "bersama"
        await db.commit()
        await db.refresh(a)
        assert a.sesi_pendek
