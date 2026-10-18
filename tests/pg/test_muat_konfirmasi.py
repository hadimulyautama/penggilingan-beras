"""Konfirmasi memakai perintah terbaru; perubahan target tidak mengubah aktual."""
import pytest
from sqlalchemy import select
from app.models import User, ActivityLog
from app.services import barang_keluar as bk
from app.penggilingan.inventory.models import OutgoingItem, OutgoingRecord, OUT_PERINTAH
from tests.pg.test_barang_keluar import gudang, _perintah, _stok, _undo


async def cuplikan(pg, rid):
    async with pg() as db:
        return await bk.ringkasan_muat(db, await db.get(OutgoingRecord, rid))


async def test_lengkapi_80_ke_100_stok_selisih_dan_undo_ke_80(pg, gudang):
    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.catat_muatan(db, user=await db.get(User, gudang['op']),
                              item_id=r.baris[0].id, jumlah_karung=80)
    awal = await cuplikan(pg, r.rec.id)
    assert awal['baris'][0]['sisa'] == 20
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang['op']),
                            rec_id=r.rec.id, dasar=awal['dasar'])
    assert await _stok(pg, gudang) == 7500
    await _undo(pg, gudang['op'])
    assert await _stok(pg, gudang) == 8000
    assert (await cuplikan(pg, r.rec.id))['baris'][0]['dimuat'] == 80


async def test_perintah_berubah_tahan_konfirmasi_lama(pg, gudang):
    r = await _perintah(pg, gudang, karung=100)
    awal = await cuplikan(pg, r.rec.id)
    async with pg() as db:
        await bk.tambah_baris(db, user=await db.get(User, gudang['adm']), rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe='finished_goods', sku_id=gudang['sku'],
                                   std_id=gudang['std'], jumlah_karung=20))
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError, match='berubah sejak diperiksa'):
            await bk.muat_semua(db, user=await db.get(User, gudang['op']),
                                rec_id=r.rec.id, dasar=awal['dasar'])
    assert await _stok(pg, gudang) == 10000
    terbaru = await cuplikan(pg, r.rec.id)
    assert terbaru['baris'][0]['perintah'] == 120
    assert terbaru['baris'][0]['dimuat'] == 0


async def test_muatan_kurang_wajib_alasan_tidak_dilengkapi_otomatis(pg, gudang):
    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.catat_muatan(db, user=await db.get(User, gudang['op']),
                              item_id=r.baris[0].id, jumlah_karung=80)
    awal = await cuplikan(pg, r.rec.id)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError, match='alasan'):
            await bk.selesai_muat(db, user=await db.get(User, gudang['op']),
                                  rec_id=r.rec.id, dasar=awal['dasar'])
    async with pg() as db:
        await bk.selesai_muat(db, user=await db.get(User, gudang['op']), rec_id=r.rec.id,
                              dasar=awal['dasar'], sebab='Stok fisik kurang 20 karung')
    assert await _stok(pg, gudang) == 8000
    async with pg() as db:
        log = (await db.execute(select(ActivityLog).where(
            ActivityLog.record_id == r.rec.id, ActivityLog.aksi == 'barang_keluar_muat'))).scalars().one()
        assert 'Stok fisik kurang' in log.new_value


async def test_tambah_setelah_dimuat_membuka_tugas_tanpa_mengubah_aktual(pg, gudang):
    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang['op']), rec_id=r.rec.id)
        await bk.tambah_baris(db, user=await db.get(User, gudang['adm']), rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe='finished_goods', sku_id=gudang['sku'],
                                   std_id=gudang['std'], jumlah_karung=20))
    assert await _stok(pg, gudang) == 7500
    async with pg() as db:
        rec = await db.get(OutgoingRecord, r.rec.id)
        assert rec.status == OUT_PERINTAH
        ringkas = await bk.ringkasan_muat(db, rec)
        assert ringkas['baris'][0]['dimuat'] == 100
        assert ringkas['baris'][0]['sisa'] == 20


async def test_dua_operator_konfirmasi_cuplikan_sama_hanya_satu_berhasil(pg, gudang):
    import asyncio
    r = await _perintah(pg, gudang, karung=100)
    awal = await cuplikan(pg, r.rec.id)
    async def simpan():
        async with pg() as db:
            try:
                await bk.muat_semua(db, user=await db.get(User, gudang['op']),
                                    rec_id=r.rec.id, dasar=awal['dasar'])
                return True
            except bk.BarangKeluarError:
                return False
    assert sorted(await asyncio.gather(simpan(), simpan())) == [False, True]
    assert await _stok(pg, gudang) == 7500


async def test_konfirmasi_aktual_basi_ditolak_dan_perintah_bermuatan_tidak_bisa_dibatalkan(pg, gudang):
    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.catat_muatan(db, user=await db.get(User, gudang['op']),
                              item_id=r.baris[0].id, jumlah_karung=80)
    awal = await cuplikan(pg, r.rec.id)
    async with pg() as db:
        await bk.catat_muatan(db, user=await db.get(User, gudang['op']),
                              item_id=r.baris[0].id, jumlah_karung=90)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError, match='berubah sejak diperiksa'):
            await bk.selesai_muat(db, user=await db.get(User, gudang['op']),
                rec_id=r.rec.id, dasar=awal['dasar'], sebab='Kurang')
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError, match='Sudah ada barang dimuat'):
            await bk.batalkan(db, user=await db.get(User, gudang['adm']),
                               rec_id=r.rec.id, sebab='Batal')
    assert await _stok(pg, gudang) == 7750


