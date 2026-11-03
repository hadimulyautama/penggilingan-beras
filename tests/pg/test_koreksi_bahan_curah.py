"""Bahan selain PK memakai sumber curah dan siklus asli, tanpa stok kedua."""
from decimal import Decimal as D
import pytest
from sqlalchemy import select
from app.models import User,PolishingOutputLog,BerasKeSilo,HasilSampingKeSilo,BrokenKeSilo,ByproductStock,PolishingSiloUsage
from app.database import now_local
from app.services import koreksi_bahan_berjalan as s
from app.penggilingan.gudang2 import service as g2,polishing as p
from tests.pg.test_masukkan_beras_silo import sosoh
from tests.pg.test_koreksi_bahan_berjalan import save
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def curah(pg,sosoh,request):
    tipe=request.param
    async with pg() as db:
        u=await db.get(User,sosoh['user']);uid=u.id
        if tipe=='beras':
            await g2.masukkan_beras_ke_silo(db,user=u,jenis='medium',kode_pol='POL-UJIR-01',nama_silo='C',berat_kg=1000)
            model=BerasKeSilo
        elif tipe=='samping':
            db.add(PolishingOutputLog(polishing_process_id=sosoh['proc_id'],jenis='menir',berat_kg=2000,waktu_update=now_local(),input_by=uid));await db.commit()
            await g2.masukkan_hasil_samping_ke_silo(db,user=u,jenis='menir',jasa_id=None,nama_silo='C',berat_kg=1000)
            model=HasilSampingKeSilo
        else:
            db.add(ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=999,berat_kg=2000,tanggal=now_local().date(),waktu=now_local(),input_by=uid));await db.commit()
            b=await db.scalar(select(ByproductStock))
            await g2.pindah_broken_ke_silo(db,user=u,byproduct_stock_id=b.id,nama_silo='C',berat=1000)
            model=BrokenKeSilo
        move=await db.scalar(select(model));mid=move.id
        pr=(await p.mulai_penyosohan(db,user=u,nama_silos=['C'])).proc
        await p.catat_output(db,user=u,kode=pr.kode_proses,jenis='medium',berat_kumulatif=400)
        await p.selesai_penyosohan(db,user=u,kode=pr.kode_proses,nama_silo='C',sisa_kg=500)
        return uid,pr.kode_proses,tipe,mid

@pytest.mark.parametrize('curah',['beras','samping','broken'],indirect=True)
async def test_bahan_curah_dilepas_sisa_mengikuti_delta(pg,curah):
    uid,kode,tipe,mid=curah
    async with pg() as db:
        ctx=await s.konteks(db,jenis='sosoh',kode=kode,user=await db.get(User,uid))
        entry=next(e for e in ctx['entries'] if e['id']==f'{tipe}:{mid}')
        key=entry['sumber'];oldfree=next(x['bebas'] for x in ctx['sources'] if x['key']==key)
    result,body=await save(pg,uid,kode,bahan=[dict(id=entry['id'],sumber=key,jumlah=800)])
    after=result['hasil']['sesudah']
    assert after['basis']==500 and after['outputs']['medium']==400
    assert next(e['sisa'] for e in after['entries'] if e['id']==entry['id'])==300
    assert D(str(next(x['bebas'] for x in after['sources'] if x['key']==key)))==D(str(oldfree))+200
    async with pg() as db:
        assert (await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.berat_akhir_kg==300))).berat_terpakai_kg==500


