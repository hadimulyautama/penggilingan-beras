"""Satuan otomatis membaca sumber asli; endpoint/ledger kg lama tetap satu."""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from app.models import User,PkPurchaseBatch,PkGudang2Intake,PkTumpukanToSilo,InternalTransfer,Peristiwa
from app.services.masukkan_silo import sumber, pilih
from app.penggilingan.gudang2 import service as g2
from tests.pg.test_pk_karung import dunia,batch_baru
from tests.pg.test_peristiwa_transfer import pabrik
from tests.pg.test_pk_sendiri_50 import siapkan
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio

async def post(c,iid,bentuk,**kw):
    return await c.post('/api/actions/pindah-tumpukan-silo',json=dict(tumpukan=f'{iid}:{bentuk}',silo='A',**kw),headers={'X-CSRF-Token':cap_formulir(c)})

@pytest.mark.parametrize('w,asal,final',[(10140,'timbangan',True),(10240,'perkiraan',False),(None,'menunggu',False)])
async def test_karung_luar_rasio_asli_bukan50(pg,dunia,w,asal,final):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,w=w,sumber=asal);uid,iid=u.id,it.id
    async with await _klien(pg,uid,'masuk-karung',mode='operator') as c:
        daftar=(await c.get('/api/actions/sumber-masukkan-silo')).json()
        assert daftar[0]['value']==f'{iid}:karung'
        p=await c.get('/api/actions/rincian-masukkan-silo',params=dict(tumpukan=f'{iid}:karung',silo='A',jumlah_karung=126))
        assert p.status_code==200,p.text
        d=p.json();assert d['sumber']['karung']==128 and d['sumber']['bobot_final']==final
        assert d['berat_masuk']==(None if w is None else w*126/128)
        assert (await post(c,iid,'karung')).status_code==400
        r=await post(c,iid,'karung',jumlah_karung=126,kunci_kiriman='baru-karung');assert r.status_code==200,r.text
    async with pg() as db:
        m=(await db.scalars(select(PkTumpukanToSilo))).one()
        assert m.jumlah_karung==126 and m.berat_timbang_kg is None
        rows=await sumber(db,await db.get(PkGudang2Intake,iid));assert rows[0]['karung']==2
        r=await g2.pindah_tumpukan_ke_silo(db,user=await db.get(User,uid),intake_id=iid,nama_silo='A',bentuk_sumber='karung',jumlah_karung=2)
        assert r.sisa_tumpukan_intake==0

async def test_sendiri_karung_curah_terpisah_tanpa_duplikasi(pg,pabrik):
    ids=await siapkan(pg,pabrik)
    async with pg() as db:
        rows=await sumber(db,await db.get(PkGudang2Intake,ids[1]))
        assert [(s['bentuk'],s['saldo_kg'],s['karung']) for s in rows]==[('karung',6400,128),('curah',20,None)]
        assert sum(s['saldo_kg'] for s in rows)==6420
    async with await _klien(pg,ids[0],'sendiri-unit-auto',mode='operator') as c:
        menu=(await c.get('/api/actions/menu')).json();a=next(a for a in menu if a['id']=='pindah_tumpukan_silo')
        assert 'hasil_timbang' not in [f['name'] for f in a['fields']]
        assert not any(f['type']=='select' for f in a['fields'])
        assert (await post(c,ids[1],'curah')).status_code==400
        r=await post(c,ids[1],'curah',berat_kg=10,kunci_kiriman='curah10');assert r.status_code==200,r.text
        r=await post(c,ids[1],'karung',jumlah_karung=2,kunci_kiriman='karung2');assert r.status_code==200,r.text
    async with pg() as db:
        rows=await sumber(db,await db.get(PkGudang2Intake,ids[1]))
        assert [(s['bentuk'],s['saldo_kg'],s['karung']) for s in rows]==[('karung',6300,126),('curah',10,None)]
        silo=await g2.get_g2_silo(db,'A');assert await g2.hitung_stok_silo(db,silo.id)==110
        assert await g2._sisa_tumpukan_intake(db,ids[1])==6310

