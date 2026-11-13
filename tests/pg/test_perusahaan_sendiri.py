"""Otorisasi HTTP dan pemetaan nyata tanpa mengubah seluruh tabel bisnis."""
import asyncio,json
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select,delete,func
from hmu_core import Perusahaan,LokasiPabrik,Warehouse,User,KeanggotaanPerusahaan,AksesLokasiAnggota,AksesGudangAnggota,PenempatanGudang
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from app.models import ActivityLog
from app.services import keanggotaan as member,perusahaan_sendiri as svc,organisasi_warisan as legacy
from app.services.organisasi_master import OrganisasiError
from app.web.security import baca_token,NAMA_COOKIE
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_master_organisasi import organisasi
from tests.pg.test_pengaturan_organisasi import fakta
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.formulir import cap_formulir

pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]
BASE='/pengaturan/perusahaan-sendiri'


async def pasang(pg,c,x,role=P.ADMIN,all_=True):
    aid,_=baca_token(c.cookies.get(NAMA_COOKIE))
    async with pg() as db:
        uid=(await db.get(Akun,aid)).user_id
        m=KeanggotaanPerusahaan(company_id=x['c'][0],user_id=uid,peran=role,aktif=True);db.add(m);await db.flush()
        db.add(AksesLokasiAnggota(keanggotaan_id=m.id,company_id=x['c'][0],lokasi_pabrik_id=x['s'][0],semua_gudang=all_));await db.flush()
        if not all_:db.add(AksesGudangAnggota(keanggotaan_id=m.id,company_id=x['c'][0],lokasi_pabrik_id=x['s'][0],warehouse_id=x['w'][0]))
        await db.commit();return uid,m.id


def form(c,**kw):return dict(_csrf=cap_formulir(c),alasan='Perubahan administratif berdasarkan penugasan',**kw)


def bisnis(f):
    return {k:v for k,v in f.items() if k not in {'hmu_companies','hmu_factory_sites','hmu_company_memberships','hmu_membership_sites','hmu_membership_warehouses','hmu_warehouse_sites','activity_logs','setelan_pabrik','warehouses'}}


@pytest.mark.parametrize('role',[P.ADMIN,P.SUPERADMIN,P.OPERATOR])
async def test_peran_global_tidak_memberikan_perusahaan_otomatis(pg,organisasi,role):
    x=organisasi
    async with await _klien(pg,peran=role) as c:
        before=await fakta(pg)
        assert (await c.get(BASE)).status_code==200
        r=await c.get(f'{BASE}/{x["c"][0]}');assert r.status_code==403
        assert (await c.post(f'{BASE}/{x["c"][0]}/lokasi',data=form(c,nama='Tidak boleh',kode='baru',alamat=''))).status_code==403
        assert await fakta(pg)==before


async def test_admin_perusahaan_http_batasi_read_payload_dan_hak_global(pg,organisasi,running):
    x=organisasi
    async with await _klien(pg,peran=P.ADMIN) as c:
        uid,mid=await pasang(pg,c,x)
        before=await fakta(pg)
        r=await c.get(BASE);assert r.status_code==200 and 'Anggota &amp; akses' in r.text
        assert 'no-store' in r.headers['cache-control']
        assert (await c.get(f'{BASE}/{x["c"][1]}')).status_code==403
        assert (await c.get('/pengguna')).status_code==403
        for payload in [dict(nama='Baru',kode='baru',alamat='',company_id=x['c'][1]),dict(nama='Baru',kode='baru',alamat='',lokasi_id=x['s'][2]),dict(nama='Baru',alamat='',lokasi_id=x['s'][0],gudang_id=x['w'][4])]:
            action='gudang' if 'gudang_id' in payload else 'lokasi'
            r=await c.post(f'{BASE}/{x["c"][0]}/{action}',data=form(c,**payload));assert r.status_code in (403,422),r.text
        assert await fakta(pg)==before
        r=await c.post(f'{BASE}/{x["c"][0]}/lokasi',data=form(c,nama='Pabrik baru',kode='baru',alamat='Alamat lokasi baru'));assert r.status_code==200,r.text[-1500:]
        async with pg() as db:
            site=await db.scalar(select(LokasiPabrik).where(LokasiPabrik.kode=='baru'));assert site.company_id==x['c'][0]
            grant=await db.scalar(select(AksesLokasiAnggota).where(AksesLokasiAnggota.keanggotaan_id==mid,AksesLokasiAnggota.lokasi_pabrik_id==site.id));assert grant.semua_gudang
            assert (await db.get(User,uid)).role==P.ADMIN
        assert bisnis(await fakta(pg))==bisnis(before)


