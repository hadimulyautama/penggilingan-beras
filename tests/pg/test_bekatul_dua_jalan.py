"""Bekatul punya DUA jalan, dan keduanya menguras tumpukan yang sama.

Keputusan pemilik 28 September 2026: bekatul sebagian dijual curah, sebagian
dikemas karung bekas 40 kg. Sampai hari itu ia curah saja — `catat_bekatul`
menulis ke `byproduct_stock` tanpa batas atas apa pun, sebab tak ada jalan
kedua yang bisa berebut dengannya.

Begitu jalan kedua dibuka, ketiadaan batas itu jadi lubang: 1.000 kg boleh
dibukukan curah, lalu dikarungi utuh, dan stok bekatul jadi 2.000 kg tanpa satu
pesan pun. Bekatul bukan barang mahal — tetapi angka stok yang bisa
dilipatgandakan dengan dua ketukan wajar membuat SELURUH layar itu berhenti
dipercaya.

Berkas ini menjaga tiga hal: kedua jalan saling mengurangi, bekatul yang
dikarungi tidak MENGUAP dari stok saat berpindah rumah, dan pabrik yang tak
menimbang bekatul di mesin tidak ikut terkunci.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sosoh_bekatul(pg):
    """Satu penyosohan SELESAI dengan 1.000 kg bekatul tercatat keluar mesin."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import (PackageSize, PackagingMaterial, Silo, Supplier, User,
                            Warehouse)
    from app.penggilingan.gudang2.models import (PkPurchaseBatch, PolishingOutputLog,
                                                 PolishingProcess, PolishingSiloUsage)
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        silo = Silo(nama_silo="Silo A", warehouse_id=g2.id)
        u = User(nama="Op Polesan", role="operator", status="aktif",
                 default_warehouse_id=g2.id)
        s = Supplier(nama_supplier="UD Sumber")
        db.add_all([silo, u, s])
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-BK-01", supplier_id=s.id, berat_total_kg=10_000,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        p = PolishingProcess(kode_proses="POL-BK-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=u.id)
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo.id,
                                  berat_awal_kg=10_000, berat_masuk_kg=0,
                                  berat_akhir_kg=0, berat_terpakai_kg=10_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="bekatul",
                                  berat_kg=1_000, waktu_update=now_local(),
                                  input_by=u.id))
        # Ukuran 40 kg & karung bekas wajib ada di master — keduanya disemai.
        assert (await db.execute(select(PackageSize).where(
            PackageSize.ukuran_kg == 40))).scalars().first(), \
            "ukuran 40 kg belum disemai"
        assert (await db.execute(select(PackagingMaterial).where(
            PackagingMaterial.kode == "bekas"))).scalars().first()
        await db.commit()
        return {"user": u.id, "kode": p.kode_proses, "proses_id": p.id}


async def _curah(pg, uid, kode, kg):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_bekatul
    async with pg() as db:
        return await catat_bekatul(db, user=await db.get(User, uid),
                                   kode_pol=kode, berat_kg=kg)


async def _karung(pg, uid, kode, karung):
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing
    async with pg() as db:
        return await catat_packing(db, user=await db.get(User, uid), kode_pol=kode,
                                   kategori="bekatul", grade=None,
                                   material_kode="bekas", ukuran=40,
                                   jumlah_karung=karung)


async def test_bekatul_bisa_dikarungi_empat_puluh_kilo(pg, sosoh_bekatul):
    """Keterangan pemilik: "kalau bekatul dikemas dengan karung bekas ukuran 40
    kg". Sebelum hari itu kombinasi ini ditolak aturan kemasan."""
    r = await _karung(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 10)
    assert r.berat_total_kg == 400, r


