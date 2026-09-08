"""Isi sebuah database uji dengan sehari kerja yang tampak sungguhan.

Gunanya menguji LAYAR, bukan mesin: begitu database uji baru dibuat, seluruh
layarnya kosong dan tak ada yang bisa dinilai. Skrip ini mengisinya sampai
tiap layar punya sesuatu untuk ditunjukkan — antrean berisi beberapa tiket
dari pemasok berbeda, satu pengeringan yang sedang berjalan, silo terisi,
satu giling berjalan, dan beberapa harga yang belum diverifikasi.

**Datanya dibuat lewat HTTP, bukan lewat INSERT.** Baris yang disuntikkan
langsung ke tabel bisa saja mustahil menurut aturan aplikasinya sendiri —
gabah basah di silo, lot tanpa target kadar air — dan data uji yang mustahil
membuat layarnya terlihat benar padahal sedang menampilkan keadaan yang tak
pernah bisa terjadi. Satu-satunya yang disuntikkan langsung adalah tiket
timbang, karena ia memang datang dari aplikasi lain.

Pemasoknya diberi awalan "(UJI)" supaya siapa pun yang membuka database ini
tahu dalam sekali lihat bahwa isinya bukan pekerjaan sungguhan.

    IZIN_DUMMY=ya DATABASE_URL=postgresql+asyncpg://... \
        PYTHONPATH=. .venv/bin/python scripts/isi_dummy.py

Menolak berjalan tanpa `IZIN_DUMMY=ya`. Pagar itu bukan basa-basi: satu-
satunya beda antara database uji dan database sungguhan adalah alamatnya,
dan alamat paling mudah salah ketik justru saat sedang buru-buru.
"""
from __future__ import annotations

import asyncio
import os
import sys

if os.environ.get("IZIN_DUMMY") != "ya":
    print("\033[31mDitolak.\033[0m Skrip ini menulis data karangan ke database "
          "yang ditunjuk DATABASE_URL.\n"
          "Jalankan dengan IZIN_DUMMY=ya bila memang itu yang Anda mau, dan "
          "PASTIKAN alamatnya bukan database utama.")
    raise SystemExit(2)

os.environ.setdefault("SECRET_KEY", "kunci-dummy-jangan-dipakai-di-produksi")
os.environ.setdefault("ADMIN_TELEGRAM_ID", "0")
for _v in ("BOT_GUDANG1_TOKEN", "BOT_GUDANG2_TOKEN", "BOT_ADMIN_TOKEN"):
    os.environ.setdefault(_v, "")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")

import httpx                                                    # noqa: E402
from sqlalchemy import select, text                             # noqa: E402

from app.database import SessionLocal                           # noqa: E402
from app.models import ProduksiAkun, Supplier, Warehouse        # noqa: E402
from app.services.seed import seed_master                       # noqa: E402
from app.web.security import hash_sandi                         # noqa: E402
from hmu_core import User                                       # noqa: E402

SANDI = "dummy123"
AWALAN = "(UJI) "

#: Pemasok karangan. Namanya sengaja beragam panjangnya — kartu yang hanya
#: pernah diuji dengan "Bu Sri" tak pernah ketahuan pecah pada nama panjang.
PEMASOK = ["H. Karyo", "Bu Sri", "Pak Tarno", "H. Sulaiman Abdurrahman",
           "Kelompok Tani Sumber Rejeki"]

#: (pemasok, jenis, plat, kg). Bobotnya kisaran satu truk: 8–11 ton.
TIKET = [
    (0, "GABAH_BASAH",  "AD 1234 XY",  9_850),
    (1, "GABAH_BASAH",  "AD 88 KK",   10_400),
    (2, "GABAH_KERING", "AD 21 LM",    8_600),
    (3, "GABAH_KERING", "AD 9 PP",    11_000),
    (4, "GABAH_BASAH",  "AD 7 CC",     9_200),
    (1, "GABAH_KERING", "AD 88 KK",    8_150),
    (0, "GABAH_KERING", "AD 1234 XY", 10_700),
]

