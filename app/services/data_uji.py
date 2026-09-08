"""Isi ulang data uji — dipakai skrip DAN tombol di layar Mode Uji.

Menghapus saja tidak cukup. Sesudah "Hapus data uji", tiap layar kosong dan
tak ada satu pun yang bisa dicoba; data dummy-nya harus diisi lagi, dan
sampai sekarang itu hanya bisa dilakukan dari laptop. Jadi yang berguna
bukan tombol hapus melainkan tombol KEMBALI KE AWAL.

**Datanya dibuat lewat endpoint aplikasi ini sendiri**, bukan lewat INSERT
dan bukan pula dengan memanggil layanan satu per satu. Baris yang disuntikkan
langsung bisa saja mustahil menurut aturan aplikasinya sendiri — gabah basah
di silo, lot tanpa target kadar air — dan data uji yang mustahil membuat
layarnya terlihat benar padahal menampilkan keadaan yang tak pernah bisa
terjadi. Memanggil layanannya satu per satu lebih baik, tetapi menuntut
menyalin ulang cara endpoint menerjemahkan tujuan jadi tindakan — dan salinan
itu akan berselisih dengan aslinya cepat atau lambat.

Jadi ia memanggil aplikasinya sendiri lewat ASGI, di dalam proses yang sama:
tak ada jaringan, tak ada aturan yang disalin, dan apa pun yang ditolak
aplikasi untuk operator sungguhan ditolak juga di sini.

Satu-satunya yang disuntikkan langsung adalah TIKET TIMBANG, karena ia memang
datang dari aplikasi lain dan tak ada layar di sini yang membuatnya.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models import ProduksiAkun, Supplier

#: Awalan pada tiap pemasok karangan. Siapa pun yang membuka basis data ini
#: harus tahu dalam sekali lihat bahwa isinya bukan pekerjaan sungguhan.
AWALAN = "(UJI) "

PEMASOK = ["H. Karyo", "Bu Sri", "Pak Tarno", "H. Sulaiman Abdurrahman",
           "Kelompok Tani Sumber Rejeki"]

#: (indeks pemasok, jenis, plat, kg). Bobotnya kisaran satu truk: 8–11 ton,
#: dan panjang namanya sengaja beragam — kartu yang hanya pernah diuji dengan
#: "Bu Sri" tak pernah ketahuan pecah pada nama panjang.
TIKET = [
    (0, "GABAH_BASAH",  "AD 1234 XY",  9_850),
    (1, "GABAH_BASAH",  "AD 88 KK",   10_400),
    (2, "GABAH_KERING", "AD 21 LM",    8_600),
    (3, "GABAH_KERING", "AD 9 PP",    11_000),
    (4, "GABAH_BASAH",  "AD 7 CC",     9_200),
    (1, "GABAH_KERING", "AD 88 KK",    8_150),
    (0, "GABAH_KERING", "AD 1234 XY", 10_700),
]


async def _pemasok(db: AsyncSession) -> dict[str, int]:
    keluar: dict[str, int] = {}
    for nama in PEMASOK:
        penuh = AWALAN + nama
        s = (await db.execute(
            select(Supplier).where(Supplier.nama_supplier == penuh))).scalars().first()
        if s is None:
            await db.execute(
                text("INSERT INTO suppliers (nama_supplier) VALUES (:n)"), {"n": penuh})
            await db.flush()
            s = (await db.execute(
                select(Supplier).where(Supplier.nama_supplier == penuh))).scalars().first()
        keluar[nama] = s.id
    return keluar


async def _tiket(db: AsyncSession, pemasok: dict[str, int]) -> int:
    """Tiket timbang, disuntikkan langsung — ia milik aplikasi Timbangan.

    Yang sudah ada dilewati, jadi menekan tombolnya dua kali tak melipatgandakan
    tiketnya. Yang sudah tertaut ke batch dibebaskan lagi oleh penghapusan.
    """
    dibuat = 0
    for i, (idx, jenis, plat, kg) in enumerate(TIKET, start=1):
        kode = f"TRX-UJI-{i:03d}"
        ada = (await db.execute(
            text("SELECT 1 FROM timbangan_transaksi WHERE kode = :k"), {"k": kode})).first()
        if ada:
            continue
        await db.execute(text("""
            INSERT INTO timbangan_transaksi
              (kode, tanggal, arah, jenis_kode, nomor_polisi, nama_sopir,
               supplier_id, timbang1_kg, timbang2_kg, netto_timbangan_kg,
               berat_barang_kg, berat_acuan_kg, status_kontrol, status_tiket)
            VALUES (:k, CURRENT_DATE, 'MASUK', :j, :p, 'Sopir Uji', :s,
                    :t1, :t2, :n, :n, :n, 'NORMAL', 'TERBUKA')
        """), {"k": kode, "j": jenis, "p": plat, "s": pemasok[PEMASOK[idx]],
               "t1": kg + 4200, "t2": 4200, "n": kg})
        dibuat += 1
    return dibuat


async def siapkan_akun(sandi: str) -> ProduksiAkun:
    """Akun uji — dibuat kalau belum ada, dikembalikan kalau sudah.

    Ada DI SINI, bukan di skripnya, karena `scripts/` tak ikut masuk ke dalam
    image: yang menyiapkan basis data uji di Railway hanya bisa memanggil apa
    yang ada di dalam `app/`. Satu tempat pula berarti akun yang dipakai
    menguji dari laptop sama dengan yang dipakai menguji dari HP.

    Sandinya diserahkan pemanggil — tak ada sandi yang tertulis di kode ini,
    dan tak ada yang pernah ditulis ke log.
    """
    from app.models import Warehouse
    from app.models.akun import mode_bawaan
    from app.services.seed import seed_master
    from app.web.security import hash_sandi
    from hmu_core import User

    await seed_master()
    async with SessionLocal() as db:
        wid = (await db.execute(select(Warehouse.id).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        for uname, peran, nama in (("uji_operator", "operator", "Operator Uji"),
                                   ("uji_admin", "superadmin", "Admin Uji")):
            ada = (await db.execute(select(ProduksiAkun).where(
                ProduksiAkun.username == uname))).scalars().first()
            if ada is not None:
                continue
            u = User(nama=nama, role=peran, telegram_user_id=None,
                     default_warehouse_id=wid if peran == "operator" else None)
            db.add(u)
            await db.flush()
            db.add(ProduksiAkun(
                user_id=u.id, username=uname, password_hash=hash_sandi(sandi),
                mode_perangkat=mode_bawaan(peran),
                # Sandi yang diketik seseorang di baris perintah tak boleh
                # menetap: masuk pertama kali WAJIB menggantinya.
                harus_ganti_sandi=True))
        await db.commit()
        return (await db.execute(select(ProduksiAkun).where(
            ProduksiAkun.username == "uji_admin"))).scalars().first()


async def isi(akun: ProduksiAkun) -> list[str]:
    """Isi data uji atas nama `akun`. → catatan langkah, untuk ditampilkan.

    Aksinya dijalankan SEBAGAI orang itu, lewat kuki sesinya sendiri: kalau
    perannya tak boleh melakukan sesuatu, di sini pun tak boleh. Data uji yang
    hanya bisa dibuat dengan hak yang tak dimiliki siapa pun bukan gambaran
    pekerjaan yang sungguhan.
    """
    import httpx

    from app.main import app
    from app.web.security import NAMA_COOKIE, buat_token

    langkah: list[str] = []
    async with SessionLocal() as db:
        pemasok = await _pemasok(db)
        n = await _tiket(db, pemasok)
        await db.commit()
    langkah.append(f"{len(PEMASOK)} pemasok · {n} tiket timbang baru")

    tr = httpx.ASGITransport(app=app)
    kuki = {NAMA_COOKIE: buat_token(akun)}
    async with httpx.AsyncClient(transport=tr, base_url="http://uji",
                                 cookies=kuki, follow_redirects=False) as c:
        tiket = (await c.get("/miniapp/actions/timbang-masuk-aktif")).json()
        if not isinstance(tiket, list):
            langkah.append("⚠️ tiket tak terbaca — data uji tak jadi diisi")
            return langkah

        def pilih(jenis: str, n: int) -> list[dict]:
            return [t for t in tiket if jenis.lower() in t["label"].lower()][:n]

        # Hanya sebagian tiket yang ditindak. Sisanya sengaja ditinggal di
        # antrean, supaya layar antrean pun ada isinya untuk dicoba.
        for t in pilih("basah", 2):
            r = await c.post("/miniapp/actions/gabah-masuk",
                             json={"timbangan_transaksi_id": t["value"],
                                   "tujuan": "dryer:1"})
            langkah.append(("✓ " if r.status_code == 200 else "✗ ")
                           + f"gabah basah → mesin pengering ({t['label'][:26]})")

        # Silonya diambil dari tujuan yang DITAWARKAN server, bukan ditebak
        # nomornya: silo di Gudang 2 bernama sama dan bernomor lain, dan
        # menebak akan menaruh gabah di gudang yang salah tanpa peringatan.
        menu = {a["id"]: a for a in (await c.get("/miniapp/actions/menu")).json()}
        silo = [o[0] for f in menu.get("gabah_masuk", {}).get("fields", [])
                if f["name"] == "tujuan" for o in f.get("options", [])
                if str(o[0]).startswith("silo:")]
        for t in pilih("kering", 1):
            if not silo:
                break
            r = await c.post("/miniapp/actions/gabah-masuk",
                             json={"timbangan_transaksi_id": t["value"],
                                   "tujuan": silo[0]})
            langkah.append(("✓ " if r.status_code == 200 else "✗ ")
                           + f"gabah kering → {silo[0]}")

        r = await c.post("/miniapp/actions/mulai-pengeringan",
                         json={"target_kadar_air": 14, "mode_dryer": "20T"})
        langkah.append(("✓ " if r.status_code == 200 else "✗ ") + "pengeringan mulai")

        lot = (await c.get("/miniapp/actions/drying-active")).json()
        if isinstance(lot, list) and lot:
            for tes in (22.4, 19.8):
                await c.post("/miniapp/actions/kadar-air",
                             json={"kode_lot": lot[0]["value"], "tes_1": tes,
                                   "tes_2": tes + .2, "tes_3": tes - .1,
                                   "tes_4": tes + .1, "indikator": tes - 1.2})
            langkah.append("✓ dua bacaan kadar air (22,4% → 19,8%)")

        siap = (await c.get("/miniapp/actions/silo-siap-giling")).json()
        if isinstance(siap, list) and siap:
            r = await c.post("/miniapp/actions/mulai-giling",
                             json={"silo": siap[0]["value"]})
            langkah.append(("✓ " if r.status_code == 200 else "✗ ") + "giling mulai")

    langkah.append("Harga sengaja BELUM diverifikasi — "
                   "layar Menunggu keputusan pun berisi.")
    return langkah