@pytest.mark.parametrize('bentuk,isi',[('curah',dict(berat_kg=21)),('curah',dict(berat_kg=0)),('curah',dict(berat_kg=-1)),('curah',dict(berat_kg='Infinity')),('curah',dict(berat_kg=True)),('karung',dict(jumlah_karung=129)),('karung',dict(jumlah_karung=1.5)),('karung',dict(jumlah_karung=True)),('karung',dict(jumlah_karung=1,berat_kg=20)),('karung',dict(jumlah_karung=0))])
async def test_input_salah_tidak_mengurangi_stok(pg,pabrik,bentuk,isi):
    ids=await siapkan(pg,pabrik)
    async with await _klien(pg,ids[0],'salah-auto',mode='operator') as c:
        r=await post(c,ids[1],bentuk,**isi);assert r.status_code in [400,422],r.text
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,ids[1])==6420
        assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==0

async def test_retry_presisi_sama_dan_isian_berbeda_ditolak(pg,pabrik):
    ids=await siapkan(pg,pabrik)
    async with await _klien(pg,ids[0],'retry-auto',mode='operator') as c:
        for _ in range(2):
            r=await post(c,ids[1],'curah',berat_kg=2.0005,kunci_kiriman='kunci-sama-auto');assert r.status_code==200,r.text
        assert (await post(c,ids[1],'curah',berat_kg=3,kunci_kiriman='kunci-sama-auto')).status_code==400
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==1
        assert await g2._sisa_tumpukan_intake(db,ids[1])==6417.999

async def test_curah_berubah_di_dua_sesi_tidak_mengurangi_karung(pg,pabrik):
    ids=await siapkan(pg,pabrik)
    async def jalan():
        async with pg() as db:
            try:return await g2.pindah_tumpukan_ke_silo(db,user=await db.get(User,ids[0]),intake_id=ids[1],nama_silo='A',bentuk_sumber='curah',berat=15)
            except g2.Gudang2Error:return None
    hasil=await asyncio.gather(jalan(),jalan());assert sum(x is not None for x in hasil)==1
    async with pg() as db:
        rows=await sumber(db,await db.get(PkGudang2Intake,ids[1]))
        assert rows[0]['karung']==128 and rows[0]['saldo_kg']==6400 and rows[1]['saldo_kg']==5

async def test_lama_bukan_curah_dan_surat_jalan_baca_saja(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=None);uid,iid,bid=u.id,it.id,b.id
    async with await _klien(pg,uid,'lama-auto',mode='operator') as c:
        r=await c.get('/api/actions/rincian-masukkan-silo',params={'tumpukan':f'{iid}:lama'})
        assert r.status_code==200 and r.json()['sumber']['bentuk']=='lama'
        r=await c.get('/api/actions/rincian-masukkan-silo',params=dict(tumpukan=f'{iid}:lama',jumlah_karung_partai=128,jumlah_karung=20,silo='A'))
        assert r.status_code==200 and r.json()['sumber']['bentuk']=='karung',r.text
        async with pg() as db:assert (await db.get(PkPurchaseBatch,bid)).jumlah_karung is None
        r=await post(c,iid,'lama',jumlah_karung_partai=128,jumlah_karung=20);assert r.status_code==200,r.text
    async with pg() as db:assert (await db.get(PkPurchaseBatch,bid)).jumlah_karung==128

async def test_lama_dengan_riwayat_kg_tetap_kg(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=None);uid,iid,bid=u.id,it.id,b.id
        await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=iid,nama_silo='A',berat=1000)
    async with await _klien(pg,uid,'lama-history',mode='operator') as c:
        r=await post(c,iid,'lama',berat_kg=100);assert r.status_code==200,r.text
    async with pg() as db:assert (await db.get(PkPurchaseBatch,bid)).jumlah_karung is None

async def test_transfer_lama_tidak_dibuatkan_unit_fiktif(pg,pabrik):
    ids=await siapkan(pg,pabrik)
    async with pg() as db:
        tr=await db.get(InternalTransfer,ids[2]);tr.jumlah_karung=None;tr.berat_curah_kg=None;await db.commit()
        rows=await sumber(db,await db.get(PkGudang2Intake,ids[1]));assert len(rows)==1 and rows[0]['bentuk']=='lama' and rows[0]['karung'] is None

