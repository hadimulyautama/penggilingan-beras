"""Perjalanan terbaca sekali; saldo/ID retur dan portal tetap per pelanggan."""
from decimal import Decimal
from types import SimpleNamespace
import re
import pytest
from sqlalchemy import select,func,text
from app.models import OutgoingRecord,OutgoingItem,KirimanKeluar,Pelanggan,User,ActivityLog,CustomerReturn,CustomerReturnItem,Jasa
from app.database import now_local
from app.services import barang_keluar as bk,retur_pengajuan as ret
from app.web.riwayat_kiriman import baca
from tests.pg.test_retur_pengajuan import asal,simpan,selesai,terima
from tests.pg.test_barang_keluar import _klien
pytestmark=pytest.mark.asyncio

async def gabung(pg,a):
    async with pg() as db:
        now=now_local();other=Pelanggan(nama_pelanggan='Rahasia pelanggan kedua');db.add(other);await db.flush()
        k=KirimanKeluar(no_polisi='B UJI 474',nama_ekspedisi='Ekspedisi Uji');db.add(k);await db.flush()
        first=await db.get(OutgoingRecord,a['oid']);first.kiriman_id=k.id
        first.nama_pembeli='Pelanggan pertama';first.catatan_perintah='Pisahkan pesanan pertama'
        first.waktu_perintah=now;first.diperintah_oleh=a['uid']
        second=OutgoingRecord(kode='OUT-UJI-KEDUA',pelanggan_id=other.id,nama_pembeli=other.nama_pelanggan,kiriman_id=k.id,status='selesai',tanggal=now.date(),waktu=now,input_by=a['uid'])
        db.add(second);await db.flush()
        source=await db.get(OutgoingItem,a['iid']);source.berat_perintah_kg=600;source.jumlah_karung_perintah=24
        i=OutgoingItem(outgoing_record_id=second.id,item_type='finished_goods',product_sku_id=source.product_sku_id,jumlah_karung=4,berat_kg=100,berat_perintah_kg=150,jumlah_karung_perintah=6)
        zero=OutgoingItem(outgoing_record_id=first.id,item_type='byproduct_curah',jenis_byproduct='bekatul',berat_kg=0,berat_perintah_kg=25)
        db.add_all([i,zero]);await db.commit();return second.id,i.id,k.id

async def test_detail_satu_perjalanan_banyak_item_dan_tautan_perintah_lama(pg,asal):
    oid,iid,kid=await gabung(pg,asal)
    async with await _klien(pg,asal['uid'],'riwayat474') as c:
        for rid in [asal['oid'],oid]:
            page=await c.get(f'/barang-keluar/{rid}');assert page.status_code==200,page.text
            assert page.text.count('class="rk-panel rk-customer"')==2
            assert f'id="pelanggan-{rid}" open' in page.text
            assert '600 kg' in page.text and 'Rahasia pelanggan kedua' in page.text
            assert f'/barang-keluar/{oid}/retur?tab_detail=barang' in page.text
            old=await c.get(f'/barang-keluar/{rid}?rincian_perintah=1');assert old.status_code==200 and 'id="judul-perintah"' in old.text
        f=await c.get(f'/barang-keluar/{asal["oid"]}/retur?tab_detail=barang')
        assert f.status_code==200 and f'name="item_id" value="{iid}"' not in f.text
        assert f.text.count('name="item_id"')==1 # item aktual nol tidak ditawarkan
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(CustomerReturn))==0
        assert await db.scalar(select(func.count()).select_from(ReturRincian))==0

from app.penggilingan.inventory.models import ReturRincian