async def test_koreksi_karung_beras_memakai_bobot_nyata_bukan_nominal(pg,sosoh):
    from tests.pg.test_beras_silo_berat_nyata import pembelian
    from app.models import FinishedGoodsStock
    src=await pembelian(pg,sosoh,berat=998,karung=20)
    async with pg() as db:
        uid=sosoh['user'];user=await db.get(User,uid)
        await g2.masukkan_beras_ke_silo(db,user=user,jenis='medium',sumber_stok=f"sku:{src['sku']}",nama_silo='C',berat_kg=998)
        move=await db.scalar(select(BerasKeSilo));mid=move.id
        pr=(await p.mulai_penyosohan(db,user=user,nama_silos=['C'])).proc;kode=pr.kode_proses
        await p.catat_output(db,user=user,kode=kode,jenis='medium',berat_kumulatif=400)
        await p.selesai_penyosohan(db,user=user,kode=kode,nama_silo='C',sisa_kg=500)
        ctx=await s.konteks(db,jenis='sosoh',kode=kode,user=user)
        e=next(e for e in ctx['entries'] if e['id']==f'beras:{mid}')
        assert e['satuan']=='karung' and e['jumlah']==20 and e['kg']==998
    result,_=await save(pg,uid,kode,bahan=[dict(id=e['id'],sumber=e['sumber'],jumlah=18)])
    after=result['hasil']['sesudah'];e2=next(x for x in after['entries'] if x['id']==e['id'])
    assert e2['jumlah']==18 and e2['kg']==898.2 and D(str(e2['sisa']))==D('400.20')
    assert after['basis']==498
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,src['id'])
        assert row.jumlah_karung==2 and row.berat_total_kg==D('99.80')
    await save(pg,uid,kode,bahan=[dict(id=e['id'],sumber=e['sumber'],jumlah=17)],key='uji-beras-koreksi-2')
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,src['id']);assert row.jumlah_karung==3 and row.berat_total_kg==D('149.70')

async def test_pembatalan_beras_belum_dipakai_memulihkan_sumber_sekali(pg,sosoh):
    from tests.pg.test_beras_silo_berat_nyata import pembelian
    from app.models import FinishedGoodsStock,Peristiwa
    src=await pembelian(pg,sosoh,berat=998,karung=20)
    async with pg() as db:
        uid=sosoh['user'];user=await db.get(User,uid)
        await g2.masukkan_beras_ke_silo(db,user=user,jenis='medium',sumber_stok=f"sku:{src['sku']}",nama_silo='C',berat_kg=998)
        move=await db.scalar(select(BerasKeSilo));mid=move.id
    result,body=await save(pg,uid,f'catatan-beras-{mid}',bahan=[dict(id=f'beras:{mid}',hapus=True)])
    assert result['hasil']['sesudah']['entries']==[]
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,src['id']);assert row.jumlah_karung==20 and row.berat_total_kg==998
        assert await db.scalar(select(BerasKeSilo.id).where(BerasKeSilo.id==mid)) is None
        original=await db.scalar(select(BerasKeSilo).where(BerasKeSilo.id==mid).execution_options(termasuk_dibatalkan=True))
        assert original.dibatalkan_pada and original.berat_kg==998
        assert (await s.simpan(db,jenis='sosoh',kode=f'catatan-beras-{mid}',user=await db.get(User,uid),req=body))['sudah_tercatat']
        await db.commit();assert row.berat_total_kg==998

async def test_hapus_curah_belum_dipakai_tidak_menghapus_proses_asal(pg,sosoh):
    from app.models import PolishingProcess
    async with pg() as db:
        uid=sosoh['user'];user=await db.get(User,uid)
        await g2.masukkan_beras_ke_silo(db,user=user,jenis='medium',kode_pol=sosoh['kode_pol'],nama_silo='C',berat_kg=1000)
        move=await db.scalar(select(BerasKeSilo));mid=move.id
    await save(pg,uid,f'catatan-beras-{mid}',bahan=[dict(id=f'beras:{mid}',hapus=True)])
    async with pg() as db:
        assert (await db.get(PolishingProcess,sosoh['proc_id'])).status=='selesai'
        assert await g2.hitung_stok_silo(db,sosoh['silo_beras'])==0

