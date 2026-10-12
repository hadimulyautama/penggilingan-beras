"""Stok Produk — barang jasa belum tampil, dan saringannya salah tempat.

Keadaan sebelum perbaikan (keputusan pemilik 6 Oktober 2026): PK Gudang 1 &
Gudang 2 sudah menampilkan barang jasa (berikut `pemilik`) di kartu stoknya;
Stok Produk membuangnya di SUMBERNYA (`FinishedGoodsStock.jasa_id.is_(None)`
di `barang_jadi_g2()`) — jadi beras pelanggan yang berdiri di gudang tak
tampil di mana pun, sampai ada yang menjualnya dan menemukan selisihnya.

Perbaikannya: `barang_jadi_g2()` mendaftar KEDUANYA (per `jasa_id` sendiri-
sendiri, supaya tak tercampur jadi satu angka pabrik), sementara borang
PENJUALAN (`stok_barang_jadi`, `barang_bisa_keluar`) menyaring `jasa_id is
None` sendiri — persis pola PK. Titipan tampil di halaman khususnya sendiri
(`/stok-produk-jasa`), terpisah per pelanggan.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sosoh_jasa(pg, pemakai):
    """Dua penyosohan SELESAI di Silo A: 9.000 kg medium PABRIK, 5.000 kg
    medium milik pesanan jasa Bu Sri. Belum ada yang dipacking."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Jasa, Pelanggan, Silo, User, Warehouse
    from app.penggilingan.gudang2.models import (PolishingOutputLog, PolishingProcess,
                                                  PolishingSiloUsage)
    from app.services.seed import seed_master

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
        jasa = Jasa(kode="JAS-2610-001", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.flush()

        p1 = PolishingProcess(kode_proses="POL-UJIP-01", status="selesai",
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=u.id)
        db.add(p1)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p1.id, silo_id=silo.id,
                                  berat_awal_kg=10_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=10_000))
        db.add(PolishingOutputLog(polishing_process_id=p1.id, jenis="medium",
                                  berat_kg=9_000, waktu_update=now_local(),
                                  input_by=u.id))

        p2 = PolishingProcess(kode_proses="POL-UJIJ-01", status="selesai",
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=u.id, jasa_id=jasa.id)
        db.add(p2)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p2.id, silo_id=silo.id,
                                  berat_awal_kg=5_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=5_000))
        db.add(PolishingOutputLog(polishing_process_id=p2.id, jenis="medium",
                                  berat_kg=5_000, waktu_update=now_local(),
                                  input_by=u.id))
        await db.commit()
        return {"user": u.id, "kode_pabrik": p1.kode_proses,
                "kode_jasa": p2.kode_proses, "jasa_id": jasa.id,
                "pelanggan_id": pel.id,
                "pemilik": "JAS-2610-001 Bu Sri"}


async def _packing(pg, sosoh_jasa, *, kode_pol, karung, grade="medium"):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing

    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        await catat_packing(db, user=u, kode_pol=kode_pol,
                           kategori="beras_putih", grade=grade,
                           material_kode="biasa", ukuran=25, jumlah_karung=karung)


async def test_beras_jasa_tampil_terpisah_dari_pabrik(pg, sosoh_jasa):
    """40 karung (1.000 kg) pabrik, 20 karung (500 kg) jasa — dua kartu
    terpisah, bukan satu kartu gabungan 60 karung."""
    from app.services.stok import barang_jadi_g2

    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_pabrik"], karung=40)
    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"], karung=20)

    async with pg() as db:
        bj = await barang_jadi_g2(db)
    kartu = [k for k in bj.produk if k["jenis"] == "medium"]
    assert len(kartu) == 2, "harus dua kartu terpisah, bukan digabung"
    pabrik = next(k for k in kartu if k["jasa_id"] is None)
    jasa = next(k for k in kartu if k["jasa_id"] is not None)
    assert pabrik["karung"] == 40 and pabrik["kg"] == 1_000
    assert jasa["karung"] == 20 and jasa["kg"] == 500
    assert jasa["pemilik"] == sosoh_jasa["pemilik"]


