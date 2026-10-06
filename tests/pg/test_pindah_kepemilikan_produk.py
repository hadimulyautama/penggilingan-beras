"""Pindah kepemilikan — titipan jadi milik pabrik (6 Oktober 2026).

Keputusan pemilik, halaman "Produk Jasa": barang atau hasil samping
pelanggan "bisa jadi milik kita ataupun kita beli" — dan koreksi susulan
("admin should typr a kg/karung amount for a partial transter") menolak
pindah "semua atau tidak sama sekali": admin mengetik jumlahnya sendiri,
FIFO, baris dipecah bila jumlahnya jatuh di tengah satu baris.

Berkas ini membuktikan di Postgres sungguhan: pemindahan AMAN walau sebagian
sisa pesanan sudah diambil pelanggan (`outgoing_records`), pagar menolak
memindahkan lebih daripada sisa, dan — pelajaran dari koreksi lapangan
"pemisahannya bukan per proses, tapi per pelanggan" — broken curah milik
PELANGGAN (bisa beberapa pesanan) dijawab & dipindah sebagai SATU angka
gabungan, dengan picker katalog umum mengelompokkannya dengan cara yang
SAMA supaya nilai tombol selalu cocok dengan satu pilihan picker.
"""
from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def titipan(pg, pemakai):
    """Bu Sri: dua pesanan.

    Pesanan 1 (`jasa1`): 5.000 kg medium disosoh, 20 karung (500 kg) sudah
    dipacking, dan 500 kg broken sudah dicatat curah (dua baris: 300 + 200,
    supaya transfer FIFO menyentuh lebih dari satu baris).

    Pesanan 2 (`jasa2`): 100 kg broken curah sendiri — dipakai membuktikan
    sisa broken curah Bu Sri (dua pesanan) dijawab sebagai SATU angka
    gabungan, bukan dijumlah belakangan oleh pemanggil.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import ByproductStock, Jasa, Pelanggan, Silo, User, Warehouse
    from app.penggilingan.gudang2.models import (PolishingOutputLog, PolishingProcess,
                                                  PolishingSiloUsage)
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.seed import seed_master
    from app.services.stok import barang_jadi_g2

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        silo = (await db.execute(select(Silo).where(
            Silo.warehouse_id == g2.id))).scalars().first()
        if silo is None:
            silo = Silo(nama_silo="Silo A", warehouse_id=g2.id)
            db.add(silo)
            await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add(pel)
        await db.flush()
        jasa1 = Jasa(kode="JAS-2610-001", pelanggan_id=pel.id, status="berjalan")
        jasa2 = Jasa(kode="JAS-2610-002", pelanggan_id=pel.id, status="berjalan")
        db.add_all([jasa1, jasa2])
        await db.flush()

        p1 = PolishingProcess(kode_proses="POL-UJIT-01", status="selesai",
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=u.id, jasa_id=jasa1.id)
        # `jasa_ids_per_pelanggan_dengan_hasil()` menemukan pesanan lewat
        # `PolishingProcess.jasa_id` — pesanan kedua Bu Sri WAJIB punya
        # prosesnya SENDIRI, bukan menumpang `source_id=p1.id`, kalau tidak
        # ia tak pernah terhitung sebagai "pesanan yang pernah menghasilkan
        # sosoh" dan hilang dari grup gabungannya.
        p2 = PolishingProcess(kode_proses="POL-UJIT-02", status="selesai",
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=u.id, jasa_id=jasa2.id)
        db.add_all([p1, p2])
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p1.id, silo_id=silo.id,
                                  berat_awal_kg=5_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=5_000))
        db.add(PolishingOutputLog(polishing_process_id=p1.id, jenis="medium",
                                  berat_kg=5_000, waktu_update=now_local(),
                                  input_by=u.id))
        db.add(PolishingSiloUsage(polishing_process_id=p2.id, silo_id=silo.id,
                                  berat_awal_kg=1_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=1_000))
        db.add(PolishingOutputLog(polishing_process_id=p2.id, jenis="broken",
                                  berat_kg=100, waktu_update=now_local(),
                                  input_by=u.id))
        await db.flush()

        kini = now_local()
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=p1.id, berat_kg=300, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=jasa1.id))
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=p1.id, berat_kg=200, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=jasa1.id))
        db.add(ByproductStock(jenis_produk="broken", source_type="polishing",
                              source_id=p2.id, berat_kg=100, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=jasa2.id))
        await db.commit()

        await catat_packing(db, user=u, kode_pol="POL-UJIT-01", kategori="beras_putih",
                            grade="medium", material_kode="biasa", ukuran=25,
                            jumlah_karung=20)
        bj = await barang_jadi_g2(db)

    kartu = next(k for k in bj.produk if k["jasa_id"] == jasa1.id)
    return {"user": pemakai.id, "pelanggan_id": pel.id,
            "jasa1": jasa1.id, "jasa2": jasa2.id,
            "sku_id": kartu["sku_id"], "std_id": kartu["std_id"]}


# ═══════════════════ Barang jadi (karung) — FIFO & pagar ═══════════════════

async def test_pindah_barang_jadi_sebagian_memecah_baris(pg, titipan):
    """20 karung milik jasa1; pindah 5 — sisanya 15 tetap jasa1, 5 jadi
    pabrik, dan beratnya persis proporsional (25 kg/karung)."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (
        hitung_stok_finished_goods, pindah_kepemilikan_barang_jadi)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        berat = await pindah_kepemilikan_barang_jadi(
            db, user=u, sku_id=titipan["sku_id"], standard_id=titipan["std_id"],
            jasa_id=titipan["jasa1"], karung=5)
        assert berat == pytest.approx(125.0)

        sisa_jasa = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"], jasa_id=titipan["jasa1"])
        sisa_pabrik = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"])
    assert sisa_jasa == {"karung": 15, "kg": pytest.approx(375.0)}
    assert sisa_pabrik == {"karung": 5, "kg": pytest.approx(125.0)}