async def test_jejak_anak_koreksi_tidak_dapat_diundo_sendiri(pg,sosoh):
    from app.models import ActivityLog
    from app.services.undo import _undo_one,UndoError
    async with pg() as db:
        row=ActivityLog(table_name='silo_storage',record_id=999,action='UPDATE',changed_by=sosoh['user'],aksi=s.JENIS)
        with pytest.raises(UndoError,match='atomik'):await _undo_one(db,row,actor_id=sosoh['user'])

@pytest.mark.parametrize('curah',['beras'],indirect=True)
async def test_http_identitas_bahan_curah_dan_role_efektif(pg,curah):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.formulir import cap_formulir
    from app.web.lihat_sebagai import NAMA_KUKI
    uid,kode,tipe,mid=curah
    async with await _klien(pg,peran='superadmin') as client:
        path=f'/api/actions/koreksi-bahan/sosoh/{kode}'
        r=await client.get(path);assert r.status_code==200,r.text
        ctx=r.json();entry=next(e for e in ctx['entries'] if e['id']==f'beras:{mid}')
        body=dict(dasar=ctx['dasar'],bahan=[dict(id=entry['id'],sumber=entry['sumber'],jumlah=800)],hasil={},alasan='Pemeriksaan data nyata',kunci='uji-http-curah-12345')
        pre=await client.post(path+'/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(client)})
        assert pre.status_code==200,pre.text
        assert pre.json()['sesudah']['basis']==500
        body.update(pemeriksaan=pre.json()['pemeriksaan'],konfirmasi=True)
        ok=await client.post(path+'/simpan',json=body,headers={'X-CSRF-Token':cap_formulir(client)})
        assert ok.status_code==200,ok.text
        assert (await client.get('/api/actions/koreksi-bahan-status/'+body['kunci'])).json()['tercatat']
        client.cookies.set(NAMA_KUKI,'operator:g2')
        assert (await client.get(path)).status_code==403
        denied=await client.post(path+'/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(client)})
        assert denied.status_code==403

async def test_ganti_sumber_karung_ke_curah_memakai_satuan_sumber_pengganti(pg,sosoh):
    from tests.pg.test_beras_silo_berat_nyata import pembelian
    from app.models import FinishedGoodsStock
    src=await pembelian(pg,sosoh,berat=998,karung=20)
    async with pg() as db:
        uid=sosoh['user'];user=await db.get(User,uid);row=await db.get(FinishedGoodsStock,src['id'])
        other=FinishedGoodsStock(product_sku_id=row.product_sku_id,rice_quality_standard_id=row.rice_quality_standard_id,source_type='timbangan',source_id=99999,jumlah_karung=0,berat_total_kg=2000,warehouse_id=row.warehouse_id,waktu=now_local(),input_by=uid,curah_kemas_ulang=True,kemasan_mengurangi_stok=False)
        db.add(other);await db.commit();target=other.id
        await g2.masukkan_beras_ke_silo(db,user=user,jenis='medium',sumber_stok=f"sku:{src['sku']}",nama_silo='C',berat_kg=998)
        move=await db.scalar(select(BerasKeSilo));mid=move.id
        proc=(await p.mulai_penyosohan(db,user=user,nama_silos=['C'])).proc;kode=proc.kode_proses
        await p.selesai_penyosohan(db,user=user,kode=kode,nama_silo='C',sisa_kg=500)
    result,_=await save(pg,uid,kode,bahan=[dict(id=f'beras:{mid}',sumber=f'berasstok:medium:{target}',jumlah=900)])
    entry=result['hasil']['sesudah']['entries'][0]
    assert entry['satuan']=='kg' and entry['jumlah']==900 and entry['kg']==900
    assert D(str(entry['sisa']))==402
    async with pg() as db:
        old=await db.get(FinishedGoodsStock,src['id']);new=await db.get(FinishedGoodsStock,target)
        assert old.jumlah_karung==20 and old.berat_total_kg==998
        assert new.jumlah_karung==0 and new.berat_total_kg==1100