async def test_keluar_kg_membatasi_karung_utuh_dan_bagian_tetap_ada(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia)
        await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',berat=25,hasil_timbang=True)
        rows=await sumber(db,it);s=rows[0]
        assert s['karung']==127 and s['bagian_karung_kg']==54.21875
        await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',bentuk_sumber='karung',jumlah_karung=127)
        rows=await sumber(db,it);assert rows[0]['bentuk']=='lama' and rows[0]['saldo_kg']==54.21875


@pytest.mark.parametrize('role,view,wh,izin',[
    ('operator',None,'g2',True),('operator',None,'g1',False),
    ('admin',None,'g2',False),('superadmin',None,'g2',True),
    ('admin','operator:g2','g2',True),('admin','operator:g1','g1',False),
    ('superadmin','operator:g1','g1',False),('staff',None,'g2',False)])
async def test_izin_sumber_ringkasan_dan_post(pg,pabrik,role,view,wh,izin):
    from app.models import Warehouse
    ids=await siapkan(pg,pabrik)
    async with pg() as db:
        u=await db.get(User,ids[0]);u.role=role
        u.default_warehouse_id=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==wh).limit(1));await db.commit()
    async with await _klien(pg,ids[0],'akses-auto',mode='operator' if role=='operator' else 'admin') as c:
        if view:
            r=await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)});assert r.status_code==303
        r=await c.get('/api/actions/sumber-masukkan-silo');assert r.status_code==200 if izin else r.status_code in [401,403]
        r=await c.get('/api/actions/rincian-masukkan-silo',params=dict(tumpukan=f'{ids[1]}:curah',berat_kg=10,silo='A'));assert r.status_code==200 if izin else r.status_code in [401,403]
        r=await post(c,ids[1],'curah',berat_kg=10);assert r.status_code==200 if izin else r.status_code in [401,403],r.text
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==(1 if izin else 0)


async def test_pemilik_tujuan_dan_rollback_pelengkapan_surat_jalan(pg,dunia):
    from app.models import Jasa,Pelanggan
    from app.database import now_local
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=None);uid,iid,bid=u.id,it.id,b.id
        kontak=[Pelanggan(nama_pelanggan='Pemilik pertama'),Pelanggan(nama_pelanggan='Pemilik kedua')];db.add_all(kontak);await db.flush()
        j1=Jasa(kode='JAS-AUTO-1',pelanggan_id=kontak[0].id);j2=Jasa(kode='JAS-AUTO-2',pelanggan_id=kontak[1].id);db.add_all([j1,j2]);await db.flush()
        b.supplier_id=None;b.jasa_id=j1.id;it.jasa_id=j1.id
        a=await g2.get_g2_silo(db,'A');db.add(PkGudang2Intake(sumber_tipe="beli_luar",silo_id=a.id,tujuan='silo',jasa_id=j2.id,berat_kg=100,bobot_final=True,tanggal_masuk=now_local().date(),waktu_masuk=now_local(),input_by=uid));await db.commit()
    async with await _klien(pg,uid,'beda-pemilik-auto',mode='operator') as c:
        opsi=(await c.get('/api/actions/silo-g2',params={'induk':f'{iid}:lama'})).json();assert [o['value'] for o in opsi]==['B']
        r=await post(c,iid,'lama',jumlah_karung_partai=128,jumlah_karung=20);assert r.status_code==400,r.text
    async with pg() as db:
        assert (await db.get(PkPurchaseBatch,bid)).jumlah_karung is None
        assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==0


