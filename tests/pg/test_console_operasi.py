"""Kebijakan nyata, batas perusahaan/produk dan seluruh pembacaan tanpa mutasi."""
import uuid
from datetime import timedelta
import pytest
from sqlalchemy import select,text,func
from hmu_core import KeanggotaanPerusahaan as M,ProdukAplikasiPerusahaan as CP,AksesProdukAnggota as UP,IntegrasiProdukPerusahaan as CI,User
from hmu_identitas.model import Akun
from hmu_identitas.monitoring import KejadianPemakaian as E,SumberMonitoring as S
from app.services import console_operasi as ops,console_monitoring as mon
from tests.pg.test_console_monitoring import orang,ev
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_pengaturan_organisasi import fakta
pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]

async def test_peta_hak_eksplisit_dan_terpisah_dari_gudang_administrasi(pg,orang):
    x=orang
    async with pg() as db:
        (await db.get(M,x['mid'])).aktif=True
        db.add_all([M(company_id=x['asing'],user_id=x['uid'],peran='admin',aktif=True),CP(company_id=x['asing'],produk='teraflow',aktif=True,warisan=False)]);await db.flush()
        db.add_all([UP(company_id=x['cid'],user_id=x['uid'],produk='padiflow',aktif=True,peran='admin'),UP(company_id=x['cid'],user_id=x['uid'],produk='teraflow',aktif=False,peran='operator'),UP(company_id=x['asing'],user_id=x['uid'],produk='teraflow',aktif=True,peran='operator')]);await db.commit()
    before=await fakta(pg)
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        data=await ops.peta_akses(db,user_id=x['uid']);by={c['company_id']:c for c in data['perusahaan']}
        pf,tf=by[x['cid']]['produk'];assert pf['izin_sesuai'] and pf['peran']=='admin' and pf['sumber']=='eksplisit'
        assert not tf['izin_sesuai'];assert by[x['asing']]['produk'][1]['operasional']=='belum_terhubung'
        assert all(w['kerja'] and not w['penetapan'] for w in by[x['cid']]['gudang'])
        selected=await ops.peta_akses(db,user_id=x['uid'],company_id=x['cid'],produk='teraflow')
        assert [p['kode'] for p in selected['perusahaan'][0]['produk']]==['teraflow'] and selected['perusahaan'][0]['gudang']==[]
        assert (await db.get(User,x['uid'])).role=='operator'
        await db.commit()
    assert await fakta(pg)==before

@pytest.mark.parametrize('field',['akun','pengguna','sandi','anggota','produk'])
async def test_peta_membaca_pencabutan_terkini_tanpa_cache_izin(pg,orang,field):
    x=orang
    async with pg() as db:(await db.get(M,x['mid'])).aktif=True;await db.commit()
    async with pg() as db:
        first=await ops.peta_akses(db,user_id=x['uid'],company_id=x['cid'],produk='padiflow');assert first['perusahaan'][0]['produk'][0]['izin_sesuai']
        async with pg() as other:
            if field=='akun':(await other.get(Akun,x['aid'])).status='nonaktif'
            elif field=='pengguna':(await other.get(User,x['uid'])).status='nonaktif'
            elif field=='sandi':(await other.get(Akun,x['aid'])).harus_ganti_sandi=True
            elif field=='anggota':(await other.get(M,x['mid'])).aktif=False
            else:(await other.get(CP,(x['cid'],'padiflow'))).aktif=False
            await other.commit()
        second=await ops.peta_akses(db,user_id=x['uid'],company_id=x['cid'],produk='padiflow')
        assert not second['perusahaan'][0]['produk'][0]['izin_sesuai']
        if field=='sandi':
            from app.services.console_bantuan import diagnosis
            d=await diagnosis(db,cid=x['cid'],jenis='staf',aid=x['aid'])
            assert not any(p['boleh'] for p in d['aplikasi'])

async def test_pencarian_username_literal_filter_dan_paginasi(pg,orang):
    x=orang;before=await fakta(pg)
    async with pg() as db:
        assert (await ops.cari_pengguna(db,cari='operator-aktif'))['pengguna'][0]['user_id']==x['uid']
        assert not (await ops.cari_pengguna(db,cari='%'))['pengguna']
        found=await ops.cari_pengguna(db,cari='operator',halaman=999);assert found['halaman']==found['halaman_total']
        assert not (await ops.cari_pengguna(db,company_id=x['asing'],cari='operator-aktif'))['pengguna']
    assert await fakta(pg)==before

