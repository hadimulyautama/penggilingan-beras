"""Membuktikan mode uji menghapus data produksi TANPA menyentuh tiket timbang.

Basis datanya dipakai bersama aplikasi Timbangan, dan tiket adalah miliknya.
Klaim "tak akan terhapus" tidak cukup diucapkan — di sini ia dijalankan:
pabrik diisi sampai penuh catatan, dihapus lewat HTTP seperti Super Admin
sungguhan, lalu tiketnya dihitung ulang.

    docker run -d --rm --name hmu-uji -e POSTGRES_PASSWORD=uji -e POSTGRES_DB=uji \
        -p 55435:5432 postgres:16 && sleep 6
    DATABASE_URL=postgresql+asyncpg://postgres:uji@127.0.0.1:55435/uji \
        .venv/bin/python -m alembic upgrade head
    MODE_UJI=1 PYTHONPATH=. .venv/bin/python scripts/uji_mode_uji.py
"""
import asyncio
import os

os.environ.setdefault("MODE_UJI", "1")

import httpx
from sqlalchemy import select, text

import scripts.skenario_gabah as S
from app.database import Base, SessionLocal
from app.main import app
from app.models import ProduksiAkun, PurchaseBatch
from app.web.mode_uji import DIPERTAHANKAN, KALIMAT, _tabel_dihapus
from hmu_core import User
from app.web.security import hash_sandi

H, M, T, N = "\033[32m", "\033[31m", "\033[1m", "\033[0m"
GAGAL = []


def cek(nama, syarat, ket=""):
    print(("  " + (H + "✅" if syarat else M + "❌") + N + " " + nama)
          + (f" — {ket}" if ket else ""))
    if not syarat:
        GAGAL.append(nama)


async def hitung(sql: str) -> int:
    async with SessionLocal() as db:
        return int((await db.execute(text(sql))).scalar_one())


