"""HTTP nyata: kelola master; master dan penetapan dengan pratinjau wajib."""
import json
from urllib.parse import urlencode
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select,func
from hmu_core import Perusahaan,LokasiPabrik,PenempatanGudang,KeanggotaanPerusahaan,Warehouse,User
from hmu_identitas import peran as P
from app.models import ActivityLog
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
from tests.pg.test_masuk_detail_timbang import sidik
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from app.services import organisasi_master as master

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]
BASE='/pengaturan/organisasi'


async def fakta(pg):
    async with pg() as db:return await sidik(db)


def tanpa_master(f):
    return {k:v for k,v in f.items() if k not in {'hmu_companies','hmu_factory_sites','activity_logs'}}


def data(c,**kw):
    return dict(_csrf=cap_formulir(c),nama='Perusahaan uji',kode='uji-a',aktif='on',alasan='Penambahan untuk persiapan organisasi',**kw)


@pytest.fixture
async def master_lokasi(pg):
    async with pg() as db:
        a=Perusahaan(kode='uji-a',nama='Perusahaan A');b=Perusahaan(kode='uji-b',nama='Perusahaan B')
        db.add_all([a,b]);await db.flush()
        sites=[LokasiPabrik(company_id=a.id,kode='pusat',nama='Pabrik pusat'),LokasiPabrik(company_id=b.id,kode='pusat',nama='Pabrik pusat')]
        db.add_all(sites);await db.commit();return a.id,b.id,sites[0].id,sites[1].id


async def test_pintu_berada_di_kelompok_perusahaan_sebelum_gudang(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        r=await c.get('/pengaturan');assert r.status_code==200
        soup=BeautifulSoup(r.text,'html.parser');group=soup.select_one('section[aria-labelledby="pg-fasilitas"]')
        links=[a['href'] for a in group.select('a[href]')]
        assert links.index('/pengaturan/perusahaan-sendiri')<links.index('/pengaturan/gudang')
        assert '/pengaturan/perusahaan' in links
        assert group.select_one('a[href="/pengaturan/perusahaan-sendiri"]').get_text(strip=True).startswith('Perusahaan saya')


async def test_tambah_edit_audit_dan_identitas_transaksi_tetap(pg,running):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        awal=await fakta(pg)
        r=await c.post(BASE+'/perusahaan/baru',data=data(c));assert r.status_code==200,r.text[-1500:]
        async with pg() as db:
            company=await db.scalar(select(Perusahaan));cid=company.id
            assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='hmu_companies'))==1
        assert tanpa_master(await fakta(pg))==tanpa_master(awal)
        r=await c.post(f'{BASE}/perusahaan/{cid}/lokasi/baru',data={**data(c),'nama':'Pabrik utara','kode':'utara','alamat':'Alamat uji'})
        assert r.status_code==200
        async with pg() as db:site=await db.scalar(select(LokasiPabrik));site_id=site.id
        page=await c.get(f'{BASE}/lokasi/{site_id}');s=BeautifulSoup(page.text,'html.parser');token=s.select_one('input[name=sidik]')['value']
        r=await c.post(f'{BASE}/lokasi/{site_id}',data={**data(c),'nama':'Nama baru <aman>','kode':'utara','alamat':'Jalan baru','sidik':token})
        assert r.status_code==200 and 'Nama baru &lt;aman&gt;' in r.text
        async with pg() as db:
            site=await db.get(LokasiPabrik,site_id);assert site.company_id==cid and site.alamat=='Jalan baru'
            logs=list(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='hmu_factory_sites').order_by(ActivityLog.id)))
            assert len(logs)==2 and json.loads(logs[-1].old_value)['nama']=='Pabrik utara'
            assert json.loads(logs[-1].new_value)['nama']=='Nama baru <aman>' and logs[-1].alasan_perubahan
        assert tanpa_master(await fakta(pg))==tanpa_master(awal)
        # Penyimpanan ulang formulir lama tidak menimpa nama terbaru atau menambah audit.
        before=await fakta(pg)
        r=await c.post(f'{BASE}/lokasi/{site_id}',data={**data(c),'nama':'Draf usang','kode':'utara','sidik':token,'alamat':'Draf'})
        assert r.status_code==422 and 'Data sudah berubah' in r.text and 'Draf usang' in r.text
        assert BeautifulSoup(r.text,'html.parser').select_one('input[name=sidik]')['value']==token
        assert await fakta(pg)==before


