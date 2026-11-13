"""Batas Console, keanggotaan per perusahaan, dan transaksi lama identik."""
import asyncio,json,secrets
from urllib.parse import urlsplit,parse_qs
import pytest
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from hmu_core import User,Perusahaan,LokasiPabrik,Warehouse,PenempatanGudang,KeanggotaanPerusahaan,AksesLokasiAnggota,AksesGudangAnggota
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from hmu_identitas.organisasi import konteks_kerja,OrganisasiTidakDiizinkan
from app.models import ActivityLog,SesiConsole
from app.services import console_auth as auth,keanggotaan as svc
from app.services.organisasi_master import OrganisasiError
from app.config import settings
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_pengaturan_organisasi import fakta
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_master_organisasi import organisasi,pilihan

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]


@pytest.fixture(autouse=True)
def console_config(monkeypatch):monkeypatch.setattr(settings,'console_website_url','https://website.uji')


async def sesi(c):
    verifier=secrets.token_urlsafe(48);state=secrets.token_urlsafe(32)
    r=await c.get('/console/otorisasi',params=dict(tantangan=auth.challenge(verifier),state=state),follow_redirects=False)
    assert r.status_code==303,r.text
    q=parse_qs(urlsplit(r.headers['location']).query);assert q['state']==[state]
    r=await c.post('/internal/console/tukar',json=dict(kode=q['kode'][0],verifier=verifier))
    assert r.status_code==200,r.text
    return dict(Authorization='Bearer '+r.json()['token'])


def grant(x,company=0,site=0,wh=0,all_=False):
    return dict(lokasi_pabrik_id=x['s'][company*2+site],semua_gudang=all_,gudang_ids=[] if all_ else [x['w'][company*4+site*2+wh]])


def payload(uid,*,lokasi=None,bukti=None,role=P.OPERATOR,aktif=True):
    return dict(user_id=uid,peran=role,aktif=aktif,lokasi=lokasi or [],bukti=svc.sidik(None) if bukti is None else bukti,alasan='Pengaturan akses berdasarkan penugasan yang disetujui')


async def anggota_api(c,h,cid,body):return await c.post(f'/internal/console/perusahaan/{cid}/anggota',headers=h,json=body)


def tanpa_admin(f):
    return {k:v for k,v in f.items() if k not in {'hmu_company_memberships','hmu_membership_sites','hmu_membership_warehouses','hmu_console_sessions','activity_logs'}}


@pytest.mark.parametrize('role',[P.ADMIN,P.OPERATOR])
async def test_non_super_tidak_dapat_menerbitkan_sesi_console(pg,role):
    async with await _klien(pg,peran=role) as c:
        before=await fakta(pg)
        r=await c.get('/console/otorisasi',params=dict(tantangan=auth.challenge('x'*43),state='s'*32));assert r.status_code==403
        assert (await c.get('/internal/console/perusahaan')).status_code==401
        assert await fakta(pg)==before


