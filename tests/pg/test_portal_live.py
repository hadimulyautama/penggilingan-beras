"""Snapshot realtime memakai otorisasi portal dan tidak menulis transaksi."""
import pytest
from sqlalchemy import event, select
from app.models import User
from tests.pg.test_gabung_jasa import dunia  # noqa: F401
from tests.pg.test_tahap_stok import siapkan
from tests.pg.test_portal_transit import _akun
from tests.pg.test_portal_pelanggan import client

pytestmark = pytest.mark.asyncio


async def test_snapshot_berubah_untuk_hasil_sendiri_tanpa_membuka_pelanggan_lain(pg, dunia):
    from app.penggilingan.gudang1.services.milling import log_progress
    kode, _ = await siapkan(pg, dunia)
    async with client(await _akun(pg, dunia)) as c:
        url='/pelanggan/live/keadaan?halaman=%2Fpelanggan%2Fbarang-saya'
        first=await c.get(url)
        assert first.status_code==200 and first.headers['cache-control']=='no-store, private'
        a=first.json()
        assert set(a)=={'n','html','url','identity'}
        assert '1.500' in a['html'] and 'Budi' not in a['html']
        async with pg() as db:
            from datetime import date
            from app.database import now_local
            from app.models import PurchaseBatch, ActivityLog
            foreign=PurchaseBatch(kode_batch='GB-RAHASIA-LIVE', jasa_id=dunia['jasa3'],
                kondisi_gabah='basah', berat_total_kg=1234, status_batch='baru',
                tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=dunia['user'])
            db.add(foreign);await db.flush()
            db.add(ActivityLog(table_name='purchase_batches',record_id=foreign.id,action='INSERT'))
            await db.commit()
        same=(await c.get(url)).json()
        assert same['n']==a['n'] and 'GB-RAHASIA-LIVE' not in same['html']
        async with pg() as db:
            await log_progress(db,user=await db.get(User,dunia['user']),kode_proses=kode,berat_kumulatif=1700)
        b=(await c.get(url)).json()
        assert a['n']!=b['n'] and '1.700' in b['html'] and a['identity']==b['identity']
        assert len(a['n'])==64 and len(a['identity'])==64
        assert (await c.get(url+'&pelanggan_id='+str(dunia['budi']))).json()['identity']==a['identity']
        # Identitas saringan dalam URL halaman tetap diperiksa pembaca native.
        r=await c.get(url+'%3Fpelanggan_id%3D'+str(dunia['budi']))
        assert r.status_code==404


async def test_semua_snapshot_hanya_get_tidak_menulis_transaksi(pg,dunia):
    await siapkan(pg,dunia)
    account=await _akun(pg,dunia)
    async with pg() as db: mesin=db.bind.sync_engine
    writes=[]
    def rekam(conn,cursor,statement,params,ctx,many):
        if statement.lstrip().split(None,1)[0].upper() in {'INSERT','UPDATE','DELETE'}:writes.append(statement)
    event.listen(mesin,'before_cursor_execute',rekam)
    try:
        async with client(account) as c:
            for page in ['/pelanggan/','/pelanggan/barang-saya','/pelanggan/jasa-saya','/pelanggan/barang-masuk']:
                r=await c.get('/pelanggan/live/keadaan',params={'halaman':page})
                assert r.status_code==200,r.text
            assert (await c.get('/pelanggan/live/sesi')).status_code==200
    finally:event.remove(mesin,'before_cursor_execute',rekam)
    assert writes==[]


@pytest.mark.parametrize('path',['https://example.com/pelanggan/','//evil.test/pelanggan/','/pengaturan','/pelanggan/masuk','/pelanggan/live/aliran','/pelanggan/jasa/1/nota.pdf','http://['])
async def test_snapshot_tidak_menerima_tujuan_di_luar_pembaca_html(pg,dunia,path):
    async with client(await _akun(pg,dunia)) as c:
        assert (await c.get('/pelanggan/live/keadaan',params={'halaman':path})).status_code==404


async def test_sesi_dicabut_memutus_dorongan_sebelum_mengirim_data_baru(pg,dunia):
    from starlette.requests import Request
    from app.models.portal import PortalAccount
    from app.web.portal.security import COOKIE,issue
    from app.web.portal.live import aliran
    from app.web.csrf import NAMA_COOKIE,terbitkan_baru
    await siapkan(pg,dunia)
    account=await _akun(pg,dunia)
    scope={'type':'http','method':'GET','scheme':'http','path':'/pelanggan/live/aliran','query_string':b'',
        'headers':[(b'host',b'uji'),(b'cookie',f'{COOKIE}={issue(account)}; {NAMA_COOKIE}={terbitkan_baru()}'.encode())],
        'server':('uji',80),'client':('127.0.0.1',1),'state':{}}
    async def receive():
        return {'type':'http.request','body':b'','more_body':False}
    req=Request(scope,receive=receive)
    generator=aliran(req,'/pelanggan/barang-saya',jeda=.01)
    initial=await anext(generator)
    assert '"html"' in initial and '1.500' in initial
    async with pg() as db:
        a=await db.get(PortalAccount,account.id);a.active=False;await db.commit()
    revoked=await anext(generator)
    assert '"akses": false' in revoked and '"html"' not in revoked
    await generator.aclose()


async def test_jalur_realtime_memerlukan_sesi_pelanggan_sendiri(pg,dunia):
    import httpx
    from app.main import app
    from tests.pg.test_stok_pk_g1_polesan import _klien
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        for path in ['/pelanggan/live/sesi','/pelanggan/live/keadaan?halaman=/pelanggan/','/pelanggan/live/aliran?halaman=/pelanggan/']:
            assert (await c.get(path)).status_code==401
    async with await _klien(pg,role='superadmin') as c:
        assert (await c.get('/pelanggan/live/sesi')).status_code==401
