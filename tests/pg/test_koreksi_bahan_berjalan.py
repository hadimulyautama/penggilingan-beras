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

async def test_60_56_sisa_300_terpakai_2500_dan_riwayat(pg,running):
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

async def test_pertukaran_dua_sumber_memakai_saldo_rancangan_akhir(pg,dunia):
    async with pg() as db:
        u,a,ia=await batch_baru(db,dunia,n=100,w=5000,kode='PKB-TUKAR-A')
        _,b,ib=await batch_baru(db,dunia,n=100,w=6000,kode='PKB-TUKAR-B')
        await pindah(db,u,ia,100,'A');await pindah(db,u,ib,100,'B')
        proc=(await p.mulai_penyosohan(db,user=u,nama_silos=['A','B'])).proc
        u.role='admin';await db.commit();uid=u.id;kode=proc.kode_proses
        moves=(await db.scalars(select(PkTumpukanToSilo).order_by(PkTumpukanToSilo.id))).all()
        changes=[dict(id=moves[0].id,sumber=str(ib.id),jumlah=100),dict(id=moves[1].id,sumber=str(ia.id),jumlah=100)]
        ids=(ia.id,ib.id)
    r,_=await save(pg,uid,kode,bahan=changes)
    assert r['hasil']['sesudah']['basis']==11000
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,ids[0])==0
        assert await g2._sisa_tumpukan_intake(db,ids[1])==0

async def test_status_kiriman_setelah_commit_tanpa_kirim_ulang(pg,running):
    from app.web.koreksi_bahan_berjalan import Rancangan,tulis,status
    uid,kode,mid,it=running
    # Simulasikan balasan hilang setelah commit dengan mengabaikan hasilnya.
    _,body=await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)])
    async with pg() as db:
        u=await db.get(User,uid)
        response=await status(body['kunci'],user=u)
        import json
        observed=json.loads(response.body)
        assert observed['tercatat'] and observed['hasil']['sesudah']['entries'][0]['sisa']==300
        assert await g2._sisa_tumpukan_intake(db,it)==2200


async def test_giling_sisa_eksplisit_menyimpan_audit_sebelum_asli(pg,hasil):
    from app.penggilingan.gudang1.services import milling as m
    from app.models import ActivityLog
    import json
    u,pr,_=hasil
    async with pg() as db:
        user=await db.get(User,u.id);user.role='admin';await db.commit()
        src=(await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==pr.id).order_by(MillingProcessSource.id))).first()
        sid=src.silo_storage_id;mid=src.id
        await m.tutup_silo_giling(db,user=user,kode_proses=pr.kode_proses,nama_silo='A',sisa_kg=500)
        st=await db.get(SiloStorage,sid);key=f'batch:{st.purchase_batch_id}'
    await save(pg,u.id,pr.kode_proses,jenis='giling',bahan=[dict(id=sid,sumber=key,jumlah=5800,sisa=400)])
    async with pg() as db:
        audit=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='milling_process_sources',ActivityLog.record_id==mid,ActivityLog.field_name=='koreksi_bahan_sisa').order_by(ActivityLog.id.desc()))
        assert D(str(json.loads(audit.old_value)['berat_akhir_kg']))==500
        assert D(str(json.loads(audit.new_value)['berat_akhir_kg']))==400

async def test_giling_pertukaran_sumber_tanpa_menggandakan_alokasi(pg,hasil):
    u,pr,_=hasil
    async with pg() as db:
        user=await db.get(User,u.id);user.role='admin';await db.commit()
        ctx=await s.konteks(db,jenis='giling',kode=pr.kode_proses,user=user)
        a,b=ctx['entries']
    result,_=await save(pg,u.id,pr.kode_proses,jenis='giling',bahan=[
        dict(id=a['id'],sumber=b['sumber'],jumlah=b['jumlah']),
        dict(id=b['id'],sumber=a['sumber'],jumlah=a['jumlah'])])
    after=result['hasil']['sesudah']
    assert after['basis']==10000
    assert sorted(e['kg'] for e in after['entries'])==[4000,6000]
    assert all(src['bebas']==0 for src in after['sources'] if src['key'] in (a['sumber'],b['sumber']))
    async with pg() as db:
        assert not await db.scalar(select(SiloStorage.id).where(SiloStorage.status=='koreksi').limit(1))

