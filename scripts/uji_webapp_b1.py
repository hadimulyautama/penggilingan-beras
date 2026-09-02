"""Uji jalur masuk webapp dari ujung ke ujung — HTTP sungguhan, DB sungguhan.

Melengkapi `tests/test_akun_webapp.py` yang menguji satuan tanpa basis data.
Yang ini menjalankan aplikasi utuh: pengalihan halaman terlindung, sandi salah,
paksa ganti sandi, pembuatan akun oleh Direksi, penolakan operator, dan
perpanjangan sesi perangkat gudang.

Butuh Postgres kosong. Tidak ikut `pytest` karena butuh Docker:

    docker run -d --name hmu-uji-b1 -e POSTGRES_PASSWORD=uji -e POSTGRES_DB=uji \
        -p 55433:5432 postgres:16
    DATABASE_URL=postgresql+asyncpg://postgres:uji@127.0.0.1:55433/uji \
        .venv/bin/python -m alembic upgrade head
    PYTHONPATH=. .venv/bin/python scripts/uji_webapp_b1.py
    docker rm -f hmu-uji-b1
"""
import asyncio, os, sys
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:uji@127.0.0.1:55433/uji"
os.environ["SECRET_KEY"] = "kunci-uji-jangan-dipakai-di-produksi"
os.environ["ADMIN_TELEGRAM_ID"] = "999001"
os.environ["ADMIN_SANDI_AWAL"] = "sandiawal123"
os.environ["BOT_GUDANG1_TOKEN"] = ""
os.environ["BOT_GUDANG2_TOKEN"] = ""
os.environ["BOT_ADMIN_TOKEN"] = ""
os.environ["ANTHROPIC_API_KEY"] = "x"

import httpx
from sqlalchemy import select, text
from app.database import SessionLocal
from app.models import ProduksiAkun
from app.web.seed_akun import seed_akun_awal
from hmu_core import User

OK = []
def cek(nama, syarat, ket=""):
    OK.append(syarat)
    print(("  ✅ " if syarat else "  ❌ ") + nama + (f" — {ket}" if ket else ""))