async def test_api_mewajibkan_pratinjau_dan_menolak_cuplikan_basi(pg, gudang):
    from tests.pg.test_barang_keluar import _klien
    from app.web import csrf
    r = await _perintah(pg, gudang, karung=100)
    c = await _klien(pg, gudang['op'], 'uji_muat7_op', mode='operator')
    async with c:
        headers = {'X-CSRF-Token': c.cookies.get(csrf.NAMA_COOKIE)}
        resp = await c.post('/api/actions/muat-semua', json={'perintah':str(r.rec.id)}, headers=headers)
        assert resp.status_code == 409, resp.text
        resp = await c.get('/api/actions/pratinjau-muat', params={'perintah':r.rec.id})
        assert resp.status_code == 200, resp.text
        awal = resp.json()
        assert 'sisa 100 karung' in awal['teks']
        async with pg() as db:
            await bk.tambah_baris(db, user=await db.get(User, gudang['adm']), rec_id=r.rec.id,
                baris=bk.BarisPerintah(tipe='finished_goods', sku_id=gudang['sku'],
                                       std_id=gudang['std'], jumlah_karung=20))
        resp = await c.post('/api/actions/muat-semua',
            json={'perintah':str(r.rec.id),'dasar':awal['dasar']}, headers=headers)
        assert resp.status_code == 409, resp.text
        assert 'berubah sejak diperiksa' in resp.text
        resp = await c.get('/api/actions/pratinjau-muat', params={'perintah':r.rec.id})
        terbaru = resp.json()
        assert terbaru['baris'][0]['sisa'] == 120
        resp = await c.post('/api/actions/muat-semua',
            json={'perintah':str(r.rec.id),'dasar':terbaru['dasar']}, headers=headers)
        assert resp.status_code == 200, resp.text
    assert await _stok(pg, gudang) == 7000


async def test_api_pratinjau_admin_tetap_boleh_sesuai_wewenang_gudang(pg, gudang):
    from tests.pg.test_barang_keluar import _klien
    r = await _perintah(pg, gudang)
    c = await _klien(pg, gudang['adm'], 'uji_muat7_admin')
    async with c:
        resp = await c.get('/api/actions/pratinjau-muat', params={'perintah':r.rec.id})
        assert resp.status_code == 200


async def test_muat_semua_hanya_memerlukan_stok_sisa_20_karung(pg, gudang):
    r = await _perintah(pg, gudang, karung=100)
    lain = await _perintah(pg, gudang, karung=300, pembeli='Toko lain')
    async with pg() as db:
        op = await db.get(User, gudang['op'])
        await bk.catat_muatan(db, user=op, item_id=r.baris[0].id, jumlah_karung=80)
        await bk.muat_semua(db, user=op, rec_id=lain.rec.id)
    assert await _stok(pg, gudang) == 500  # Tepat 20 karung tersisa.
    awal = await cuplikan(pg, r.rec.id)
    async with pg() as db:
        await bk.muat_semua(db, user=await db.get(User, gudang['op']),
                            rec_id=r.rec.id, dasar=awal['dasar'])
    assert await _stok(pg, gudang) == 0


async def test_stok_tidak_cukup_tidak_mengarang_muatan(pg, gudang):
    from app.penggilingan.inventory.models import FinishedGoodsStock
    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        await bk.catat_muatan(db, user=await db.get(User, gudang['op']),
                              item_id=r.baris[0].id, jumlah_karung=80)
        stok = (await db.execute(select(FinishedGoodsStock))).scalars().one()
        stok.jumlah_karung, stok.berat_total_kg = 90, 2250
        await db.commit()
    awal = await cuplikan(pg, r.rec.id)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError, match='tak cukup'):
            await bk.muat_semua(db, user=await db.get(User, gudang['op']),
                                rec_id=r.rec.id, dasar=awal['dasar'])
    assert (await cuplikan(pg, r.rec.id))['baris'][0]['dimuat'] == 80


async def test_tambah_jenis_baru_setelah_dimuat_tetap_nol_sampai_dikonfirmasi(pg, gudang):
    from tests.pg.test_barang_keluar import _bekatul_curah
    await _bekatul_curah(pg, gudang, 1000)
    r = await _perintah(pg, gudang, karung=100)
    async with pg() as db:
        op = await db.get(User, gudang['op'])
        await bk.muat_semua(db, user=op, rec_id=r.rec.id)
        await bk.tambah_baris(db, user=await db.get(User, gudang['adm']), rec_id=r.rec.id,
            baris=bk.BarisPerintah(tipe='byproduct_curah', jenis='bekatul', berat_kg=20))
    awal = await cuplikan(pg, r.rec.id)
    assert len(awal['baris']) == 2
    assert awal['baris'][1]['dimuat'] == 0
    assert awal['baris'][1]['sisa'] == 20
    async with pg() as db:
        hasil = await bk.muat_semua(db, user=await db.get(User, gudang['op']),
                                    rec_id=r.rec.id, dasar=awal['dasar'])
        assert [float(i.berat_kg) for i in hasil.baris] == [2500, 20]
