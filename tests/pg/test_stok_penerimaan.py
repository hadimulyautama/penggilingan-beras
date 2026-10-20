"""Bukti penerimaan Stok: seluruh data buatan, hanya PostgreSQL lokal uji."""
from dataclasses import asdict, is_dataclass
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlsplit
from html import unescape
import json, re
import pytest
import pytest_asyncio
from sqlalchemy import select, func
from app.database import now_local
from app.models import User, MillingProcess, MillingProgressLog, Jasa, ActivityLog
from tests.pg.test_konsolidasi_stok import stok_lengkap, sosoh_jasa, PASANGAN
from tests.pg.test_riwayat_giling import _klien, pabrik, _giling_selesai
from tests.pg.test_stok_pk_qc import dunia, dunia_asal
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio
OUT=Path('output/stok390');OUT.mkdir(parents=True,exist_ok=True)

@pytest_asyncio.fixture
async def lengkap(pg, stok_lengkap):
    from app.penggilingan.gudang2.models import PolishingProcess,PolishingOutputLog
    from tests.pg.test_stok_produk_jasa import _packing
    d=stok_lengkap
    await _packing(pg,d,kode_pol=d['kode_pabrik'],karung=8)
    await _packing(pg,d,kode_pol=d['kode_jasa'],karung=8)
    async with pg() as db:
        j=Jasa(kode='JAS-AUDIT-ULANG',pelanggan_id=d['pelanggan_id'],status='berjalan')
        db.add(j);await db.flush()
        asal=await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses=='LOT-STOK-JASA'))
        for kode,kg,status,jid in [('LOT-AUDIT-ULANG',125.25,'selesai',j.id),('LOT-AUDIT-BERJALAN',200.5,'proses',None),('LOT-AUDIT-KOSONG',None,'selesai',None)]:
            p=MillingProcess(kode_proses=kode,status=status,jasa_id=jid,silo_id=asal.silo_id,
                             berat_gabah_masuk_kg=1000,waktu_mulai=now_local(),created_by=d['user'])
            db.add(p);await db.flush()
            if kg is not None:db.add(MillingProgressLog(milling_process_id=p.id,berat_kumulatif_kg=kg,waktu_update=now_local(),input_by=d['user']))
        for kode in (d['kode_pabrik'],d['kode_jasa']):
            p=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode))
            for jenis in ('premium','medsuper','sayur','beras_putih','beras_b','broken','menir','bekatul','reject'):
                db.add(PolishingOutputLog(polishing_process_id=p.id,jenis=jenis,berat_kg=125.25,waktu_update=now_local(),input_by=d['user']))
        await db.commit()
    return {**d,'jasa_kedua':j.id}

async def test_semua_kategori_detail_dan_pk_dua_pesanan(pg,lengkap):
    from app.web import tampilan
    from unittest.mock import patch
    saved=[];asli=tampilan.render
    def tangkap(request,nama,**k):
        saved.append(k)
        return asli(request,nama,**k)
    async with await _klien(pg,peran='superadmin') as c:
        with patch.object(tampilan,'render',tangkap):
            r=await c.get('/stok',params={'tab':'bahan','pemilik':'jasa','pelanggan_id':lengkap['pelanggan_id'],'gudang':'g1'})
            assert r.status_code==200
            assert 'LOT-STOK-JASA' in r.text and 'LOT-AUDIT-ULANG' in r.text and 'LOT-STOK-LAIN' not in r.text
            # Konteks hasil siapkan berasal dari render_laci, kelompok tampak lewat HTML.
            assert '3.625,25' in r.text
        for owner,path in [('pabrik','/stok-produk'),('jasa','/stok-produk-jasa')]:
            params={'tab':'produk','pemilik':owner,'gudang':'g2'}
            if owner=='jasa':params['pelanggan_id']=lengkap['pelanggan_id']
            r=await c.get('/stok',params=params);assert r.status_code==200
            for jenis in ('medium','premium','medsuper','sayur','beras_putih','beras_b','broken','menir','bekatul','reject'):
                links=[unescape(h) for h in re.findall(r'href="([^"]+)"',r.text) if '/detail?' in h and parse_qs(urlsplit(unescape(h)).query).get('jenis')==[jenis]]
                assert len(links)==1,(owner,jenis)
                det=await c.get(links[0]);assert det.status_code==200
                if jenis!='medium':assert '125,25' in det.text,(owner,jenis)
                assert ('Bu Sri' in det.text)==(owner=='jasa')
                assert ('POL-UJIJ-01' in det.text)==(owner=='jasa')
        for kode,pesan in [('LOT-AUDIT-BERJALAN','Mesin masih giling'),('LOT-AUDIT-KOSONG','belum')]:
            det=await c.get('/stok/pk/detail',params={'gudang':'g1','kode':kode})
            assert det.status_code==200,(kode,det.text)
            assert pesan.lower() in det.text.lower()
        opsi=(await c.get('/api/actions/beras-belum-dikemas')).json()
        assert any('125,25 kg' in o['label'] and o['berat_kg']==125.25 for o in opsi)
        (OUT/'kategori-dan-pesanan.json').write_text(json.dumps({'akun':'Uji superadmin','pk_pelanggan':3625.25,'kategori':10,'dua_pemilik':True}))

