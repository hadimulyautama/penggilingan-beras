"""Skenario penerimaan gabah — situasi nyata, dijalankan sungguhan.

Bukan daftar di dokumen: tiap skenario menjalankan aplikasi utuh di atas basis
data yang bersih, lewat HTTP, dan memeriksa hasilnya. Yang dibuktikan bukan
"fungsinya jalan" melainkan bahwa aturan pabrik berlaku di keadaan yang
sesungguhnya terjadi di pos timbang — termasuk keadaan yang tidak rapi.

    docker run -d --name hmu-skenario -e POSTGRES_PASSWORD=uji -e POSTGRES_DB=uji \
        -p 55435:5432 postgres:16
    sleep 4
    DATABASE_URL=postgresql+asyncpg://postgres:uji@127.0.0.1:55435/uji \
        .venv/bin/python -m alembic upgrade head
    PYTHONPATH=. .venv/bin/python scripts/skenario_gabah.py
    docker rm -f hmu-skenario
"""
import asyncio
import os
import sys

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:uji@127.0.0.1:55435/uji")
os.environ["SECRET_KEY"] = "kunci-skenario-jangan-dipakai-di-produksi"
os.environ["ADMIN_TELEGRAM_ID"] = "0"
for v in ("BOT_GUDANG1_TOKEN", "BOT_GUDANG2_TOKEN", "BOT_ADMIN_TOKEN"):
    os.environ[v] = ""
os.environ["ANTHROPIC_API_KEY"] = "x"

import httpx
from sqlalchemy import select, text

from app.database import SessionLocal
from app.models import ProduksiAkun, Supplier, Warehouse
from app.services.seed import seed_master
from app.web.security import hash_sandi
from hmu_core import User

SANDI = "skenario123"
#: Tujuan dryer kini menyebut mesinnya: "dryer:<id>". Di pabrik uji hanya ada
#: satu mesin, dan id-nya selalu 1 karena tabel dikosongkan tiap skenario.
DRYER = "dryer:1"
#: Silo pun menyebut nomornya; di pabrik uji Silo A id 1, Silo B id 2.
SILO_A, SILO_B = "silo:1", "silo:2"
_IZIN = ("127.0.0.1:55435", "localhost:55435")
GAGAL: list[str] = []
SKENARIO: list = []


def skenario(judul: str):
    def bungkus(f):
        SKENARIO.append((judul, f))
        return f
    return bungkus


def cek(nama: str, syarat: bool, ket: str = "") -> bool:
    print(("    ✅ " if syarat else "    ❌ ") + nama + (f" — {ket}" if ket else ""))
    if not syarat:
        GAGAL.append(nama)
    return syarat


def _pastikan_bukan_produksi() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not any(t in url for t in _IZIN):
        print("\033[31mDitolak.\033[0m Skenario mengosongkan seluruh tabel, jadi ia "
              f"hanya mau berjalan di Postgres skenario ({', '.join(_IZIN)}).")
        sys.exit(2)


async def _kosongkan(db) -> None:
    await db.execute(text("""
        DO $$
        DECLARE t text;
        BEGIN
          FOR t IN SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public' AND tablename <> 'alembic_version'
          LOOP EXECUTE format('TRUNCATE TABLE %I RESTART IDENTITY CASCADE', t);
          END LOOP;
        END $$;
    """))
    await db.commit()