async def main() -> None:
    S._pastikan_bukan_produksi()
    sid = await S.siapkan()
    # Satu vendor "dari Kledo" dan satu pelanggan biasa, supaya penyaringannya
    # bisa dibedakan dari penghapusan borongan.
    async with SessionLocal() as db:
        await db.execute(text(
            "INSERT INTO suppliers (nama_supplier, status, kledo_contact_id) "
            "VALUES ('Vendor Kledo', 'aktif', 12345)"))
        await db.execute(text(
            "INSERT INTO pelanggan (nama_pelanggan, status) VALUES ('Pembeli Uji', 'aktif')"))
        await db.commit()

    async with SessionLocal() as db:
        u = User(nama="Uji Super", role="superadmin", status="aktif")
        db.add(u); await db.flush()
        db.add(ProduksiAkun(user_id=u.id, username="ujisuper",
                            password_hash=hash_sandi(S.SANDI),
                            mode_perangkat="pribadi", harus_ganti_sandi=False))
        await db.commit()

    tr = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://uji") as op:
        await S.masuk(op, "sknoperator")
        # Pabrik diisi: gabah masuk, dikeringkan, dipindah, digiling.
        await S.tiket(sid, "TRX-U1", "GABAH_BASAH", netto=9000, nota=9000)
        await S.tiket(sid, "TRX-U2", "GABAH_BASAH", netto=8000, nota=8000)
        for _ in range(2):
            t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
            await op.post("/miniapp/actions/gabah-masuk",
                          json={"timbangan_transaksi_id": t[0]["value"], "tujuan": S.DRYER})
        await op.post("/miniapp/actions/mulai-pengeringan", json={})
        pgr = (await op.get("/miniapp/actions/drying-active")).json()[0]["value"]
        for aksi in ("selesai-pengeringan", "selesai-pendinginan"):
            await op.post(f"/miniapp/actions/{aksi}", json={"kode_lot": pgr})
        await op.post("/miniapp/actions/pindah-silo", json={"kode_lot": pgr, "silo": "A"})
        await op.post("/miniapp/actions/mulai-giling", json={"silo": "A"})

    tiket_sebelum = await hitung("SELECT count(*) FROM timbangan_transaksi")
    jenis_sebelum = await hitung("SELECT count(*) FROM timbangan_jenis")
    async with SessionLocal() as db:
        batch_sebelum = len((await db.execute(select(PurchaseBatch))).scalars().all())
    print(f"\n{T}Sebelum hapus{N}: {batch_sebelum} batch gabah · "
          f"{tiket_sebelum} tiket timbang · {jenis_sebelum} jenis komoditas")

    # ── Penghapusan, lewat HTTP, sebagai Super Admin ──
    async with httpx.AsyncClient(transport=tr, base_url="http://uji",
                                 follow_redirects=False) as su:
        await S.masuk(su, "ujisuper")
        r_salah = await su.post("/pengaturan/mode-uji", data={"kalimat": "hapus"})
        cek("kalimat salah ditolak", r_salah.status_code == 200
            and "Ketik persis" in r_salah.text)
        r = await su.post("/pengaturan/mode-uji", data={"kalimat": KALIMAT})
        cek("penghapusan dijalankan", r.status_code == 303, f"HTTP {r.status_code}")

    # ── Yang HARUS utuh ──
    print(f"\n{T}Tiket timbang — milik aplikasi Timbangan{N}")
    tiket_sesudah = await hitung("SELECT count(*) FROM timbangan_transaksi")
    cek("tiket timbang UTUH", tiket_sesudah == tiket_sebelum,
        f"{tiket_sebelum} → {tiket_sesudah}")
    tertaut = await hitung(
        "SELECT count(*) FROM timbangan_transaksi WHERE purchase_batch_id IS NOT NULL")
    cek("tautan ke batch uji dilepas", tertaut == 0, f"{tertaut} masih tertaut")
    sup = await hitung("SELECT count(*) FROM suppliers")
    plg = await hitung("SELECT count(*) FROM pelanggan")
    cek("SEMUA vendor bertahan", sup == 2, f"{sup} baris")
    cek("SEMUA pelanggan bertahan", plg == 1, f"{plg} baris")
    # Inti syarat pemilik: tak satu tiket pun boleh kehilangan nama pengirim.
    yatim = await hitung(
        "SELECT count(*) FROM timbangan_transaksi t LEFT JOIN suppliers s "
        "ON s.id = t.supplier_id WHERE t.supplier_id IS NOT NULL AND s.id IS NULL")
    kosong = await hitung(
        "SELECT count(*) FROM timbangan_transaksi WHERE supplier_id IS NULL")
    cek("tak ada tiket kehilangan nama pengirim", yatim == 0 and kosong == 0,
        f"{yatim} menunjuk vendor hilang · {kosong} tanpa vendor")
    cek("jenis komoditas UTUH", await hitung("SELECT count(*) FROM timbangan_jenis")
        == jenis_sebelum)
    cek("produksi tak mengenal tabel timbangan",
        not [t for t in Base.metadata.tables if t.startswith("timbangan")])

    print(f"\n{T}Yang dipertahankan{N}")
    for nama in ("users", "produksi_akun", "warehouses", "silos", "dryers"):
        n = await hitung(f'SELECT count(*) FROM "{nama}"')
        cek(f"{nama} bertahan", n > 0, f"{n} baris")

    print(f"\n{T}Yang dihapus{N}")
    sisa = []
    for nama in _tabel_dihapus():
        n = await hitung(f'SELECT count(*) FROM "{nama}"')
        if n:
            sisa.append(f"{nama}={n}")
    # `suppliers` dkk. tak disemai ulang; daftar acuan memang dipulihkan seed.
    acuan = {"brands", "package_sizes", "rice_quality_standards",
             "packaging_materials"}
    nyata = [s for s in sisa if s.split("=")[0] not in acuan]
    cek("catatan pekerjaan bersih", not nyata, ", ".join(nyata) or "tak ada sisa")

    print(f"\n{T}Masih bisa dipakai sesudahnya{N}")
    async with httpx.AsyncClient(transport=tr, base_url="http://uji") as op2:
        await S.masuk(op2, "sknoperator")
        t = (await op2.get("/miniapp/actions/timbang-masuk-aktif")).json()
        cek("tiket lama kembali bisa dicatat", len(t) == tiket_sebelum,
            f"{len(t)} tiket ditawarkan lagi")

    print()
    if GAGAL:
        print(M + f"{len(GAGAL)} gagal: " + ", ".join(GAGAL) + N)
        raise SystemExit(1)
    print(H + "Mode uji menghapus data produksi tanpa menyentuh tiket timbang." + N)


if __name__ == "__main__":
    asyncio.run(main())
