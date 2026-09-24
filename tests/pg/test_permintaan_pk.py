"""Operator Gudang 2 MEMINTA lot PK Gudang 1 — bagian kedua keputusan pemilik.

24 September 2026: operator polesan melihat lot PK Gudang 1 dan boleh meminta
satu dipindah; yang mencatat perpindahan tetap Admin. Yang lahir permintaan,
bukan izin — `can_transfer_pk` tidak berubah.

Yang dijaga berkas ini adalah hal-hal yang tak terlihat di layar sampai
seseorang menekannya dua kali: satu permintaan terbuka per lot (dijaga INDEKS,
bukan layar), kematiannya lewat tiga jalan, dan gerbang perannya dua arah.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg):
    """Satu lot giling selesai berisi 6.500 kg PK, satu operator G2, satu admin."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import (MillingProcess, MillingProgressLog, PurchaseBatch, Silo,
                            Supplier, User, Warehouse)
    from app.peran import PERAN_ADMIN_KEATAS
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        silo = (await db.execute(select(Silo).where(
            Silo.warehouse_id == g1.id))).scalars().first()
        if silo is None:
            silo = Silo(nama_silo="Silo Selepan", warehouse_id=g1.id)
            db.add(silo)
            await db.flush()
        op1 = User(nama="Op Selepan", role="operator", status="aktif",
                   default_warehouse_id=g1.id)
        op2 = User(nama="Op Polesan", role="operator", status="aktif",
                   default_warehouse_id=g2.id)
        op2b = User(nama="Op Polesan Dua", role="operator", status="aktif",
                    default_warehouse_id=g2.id)
        adm = User(nama="Admin Uji", role=PERAN_ADMIN_KEATAS[-1], status="aktif")
        s = Supplier(nama_supplier="Pak Tani")
        db.add_all([op1, op2, op2b, adm, s])
        await db.flush()
        b = PurchaseBatch(kode_batch="GB-P2-01", supplier_id=s.id, berat_total_kg=10_000,
                          kondisi_gabah="kering", tanggal_pembelian=date.today(),
                          waktu_pembelian=now_local(), input_by=op1.id,
                          flag_unverified=False, sumber_berat="manual")
        db.add(b)
        await db.flush()
        p = MillingProcess(kode_proses="LOT-P2-01", status="selesai", silo_id=silo.id,
                           berat_gabah_masuk_kg=10_000, waktu_mulai=now_local(),
                           waktu_selesai=now_local(), created_by=op1.id,
                           purchase_batch_id=b.id)
        db.add(p)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=p.id, berat_kumulatif_kg=6_500,
                                  waktu_update=now_local(), input_by=op1.id))
        await db.commit()
        return {"lot": p.kode_proses, "lot_id": p.id, "op2": op2.id,
                "op2b": op2b.id, "adm": adm.id}


async def _minta(pg, uid, kode="LOT-P2-01"):
    from app.models import User
    from app.services.permintaan_pk import minta

    async with pg() as db:
        return await minta(db, user=await db.get(User, uid), kode_proses=kode)


async def test_satu_permintaan_terbuka_per_lot(pg, pabrik):
    """Ditekan dua kali karena halamannya lambat → tetap SATU.

    Pagarnya indeks parsial, bukan pemeriksaan di depan: dua penekanan yang
    tiba bersamaan sama-sama lolos "sudah ada belum?" lalu keduanya menulis.
    """
    from sqlalchemy import func, select

    from app.models import PermintaanPk
    from app.services.permintaan_pk import PermintaanError

    await _minta(pg, pabrik["op2"])
    with pytest.raises(PermintaanError) as e:
        await _minta(pg, pabrik["op2"])
    assert "sudah diminta" in str(e.value)

    # Dan operator LAIN pun tak melahirkan yang kedua.
    with pytest.raises(PermintaanError):
        await _minta(pg, pabrik["op2b"])

    async with pg() as db:
        n = (await db.execute(select(func.count()).select_from(PermintaanPk))).scalar_one()
    assert n == 1


async def test_kartu_admin_muncul_sekali_dan_membawa_pilihannya(pg, pabrik):
    from app.models import User
    from app.services.berjalan import untuk

    await _minta(pg, pabrik["op2"])
    async with pg() as db:
        b = await untuk(db, await db.get(User, pabrik["adm"]))

    kartu = [x for x in b.menunggu if x.kelompok == "permintaan"]
    assert len(kartu) == 1
    k = kartu[0]
    assert k.kode == "LOT-P2-01" and "Op Polesan" in k.isi
    # Dua jalan keluar, dan keduanya milik Admin.
    assert [p[0] for p in k.pilihan] == ["transfer_pk", "tolak_permintaan_pk"]
    # Dicap gudang — kartu tanpa cap lenyap dari ?gudang=g1 DAN ?gudang=g2.
    assert k.gudang == "g1"
    # Dan ia ikut terhitung lencana antrean layar yang menggambarnya.
    assert b.jumlah_menunggu == len(b.menunggu)