async def test_masuk_ke_penyosohan_berjalan_bukan_output_baru(pg,pabrik):
    from app.models import PolishingProcess,PolishingSiloUsage,PolishingOutputLog
    from app.penggilingan.gudang2 import polishing as pol
    ids=await siapkan(pg,pabrik)
    async with pg() as db:
        u=await db.get(User,ids[0]);await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=ids[1],nama_silo='A',jumlah_karung=10)
        mulai=await pol.mulai_penyosohan(db,user=u,nama_silos=['A']);kode=mulai.proc.kode_proses;pid=mulai.proc.id
    async with await _klien(pg,ids[0],'silo-proses-auto',mode='operator') as c:
        p=await c.get('/api/actions/rincian-masukkan-silo',params=dict(tumpukan=f'{ids[1]}:curah',berat_kg=10,silo='A'))
        assert p.status_code==200 and p.json()['proses']==[kode],p.text
        r=await post(c,ids[1],'curah',berat_kg=10);assert r.status_code==200,r.text
        assert r.json()['rincian_masukkan']['sisa_kg']==10
        assert r.json()['rincian_masukkan']['sejawat'][0]['saldo_kg']==5900
    async with pg() as db:
        proc=await db.get(PolishingProcess,pid);assert proc.status=='proses'
        usage=(await db.scalars(select(PolishingSiloUsage))).one();assert usage.berat_masuk_kg==10
        assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==0


async def test_kg_data_lama_tetap_bertanda_bobot_sementara(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=None,w=10240,sumber='perkiraan');uid,iid,bid=u.id,it.id,b.id
    async with await _klien(pg,uid,'lama-sementara-auto',mode='operator') as c:
        r=await post(c,iid,'lama',berat_kg=100)
        assert r.status_code==200,r.text
        assert r.json()['rincian_masukkan']['bobot_final'] is False and '±' in r.json()['pesan']
    async with pg() as db:assert (await db.get(PkPurchaseBatch,bid)).sumber_berat=='perkiraan'


async def test_baca_saldo_tambahan_gagal_tidak_mengaburkan_simpan(pg,dunia,monkeypatch):
    from app.services import masukkan_silo as ms
    asli=ms.sumber;jumlah=0
    async def baca(*a,**kw):
        nonlocal jumlah
        jumlah+=1
        if jumlah==2:raise RuntimeError('Gangguan baca tambahan uji')
        return await asli(*a,**kw)
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia);uid,iid=u.id,it.id
    monkeypatch.setattr(ms,'sumber',baca)
    async with await _klien(pg,uid,'baca-tambahan-auto',mode='operator') as c:
        r=await post(c,iid,'karung',jumlah_karung=126,kunci_kiriman='baca-gagal-tetap-simpan')
        assert r.status_code==200,r.text
        assert r.json()['ok'] and r.json()['ringkasan_tersedia'] is False
        assert 'tersimpan' in r.json()['pesan'] and 'belum dapat dimuat' in r.json()['pesan']
        r=await post(c,iid,'karung',jumlah_karung=126,kunci_kiriman='baca-gagal-tetap-simpan');assert r.status_code==200,r.text
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==1


async def test_curah_seluruh_dan_pembatalan_memulihkan_dua_bentuk(pg,pabrik):
    from tests.pg.test_peristiwa_pindah_tumpukan import _undo
    ids=await siapkan(pg,pabrik)
    async with await _klien(pg,ids[0],'curah-seluruh-undo',mode='operator') as c:
        r=await post(c,ids[1],'curah',berat_kg=20,kunci_kiriman='seluruh-curah-undo')
        assert r.status_code==200,r.text
    async with pg() as db:
        rows=await sumber(db,await db.get(PkGudang2Intake,ids[1]))
        assert [(s['bentuk'],s['saldo_kg']) for s in rows]==[('karung',6400)]
        assert await g2.hitung_stok_silo(db,(await g2.get_g2_silo(db,'A')).id)==20
        e=await db.scalar(select(Peristiwa).where(Peristiwa.jenis=='pk_tumpukan_ke_silo'))
        assert e.muatan['isian_sumber']['bentuk']=='curah'
    hasil=await _undo(pg,ids[0]);assert 'UndoError' not in hasil,hasil
    async with pg() as db:
        rows=await sumber(db,await db.get(PkGudang2Intake,ids[1]))
        assert [(s['bentuk'],s['saldo_kg']) for s in rows]==[('karung',6400),('curah',20)]
        assert await g2.hitung_stok_silo(db,(await g2.get_g2_silo(db,'A')).id)==0