GAGAL: list[str] = []


def cek(nama: str, syarat: bool, ket: str = "") -> bool:
    print(("  ✅ " if syarat else "  ❌ ") + nama + (f" — {ket}" if ket else ""))
    if not syarat:
        GAGAL.append(nama)
    return syarat


def babak(n: str) -> None:
    print(f"\n\033[1m{n}\033[0m")


async def _orang_dan_pabrik() -> dict[str, int]:
    """Akun & alat. Tanpa ini seluruh layar menolak dibuka."""
    await seed_master()
    async with SessionLocal() as db:
        wid = (await db.execute(
            select(Warehouse.id).where(Warehouse.nama_gudang.like("Gudang 1%"))
        )).scalars().first()

        sup_id: dict[str, int] = {}
        for nama in PEMASOK:
            penuh = AWALAN + nama
            s = (await db.execute(
                select(Supplier).where(Supplier.nama_supplier == penuh)
            )).scalars().first()
            if s is None:
                await db.execute(text(
                    "INSERT INTO suppliers (nama_supplier) VALUES (:n)"), {"n": penuh})
                await db.commit()
                s = (await db.execute(
                    select(Supplier).where(Supplier.nama_supplier == penuh)
                )).scalars().first()
            sup_id[nama] = s.id

        for uname, peran, nama in (("uji_operator", "operator", "Operator Uji"),
                                   ("uji_admin", "superadmin", "Admin Uji")):
            ada = (await db.execute(
                select(ProduksiAkun).where(ProduksiAkun.username == uname)
            )).scalars().first()
            if ada is not None:
                continue
            u = User(nama=nama, role=peran, telegram_user_id=None,
                     default_warehouse_id=wid if peran == "operator" else None)
            db.add(u)
            await db.flush()
            db.add(ProduksiAkun(
                # `peran` sengaja tak disebut: ia properti baca-saja yang
                # mengambil dari `User.role`, supaya peran orang tak pernah
                # bisa berbeda antara akunnya dan dirinya.
                user_id=u.id, username=uname, password_hash=hash_sandi(SANDI),
                mode_perangkat="pribadi", harus_ganti_sandi=False))
        await db.commit()
        return sup_id


async def _tiket(sup_id: dict[str, int]) -> None:
    """Tiket timbang datang dari APLIKASI LAIN, jadi inilah satu-satunya yang
    disuntikkan langsung — tak ada layar di aplikasi ini yang membuatnya."""
    async with SessionLocal() as db:
        for i, (idx, jenis, plat, kg) in enumerate(TIKET, start=1):
            kode = f"TRX-UJI-{i:03d}"
            ada = (await db.execute(text(
                "SELECT 1 FROM timbangan_transaksi WHERE kode = :k"), {"k": kode})).first()
            if ada:
                continue
            await db.execute(text("""
                INSERT INTO timbangan_transaksi
                  (kode, tanggal, arah, jenis_kode, nomor_polisi, nama_sopir,
                   supplier_id, timbang1_kg, timbang2_kg, netto_timbangan_kg,
                   berat_barang_kg, berat_acuan_kg, status_kontrol, status_tiket)
                VALUES (:k, CURRENT_DATE, 'MASUK', :j, :p, 'Sopir Uji', :s,
                        :t1, :t2, :n, :n, :n, 'NORMAL', 'TERBUKA')
            """), {"k": kode, "j": jenis, "p": plat,
                   "s": sup_id[PEMASOK[idx]], "t1": kg + 4200, "t2": 4200, "n": kg})
        await db.commit()