@pytest.mark.parametrize('role',[P.ADMIN,P.OPERATOR])
async def test_hanya_super_bahkan_jika_belum_ada_super_aktif(pg,role):
    async with await _klien(pg,peran=role) as c:
        before=await fakta(pg)
        for path in [BASE,BASE+'/penetapan',BASE+'/perusahaan/1',BASE+'/lokasi/1']:
            assert (await c.get(path)).status_code==403
        for path in [BASE+'/perusahaan/baru',BASE+'/perusahaan/1',BASE+'/perusahaan/1/lokasi/baru',BASE+'/lokasi/1',BASE+'/penetapan/terapkan']:
            assert (await c.post(path,data=data(c))).status_code==403
        assert await fakta(pg)==before


async def test_csrf_dan_payload_penempatan_ditolak(pg,master_lokasi):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        before=await fakta(pg)
        assert (await c.post(BASE+'/perusahaan/baru',data={'nama':'Tanpa csrf'})).status_code==403
        r=await c.post(BASE+'/perusahaan/baru',data={**data(c),'warehouse_id':'1','company_id':str(master_lokasi[0])})
        assert r.status_code==422 and 'Isian tidak dikenal' in r.text
        for bad in ('perusahaan/0','lokasi/0'):
            assert (await c.get(BASE+'/'+bad)).status_code==404
            assert (await c.post(BASE+'/'+bad,data=data(c))).status_code==404
        assert await fakta(pg)==before


async def test_pratinjau_menampilkan_konflik_fasilitas_dan_tidak_menulis(pg,running,master_lokasi):
    a,b,sa,sb=master_lokasi
    async with pg() as db:
        wh=list(await db.scalars(select(Warehouse).order_by(Warehouse.id)))
        db.add(PenempatanGudang(company_id=b,lokasi_pabrik_id=sb,warehouse_id=wh[0].id));await db.commit()
        ids=[w.id for w in wh]
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        before=await fakta(pg)
        q=urlencode([('periksa','1'),('lokasi_pabrik_id',sa)]+[('warehouse_id',i) for i in ids])
        r=await c.get(BASE+'/penetapan?'+q);assert r.status_code==200,r.text[-1500:]
        s=BeautifulSoup(r.text,'html.parser');plan=s.select_one('[data-rencana-penetapan]')
        assert plan and 'Perusahaan A' in plan.get_text() and 'Lokasi berbeda' in plan.get_text()
        assert 'silo' in plan.get_text() and 'dryer' in plan.get_text() and 'line' in plan.get_text()
        assert not s.select('.org form[method=post]')
        assert await fakta(pg)==before
        # Payload lama tanpa bukti pratinjau tetap ditolak; URL tebakan lain tidak tersedia.
        for path in [BASE+'/penetapan',BASE+'/penetapan/terapkan',BASE+'/penetapan/simpan',BASE+'/penetapan/commit']:
            assert (await c.post(path,data={**data(c),'lokasi_pabrik_id':sa,'warehouse_id':ids})).status_code in ((422,) if path.endswith('/terapkan') else (404,405))
        assert await fakta(pg)==before


@pytest.mark.parametrize('query',['periksa=1','periksa=1&lokasi_pabrik_id=abc','periksa=1&lokasi_pabrik_id=999&warehouse_id=1'])
async def test_pratinjau_input_tidak_sah_tanpa_mutasi(pg,query):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        before=await fakta(pg);r=await c.get(BASE+'/penetapan?'+query)
        assert r.status_code==422 and 'role="alert"' in r.text
        assert await fakta(pg)==before


async def test_kode_dan_perusahaan_lokasi_tetap_serta_induk_nonaktif_dijaga(pg,master_lokasi):
    a,b,sa,sb=master_lokasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        async with pg() as db:site=await db.get(LokasiPabrik,sa);token=master.sidik(site)
        before=await fakta(pg)
        r=await c.post(f'{BASE}/lokasi/{sa}',data={**data(c),'kode':'ubah-kode','sidik':token,'alamat':''})
        assert r.status_code==422 and await fakta(pg)==before
        r=await c.post(f'{BASE}/lokasi/{sa}',data={**data(c),'kode':'pusat','sidik':token,'alamat':'','company_id':b})
        assert r.status_code==422 and await fakta(pg)==before
        async with pg() as db:co=await db.get(Perusahaan,a);token=master.sidik(co)
        r=await c.post(f'{BASE}/perusahaan/{a}',data={k:v for k,v in {**data(c),'sidik':token}.items() if k!='aktif'})
        assert r.status_code==422 and 'masih digunakan' in r.text
        assert await fakta(pg)==before