async def test_pindah_barang_jadi_menolak_lebih_dari_sisa(pg, titipan):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (
        InventoryError, pindah_kepemilikan_barang_jadi)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        with pytest.raises(InventoryError, match="tinggal 20 karung"):
            await pindah_kepemilikan_barang_jadi(
                db, user=u, sku_id=titipan["sku_id"], standard_id=titipan["std_id"],
                jasa_id=titipan["jasa1"], karung=21)


async def test_pindah_barang_jadi_aman_walau_sebagian_sudah_diambil(pg, titipan):
    """Pelanggan sudah mengambil 12 dari 20 karung (perintah barang keluar
    sungguhan, bukan simulasi kosong) — sisa 8, dan memindahkan SELURUH sisa
    itu tak boleh mengambil lebih atau kurang daripada 8 karung persis,
    walau baris `finished_goods_stock` yang dipilih FIFO sudah tersentuh
    pengambilan itu."""
    from datetime import date as _date

    from app.database import now_local
    from app.models import OutgoingItem, OutgoingRecord, User
    from app.penggilingan.inventory.finished_goods import (
        hitung_stok_finished_goods, pindah_kepemilikan_barang_jadi)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        kini = now_local()
        rec = OutgoingRecord(kode="OUT-UJIT-01", jasa_id=titipan["jasa1"],
                             tanggal=kini.date(), waktu=kini, input_by=u.id,
                             status="selesai")
        db.add(rec)
        await db.flush()
        db.add(OutgoingItem(outgoing_record_id=rec.id, item_type="finished_goods",
                            product_sku_id=titipan["sku_id"],
                            rice_quality_standard_id=titipan["std_id"],
                            jumlah_karung=12, berat_kg=300))
        await db.commit()

        sisa = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"], jasa_id=titipan["jasa1"])
        assert sisa == {"karung": 8, "kg": pytest.approx(200.0)}

        berat = await pindah_kepemilikan_barang_jadi(
            db, user=u, sku_id=titipan["sku_id"], standard_id=titipan["std_id"],
            jasa_id=titipan["jasa1"], karung=8)
        assert berat == pytest.approx(200.0)

        sisa_jasa = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"], jasa_id=titipan["jasa1"])
        sisa_pabrik = await hitung_stok_finished_goods(
            db, titipan["sku_id"], titipan["std_id"])
    assert sisa_jasa == {"karung": 0, "kg": pytest.approx(0.0)}
    assert sisa_pabrik == {"karung": 8, "kg": pytest.approx(200.0)}


# ═══════════════════ Broken curah — gabungan per pelanggan ═══════════════════

