"""Form kumulatif: API asli, saldo asli, dan balapan PostgreSQL terisolasi."""
import asyncio
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select, func

from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def hasil(pg, gudang2):
    from app.penggilingan.gudang2 import polishing as p
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
    u = gudang2['user']
    async with pg() as db:
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=gudang2['intake_tumpukan'], nama_silo='A', berat=4000)
        pr = (await p.mulai_penyosohan(db, user=u, nama_silos=['A', 'B'])).proc
        for total in (4000, 4400):
            await p.catat_output(db, user=u, kode=pr.kode_proses, jenis='medium', berat_kumulatif=total)
        await p.catat_output(db, user=u, kode=pr.kode_proses, jenis='menir', berat_kumulatif=150)
        from datetime import date
        from app.database import now_local
        from app.models import Pelanggan, Jasa, Silo, PkPurchaseBatch
        from app.penggilingan.gudang2.service import masukkan_pk_luar
        owner=Pelanggan(nama_pelanggan='Pelanggan Uji Hasil')
        db.add(owner);await db.flush()
        jasa=Jasa(kode='JAS-UJI-HASIL',pelanggan_id=owner.id)
        db.add(jasa);await db.flush()
        db.add(Silo(nama_silo='Silo C',warehouse_id=u.default_warehouse_id))
        db.add(PkPurchaseBatch(kode_batch='PKB-UJI-JASA',jasa_id=jasa.id,berat_total_kg=1000,
            tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=u.id,
            status_batch='diterima',flag_unverified=True,sumber_berat='manual'))
        await db.commit()
        intake=await masukkan_pk_luar(db,user=u,kode='PKB-UJI-JASA',tujuan='ditumpuk')
        await pindah_tumpukan_ke_silo(db,user=u,intake_id=intake.intake.id,nama_silo='C',berat=1000)
        other=(await p.mulai_penyosohan(db,user=u,nama_silos=['C'])).proc
        await p.catat_output(db,user=u,kode=other.kode_proses,jenis='medium',berat_kumulatif=700)

    return u, pr


async def kirim(c, kode, **isi):
    return await c.post('/api/actions/hasil-penyosohan', json={'kode_proses':kode, 'jenis':'medium', **isi}, headers={'X-CSRF-Token':cap_formulir(c)})


async def fakta(pg, pr):
    from app.models import PolishingOutputLog, PolishingSiloUsage, PolishingProcess, FinishedGoodsStock, ActivityLog, ByproductStock
    from app.services.stok import output_sosoh, beras_curah
    async with pg() as db:
        logs = (await db.execute(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==pr.id).order_by(PolishingOutputLog.id))).scalars().all()
        usages = (await db.execute(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pr.id))).scalars().all()
        audits=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='polishing_output_logs',ActivityLog.record_id.in_([r.id for r in logs])).order_by(ActivityLog.id))).all()
        return {'audit':[(x.action,x.changed_by,str(x.waktu_perubahan)) for x in audits],
                'total':await output_sosoh(db,pr.id),
                'logs':[(r.jenis,float(r.berat_kg),r.input_by,str(r.waktu_update)) for r in logs],
                'curah':[(x.jenis,x.sisa_kg,x.jasa_id) for x in await beras_curah(db) if x.kode_proses==pr.kode_proses],
                'silos':[(x.silo_id,x.berat_akhir_kg) for x in usages],
                'status':(await db.get(PolishingProcess,pr.id)).status,
                'packing':await db.scalar(select(func.count()).select_from(FinishedGoodsStock)),
                'samping_dikemas':await db.scalar(select(func.count()).select_from(ByproductStock))}


async def test_kontrak_konteks_seluruh_log_dan_tanpa_mutasi(pg, hasil):
    u,pr = hasil
    before = await fakta(pg,pr)
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        menu = (await c.get('/api/actions/menu')).json()
        a = next(x for x in menu if x['id']=='hasil_penyosohan')
        assert [f['name'] for f in a['fields']]==['kode_proses','jenis','berat_kumulatif']
        assert dict(a['fields'][1]['options'])=={'':'— belum ditentukan —','premium':'Beras Premium','medsuper':'Beras Medium Super','medium':'Beras Medium','sayur':'Beras Sayur','beras_b':'Beras B (olah ulang)','menir':'Menir','broken':'Broken','bekatul':'Bekatul','reject':'Reject'}
        assert not a.get('konfirmasi') and all('bawaan' not in f for f in a['fields'])
        for jenis,total in [('medium',4400),('menir',150),('premium',0),('',None)]:
            r = await c.get('/api/actions/ringkasan-hasil-penyosohan',params={'kode_proses':pr.kode_proses,'jenis':jenis})
            assert r.status_code==200, r.text
            assert r.headers['cache-control']=='no-store'
            data=r.json()
            assert data['tercatat']==total and data['pemilik']=='Pabrik' and data['status']=='berjalan'
            assert [s['nama'] for s in data['silos']]==['Silo A','Silo B']
        active=(await c.get('/api/actions/polishing-active')).json()
        other=next(x['value'] for x in active if x['value']!=pr.kode_proses)
        data=(await c.get('/api/actions/ringkasan-hasil-penyosohan',params={'kode_proses':other,'jenis':'medium'})).json()
        assert data['tercatat']==700 and 'Pelanggan Uji Hasil' in data['pemilik']
        assert data['kepemilikan']=='Titipan jasa' and data['silos']==[{'nama':'Silo C','dipakai':True}]
        for kode,jenis in [('', 'medium'),('tidak-ada','medium'),(pr.kode_proses,'palsu')]:
            assert (await c.get('/api/actions/ringkasan-hasil-penyosohan',params={'kode_proses':kode,'jenis':jenis})).status_code==400
        if os.environ.get('UJI_FORM_SOSOH_SEED'):
            # Hanya fixture lokal; cookie tidak masuk artefak laporan.
            Path('/tmp/form-sosoh-session.json').write_text(json.dumps({'kode':pr.kode_proses,'lain':other,'cookies':{x.name:x.value for x in c.cookies.jar}}))
    assert await fakta(pg,pr)==before