async def test_gangguan_filter_produk_perusahaan_kategori_dan_waktu(pg,orang):
    x=orang
    async with pg() as db:
        await ev(db,x,typ='respons_web',code='500');await ev(db,x,typ='respons_web',code='403')
        await ev(db,x,typ='login',code='kredensial');await ev(db,x,typ='galat_browser')
        await ev(db,x,typ='respons_web',code='422');await ev(db,x,typ='respons_web',code='500',when=mon.sekarang()-timedelta(days=2))
        await ev(db,x,app='teraflow',typ='respons_web',code='503')
        db.add(E(company_id=x['asing'],aplikasi='padiflow',event_id=str(uuid.uuid4()),jenis_akun='staf',akun_id=x['aid'],jenis='respons_web',kode='500',layar='asing',peran='',metode='POST',browser='',perangkat=''))
        db.add(S(company_id=x['cid'],aplikasi='padiflow',versi='build-nyata',mulai=mon.sekarang(),terakhir=mon.sekarang()));await db.commit()
    before=await fakta(pg)
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        d=await ops.gangguan(db,produk='padiflow');assert d['total']==4 and d['jumlah']==dict(server=1,akses=1,login=1,browser=1)
        assert all(e['layar']!='asing' and e['aplikasi']!='teraflow' for e in d['kejadian'])
        assert d['layanan'][0]['pelaporan'][0]['versi']=='build-nyata'
        assert (await ops.gangguan(db,produk='teraflow',kategori='server'))['total']==1
        foreign=await ops.gangguan(db,company_id=x['asing']);assert not foreign['cakupan']['tersedia'] and foreign['total'] is None and not foreign['kejadian']
        await db.commit()
    assert await fakta(pg)==before

@pytest.mark.parametrize('pf,tf',[(True,False),(False,True),(False,False)])
async def test_produk_tidak_dipakai_tidak_memunculkan_alarm_atau_data_produk_lain(pg,orang,pf,tf):
    x=orang
    async with pg() as db:
        (await db.get(CP,(x['cid'],'padiflow'))).aktif=pf;(await db.get(CP,(x['cid'],'teraflow'))).aktif=tf
        for app in ('padiflow','portal','teraflow'):await ev(db,x,app=app,typ='respons_web',code='500')
        await db.commit()
    async with pg() as db:
        d=await ops.gangguan(db);assert d['total']==2*pf+tf
        assert all(not p['pelaporan'] for p in d['layanan'] if not p['aktif'])
        assert d['integrasi']['status']=='tidak_digunakan'

async def test_kasus_banyak_tidak_hilang_dari_total_dan_identitas_asing_tidak_ditautkan(pg,orang):
    x=orang
    async with pg() as db:
        for i in range(34):await ev(db,x,typ='respons_web',code='500')
        await ev(db,x,typ='respons_web',code='500',aid=999999);await db.commit()
    async with pg() as db:
        d=await ops.gangguan(db);assert d['total']==35 and len(d['kejadian'])==30 and d['halaman_total']==2
        assert d['kejadian'][0]['akun_id'] is None
        assert len((await ops.gangguan(db,halaman=999))['kejadian'])==5

@pytest.mark.parametrize('args',[dict(produk='asing'),dict(company_id=-1),dict(halaman=0),dict(jam=2),dict(kategori='payload')])
async def test_filter_gangguan_tidak_valid_tidak_menulis(pg,orang,args):
    before=await fakta(pg)
    async with pg() as db:
        with pytest.raises(ValueError):await ops.gangguan(db,**args)
        assert not db.new and not db.dirty and not db.deleted
    assert await fakta(pg)==before

async def test_endpoint_hanya_console_dan_get_serta_sidik_transaksi_tetap(pg,orang,monkeypatch):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.test_console_akses import sesi
    from app.config import settings
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    async with await _klien(pg,peran='superadmin') as c:
        assert (await c.get('/internal/console/gangguan')).status_code==401
        h=await sesi(c);before=await fakta(pg)
        for path in ('/internal/console/gangguan',f"/internal/console/peta-akses?user_id={orang['uid']}"):
            r=await c.get(path,headers=h);assert r.status_code==200,r.text
            assert 'no-store' in r.headers['cache-control'] and 'password_hash' not in r.text
            assert (await c.post(path,headers=h,json={})).status_code==405
        assert await fakta(pg)==before


async def test_peta_portal_terpisah_dari_id_staf_dan_produk_lain(pg,orang):
    x=orang;before=await fakta(pg)
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        search=await ops.peta_akun_lokal(db,jenis='pelanggan',cari='portal-uji')
        assert search['pengguna'][0]['akun_id']==x['portal'] and search['pengguna'][0]['user_id'] is None
        d=await ops.peta_akun_lokal(db,jenis='pelanggan',akun_id=x['portal'])
        assert d['jenis']=='pelanggan' and d['user_id'] is None and d['akun_id']==x['portal']
        assert d['perusahaan'][0]['produk'][0]['kode']=='padiflow'
        assert d['perusahaan'][0]['produk'][0]['operasional']=='diizinkan'
        for args in (dict(produk='teraflow'),dict(company_id=x['asing'])):
            with pytest.raises((ValueError,PermissionError)):await ops.peta_akun_lokal(db,jenis='pelanggan',akun_id=x['portal'],**args)
        assert (await ops.peta_akun_lokal(db,jenis='pelanggan',company_id=x['asing']))['total'] is None
        await db.commit()
    assert await fakta(pg)==before