from tests.pg.test_gabah_kering_dikemas import pabrik
async def test_bongkar_gabah_ganti_sumber_dan_batal_menjaga_lot_asal(pg,pabrik):
    from tests.pg.test_gabah_kering_dikemas import _isi_silo_langsung,_keluarkan
    from app.penggilingan.gudang1.services.silo import masuk_silo
    from app.penggilingan.gudang1.services.gabah_kering import saldo_gabah_kering
    from app.models import GabahKeringBongkar,GabahKeringLot
    a=await _isi_silo_langsung(pg,pabrik,huruf='A',kode='GB-KOREKSI-01',kg=1000)
    first=await _keluarkan(pg,pabrik,silo_storage_id=a,berat_kg=1000)
    b=await _isi_silo_langsung(pg,pabrik,huruf='B',kode='GB-KOREKSI-02',kg=1500)
    second=await _keluarkan(pg,pabrik,silo_storage_id=b,berat_kg=1500)
    async with pg() as db:
        u=await db.get(User,pabrik['user'])
        await masuk_silo(db,user=u,nama_silo='B',kode_lot=None,kode_batch=None,kode_gkr=first.lot.kode_lot)
        bo=await db.scalar(select(GabahKeringBongkar).where(GabahKeringBongkar.gabah_kering_lot_id==first.lot.id));sid=bo.silo_storage_id
    key=f'bongkar:{second.lot.id}'
    await save(pg,pabrik['user'],f'catatan-{sid}',jenis='giling',bahan=[dict(id=sid,sumber=key,jumlah=800)])
    async with pg() as db:
        assert await saldo_gabah_kering(db,first.lot.id)==1000
        assert await saldo_gabah_kering(db,second.lot.id)==700
        assert (await db.get(GabahKeringLot,first.lot.id)).berat_timbang_kg==1000
    await save(pg,pabrik['user'],f'catatan-{sid}',jenis='giling',bahan=[dict(id=sid,hapus=True)],key='uji-bongkar-batal-123')
    async with pg() as db:
        assert await saldo_gabah_kering(db,second.lot.id)==1500
        assert (await db.get(SiloStorage,sid)).status=='batal'
        assert await db.get(GabahKeringLot,first.lot.id)

async def test_hasil_bertambah_tidak_membatalkan_kemasan_lama(pg,running):
    from tests.pg.test_masukkan_beras_silo import _kemas_grade
    from app.models import FinishedGoodsStock
    from app.services.seed import seed_master
    uid,kode,mid,it=running
    await seed_master()
    await _kemas_grade(pg,dict(user=uid,kode_pol=kode),grade='medium',jumlah_karung=10,ukuran=25)
    async with pg() as db:
        old=[(x.id,x.jumlah_karung,x.berat_total_kg) for x in (await db.scalars(select(FinishedGoodsStock))).all()]
    r,_=await save(pg,uid,kode,hasil={'medium':2200})
    assert r['hasil']['sesudah']['outputs']['medium']==2200
    async with pg() as db:
        assert [(x.id,x.jumlah_karung,x.berat_total_kg) for x in (await db.scalars(select(FinishedGoodsStock))).all()]==old

async def test_koreksi_dua_bahan_satu_siklus_memakai_dampak_akhir_bersama(pg,dunia):
    async with pg() as db:
        u,a,ia=await batch_baru(db,dunia,n=100,w=5000,kode='PKB-GABUNG-A')
        _,b,ib=await batch_baru(db,dunia,n=100,w=5000,kode='PKB-GABUNG-B')
        await pindah(db,u,ia,20,'A');await pindah(db,u,ib,20,'A')
        pr=(await p.mulai_penyosohan(db,user=u,nama_silos=['A'])).proc
        await p.selesai_penyosohan(db,user=u,kode=pr.kode_proses,nama_silo='A',sisa_kg=100)
        u.role='admin';await db.commit();uid=u.id;kode=pr.kode_proses
        moves=(await db.scalars(select(PkTumpukanToSilo).order_by(PkTumpukanToSilo.id))).all()
        changes=[dict(id=moves[0].id,sumber=str(ia.id),jumlah=10),dict(id=moves[1].id,sumber=str(ib.id),jumlah=30)]
    result,_=await save(pg,uid,kode,bahan=changes)
    assert result['hasil']['sesudah']['basis']==1900
    assert all(e['sisa']==100 for e in result['hasil']['sesudah']['entries'])
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,ia.id)==4500
        assert await g2._sisa_tumpukan_intake(db,ib.id)==3500