async def test_angka_pabrik_tak_berubah_karena_titipan_ikut_didaftar(pg, sosoh_jasa):
    """Pagar inti bagian 2: menampilkan titipan TIDAK boleh menggeser satu
    kilogram pun angka pabrik — keduanya pertanyaan yang berbeda."""
    from app.services.stok import barang_jadi_g2

    # Dulu (sebelum perbaikan) stok pabrik hanya baca baris jasa_id IS NULL;
    # hasilnya untuk kartu pabrik harus sama persis sebelum/sesudah jasa ikut
    # dipacking.
    async with pg() as db:
        sebelum = await barang_jadi_g2(db)
    pabrik_sebelum = sum(k["kg"] for k in sebelum.produk if k["jasa_id"] is None)

    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_pabrik"], karung=40)
    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"], karung=20)

    async with pg() as db:
        sesudah = await barang_jadi_g2(db)
    pabrik_sesudah = sum(k["kg"] for k in sesudah.produk if k["jasa_id"] is None)
    assert pabrik_sesudah == pabrik_sebelum + 1_000       # cuma pabrik sendiri
    assert pabrik_sesudah == 1_000


async def test_beras_jasa_tak_muncul_di_borang_penjualan(pg, sosoh_jasa):
    """⚠⚠ PAGAR TERPENTING: kegagalannya tak terlihat sampai ada yang
    menjualnya. Beras Bu Sri tak boleh tawar di `barang_bisa_keluar` maupun
    `stok_barang_jadi` — keduanya memberi makan borang penjualan pabrik."""
    from types import SimpleNamespace

    from app.web.aksi_inventory import barang_bisa_keluar, stok_barang_jadi

    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_pabrik"], karung=40)
    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"], karung=20)

    admin = SimpleNamespace(id=sosoh_jasa["user"], role="admin", nama="Uji")
    keluar = await barang_bisa_keluar(user=admin)
    assert any("Medium" in b["label"] or "medium" in b["label"].lower()
              for b in keluar), "pabrik harus tetap ditawarkan"
    assert not any(sosoh_jasa["pemilik"] in b["label"] or "Bu Sri" in b["label"]
                  for b in keluar), "beras jasa TIDAK BOLEH tawar di borang jual"

    daftar = await stok_barang_jadi(user=admin)
    assert not any("Bu Sri" in b["label"] for b in daftar)


async def _klien(pg, *, peran: str = "admin") -> "httpx.AsyncClient":
    """Klien HTTP sungguhan berlogin — sebangun `_klien` di
    `tests/pg/test_riwayat_sosoh.py`: rute `render_laci` memegang `Berjalan`
    penuh (view, peran, lencana), dan memanggil fungsinya langsung dengan
    objek tiruan akan berhenti di galat mock jauh sebelum sempat menguji
    yang sungguh diuji — apa yang TERGAMBAR."""
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
        a = ProduksiAkun(user_id=u.id, username=f"spj{u.id}",
                         password_hash=S.hash_sandi("rahasia123"),
                         status="aktif", mode_perangkat=mode_bawaan(peran))
        db.add(a)
        await db.commit()
        tok = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji", follow_redirects=True)
    c.cookies.set(security.NAMA_COOKIE, tok)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    return c