async def test_batas_gudang_menyaring_anggota_lokasi_dan_audit(pg,organisasi):
    x=organisasi
    async with await _klien(pg,peran=P.ADMIN) as c:
        uid,mid=await pasang(pg,c,x,all_=False)
        async with pg() as db:
            (await db.get(Warehouse,x['w'][1])).nama_gudang='Gudang rahasia lain'
            (await db.get(LokasiPabrik,x['s'][1])).nama='Pabrik rahasia lain';await db.commit()
        r=await c.get(f'{BASE}/{x["c"][0]}');assert r.status_code==200
        assert 'Gudang rahasia lain' not in r.text and 'Pabrik rahasia lain' not in r.text and 'Lintas perusahaan' not in r.text
        before=await fakta(pg)
        r=await c.post(f'{BASE}/{x["c"][0]}/gudang',data=form(c,lokasi_id=x['s'][0],nama='Gudang baru',alamat=''))
        assert r.status_code==403 and await fakta(pg)==before


async def test_gudang_identitas_stale_csrf_draf_tetap_dan_tidak_mengubah_fungsi(pg,organisasi):
    x=organisasi
    async with await _klien(pg,peran=P.ADMIN) as c:
        await pasang(pg,c,x)
        async with pg() as db:
            info=await svc.baca(db,member.RuangAdministrasi((await db.get(Akun,baca_token(c.cookies.get(NAMA_COOKIE))[0])).user_id,x['c'][0]))
            w=info['lokasi'][0]['gudang'][0]
        body=form(c,lokasi_id=x['s'][0],gudang_id=w['id'],nama='Gudang diganti',alamat='Alamat baru',bukti=w['bukti'])
        before=await fakta(pg)
        bad={**body,'_csrf':'palsu'};assert (await c.post(f'{BASE}/{x["c"][0]}/gudang',data=bad)).status_code==403
        assert await fakta(pg)==before
        assert (await c.post(f'{BASE}/{x["c"][0]}/gudang',data=body)).status_code==200
        saved=await fakta(pg)
        r=await c.post(f'{BASE}/{x["c"][0]}/gudang',data={**body,'nama':'Draf usang'});assert r.status_code==422 and 'Draf usang' in r.text
        assert BeautifulSoup(r.text,'html.parser').select_one(f'input[value="{w["bukti"]}"]') is not None
        assert await fakta(pg)==saved and bisnis(saved)==bisnis(before)
        async with pg() as db:assert (await db.get(Warehouse,w['id'])).kode_fungsi==w.get('fungsi')


@pytest.mark.parametrize('kind',['nonaktif','operator','scope'])
async def test_pencabutan_akses_terbaru_dan_orm_cache_tidak_meloloskan_writer(pg,organisasi,kind):
    x=organisasi;ruang=member.RuangAdministrasi(x['uid'],x['c'][0])
    async with pg() as stale:
        await svc.baca(stale,ruang)
        async with pg() as db:
            m=await db.get(KeanggotaanPerusahaan,x['m'][0])
            if kind=='nonaktif':m.aktif=False
            elif kind=='operator':m.peran=P.OPERATOR
            else:(await db.get(AksesLokasiAnggota,(m.id,x['s'][0]))).semua_gudang=False
            await db.commit()
        before=await fakta(pg)
        with pytest.raises(PermissionError):
            await svc.simpan_gudang(stale,ruang=ruang,lokasi_id=x['s'][0],nama='Tidak boleh',alamat='',alasan='Uji pencabutan saat formulir terbuka')
        await stale.rollback();assert await fakta(pg)==before


async def test_keanggotaan_dapat_dinonaktifkan_perusahaan_sendiri_tanpa_mencabut_login_global(pg,organisasi):
    x=organisasi
    async with await _klien(pg,peran=P.ADMIN) as c:
        _,mid=await pasang(pg,c,x)
        async with pg() as db:
            target=KeanggotaanPerusahaan(company_id=x['c'][0],user_id=x['luar'],peran=P.OPERATOR,aktif=True);db.add(target);await db.commit()
        r=await c.get(f'{BASE}/{x["c"][0]}?anggota={x["luar"]}')
        token=BeautifulSoup(r.text,'html.parser').select_one('#ubah-anggota input[name=bukti]')['value']
        before=await fakta(pg)
        r=await c.post(f'{BASE}/{x["c"][0]}/anggota',data=form(c,user_id=x['luar'],peran=P.OPERATOR,bukti=token));assert r.status_code==200,r.text[-800:]
        async with pg() as db:
            assert not (await db.scalar(select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.user_id==x['luar']))).aktif
            assert (await db.get(User,x['luar'])).status=='aktif'
        assert bisnis(await fakta(pg))==bisnis(before)