async def test_saldo_bertahap_pengajuan_edit_batal_dan_item_pelanggan_lain(pg,asal):
    oid,iid,kid=await gabung(pg,asal)
    a=await simpan(pg,asal,3)
    async with pg() as db:
        d=await baca(db,await db.get(OutgoingRecord,asal['oid']),boleh_retur=True)
        assert d['total']==600 and d['pelanggan'][0]['barang'][0]['saldo']==dict(diterima=0,tertunda=3,sisa=17,satuan='karung')
        _,usage=await ret.sisa_asal(db,asal['oid'],kecuali=a.id);assert usage[asal['iid']]['karung']==0
    a=await simpan(pg,asal,4,pengajuan_id=a.id,alasan='Tambah satu karung fisik')
    async with pg() as db:
        with pytest.raises(ValueError,match='bukan bagian'):
            await ret.simpan(db,pengiriman_id=asal['oid'],tiket_id=asal['tiket'][1],jumlah={iid:'1'},pelaku_id=asal['uid'])
    await selesai(pg,asal,100);receipt=await terima(pg,a.id);assert receipt
    async with pg() as db:
        d=await baca(db,await db.get(OutgoingRecord,oid),boleh_retur=True)
        b=d['pelanggan'][0]['barang'][0]['saldo'];assert b['diterima']==4 and b['tertunda']==0 and b['sisa']==16
        assert d['total']==600 and len(d['pelanggan'][0]['retur'])==1 and not d['pelanggan'][1]['retur']
        assert (await db.get(OutgoingItem,asal['iid'])).berat_kg==500
    b=await simpan(pg,asal,2,tiket=1)
    async with pg() as db:
        await ret.batalkan(db,identitas=b.id,pelaku=await db.get(User,asal['uid']),alasan='Tidak jadi kembali');await db.commit()
        _,usage=await ret.sisa_asal(db,asal['oid']);assert usage[asal['iid']]['karung']==4
        assert await db.scalar(select(func.count()).select_from(CustomerReturn))==1

async def test_pagination_mengelompokkan_sebelum_limit_dan_search_anggota(pg,asal):
    oid,iid,kid=await gabung(pg,asal)
    async with pg() as db:
        now=now_local()
        for n in range(55):
            db.add(OutgoingRecord(kode='OUT-LAMA-'+str(n),pelanggan_id=asal['pid'],status='selesai',tanggal=now.date(),waktu=now,input_by=asal['uid']))
        await db.commit()
        page=await bk.daftar(db,status=('selesai',),batas=51,gabung_riwayat=True)
        nextpage=await bk.daftar(db,status=('selesai',),batas=51,gabung_riwayat=True,sebelum_id=page[49][0].id)
        firstids=[r.id for r,_ in page[:50]];lastids=[r.id for r,_ in nextpage]
        assert len(firstids)==50 and len(lastids)==6 and not set(firstids)&set(lastids)
        assert sum(r.kiriman_id==kid for r,_ in page[:50]+nextpage)==1
        for search in ['Pelanggan pertama','OUT-UJI-KEDUA','B UJI 474']:
            found=await bk.daftar(db,status=('selesai',),pencarian=search,gabung_riwayat=True)
            assert len(found)==1 and found[0][0].kiriman_id==kid
        assert not await bk.daftar(db,status=('batal',),gabung_riwayat=True)
        assert len(await bk.daftar(db,status=('selesai',),gabung_riwayat=False,batas=100))==57

async def test_portal_proyeksi_tidak_membaca_pelanggan_lain_atau_tiket_gabungan(pg,asal):
    oid,iid,kid=await gabung(pg,asal)
    async with pg() as db:
        j=Jasa(kode='JAS-UJI-474',pelanggan_id=asal['pid']);db.add(j);await db.flush()
        for item in (await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==asal['oid']))).all():item.jasa_id=j.id
        await db.commit()
        scope=SimpleNamespace(ids=lambda model:frozenset([asal['oid']]),jasa_ids=frozenset([j.id]))
        d=await baca(db,await db.get(OutgoingRecord,asal['oid']),scope=scope)
        assert len(d['pelanggan'])==1 and d['total']==500 and d['tiket'] is None and d['tiket_dibatasi']
        assert 'Rahasia pelanggan kedua' not in str(d) and not d['boleh_retur']
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as err:await baca(db,await db.get(OutgoingRecord,oid),scope=scope)
        assert err.value.status_code==404

