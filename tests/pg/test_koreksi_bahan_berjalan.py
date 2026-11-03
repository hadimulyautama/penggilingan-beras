from decimal import Decimal as D
import asyncio,copy
import pytest
from sqlalchemy import select,func
from app.models import User,PkTumpukanToSilo,PolishingSiloUsage,PolishingOutputLog,Peristiwa,MillingProcessSource,MillingProcess,SiloStorage
from app.services import koreksi_bahan_berjalan as s
from app.penggilingan.gudang2 import polishing as p,service as g2
from tests.pg.test_pk_karung import dunia,batch_baru,pindah
from tests.pg.test_form_hasil_penggilingan import hasil,g1
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def running(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=100,w=5000)
        move=await pindah(db,u,it,60)
        pr=(await p.mulai_penyosohan(db,user=u,nama_silos=['A'])).proc
        await p.catat_output(db,user=u,kode=pr.kode_proses,jenis='medium',berat_kumulatif=2000)
        await p.catat_output(db,user=u,kode=pr.kode_proses,jenis='broken',berat_kumulatif=200)
        await p.selesai_penyosohan(db,user=u,kode=pr.kode_proses,nama_silo='A',sisa_kg=500)
        u.role='admin';await db.commit()
        mid=await db.scalar(select(PkTumpukanToSilo.id).where(PkTumpukanToSilo.kode_pindah==move.kode_pindah))
        return u.id,pr.kode_proses,mid,it.id

async def request(db,uid,kode,*,jenis='sosoh',bahan=None,hasil=None,key='uji-koreksi-123456'):
    user=await db.get(User,uid);ctx=await s.konteks(db,jenis=jenis,kode=kode,user=user)
    return user,dict(dasar=ctx['dasar'],bahan=bahan or [],hasil=hasil or {},alasan='Pemeriksaan fisik dan salah input',kunci=key)

async def save(pg,uid,kode,**kw):
    jenis=kw.pop('jenis','sosoh')
    async with pg() as db:
        user,body=await request(db,uid,kode,jenis=jenis,**kw)
        pre=await s.periksa(db,jenis=jenis,kode=kode,user=user,req=body)
        body.update(pemeriksaan=pre['pemeriksaan'],konfirmasi=True)
        await db.rollback()
    async with pg() as db:
        user=await db.get(User,uid)
        result=await s.simpan(db,jenis=jenis,kode=kode,user=user,req=body);await db.commit()
    return result,body

async def test_60_56_sisa_500_terpakai_2300_dan_riwayat(pg,running):
    uid,kode,mid,it=running
    r,body=await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)])
    after=r['hasil']['sesudah'];assert after['basis']==2500
    assert after['outputs']=={'medium':2000,'broken':200}
    assert after['entries'][0]['sisa']==300
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,it)==2200
        event=await db.get(Peristiwa,r['peristiwa_id']);assert event.muatan['hasil']['sebelum']['entries'][0]['jumlah']==60
        user=await db.get(User,uid)
        again=await s.simpan(db,jenis='sosoh',kode=kode,user=user,req=body)
        assert again['sudah_tercatat'];await db.commit()
        assert await g2._sisa_tumpukan_intake(db,it)==2200

async def test_periksa_tidak_menulis(pg,running):
    uid,kode,mid,it=running
    async with pg() as db:
        u,body=await request(db,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)])
        pre=await s.periksa(db,jenis='sosoh',kode=kode,user=u,req=body)
        assert pre['sesudah']['basis']==2500
        await db.commit()
    async with pg() as db:
        assert (await db.get(PkTumpukanToSilo,mid)).jumlah_karung==60
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.JENIS))==0

@pytest.mark.parametrize('jumlah',[-1,2.5,101])
async def test_angka_dan_stok_tidak_sah(pg,running,jumlah):
    uid,kode,mid,it=running
    with pytest.raises(ValueError):await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=jumlah)])
    async with pg() as db:assert (await db.get(PkTumpukanToSilo,mid)).jumlah_karung==60