async def test_beberapa_siklus_satu_rancangan_tidak_mengalirkan_selisih_dua_kali(pg,dunia):
    async with pg() as db:
        u,a,ia=await batch_baru(db,dunia,n=100,w=5000,kode='PKB-SIKLUS-A')
        _,b,ib=await batch_baru(db,dunia,n=100,w=5000,kode='PKB-SIKLUS-B')
        await pindah(db,u,ia,20,'A')
        proc=(await p.mulai_penyosohan(db,user=u,nama_silos=['A'])).proc
        await p.selesai_penyosohan(db,user=u,kode=proc.kode_proses,nama_silo='A',sisa_kg=500)
        await pindah(db,u,ib,20,'A')
        await p.tambah_silo_penyosohan(db,user=u,kode=proc.kode_proses,nama_silos=['A'])
        await p.selesai_penyosohan(db,user=u,kode=proc.kode_proses,nama_silo='A',sisa_kg=400)
        await p.tambah_silo_penyosohan(db,user=u,kode=proc.kode_proses,nama_silos=['A'])
        u.role='admin';await db.commit();uid=u.id;kode=proc.kode_proses
        rows=(await db.scalars(select(PkTumpukanToSilo).order_by(PkTumpukanToSilo.id))).all()
        changes=[dict(id=rows[0].id,sumber=str(ia.id),jumlah=18),dict(id=rows[1].id,sumber=str(ib.id),jumlah=22)]
    result,_=await save(pg,uid,kode,bahan=changes)
    assert result['hasil']['sesudah']['basis']==2000
    async with pg() as db:
        usages=(await db.scalars(select(PolishingSiloUsage).order_by(PolishingSiloUsage.id))).all()
        assert [x.berat_akhir_kg for x in usages]==[400,400,None]
        assert [x.berat_terpakai_kg for x in usages[:2]]==[500,1100]
        assert usages[2].berat_awal_kg==400
        from hmu_core.proses_db import ProsesTerpadu,ArusProsesTerpadu
        shared=await db.scalar(select(ProsesTerpadu).where(ProsesTerpadu.tabel_sumber=='polishing_process',ProsesTerpadu.id_sumber==str(proc.id)))
        total=await db.scalar(select(func.sum(ArusProsesTerpadu.berat_kg)).where(ArusProsesTerpadu.proses_id==shared.id,ArusProsesTerpadu.arah=='bahan'))
        assert total==2000

async def test_siklus_lanjutan_selesai_dilindungi_dari_koreksi_bahan(pg,running):
    uid,kode,mid,it=running
    async with pg() as db:
        u=await db.get(User,uid)
        nxt=(await p.mulai_penyosohan(db,user=u,nama_silos=['A'])).proc
        await p.catat_output(db,user=u,kode=nxt.kode_proses,jenis='medium',berat_kumulatif=450)
        await p.catat_output(db,user=u,kode=nxt.kode_proses,jenis='broken',berat_kumulatif=50)
        await p.selesai_penyosohan(db,user=u,kode=nxt.kode_proses,nama_silo='A',sisa_kg=0)
        await p.akhiri_penyosohan(db,user=u,kode=nxt.kode_proses)
    with pytest.raises(ValueError,match='selesai'):await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)])
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,it)==2000
        assert (await db.get(PkTumpukanToSilo,mid)).jumlah_karung==60

async def test_koreksi_sisa_yang_sama_tidak_membuat_jejak_baru(pg,running):
    uid,kode,mid,it=running
    with pytest.raises(ValueError,match='Tidak ada perubahan'):await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=60,sisa=500)])
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.JENIS))==0

async def test_jawaban_http_putus_setelah_commit_diperiksa_sebelum_retry(pg,running):
    import httpx
    uid,kode,mid,it=running
    async with await _klien(pg,peran='superadmin') as c:
        path=f'/api/actions/koreksi-bahan/sosoh/{kode}'
        ctx=(await c.get(path)).json()
        req=dict(dasar=ctx['dasar'],bahan=[dict(id=mid,sumber=str(it),jumlah=56)],hasil={},alasan='Uji balasan putus setelah transaksi',kunci='uji-putus-http-12345')
        pre=await c.post(path+'/periksa',json=req,headers={'X-CSRF-Token':cap_formulir(c)});assert pre.status_code==200,pre.text
        req.update(pemeriksaan=pre.json()['pemeriksaan'],konfirmasi=True)
        async def putus(response):
            if response.request.url.path==path+'/simpan' and response.status_code==200:raise httpx.ReadError('Simulasi balasan terputus setelah commit',request=response.request)
        c.event_hooks['response'].append(putus)
        with pytest.raises(httpx.ReadError):await c.post(path+'/simpan',json=req,headers={'X-CSRF-Token':cap_formulir(c)})
        c.event_hooks['response'].remove(putus)
        status=(await c.get('/api/actions/koreksi-bahan-status/'+req['kunci'])).json();assert status['tercatat']
        retry=await c.post(path+'/simpan',json=req,headers={'X-CSRF-Token':cap_formulir(c)})
        assert retry.status_code==200 and retry.json()['sudah_tercatat'] and retry.json()['peristiwa_id']==status['peristiwa_id']
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,it)==2200
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.JENIS))==1