async def test_halaman_titipan_mengelompokkan_per_pelanggan(pg, sosoh_jasa):
    """`/stok-produk-jasa` — satu seksi per pesanan, menyebut pemiliknya,
    kartunya rupa yang SAMA dengan `/stok-produk` (keputusan pemilik:
    "tampilannya juga harus konsisten seperti kartu stock milik kami
    sendiri") — diuji lewat HTTP sungguhan, sebab penjaga yang cuma
    memanggil fungsinya akan lulus pada hari templatnya berhenti menggambar
    angkanya (pelajaran `TempatPk.pemilik`, lihat `test_riwayat_sosoh.py`).
    """
    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_pabrik"], karung=40)
    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"], karung=20)

    # Data pengelompokannya, di tingkat Python.
    from sqlalchemy import select

    from app.penggilingan.gudang2.models import PolishingProcess
    from app.services.jasa import nama_pemilik_banyak
    from app.services.stok import adalah_beras, barang_jadi_g2, stok_produk

    async with pg() as db:
        jasa_ids = sorted((await db.execute(
            select(PolishingProcess.jasa_id.distinct())
            .where(PolishingProcess.jasa_id.isnot(None))
        )).scalars().all())
        assert jasa_ids == [sosoh_jasa["jasa_id"]]
        nama = await nama_pemilik_banyak(db, jasa_ids)
        bj = await barang_jadi_g2(db)
        kartu = await stok_produk(db, jasa_id=jasa_ids[0])
    assert nama[jasa_ids[0]] == sosoh_jasa["pemilik"]
    beras = [k for k in kartu if adalah_beras(k.jenis)]
    # Kartunya KartuProduk (rupa `stok_produk()`), bukan dict sederhana —
    # itulah yang membuatnya bisa digambar `st.blok` yang sama dengan
    # `/stok-produk`.
    assert beras[0].jenis == "medium"
    assert beras[0].hasil_kg == 5_000
    assert beras[0].dikemas_kg == 500
    kemasan_jasa = [k for k in bj.produk if k.get("jasa_id") == jasa_ids[0]]
    assert kemasan_jasa[0]["karung"] == 20

    # Dan yang SUNGGUH tergambar di HTML — lewat HTTP penuh, sebab penjaga
    # yang cuma memanggil fungsinya akan lulus pada hari templatnya berhenti
    # menggambar angkanya (pelajaran `TempatPk.pemilik`, lihat
    # `test_riwayat_sosoh.py`).
    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/stok-produk-jasa")
    finally:
        await c.aclose()
    assert r.status_code == 200
    # Seksinya menyebut PELANGGANNYA ("Bu Sri") — bukan kode pesanannya;
    # koreksi lapangan: dikelompokkan per pelanggan, bukan per pesanan.
    assert "Bu Sri" in r.text
    assert "Hasil sosoh" in r.text and "Dikemas" in r.text and "Curah" in r.text


async def test_stok_produk_pabrik_tidak_mengulang_titipan_produk_jasa(pg, sosoh_jasa):
    """Stok jasa ditampilkan pada halaman Produk Jasa saja, tidak sebagai
    baris tambahan pada kartu stok pabrik."""
    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"], karung=20)

    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/stok-produk")
    finally:
        await c.aclose()
    assert r.status_code == 200
    assert "+ titipan 500 kg" not in r.text

    # Stok jasa tetap tampil di rumahnya sendiri.
    c2 = await _klien(pg, peran="superadmin")
    try:
        r2 = await c2.get("/stok-produk-jasa")
    finally:
        await c2.aclose()
    assert r2.status_code == 200
    assert "500 kg" in r2.text


