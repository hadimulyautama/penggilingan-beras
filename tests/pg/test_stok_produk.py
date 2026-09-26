"""Stok Produk — beras yang sudah keluar mesin akhirnya punya rumah.

Temuan QA 26 September 2026: beras yang keluar dari mesin sosoh tidak ada di
angka stok mana pun. `polishing_output_logs` dibaca tepat dua tempat di seluruh
repo, dan tak satu pun layar stok membacanya — beras baru MENJADI stok ketika
seseorang menjalankan "Catat packing". Di pabrik, jarak antara "sosoh selesai"
dan "packing dicatat" adalah jam, kadang hari; sepanjang waktu itu berton-ton
beras berdiri di lantai sementara aplikasi menyebut stoknya nol.

Keputusan pemilik: halaman "Stok Produk" sendiri, dan kartu hasil sosoh di
situ. Aksesnya semua orang KECUALI operator Gudang 1.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sosoh(pg, pemakai, pemasok):
    """Satu penyosohan SELESAI: 9.000 kg medium, belum dipacking sama sekali."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Silo, User, Warehouse
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
        silo = (await db.execute(select(Silo).where(
            Silo.warehouse_id == g2.id))).scalars().first()
        if silo is None:
            silo = Silo(nama_silo="Silo A", warehouse_id=g2.id)
            db.add(silo)
            await db.flush()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        p = PolishingProcess(kode_proses="POL-UJI-01", status="selesai",
                             waktu_mulai=now_local(), waktu_selesai=now_local(),
                             created_by=u.id)
        db.add(p)
        await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id, silo_id=silo.id,
                                  berat_awal_kg=10_000, berat_akhir_kg=0,
                                  berat_terpakai_kg=10_000))
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="medium",
                                  berat_kg=9_000, waktu_update=now_local(),
                                  input_by=u.id))
        await db.commit()
        return {"user": u.id, "kode": p.kode_proses, "proses_id": p.id}


async def test_beras_muncul_tanpa_perlu_dipacking_dulu(pg, sosoh):
    """Inti keluhannya. Sebelum ini: tak ada satu layar pun yang menyebutnya."""
    from app.services.stok import beras_curah

    async with pg() as db:
        baris = await beras_curah(db)
    assert len(baris) == 1, baris
    b = baris[0]
    assert b.kode_proses == "POL-UJI-01" and b.jenis == "medium"
    assert b.keluar_kg == 9_000 and b.dikemas_kg == 0 and b.sisa_kg == 9_000
    assert not b.berjalan