async def test_penempatan_identitas_lama_berulang_metadata_saja(pg,running):
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        async with pg() as db:
            ws=list(await db.scalars(select(Warehouse.id).order_by(Warehouse.id).limit(2)))
            plan=await legacy.pratinjau(db,kode='perusahaan-lama',lokasi_nama='Pabrik lama nyata',warehouse_ids=ws)
        before=await fakta(pg)
        async with pg() as db:
            with pytest.raises(OrganisasiError):await legacy.terapkan(db,kode='perusahaan-lama',lokasi_nama='Pabrik lama nyata',warehouse_ids=ws,bukti='salah',alasan='Uji sumber berubah',sistem=True)
        assert await fakta(pg)==before
        async with pg() as db:
            cid=await legacy.terapkan(db,kode='perusahaan-lama',lokasi_nama='Pabrik lama nyata',warehouse_ids=ws,bukti=plan['bukti'],alasan='Pemetaan identitas lama disetujui',sistem=True);await db.commit()
        saved=await fakta(pg);assert bisnis(saved)==bisnis(before)
        assert saved['warehouses']==before['warehouses']
        async with pg() as db:
            assert await legacy.terapkan(db,kode='perusahaan-lama',lokasi_nama='Pabrik lama nyata',warehouse_ids=ws,bukti=plan['bukti'],alasan='Pengiriman ulang penetapan',sistem=True)==cid
            await db.commit()
        assert await fakta(pg)==saved
        r=await c.get(BASE);assert r.status_code==200 and 'Pabrik lama nyata' in r.text


async def test_console_daftar_banyak_perusahaan_filter_halaman_dan_admin_pertama_atomic(pg):
    from tests.pg.test_console_akses import sesi
    from app.config import settings
    old=settings.console_website_url;settings.console_website_url='https://website.uji'
    try:
        async with await _klien(pg,peran=P.SUPERADMIN) as c:
            h=await sesi(c)
            async with pg() as db:
                db.add_all([Perusahaan(kode='perusahaan-'+str(i),nama='Perusahaan '+str(i),aktif=i%2==0) for i in range(24)])
                await db.commit()
            before=await fakta(pg)
            r=await c.get('/internal/console/perusahaan',headers=h);assert r.status_code==200
            assert len(r.json()['perusahaan'])==20 and r.json()['total']==24 and r.json()['statistik']['aktif']==12
            second=(await c.get('/internal/console/perusahaan?halaman=2',headers=h)).json();assert len(second['perusahaan'])==4
            assert (await c.get('/internal/console/perusahaan?status=nonaktif',headers=h)).json()['total']==12
            assert (await c.get('/internal/console/perusahaan?cari=perusahaan-23',headers=h)).json()['total']==1
            assert await fakta(pg)==before
            body=dict(nama='Perusahaan baru',kode='baru',alasan='Penetapan Admin pertama dalam satu transaksi',admin_user_id=2147483647)
            assert (await c.post('/internal/console/perusahaan',json=body,headers=h)).status_code==422
            assert await fakta(pg)==before
            aid,_=baca_token(c.cookies.get(NAMA_COOKIE))
            async with pg() as db:body['admin_user_id']=(await db.get(Akun,aid)).user_id
            r=await c.post('/internal/console/perusahaan',json=body,headers=h);assert r.status_code==200,r.text
            async with pg() as db:
                m=await db.scalar(select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.company_id==r.json()['id']))
                assert m.user_id==body['admin_user_id'] and m.peran==P.ADMIN
    finally:settings.console_website_url=old


async def test_peran_admin_perusahaan_tidak_mengubah_peran_operasi(pg,organisasi):
    async with await _klien(pg,peran=P.OPERATOR) as c:
        await pasang(pg,c,organisasi)
        assert (await c.get(BASE)).status_code==200
        assert (await c.get('/pengguna')).status_code==403


async def test_dua_pengiriman_tambah_gudang_tidak_menggandakan_master(pg,organisasi):
    x=organisasi;ruang=member.RuangAdministrasi(x['uid'],x['c'][0])
    async def tambah():
        async with pg() as db:
            row=await svc.simpan_gudang(db,ruang=ruang,lokasi_id=x['s'][0],nama='Gudang tambahan',alamat='Alamat sama',alasan='Pengiriman bersamaan dari formulir yang sama')
            await db.commit();return row.id
    ids=await asyncio.wait_for(asyncio.gather(tambah(),tambah()),timeout=10)
    assert len(set(ids))==1
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='warehouses'))==1