@pytest.mark.parametrize('peran,view',[('operator',None),('admin',None),('superadmin',None),('admin','operator:g2'),('superadmin','operator:g2')])
async def test_4400_4600_log200_saldo_laporan_dan_kirim_ulang(pg,hasil,peran,view):
    u,pr=hasil
    before=await fakta(pg,pr)
    async with await _klien(pg,peran=peran,gudang='Gudang 2') as c:
        if view:
            from app.web.lihat_sebagai import NAMA_KUKI
            c.cookies.set(NAMA_KUKI,view)
        r=await kirim(c,pr.kode_proses,berat_kumulatif=4600)
        assert r.status_code==200,r.text
        assert 'total medium 4600 kg (tambahan 200 kg)' in r.json()['pesan']
        after=await fakta(pg,pr)
        assert after['total']=={'medium':4600,'menir':150}
        assert after['logs'][-1][0:2]==('medium',200)
        assert after['logs'][-1][2] and after['logs'][-1][3]
        assert ('medium',4600,None) in after['curah']
        assert len(after['audit'])==len(before['audit'])+1
        assert after['audit'][-1][0:2]==('INSERT',after['logs'][-1][2]) and after['audit'][-1][2]
        assert after['packing']==before['packing']==0
        assert after['samping_dikemas']==before['samping_dikemas']==0
        assert after['silos']==before['silos'] and after['status']=='proses'
        assert (await kirim(c,pr.kode_proses,berat_kumulatif=4600)).status_code==200
        assert await fakta(pg,pr)==after
        r=await c.get('/proses-aktif/sosoh/'+pr.kode_proses+'?tab_detail=hasil')
        assert '4.600' in r.text and '200 kg' in r.text


@pytest.mark.parametrize('isi',[{'berat_kumulatif':4300},{'berat_kumulatif':0},{'berat_kumulatif':-1},{'berat_kumulatif':''},{'berat_kumulatif':'NaN'},{'berat_kumulatif':'Infinity'},{'berat_kumulatif':'4.600,1'},{},{'jenis':'palsu','berat_kumulatif':4600},{'berat_kumulatif':4600,'berat_kg':200}])
async def test_validasi_server_tidak_mengubah_catatan(pg,hasil,isi):
    _,pr=hasil
    before=await fakta(pg,pr)
    async with await _klien(pg,peran='admin') as c:
        assert (await kirim(c,pr.kode_proses,**isi)).status_code in (400,422)
    assert await fakta(pg,pr)==before


async def test_legacy_delta_dan_presisi(pg,hasil):
    _,pr=hasil
    async with await _klien(pg,peran='admin') as c:
        assert (await kirim(c,pr.kode_proses,berat_kg=12.125)).status_code==200
        assert (await kirim(c,pr.kode_proses,berat_kumulatif=4412.625)).status_code==200
    f=await fakta(pg,pr)
    # Numeric(12, 2) lama tetap menentukan presisi tersimpan.
    assert f['total']['medium']==4412.62
    assert [x[1] for x in f['logs'][-2:]]==[12.13,0.49]


async def test_total_terbaru_dan_balapan_kunci_baris(pg,hasil):
    from app.penggilingan.gudang2 import polishing as p
    u,pr=hasil
    async def catat(total):
        async with pg() as db:
            return await p.catat_output(db,user=u,kode=pr.kode_proses,jenis='medium',berat_kumulatif=total)
    # Ringkasan browser 4400 bukan cuplikan yang mengalahkan server.
    await catat(4500)
    r=await catat(4600)
    assert r.berat_kg==100 and r.berat_kumulatif==4600
    r1,r2=await asyncio.gather(catat(4700),catat(4700))
    assert sorted([r1.berat_kg,r2.berat_kg])==[0,100]
    before=await fakta(pg,pr)
    with pytest.raises(p.Gudang2Error,match='tidak boleh lebih kecil'):
        await catat(4600)
    assert await fakta(pg,pr)==before


