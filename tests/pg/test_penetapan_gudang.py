"""Penetapan administratif atomik, bukan pemindahan transaksi/stock tenant."""
import asyncio
import json
from urllib.parse import urlencode
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select,func
from hmu_core import Perusahaan,LokasiPabrik,PenempatanGudang,Warehouse,User
from hmu_identitas import peran as P
from app.models import ActivityLog
from app.services import organisasi_rencana as r
from app.services.organisasi_master import OrganisasiError
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_pengaturan_organisasi import BASE,fakta,master_lokasi
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.formulir import cap_formulir

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]
ALASAN='Menetapkan gudang lama setelah pemeriksaan tujuan'


def tanpa_penetapan(f):
    return {k:v for k,v in f.items() if k not in {'hmu_warehouse_sites','activity_logs'}}


@pytest.fixture
async def gudang(pg):
    async with pg() as db:
        wh=[Warehouse(nama_gudang='Gudang uji satu'),Warehouse(nama_gudang='Gudang uji dua')]
        db.add_all(wh);await db.commit();return [w.id for w in wh]


async def preview(c,site,ids):
    query=urlencode([('periksa','1'),('lokasi_pabrik_id',site)]+[('warehouse_id',i) for i in ids])
    page=await c.get(BASE+'/penetapan?'+query);assert page.status_code==200,page.text[-1200:]
    soup=BeautifulSoup(page.text,'html.parser')
    f=soup.select_one('form[action$="/penetapan/terapkan"]')
    return soup,dict(_csrf=cap_formulir(c),bukti=f.select_one('input[name=bukti]')['value'],alasan=ALASAN,konfirmasi='on') if f else None


async def post(c,data):
    return await c.post(BASE+'/penetapan/terapkan',data=data)


async def test_penetapan_hanya_menambah_binding_audit_transaksi_tetap(pg,running,master_lokasi):
    a,b,sa,sb=master_lokasi
    async with pg() as db:ids=list(await db.scalars(select(Warehouse.id).order_by(Warehouse.id)))
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        before=await fakta(pg)
        soup,data=await preview(c,sa,ids)
        assert data and '30 menit' in soup.get_text() and await fakta(pg)==before
        response=await post(c,data);assert response.status_code==200,response.text[-1000:]
        assert 'Penetapan gudang tersimpan.' in response.text
        after=await fakta(pg);assert tanpa_penetapan(after)==tanpa_penetapan(before)
        async with pg() as db:
            bindings=list(await db.scalars(select(PenempatanGudang).order_by(PenempatanGudang.warehouse_id)))
            logs=list(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='penetapan_gudang')))
            assert [v.warehouse_id for v in bindings]==ids and all(v.company_id==a and v.lokasi_pabrik_id==sa for v in bindings)
            assert len(logs)==len(ids) and all(x.old_value is None and x.alasan_perubahan==ALASAN and x.changed_by for x in logs)
            assert {json.loads(x.new_value)['warehouse_id'] for x in logs}==set(ids)
        saved=await fakta(pg)
        assert (await post(c,data)).status_code==200
        assert await fakta(pg)==saved
        soup,noop=await preview(c,sa,ids)
        assert noop is None and 'Semua gudang sudah sesuai' in soup.get_text() and await fakta(pg)==saved
        audit=await c.get('/audit?rentang=semua&cari=hmu_warehouse_sites')
        assert audit.status_code==200 and 'penetapan gudang' in audit.text
        assert ALASAN in response.text and 'Riwayat penetapan gudang' in response.text and 'Belum ditetapkan' in response.text


async def test_pratinjau_campuran_sudah_sesuai_tidak_menulis_ulang(pg,gudang,master_lokasi):
    a,b,sa,sb=master_lokasi
    async with pg() as db:
        old=PenempatanGudang(warehouse_id=gudang[0],company_id=a,lokasi_pabrik_id=sa);db.add(old);await db.commit();stamp=old.updated_at
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,sa,gudang);assert data
        assert (await post(c,data)).status_code==200
        async with pg() as db:
            assert (await db.get(PenempatanGudang,gudang[0])).updated_at==stamp
            logs=list(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='penetapan_gudang')))
            assert len(logs)==1 and logs[0].record_id==gudang[1]


@pytest.mark.parametrize('jenis',['konflik','nonaktif'])
async def test_satu_gudang_terhalang_membatalkan_seluruh_rencana(pg,gudang,master_lokasi,jenis):
    a,b,sa,sb=master_lokasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,sa,gudang)
        async with pg() as db:
            if jenis=='konflik':db.add(PenempatanGudang(warehouse_id=gudang[1],company_id=b,lokasi_pabrik_id=sb))
            else:(await db.get(Warehouse,gudang[1])).aktif=False
            await db.commit()
        before=await fakta(pg)
        result=await post(c,data);assert result.status_code==422 and ALASAN in result.text
        assert await fakta(pg)==before
        soup,data2=await preview(c,sa,gudang)
        assert data2 is None and 'Belum dapat diterapkan' in soup.get_text()
        assert await fakta(pg)==before