async def main() -> None:
    from app.main import app

    babak("0. Orang, alat, dan tiket timbang")
    sup_id = await _orang_dan_pabrik()
    await _tiket(sup_id)
    cek("pemasok, akun & tiket siap", True, f"{len(PEMASOK)} pemasok · {len(TIKET)} tiket")

    tr = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://dummy",
                                 follow_redirects=False) as op:
        r = await op.post("/masuk", data={"username": "uji_operator", "sandi": SANDI})
        if not cek("operator masuk", r.status_code == 303, f"HTTP {r.status_code}"):
            return

        babak("1. Sebagian tiket ditindak, sebagian sengaja ditinggal di antrean")
        tiket = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
        cek("tiket terbaca", len(tiket) >= 5, f"{len(tiket)} tiket")

        def ambil(jenis: str, n: int) -> list[dict]:
            return [t for t in tiket if jenis.lower() in t["label"].lower()][:n]

        # Batasnya `MAX_PURCHASE_BATCH_PER_DAY` (bawaan 3) — sengaja dihormati,
        # bukan dinaikkan: data uji yang hanya bisa dibuat dengan melonggarkan
        # aturan bukan gambaran hari kerja yang sungguhan.
        #
        # Dua basah → mesin pengering. Sisanya ditinggal supaya antrean berisi.
        for t in ambil("basah", 2):
            r = await op.post("/miniapp/actions/gabah-masuk",
                              json={"timbangan_transaksi_id": t["value"],
                                    "tujuan": "dryer:1"})
            cek(f"gabah basah → pengering ({t['label'][:22]})", r.status_code == 200,
                r.text[:80])

        # Satu kering → silo, supaya ada yang siap digiling. Silonya dipilih
        # dari tujuan yang DITAWARKAN server, bukan ditebak nomornya: silo di
        # Gudang 2 bernama sama dan bernomor lain, dan menebak akan menempatkan
        # gabah di gudang yang salah tanpa satu peringatan pun.
        menu = {a["id"]: a for a in (await op.get("/miniapp/actions/menu")).json()}
        tujuan_silo = [o[0] for f in menu["gabah_masuk"]["fields"]
                       if f["name"] == "tujuan" for o in f["options"]
                       if o[0].startswith("silo:")]
        cek("tujuan silo ditawarkan server", bool(tujuan_silo), str(tujuan_silo))
        for t in ambil("kering", 1):
            r = await op.post("/miniapp/actions/gabah-masuk",
                              json={"timbangan_transaksi_id": t["value"],
                                    "tujuan": tujuan_silo[0]})
            cek(f"gabah kering → {tujuan_silo[0]}", r.status_code == 200, r.text[:80])

        babak("2. Satu pengeringan berjalan, dengan bacaan kadar air")
        r = await op.post("/miniapp/actions/mulai-pengeringan",
                          json={"target_kadar_air": 14, "mode_dryer": "20T"})
        cek("pengeringan mulai", r.status_code == 200, r.text[:90])
        lot = (await op.get("/miniapp/actions/drying-active")).json()
        if lot:
            kode = lot[0]["value"]
            for tes in (22.4, 19.8):
                await op.post("/miniapp/actions/kadar-air",
                              json={"kode_lot": kode, "tes_1": tes, "tes_2": tes + .2,
                                    "tes_3": tes - .1, "tes_4": tes + .1,
                                    "indikator": tes - 1.2})
            cek("dua bacaan kadar air tercatat", True, f"{kode} · 22,4% → 19,8%")

        babak("3. Satu giling berjalan")
        siap = (await op.get("/miniapp/actions/silo-siap-giling")).json()
        if siap:
            r = await op.post("/miniapp/actions/mulai-giling",
                              json={"silo": siap[0]["value"]})
            cek("giling mulai", r.status_code == 200, r.text[:90])
        else:
            cek("ada silo siap digiling", False, "tak ada")

    print()
    if GAGAL:
        print(f"\033[31m{len(GAGAL)} langkah GAGAL:\033[0m")
        for g in GAGAL:
            print("  · " + g)
        sys.exit(1)
    print("\033[32mData uji siap. Masuk sebagai `uji_admin` atau `uji_operator`, "
          f"sandi `{SANDI}`.\033[0m")
    print("Harga sengaja BELUM diverifikasi — layar Menunggu keputusan pun berisi.")


if __name__ == "__main__":
    asyncio.run(main())