async def test_jeda_dan_selesai_mengikuti_layanan_lama(pg,hasil):
    from app.penggilingan.gudang1.services import jeda
    from app.penggilingan.gudang2 import polishing as p
    u,pr=hasil
    async with pg() as db:
        await jeda.hentikan(db,user=u,jenis='penyosohan',kode=pr.kode_proses,sebab='Listrik padam')
    async with await _klien(pg,peran='admin') as c:
        r=await c.get('/api/actions/ringkasan-hasil-penyosohan',params={'kode_proses':pr.kode_proses,'jenis':'medium'})
        assert r.json()['status']=='dijeda' and r.json()['sebab_jeda']=='Listrik padam'
        assert (await kirim(c,pr.kode_proses,berat_kumulatif=4600)).status_code==200
        async with pg() as db:
            assert await jeda.jeda_terbuka(db,'penyosohan',pr.id)
            for silo in ('A','B'):
                await p.selesai_penyosohan(db,user=u,kode=pr.kode_proses,nama_silo=silo,sisa_kg=0)
            await p.akhiri_penyosohan(db,user=u,kode=pr.kode_proses)
        before=await fakta(pg,pr)
        assert (await kirim(c,pr.kode_proses,berat_kumulatif=4800)).status_code==400
        assert await fakta(pg,pr)==before


@pytest.mark.parametrize('peran,view',[('operator',None),('admin','operator:g1'),('superadmin','operator:g1')])
async def test_gudang_efektif_menjaga_baca_dan_tulis(pg,hasil,peran,view):
    from app.models import Warehouse
    from app.web.lihat_sebagai import NAMA_KUKI
    _,pr=hasil
    async with pg() as db:
        db.add(Warehouse(nama_gudang='Gudang 1 - Selepan',kode_fungsi='g1'))
        await db.commit()
    before=await fakta(pg,pr)
    async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
        if view:c.cookies.set(NAMA_KUKI,view)
        r=await c.get('/api/actions/ringkasan-hasil-penyosohan',params={'kode_proses':pr.kode_proses,'jenis':'medium'})
        assert r.status_code==403 and pr.kode_proses not in r.text
        assert (await kirim(c,pr.kode_proses,berat_kumulatif=4600)).status_code==403
    assert await fakta(pg,pr)==before


async def test_csrf_sesi_dan_portal_baca_saja(pg,hasil):
    import httpx
    from app.main import app
    from app.models import Pelanggan, Jasa
    from app.models.portal import PortalAccount
    from app.web.portal.security import COOKIE, issue
    from app.web import csrf, security
    _,pr=hasil
    before=await fakta(pg,pr)
    async with await _klien(pg,peran='admin') as c:
        r=await c.post('/api/actions/hasil-penyosohan',json={'kode_proses':pr.kode_proses,'jenis':'medium','berat_kumulatif':4600})
        assert r.status_code==403
    async with pg() as db:
        owner=await db.scalar(select(Pelanggan).where(Pelanggan.nama_pelanggan=='Pelanggan Uji Hasil'))
        account=PortalAccount(username='uji-hasil-portal',pelanggan_id=owner.id,password_hash=security.hash_sandi('uji-hasil-aman123'),active=True,token_version=1)
        db.add(account);await db.commit()
        own=await db.scalar(select(Jasa).where(Jasa.pelanggan_id==owner.id))
        from app.models import PolishingProcess
        ownproc=await db.scalar(select(PolishingProcess).where(PolishingProcess.jasa_id==own.id))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        c.cookies.set(COOKIE,issue(account));c.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
        for kode in (pr.kode_proses,ownproc.kode_proses):
            assert (await c.get('/api/actions/ringkasan-hasil-penyosohan',params={'kode_proses':kode,'jenis':'medium'})).status_code in (401,403)
            assert (await kirim(c,kode,berat_kumulatif=4600)).status_code in (401,403)
            assert (await c.get('/pelanggan/api/actions/ringkasan-hasil-penyosohan',params={'kode_proses':kode,'jenis':'medium'})).status_code in (401,403,404)
    assert await fakta(pg,pr)==before


async def test_semua_jenis_lama_tetap_diterima_dan_sumber_laporan_sama(pg,hasil):
    from app.services.stok import output_sosoh
    _,pr=hasil
    jenis=['premium','medsuper','medium','sayur','beras_b','menir','broken','bekatul','reject']
    async with await _klien(pg,peran='admin') as c:
        for j in jenis:
            assert (await kirim(c,pr.kode_proses,jenis=j,berat_kumulatif=5000.25)).status_code==200
        r=await c.get('/proses-aktif/sosoh/'+pr.kode_proses+'?tab_detail=hasil')
        assert r.status_code==200 and '5.000,25' in r.text
    async with pg() as db:
        totals=await output_sosoh(db,pr.id)
        assert totals=={j:5000.25 for j in jenis}
