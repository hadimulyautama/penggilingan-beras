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
                "pemilik": "JAS-2610-001 Bu Sri"}


async def _packing(pg, sosoh_jasa, *, kode_pol, karung):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing

    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        await catat_packing(db, user=u, kode_pol=kode_pol,
                           kategori="beras_putih", grade="medium",
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


async def test_halaman_titipan_mengelompokkan_per_pelanggan(pg, sosoh_jasa):
    """`/stok-produk-jasa` — satu seksi per pesanan, menyebut pemiliknya.

    Pengelompokan yang sama persis dengan yang dikerjakan
    `layar_produk.halaman_stok_produk_jasa` — diuji di sini atas
    `barang_jadi_g2()` langsung, konsisten dengan pola pg lain di berkas
    ini, tanpa butuh autentikasi HTTP penuh.
    """
    from app.services.stok import GRADES_BERAS, barang_jadi_g2

    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_pabrik"], karung=40)
    await _packing(pg, sosoh_jasa, kode_pol=sosoh_jasa["kode_jasa"], karung=20)

    async with pg() as db:
        bj = await barang_jadi_g2(db)
    pesanan: dict[int, dict] = {}
    for k in bj.produk + bj.samping:
        jid = k.get("jasa_id")
        if jid is None:
            continue
        p = pesanan.setdefault(jid, {"pemilik": k.get("pemilik"), "produk": [], "samping": []})
        (p["produk"] if k["jenis"] in GRADES_BERAS or k["jenis"] == "beras_putih"
         else p["samping"]).append(k)
    assert len(pesanan) == 1
    p = next(iter(pesanan.values()))
    assert p["pemilik"] == sosoh_jasa["pemilik"]
    assert sum(k["kg"] for k in p["produk"]) == 500