async def test_operator_melihat_keadaannya_di_kartu_stok(pg, pabrik):
    """Kartu yang sudah diminta tak menawarkan tombolnya lagi."""
    from app.services.stok import pk_gudang1

    async with pg() as db:
        sebelum = {l.kode: l.diminta_oleh for l in await pk_gudang1(db)}
    assert sebelum["LOT-P2-01"] is None

    await _minta(pg, pabrik["op2"])
    async with pg() as db:
        sesudah = {l.kode: l.diminta_oleh for l in await pk_gudang1(db)}
    assert sesudah["LOT-P2-01"] == "Op Polesan"


async def test_transfer_menutup_permintaannya(pg, pabrik):
    from app.models import PermintaanPk, User
    from app.services.berjalan import untuk
    from app.services.transfer import create_internal_transfer

    baris = await _minta(pg, pabrik["op2"])
    async with pg() as db:
        await create_internal_transfer(db, user=await db.get(User, pabrik["adm"]),
                                       kode_proses="LOT-P2-01", lokasi_tujuan="silo_a")
    async with pg() as db:
        ada = await db.get(PermintaanPk, baris.id)
        assert ada.status == "selesai" and ada.waktu_tutup is not None
        b = await untuk(db, await db.get(User, pabrik["adm"]))
    assert not [x for x in b.menunggu if x.kelompok == "permintaan"], "kartunya tetap berdiri"


async def test_lot_habis_lewat_jalan_lain_menggugurkan_permintaan(pg, pabrik):
    """Dijual langsung, atau terkirim sebagian-sebagian sampai nol. Daftar yang
    memuat pekerjaan yang tak bisa dikerjakan lagi berhenti dibaca orang."""
    from app.database import now_local
    from app.models import OutgoingItem, OutgoingRecord, PermintaanPk, User
    from app.services.berjalan import untuk

    baris = await _minta(pg, pabrik["op2"])
    async with pg() as db:
        rec = OutgoingRecord(kode="OUT-P2-01", tanggal=date.today(),
                             waktu=now_local(), input_by=pabrik["adm"])
        db.add(rec)
        await db.flush()
        db.add(OutgoingItem(outgoing_record_id=rec.id, item_type="pk_langsung",
                            milling_process_id=pabrik["lot_id"], berat_kg=6_500))
        await db.commit()

    async with pg() as db:
        b = await untuk(db, await db.get(User, pabrik["adm"]))
        ada = await db.get(PermintaanPk, baris.id)
    assert not [x for x in b.menunggu if x.kelompok == "permintaan"]
    assert ada.status == "gugur"


async def test_menolak_menuntut_sebab_dan_terbaca_operator(pg, pabrik):
    from app.models import User
    from app.services.permintaan_pk import PermintaanError, tolak
    from app.services.stok import pk_gudang1

    baris = await _minta(pg, pabrik["op2"])
    async with pg() as db:
        adm = await db.get(User, pabrik["adm"])
        with pytest.raises(PermintaanError):
            await tolak(db, user=adm, permintaan_id=baris.id, sebab="   ")
        r = await tolak(db, user=adm, permintaan_id=baris.id,
                        sebab="Lot ini sudah dijanjikan pembeli.")
    assert r.status == "ditolak" and "pembeli" in r.sebab

    # Kartunya hilang dari layar Admin, dan lotnya boleh diminta LAGI besok.
    async with pg() as db:
        lot = {l.kode: l.diminta_oleh for l in await pk_gudang1(db)}
    assert lot["LOT-P2-01"] is None
    await _minta(pg, pabrik["op2"])


async def test_lot_yang_sudah_habis_tak_bisa_diminta(pg, pabrik):
    from app.models import User
    from app.services.permintaan_pk import PermintaanError
    from app.services.transfer import create_internal_transfer

    async with pg() as db:
        await create_internal_transfer(db, user=await db.get(User, pabrik["adm"]),
                                       kode_proses="LOT-P2-01", lokasi_tujuan="silo_a")
    with pytest.raises(PermintaanError) as e:
        await _minta(pg, pabrik["op2"])
    assert "habis" in str(e.value)