async def test_login_belum_ada_mempertahankan_tantangan_state(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        from app.web.security import NAMA_COOKIE
        c.cookies.delete(NAMA_COOKIE)
        r=await c.get('/console/otorisasi?tantangan='+auth.challenge('x'*43)+'&state='+'s'*32,follow_redirects=False)
        assert r.status_code==303
        nxt=parse_qs(urlsplit(r.headers['location']).query)['next'][0]
        assert 'tantangan=' in nxt and 'state=' in nxt and nxt.startswith('/console/otorisasi?')


async def test_bearer_console_terpisah_dan_tidak_mengubah_sesi_operator(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        from app.web.security import NAMA_COOKIE
        before=await fakta(pg);raw=c.cookies.get(NAMA_COOKIE)
        assert (await c.get('/internal/console/perusahaan',headers={'Authorization':'Bearer '+raw})).status_code==401
        h=await sesi(c)
        assert (await c.get('/internal/console/saya',headers=h)).status_code==200
        assert c.cookies.get(NAMA_COOKIE)==raw
        assert (await c.post('/internal/console/keluar',headers=h,json={})).status_code==200
        assert (await c.get('/internal/console/saya',headers=h)).status_code==401
        assert (await c.get('/pengaturan')).status_code==200
        after=await fakta(pg);assert {k:v for k,v in after.items() if k!='hmu_console_sessions'}=={k:v for k,v in before.items() if k!='hmu_console_sessions'}


async def test_kode_pkce_sekali_pakai_salah_verifier_tidak_mengonsumsi(pg):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        verifier=secrets.token_urlsafe(48)
        r=await c.get('/console/otorisasi',params=dict(tantangan=auth.challenge(verifier),state='s'*32),follow_redirects=False)
        code=parse_qs(urlsplit(r.headers['location']).query)['kode'][0]
        before=await fakta(pg)
        assert (await c.post('/internal/console/tukar',json=dict(kode=code,verifier='x'*64))).status_code==401
        assert await fakta(pg)==before
        results=await asyncio.gather(*[c.post('/internal/console/tukar',json=dict(kode=code,verifier=verifier)) for _ in range(2)])
        assert sorted(r.status_code for r in results)==[200,401]
        assert 'no-store' in r.headers['cache-control']


@pytest.mark.parametrize('field',['role','status','versi','dicabut','waktu','wajib_sandi'])
async def test_setiap_permintaan_console_memeriksa_pencabutan_terbaru(pg,field):
    from datetime import timedelta
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        h=await sesi(c)
        async with pg() as db:
            s=await db.scalar(select(SesiConsole));a=await db.get(Akun,s.akun_id)
            if field=='role':a.user.role=P.OPERATOR
            elif field=='status':a.user.status='nonaktif'
            elif field=='versi':a.token_version+=1
            elif field=='dicabut':s.dicabut=True
            elif field=='wajib_sandi':a.harus_ganti_sandi=True
            else:s.sesi_sampai=auth.now()-timedelta(seconds=1)
            await db.commit()
        before=await fakta(pg)
        assert (await c.get('/internal/console/perusahaan',headers=h)).status_code==401
        assert await fakta(pg)==before


async def test_keanggotaan_dan_akses_hanya_metadata_transaksi_tetap(pg,running,organisasi):
    x=organisasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        h=await sesi(c);before=await fakta(pg)
        body=payload(x['luar'],lokasi=[grant(x)])
        r=await anggota_api(c,h,x['c'][0],body);assert r.status_code==200,r.text
        assert tanpa_admin(await fakta(pg))==tanpa_admin(before)
        async with pg() as db:
            ctx=await konteks_kerja(db,user_id=x['luar'],company_id=x['c'][0],lokasi_pabrik_id=x['s'][0],warehouse_id=x['w'][0])
            assert ctx.peran==P.OPERATOR
            for w in (x['w'][1],x['w'][2],x['w'][4]):
                with pytest.raises(OrganisasiTidakDiizinkan):await konteks_kerja(db,user_id=x['luar'],company_id=x['c'][0],lokasi_pabrik_id=x['s'][0],warehouse_id=w)
            logs=list(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='keanggotaan_perusahaan')))
            assert len(logs)==1 and logs[0].alasan_perubahan==body['alasan'] and json.loads(logs[0].new_value)['lokasi']==body['lokasi']
            assert (await db.get(User,x['luar'])).role==P.SUPERADMIN
        saved=await fakta(pg)
        assert (await anggota_api(c,h,x['c'][0],body)).status_code==200
        assert await fakta(pg)==saved
        audit=(await c.get(f'/internal/console/perusahaan/{x["c"][0]}/audit',headers=h)).json()
        assert audit['catatan'][0]['alasan']==body['alasan'] and audit['catatan'][0]['sebelum'] is None


async def test_tanpa_pilihan_tidak_otomatis_mendapat_semua_lokasi(pg,organisasi):
    x=organisasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        h=await sesi(c)
        assert (await anggota_api(c,h,x['c'][0],payload(x['luar']))).status_code==200
        async with pg() as db:
            with pytest.raises(OrganisasiTidakDiizinkan):await konteks_kerja(db,**dict(pilihan(x),user_id=x['luar']))


@pytest.mark.parametrize('jenis',['perusahaan','lokasi','gudang','bool_id','peran_platform','status_teks','payload_asing','semua_dan_sebagian'])
async def test_payload_tidak_bisa_melompati_relasi_dan_peran(pg,organisasi,jenis):
    x=organisasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        h=await sesi(c);body=payload(x['luar'],lokasi=[grant(x)])
        if jenis=='perusahaan':body['lokasi']=[grant(x,company=1)]
        elif jenis=='lokasi':body['lokasi'][0]['lokasi_pabrik_id']=x['s'][1]
        elif jenis=='gudang':body['lokasi'][0]['gudang_ids']=[x['w'][4]]
        elif jenis=='bool_id':body['user_id']=True
        elif jenis=='peran_platform':body['peran']=P.SUPERADMIN
        elif jenis=='status_teks':body['aktif']='true'
        elif jenis=='payload_asing':body['role']=P.SUPERADMIN
        else:body['lokasi'][0]['semua_gudang']=True
        before=await fakta(pg)
        r=await anggota_api(c,h,x['c'][0],body)
        assert r.status_code==422,r.text
        assert await fakta(pg)==before