async def test_stok_produk_pabrik_tak_tercampur_hasil_proses_jasa(pg, sosoh_jasa):
    """Pagar yang terungkap justru oleh perbaikan ini: `stok_produk()` dulu
    TIDAK menyaring `PolishingProcess` sama sekali, jadi "hasil sosoh"
    pabrik diam-diam memuat output proses jasa, dan "curah" pabrik terbaca
    lebih besar daripada yang sebenarnya (sebagian sebenarnya milik
    pelanggan, belum dikemas atas namanya)."""
    from app.services.stok import stok_produk

    async with pg() as db:
        kartu = await stok_produk(db)
    medium = next(k for k in kartu if k.jenis == "medium")
    # HANYA 9.000 kg pabrik (POL-UJIP-01) — BUKAN 9.000 + 5.000 jasa.
    assert medium.hasil_kg == 9_000
    assert medium.curah_kg == 9_000          # belum ada yang dipacking

    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"], karung=20)  # 500 kg

    async with pg() as db:
        kartu = await stok_produk(db)
    medium = next(k for k in kartu if k.jenis == "medium")
    # Packing JASA tak mengurangi curah PABRIK sedikit pun.
    assert medium.hasil_kg == 9_000 and medium.curah_kg == 9_000

    async with pg() as db:
        kartu_jasa = await stok_produk(db, jasa_id=sosoh_jasa["jasa_id"])
    medium_jasa = next(k for k in kartu_jasa if k.jenis == "medium")
    assert medium_jasa.hasil_kg == 5_000
    assert medium_jasa.dikemas_kg == 500
    assert medium_jasa.curah_kg == pytest.approx(5_000 - 500)


async def test_pengambilan_jasa_tak_membuat_dikemas_pabrik_negatif(pg, sosoh_jasa):
    """Pesan kerja 10/pengambilan jasa — reproduksi PERSIS skenario cacat yang
    ditemukan 7 Oktober 2026: sosoh jasa 5.000 kg, dikemas 100 karung (2.500
    kg) atas nama pesanannya, lalu DIAMBIL pemiliknya 2.500 kg.

    Sebelum perbaikan 6 Oktober (lihat `stok_produk()`), `keluar` dihitung
    dari SELURUH `OutgoingItem` tanpa saringan `jasa_id` — pengambilan
    pelanggan ikut mengurangi "keluar" PABRIK, dan kartu "Beras putih" pabrik
    berbunyi `dikemas = -2.500 kg`, MINUS, karena pengambilan pelanggan
    tercatat sebagai penjualan pabrik yang sebenarnya tak pernah terjadi.

    Uji ini yang paling penting di butir 2 (pesan kerjanya sendiri menyebut
    "celahnya lolos dari 1.145 uji yang ada" — pagar packing-saja sudah ada
    di uji lain berkas ini, yang belum pernah diuji adalah langkah AMBIL-nya).
    """
    from app.models import User
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    from app.services import barang_keluar as bk
    from app.services.stok import stok_produk

    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"], karung=100)  # 2.500 kg

    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        sku_id, std_id = (await db.execute(_sku_terpacking())).first()
        r = await bk.buat_perintah(
            db, user=u,
            baris=[bk.BarisPerintah(tipe="finished_goods", sku_id=sku_id,
                                    std_id=std_id, jumlah_karung=100)],
            jasa_id=sosoh_jasa["jasa_id"])
    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        await bk.muat_semua(db, user=u, rec_id=r.rec.id)

    # ── PABRIK: angkanya tak boleh bergerak SAMA SEKALI ──
    async with pg() as db:
        kartu = await stok_produk(db)
    medium = next(k for k in kartu if k.jenis == "medium")
    assert medium.hasil_kg == 9_000, "hasil pabrik tak boleh ikut hasil jasa"
    assert medium.dikemas_kg >= 0, \
        f"dikemas PABRIK jadi negatif ({medium.dikemas_kg}) — pengambilan " \
        "pelanggan bocor ke penjualan pabrik"
    assert medium.dikemas_kg == 0, "pabrik sama sekali belum packing apa pun"
    assert medium.curah_kg == 9_000, \
        "curah pabrik tak boleh berubah karena pengambilan jasa"

    # ── PESANAN: sudah diambil semua, sisanya 0 — bukan 5.000 kg utuh ──
    async with pg() as db:
        kartu_jasa = await stok_produk(db, jasa_id=sosoh_jasa["jasa_id"])
    medium_jasa = next((k for k in kartu_jasa if k.jenis == "medium"), None)
    if medium_jasa is not None:
        assert medium_jasa.dikemas_kg == 0, \
            "sisa dikemas pesanan harus 0 sesudah diambil semua"

    # ── Pembanding independen: fungsi yang sudah terbukti benar ──
    async with pg() as db:
        pabrik = await hitung_stok_finished_goods(db, sku_id, std_id, jasa_id=None)
        pesanan = await hitung_stok_finished_goods(
            db, sku_id, std_id, jasa_id=sosoh_jasa["jasa_id"])
    assert pabrik == {"karung": 0, "kg": 0.0}
    assert pesanan == {"karung": 0, "kg": 0.0}