async def test_hasil_turun_per_jenis_saat_jeda(pg,running):
    uid,kode,mid,it=running
    from app.penggilingan.gudang1.services import jeda
    async with pg() as db:
        u=await db.get(User,uid);await jeda.hentikan(db,user=u,jenis='penyosohan',kode=kode,sebab='Listrik padam')
    r,_=await save(pg,uid,kode,hasil={'medium':1900})
    assert r['hasil']['sesudah']['outputs']=={'medium':1900,'broken':200}
    async with pg() as db:
        pr=await db.scalar(select(__import__('app.models',fromlist=['PolishingProcess']).PolishingProcess).where(__import__('app.models',fromlist=['PolishingProcess']).PolishingProcess.kode_proses==kode))
        assert pr.status=='proses' and await jeda.jeda_terbuka(db,'penyosohan',pr.id)

async def test_giling_bahan_dan_hasil_bersama(pg,hasil):
    u,pr,_=hasil
    async with pg() as db:
        user=await db.get(User,u.id);user.role='admin';await db.commit()
        src=(await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==pr.id).order_by(MillingProcessSource.id))).first()
        st=await db.get(SiloStorage,src.silo_storage_id);key=f'batch:{st.purchase_batch_id}'
    r,_=await save(pg,u.id,pr.kode_proses,jenis='giling',bahan=[dict(id=st.id,sumber=key,jumlah=5800)],hasil={'pk':5900})
    assert r['hasil']['sesudah']['basis']==9800
    assert r['hasil']['sesudah']['outputs']['pk']==5900
    async with pg() as db:
        source=await s.g1_sumber(db,key);assert source['bebas']==200
        await __import__('app.penggilingan.gudang1.services.milling',fromlist=['resinkron_bahan_berjalan']).resinkron_bahan_berjalan(db)
        assert (await db.get(MillingProcess,pr.id)).berat_gabah_masuk_kg==9800

async def test_giling_verifikasi_tetap_terpisah(pg,hasil):
    u,pr,_=hasil
    from app.penggilingan.gudang1.services import milling as m
    async with pg() as db:
        user=await db.get(User,u.id);user.role='admin';await db.commit()
        await m.verify_milling_output(db,user=user,kode_proses=pr.kode_proses,berat_output=5900)
    r,_=await save(pg,u.id,pr.kode_proses,jenis='giling',hasil={'pk':5800})
    assert r['hasil']['sesudah']['verification']['berat_output_final_kg']==5900
    async with pg() as db:assert (await m._pk_breakdown(db,pr.id)).produced==5900

async def test_izin_operator_tidak_menjadi_hak_koreksi(pg,running):
    uid,kode,mid,it=running
    async with pg() as db:
        user=await db.get(User,uid);user.role='operator'
        with pytest.raises(PermissionError):await s.konteks(db,jenis='sosoh',kode=kode,user=user)

async def test_ganti_sumber_audit_dan_replay_proyeksi(pg,running,dunia):
    uid,kode,mid,it=running
    async with pg() as db:
        u,b,newit=await batch_baru(db,dunia,n=100,w=6000,kode='PKB-PENGGANTI')
        nid=newit.id
    r,_=await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(nid),jumlah=50)])
    assert r['hasil']['sesudah']['basis']==2500
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,it)==5000
        assert await g2._sisa_tumpukan_intake(db,nid)==3000
        from app.models import ProyeksiPindahTumpukanSilo
        row=await db.get(PkTumpukanToSilo,mid)
        pro=await db.get(ProyeksiPindahTumpukanSilo,row.peristiwa_id)
        assert pro.intake_id==nid and pro.jumlah_karung==50
        from app.services import peristiwa
        await peristiwa.bangun_ulang(db)
        pro=await db.get(ProyeksiPindahTumpukanSilo,row.peristiwa_id,populate_existing=True)
        assert pro.intake_id==nid and pro.jumlah_karung==50