async def test_hitung_broken_curah_daftar_jasa_id_menjumlah_gabungan(pg, titipan):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah

    async with pg() as db:
        satu = await hitung_stok_broken_curah(db, jasa_id=titipan["jasa1"])
        dua = await hitung_stok_broken_curah(db, jasa_id=titipan["jasa2"])
        gabungan = await hitung_stok_broken_curah(
            db, jasa_id=[titipan["jasa1"], titipan["jasa2"]])
    assert satu == pytest.approx(500.0)
    assert dua == pytest.approx(100.0)
    assert gabungan == pytest.approx(satu + dua)


async def test_pindah_broken_curah_gabungan_dua_pesanan_memecah_baris(pg, titipan):
    """Sisa gabungan Bu Sri = 500 (jasa1, dua baris) + 100 (jasa2) = 600.
    Memindahkan 550 kg wajib menghabiskan SELURUH baris jasa1 (300+200)
    dan memecah baris jasa2 (100 → 50 pabrik + 50 tetap jasa2)."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (
        hitung_stok_broken_curah, pindah_kepemilikan_broken_curah)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        berat = await pindah_kepemilikan_broken_curah(
            db, user=u, jasa_id=[titipan["jasa1"], titipan["jasa2"]], berat_kg=550)
        assert berat == pytest.approx(550.0)

        gabungan = await hitung_stok_broken_curah(
            db, jasa_id=[titipan["jasa1"], titipan["jasa2"]])
        sisa_jasa2 = await hitung_stok_broken_curah(db, jasa_id=titipan["jasa2"])
        sisa_pabrik = await hitung_stok_broken_curah(db)
    assert gabungan == pytest.approx(50.0)
    assert sisa_jasa2 == pytest.approx(50.0), \
        "baris jasa2 wajib terpecah, bukan jasa1 dipaksa menyumbang lebih"
    assert sisa_pabrik == pytest.approx(550.0)


async def test_pindah_broken_curah_menolak_lebih_dari_gabungan(pg, titipan):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import (
        InventoryError, pindah_kepemilikan_broken_curah)

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        with pytest.raises(InventoryError, match="tinggal 600"):
            await pindah_kepemilikan_broken_curah(
                db, user=u, jasa_id=[titipan["jasa1"], titipan["jasa2"]],
                berat_kg=601)


# ═══════════════════ Picker & rute — nilainya wajib cocok ═══════════════════

async def test_picker_mengelompokkan_broken_per_pelanggan_bukan_pesanan(pg, titipan):
    """`produk_jasa_tersedia` wajib menawarkan broken curah Bu Sri sebagai
    SATU baris gabungan dua pesanan — bukan dua baris per pesanan — sebab
    tombol per-kartu di `/stok-produk-jasa` membawa SELURUH `jasa_ids`
    pelanggan itu sekaligus (lihat `layar_produk.halaman_stok_produk_jasa`).
    Nilai yang tak cocok berarti medan "item" di borang gagal terisi
    otomatis tanpa satu pun galat (`aksi.js` mencocokkan apa adanya)."""
    from types import SimpleNamespace

    from app.web.aksi_inventory import produk_jasa_tersedia

    admin = SimpleNamespace(id=titipan["user"], role="admin", nama="Uji")
    daftar = await produk_jasa_tersedia(user=admin)
    baris_cr = [b for b in daftar if b["value"].startswith("cr:broken|")]
    assert len(baris_cr) == 1, "dua pesanan satu pelanggan harus satu baris"
    nilai = baris_cr[0]["value"]
    ids = {int(x) for x in nilai.split("|", 1)[1].split(",")}
    assert ids == {titipan["jasa1"], titipan["jasa2"]}
    assert "600" in baris_cr[0]["label"]
    assert "Bu Sri" in baris_cr[0]["label"]


async def _klien(pg, *, peran: str = "admin") -> "httpx.AsyncClient":
    """Klien HTTP berlogin — sebangun `_klien` di `test_stok_produk_jasa.py`."""
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
        a = ProduksiAkun(user_id=u.id, username=f"pkp{u.id}",
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


async def test_rute_transfer_gerbang_admin_dan_nilai_gabungan_via_http(pg, titipan):
    """Operator ditolak (`can_see_financials`), Admin berhasil memindahkan
    broken curah lewat nilai GABUNGAN (`cr:broken|id1,id2`) persis seperti
    yang dikirim tombol per-kartu halaman `/stok-produk-jasa`."""
    nilai = f"cr:broken|{titipan['jasa1']},{titipan['jasa2']}"

    c = await _klien(pg, peran="operator")
    try:
        r = await c.post("/api/actions/pindah-kepemilikan-produk",
                         json={"item": nilai, "jumlah": 550})
    finally:
        await c.aclose()
    assert r.status_code == 403

    c = await _klien(pg, peran="admin")
    try:
        r = await c.post("/api/actions/pindah-kepemilikan-produk",
                         json={"item": nilai, "jumlah": 550})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
    finally:
        await c.aclose()

    from app.penggilingan.inventory.finished_goods import hitung_stok_broken_curah
    async with pg() as db:
        gabungan = await hitung_stok_broken_curah(
            db, jasa_id=[titipan["jasa1"], titipan["jasa2"]])
    assert gabungan == pytest.approx(50.0)


# ═══════════════════ Halaman: bekatul disebut, broken bertombol ═══════════════

async def test_halaman_jasa_menampilkan_bekatul_readonly_dan_broken_bertombol(
    pg, titipan,
):
    """Keluhan pemilik: "bekatulnya kenapa tidak ada di halaman produk jasa?
    tetap harus ada." Bekatul tampil sebagai INFORMASI (tanpa tombol — sudah
    milik pabrik sejak dibukukan); broken curah tampil dengan tombol yang
    nilainya menyebut SELURUH jasa_ids pelanggan ini."""
    import re

    from app.database import now_local
    from app.models import ByproductStock, User

    async with pg() as db:
        u = await db.get(User, titipan["user"])
        kini = now_local()
        db.add(ByproductStock(jenis_produk="bekatul", source_type="polishing",
                              source_id=1, berat_kg=800, tanggal=kini.date(),
                              waktu=kini, input_by=u.id, jasa_id=None))
        await db.commit()

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/stok-produk-jasa")
    finally:
        await c.aclose()
    assert r.status_code == 200
    assert "Bekatul dari hasil sosoh" in r.text
    assert "sudah milik pabrik sejak dibukukan" in r.text
    assert "Broken (curah), sudah dicatat" in r.text
    # Himpunan id, bukan string persis — urutannya tak dijamin (lihat
    # catatan `jasa_ids_per_pelanggan_dengan_hasil`), maknanya yang harus
    # sama: SELURUH jasa_ids pelanggan ini, bukan cuma salah satu.
    cocok = re.search(r"cr:broken\|([\d,]+)", r.text)
    assert cocok, "tombol pindah broken curah tak ditemukan di halaman"
    assert {int(x) for x in cocok.group(1).split(",")} == {
        titipan["jasa1"], titipan["jasa2"]}


async def test_bekatul_dikarungi_dari_proses_jasa_tetap_tersebut(pg, titipan):
    """Laporan lapangan 6 Oktober 2026: *"saya baru saja packing bekatul dari
    proses jasa. tetapi tidak ada di halaman produk jasa."*

    `bekatul_per_proc` dulu HANYA membaca `ByproductStock` (jalur "Catat
    bekatul curah") — bekatul yang dikarungi langsung lewat `catat_packing`
    (jalur KEDUA bekatul, sejak 28 September 2026) tak pernah dijumlahkan,
    walau `source_id`-nya menunjuk proses yang SAMA. Operator yang packing
    langsung (tanpa singgah "Catat bekatul curah" dulu) kehilangan barisnya.
    """
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import catat_packing

    async with pg() as db:
        db.add(PolishingOutputLog(
            polishing_process_id=1,  # POL-UJIT-01, proses jasa1
            jenis="bekatul", berat_kg=900, waktu_update=now_local(),
            input_by=titipan["user"]))
        await db.commit()
        u = await db.get(User, titipan["user"])
        await catat_packing(db, user=u, kode_pol="POL-UJIT-01",
                            kategori="bekatul", material_kode="bekas",
                            ukuran=40, jumlah_karung=20)      # 800 kg

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/stok-produk-jasa")
    finally:
        await c.aclose()
    assert r.status_code == 200
    assert "Bekatul dari hasil sosoh" in r.text
    assert "800" in r.text or "800,0" in r.text or "800.0" in r.text, \
        "bekatul yang dikarungi dari proses jasa tak tersebut angkanya"