async def test_pembatasan_perusahaan_sendiri_dan_delegasi(pg,organisasi):
    x=organisasi;company_scope=svc.RuangAdministrasi(x['uid'],x['c'][0])
    async with pg() as db:
        with pytest.raises(PermissionError):await svc.rincian(db,ruang=company_scope,company_id=x['c'][1])
        # Kurangi cakupan Admin A secara eksplisit menjadi gudang pertama.
        await db.execute(__import__('sqlalchemy').delete(AksesLokasiAnggota).where(AksesLokasiAnggota.keanggotaan_id==x['m'][0]))
        db.add(AksesLokasiAnggota(keanggotaan_id=x['m'][0],company_id=x['c'][0],lokasi_pabrik_id=x['s'][0],semua_gudang=False));await db.flush()
        db.add(AksesGudangAnggota(keanggotaan_id=x['m'][0],company_id=x['c'][0],lokasi_pabrik_id=x['s'][0],warehouse_id=x['w'][0]));await db.commit()
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        h=await sesi(c);created=(await anggota_api(c,h,x['c'][0],payload(x['luar'],lokasi=[grant(x)]))).json()
        before=await fakta(pg)
        async with pg() as db:
            body=payload(x['luar'],lokasi=[grant(x,wh=1)],bukti=svc.sidik(created))
            with pytest.raises(PermissionError):await svc.simpan(db,ruang=company_scope,company_id=x['c'][0],**body)
        assert await fakta(pg)==before
        async with pg() as db:
            body=payload(x['luar'],lokasi=[grant(x)],bukti=svc.sidik(created),aktif=False)
            await svc.simpan(db,ruang=company_scope,company_id=x['c'][0],**body);await db.commit()
        assert tanpa_admin(await fakta(pg))==tanpa_admin(before)
        async with pg() as db:
            assert (await db.get(KeanggotaanPerusahaan,x['m'][1])).aktif
            assert (await db.get(User,x['luar'])).status=='aktif'


async def test_last_admin_dan_stale_form_ditolak(pg,organisasi):
    x=organisasi
    async with pg() as db:
        old=await svc.snapshot(db,await db.get(KeanggotaanPerusahaan,x['m'][0]))
        body=payload(x['uid'],lokasi=old['lokasi'],bukti=svc.sidik(old),role=P.OPERATOR)
        with pytest.raises(OrganisasiError,match='terakhir'):await svc.simpan(db,ruang=svc.RuangAdministrasi(x['uid'],x['c'][0]),company_id=x['c'][0],**body)
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        h=await sesi(c);body=payload(x['luar'],lokasi=[grant(x)])
        assert (await anggota_api(c,h,x['c'][0],body)).status_code==200
        saved=await fakta(pg);body['lokasi']=[grant(x,site=1)]
        assert (await anggota_api(c,h,x['c'][0],body)).status_code==422
        assert await fakta(pg)==saved


async def test_balapan_dua_penetapan_anggota_tidak_menimpa(pg,organisasi):
    x=organisasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        h=await sesi(c)
        results=await asyncio.wait_for(asyncio.gather(*[anggota_api(c,h,x['c'][0],payload(x['luar'],lokasi=[grant(x,site=i)])) for i in (0,1)]),timeout=20)
        assert sorted(r.status_code for r in results)==[200,422]
        async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='keanggotaan_perusahaan'))==1


async def test_gagal_audit_rollback_semua_hak_baru(pg,organisasi,monkeypatch):
    x=organisasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        h=await sesi(c);before=await fakta(pg)
        async def gagal(*args,**kwargs):raise RuntimeError('Simulasi audit gagal')
        monkeypatch.setattr(svc,'log_activity',gagal)
        with pytest.raises(RuntimeError):await anggota_api(c,h,x['c'][0],payload(x['luar'],lokasi=[grant(x)]))
        assert await fakta(pg)==before


@pytest.mark.parametrize('kasus',['keanggotaan','lokasi','gudang','tanpa_lokasi'])
async def test_fk_tidak_menerima_akses_lintas_perusahaan(pg,organisasi,kasus):
    x=organisasi
    async with pg() as db:
        before=await fakta(pg)
        with pytest.raises(IntegrityError):
            if kasus in ('keanggotaan','lokasi'):
                db.add(AksesLokasiAnggota(keanggotaan_id=x['m'][0],company_id=x['c'][1] if kasus=='keanggotaan' else x['c'][0],lokasi_pabrik_id=x['s'][3]))
            else:
                db.add(AksesGudangAnggota(keanggotaan_id=x['m'][0],company_id=x['c'][0],lokasi_pabrik_id=x['s'][0] if kasus=='gudang' else x['s'][3],warehouse_id=x['w'][4]))
            await db.flush()
        await db.rollback();assert await fakta(pg)==before


async def test_pembacaan_console_tidak_autoflush_draf(pg,organisasi):
    x=organisasi
    async with pg() as db:
        before=await fakta(pg)
        draft=User(nama='Draf belum disimpan',role=P.OPERATOR,status='aktif');db.add(draft)
        data=await svc.rincian(db,ruang=svc.RuangAdministrasi(x['uid']),company_id=x['c'][0])
        assert data['perusahaan']['id']==x['c'][0] and draft.id is None and draft in db.new
        await db.rollback();assert await fakta(pg)==before