@pytest.mark.parametrize('jenis',['nama_gudang','nama_lokasi','lokasi_nonaktif','perusahaan_nonaktif'])
async def test_pratinjau_usang_ditolak_tanpa_mutasi(pg,gudang,master_lokasi,jenis):
    a,b,sa,sb=master_lokasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,sa,gudang)
        async with pg() as db:
            if jenis=='nama_gudang':(await db.get(Warehouse,gudang[0])).nama_gudang='Nama terkini'
            elif jenis=='nama_lokasi':(await db.get(LokasiPabrik,sa)).nama='Nama terkini'
            elif jenis=='lokasi_nonaktif':(await db.get(LokasiPabrik,sa)).aktif=False
            else:(await db.get(Perusahaan,a)).aktif=False
            await db.commit()
        before=await fakta(pg);result=await post(c,data)
        assert result.status_code==422 and ALASAN in result.text
        assert 'Terapkan penetapan gudang' not in result.text
        assert await fakta(pg)==before


@pytest.mark.parametrize('jenis',['kosong','rusak','payload_tujuan','tanpa_konfirmasi','alasan','kedaluwarsa','duplikat_field','kunci_kosong'])
async def test_bukti_dan_isian_wajib_tidak_dapat_dilewati(pg,gudang,master_lokasi,monkeypatch,jenis):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,master_lokasi[2],gudang)
        before=await fakta(pg)
        if jenis=='kosong':data.pop('bukti')
        elif jenis=='rusak':data['bukti']=data['bukti'][:-2]+'zz'
        elif jenis=='payload_tujuan':data.update(lokasi_pabrik_id=master_lokasi[3],warehouse_id=gudang)
        elif jenis=='tanpa_konfirmasi':data.pop('konfirmasi')
        elif jenis=='alasan':data['alasan']=' '
        elif jenis=='kunci_kosong':
            import hmac,hashlib
            isi=data['bukti'].split('.')[0]
            data['bukti']=isi+'.'+hmac.new(b'',b'penetapan-gudang-v1:'+isi.encode(),hashlib.sha256).hexdigest()
        elif jenis=='kedaluwarsa':
            now=r.time.time();monkeypatch.setattr(r.time,'time',lambda:now+r.UMUR_PRATINJAU+1)
        else:data['bukti']=[data['bukti'],data['bukti']]
        assert (await post(c,data)).status_code==422
        assert await fakta(pg)==before


async def test_csrf_dan_bukti_akun_lain_ditolak(pg,gudang,master_lokasi):
    async with await _klien(pg,peran=P.SUPERADMIN) as c, await _klien(pg,peran=P.SUPERADMIN) as other:
        _,data=await preview(c,master_lokasi[2],gudang);before=await fakta(pg)
        assert (await post(c,{k:v for k,v in data.items() if k!='_csrf'})).status_code==403
        assert (await post(other,{**data,'_csrf':cap_formulir(other)})).status_code==422
        assert await fakta(pg)==before


@pytest.mark.parametrize('role',[P.ADMIN,P.OPERATOR])
async def test_izin_writer_langsung_juga_menolak_non_super(pg,gudang,master_lokasi,role):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,master_lokasi[2],gudang)
        async with pg() as db:
            user=User(nama='Pemakai tidak berhak',role=role,status='aktif');db.add(user);await db.commit();uid=user.id
        before=await fakta(pg)
        async with pg() as db:
            with pytest.raises(PermissionError):await r.terapkan(db,user_id=uid,bukti=data['bukti'],alasan=ALASAN)
        assert await fakta(pg)==before


async def test_dua_kiriman_sama_idempoten_tanpa_audit_ganda(pg,gudang,master_lokasi):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,master_lokasi[2],gudang)
        responses=await asyncio.wait_for(asyncio.gather(post(c,data),post(c,data)),timeout=20)
        assert [x.status_code for x in responses]==[200,200]
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(PenempatanGudang))==len(gudang)
            assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='penetapan_gudang'))==len(gudang)


async def test_dua_tujuan_bersaing_hanya_satu_yang_diterapkan(pg,gudang,master_lokasi):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,a=await preview(c,master_lokasi[2],gudang)
        _,b=await preview(c,master_lokasi[3],list(reversed(gudang)))
        results=await asyncio.wait_for(asyncio.gather(post(c,a),post(c,b)),timeout=20)
        assert sorted(x.status_code for x in results)==[200,422]
        async with pg() as db:
            rows=list(await db.scalars(select(PenempatanGudang)))
            assert len(rows)==len(gudang) and len({x.lokasi_pabrik_id for x in rows})==1
            assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='penetapan_gudang'))==len(gudang)


