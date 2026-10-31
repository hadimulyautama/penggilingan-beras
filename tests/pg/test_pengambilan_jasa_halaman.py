"""Penerbitan draf jasa atomik, tanpa mengubah stok, dan tetap milik pelanggan."""
import asyncio
import re
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from app.models import Jasa, Pelanggan, User, OutgoingRecord, OutgoingItem, DrafKeluar
from app.web.draf_keluar import simpan,terbitkan,SimpanDraf,TerbitDraf
from app.web.aksi_inventory import AmbilJasaReq,BarisReq,pratinjau_pengambilan_jasa
from tests.pg.test_barang_keluar import gudang,_klien

pytestmark=pytest.mark.asyncio

async def dunia(pg,g):
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    async with pg() as db:
        a=Pelanggan(nama_pelanggan='Pemilik A',kledo_contact_id=9201)
        b=Pelanggan(nama_pelanggan='Pemilik B',kledo_contact_id=9202)
        db.add_all([a,b]);await db.flush()
        ja=Jasa(kode='JAS-UJI-01',pelanggan_id=a.id,status='berjalan')
        jb=Jasa(kode='JAS-UJI-02',pelanggan_id=b.id,status='berjalan')
        db.add_all([ja,jb]);await db.flush()
        stocks=list((await db.scalars(select(FinishedGoodsStock))).all())
        for stock in stocks:stock.jasa_id=ja.id
        await db.commit()
        return {'a':a.id,'b':b.id,'ja':ja.id,'jb':jb.id,'pilih':f"bj:{g['sku']}|{g['std']}@{ja.id}"}

async def saldo(pg,g,jid):
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    async with pg() as db:return float((await hitung_stok_finished_goods(db,g['sku'],g['std'],jasa_id=jid))['kg'])

async def test_jasa_draf_dan_pratinjau_tidak_memotong_stok_terbit_idempoten(pg,gudang):
    d=await dunia(pg,gudang)
    async with pg() as db:u=await db.get(User,gudang['adm'])
    awal=await saldo(pg,gudang,d['ja']);assert awal==10000
    req=AmbilJasaReq(pelanggan=str(d['a']),barang=[BarisReq(pilih=d['pilih'],jumlah=4)])
    h=await pratinjau_pengambilan_jasa(req,u)
    assert h['sumber'][d['pilih']]['kg_per_unit']==25
    assert h['sumber'][d['pilih']]['tersedia']==10000
    ident=uuid4();isi={'jenis':'jasa',**req.model_dump(),'metode':'diambil','catatan':'Diambil bertahap'}
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),u)
    assert await saldo(pg,gudang,d['ja'])==awal
    x,y=await asyncio.gather(terbitkan(ident,TerbitDraf(revisi=1),u),terbitkan(ident,TerbitDraf(revisi=1),u))
    assert x['tujuan']==y['tujuan']
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==1
        rec=await db.get(OutgoingRecord,int(x['tujuan'].rsplit('/',1)[-1]))
        assert rec.pelanggan_id==d['a'] and rec.status=='perintah' and rec.metode=='diambil'
        assert rec.catatan_perintah=='Diambil bertahap'
        items=list((await db.scalars(select(OutgoingItem))).all())
        assert len(items)==1 and items[0].jasa_id==d['ja'] and float(items[0].berat_kg)==0
    assert await saldo(pg,gudang,d['ja'])==awal
    h=await pratinjau_pengambilan_jasa(req,u)
    assert h['sumber'][d['pilih']]['tersedia']==9900

@pytest.mark.parametrize('masalah',['pemilik_lain','pabrik','jumlah_pecahan','kosong'])
async def test_tolak_draf_salah_tanpa_menghilangkan_isian(pg,gudang,masalah):
    d=await dunia(pg,gudang)
    async with pg() as db:u=await db.get(User,gudang['adm'])
    isi={'jenis':'jasa','pelanggan':str(d['a']),'barang':[{'pilih':d['pilih'],'jumlah':4}]}
    if masalah=='pemilik_lain':isi['pelanggan']=str(d['b'])
    if masalah=='pabrik':isi['barang'][0]['pilih']=d['pilih'].split('@')[0]
    if masalah=='jumlah_pecahan':isi['barang'][0]['jumlah']=1.5
    if masalah=='kosong':isi['barang']=[]
    ident=uuid4();await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),u)
    with pytest.raises(HTTPException):await terbitkan(ident,TerbitDraf(revisi=1),u)
    async with pg() as db:
        assert (await db.get(DrafKeluar,str(ident))).isi==isi
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0
    assert await saldo(pg,gudang,d['ja'])==10000

async def test_halaman_dan_alias_lama_tanpa_borang_dan_izin(pg,gudang):
    d=await dunia(pg,gudang)
    c=await _klien(pg,gudang['adm'],'halaman-jasa-admin')
    async with c:
        r=await c.get('/barang-keluar/pengambilan-jasa?pelanggan_id='+str(d['a']))
        assert r.status_code==200,r.text
        assert 'data-jenis="jasa"' in r.text and 'id="lembar"' not in r.text
        r=await c.get('/barang-keluar?buka=ambil_jasa&nilai='+str(d['a']))
        assert r.status_code==303 and r.headers['location'].endswith('pelanggan_id='+str(d['a']))
        r=await c.get('/barang-keluar')
        assert '/barang-keluar/pengambilan-jasa' in r.text
    c=await _klien(pg,gudang['op'],'halaman-jasa-operator',mode='operator')
    async with c:
        assert (await c.get('/barang-keluar/pengambilan-jasa')).status_code==403
        from app.web import csrf
        halaman=await c.get('/barang-keluar')
        token=re.search(r'name="formulir-sesi" content="([^"]+)"',halaman.text).group(1)
        # CSRF valid: the role check itself must deny this endpoint.
        r=await c.post('/api/actions/pratinjau-pengambilan-jasa',json={'pelanggan':str(d['a']),'barang':[{'pilih':d['pilih'],'jumlah':1}]},headers={csrf.NAMA_HEADER:token})
        assert r.status_code==403