async def test_koreksi_berurutan_memakai_total_efektif(pg,running):
    uid,kode,mid,it=running
    await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)],key='uji-koreksi-pertama')
    await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=54)],key='uji-koreksi-kedua')
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,it)==2300
        usage=await db.scalar(select(PolishingSiloUsage));assert usage.berat_terpakai_kg==2500
        assert usage.berat_akhir_kg==200

async def test_konflik_mempertahankan_rancangan_dan_tidak_mengurangi_dua_kali(pg,running):
    uid,kode,mid,it=running
    async with pg() as db:
        u,b=await request(db,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)])
        check=await s.periksa(db,jenis='sosoh',kode=kode,user=u,req=b);b.update(pemeriksaan=check['pemeriksaan'],konfirmasi=True)
    await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=58)],key='uji-pihak-lain-1234')
    async with pg() as db:
        u=await db.get(User,uid)
        with pytest.raises(s.Konflik):await s.simpan(db,jenis='sosoh',kode=kode,user=u,req=b)
        await db.rollback()
    assert b['bahan'][0]['jumlah']==56
    async with pg() as db:assert await g2._sisa_tumpukan_intake(db,it)==2100

async def test_dua_permintaan_bersamaan_tepat_satu_koreksi(pg,running):
    uid,kode,mid,it=running
    async with pg() as db:
        u,b=await request(db,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)])
        x=await s.periksa(db,jenis='sosoh',kode=kode,user=u,req=b);b.update(pemeriksaan=x['pemeriksaan'],konfirmasi=True)
    async def write():
        async with pg() as db:
            u=await db.get(User,uid);r=await s.simpan(db,jenis='sosoh',kode=kode,user=u,req=b);await db.commit();return r
    a,c=await asyncio.gather(write(),write())
    assert a['peristiwa_id']==c['peristiwa_id']
    assert sum(not x['sudah_tercatat'] for x in (a,c))==1
    async with pg() as db:assert await g2._sisa_tumpukan_intake(db,it)==2200

async def test_bahan_belum_dipakai_diubah_dan_dibatalkan(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=100,w=5000);r=await pindah(db,u,it,10)
        mid=await db.scalar(select(PkTumpukanToSilo.id).where(PkTumpukanToSilo.kode_pindah==r.kode_pindah))
        uid=u.id;iid=it.id;u.role='admin';await db.commit()
    code='catatan-'+str(mid)
    r,_=await save(pg,uid,code,bahan=[dict(id=mid,sumber=str(iid),jumlah=8)])
    assert r['hasil']['sesudah']['entries'][0]['kg']==400
    r,b=await save(pg,uid,code,bahan=[dict(id=mid,sumber=str(iid),hapus=True)],key='uji-pembatalan-1234')
    assert not r['hasil']['sesudah']['entries']
    async with pg() as db:
        assert (await db.scalar(select(PkTumpukanToSilo).where(PkTumpukanToSilo.id==mid).execution_options(termasuk_dibatalkan=True))).dibatalkan_pada
        assert await g2._sisa_tumpukan_intake(db,iid)==5000
        u=await db.get(User,uid);again=await s.simpan(db,jenis='sosoh',kode=code,user=u,req=b);assert again['sudah_tercatat']

async def test_rancangan_gagal_tidak_menyisakan_koreksi_bahan(pg,running):
    uid,kode,mid,it=running
    with pytest.raises(ValueError):await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)],hasil={'medium':-1})
    async with pg() as db:
        assert (await db.get(PkTumpukanToSilo,mid)).jumlah_karung==60
        assert await g2._sisa_tumpukan_intake(db,it)==2000

