"""Pencabutan hak lintas koneksi dan isolasi induk metadata; PostgreSQL uji."""
import secrets
from datetime import timedelta
import pytest
from sqlalchemy import select,text
from hmu_core import User,Perusahaan,LokasiPabrik
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from hmu_identitas.sandi import hash_sandi
from app.models import SesiConsole,PolishingProcess
from app.services import console_auth as auth,organisasi_master as master,keanggotaan as svc
from tests.pg.test_master_organisasi import organisasi
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_pengaturan_organisasi import fakta
pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]

@pytest.mark.parametrize('field',['role','status'])
async def test_pengelola_master_memeriksa_hak_terbaru_meski_user_dicache(pg,organisasi,field):
    x=organisasi
    async with pg() as stale:
        cached=await stale.get(User,x['uid'])
        async with pg() as db:
            u=await db.get(User,x['uid']);setattr(u,field,P.OPERATOR if field=='role' else 'nonaktif');await db.commit()
        before=await fakta(pg)
        with pytest.raises(PermissionError):
            await master.simpan(stale,user_id=cached.id,objek='perusahaan',nama='Tidak boleh dibuat',kode='cache-ditolak',aktif=True,alasan='Pencabutan hak harus berlaku pada seluruh koneksi')
        await stale.rollback();assert await fakta(pg)==before

async def test_anggota_baru_ditolak_jika_perusahaan_di_cache_sudah_nonaktif(pg,organisasi):
    x=organisasi
    async with pg() as stale:
        cached=await stale.get(Perusahaan,x['c'][0])
        async with pg() as db:
            (await db.get(Perusahaan,cached.id)).aktif=False;await db.commit()
        before=await fakta(pg)
        with pytest.raises(master.OrganisasiError,match='aktif'):
            await svc.simpan(stale,ruang=svc.RuangAdministrasi(x['uid']),company_id=cached.id,user_id=x['luar'],peran=P.OPERATOR,
                aktif=True,lokasi=[],bukti=svc.sidik(None),alasan='Perusahaan nonaktif tidak boleh diberi anggota baru')
        await stale.rollback();assert await fakta(pg)==before

async def test_id_lokasi_perusahaan_lain_tidak_dinormalisasi_diam_diam(pg,organisasi):
    x=organisasi;before=await fakta(pg)
    async with pg() as db:
        foreign=await db.get(LokasiPabrik,x['s'][2])
        with pytest.raises(master.OrganisasiError,match='[Pp]erusahaan'):
            await master.simpan(db,user_id=x['uid'],objek='lokasi',identitas=foreign.id,company_id=x['c'][0],
                nama='Jangan ubah lokasi perusahaan lain',kode=foreign.kode,aktif=True,alamat='',bukti=master.sidik(foreign),alasan='ID lokasi tidak cocok dengan perusahaan yang dipilih')
        await db.rollback()
    assert await fakta(pg)==before

async def token_lama(pg,x):
    async with pg() as db:
        a=Akun(user_id=x['uid'],username='super-isolasi',password_hash=hash_sandi('sandi-isolasi-123'),status='aktif',token_version=1)
        db.add(a);await db.commit()
        v=secrets.token_urlsafe(48);code=await auth.terbitkan(db,akun_id=a.id,versi=1,tantangan=auth.challenge(v))
        token=await auth.tukar(db,kode=code,verifier=v);await db.commit();return token

@pytest.mark.parametrize('field',['role','status_user','status_akun','versi','dicabut','waktu','wajib_sandi'])
async def test_console_cache_tidak_menerima_sesi_yang_sudah_dicabut(pg,organisasi,field):
    x=organisasi;token=await token_lama(pg,x)
    async with pg() as stale:
        row,a=await auth.periksa(stale,token)
        async with pg() as db:
            s=await db.get(SesiConsole,row.id);account=await db.get(Akun,a.id)
            if field=='role':account.user.role=P.OPERATOR
            elif field=='status_user':account.user.status='nonaktif'
            elif field=='status_akun':account.status='nonaktif'
            elif field=='versi':account.token_version+=1
            elif field=='dicabut':s.dicabut=True
            elif field=='wajib_sandi':account.harus_ganti_sandi=True
            else:s.sesi_sampai=auth.now()-timedelta(seconds=1)
            await db.commit()
        before=await fakta(pg)
        with pytest.raises(auth.TolakConsole):await auth.periksa(stale,token)
        assert await fakta(pg)==before