async def test_pengambilan_lintas_pesanan_sepemilik_tetap_terpisah_per_baris(pg,gudang):
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.web.aksi_inventory import _barang_jasa_pelanggan_rows
    d=await dunia(pg,gudang)
    async with pg() as db:
        second=Jasa(kode='JAS-UJI-03',pelanggan_id=d['a'],status='berjalan')
        db.add(second);await db.flush()
        stock=await db.scalar(select(FinishedGoodsStock))
        stock.jumlah_karung=200;stock.berat_total_kg=5000
        db.add(FinishedGoodsStock(product_sku_id=stock.product_sku_id,
            rice_quality_standard_id=stock.rice_quality_standard_id,
            source_type=stock.source_type,source_id=stock.source_id,
            jumlah_karung=200,berat_total_kg=5000,warehouse_id=stock.warehouse_id,
            waktu=stock.waktu,input_by=stock.input_by,jasa_id=second.id))
        await db.commit();jid2=second.id
        catalog=await _barang_jasa_pelanggan_rows(db,d['a'])
        assert any('JAS-UJI-01' in x['label'] for x in catalog)
        assert any('JAS-UJI-03' in x['label'] for x in catalog)
        u=await db.get(User,gudang['adm'])
    isi={'jenis':'jasa','pelanggan':str(d['a']),'barang':[
        {'pilih':d['pilih'],'jumlah':2},
        {'pilih':d['pilih'].split('@')[0]+'@'+str(jid2),'jumlah':3}]}
    ident=uuid4();await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),u)
    h=await terbitkan(ident,TerbitDraf(revisi=1),u)
    async with pg() as db:
        rec=await db.get(OutgoingRecord,int(h['tujuan'].rsplit('/',1)[-1]))
        items=list((await db.scalars(select(OutgoingItem))).all())
        assert rec.pelanggan_id==d['a'] and rec.jasa_id is None
        assert {x.jasa_id for x in items}=={d['ja'],jid2}
        assert sorted(float(x.berat_perintah_kg) for x in items)==[50,75]
    assert await saldo(pg,gudang,d['ja'])==5000
    assert await saldo(pg,gudang,jid2)==5000
    # Barang identik dari dua pesanan tetap mempunyai saldo dan muatan sendiri.
    from app.services import barang_keluar as bk
    by_jasa={x.jasa_id:x.id for x in items}
    async def muat(jid,jumlah):
        async with pg() as db:
            await bk.catat_muatan(db,user=await db.get(User,gudang['op']),
                item_id=by_jasa[jid],rec_id=rec.id,jumlah_karung=jumlah)
    await muat(d['ja'],1)
    await muat(d['ja'],1)  # pengulangan total yang sama tidak memotong lagi
    await muat(jid2,2)
    assert await saldo(pg,gudang,d['ja'])==4975
    assert await saldo(pg,gudang,jid2)==4950
    await muat(d['ja'],2)
    await muat(d['ja'],1)  # koreksi penurunan total memulihkan selisih 25 kg
    assert await saldo(pg,gudang,d['ja'])==4975
    assert await saldo(pg,gudang,jid2)==4950
    # Kekurangan ditutup berdasarkan aktual, bukan menjalankan Muat semua.
    async with pg() as db:
        await bk.selesai_muat(db,user=await db.get(User,gudang['op']),rec_id=rec.id,sebab='Sisa tetap dititipkan')
        await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rec.id)
    async with await _klien(pg,gudang['adm'],'lintas-pesanan-riwayat') as c:
        page=await c.get(f'/barang-keluar/{rec.id}/perbaikan')
        assert page.status_code==200 and 'Barang jasa' in page.text and 'Retur barang Pemilik A' in page.text
        from tests.pg.formulir import cap_formulir
        from app.models import ActivityLog
        async with pg() as db:
            log=await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='barang_keluar_verifikasi').order_by(ActivityLog.id.desc()).limit(1))
        response=await c.post(f'/api/actions/perbaikan-pengiriman/{rec.id}/buka-ulang',
            json={'log_id':log.id,'alasan':'Periksa kesalahan pencatatan dua pesanan','konfirmasi':True},
            headers={'X-CSRF-Token':cap_formulir(c)})
        assert response.status_code==200,response.text
    assert await saldo(pg,gudang,d['ja'])==4975
    assert await saldo(pg,gudang,jid2)==4950
    async with pg() as db:
        unchanged=list((await db.scalars(select(OutgoingItem))).all())
        assert {x.id:x.jasa_id for x in unchanged}=={x.id:x.jasa_id for x in items}
        assert sorted(float(x.berat_kg) for x in unchanged)==[25,50]
