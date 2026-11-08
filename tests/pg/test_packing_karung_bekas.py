"""Hasil samping otomatis; master kemasan dan data historis tetap tersedia."""
import pytest
from sqlalchemy import select, func
from app.models import FinishedGoodsStock, PolishingOutputLog, PolishingProcess, User
from app.services.stok import stok_produk
from tests.pg.test_grup_packing_jasa import empat_jenis, _klien
from tests.pg.packing_historis import siapkan_packing_historis


@pytest.mark.parametrize('jenis,ukuran,material', [('broken',50,'putih'),('menir',50,'putih'),('reject',50,'bekas'),('bekatul',40,'bekas')])
@pytest.mark.parametrize('historis', [False, True])
async def test_otomatis_sisa_curah_hasil_berubah_dan_riwayat_tidak_ganda(pg, empat_jenis, pemakai, jenis, ukuran, material, historis):
    async with pg() as db:
        proc = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == empat_jenis['kode']))
        proc.status, proc.waktu_selesai = 'proses', None
        log = await db.scalar(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id == proc.id, PolishingOutputLog.jenis == jenis))
        log.berat_kg = 3*ukuran+17
        await db.commit()
        if historis:
            await siapkan_packing_historis(db,user=await db.get(User,pemakai.id),kode_pol=proc.kode_proses,kategori=jenis,material_kode=material,ukuran=ukuran,jumlah_karung=1)
        async def kartu(): return next(k for k in await stok_produk(db) if k.jenis == jenis)
        k = await kartu()
        assert (k.sisa_kg,k.jumlah_karung_otomatis,k.curah_otomatis_kg)==(3*ukuran+17,3,17)
        assert k.belum_final_kg == 3*ukuran+17
        # Koreksi hasil memperbarui tampilan virtual tanpa transaksi pengganti.
        log.berat_kg = 4*ukuran+9
        await db.commit()
        k = await kartu()
        assert (k.sisa_kg,k.jumlah_karung_otomatis,k.curah_otomatis_kg)==(4*ukuran+9,4,9)
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==int(historis)
    async with await _klien(pg,peran='superadmin') as c:
        detail=await c.get('/stok-produk/detail',params={'jenis':jenis})
        assert detail.status_code==200
        assert 'buka=catat_packing' not in detail.text
        assert (await c.get('/api/actions/beras-belum-dikemas',params={'jenis':jenis})).json()==[]


async def test_pengeluaran_mengurangi_saldo_otomatis_sekali(pg,empat_jenis,pemakai):
    from app.models import OutgoingRecord, OutgoingItem
    from app.database import now_local
    async with pg() as db:
        rec=OutgoingRecord(kode='OUT-AUTO-UJI',tanggal=now_local().date(),waktu=now_local(),input_by=pemakai.id,status='selesai')
        db.add(rec);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=rec.id,item_type='byproduct_curah',jenis_byproduct='bekatul',berat_kg=237))
        await db.commit()
        k=next(k for k in await stok_produk(db) if k.jenis=='bekatul')
        assert (k.sisa_kg,k.jumlah_karung_otomatis,k.curah_otomatis_kg)==(63,1,23)