async def test_baca_otorisasi_tidak_mem_flush_draf_transaksi(pg,organisasi,running):
    token=await token_lama(pg,organisasi)
    async with pg() as db:
        draft=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==running[1]));old=draft.status;draft.status='proses'
        await auth.periksa(db,token)
        assert draft in db.dirty and draft.status=='proses'
        connection=await db.connection()
        assert await connection.scalar(text('SELECT status FROM polishing_process WHERE id=:id'),{'id':draft.id})==old
        await db.rollback()

async def test_master_menolak_transaksi_yang_sudah_memiliki_draf_bisnis(pg,organisasi,running):
    before=await fakta(pg)
    async with pg() as db:
        draft=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==running[1]));draft.status='proses'
        with pytest.raises(master.OrganisasiError,match='transaksi'):
            await master.simpan(db,user_id=organisasi['uid'],objek='perusahaan',nama='Tidak boleh dicampur',kode='jangan-campur',aktif=True,alasan='Transaksi bisnis harus terpisah dari metadata')
        assert draft in db.dirty
        await db.rollback()
    assert await fakta(pg)==before

@pytest.mark.parametrize('global_role',[P.OPERATOR,P.ADMIN])
async def test_admin_perusahaan_tidak_mendapat_console_platform(pg,organisasi,global_role,monkeypatch):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.test_perusahaan_sendiri import pasang
    from app.config import settings
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    x=organisasi
    async with await _klien(pg,peran=global_role) as c:
        await pasang(pg,c,x,role=P.ADMIN)
        assert (await c.get(f'/pengaturan/perusahaan-sendiri/{x["c"][0]}')).status_code==200
        assert (await c.get(f'/pengaturan/perusahaan-sendiri/{x["c"][1]}')).status_code==403
        before=await fakta(pg)
        for path in ['/internal/console/perusahaan','/internal/console/calon-admin','/internal/console/monitoring',
                     f'/internal/console/perusahaan/{x["c"][1]}',f'/internal/console/perusahaan/{x["c"][1]}/audit']:
            assert (await c.get(path)).status_code==401
        r=await c.post('/internal/console/perusahaan',json=dict(nama='Tidak boleh dibuat',kode='tidak-boleh',alasan='Admin perusahaan bukan Admin platform'))
        assert r.status_code==401
        assert await fakta(pg)==before

async def test_penetapan_lintas_ruang_ditolak_403_bukan_500(pg,organisasi,monkeypatch):
    import uuid
    from app.config import settings
    from app.services import organisasi_rencana as rencana
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.test_console_akses import sesi
    from app.web.security import baca_token,NAMA_COOKIE
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    x=organisasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        headers=await sesi(c)
        async with pg() as db:
            uid=(await db.get(Akun,baca_token(c.cookies.get(NAMA_COOKIE))[0])).user_id
            plan=await rencana.pratinjau(db,lokasi_pabrik_id=x['s'][2],warehouse_ids=[x['bebas']])
            proof=rencana.buat_bukti(plan,user_id=uid)
        monkeypatch.setenv('HMU_COMPANY_ID',str(x['c'][0]));monkeypatch.setenv('HMU_RUANG_DATA',str(uuid.uuid4()))
        before=await fakta(pg)
        r=await c.get('/internal/console/penetapan',params=dict(lokasi_pabrik_id=x['s'][2],warehouse_id=x['bebas']),headers=headers)
        assert r.status_code==403 and 'no-store' in r.headers['cache-control']
        r=await c.post('/internal/console/penetapan',json=dict(bukti=proof,konfirmasi=True,alasan='Pratinjau lama milik ruang perusahaan berbeda'),headers=headers)
        assert r.status_code==403
        assert (await c.get('/internal/console/saya',headers=headers)).status_code==200
        assert await fakta(pg)==before