async def test_mutu_nonaktif_menolak_post_kedua_jenis_tanpa_audit(pg,dunia):
    from app.services.setelan import set_fitur_mutu
    async with await _klien(pg,peran='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        async with pg() as db:
            await set_fitur_mutu(db,False,user=await db.get(User,dunia['user'].id))
            n=await db.scalar(select(func.count()).select_from(ActivityLog))
        for endpoint,ident in [('qc-giling',{'kode_proses':'LOT-KODE-01'}),('qc-pk-luar',{'kode_batch':'PKB-KODE-01'})]:
            r=await c.post('/api/actions/'+endpoint,json={**ident,'kadar_air':13,'butir_kuning':'bersih','gabah':'bersih','merang':'bersih'})
            assert r.status_code==400 and 'dimatikan' in r.text
        async with pg() as db:
            assert n==await db.scalar(select(func.count()).select_from(ActivityLog))
            await set_fitur_mutu(db,True,user=await db.get(User,dunia['user'].id))
        for endpoint,ident in [('qc-giling',{'kode_proses':'LOT-KODE-01'}),('qc-pk-luar',{'kode_batch':'PKB-KODE-01'})]:
            r=await c.post('/api/actions/'+endpoint,json={**ident,'kadar_air':13,'butir_kuning':'bersih','gabah':'bersih','merang':'bersih'})
            assert r.status_code==200,r.text

async def test_koreksi_hasil_giling_saldo_rendemen_audit_dan_batal(pg,pabrik):
    from app.services.stok import pk_gudang1
    from app.services import undo
    kode=await _giling_selesai(pg,pabrik,masuk_kg=10000,berat_akhir=6500)
    async with await _klien(pg,peran='admin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        det=await c.get('/stok/pk/detail',params={'kode':kode,'gudang':'g1'})
        assert 'buka=verify_output' in det.text
        r=await c.post('/api/actions/verify-output',json={'kode_proses':kode,'berat_output':6750.25})
        assert r.status_code==200,r.text
        async with pg() as db:
            lot=next(x for x in await pk_gudang1(db) if x.kode==kode)
            assert lot.tersedia==6750.25 and lot.rendemen==pytest.approx(67.5025)
            audit=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='milling_process_verifications').order_by(ActivityLog.id.desc()))
            actor=await db.get(User,audit.changed_by)
            assert actor.nama=='Uji admin'
            assert audit.new_value=='6750.25'
            await undo.undo_last(db,actor=actor,cakupan=undo.Cakupan([actor.id]),log_id=audit.id)
        async with pg() as db:
            lot=next(x for x in await pk_gudang1(db) if x.kode==kode)
            assert lot.tersedia==6500 and lot.rendemen==65
        (OUT/'koreksi-giling.json').write_text(json.dumps({'kode':kode,'akun':'Uji admin','sebelum':[6500,65],'sesudah':[6750.25,67.5025],'dibatalkan':[6500,65]}))

# Syarat izin tiap tindakan; payload sengaja tidak sah agar jalur berizin tidak
# mengubah data. Transaksi positif diuji terpisah melalui layanan/HTTP/browser.
AKSI=[
 ('verify-output',{'kode_proses':'','berat_output':1},'admin'),
 ('qc-giling',{'kode_proses':''},'admin'),('qc-pk-luar',{'kode_batch':''},'admin'),
 ('minta-pk-g1',{'kode_proses':''},'g2'),
 ('pindah-tumpukan-silo',{'tumpukan':'','silo':''},'fisik'),
 ('catat-packing',{'hasil':'','kemasan':'','jumlah_karung':1},'packing'),
 ('catat-bekatul',{'kode_pol':'','berat_kg':0},'packing'),
 ('pindah-kepemilikan-produk',{'item':'','jumlah':0},'admin'),
 ('pindah-kepemilikan-karung',{'karung':'','pelanggan':'','jumlah':0},'admin'),
 ('beli-kemasan',{'karung':'','jumlah':0},'admin'),
 ('masukkan-broken-silo',{'proses':'','silo':'','berat_kg':1},'fisik'),
 ('masukkan-menir-silo',{'pemilik':'','silo':'','berat_kg':1},'fisik'),
 ('masukkan-reject-silo',{'pemilik':'','silo':'','berat_kg':1},'fisik'),
 ('masukkan-beras-silo',{'jenis':'','sumber_stok':'','silo':'','berat_kg':1},'fisik'),
]
@pytest.mark.parametrize('role,gudang,lihat',[
    ('superadmin',None,None),('admin',None,None),
    ('operator','Gudang 1',None),('operator','Gudang 2',None),
    ('superadmin','Gudang 1','operator:g1'),('superadmin','Gudang 2','operator:g2'),
])
async def test_izin_semua_endpoint_stok(pg,stok_lengkap,role,gudang,lihat):
    async with await _klien(pg,peran=role,gudang=gudang) as c:
        if lihat:
            r=await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)})
            assert r.status_code==200 and c.cookies.get('produksi_lihat')==lihat
            role='operator'
        c.headers['X-CSRF-Token']=cap_formulir(c)
        for endpoint,payload,jenis in AKSI:
            boleh=(role in {'admin','superadmin'} if jenis=='admin' else
                   role=='operator' and gudang=='Gudang 2' if jenis=='g2' else
                   role=='superadmin' or role=='operator' and gudang=='Gudang 2' if jenis=='fisik' else
                   role in {'admin','superadmin'} or gudang=='Gudang 2')
            r=await c.post('/api/actions/'+endpoint,json=payload)
            assert r.status_code in ({400,422} if boleh else {403}),(role,gudang,endpoint,r.status_code,r.text)
        r=await c.post('/api/kemas-ulang',json={'sumber_id':0,'kunci':'0'*64,'jumlah_asal':1,'material':'biasa','ukuran':25,'jumlah_baru':1})
        assert r.status_code==(403 if gudang=='Gudang 1' else 400)

