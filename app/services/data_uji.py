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

PEMASOK = [
    "H. Karyo", "Bu Sri", "Pak Tarno", "H. Sulaiman Abdurrahman",
    "Kelompok Tani Sumber Rejeki", "Mbah Wagimin", "Hj. Rohmah",
    "Pak Darto", "CV Tani Makmur Sentosa", "Bu Painem",
]

#: Tiket timbang: (indeks pemasok, jenis, plat, kg, berapa hari yang lalu).
#:
#: Riwayat beberapa hari dibuat dengan sengaja. Layar Laporan dan List audit
#: yang hanya berisi hari ini tak bisa dipakai menilai apa pun — yang ingin
#: dilihat orang di sana justru perbandingan antar hari.
TIKET = [
    # ── 4 hari lalu ──
    (0, "GABAH_BASAH",  "AD 1234 XY",  9_850, 4),
    (1, "GABAH_BASAH",  "AD 88 KK",   10_400, 4),
    (5, "GABAH_BASAH",  "AD 3 QQ",     8_900, 4),
    # ── 3 hari lalu ──
    (2, "GABAH_KERING", "AD 21 LM",    8_600, 3),
    (6, "GABAH_KERING", "AD 45 RT",   10_150, 3),
    (3, "GABAH_BASAH",  "AD 9 PP",    11_000, 3),
    # ── 2 hari lalu ──
    (4, "GABAH_BASAH",  "AD 7 CC",     9_200, 2),
    (7, "GABAH_BASAH",  "AD 12 DD",   10_600, 2),
    (8, "GABAH_KERING", "AD 77 SS",    9_400, 2),
    # ── kemarin ──
    (9, "GABAH_BASAH",  "AD 2 MM",     8_750, 1),
    (0, "GABAH_KERING", "AD 1234 XY", 10_700, 1),
    (1, "GABAH_BASAH",  "AD 88 KK",    9_980, 1),
    # ── hari ini: sebagian ditindak, sebagian ditinggal di antrean ──
    (2, "GABAH_BASAH",  "AD 21 LM",   10_250, 0),
    (5, "GABAH_BASAH",  "AD 3 QQ",     9_600, 0),
    (3, "GABAH_KERING", "AD 9 PP",    11_200, 0),
    (6, "GABAH_KERING", "AD 45 RT",    8_300, 0),
    (7, "GABAH_BASAH",  "AD 12 DD",    9_050, 0),
    (8, "GABAH_KERING", "AD 77 SS",   10_900, 0),
    (9, "GABAH_BASAH",  "AD 2 MM",     8_480, 0),
    (4, "GABAH_KERING", "AD 7 CC",     9_770, 0),
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


class JembatanDipakai(Exception):
    """Basis datanya melayani jembatan timbang yang sungguh dipakai."""


async def _jembatan_sungguhan(db: AsyncSession) -> int:
    """Berapa tiket timbang di sini yang BUKAN buatan pembuat data uji.

    `timbangan_transaksi` milik aplikasi Timbangan, dan aplikasi itu membaca
    basis data yang sama. Tiket karangan yang ditulis ke sini tidak berhenti
    di layar Produksi — ia muncul di layar petugas timbang, di antara tiket
    truk yang sungguh datang hari itu. Sekali ini terjadi, dan pemiliknya
    yang menemukannya.

    Jadi keberadaan tiket ORANG LAIN dipakai sebagai tanda: kalau jembatannya
    sudah dipakai sungguhan, tak ada satu pun tiket karangan yang boleh lahir
    di sini.
    """
    return (await db.execute(text(
        "SELECT count(*) FROM timbangan_transaksi WHERE kode NOT LIKE 'TRX-UJI-%'"
    ))).scalar_one()


async def _tiket(db: AsyncSession, pemasok: dict[str, int]) -> int:
    """Tiket timbang, disuntikkan langsung — ia milik aplikasi Timbangan.

    `timbang1_waktu` yang mundur beberapa hari BUKAN hiasan: dari situlah
    tanggal batch diambil (`purchase.create_purchase_batch_dari_timbang`),
    jadi riwayat beberapa harinya terbentuk lewat jalur yang sama dengan
    hari biasa — bukan dengan menambal tanggal sesudahnya.
    """
    dibuat = 0
    for i, (idx, jenis, plat, kg, lalu) in enumerate(TIKET, start=1):
        kode = f"TRX-UJI-{i:03d}"
        ada = (await db.execute(
            text("SELECT 1 FROM timbangan_transaksi WHERE kode = :k"), {"k": kode})).first()
        if ada:
            continue
        await db.execute(text("""
            INSERT INTO timbangan_transaksi
              (kode, tanggal, arah, jenis_kode, nomor_polisi, nama_sopir,
               supplier_id, timbang1_kg, timbang2_kg, netto_timbangan_kg,
               berat_barang_kg, berat_acuan_kg, status_kontrol, status_tiket,
               timbang1_waktu, timbang2_waktu)
            VALUES (:k, CURRENT_DATE - CAST(:lalu AS int), 'MASUK', :j, :p,
                    'Sopir Uji', :s, :t1, :t2, :n, :n, :n, 'NORMAL', 'TERBUKA',
                    now() - make_interval(days => CAST(:lalu AS int), hours => 3),
                    now() - make_interval(days => CAST(:lalu AS int), hours => 2))
        """), {"k": kode, "j": jenis, "p": plat, "s": pemasok[PEMASOK[idx]],
               "t1": kg + 4200, "t2": 4200, "n": kg, "lalu": lalu})
        dibuat += 1
    return dibuat


async def _mundurkan(hari: int, kode_lot: str | None, kode_proses: str | None) -> None:
    """Geser jam satu siklus yang sudah selesai ke belakang.

    Bentuk datanya tetap dibuat aplikasi lewat jalurnya sendiri; yang digeser
    hanya JAMNYA. Tanpa ini seluruh riwayat bertanggal hari ini, dan laporan
    per hari — satu-satunya alasan riwayat itu dibuat — jadi tak menunjukkan
    apa pun. Hanya dipakai pada siklus yang SUDAH ditutup: yang masih berjalan
    dibiarkan apa adanya supaya "sudah berapa lama" tetap jujur.
    """
    async with SessionLocal() as db:
        if kode_lot:
            await db.execute(text("""
                UPDATE drying_lots SET
                    waktu_mulai_pengeringan = waktu_mulai_pengeringan - make_interval(days => CAST(:h AS int)),
                    waktu_selesai_pengeringan = waktu_selesai_pengeringan - make_interval(days => CAST(:h AS int)),
                    waktu_selesai_pendinginan = waktu_selesai_pendinginan - make_interval(days => CAST(:h AS int))
                 WHERE kode_lot = :k
            """), {"h": hari, "k": kode_lot})
        if kode_proses:
            await db.execute(text("""
                UPDATE milling_process SET
                    waktu_mulai = waktu_mulai - make_interval(days => CAST(:h AS int)),
                    waktu_selesai = waktu_selesai - make_interval(days => CAST(:h AS int))
                 WHERE kode_proses = :k
            """), {"h": hari, "k": kode_proses})
        await db.commit()


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
        dipakai = await _jembatan_sungguhan(db)
        if dipakai:
            raise JembatanDipakai(
                f"Dibatalkan: basis data ini melayani jembatan timbang yang "
                f"sedang dipakai — ada {dipakai} tiket timbang sungguhan di "
                "dalamnya. Tiket karangan yang dibuat di sini akan muncul di "
                "layar petugas timbang, di antara truk yang benar-benar "
                "datang. Data uji hanya boleh diisi di basis data yang khusus "
                "untuk menguji."
            )
        pemasok = await _pemasok(db)
        n = await _tiket(db, pemasok)
        await db.commit()
    langkah.append(f"{len(PEMASOK)} pemasok · {n} tiket timbang")

    tr = httpx.ASGITransport(app=app)
    kuki = {NAMA_COOKIE: buat_token(akun)}
    async with httpx.AsyncClient(transport=tr, base_url="http://uji",
                                 cookies=kuki, follow_redirects=False) as c:

        async def kirim(alamat: str, muatan: dict) -> dict:
            r = await c.post(f"/miniapp/actions/{alamat}", json=muatan)
            return r.json() if r.headers.get("content-type", "").startswith(
                "application/json") else {}

        async def daftar(alamat: str) -> list:
            r = await c.get(f"/miniapp/actions/{alamat}")
            d = r.json() if r.status_code == 200 else []
            return d if isinstance(d, list) else []

        async def tiket_bebas(jenis: str, n: int = 1, *,
                              terbaru: bool = False) -> list[dict]:
            """Yang TERTUA lebih dulu — kodenya urut waktu (TRX-UJI-001 …).

            Tanpa diurutkan, siklus riwayat memakan tiket terbaru dan seluruh
            riwayat terpencet ke dua-tiga hari terakhir, sementara tiket
            tertua menganggur di antrean. Daftar dari server diurutkan untuk
            MATA operator — yang berjalan didahulukan — dan urutan itu tak
            ada hubungannya dengan urutan yang dibutuhkan di sini.
            """
            semua = await daftar("timbang-masuk-aktif")
            cocok = [t for t in semua if jenis.lower() in t["label"].lower()]
            return sorted(cocok, key=lambda t: t["label"], reverse=terbaru)[:n]

        async def silo_tujuan() -> list[str]:
            menu = {a["id"]: a for a in await daftar("menu")}
            return [o[0] for f in menu.get("gabah_masuk", {}).get("fields", [])
                    if f["name"] == "tujuan" for o in f.get("options", [])
                    if str(o[0]).startswith("silo:")]

        async def siklus_penuh(hari: int, ke: int) -> None:
            """Satu hari kerja yang SELESAI: masuk → kering → silo → giling →
            QC → verifikasi. Inilah yang membuat Laporan punya isi."""
            masuk = []
            for t in await tiket_bebas("basah", 2):
                await kirim("gabah-masuk", {"timbangan_transaksi_id": t["value"],
                                            "tujuan": "dryer:1"})
                masuk.append(t)
            if not masuk:
                return
            r = await kirim("mulai-pengeringan",
                            {"target_kadar_air": 14, "mode_dryer": "20T"})
            lot = await daftar("drying-active")
            if not lot:
                return
            kode_lot = lot[0]["value"]
            for tes in (23.1, 19.4, 15.2, 13.8):
                await kirim("kadar-air", {"kode_lot": kode_lot, "tes_1": tes,
                                          "tes_2": tes + .2, "tes_3": tes - .1,
                                          "tes_4": tes + .1, "indikator": tes - 1.1})
            await kirim("selesai-pengeringan", {"kode_lot": kode_lot})
            await kirim("selesai-pendinginan", {"kode_lot": kode_lot})
            siap = await daftar("drying-done")
            silo = await daftar("silo-g1")
            if siap and silo:
                await kirim("pindah-silo", {"kode_lot": siap[0]["value"],
                                            "silo": silo[0]["value"]})
            bisa = await daftar("silo-siap-giling")
            kode_proses = None
            if bisa:
                await kirim("mulai-giling", {"silo": bisa[0]["value"]})
                aktif = await daftar("milling-active")
                if aktif:
                    kode_proses = aktif[0]["value"]
                    # Bobotnya dibaca dari basis data, BUKAN diurai dari
                    # tulisan di kartu: label itu untuk mata orang, bentuknya
                    # boleh berubah kapan saja, dan kode yang mengurainya akan
                    # pecah pada perubahan yang tak ada hubungannya.
                    async with SessionLocal() as db2:
                        kg = float((await db2.execute(text(
                            "SELECT berat_gabah_masuk_kg FROM milling_process "
                            "WHERE kode_proses = :k"), {"k": kode_proses}
                        )).scalar_one_or_none() or 18_000)
                    await kirim("hasil-giling", {"kode_proses": kode_proses,
                                                 "berat_kumulatif": round(kg * .63)})
                    await kirim("selesai-giling", {"kode_proses": kode_proses})
                    await kirim("qc-giling", {"kode_proses": kode_proses,
                                              "kadar_air": 13.4, "broken": 8.5,
                                              "susut": 1.2})
                    await kirim("verify-output", {"kode_proses": kode_proses,
                                                  "berat_output": round(kg * .63)})
            # Harga diverifikasi untuk yang sudah selesai — supaya layar
            # Menunggu keputusan hanya berisi yang hari ini, bukan tumpukan
            # sisa berhari-hari yang tak pernah ada di pabrik sungguhan.
            for b in await daftar("gabah-unverified"):
                await kirim("verify-gabah", {"kode_batch": b["value"],
                                             "metode": "per_kg", "nilai": 5_600 + ke * 50})
            await _mundurkan(hari, kode_lot, kode_proses)
            langkah.append(f"✓ siklus penuh {hari} hari lalu — {kode_lot}"
                           + (f" → {kode_proses}" if kode_proses else ""))

        for ke, hari in enumerate((4, 3, 2), start=1):
            await siklus_penuh(hari, ke)

        # ── Hari ini: keadaan yang sedang berlangsung ──
        #
        # Memakai tiket TERBARU, kebalikan dari riwayat. Kalau tidak, mesin
        # yang menyala hari ini berisi gabah bertanggal minggu lalu, dan
        # "gabah masuk hari ini" di Beranda menghitung nol sementara layar
        # sebelahnya menunjukkan pengeringan berjalan.
        for t in await tiket_bebas("basah", 2, terbaru=True):
            await kirim("gabah-masuk", {"timbangan_transaksi_id": t["value"],
                                        "tujuan": "dryer:1"})
        await kirim("mulai-pengeringan", {"target_kadar_air": 14, "mode_dryer": "25T"})
        lot = await daftar("drying-active")
        if lot:
            for tes in (22.4, 19.8):
                await kirim("kadar-air", {"kode_lot": lot[0]["value"], "tes_1": tes,
                                          "tes_2": tes + .2, "tes_3": tes - .1,
                                          "tes_4": tes + .1, "indikator": tes - 1.2})
            langkah.append(f"✓ pengeringan berjalan — {lot[0]['value']}, 2 bacaan")

        silo = await silo_tujuan()
        for t in await tiket_bebas("kering", 1, terbaru=True):
            if silo:
                await kirim("gabah-masuk", {"timbangan_transaksi_id": t["value"],
                                            "tujuan": silo[-1]})
        bisa = await daftar("silo-siap-giling")
        if bisa:
            await kirim("mulai-giling", {"silo": bisa[0]["value"]})
            aktif = await daftar("milling-active")
            if aktif:
                await kirim("hasil-giling", {"kode_proses": aktif[0]["value"],
                                             "berat_kumulatif": 4_200})
                langkah.append(f"✓ giling berjalan — {aktif[0]['value']}")
                # Satu proses DIHENTIKAN sementara: layar jeda pun ada isinya,
                # dan jam tertahan mulai berjalan dari sekarang.
                proses = await daftar("proses-berjalan")
                target = next((p for p in proses
                               if "giling" in str(p.get("value", "")).lower()), None)
                if target:
                    await kirim("hentikan-proses", {"proses": target["value"],
                                                    "sebab": "Limbah produksi penuh"})
                    langkah.append("⏸ satu giling dihentikan sementara")

        # Satu muatan ditumpuk di lantai — tanda pembelian berlebih.
        for t in await tiket_bebas("kering", 1, terbaru=True):
            await kirim("gabah-masuk", {"timbangan_transaksi_id": t["value"],
                                        "tujuan": "tumpuk"})
            langkah.append("✓ satu muatan ditumpuk di lantai")

        sisa = len(await daftar("timbang-masuk-aktif"))
        belum = len(await daftar("gabah-unverified"))
        langkah.append(f"{sisa} tiket ditinggal di antrean · "
                       f"{belum} harga menunggu diverifikasi")
    return langkah