async def test_packing_memindahkan_bukan_menciptakan(pg, sosoh):
    """Sesudah dipacking sebagian: curah berkurang sebanyak itu, barang jadi
    bertambah sebanyak itu, dan jumlah keduanya tetap."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.stok import barang_jadi_g2, beras_curah

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        await catat_packing(db, user=u, kode_pol=sosoh["kode"],
                            kategori="beras_putih", grade="medium",
                            material_kode="biasa", ukuran=25,
                            jumlah_karung=100)          # 2.500 kg

    async with pg() as db:
        curah = await beras_curah(db)
        bj = await barang_jadi_g2(db)
    b = curah[0]
    assert b.dikemas_kg == 2_500 and b.sisa_kg == 6_500
    dikemas = sum(k["kg"] for k in bj.produk)
    assert dikemas == 2_500
    # Jumlah keduanya tetap: tak ada beras yang lahir atau lenyap.
    assert b.sisa_kg + dikemas == 9_000


async def test_packing_melebihi_curah_ditolak_dengan_angkanya(pg, sosoh):
    """Pagar yang sampai hari ini MUSTAHIL: tanpa angka asal, tak ada yang
    bisa dilanggar. Yang ada cuma peringatan sesudah commit."""
    from app.models import User
    from app.penggilingan.inventory.finished_goods import InventoryError, catat_packing

    async with pg() as db:
        u = await db.get(User, sosoh["user"])
        with pytest.raises(InventoryError) as e:
            await catat_packing(db, user=u, kode_pol=sosoh["kode"],
                                kategori="beras_putih", grade="medium",
                                material_kode="biasa", ukuran=25,
                                jumlah_karung=400)      # 10.000 kg > 9.000
    pesan = str(e.value)
    assert "9.000" in pesan and "10.000" in pesan, pesan

    # Dan tak ada yang tertulis: penolakannya SEBELUM menulis.
    from app.services.stok import barang_jadi_g2

    async with pg() as db:
        assert (await barang_jadi_g2(db)).produk == []


async def test_dua_jenis_dari_satu_proses_tak_saling_menimpa(pg, sosoh):
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.services.stok import beras_curah

    async with pg() as db:
        db.add(PolishingOutputLog(polishing_process_id=sosoh["proses_id"],
                                  jenis="premium", berat_kg=1_200,
                                  waktu_update=now_local(), input_by=sosoh["user"]))
        await db.commit()
    async with pg() as db:
        baris = {b.jenis: b.sisa_kg for b in await beras_curah(db)}
    assert baris == {"medium": 9_000, "premium": 1_200}


async def test_proses_yang_masih_berjalan_ditandai_belum_final(pg, sosoh):
    """Kartu penyosohan sudah jujur soal ini; blok stok yang menyebutnya
    seolah pasti akan membuat orang mengemas dua kali."""
    from sqlalchemy import select

    from app.models import User
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.services.berjalan import untuk_operator_gudang2
    from app.services.stok import beras_curah

    async with pg() as db:
        p = (await db.execute(select(PolishingProcess))).scalars().one()
        p.status = "proses"
        p.waktu_selesai = None
        await db.commit()

    async with pg() as db:
        baris = await beras_curah(db)
        tanpa = await beras_curah(db, termasuk_berjalan=False)
        b = await untuk_operator_gudang2(db)
    assert len(baris) == 1 and baris[0].berjalan, "tak ditandai belum final"
    assert tanpa == [], "yang berjalan ikut ke daftar yang meminta yang final"
    # Dan ia TIDAK berkartu antrean: menagih pekerjaan atas angka yang masih
    # akan berubah membuat orang mengemas dua kali.
    assert not [x for x in b.menunggu if x.kelompok == "produk"]


async def test_kartu_antrean_dan_lencana_untuk_yang_sudah_selesai(pg, sosoh):
    """Halaman yang harus dibuka sendiri tak menjawab keluhan pemilik: yang
    hilang selama ini KABARNYA, bukan tempat menyimpannya."""
    from app.services.berjalan import untuk_operator_gudang2

    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    kartu = [x for x in b.menunggu if x.kelompok == "produk"]
    assert len(kartu) == 1, b.menunggu
    assert kartu[0].aksi == "catat_packing" and "9.000" in kartu[0].isi
    assert b.jumlah_produk == 1
    assert b.lencana()["PRODUK"] == 1


async def test_pintu_tertutup_hanya_bagi_operator_gudang1(pg, sosoh, pemasok):
    """Keputusan pemilik 26 September 2026: semua boleh, kecuali operator
    Gudang 1 — produknya sendiri (PK) sudah berkartu di layar Stok."""
    from sqlalchemy import select

    from app.models import User, Warehouse
    from app.services.berjalan import untuk

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
            await db.flush()
        op1 = User(nama="Operator Selepan", role="operator", status="aktif",
                   default_warehouse_id=g1.id)
        adm = User(nama="Admin Produk", role="admin", status="aktif")
        db.add_all([op1, adm])
        await db.commit()
        await db.refresh(op1)
        await db.refresh(adm)

    async with pg() as db:
        b1 = await untuk(db, await db.get(User, op1.id))
        b2 = await untuk(db, await db.get(User, adm.id))
        b3 = await untuk(db, await db.get(User, sosoh["user"]))
    assert "stok_produk" in b1.lencana()["PINTU_MATI"], "operator G1 ditawari pintunya"
    assert "stok_produk" not in b2.lencana()["PINTU_MATI"], "Admin kehilangan pintunya"
    assert "stok_produk" not in b3.lencana()["PINTU_MATI"], "operator G2 kehilangan pintunya"
    # Lencananya ikut sampai ke Admin, bukan cuma ke yang mengerjakannya.
    assert b2.lencana()["PRODUK"] == 1