async def test_validasi_http_mempertahankan_isian_native_dan_json(pg,asal):
    async with await _klien(pg,asal['uid'],'riwayat474fail') as c:
        token=(await c.get('/api/sesi-formulir')).json()['token']
        data=dict(_csrf=token,tiket_id=str(asal['tiket'][0]),item_id=str(asal['iid']),jumlah='21',catatan='Catatan tidak boleh lenyap',**{f'catatan_item_{asal["iid"]}':'Kemasan utuh'})
        response=await c.post(f'/barang-keluar/{asal["oid"]}/retur',data=data)
        assert response.status_code==200,response.text
        assert 'value="21"' in response.text and 'Catatan tidak boleh lenyap' in response.text and 'Kemasan utuh' in response.text
        response=await c.post(f'/barang-keluar/{asal["oid"]}/retur',data=data,headers={'Accept':'application/json'})
        assert response.status_code==400 and 'kumulatif' in response.json()['detail']
        data['jumlah']='2'
        response=await c.post(f'/barang-keluar/{asal["oid"]}/retur',data=data,headers={'Accept':'application/json'})
        assert response.status_code==200 and response.json()['ok']
        async with pg() as db:assert await db.scalar(select(func.count()).select_from(ReturRincian))==1

async def test_history_tiket_legacy_tidak_memalsukan_snapshot_dan_get_tanpa_mutasi(pg,asal):
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET arah='KELUAR',netto_timbangan_kg=501,berat_barang_kg=NULL WHERE id=:id"),{'id':asal['tiket'][0]})
        rec=await db.get(OutgoingRecord,asal['oid']);rec.timbangan_transaksi_id=asal['tiket'][0];await db.commit()
        d=await baca(db,rec,boleh_retur=True)
        assert d['tiket']['legacy'] and d['tiket']['pembanding']==501 and d['tiket']['selisih']==1
        assert d['perintah'] is None and d['tidak_terkirim'] is None
        for _ in range(2):await baca(db,rec,boleh_retur=True)
        assert await db.scalar(select(func.count()).select_from(ActivityLog))==0
        assert await db.scalar(select(func.count()).select_from(CustomerReturn))==0

async def test_penerimaan_historis_bertautan_item_tetap_mengurangi_batas_tanpa_ganda(pg,asal):
    a=await simpan(pg,asal,4);await selesai(pg,asal,100);receipt=await terima(pg,a.id);assert receipt
    async with pg() as db:
        _,pakai=await ret.sisa_asal(db,asal['oid']);assert pakai[asal['iid']]['karung']==4
        # Simulasikan catatan historis: penerimaan punya item asal eksplisit,
        # sementara pengajuannya belum tertaut perintah. Tidak cocokkan SKU.
        draft=await db.get(ReturRincian,a.id);draft.outgoing_record_id=None;await db.commit()
        _,pakai=await ret.sisa_asal(db,asal['oid']);assert pakai[asal['iid']]['karung']==4 and pakai[asal['iid']]['kg']==100
    with pytest.raises(ValueError,match='kumulatif'):await simpan(pg,asal,17,tiket=1)

async def test_portal_http_detail_gabungan_membatasi_data_dan_url_langsung(pg,asal):
    import httpx
    from app.main import app
    from app.models.portal import PortalAccount
    from app.web.portal.security import issue,COOKIE
    from app.web.security import hash_sandi
    oid,iid,kid=await gabung(pg,asal)
    async with pg() as db:
        j=Jasa(kode='JAS-HTTP-474',pelanggan_id=asal['pid']);db.add(j);await db.flush()
        for item in (await db.scalars(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==asal['oid']))).all():item.jasa_id=j.id
        await db.execute(text("UPDATE timbangan_transaksi SET kode='KLR-RAHASIA-474',arah='KELUAR',berat_barang_kg=605 WHERE id=:id"),{'id':asal['tiket'][0]})
        header=await db.get(KirimanKeluar,kid);header.timbangan_transaksi_id=asal['tiket'][0]
        account=PortalAccount(username='portal474',pelanggan_id=asal['pid'],password_hash=hash_sandi('rahasia474'),active=True,token_version=1)
        db.add(account);await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        c.cookies.set(COOKIE,issue(account))
        for query in ['','?rincian_perintah=1']:
            r=await c.get(f'/pelanggan/barang-keluar/{asal["oid"]}'+query)
            assert r.status_code==200,r.text
            assert 'Rahasia pelanggan kedua' not in r.text and 'KLR-RAHASIA-474' not in r.text
            if not query:
                from bs4 import BeautifulSoup
                soup=BeautifulSoup(r.text,'html.parser')
                assert soup.select_one('.rk-number').get_text(strip=True)=='500 kg'
                assert len(soup.select('.rk-customer'))==1
        assert (await c.get(f'/pelanggan/barang-keluar/{oid}')).status_code==404
        assert (await c.post(f'/pelanggan/barang-keluar/{asal["oid"]}/retur')).status_code in (403,404,405)