async def test_gagal_audit_kedua_rollback_seluruh_penetapan(pg,gudang,master_lokasi,monkeypatch):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,master_lokasi[2],gudang)
        original=r.log_activity;counter=0
        async def gagal(*args,**kw):
            nonlocal counter
            counter+=1
            if counter==2:raise RuntimeError('Simulasi kegagalan audit')
            await original(*args,**kw)
            await args[0].flush()
        monkeypatch.setattr(r,'log_activity',gagal)
        before=await fakta(pg)
        with pytest.raises(RuntimeError,match='Simulasi'):await post(c,data)
        assert await fakta(pg)==before


async def test_writer_tidak_mengikutkan_draf_orm(pg,gudang,master_lokasi):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,master_lokasi[2],gudang)
        payload=json.loads(__import__('base64').urlsafe_b64decode(data['bukti'].split('.')[0]))
        before=await fakta(pg)
        async with pg() as db:
            draft=User(nama='Draf operator',role=P.OPERATOR,status='aktif');db.add(draft)
            with pytest.raises(OrganisasiError,match='transaksi tersendiri'):
                await r.terapkan(db,user_id=payload['user_id'],bukti=data['bukti'],alasan=ALASAN)
            assert draft.id is None
        assert await fakta(pg)==before


async def test_audit_penetapan_tidak_menggeser_undo_operator(pg,running,master_lokasi):
    from app.services.undo import _log_terakhir
    from app.services.activity_log import log_activity
    from app.models import PolishingOutputLog
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        async with pg() as db:
            output=await db.scalar(select(PolishingOutputLog))
            await log_activity(db,table_name='polishing_output_logs',record_id=output.id,action='INSERT',changed_by=output.input_by,new_value='Hasil uji')
            await db.commit();last=(await _log_terakhir(db,None)).id
            ids=list(await db.scalars(select(Warehouse.id)))
        _,data=await preview(c,master_lokasi[2],ids)
        assert (await post(c,data)).status_code==200
        async with pg() as db:assert (await _log_terakhir(db,None)).id==last


async def test_riwayat_lengkap_berhalaman_dan_nama_snapshot_tetap(pg,master_lokasi):
    async with pg() as db:
        wh=[Warehouse(nama_gudang=f'Gudang riwayat {i:02d}') for i in range(51)]
        db.add_all(wh);await db.commit();ids=[w.id for w in wh]
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,master_lokasi[2],ids)
        saved=await post(c,data);assert saved.status_code==200
        soup=BeautifulSoup(saved.text,'html.parser')
        assert len(soup.select('[aria-labelledby="org-jejak"] article'))==50
        older=soup.find('a',string='Riwayat lebih lama');assert older
        async with pg() as db:
            (await db.get(Perusahaan,master_lokasi[0])).nama='Nama master diperbarui'
            await db.commit()
        before=await fakta(pg)
        old=await c.get(older['href']);soup=BeautifulSoup(old.text,'html.parser')
        rows=soup.select('[aria-labelledby="org-jejak"] article')
        assert len(rows)==1 and 'Perusahaan A' in rows[0].get_text() and ALASAN in rows[0].get_text()
        assert 'Uji superadmin' in rows[0].get_text() and 'Belum ditetapkan' in rows[0].get_text()
        assert soup.find('a',string='Riwayat terbaru')
        assert (await c.get(f'{BASE}/lokasi/{master_lokasi[2]}?sebelum=abc')).status_code==422
        assert await fakta(pg)==before


async def test_penempatan_tidak_menahan_pemakaian_fk_gudang_operator(pg,gudang,master_lokasi):
    from hmu_core import Silo
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,master_lokasi[2],gudang)
        actor=json.loads(__import__('base64').urlsafe_b64decode(data['bukti'].split('.')[0]))['user_id']
        async with pg() as setting:
            await r.terapkan(setting,user_id=actor,bukti=data['bukti'],alasan=ALASAN)
            async def pekerjaan():
                async with pg() as ops:
                    ops.add(Silo(nama_silo='Fasilitas uji FK',warehouse_id=gudang[0],status='kosong'))
                    await ops.flush()
                    await ops.rollback()
            await asyncio.wait_for(pekerjaan(),timeout=3)
            await setting.commit()


async def test_perubahan_fasilitas_minta_pratinjau_baru(pg,gudang,master_lokasi):
    from hmu_core import Silo
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        _,data=await preview(c,master_lokasi[2],gudang)
        async with pg() as db:
            db.add(Silo(nama_silo='Silo baru',warehouse_id=gudang[0],status='kosong'));await db.commit()
        before=await fakta(pg)
        result=await post(c,data)
        assert result.status_code==422 and 'Data gudang atau tujuan sudah berubah' in result.text
        assert await fakta(pg)==before