async def test_super_yang_sedang_lihat_sebagai_operator_tidak_mengelola_master(pg):
    from app.web.lihat_sebagai import NAMA_KUKI
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        c.cookies.set(NAMA_KUKI,P.OPERATOR+':'+P.G1)
        before=await fakta(pg)
        assert (await c.get(BASE)).status_code==403
        assert (await c.post(BASE+'/perusahaan/baru',data=data(c))).status_code==403
        assert (await c.post(BASE+'/penetapan/terapkan',data=data(c))).status_code==403
        assert await fakta(pg)==before


async def test_pratinjau_tidak_autoflush_draf_dan_lokasi_nonaktif_ditolak(pg,master_lokasi):
    from app.services.organisasi_rencana import pratinjau
    a,b,sa,sb=master_lokasi
    async with pg() as db:
        w=Warehouse(nama_gudang='Gudang lama',aktif=True);db.add(w);await db.commit();wid=w.id
        before=await sidik(db)
        draft=User(nama='Draf tidak disimpan',role=P.OPERATOR,status='aktif');db.add(draft)
        plan=await pratinjau(db,lokasi_pabrik_id=sa,warehouse_ids=[wid,wid])
        assert len(plan.gudang)==1 and draft.id is None and draft in db.new
        await db.rollback();assert await sidik(db)==before
        s=await db.get(LokasiPabrik,sa);s.aktif=False;await db.commit();before=await sidik(db)
        with pytest.raises(master.OrganisasiError,match='tidak aktif'):await pratinjau(db,lokasi_pabrik_id=sa,warehouse_ids=[wid])
        assert await sidik(db)==before


async def test_dua_formulir_bersamaan_hanya_satu_perubahan_dan_noop_tidak_menambah_audit(pg,master_lokasi):
    import asyncio
    a,b,sa,sb=master_lokasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        async with pg() as db:co=await db.get(Perusahaan,a);token=master.sidik(co)
        before=await fakta(pg)
        unchanged={**data(c),'nama':'Perusahaan A','sidik':token}
        assert (await c.post(f'{BASE}/perusahaan/{a}',data=unchanged)).status_code==200
        assert await fakta(pg)==before
        results=await asyncio.gather(*[c.post(f'{BASE}/perusahaan/{a}',data={**unchanged,'nama':n}) for n in ('Nama satu','Nama dua')])
        assert sorted(r.status_code for r in results)==[200,422]
        after=await fakta(pg);assert tanpa_master(after)==tanpa_master(before)
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='hmu_companies'))==1
            assert (await db.get(Perusahaan,a)).nama in ('Nama satu','Nama dua')


async def test_portal_tidak_mendapat_akses_master_organisasi(pg):
    from app.models.portal import PortalAccount
    from app.models import Pelanggan
    from tests.pg.test_portal_pelanggan import client
    async with pg() as db:
        p=Pelanggan(nama_pelanggan='Pelanggan uji');db.add(p);await db.flush()
        a=PortalAccount(username='organisasi-portal',pelanggan_id=p.id,password_hash='x',active=True,token_version=1)
        db.add(a);await db.commit()
    async with client(a) as c:
        before=await fakta(pg)
        for path in (BASE,BASE+'/penetapan'):
            assert (await c.get(path)).status_code in (303,401,403)
        assert await fakta(pg)==before


async def test_audit_master_terbaca_tanpa_menggeser_pembatalan_pekerjaan(pg,running):
    from app.models import PolishingOutputLog
    from app.services.activity_log import log_activity
    from app.services.undo import _log_terakhir
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        async with pg() as db:
            output=await db.scalar(select(PolishingOutputLog).order_by(PolishingOutputLog.id))
            await log_activity(db,table_name='polishing_output_logs',record_id=output.id,action='INSERT',changed_by=output.input_by,new_value='Hasil proses uji')
            await db.commit();last=(await _log_terakhir(db,None)).id
        before=await fakta(pg)
        r=await c.post(BASE+'/perusahaan/baru',data=data(c));assert r.status_code==200
        async with pg() as db:assert (await _log_terakhir(db,None)).id==last
        page=await c.get('/audit?rentang=semua&cari=uji-a')
        assert page.status_code==200 and 'master perusahaan' in page.text and 'Perusahaan uji' in page.text
        assert tanpa_master(await fakta(pg))==tanpa_master(before)