async def siapkan() -> int:
    """Pabrik kosong, dua orang, satu supplier. Kembalikan id supplier."""
    async with SessionLocal() as db:
        await _kosongkan(db)
    await seed_master()
    async with SessionLocal() as db:
        g1 = (await db.execute(
            select(Warehouse).where(Warehouse.nama_gudang.like("Gudang 1%"))
        )).scalars().first()
        direksi = User(nama="SKN Direksi", role="admin", status="aktif")
        operator = User(nama="SKN Operator", role="operator", status="aktif",
                        default_warehouse_id=g1.id)
        supplier = Supplier(nama_supplier="H. Karyo")
        db.add_all([direksi, operator, supplier])
        await db.flush()
        db.add_all([
            ProduksiAkun(user_id=direksi.id, username="skndireksi",
                         password_hash=hash_sandi(SANDI), mode_perangkat="pribadi",
                         harus_ganti_sandi=False),
            ProduksiAkun(user_id=operator.id, username="sknoperator",
                         password_hash=hash_sandi(SANDI), mode_perangkat="bersama",
                         harus_ganti_sandi=False),
        ])
        await db.commit()
        return supplier.id


async def tiket(sid: int, kode: str, jenis: str, *, netto: float,
                nota: float | None = None, status: str = "TERBUKA") -> int:
    """Satu tiket timbang MASUK. Kembalikan id-nya."""
    async with SessionLocal() as db:
        r = await db.execute(text("""
            INSERT INTO timbangan_transaksi
              (kode, tanggal, arah, jenis_kode, nomor_polisi, nama_sopir,
               supplier_id, timbang1_kg, timbang2_kg, netto_timbangan_kg,
               berat_barang_kg, berat_acuan_kg, selisih_kg, selisih_persen,
               status_kontrol, status_tiket)
            VALUES (:kode, CURRENT_DATE, 'MASUK', :jenis, 'AD 1 XX', 'Sopir',
                    :sid, :bruto, :tara, :netto, :netto, :nota, 0, 0,
                    'NORMAL', :status)
            RETURNING id
        """), {"kode": kode, "jenis": jenis, "sid": sid, "bruto": netto + 3000,
               "tara": 3000, "netto": netto, "nota": nota or 0, "status": status})
        tid = r.scalar_one()
        await db.commit()
        return tid


async def masuk(klien, username: str) -> None:
    r = await klien.post("/masuk", data={"username": username, "sandi": SANDI})
    assert r.status_code == 303, r.text[:200]


# ═══════════════════════════ Skenario ═══════════════════════════

@skenario("Gabah basah, dryer kosong — jalur lurus sampai silo")
async def s1(op, dir_, sid):
    await tiket(sid, "TRX-A1", "GABAH_BASAH", netto=8000, nota=8050)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": DRYER})
    cek("basah diterima ke dryer", r.status_code == 200, r.text[:90])

    await op.post("/miniapp/actions/mulai-pengeringan", json={})
    lot = (await op.get("/miniapp/actions/drying-active")).json()[0]["value"]
    await op.post("/miniapp/actions/kadar-air", json={"kode_lot": lot, "kadar_air": 14})
    await op.post("/miniapp/actions/selesai-pengeringan", json={"kode_lot": lot})
    await op.post("/miniapp/actions/selesai-pendinginan", json={"kode_lot": lot})
    r = await op.post("/miniapp/actions/pindah-silo",
                      json={"kode_lot": lot, "silo": "A"})
    cek("berakhir di Silo A", r.status_code == 200 and "Silo A" in r.text, r.text[:90])
    cek("bobot yang dipakai = NOTA", "8.050" in r.text or "8050" in r.text, r.text[:90])


@skenario("Gabah basah datang saat dryer terisi — ditumpuk, lalu menyusul")
async def s2(op, dir_, sid):
    await tiket(sid, "TRX-B1", "GABAH_BASAH", netto=9000, nota=9000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    await op.post("/miniapp/actions/gabah-masuk",
                  json={"timbangan_transaksi_id": t[0]["value"], "tujuan": DRYER})
    await op.post("/miniapp/actions/mulai-pengeringan", json={})

    # Truk kedua datang. Dryer sedang berputar.
    await tiket(sid, "TRX-B2", "GABAH_BASAH", netto=7000, nota=7000)
    t2 = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t2[0]["value"], "tujuan": DRYER})
    cek("dryer menolak muatan kedua", "Belum ditempatkan" in r.text, r.text[:120])

    cek("tapi gabahnya TETAP tercatat, tak hilang", r.status_code == 200)

    # Batch yang gagal ditempatkan berstatus 'baru' — belum di mana-mana.
    # Kalau ia tidak menagih, gabahnya berdiri di halaman tanpa ada yang tahu.
    r = await op.get("/berjalan")
    cek("gabah yang belum ditempatkan MENAGIH di Berjalan",
        "belum ditempatkan" in r.text.lower(), "cari baris batch 'baru'")


