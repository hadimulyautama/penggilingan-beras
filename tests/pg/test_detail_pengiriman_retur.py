"""Panel memindahkan data; transaksi tetap layanan lama dan GET tidak menulis stok."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select
from app.models import CustomerReturn, FinishedGoodsStock, OutgoingRecord, User
from app.penggilingan.inventory.models import ReturRincian
from tests.pg.test_barang_keluar import gudang, _klien, _perintah, _stok
from tests.pg.test_retur_pengajuan import asal, simpan, selesai, terima

pytestmark=pytest.mark.asyncio

async def potret(c,url,nama):
    folder=Path(os.environ['BUKTI_DETAIL_KIRIM']) if os.environ.get('BUKTI_DETAIL_KIRIM') else None
    for tab in ('ringkasan','barang','tiket','riwayat'):
        r=await c.get(url,params={'tab_detail':tab})
        assert r.status_code==200,r.text
        assert r.text.count('role="tab"')==4
        assert f'id="tab-{tab}" aria-controls="panel-{tab}" aria-selected="true"' in r.text
        if folder:
            folder.mkdir(parents=True,exist_ok=True)
            (folder/f'{nama}-{tab}.html').write_text(r.text)
    return r

async def test_pengiriman_semua_tab_tanpa_perubahan_stok(pg,gudang):
    from app.services import barang_keluar as bk
    r=await _perintah(pg,gudang,karung=100)
    async with await _klien(pg,gudang['adm'],'detail_kirim_admin') as c:
        await potret(c,f'/barang-keluar/{r.rec.id}','pengiriman-perintah')
        kembali=await c.get(f'/barang-keluar/{r.rec.id}',params={'kembali_kerja':'/pekerjaan?tab=tindakan&jenis=muat'})
        assert 'href="/pekerjaan?tab=tindakan&amp;jenis=muat"' in kembali.text
        luar=await c.get(f'/barang-keluar/{r.rec.id}',params={'kembali_kerja':'https://contoh.invalid'})
        assert 'href="https://contoh.invalid"' not in luar.text
        assert await _stok(pg,gudang)==10000
        async with pg() as db:
            await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=r.rec.id)
        html=await potret(c,f'/barang-keluar/{r.rec.id}','pengiriman-dimuat')
        assert 'buka=verifikasi_keluar' in html.text
        assert 'buka=muat_semua' not in html.text
        assert await _stok(pg,gudang)==7500
        async with pg() as db:
            await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=r.rec.id)
        await potret(c,f'/barang-keluar/{r.rec.id}','pengiriman-selesai')
        assert await _stok(pg,gudang)==7500
    async with await _klien(pg,gudang['op'],'detail_kirim_operator') as c:
        html=await potret(c,f'/barang-keluar/{r.rec.id}','pengiriman-operator')
        assert f'/barang-keluar/{r.rec.id}/retur' not in html.text

async def test_retur_tab_manual_snapshot_dan_get_tidak_menerima(pg,asal):
    c=await _klien(pg,asal['uid'],'detail_retur_admin')
    async with c:
        await potret(c,f'/barang-keluar/{asal["oid"]}/retur','retur-baru')
        if os.environ.get('BENIH_DETAIL_KIRIM'):
            Path('/tmp/kirim-retur-session.json').write_text(json.dumps({'cookies':{x.name:x.value for x in c.cookies.jar},'url':f'/barang-keluar/{asal["oid"]}/retur','tiket':asal['tiket'][0],'item':asal['iid']}))
            return
        r=await simpan(pg,asal,9)
        html=await potret(c,f'/retur/pengajuan/{r.id}','retur-menunggu')
        assert 'Menunggu timbang kedua' in html.text
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(CustomerReturn))==0
        await selesai(pg,asal)
        # Pembukaan tab tidak memanggil periksa_dan_terima.
        await potret(c,f'/retur/pengajuan/{r.id}','retur-menunggu-tiket-selesai')
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(CustomerReturn))==0
        assert await terima(pg,r.id) is None
        await potret(c,f'/retur/pengajuan/{r.id}','retur-perlu-koreksi')
        await simpan(pg,asal,10,pengajuan_id=r.id,alasan='Satu karung tertinggal dari rincian.')
        await potret(c,f'/retur/pengajuan/{r.id}','retur-siap-manual')
        token=(await c.get('/api/sesi-formulir')).json()['token']
        response=await c.post(f'/retur/pengajuan/{r.id}/verifikasi',data={'_csrf':token})
        assert response.status_code==303
        await potret(c,response.headers['location'],'retur-diterima')
        await potret(c,f'/retur/pengajuan/{r.id}','retur-pengajuan-terkunci')
        for _ in range(2):
            await c.post(f'/retur/pengajuan/{r.id}/verifikasi',data={'_csrf':token})
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(CustomerReturn))==1
            assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==1
            receipt=await db.scalar(select(CustomerReturn))
            assert receipt.berat_rincian_kg==250 and receipt.berat_tiket_kg==250
            assert (await db.get(OutgoingRecord,asal['oid'])).status=='selesai'

async def test_batal_tab_tetap_terkunci_tanpa_stok(pg,asal):
    r=await simpan(pg,asal,10)
    async with await _klien(pg,asal['uid'],'detail_retur_batal') as c:
        token=(await c.get('/api/sesi-formulir')).json()['token']
        assert (await c.post(f'/retur/pengajuan/{r.id}/batalkan',data={'_csrf':token,'alasan':'Barang tidak jadi kembali.'})).status_code==303
        html=await potret(c,f'/retur/pengajuan/{r.id}','retur-dibatalkan')
        assert 'fieldset disabled' in html.text
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(CustomerReturn))==0
            assert (await db.get(ReturRincian,r.id)).status_pemeriksaan=='dibatalkan'

async def test_batas_tara_snapshot_dan_tiket_sekarang_terpisah(pg,asal):
    from sqlalchemy import text
    await selesai(pg,asal,251) # 10 karung × tara .10: batas inklusif +1.
    r=await simpan(pg,asal,10)
    receipt=await terima(pg,r.id)
    assert receipt and receipt.berat_rincian_kg==250 and receipt.berat_tiket_kg==251
    async with await _klien(pg,asal['uid'],'detail_retur_otomatis') as c:
        await potret(c,f'/retur/{receipt.id}','retur-otomatis')
        async with pg() as db:
            await db.execute(text('UPDATE timbangan_transaksi SET berat_barang_kg=261 WHERE id=:id'),{'id':asal['tiket'][0]})
            await db.commit()
        html=await potret(c,f'/retur/{receipt.id}','retur-snapshot-tiket-berubah')
        assert '251' in html.text and '261' in html.text
        async with pg() as db:
            assert (await db.get(CustomerReturn,receipt.id)).berat_tiket_kg==251
            assert await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg)))==250

async def test_tara_tidak_sah_tertahan_dan_tampil(pg,asal):
    from app.models import KemasanTara
    from sqlalchemy import delete
    await selesai(pg,asal)
    async with pg() as db:
        await db.execute(delete(KemasanTara));await db.commit()
    r=await simpan(pg,asal,10)
    assert await terima(pg,r.id) is None
    async with await _klien(pg,asal['uid'],'detail_retur_tara') as c:
        html=await potret(c,f'/retur/pengajuan/{r.id}','retur-tara-belum-sah')
        assert 'tara kemasan belum lengkap atau tidak sah' in html.text
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(CustomerReturn))==0