async def main():
    from app.main import app

    # ── siapkan orang ──
    async with SessionLocal() as db:
        await db.execute(text("delete from produksi_akun"))
        await db.execute(text("delete from users where telegram_user_id in (999001,999002)"))
        db.add(User(nama="Direksi Uji", role="admin", telegram_user_id=999001, status="aktif"))
        db.add(User(nama="Operator Uji", role="operator", telegram_user_id=999002, status="aktif"))
        await db.commit()

    print("\n1. Seed akun pertama dari ADMIN_SANDI_AWAL")
    await seed_akun_awal()
    async with SessionLocal() as db:
        a = (await db.execute(select(ProduksiAkun))).scalars().all()
    cek("satu akun dibuat", len(a) == 1, f"{len(a)} akun")
    cek("wajib ganti sandi", a[0].harus_ganti_sandi)
    cek("admin → perangkat sendiri", a[0].mode_perangkat == "pribadi", a[0].mode_perangkat)

    print("\n2. Seed kedua kali tidak menggandakan")
    await seed_akun_awal()
    async with SessionLocal() as db:
        n = len((await db.execute(select(ProduksiAkun))).scalars().all())
    cek("tetap satu akun", n == 1, f"{n} akun")

    tr = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://uji", follow_redirects=False) as c:
        print("\n3. Halaman terlindung tanpa sesi")
        r = await c.get("/")
        cek("beranda mengalihkan ke /masuk", r.status_code == 303 and r.headers["location"] == "/masuk", f"{r.status_code} {r.headers.get('location')}")
        r = await c.get("/pengguna")
        cek("/pengguna mengalihkan ke masuk", r.status_code == 303 and "/masuk?next=" in r.headers.get("location", ""), r.headers.get("location"))

        print("\n4. Sandi salah")
        r = await c.post("/masuk", data={"username": "admin", "sandi": "salah", "tujuan": ""})
        cek("ditolak & tak ada cookie", r.status_code == 200 and "produksi_sesi" not in r.cookies)
        cek("pesan tak membocorkan mana yang salah", "Nama pengguna atau kata sandi salah" in r.text)

        print("\n5. Masuk benar → dipaksa ganti sandi")
        r = await c.post("/masuk", data={"username": "admin", "sandi": "sandiawal123", "tujuan": ""})
        cek("dialihkan ke /ganti-sandi", r.status_code == 303 and r.headers["location"] == "/ganti-sandi", r.headers.get("location"))
        cek("cookie sesi terpasang", "produksi_sesi" in r.cookies)
        cek("cookie httponly", "httponly" in r.headers.get("set-cookie", "").lower())

        print("\n6. Ganti sandi")
        r = await c.post("/ganti-sandi", data={"sandi_lama": "salah", "sandi_baru": "sandibaru1", "ulangi": "sandibaru1"})
        cek("sandi lama salah ditolak", "Kata sandi lama salah" in r.text)
        r = await c.post("/ganti-sandi", data={"sandi_lama": "sandiawal123", "sandi_baru": "abc", "ulangi": "abc"})
        cek("sandi terlalu pendek ditolak", "minimal 6" in r.text)
        r = await c.post("/ganti-sandi", data={"sandi_lama": "sandiawal123", "sandi_baru": "sandibaru1", "ulangi": "beda"})
        cek("ulangan tak sama ditolak", "tidak sama" in r.text)
        r = await c.post("/ganti-sandi", data={"sandi_lama": "sandiawal123", "sandi_baru": "sandibaru1", "ulangi": "sandibaru1"})
        cek("berhasil diganti", "berhasil diganti" in r.text)

        print("\n7. Beranda & kelola pengguna (admin)")
        r = await c.get("/")
        cek("beranda terbuka", r.status_code == 200 and "Selamat datang" in r.text)
        r = await c.get("/pengguna")
        cek("halaman pengguna terbuka", r.status_code == 200 and "Buatkan akun" in r.text)
        cek("operator muncul sbg calon", "Operator Uji" in r.text)

        print("\n8. Buatkan akun operator")
        async with SessionLocal() as db:
            op = (await db.execute(select(User).where(User.telegram_user_id == 999002))).scalars().first()
            op_id = op.id
        r = await c.post("/pengguna/buat", data={"user_id": op_id, "username": "rusdi"})
        cek("akun dibuat & sandi awal ditampilkan", "Sandi awal:" in r.text)
        async with SessionLocal() as db:
            ak = (await db.execute(select(ProduksiAkun).where(ProduksiAkun.username == "rusdi"))).scalars().first()
        cek("operator → perangkat gudang", ak.mode_perangkat == "bersama", ak.mode_perangkat)
        cek("wajib ganti sandi", ak.harus_ganti_sandi)
        r = await c.post("/pengguna/buat", data={"user_id": op_id, "username": "rusdi"})
        cek("username bentrok ditolak", "sudah dipakai" in r.text)

        print("\n9. Keluar")
        r = await c.post("/keluar")
        cek("dialihkan ke /masuk", r.status_code == 303 and r.headers["location"] == "/masuk")
        c.cookies.clear()
        r = await c.get("/")
        cek("sesi habis → ke halaman masuk", r.status_code == 303 and r.headers["location"] == "/masuk")

    print("\n10. Operator tak boleh kelola pengguna")
    async with SessionLocal() as db:
        ak = (await db.execute(select(ProduksiAkun).where(ProduksiAkun.username == "rusdi"))).scalars().first()
        from app.web.security import hash_sandi
        ak.password_hash = hash_sandi("operator123")
        ak.harus_ganti_sandi = False
        await db.commit()
    async with httpx.AsyncClient(transport=tr, base_url="http://uji", follow_redirects=False) as c:
        await c.post("/masuk", data={"username": "rusdi", "sandi": "operator123", "tujuan": ""})
        r = await c.get("/pengguna")
        cek("operator ditolak (403)", r.status_code == 403, str(r.status_code))
        r = await c.get("/")
        cek("beranda operator tanpa menu kelola pengguna", "Kelola pengguna" not in r.text)
        cek("beranda operator menyebut perangkat gudang", "perangkat gudang" in r.text)
        setc = r.headers.get("set-cookie", "")
        cek("sesi pendek diperpanjang tiap permintaan", "produksi_sesi" in setc, "cookie diperbarui" if setc else "TIDAK diperbarui")

    print(f"\n{sum(OK)}/{len(OK)} pemeriksaan lulus")
    sys.exit(0 if all(OK) else 1)

asyncio.run(main())