async def test_tautan_masuk_dan_bookmark_lama(pg,lengkap):
    sumber=['/','/aksi','/berjalan','/barang-keluar','/jasa','/riwayat-giling','/riwayat-sosoh','/laporan']
    hasil=[]
    async with await _klien(pg,peran='superadmin') as c:
        for page in sumber:
            r=await c.get(page);assert r.status_code==200,(page,r.status_code)
            links={unescape(h) for h in re.findall(r'href="([^"]+)"',r.text) if h.startswith('/stok')}
            for href in sorted(links):
                tujuan=await c.get(href);assert tujuan.status_code==200,(page,href,tujuan.status_code)
                hasil.append({'dari':page,'ke':href,'status':200})
        for lama,tab,owner in PASANGAN:
            url=lama+'?'+urlencode({'buka':'catat_packing','nilai':'POL-UJIJ-01|medium','gudang':'g2'})
            r=await c.get(url);assert r.status_code==200
            if lama!='/stok-karung-jasa':
                assert 'data-buka="catat_packing"' in r.text and 'POL-UJIJ-01|medium' in unescape(r.text),lama
            else:
                assert r.url.params['buka']=='catat_packing' and 'Pindah kepemilikan' not in r.text
            hasil.append({'bookmark':url,'tab':tab,'pemilik':owner,'status':200})
    assert hasil
    (OUT/'tautan-masuk.json').write_text(json.dumps(hasil,indent=2))

@pytest.mark.parametrize('endpoint,ident,table',[
 ('qc-giling',{'kode_proses':'LOT-KODE-01'},'milling_qc_logs'),
 ('qc-pk-luar',{'kode_batch':'PKB-KODE-01'},'pk_purchase_qc_logs'),
])
async def test_qc_dari_stok_audit_dan_pembatalan(pg,dunia,endpoint,ident,table):
    from app.services import undo
    from sqlalchemy import text
    async with await _klien(pg,peran='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        async with pg() as db:
            before=await db.scalar(text('select count(*) from '+table))
        r=await c.post('/api/actions/'+endpoint,json={**ident,'kadar_air':12.25,'butir_kuning':'bersih','gabah':'bersih','merang':'bersih'})
        assert r.status_code==200,r.text
        async with pg() as db:
            assert await db.scalar(text('select count(*) from '+table))==before+1
            log=await db.scalar(select(ActivityLog).where(ActivityLog.table_name==table).order_by(ActivityLog.id.desc()))
            actor=await db.get(User,log.changed_by)
            assert actor.nama=='Uji superadmin'
            await undo.undo_last(db,actor=actor,cakupan=undo.Cakupan([actor.id]),log_id=log.id)
        async with pg() as db:
            assert await db.scalar(text('select count(*) from '+table))==before
            assert (await db.get(ActivityLog,log.id)).dibatalkan_pada is not None

@pytest.mark.parametrize('url',[
 'https://contoh.invalid/stok?tab=produk','//contoh.invalid/stok','/barang-keluar',
 '/stok?tab=lain','/stok?pemilik=lain','/stok?pelanggan_id=-1','/stok?gudang=g3',
])
async def test_konteks_kembali_tidak_menerima_tujuan_sembarang(url):
    from app.web.stok_navigasi import kembali_aman
    assert kembali_aman(url)==''

async def test_tautan_pindah_produk_detail_membawa_konteks(pg,lengkap):
    origin='/stok?tab=produk&pemilik=jasa&pelanggan_id='+str(lengkap['pelanggan_id'])+'&gudang=g2'
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get('/stok-produk-jasa/detail',params={'jenis':'medium','pelanggan_id':lengkap['pelanggan_id'],'kembali_stok':origin})
        hrefs=[unescape(h) for h in re.findall(r'href="([^"]+)"',r.text) if 'buka=pindah_kepemilikan_produk' in h]
        assert hrefs
        for h in hrefs:
            assert urlsplit(h).path=='/stok-produk-jasa/detail'
            assert parse_qs(urlsplit(h).query)['kembali_stok']==[origin]
            assert (await c.get(h)).status_code==200