@skenario("Gabah basah sengaja ditumpuk, lalu dipindah ke dryer")
async def s3(op, dir_, sid):
    await tiket(sid, "TRX-C1", "GABAH_BASAH", netto=6000, nota=6000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": "tumpuk"})
    cek("basah boleh ditumpuk", r.status_code == 200 and "ditumpuk" in r.text, r.text[:90])

    r = await op.get("/berjalan")
    cek("tumpukan menagih di Berjalan", "menumpuk" in r.text)
    cek("dan berbunyi harus ke dryer", "harus ke dryer" in r.text)

    isi = (await op.get("/miniapp/actions/tumpukan")).json()
    r = await op.post("/miniapp/actions/pindah-tumpukan",
                      json={"kode_batch": isi[0]["value"], "tujuan": SILO_A})
    cek("basah DITOLAK ke silo", r.status_code == 400 and "belum boleh ke silo" in r.text,
        r.text[:110])

    r = await op.post("/miniapp/actions/pindah-tumpukan",
                      json={"kode_batch": isi[0]["value"], "tujuan": DRYER})
    cek("basah diterima ke dryer", r.status_code == 200, r.text[:90])
    cek("tumpukan kembali kosong",
        (await op.get("/miniapp/actions/tumpukan")).json() == [])


@skenario("Gabah kering langsung ke silo — tanpa dryer sama sekali")
async def s4(op, dir_, sid):
    await tiket(sid, "TRX-D1", "GABAH_KERING", netto=5000, nota=5000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": SILO_B})
    cek("kering langsung ke Silo B", r.status_code == 200 and "Silo B" in r.text,
        r.text[:90])
    kosong = (await op.get("/miniapp/actions/drying-active")).json()
    cek("dryer tak tersentuh", kosong == [])


@skenario("Silo campuran — lot pengeringan + gabah kering, digiling seutuhnya")
async def s5(op, dir_, sid):
    # Lot pengeringan → Silo A.
    await tiket(sid, "TRX-E1", "GABAH_BASAH", netto=10000, nota=10000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    await op.post("/miniapp/actions/gabah-masuk",
                  json={"timbangan_transaksi_id": t[0]["value"], "tujuan": DRYER})
    await op.post("/miniapp/actions/mulai-pengeringan", json={})
    lot = (await op.get("/miniapp/actions/drying-active")).json()[0]["value"]
    await op.post("/miniapp/actions/selesai-pengeringan", json={"kode_lot": lot})
    await op.post("/miniapp/actions/selesai-pendinginan", json={"kode_lot": lot})
    r = await op.post("/miniapp/actions/pindah-silo", json={"kode_lot": lot, "silo": "A"})
    cek("lot masuk Silo A", r.status_code == 200, r.text[:90])

    # Gabah kering menyusul ke silo yang SAMA — dulu ini ditolak.
    await tiket(sid, "TRX-E2", "GABAH_KERING", netto=4000, nota=4000)
    t2 = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t2[0]["value"], "tujuan": SILO_A})
    cek("silo yang sudah berisi MENERIMA tambahan",
        r.status_code == 200 and "Belum ditempatkan" not in r.text, r.text[:110])

    silo = (await op.get("/miniapp/actions/silo-siap-giling")).json()
    r = await op.post("/miniapp/actions/mulai-giling",
                      json={"silo": silo[0]["value"]})
    cek("giling mengambil SELURUH isi silo (14 ton)",
        "14.000" in r.text or "14000" in r.text, r.text[:130])


@skenario("Tiket sudah ditutup — dicatat susulan, bukan hilang")
async def s6(op, dir_, sid):
    await tiket(sid, "TRX-F1", "GABAH_KERING", netto=3000, nota=3000, status="SELESAI")
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    cek("tiket tertutup tetap ditawarkan", len(t) == 1, f"{len(t)} tiket")
    cek("dan ditandai susulan", "SUSULAN" in t[0]["label"], t[0]["label"][:80])
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": SILO_A})
    cek("bisa ditaut susulan", r.status_code == 200, r.text[:90])


@skenario("Kapasitas dryer: 30 ton di kertas, toleransi 3 ton — dua sisinya diuji")
async def s7(op, dir_, sid):
    # 32 ton: di atas angka kertas, masih dalam toleransi. Truk yang sudah
    # berdiri di halaman tidak ditolak karena selisih dua ton.
    await tiket(sid, "TRX-G1", "GABAH_BASAH", netto=32000, nota=32000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": DRYER})
    cek("32 ton diterima — di atas kertas, dalam toleransi",
        "Belum ditempatkan" not in r.text, r.text[:110])


@skenario("Melebihi toleransi dryer — ditolak mesin, bukan diterima diam-diam")
async def s8(op, dir_, sid):
    # 34 ton: melewati 30 + 3. Ditolak.
    await tiket(sid, "TRX-H1", "GABAH_BASAH", netto=34000, nota=34000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": DRYER})
    cek("34 ton ditolak dryer", "Kapasitas dryer" in r.text, r.text[:140])
    cek("gabahnya tetap tercatat, tidak hilang", r.status_code == 200,
        f"HTTP {r.status_code}")

    r = await op.get("/berjalan")
    cek("dan menagih sebagai belum ditempatkan",
        "belum ditempatkan" in r.text.lower())

    # Jalan keluarnya ada: tumpuk dulu, giling menyusul saat dryer longgar.
    menunggu = (await op.get("/miniapp/actions/tumpukan")).json()
    r = await op.post("/miniapp/actions/pindah-tumpukan",
                      json={"kode_batch": menunggu[0]["value"], "tujuan": "tumpuk"})
    cek("bisa ditumpuk sementara", r.status_code == 200, r.text[:100])

    r2 = await op.post("/miniapp/actions/gabah-masuk",
                       json={"timbangan_transaksi_id": t[0]["value"], "tujuan": DRYER})
    cek("tiket yang sama tak bisa dicatat dua kali", r2.status_code == 400,
        f"HTTP {r2.status_code}")


@skenario("Peringatan: pengeringan satu batch, dan silo yang dicampur")
async def s9(op, dir_, sid):
    # Satu batch saja — boleh, tetapi diperingatkan.
    await tiket(sid, "TRX-I1", "GABAH_BASAH", netto=6000, nota=6000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    await op.post("/miniapp/actions/gabah-masuk",
                  json={"timbangan_transaksi_id": t[0]["value"], "tujuan": DRYER})
    r = await op.post("/miniapp/actions/mulai-pengeringan", json={})
    cek("pengeringan 1 batch TETAP jalan", r.status_code == 200)
    cek("tapi diperingatkan", "Hanya 1 batch" in r.text, r.text[-110:])

    # Isi Silo A lebih dulu dengan gabah kering, lalu pindahkan lot ke sana.
    await tiket(sid, "TRX-I2", "GABAH_KERING", netto=2000, nota=2000)
    t2 = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    await op.post("/miniapp/actions/gabah-masuk",
                  json={"timbangan_transaksi_id": t2[0]["value"], "tujuan": SILO_A})

    lot = (await op.get("/miniapp/actions/drying-active")).json()[0]["value"]
    await op.post("/miniapp/actions/selesai-pengeringan", json={"kode_lot": lot})
    await op.post("/miniapp/actions/selesai-pendinginan", json={"kode_lot": lot})
    r = await op.post("/miniapp/actions/pindah-silo",
                      json={"kode_lot": lot, "silo": "A"})
    cek("pindah ke silo berisi TETAP jalan", r.status_code == 200, r.text[:90])
    cek("tapi diperingatkan tercampur", "tercampur" in r.text, r.text[-130:])

    silo = (await op.get("/miniapp/actions/silo-siap-giling")).json()
    r = await op.post("/miniapp/actions/mulai-giling", json={"silo": silo[0]["value"]})
    cek("campurannya jadi SATU proses giling (8 ton)",
        "8.000" in r.text or "8000" in r.text, r.text[:120])


@skenario("Direksi menambah dryer & silo — dan gabah bisa diarahkan ke sana")
async def s10(op, dir_, sid):
    r = await op.get("/pengaturan/alat")
    cek("operator TIDAK boleh membuka pengaturan alat",
        r.status_code in (303, 403), f"HTTP {r.status_code}")

    r = await dir_.post("/pengaturan/alat/dryer",
                        data={"nama": "Pengering 2", "kapasitas_kg": 20000})
    cek("Direksi menambah mesin kedua", r.status_code == 303)
    r = await dir_.post("/pengaturan/alat/silo", data={"nama": "C"})
    cek("dan silo ketiga", r.status_code == 303)

    # Mesin & silo baru langsung tersedia sebagai tujuan — tanpa deploy ulang.
    menu = (await op.get("/miniapp/actions/menu")).json()
    aksi = [a for a in menu if a["id"] == "gabah_masuk"][0]
    tujuan = [o[1] for o in
              [f for f in aksi["fields"] if f["name"] == "tujuan"][0]["options"]]
    cek("mesin baru muncul sebagai tujuan", "Pengering 2" in tujuan, str(tujuan))
    cek("silo baru muncul sebagai tujuan",
        any("Silo C" in t for t in tujuan), str(tujuan))

    # Dua mesin: yang satu sibuk tidak menutup yang lain.
    await tiket(sid, "TRX-J1", "GABAH_BASAH", netto=8000, nota=8000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": DRYER})
    cek("gabah masuk mesin 1", "Belum ditempatkan" not in r.text, r.text[:100])
    await op.post("/miniapp/actions/mulai-pengeringan", json={"dryer_id": 1})

    await tiket(sid, "TRX-J2", "GABAH_BASAH", netto=5000, nota=5000)
    t2 = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    r = await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t2[0]["value"],
                            "tujuan": "dryer:2"})
    cek("mesin 1 sibuk TIDAK menutup mesin 2",
        "Belum ditempatkan" not in r.text, r.text[:120])

    pilih = (await op.get("/miniapp/actions/dryer-menunggu")).json()
    cek("hanya mesin yang ada gabahnya ditawarkan", len(pilih) == 1,
        pilih[0]["label"] if pilih else "kosong")


async def main() -> None:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    for i, (judul, f) in enumerate(SKENARIO, start=1):
        print(f"\n\033[1m{i}. {judul}\033[0m")
        sid = await siapkan()
        async with httpx.AsyncClient(transport=transport, base_url="http://skn",
                                     follow_redirects=False) as op, \
                   httpx.AsyncClient(transport=transport, base_url="http://skn",
                                     follow_redirects=False) as dir_:
            await masuk(op, "sknoperator")
            await masuk(dir_, "skndireksi")
            await f(op, dir_, sid)

    print()
    if GAGAL:
        print(f"\033[31m{len(GAGAL)} pemeriksaan GAGAL:\033[0m")
        for g in GAGAL:
            print("  · " + g)
        sys.exit(1)
    print(f"\033[32m{len(SKENARIO)} skenario penerimaan gabah berjalan sesuai "
          "aturan pabrik.\033[0m")


if __name__ == "__main__":
    _pastikan_bukan_produksi()
    asyncio.run(main())