def _sku_terpacking():
    from sqlalchemy import select

    from app.penggilingan.inventory.models import FinishedGoodsStock
    return (select(FinishedGoodsStock.product_sku_id,
                  FinishedGoodsStock.rice_quality_standard_id)
            .where(FinishedGoodsStock.jasa_id.isnot(None)).limit(1))


async def test_dua_pesanan_satu_pelanggan_digabung_satu_seksi(pg, sosoh_jasa):
    """⚠⚠ Koreksi lapangan: "pemisahannya bukan per proses. tapi per
    pelanggan." Bu Sri datang KEDUA KALINYA — pesanan BARU (`Jasa` kedua,
    kode lain), sosoh KEDUA (broken 1.000 kg) — tetapi tetap pelanggan yang
    SAMA. Halaman ini wajib menyatukan keduanya jadi SATU seksi "Bu Sri",
    bukan memecahnya jadi dua seksi sebagaimana jumlah pesanannya.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Jasa, Pelanggan, Silo, User
    from app.penggilingan.gudang2.models import (PolishingOutputLog, PolishingProcess,
                                                  PolishingSiloUsage)

    async with pg() as db:
        pel = (await db.execute(select(Pelanggan).where(
            Pelanggan.nama_pelanggan == "Bu Sri"))).scalars().one()
        silo = (await db.execute(select(Silo).limit(1))).scalars().first()
        u = await db.get(User, sosoh_jasa["user"])
        jasa2 = Jasa(kode="JAS-2610-002", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa2)
        await db.flush()
        p3 = PolishingProcess(kode_proses="POL-UJIJ-02", status="selesai",
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=u.id, jasa_id=jasa2.id)
        db.add(p3)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p3.id, silo_id=silo.id,
                                  berat_awal_kg=1_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=1_000))
        db.add(PolishingOutputLog(polishing_process_id=p3.id, jenis="broken",
                                  berat_kg=1_000, waktu_update=now_local(),
                                  input_by=u.id))
        await db.commit()

    from app.services.stok import adalah_beras, stok_produk

    async with pg() as db:
        # Dua pesanan, SATU panggilan — `jasa_id` sebagai daftar.
        kartu = await stok_produk(db, jasa_id=[sosoh_jasa["jasa_id"], jasa2.id])
    assert {k.jenis for k in kartu} == {"medium", "broken"}
    beras = [k for k in kartu if adalah_beras(k.jenis)]
    samping = [k for k in kartu if not adalah_beras(k.jenis)]
    assert beras[0].hasil_kg == 5_000           # dari pesanan pertama
    assert samping[0].hasil_kg == 1_000         # dari pesanan kedua

    # Dan lewat rute sungguhan: SATU seksi "Bu Sri", bukan dua.
    c = await _klien(pg, peran="superadmin")
    try:
        r = await c.get("/stok-produk-jasa")
    finally:
        await c.aclose()
    assert r.status_code == 200
    assert r.text.count("Bu Sri") == 1, \
        "satu pelanggan dua pesanan harus satu seksi, bukan dua"
    assert "Broken" in r.text


async def test_hasil_samping_pelanggan_berkurang_sesudah_diangkut_jasa(pg, sosoh_jasa):
    """Pesan kerja 10, bagian 4 (UJI) — pagar terakhir yang masih lowong:
    hasil samping curah (menir/reject/bekatul) titipan pelanggan wajib
    BERKURANG sesudah diangkut lewat perintah pengambilan jasa, bukan cuma
    TAMPIL di `/stok-produk-jasa`.

    ⚠ BUKAN broken — broken punya rumus tiga suku sendiri (`SisaJasa.
    broken_kg`, lihat catatan "telescoping" di `jasa.py`) dan sudah diuji
    jalurnya sendiri. Ini menguji `samping_kg` (menir/reject/bekatul) —
    jalur yang baru dibuka pesan kerja 11 butir 4a (`hitung_stok_byproduct_
    curah` + picker `cr:` di `/actions/barang-jasa`) — DIAM-DIAM sampai
    sekarang belum pernah diuji ujung ke ujung lewat perintah sungguhan,
    cuma lewat pemanggilan fungsi langsung.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import User
    from app.penggilingan.inventory.finished_goods import hitung_stok_byproduct_curah
    from app.penggilingan.inventory.models import ByproductStock
    from app.services import barang_keluar as bk
    from app.services.jasa import sisa_jasa
    from app.web.aksi_inventory import barang_jasa

    jid = sosoh_jasa["jasa_id"]
    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        u.role = "superadmin"      # `barang_jasa()` (picker) menuntut financials
        now = now_local()
        db.add(ByproductStock(
            jenis_produk="menir", source_type="polishing", source_id=None,
            berat_kg=800, tanggal=now.date(), waktu=now, status="tersedia",
            input_by=u.id, jasa_id=jid))
        await db.commit()

    async with pg() as db:
        assert await hitung_stok_byproduct_curah(db, "menir", jasa_id=jid) == 800
        sisa = await sisa_jasa(db, jid)
        assert sisa.samping_kg == 800

    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
    opsi = {o["value"] for o in
            await barang_jasa(induk=str(sosoh_jasa["pelanggan_id"]), user=u)}
    assert f"cr:menir@{jid}" in opsi

    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        r = await bk.buat_perintah(
            db, user=u, jasa_id=jid,
            baris=[bk.BarisPerintah(tipe="byproduct_curah", jenis="menir",
                                    berat_kg=800)])
        rec_id = r.rec.id
    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        await bk.muat_semua(db, user=u, rec_id=rec_id)

    async with pg() as db:
        assert await hitung_stok_byproduct_curah(db, "menir", jasa_id=jid) == 0
        assert await hitung_stok_byproduct_curah(db, "menir", jasa_id=None) == 0, \
            "pengambilan jasa tak boleh ikut mengurangi stok menir pabrik"
        sisa = await sisa_jasa(db, jid)
        assert sisa.samping_kg == 0


