"""Simulasi penerimaan gabah dari ujung ke ujung — HTTP sungguhan, DB sungguhan.

Bukan uji satuan: ini menjalankan **satu hari kerja** lewat layar webapp, dari
truk masuk sampai gabah duduk di silo dan harganya diverifikasi Direksi. Yang
dibuktikan bukan "fungsinya jalan", melainkan bahwa seorang operator yang hanya
memegang peramban benar-benar bisa menyelesaikan pekerjaannya tanpa Telegram.

Hanya ADA SATU jalur masuk, dan itu disengaja: seluruh gabah ditimbang dengan
aplikasi timbang, partai kecil sekalipun — satu kode timbang, berapa pun kali
ditimbang. Supplier, bobot, dan plat datang dari jembatan timbang; operator
tidak mengetik satu angka pun. Simulasi ini ikut membuktikan bahwa jalur
manual yang dulu ada memang sudah tidak bisa dilalui.

Butuh Postgres kosong:

    docker run -d --name hmu-sim -e POSTGRES_PASSWORD=uji -e POSTGRES_DB=uji \
        -p 55434:5432 postgres:16
    sleep 4
    DATABASE_URL=postgresql+asyncpg://postgres:uji@127.0.0.1:55434/uji \
        .venv/bin/python -m alembic upgrade head
    PYTHONPATH=. .venv/bin/python scripts/simulasi_gabah.py
    docker rm -f hmu-sim
"""
import asyncio
import os
import sys

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:uji@127.0.0.1:55434/uji")
os.environ["SECRET_KEY"] = "kunci-simulasi-jangan-dipakai-di-produksi"
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

SANDI = "simulasi123"
GAGAL: list[str] = []

#: Simulasi ini MENGOSONGKAN seluruh tabel sebelum berjalan, supaya bisa
#: dijalankan berulang kali. Karena itu ia menolak berjalan kecuali alamat
#: databasenya jelas-jelas milik simulasi.
#:
#: Pagar ini bukan basa-basi. Skrip yang meng-TRUNCATE segalanya dan hanya
#: dijaga oleh kehati-hatian orang yang menjalankannya adalah kecelakaan yang
#: menunggu hari sibuk.
_IZIN = ("127.0.0.1:55434", "localhost:55434")


def _pastikan_bukan_produksi() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not any(t in url for t in _IZIN):
        print("\033[31mDitolak.\033[0m Simulasi mengosongkan seluruh tabel, "
              "jadi ia hanya mau berjalan di Postgres simulasi\n"
              f"(salah satu dari: {', '.join(_IZIN)}).\n"
              f"DATABASE_URL sekarang: {url or '(kosong)'}")
        sys.exit(2)


async def _kosongkan(db) -> None:
    """Kosongkan seluruh tabel data, sisakan catatan migrasi."""
    await db.execute(text("""
        DO $$
        DECLARE t text;
        BEGIN
          FOR t IN SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public' AND tablename <> 'alembic_version'
          LOOP
            EXECUTE format('TRUNCATE TABLE %I RESTART IDENTITY CASCADE', t);
          END LOOP;
        END $$;
    """))
    await db.commit()


def cek(nama: str, syarat: bool, ket: str = "") -> bool:
    print(("  ✅ " if syarat else "  ❌ ") + nama + (f" — {ket}" if ket else ""))
    if not syarat:
        GAGAL.append(nama)
    return syarat


def babak(n: str) -> None:
    print(f"\n\033[1m{n}\033[0m")