async def test_perusahaan_nonaktif_tidak_menghasilkan_alarm_produk(pg,orang):
    from hmu_core import Perusahaan
    async with pg() as db:
        (await db.get(Perusahaan,orang['cid'])).aktif=False
        await ev(db,orang,typ='respons_web',code='500');await db.commit()
    async with pg() as db:
        d=await ops.gangguan(db);assert d['total']==0
        assert not any(p['aktif'] for p in d['layanan']) and d['integrasi']['status']=='tidak_digunakan'

async def test_pemeriksaan_tidak_memicu_autoflush_draf_pemanggil(pg,orang):
    async with pg() as db:
        u=await db.get(User,orang['uid']);u.nama='Draf tidak boleh tersimpan'
        with pytest.raises(ValueError):await ops.peta_akses(db,user_id=u.id)
        assert u in db.dirty


async def test_cari_id_pengguna_menerima_spasi_dan_seluruh_id_int32(pg,orang):
    async with pg() as db:
        db.add(User(id=2147483000,nama='Identitas ID panjang',role='operator',status='aktif'));await db.commit()
        for query in ('2147483000',' 2147483000 '):
            found=await ops.cari_pengguna(db,cari=query)
            assert [u['user_id'] for u in found['pengguna']]==[2147483000]
        assert not (await ops.cari_pengguna(db,cari='2147483648'))['pengguna']

@pytest.mark.parametrize('local_pf,local_tf,foreign_pf,foreign_tf',[(True,False,False,True),(False,True,True,False),(True,True,False,False)])
async def test_pengguna_lintas_perusahaan_tidak_mewarisi_izin_produk_perusahaan_lain(pg,orang,local_pf,local_tf,foreign_pf,foreign_tf):
    x=orang
    async with pg() as db:
        (await db.get(M,x['mid'])).aktif=True
        db.add(M(company_id=x['asing'],user_id=x['uid'],peran='admin',aktif=True))
        db.add_all([CP(company_id=x['asing'],produk=c,aktif=True,warisan=False) for c in ('padiflow','teraflow')]);await db.flush()
        for cid,flags in ((x['cid'],(local_pf,local_tf)),(x['asing'],(foreign_pf,foreign_tf))):
            for code,flag in zip(('padiflow','teraflow'),flags):db.add(UP(company_id=cid,user_id=x['uid'],produk=code,aktif=flag,peran='admin' if code=='padiflow' else 'operator'))
        await db.commit()
    before=await fakta(pg)
    async with pg() as db:
        for cid,flags in ((x['cid'],(local_pf,local_tf)),(x['asing'],(foreign_pf,foreign_tf))):
            for code,flag in zip(('padiflow','teraflow'),flags):
                d=await ops.peta_akses(db,user_id=x['uid'],company_id=cid,produk=code)
                co=d['perusahaan'][0];p=co['produk'][0]
                assert co['company_id']==cid and p['kode']==code and p['izin_sesuai']==flag
                assert p['operasional']!= 'diizinkan' or cid==x['cid']
    assert await fakta(pg)==before


async def test_penolakan_get_dari_kedua_produk_muncul_hanya_pada_cakupan_sendiri(pg,orang):
    from hmu_identitas.monitoring import MonitoringHTTP,PengumpulPemakaian,PelakuPemakaian
    x=orang;before=await fakta(pg)
    async def blocked(scope,receive,send):
        await send(dict(type='http.response.start',status=403,headers=[]))
        await send(dict(type='http.response.body',body=b'akses ditolak'))
    async def send(msg):pass
    for app in ('padiflow','teraflow'):
        collector=PengumpulPemakaian(pg,app,'versi-data-uji')
        await MonitoringHTTP(blocked,pengumpul=collector,pelaku=lambda _:PelakuPemakaian('staf',x['aid'],x['uid']))(dict(type='http',method='GET',path='/stok',state={},headers=[]),None,send)
        await collector.kirim()
    async with pg() as db:
        for code,app in [('padiflow','padiflow'),('teraflow','teraflow')]:
            d=await ops.gangguan(db,produk=code,kategori='akses')
            assert d['jumlah']['akses']==1 and len(d['kejadian'])==1 and d['kejadian'][0]['aplikasi']==app
        d=await ops.gangguan(db,company_id=x['asing']);assert d['total'] is None and d['kejadian']==[]
    after=await fakta(pg);metadata={'hmu_usage_events','hmu_monitoring_sources'}
    assert {k:v for k,v in before.items() if k not in metadata}=={k:v for k,v in after.items() if k not in metadata}
