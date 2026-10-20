"""Pilihan packing hasil samping tetap ada walau karung bekas disembunyikan."""
import pytest
from tests.pg.test_grup_packing_jasa import empat_jenis
from tests.pg.test_pindah_kepemilikan_produk import titipan, _klien

pytestmark = pytest.mark.asyncio


async def test_picker_bekas_tanpa_mengubah_antrean(pg, empat_jenis):
    from app.services.stok import beras_curah
    async with await _klien(pg, peran="superadmin") as c:
        r = await c.get("/api/actions/beras-belum-dikemas",
                        params={"jenis": "bekatul", "pemilik": "pabrik"})
        assert r.status_code == 200
        assert [(o["value"], o["berat_kg"]) for o in r.json()] == [
            (empat_jenis["kode"] + "|bekatul", 300)]
        kemasan = await c.get("/api/actions/kemasan-untuk",
                             params={"induk": r.json()[0]["value"]})
        assert {o["value"] for o in kemasan.json()} == {"bekas|20", "bekas|40"}
        stok = await c.get("/stok-karung")
        assert "karung bekas" not in stok.text.lower()
    async with pg() as db:
        assert [b.jenis for b in await beras_curah(db)] == ["medium"]


async def test_packing_bekas_saldo_diperiksa_ulang(pg, empat_jenis, pemakai):
    from app.penggilingan.inventory.finished_goods import catat_packing, InventoryError
    from app.services.stok import hasil_samping_bisa_dikemas, stok_produk
    async with pg() as db:
        sebelum = next(k.sisa_kg for k in await stok_produk(db) if k.jenis == "bekatul")
        await catat_packing(db, user=pemakai, kode_pol=empat_jenis["kode"],
                           kategori="bekatul", material_kode="bekas", ukuran=40,
                           jumlah_karung=7)
        pilihan = await hasil_samping_bisa_dikemas(db)
        assert next(b.sisa_kg for b in pilihan if b.jenis == "bekatul") == 20
        assert next(k.sisa_kg for k in await stok_produk(db) if k.jenis == "bekatul") == sebelum
        with pytest.raises(InventoryError, match="tinggal 20 kg"):
            await catat_packing(db, user=pemakai, kode_pol=empat_jenis["kode"],
                               kategori="bekatul", material_kode="bekas", ukuran=40,
                               jumlah_karung=1)
        await db.rollback()


async def test_pemilik_bekatul_jasa_dan_hasil_ditahan(pg, titipan):
    from app.models import Jasa, PolishingOutputLog
    from app.database import now_local
    async with pg() as db:
        db.add(PolishingOutputLog(polishing_process_id=1, jenis="bekatul",
                                 berat_kg=300, waktu_update=now_local(),
                                 input_by=titipan["user"]))
        await db.commit()
    async with await _klien(pg, peran="superadmin") as c:
        async def pilihan(owner):
            return (await c.get("/api/actions/beras-belum-dikemas",
                    params={"jenis":"bekatul", "pemilik":str(owner)})).json()
        assert await pilihan("pabrik") == []
        assert len(await pilihan(titipan["jasa1"])) == 1
        async with pg() as db:
            j = await db.get(Jasa, titipan["jasa1"])
            j.hasil_ditahan = "sekam,bekatul"
            await db.commit()
        # Bekatul jasa tetap milik pelanggan sampai transfer eksplisit.
        assert len(await pilihan(titipan["jasa1"])) == 1
        assert await pilihan("pabrik") == []


async def test_barang_sudah_keluar_tidak_dikemas_lagi(pg, empat_jenis, pemakai):
    from datetime import date
    from app.models import OutgoingRecord, OutgoingItem
    from app.database import now_local
    from app.services.stok import hasil_samping_bisa_dikemas
    from app.penggilingan.inventory.finished_goods import catat_packing, InventoryError
    async with pg() as db:
        rec = OutgoingRecord(kode="OUT-UJI-BEKAS", tanggal=date.today(),
                             waktu=now_local(), input_by=pemakai.id, status="selesai")
        db.add(rec)
        await db.flush()
        db.add(OutgoingItem(outgoing_record_id=rec.id, item_type="byproduct_curah",
                            jenis_byproduct="bekatul", berat_kg=280))
        await db.commit()
        assert next(b.sisa_kg for b in await hasil_samping_bisa_dikemas(db)
                    if b.jenis == "bekatul") == 20
        with pytest.raises(InventoryError, match="tinggal 20 kg"):
            await catat_packing(db, user=pemakai, kode_pol=empat_jenis["kode"],
                               kategori="bekatul", material_kode="bekas", ukuran=40,
                               jumlah_karung=1)
        await db.rollback()


async def test_dua_operator_tidak_memakai_saldo_bekatul_yang_sama(pg, empat_jenis, pemakai):
    import asyncio
    from app.penggilingan.inventory.finished_goods import catat_packing, InventoryError
    from app.services.stok import hasil_samping_bisa_dikemas

    async def kemas():
        async with pg() as db:
            try:
                await catat_packing(db, user=pemakai, kode_pol=empat_jenis["kode"],
                                   kategori="bekatul", material_kode="bekas",
                                   ukuran=40, jumlah_karung=5)
                return True
            except InventoryError:
                await db.rollback()
                return False
    assert sorted(await asyncio.gather(kemas(), kemas())) == [False, True]
    async with pg() as db:
        assert next(b.sisa_kg for b in await hasil_samping_bisa_dikemas(db)
                    if b.jenis == "bekatul") == 100