async def main() -> None:
    from app.main import app

    babak("0. Menyiapkan pabrik, orang, dan satu truk di jembatan timbang")
    async with SessionLocal() as db:
        await _kosongkan(db)
    await seed_master()
    async with SessionLocal() as db:
        g1 = (await db.execute(
            select(Warehouse).where(Warehouse.nama_gudang.like("Gudang 1%"))
        )).scalars().first()
        direksi = User(nama="SIM Direksi", role="admin", status="aktif")
        operator = User(nama="SIM Operator G1", role="operator", status="aktif",
                        default_warehouse_id=g1.id if g1 else None)
        db.add_all([direksi, operator])
        supplier = (await db.execute(select(Supplier).limit(1))).scalars().first()
        if supplier is None:
            supplier = Supplier(nama_supplier="H. Karyo")
            db.add(supplier)
        await db.flush()

        db.add_all([
            ProduksiAkun(user_id=direksi.id, username="simdireksi",
                         password_hash=hash_sandi(SANDI), mode_perangkat="pribadi",
                         harus_ganti_sandi=False),
            ProduksiAkun(user_id=operator.id, username="simoperator",
                         password_hash=hash_sandi(SANDI), mode_perangkat="bersama",
                         harus_ganti_sandi=False),
        ])
        # Satu truk gabah basah sudah ditimbang, tiketnya masih terbuka.
        # `timbangan_transaksi` MILIK aplikasi Timbangan, tetapi hidup di
        # database yang sama dan tabelnya ikut rantai migrasi ini. Jadi tiket
        # di bawah ditulis ke tabel yang SUNGGUHAN — jalur harian yang diuji
        # adalah jalur yang sesungguhnya, bukan tiruannya.
        await db.execute(text("""
            INSERT INTO timbangan_transaksi
              (kode, tanggal, arah, jenis_kode, nomor_polisi, nama_sopir,
               supplier_id, timbang1_kg, timbang2_kg, netto_timbangan_kg,
               berat_barang_kg, berat_acuan_kg, selisih_kg, selisih_persen,
               status_kontrol, status_tiket)
            VALUES ('TRX-SIM-001', CURRENT_DATE, 'MASUK', 'GABAH_BASAH',
                    'AD 1234 XY', 'Suparno', :sid,
                    12000, 3760, 8240, 8240, 8250, -10, -0.12,
                    'NORMAL', 'TERBUKA'),
                   ('TRX-SIM-002', CURRENT_DATE, 'MASUK', 'GABAH_KERING',
                    'AD 5 BB', 'Slamet', :sid,
                    9000, 2900, 6100, 6100, 6100, 0, 0,
                    'NORMAL', 'SELESAI')
        """), {"sid": supplier.id})
        await db.commit()
        nama_supplier = supplier.nama_supplier
        supplier_id = supplier.id
    cek("pabrik & orang siap", g1 is not None, f"supplier: {nama_supplier}")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sim",
                                 follow_redirects=False) as op, \
               httpx.AsyncClient(transport=transport, base_url="http://sim",
                                 follow_redirects=False) as dir_:

        babak("1. Operator masuk lewat peramban — tanpa Telegram sama sekali")
        r = await op.post("/masuk", data={"username": "simoperator", "sandi": SANDI})
        cek("operator berhasil masuk", r.status_code == 303, f"HTTP {r.status_code}")
        r = await dir_.post("/masuk", data={"username": "simdireksi", "sandi": SANDI})
        cek("Direksi berhasil masuk", r.status_code == 303, f"HTTP {r.status_code}")

        babak("2. Layar pencatatan menawarkan pekerjaan yang benar")
        menu = (await op.get("/miniapp/actions/menu")).json()
        ids = {a["id"] for a in menu}
        cek("gabah masuk ada", "gabah_masuk" in ids)
        cek("operator TIDAK melihat aksi uang",
            not ({"verify_gabah", "beli_kemasan", "jual_pk"} & ids),
            f"{len(ids)} aksi")
        cek("tombol batal ada", "undo" in ids)

        babak("3. Jalur harian — pilih tiket timbang, jangan ketik apa pun")
        tiket = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
        cek("tiket timbang terbaca", len(tiket) == 2, f"{len(tiket)} tiket")
        for t in tiket:
            print("     ·", t["label"])
        if not tiket:
            return
        # Tiket TERBUKA didahulukan: itu pekerjaan yang sedang berjalan,
        # sedangkan yang tertutup adalah tambalan atas yang terlewat.
        cek("tiket berjalan di urutan pertama", "SUSULAN" not in tiket[0]["label"])
        cek("tiket yang sudah ditutup tetap bisa ditaut, bertanda susulan",
            any("SUSULAN" in t["label"] for t in tiket))
        r = await op.post("/miniapp/actions/gabah-masuk",
                          json={"timbangan_transaksi_id": tiket[0]["value"],
                                "tujuan": "dryer"})
        cek("gabah masuk tercatat", r.status_code == 200, r.text[:120])
        print("     " + r.json().get("pesan", "").replace("\n", "\n     "))

        habis = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
        cek("tiket yang sama tak bisa dipakai dua kali", len(habis) == 1,
            f"{len(habis)} tersisa (yang susulan)")

        babak("4. Tidak ada jalur lain — gabah tanpa tiket timbang mustahil")
        # Direksi menegaskan 2 September 2026: SELURUH gabah masuk ditimbang
        # dengan aplikasi timbang, partai kecil sekalipun (satu kode timbang,
        # berapa pun kali ditimbang). Jalur manual dicabut, dan uji ini yang
        # menjaganya tetap tercabut.
        menu2 = {a["id"] for a in (await op.get("/miniapp/actions/menu")).json()}
        cek("tak ada aksi gabah masuk manual", "gabah_masuk_manual" not in menu2)
        r = await op.post("/miniapp/actions/gabah-masuk-manual",
                          json={"supplier": "Petani Setempat", "berat": 1500,
                                "kondisi": "basah", "plat": "AD 9 ZZ",
                                "tujuan": "dryer"})
        cek("alamatnya pun sudah tidak ada", r.status_code == 404,
            f"HTTP {r.status_code}")

        babak("4b. Tumpukan — tanda pembelian berlebih, bukan tempat penyimpanan")
        # Tiket susulan yang tersisa ditaruh di tumpukan: dryer sedang terisi.
        sisa = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
        r = await op.post("/miniapp/actions/gabah-masuk",
                          json={"timbangan_transaksi_id": sisa[0]["value"],
                                "tujuan": "tumpuk"})
        cek("gabah ditumpuk", r.status_code == 200, r.text[:100])
        isi_tumpukan = (await op.get("/miniapp/actions/tumpukan")).json()
        cek("isinya terbaca", len(isi_tumpukan) == 1,
            isi_tumpukan[0]["label"] if isi_tumpukan else "kosong")

        r = await op.get("/berjalan")
        cek("tumpukan MENAGIH di layar Berjalan",
            "menumpuk" in r.text and "pindah_tumpukan" in r.text)

        # Gabah kering boleh ke silo; yang basah akan ditolak.
        r = await op.post("/miniapp/actions/pindah-tumpukan",
                          json={"kode_batch": isi_tumpukan[0]["value"],
                                "tujuan": "silo_b"})
        cek("gabah kering pindah dari tumpukan ke silo",
            r.status_code == 200, r.text[:140])
        cek("tumpukan kembali kosong",
            (await op.get("/miniapp/actions/tumpukan")).json() == [])

        babak("5. Pengeringan — satu lot dari semua yang menunggu di dryer")
        r = await op.post("/miniapp/actions/mulai-pengeringan", json={})
        cek("lot terbentuk", r.status_code == 200, r.text[:120])
        lot = (await op.get("/miniapp/actions/drying-active")).json()
        cek("lot berjalan terlihat", len(lot) == 1,
            lot[0]["label"] if lot else "kosong")
        if not lot:
            return
        kode_lot = lot[0]["value"]

        r = await op.post("/miniapp/actions/kadar-air",
                          json={"kode_lot": kode_lot, "kadar_air": 21.5})
        cek("kadar air tercatat", r.status_code == 200, r.text[:120])
        r = await op.post("/miniapp/actions/kadar-air",
                          json={"kode_lot": kode_lot, "kadar_air": 14.2})
        cek("kadar air kedua tercatat", r.status_code == 200)

        r = await op.post("/miniapp/actions/selesai-pengeringan",
                          json={"kode_lot": kode_lot})
        cek("pengeringan selesai", r.status_code == 200, r.text[:120])

        babak("6. Pendinginan lalu pindah ke silo")
        dingin = (await op.get("/miniapp/actions/cooling-active")).json()
        cek("lot masuk fase pendinginan", len(dingin) == 1)
        r = await op.post("/miniapp/actions/selesai-pendinginan",
                          json={"kode_lot": kode_lot})
        cek("pendinginan selesai", r.status_code == 200, r.text[:120])

        siap = (await op.get("/miniapp/actions/drying-done")).json()
        cek("lot siap dipindah", len(siap) == 1)
        r = await op.post("/miniapp/actions/pindah-silo",
                          json={"kode_lot": kode_lot, "silo": "A"})
        cek("gabah duduk di Silo A", r.status_code == 200, r.text[:120])
        print("     " + r.json().get("pesan", "").replace("\n", "\n     "))

        babak("7. Direksi memverifikasi harganya — operator tak boleh")
        r = await op.get("/miniapp/actions/gabah-unverified")
        cek("operator ditolak melihat daftar harga", r.status_code == 403,
            f"HTTP {r.status_code}")
        belum = (await dir_.get("/miniapp/actions/gabah-unverified")).json()
        cek("Direksi melihat batch menunggu harga", len(belum) >= 1,
            f"{len(belum)} batch")
        if belum:
            r = await dir_.post("/miniapp/actions/verify-gabah",
                                json={"kode_batch": belum[0]["value"],
                                      "metode": "per_kg", "nilai": 5600})
            cek("harga terverifikasi", r.status_code == 200, r.text[:150])

        babak("8. Laporan — dan batas yang memisahkan siapa melihat apa")
        r = await op.get("/api/laporan/status_gudang")
        cek("operator boleh baca status gudang", r.status_code == 200)
        if r.status_code == 200:
            isi = r.json()["isi"]
            cek("laporan menyebut Silo A", "Silo A" in isi or "silo" in isi.lower())
        r = await op.get("/api/laporan/hpp_trend")
        cek("operator DITOLAK baca laporan uang", r.status_code == 403,
            f"HTTP {r.status_code}")
        r = await dir_.get("/api/laporan/pembelian_gabah?periode=hari_ini")
        cek("Direksi boleh baca pembelian gabah", r.status_code == 200)
        if r.status_code == 200:
            # 8.250 (nota) — BUKAN 8.240 (netto
            # timbang). Aturannya: bobot efektif = nota bila ada, selain itu
            # netto real (`timbang_link._SQL_SINKRON`). Yang dibayar pabrik
            # adalah angka nota, dan simulasi ini menegaskannya justru karena
            # dugaan pertama saya keliru.
            cek("pembelian memakai bobot NOTA, bukan netto timbang",
                "8.250" in r.json()["isi"],
                r.json()["isi"].split("\n")[1].strip() if "\n" in r.json()["isi"] else "")

        babak("9. Tombol batal — apa yang akan hilang harus terbaca dulu")
        pilih = (await op.get("/miniapp/actions/undo-terakhir")).json()
        cek("operator hanya melihat lingkup dirinya", len(pilih) <= 1,
            pilih[0]["label"] if pilih else "kosong")
        luas = (await dir_.get("/miniapp/actions/undo-terakhir")).json()
        cek("Direksi melihat beberapa lingkup", len(luas) >= 1,
            f"{len(luas)} lingkup")
        for p in luas:
            print("     · " + p["label"])
        r = await op.post("/miniapp/actions/undo", json={"lingkup": "semua"})
        cek("operator ditolak membatalkan kerja orang lain",
            r.status_code == 403, f"HTTP {r.status_code}")

        babak("10. Bilah navigasi & layar Berjalan")
        # Babak ini menyiapkan keadaannya sendiri: babak-babak sebelumnya
        # sudah menutup semua pekerjaan, dan layar yang kosong tak bisa
        # membuktikan apa pun tentang baris yang menagih.
        async with SessionLocal() as db:
            await db.execute(text("""
                INSERT INTO timbangan_transaksi
                  (kode, tanggal, arah, jenis_kode, nomor_polisi, supplier_id,
                   timbang1_kg, netto_timbangan_kg, berat_acuan_kg, status_tiket)
                VALUES ('TRX-SIM-003', CURRENT_DATE, 'MASUK', 'GABAH_KERING',
                        'AD 7 CC', :sid, 5000, 2000, 2000, 'TERBUKA')
            """), {"sid": supplier_id})
            await db.commit()

        r = await op.get("/berjalan")
        cek("layar Berjalan terbuka", r.status_code == 200, f"HTTP {r.status_code}")
        cek("bilah tampil di layar bertab", 'class="bilah"' in r.text)
        cek("tab Berjalan menyala", "bilah__tab--aktif" in r.text)
        # Tiket susulan yang tersisa belum ditaut → satu hal menunggu operator.
        cek("yang menunggu terdaftar", "Menunggu Anda" in r.text)
        cek("barisnya menaut ke aksi yang menutupnya",
            "/aksi?buka=gabah_masuk" in r.text)

        r = await op.get("/masuk")
        cek("bilah TIDAK muncul di halaman masuk", 'class="bilah"' not in r.text)

        # Direksi berperan admin, dan `_is_wh_operator` memberi admin akses
        # ke kedua gudang — jadi ia melihat pekerjaan fisik G1 juga.
        r = await dir_.get("/berjalan")
        cek("Direksi melihat tiket yang masih menggantung",
            "TRX-SIM-003" in r.text, f"HTTP {r.status_code}")
        # Dan yang SUDAH dikerjakan berhenti memanggil: batch yang harganya
        # diverifikasi di babak 7 tidak lagi muncul sebagai menunggu.
        # Batch dari babak 4b belum diverifikasi harganya, jadi ia MEMANG
        # masih memanggil. Yang diuji: batch babak 3 yang sudah diverifikasi
        # tidak ikut muncul lagi.
        cek("yang sudah diverifikasi berhenti memanggil",
            "GB-" in r.text and r.text.count("harga belum diverifikasi") <= 1,
            f"{r.text.count('harga belum diverifikasi')} batch menunggu harga")

    print()
    if GAGAL:
        print(f"\033[31m{len(GAGAL)} pemeriksaan GAGAL:\033[0m")
        for g in GAGAL:
            print("  · " + g)
        sys.exit(1)
    print("\033[32mSeluruh alur penerimaan gabah berjalan lewat layar, "
          "tanpa Telegram.\033[0m")


if __name__ == "__main__":
    _pastikan_bukan_produksi()
    asyncio.run(main())