async def test_yang_sudah_dicatat_curah_tak_bisa_dikarungi_lagi(pg, sosoh_bekatul):
    """Lubang yang lahir bersama jalan kedua: 1.000 kg dibukukan curah, lalu
    dikarungi utuh — keduanya lolos, stok jadi 2.000 kg, tanpa satu pesan pun."""
    from app.penggilingan.inventory.packaging import InventoryError

    await _curah(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 800)
    with pytest.raises(InventoryError) as e:
        await _karung(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 10)  # 400 kg
    # Kalimatnya menyebut sisanya — yang ditolak tanpa angka akan mencoba lagi
    # dengan tebakan.
    assert "200" in str(e.value), str(e.value)
    # Dan yang MUAT tetap boleh.
    r = await _karung(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 5)  # 200 kg
    assert r.berat_total_kg == 200


async def test_yang_sudah_dikarungi_tak_bisa_dicatat_curah_lagi(pg, sosoh_bekatul):
    """Arah sebaliknya, dan ia ditulis terpisah sebab pagarnya juga terpisah:
    `catat_bekatul` dulu tak punya batas atas SAMA SEKALI."""
    from app.penggilingan.inventory.packaging import InventoryError

    await _karung(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 20)  # 800 kg
    with pytest.raises(InventoryError) as e:
        await _curah(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 400)
    assert "200" in str(e.value), str(e.value)
    assert await _curah(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 200) == 200


async def test_bekatul_yang_dikarungi_tidak_menguap_dari_stok(pg, sosoh_bekatul):
    """Yang paling mudah terlewat, dan paling mahal: bekatul berpindah RUMAH,
    bukan hilang.

    Kartu Stok Produk membaca `byproduct_stock` untuk bekatul. Kalau ia tetap
    membaca itu saja, mengarungi 400 kg menurunkan "belum dicatat" sebesar 400
    tanpa menaikkan apa pun — bekatulnya menguap dari layar, padahal ia berdiri
    di gudang di dalam karung.
    """
    from app.services.stok import stok_produk

    async with pg() as db:
        kartu = {k.jenis: k for k in await stok_produk(db)}
    awal = kartu["bekatul"]
    # Sebelum dibukukan, bekatulnya TETAP terhitung sisa: ia sungguh berdiri di
    # gudang, cuma belum punya rumah di pembukuan. Itu justru sebab halaman ini
    # lahir — barang yang ada tetapi tak terbaca di angka stok mana pun.
    assert awal.hasil_kg == 1_000 and awal.sisa_kg == 1_000, awal
    assert awal.dikemas_kg == 0, awal.dikemas_kg
    assert awal.curah_kg == 1_000, "1.000 kg belum dibukukan, harusnya terbaca"

    await _karung(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 10)  # 400 kg
    await _curah(pg, sosoh_bekatul["user"], sosoh_bekatul["kode"], 600)

    async with pg() as db:
        kartu = {k.jenis: k for k in await stok_produk(db)}
    b = kartu["bekatul"]
    assert b.hasil_kg == 1_000, b.hasil_kg
    assert b.dikemas_kg == 1_000, (
        f"bekatul yang berpindah rumah menguap: cuma {b.dikemas_kg} kg terbaca")
    assert b.curah_kg == 0, f"belum-dicatat harusnya nol: {b.curah_kg}"
    assert b.sisa_kg == 1_000, f"stok bekatul salah: {b.sisa_kg}"


async def test_penyosohan_tanpa_catatan_bekatul_tetap_bisa_mencatat_curah(pg, sosoh_bekatul):
    """Pabrik yang tak menimbang bekatulnya di mesin tidak boleh ikut terkunci.

    Pagar batas-atas hanya berlaku bila hasil bekatulnya MEMANG tercatat pada
    penyosohan itu. Tanpa catatan hasil, packing juga mustahil — jadi tak ada
    jalan kedua yang bisa menggandakan angkanya, dan menolak di sini cuma akan
    mematikan pencatatan yang sudah berjalan bertahun-tahun.
    """
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingProcess

    async with pg() as db:
        p = PolishingProcess(kode_proses="POL-BK-02", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=sosoh_bekatul["user"])
        db.add(p)
        await db.commit()
        kode = p.kode_proses
    # Tak ada satu pun `polishing_output_logs` bekatul untuk proses ini.
    assert await _curah(pg, sosoh_bekatul["user"], kode, 5_000) == 5_000
