"""Regresi Console: input sensitif, bantuan, master dan batas daftar akun."""
import json
from datetime import timedelta
import pytest,httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from hmu_core import User,Perusahaan
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from app.main import app
from app.services import console_monitoring as mon,console_bantuan as bantuan,keanggotaan
from tests.pg.test_console_monitoring import orang
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_pengaturan_organisasi import fakta

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]

async def test_validasi_pemulihan_tidak_memantulkan_sandi_cap_atau_input_lain(pg,orang,caplog):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        page=await c.get('/pemulihan')
        csrf=BeautifulSoup(page.text,'html.parser').select_one('[data-csrf-pemulihan]')['value']
        headers={'X-CSRF-Token':csrf}
        for path,payload,secrets in [
            ('simpan',dict(cap='C'*64,sandi='R4H4S14',ulangi='R4H4S14'),['R4H4S14','C'*64]),
            ('simpan',dict(cap='D'*64,sandi='sandi-baru-uji',ulangi='sandi-baru-uji',tambahan='jangan-pantulkan'),['sandi-baru-uji','D'*64,'jangan-pantulkan']),
            ('periksa',dict(cap='cap-tidak-lengkap-rahasia'),['cap-tidak-lengkap-rahasia'])]:
            before=await fakta(pg)
            r=await c.post('/pemulihan/'+path,json=payload,headers=headers)
            assert r.status_code==422 and isinstance(r.json()['detail'],str)
            assert all(secret not in r.text+caplog.text for secret in secrets)
            assert await fakta(pg)==before

@pytest.mark.parametrize('lama',[False,True])
async def test_login_baru_tidak_membatalkan_pratinjau_bantuan(pg,orang,lama):
    x=orang
    async with pg() as db:
        plan=await bantuan.pratinjau(db,cid=x['cid'],jenis='staf',aid=x['aid'],pelaku_id=x['root'],aksi='cabut_sesi',alasan='Pemilik meminta mengakhiri sesi perangkat lama')
        if lama:
            from hmu_identitas.monitoring import RencanaBantuan
            row=await db.get(RencanaBantuan,plan['id']);row.sidik=bantuan.hash_(row.sebelum)
        await db.commit()
        (await db.get(Akun,x['aid'])).terakhir_login=mon.sekarang()+timedelta(seconds=1)
        await db.commit()
    async with pg() as db:
        result=await bantuan.terapkan(db,cid=x['cid'],jenis='staf',aid=x['aid'],pelaku_id=x['root'],plan_id=plan['id'])
        await db.commit()
        assert not result['sudah'] and (await db.get(Akun,x['aid'])).token_version==2

async def test_keanggotaan_tidak_diaktifkan_di_perusahaan_nonaktif(pg,orang):
    x=orang
    async with pg() as db:
        plan=await bantuan.pratinjau(db,cid=x['cid'],jenis='staf',aid=x['aid'],pelaku_id=x['root'],aksi='aktifkan_keanggotaan',alasan='Memulihkan izin perusahaan yang sudah tersimpan')
        await db.commit()
        (await db.get(Perusahaan,x['cid'])).aktif=False
        await db.commit()
    before=await fakta(pg)
    async with pg() as db:
        with pytest.raises(ValueError,match='perusahaan'):
            await bantuan.terapkan(db,cid=x['cid'],jenis='staf',aid=x['aid'],pelaku_id=x['root'],plan_id=plan['id'])
        await db.rollback()
        diagnosis=await bantuan.diagnosis(db,cid=x['cid'],jenis='staf',aid=x['aid'])
        assert 'aktifkan_keanggotaan' not in diagnosis['tindakan']
        with pytest.raises(ValueError,match='perusahaan'):
            await bantuan.pratinjau(db,cid=x['cid'],jenis='staf',aid=x['aid'],pelaku_id=x['root'],aksi='aktifkan_keanggotaan',alasan='Permintaan tidak boleh melewati status induk')
    assert await fakta(pg)==before

async def test_calon_admin_bisa_dicari_dan_dipaginasi_tanpa_ruang_perusahaan(pg,orang,monkeypatch):
    async with pg() as db:
        pw=(await db.get(Akun,orang['aid'])).password_hash
        for i in range(35):
            user=User(nama=f'Awal {i:02}',role=P.OPERATOR,status='aktif');db.add(user);await db.flush()
            db.add(Akun(user_id=user.id,username=f'calon-{i:02}',password_hash=pw,status='aktif',token_version=1))
        await db.commit()
    monkeypatch.delenv('HMU_COMPANY_ID',raising=False)
    async with pg() as db:
        first=await keanggotaan.calon_admin(db)
        assert len(first['pengguna'])==30 and first['total']==37 and first['halaman_total']==2
        found=await keanggotaan.calon_admin(db,cari='calon-34')
        assert len(found['pengguna'])==1 and found['pengguna'][0]['username']=='calon-34'
        second=await keanggotaan.calon_admin(db,halaman=2)
        assert set(u['user_id'] for u in first['pengguna']).isdisjoint(u['user_id'] for u in second['pengguna'])
        selected=await keanggotaan.calon_admin(db,cari='tidak-ada',user_id=found['pengguna'][0]['user_id'])
        assert selected['total']==0 and selected['terpilih']['username']=='calon-34'
        assert (await keanggotaan.calon_admin(db,cari='%'))['total']==0
        assert (await keanggotaan.calon_admin(db,cari='²'))['total']==0
        assert (await keanggotaan.calon_admin(db,cari='operator-off'))['total']==0

async def test_api_calon_admin_memerlukan_sesi_console_dan_tidak_mengubah_data(pg,orang,monkeypatch):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.test_console_akses import sesi
    from app.config import settings
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        assert (await c.get('/internal/console/calon-admin')).status_code==401
        headers=await sesi(c);before=await fakta(pg)
        r=await c.get('/internal/console/calon-admin?cari=operator-aktif',headers=headers)
        assert r.status_code==200 and r.json()['pengguna'][0]['user_id']==orang['uid']
        assert 'no-store' in r.headers['cache-control']
        assert (await c.get('/internal/console/calon-admin?halaman=0',headers=headers)).status_code==422
        assert await fakta(pg)==before