async def test_picker_pengambilan_jasa_menampilkan_mutu_beras(pg, sosoh_jasa):
    """Pilihan beras jasa harus memakai mutu pada stoknya, bukan label mutu
    kosong. Kedua grade memakai SKU kemasan yang sama dan dibedakan oleh
    rice_quality_standard_id.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingProcess
    from app.web.aksi_inventory import barang_jasa

    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        u.role = "superadmin"
        proc = (await db.execute(
            select(PolishingProcess).where(
                PolishingProcess.kode_proses == sosoh_jasa["kode_jasa"])
        )).scalar_one()
        for grade in ("premium", "medsuper"):
            db.add(PolishingOutputLog(
                polishing_process_id=proc.id, jenis=grade, berat_kg=25,
                waktu_update=now_local(), input_by=u.id))
        await db.commit()

    for grade in ("premium", "medsuper"):
        await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"],
                       karung=1, grade=grade)

    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
    opsi = await barang_jasa(induk=str(sosoh_jasa["pelanggan_id"]), user=u)
    beras = [o["label"] for o in opsi if o["value"].startswith("bj:")]
    assert any("Premium" in label for label in beras), beras
    assert any("Medium Super" in label for label in beras), beras
    assert all("biasa 25 kg" in label for label in beras), beras
    assert all("Polos" in label or "Tanpa merek" in label for label in beras), beras
    assert not any("mutu di catatan lama kosong" in label for label in beras), beras