async def test_request_langsung_item_pelanggan_lain_ditolak_tanpa_pengajuan(pg,asal):
    oid,iid,kid=await gabung(pg,asal)
    async with await _klien(pg,asal['uid'],'retur474direct') as c:
        token=(await c.get('/api/sesi-formulir')).json()['token']
        r=await c.post(f'/barang-keluar/{asal["oid"]}/retur',headers={'Accept':'application/json'},data=dict(_csrf=token,tiket_id=str(asal['tiket'][0]),item_id=str(iid),jumlah='1'))
        assert r.status_code==400 and 'bukan bagian' in r.json()['detail']
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(ReturRincian))==0

@pytest.mark.parametrize('view',['operator:g1','operator:g2'])
async def test_peran_efektif_tidak_mendapat_hak_retur_dari_halaman_baru(pg,asal,view):
    async with await _klien(pg,asal['uid'],'retur474lihat') as c:
        token=(await c.get('/api/sesi-formulir')).json()['token']
        c.cookies.set('produksi_lihat',view,domain='uji.local')
        page=await c.get(f'/barang-keluar/{asal["oid"]}')
        assert page.status_code==(200 if view=='operator:g2' else 403)
        assert 'Retur barang pelanggan ini' not in page.text
        assert (await c.get(f'/barang-keluar/{asal["oid"]}/retur')).status_code==403
        r=await c.post(f'/barang-keluar/{asal["oid"]}/retur',headers={'Accept':'application/json'},data=dict(_csrf=token,tiket_id=str(asal['tiket'][0]),item_id=str(asal['iid']),jumlah='1'))
        assert r.status_code==403

async def test_catatan_barang_saja_bukan_bukti_koreksi_data_bobot(pg,asal):
    await selesai(pg,asal,250)
    a=await simpan(pg,asal,9)
    assert a.wajib_manual and a.status_pemeriksaan=='perlu_koreksi'
    # Perubahan bobot tanpa audit TeraFlow tidak menjadi koreksi yang sah.
    # Mengganti catatan barang saja juga tidak boleh membuka gerbang manual.
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET berat_barang_kg=225,timbang2_kg=8775 WHERE id=:id'),{'id':asal['tiket'][0]});await db.commit()
    a=await simpan(pg,asal,9,pengajuan_id=a.id,alasan='Catatan saja',catatan_item={asal['iid']:'Label kemasan diperjelas'})
    async with pg() as db:pelaku=await db.get(User,asal['uid'])
    assert await terima(pg,a.id,manual=True,pelaku=pelaku) is None
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(CustomerReturn))==0

@pytest.mark.parametrize('jumlah',['1.001','-1','NaN','501'])
async def test_presisi_kg_dan_batas_curah_tetap_divalidasi_server(pg,asal,jumlah):
    async with pg() as db:
        item=await db.get(OutgoingItem,asal['iid']);item.item_type='byproduct_curah';item.product_sku_id=None;item.jumlah_karung=None;item.jenis_byproduct='bekatul';await db.commit()
    with pytest.raises(ValueError):await simpan(pg,asal,jumlah)
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(ReturRincian))==0