async def test_sisa_giling_dilepas_otomatis_dan_pembaca_detail_sama(pg,hasil):
    u,pr,_=hasil
    from app.penggilingan.gudang1.services import milling as m,silo as si
    async with pg() as db:
        user=await db.get(User,u.id);user.role='admin';await db.commit()
        await m.tutup_silo_giling(db,user=user,kode_proses=pr.kode_proses,nama_silo='A',sisa_kg=500)
        src=(await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==pr.id).order_by(MillingProcessSource.id))).first()
        st=await db.get(SiloStorage,src.silo_storage_id);key=f'batch:{st.purchase_batch_id}';sid=st.id
        assert src.berat_terpakai_kg==5500
    r,_=await save(pg,u.id,pr.kode_proses,jenis='giling',bahan=[dict(id=sid,sumber=key,jumlah=5800)])
    assert r['hasil']['sesudah']['entries'][0]['sisa']==300
    async with pg() as db:
        src=(await db.scalars(select(MillingProcessSource).where(MillingProcessSource.silo_storage_id==sid))).one()
        assert src.berat_terpakai_kg==5500
        assert (await si._row_bobot(db,await db.get(SiloStorage,sid))).kg==300
        from app.services.bahan_silo import sumber_giling_banyak
        kelompok=(await sumber_giling_banyak(db,[pr.id]))[pr.id]
        assert kelompok[0]['ringkasan_sisa']=='300 kg'

async def test_sisa_sosoh_mengalir_ke_siklus_berikutnya_yang_masih_berjalan(pg,running):
    uid,kode,mid,it=running
    async with pg() as db:
        u=await db.get(User,uid)
        next_pr=(await p.mulai_penyosohan(db,user=u,nama_silos=['A'])).proc
        nid=next_pr.id
        assert (await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==nid))).berat_awal_kg==500
    r,_=await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)])
    async with pg() as db:
        us=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==nid))
        assert us.berat_awal_kg==300 and us.berat_akhir_kg is None
        assert (await db.get(__import__('app.models',fromlist=['PolishingProcess']).PolishingProcess,nid)).status=='proses'

from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir

@pytest.mark.parametrize('role,view,ok',[('superadmin',None,True),('admin',None,True),('operator',None,False),('admin','operator:g1',False),('superadmin','operator:g2',False),('staff',None,False)])
async def test_http_hak_efektif_tidak_terbuka_dari_url(pg,running,role,view,ok):
    uid,kode,mid,it=running
    from app.web.lihat_sebagai import NAMA_KUKI
    async with await _klien(pg,peran=role,gudang='Gudang 2') as c:
        if view:c.cookies.set(NAMA_KUKI,view)
        r=await c.get('/koreksi-bahan/sosoh/'+kode);assert r.status_code==(200 if ok else 403),r.text
        d=await c.get('/api/actions/koreksi-bahan/sosoh/'+kode);assert d.status_code==(200 if ok else 403),d.text
        if ok:
            body={'dasar':d.json()['dasar'],'alasan':'Salah jumlah karung','kunci':'http-koreksi-123456','bahan':[dict(id=mid,sumber=str(it),jumlah=56)]}
        else:body={'dasar':'palsu','alasan':'Akses langsung','kunci':'http-koreksi-123456','hasil':{'medium':100}}
        r=await c.post('/api/actions/koreksi-bahan/sosoh/'+kode+'/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==(200 if ok else 403),r.text
        if ok:
            body.update(pemeriksaan=r.json()['pemeriksaan'],konfirmasi=True)
            r=await c.post('/api/actions/koreksi-bahan/sosoh/'+kode+'/simpan',json=body,headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==200,r.text
            assert r.json()['hasil']['sesudah']['entries'][0]['sisa']==300
            assert (await c.get('/api/actions/koreksi-bahan-status/http-koreksi-123456')).json()['tercatat']

async def test_siapkan_bukti_ui(pg,running,hasil):
    import json,os
    from pathlib import Path
    uid,kode,mid,it=running;u,giling,_=hasil
    async with await _klien(pg,peran='admin') as c:
        from app.models import ProduksiAkun
        async with pg() as db:
            akun=await db.scalar(select(ProduksiAkun).order_by(ProduksiAkun.id.desc()).limit(1))
            if os.environ.get('UJI_EXPORT_UI'):
                Path('../ui.json').write_text(json.dumps(dict(username=akun.username,password='rahasia123',sosoh=kode,giling=giling.kode_proses,move_id=mid,intake_id=it)))
