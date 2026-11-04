import asyncio
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from app.models import User,PolishingProcess,PolishingOutputLog,Peristiwa,FinishedGoodsStock,ByproductStock,ProductSku
from app.database import now_local
from app.services import koreksi_pengemasan_asal as s,pengemasan_otomatis as auto,stok,koreksi_bahan_berjalan as aktif
from app.services.koreksi_pengiriman import cap
from app.penggilingan.gudang2 import polishing as p
from tests.pg.test_barang_keluar import gudang,_klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio
async def seed(pg,g,done=False,kind='broken',cumulative=False):
    async with pg() as db:
        pr=await db.scalar(select(PolishingProcess));pr.status='proses';pr.waktu_selesai=None
        await db.commit();pid=pr.id
        u=await db.get(User,g['op'])
        if cumulative:
            a=await p.catat_output(db,user=u,kode=pr.kode_proses,jenis=kind,berat_kumulatif=325)
            await p.catat_output(db,user=u,kode=pr.kode_proses,jenis=kind,berat_kumulatif=1250)
        else:
            await p.catat_output(db,user=u,kode=pr.kode_proses,jenis=kind,berat_kg=325)
            await p.catat_output(db,user=u,kode=pr.kode_proses,jenis=kind,berat_kg=925)
        pr=await db.get(PolishingProcess,pid)
        if done:pr.status='selesai';pr.waktu_selesai=now_local()
        await db.commit()
        ids=list((await db.scalars(select(PolishingOutputLog.id).where(PolishingOutputLog.polishing_process_id==pid,PolishingOutputLog.jenis==kind).order_by(PolishingOutputLog.id))).all())
    return pid,ids
async def preview(pg,g,pid,kind,req):
    async with pg() as db:
        plan=await s.rencana(db,pid,kind,await db.get(User,g['adm']),req);await db.commit();return plan,cap(plan)
async def apply(pg,g,pid,kind,req,t,key=None):
    async with pg() as db:
        e=await s.simpan(db,pid,kind,await db.get(User,g['adm']),req,dasar=t,kunci=key or uuid4().hex);await db.commit();return e
@pytest.mark.parametrize('done',[False,True])
@pytest.mark.parametrize('cumulative',[False,True])
@pytest.mark.parametrize('kind',['broken','bekatul','menir','reject'])
async def test_selected_325_250_cancel_others_925(pg,gudang,done,cumulative,kind):
    pid,ids=await seed(pg,gudang,done,kind,cumulative)
    req=dict(catatan_id=ids[0],aksi='ubah',kg='250',alasan='Salah catat hasil asal')
    pre,t=await preview(pg,gudang,pid,kind,req)
    assert pre['sebelum']['ringkasan']['total_proses']==1250
    assert pre['sesudah']['ringkasan']['total_proses']==1175
    size=40 if kind=='bekatul' else 50
    assert pre['sesudah']['ringkasan']['karung']==int(1175//size)
    assert pre['sesudah']['ringkasan']['curah']==1175%size
    async with pg() as db:assert float((await db.get(PolishingOutputLog,ids[0])).berat_kg)==325
    key=uuid4().hex;e=await apply(pg,gudang,pid,kind,req,t,key);await apply(pg,gudang,pid,kind,req,t,key)
    assert e.muatan['hasil_lain']==925
    req=dict(catatan_id=ids[0],aksi='batal',kg='',alasan='Catatan terpilih ternyata duplikat')
    pre,t=await preview(pg,gudang,pid,kind,req);await apply(pg,gudang,pid,kind,req,t)
    assert pre['sesudah']['ringkasan']['total_proses']==925
    async with pg() as db:
        assert float((await db.get(PolishingOutputLog,ids[1])).berat_kg)==925
        assert (await db.get(PolishingProcess,pid)).status==('selesai' if done else 'proses')
        assert len((await db.scalars(select(Peristiwa).where(Peristiwa.jenis==s.JENIS))).all())==2
        assert await db.scalar(select(func.count()).select_from(ByproductStock))==0
    with pytest.raises(ValueError,match='sudah dibatalkan'):await preview(pg,gudang,pid,kind,req)
async def test_unrelated_packaging_no_block_and_partial_materialized(pg,gudang):
    pid,ids=await seed(pg,gudang,False,'broken')
    # Fixture sudah memiliki kemasan medium: bukan penghalang broken.
    req=dict(catatan_id=ids[0],aksi='ubah',kg='250',alasan='Koreksi broken bukan medium');_,t=await preview(pg,gudang,pid,'broken',req);await apply(pg,gudang,pid,'broken',req,t)
    async with pg() as db:
        db.add(ByproductStock(jenis_produk='broken',source_type='polishing',source_id=pid,berat_kg=1000,tanggal=now_local().date(),waktu=now_local(),input_by=gudang['adm']));await db.commit()
    # Hanya 1000 dari total1175 yang sudah dibukukan; penurunan hingga1050 sah.
    req['kg']='125';_,t=await preview(pg,gudang,pid,'broken',req);await apply(pg,gudang,pid,'broken',req,t)
    req['kg']='0'
    with pytest.raises((ValueError,p.Gudang2Error),match='byproduct_stock'):await preview(pg,gudang,pid,'broken',req)

async def test_conflict_retry_race_rollback(pg,gudang,monkeypatch):
    pid,ids=await seed(pg,gudang)
    req=dict(catatan_id=ids[0],aksi='ubah',kg='250',alasan='Koreksi sah');_,t=await preview(pg,gudang,pid,'broken',req)
    async with pg() as db:
        await p.catat_output(db,user=await db.get(User,gudang['op']),kode=(await db.get(PolishingProcess,pid)).kode_proses,jenis='broken',berat_kg=1)
    with pytest.raises(ValueError,match='berubah'):await apply(pg,gudang,pid,'broken',req,t)
    _,t=await preview(pg,gudang,pid,'broken',req);key=uuid4().hex
    a,b=await asyncio.gather(apply(pg,gudang,pid,'broken',req,t,key),apply(pg,gudang,pid,'broken',req,t,key));assert a.id==b.id
    req['kg']='200';_,t=await preview(pg,gudang,pid,'broken',req)
    original=s.buku.catat
    async def fail(*a,**kw):raise ValueError('Audit gagal uji')
    monkeypatch.setattr(s.buku,'catat',fail)
    async with pg() as db:
        with pytest.raises(ValueError,match='Audit gagal'):await s.simpan(db,pid,'broken',await db.get(User,gudang['adm']),req,dasar=t,kunci=uuid4().hex)
        await db.commit()
        assert float((await db.get(PolishingOutputLog,ids[0])).berat_kg)==250
async def test_canceled_note_never_revived_by_total_or_undo(pg,gudang):
    pid,ids=await seed(pg,gudang)
    req=dict(catatan_id=ids[0],aksi='batal',kg='',alasan='Duplikat');_,t=await preview(pg,gudang,pid,'broken',req);await apply(pg,gudang,pid,'broken',req,t)
    async with pg() as db:
        user=await db.get(User,gudang['adm']);pr=await db.get(PolishingProcess,pid)
        await aktif.hasil_berjalan(db,'sosoh',pr,{'broken':1100},user,'Koreksi total berikutnya');await db.commit()
        assert float((await db.get(PolishingOutputLog,ids[0])).berat_kg)==0
        assert (await stok.output_sosoh(db,pid))['broken']==1100
        from app.services.undo import _undo_output_sosoh,UndoError
        with pytest.raises(UndoError,match='per transaksi'):await _undo_output_sosoh(db,ids[0])
async def test_empty_bags_and_source_packing_unchanged(pg,gudang):
    from app.penggilingan.inventory.packaging import hitung_stok_kemasan
    pid,ids=await seed(pg,gudang)
    async with pg() as db:
        sku=await db.get(ProductSku,gudang['sku']);args=(sku.packaging_material_id,sku.package_size_id,sku.brand_id)
        n=await hitung_stok_kemasan(db,*args)
        initial=[aktif.raw(r) for r in (await db.scalars(select(FinishedGoodsStock))).all()]
    req=dict(catatan_id=ids[0],aksi='ubah',kg='250',alasan='Koreksi tanpa transaksi kemasan');_,t=await preview(pg,gudang,pid,'broken',req);await apply(pg,gudang,pid,'broken',req,t)
    async with pg() as db:
        assert await hitung_stok_kemasan(db,*args)==n
        assert [aktif.raw(r) for r in (await db.scalars(select(FinishedGoodsStock))).all()]==initial
@pytest.mark.parametrize('role',['superadmin','admin','operator:g1','operator:g2'])
async def test_role_and_view_as_separate_correction_cancel(pg,gudang,role):
    pid,ids=await seed(pg,gudang)
    async with pg() as db:(await db.get(User,gudang['adm'])).role='superadmin';await db.commit()
    async with await _klien(pg,gudang['adm'],'uji-pack-view',mode='superadmin') as c:
        if role!='superadmin':assert (await c.post('/lihat-sebagai',data={'peran':role,'_csrf':cap_formulir(c)})).status_code==303
        body=dict(catatan_id=ids[0],aksi='ubah',kg='250',alasan='Uji izin efektif',kunci=uuid4().hex)
        page=await c.get(f'/pengemasan-otomatis/sosoh/{pid}/broken');assert page.status_code==(403 if role=='operator:g1' else 200)
        r=await c.post(f'/api/actions/pengemasan-otomatis/{pid}/broken/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==(403 if role=='operator:g1' else 200),r.text
        body['aksi']='batal'
        r=await c.post(f'/api/actions/pengemasan-otomatis/{pid}/broken/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==(200 if role in ('admin','superadmin') else 403),r.text
async def test_closed_operator_denied_and_direct_url_csrf(pg,gudang):
    pid,ids=await seed(pg,gudang,True)
    async with await _klien(pg,gudang['op'],'uji-pack-op') as c:assert (await c.get(f'/pengemasan-otomatis/sosoh/{pid}/broken')).status_code==403
    async with await _klien(pg,gudang['adm'],'uji-pack-adm') as c:
        page=await c.get(f'/pengemasan-otomatis/sosoh/{pid}/broken');assert page.status_code==200
        body=dict(catatan_id=ids[0],aksi='ubah',kg='250',alasan='Uji CSRF',kunci=uuid4().hex)
        assert (await c.post(f'/api/actions/pengemasan-otomatis/{pid}/broken/periksa',json=body)).status_code==403
        h={'X-CSRF-Token':cap_formulir(c)}
        r=await c.post(f'/api/actions/pengemasan-otomatis/{pid}/broken/periksa',json=body,headers=h);assert r.status_code==200,r.text
        r=await c.post(f'/api/actions/pengemasan-otomatis/{pid}/broken/simpan',json={**body,'dasar':r.json()['dasar'],'konfirmasi':True},headers=h);assert r.status_code==200,r.text
        assert (await c.get(f'/api/actions/pengemasan-otomatis/{pid}/broken/status?kunci='+body['kunci'])).json()['ditemukan']
async def test_foreign_source_negative_fraction_precision(pg,gudang):
    pid,ids=await seed(pg,gudang)
    for note,kg in [(999999,'250'),(ids[0],'-1'),(ids[0],'1.234'),(ids[0],'NaN'),(ids[0],'325')]:
        with pytest.raises(ValueError):await preview(pg,gudang,pid,'broken',dict(catatan_id=note,aksi='ubah',kg=kg,alasan='Uji penolakan'))

@pytest.mark.parametrize('done',[False,True])
async def test_total_correction_paths_match_shared_reader(pg,gudang,done):
    pid,ids=await seed(pg,gudang,done)
    async with pg() as db:
        pr=await db.get(PolishingProcess,pid);u=await db.get(User,gudang['adm']);base=await stok.output_sosoh(db,pid)
        if done:
            await p.koreksi_hasil_sosoh(db,user=u,process_id=pid,perubahan={k:1175 if k=='broken' else base.get(k,0) for k in p._ALL_JENIS},dasar={k:base.get(k,0) for k in p._ALL_JENIS},alasan='Koreksi total melalui riwayat',simpan=False)
        else:await aktif.hasil_berjalan(db,'sosoh',pr,{'broken':1175},u,'Koreksi total melalui formulir berjalan')
        await db.commit();c=await auto.ringkasan(db,pr,'broken')
        assert (c['total_proses'],c['saldo_pemilik'],c['karung'],c['berat_terkemas'],c['curah'])==(1175,1175,23,1150,25)
        assert (await stok.output_sosoh(db,pid))['medium']==10000
async def test_partial_outgoing_remaining_not_initial_total(pg,gudang):
    from tests.pg.test_barang_keluar import _pelanggan
    from app.services import barang_keluar as bk
    pid,ids=await seed(pg,gudang)
    customer=await _pelanggan(pg,'Pembeli curah uji')
    async with pg() as db:
        h=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=customer,baris=[bk.BarisPerintah(tipe='byproduct_curah',jenis='broken',berat_kg=800)])
        await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=h.rec.id)
    req=dict(catatan_id=ids[0],aksi='ubah',kg='250',alasan='Koreksi saldo setelah muatan');plan,t=await preview(pg,gudang,pid,'broken',req)
    assert plan['sesudah']['ringkasan']['saldo_pemilik']==375
    assert plan['sesudah']['ringkasan']['karung']==7 and plan['sesudah']['ringkasan']['curah']==25
    await apply(pg,gudang,pid,'broken',req,t)
    # Mengurangi catatan 925 menjadi0 akan mengganggu muatan800.
    with pytest.raises((ValueError,p.Gudang2Error),match='saldo pemilik'):await preview(pg,gudang,pid,'broken',dict(catatan_id=ids[1],aksi='ubah',kg='0',alasan='Uji penghalang pengiriman'))
async def test_zero_and_fractional_not_rounded_to_missing(pg,gudang):
    pid,ids=await seed(pg,gudang)
    async with pg() as db:
        (await db.get(PolishingOutputLog,ids[1])).berat_kg=0;await db.commit()
    req=dict(catatan_id=ids[0],aksi='ubah',kg='0.25',alasan='Bobot kecil tetap sah');plan,t=await preview(pg,gudang,pid,'broken',req)
    assert plan['sesudah']['ringkasan']['curah']==.25 and plan['sesudah']['ringkasan']['saldo_pemilik']==.25
    await apply(pg,gudang,pid,'broken',req,t)
    req.update(kg='0');_,t=await preview(pg,gudang,pid,'broken',req);await apply(pg,gudang,pid,'broken',req,t)
    req.update(aksi='batal');_,t=await preview(pg,gudang,pid,'broken',req);await apply(pg,gudang,pid,'broken',req,t)
    async with pg() as db:assert ids[0] in await s.batal_ids(db,pid)
async def test_stock_entry_points_and_pagination_totals(pg,gudang):
    pid,ids=await seed(pg,gudang)
    async with pg() as db:
        u=await db.get(User,gudang['op']);proc=await db.get(PolishingProcess,pid)
        for _ in range(30):await p.catat_output(db,user=u,kode=proc.kode_proses,jenis='broken',berat_kg=1,simpan=False)
        await db.commit()
        d=await s.data(db,pid,'broken',await db.get(User,gudang['adm']))
        assert len(d['catatan'])==25 and d['berikut']
        assert d['ringkasan']['total_proses']==1280
        older=await s.data(db,pid,'broken',await db.get(User,gudang['adm']),sebelum=d['berikut'])
        assert older['ringkasan']['total_proses']==1280 and ids[0] in [r['id'] for r in older['catatan']]
    async with await _klien(pg,gudang['adm'],'uji-stock-entry') as c:
        page=await c.get('/stok-produk/detail?jenis=broken');assert page.status_code==200,page.text
        assert f'/pengemasan-otomatis/sosoh/{pid}/broken' in page.text

async def test_source_correction_while_paused_preserves_pause(pg,gudang):
    from app.penggilingan.gudang1.services import jeda
    pid,ids=await seed(pg,gudang)
    async with pg() as db:
        u=await db.get(User,gudang['op']);pr=await db.get(PolishingProcess,pid)
        await jeda.hentikan(db,user=u,jenis='penyosohan',kode=pr.kode_proses,sebab='Listrik padam')
    req=dict(catatan_id=ids[0],aksi='ubah',kg='250',alasan='Pembetulan saat dijeda')
    async with pg() as db:
        u=await db.get(User,gudang['op']);plan=await s.rencana(db,pid,'broken',u,req)
        await s.simpan(db,pid,'broken',u,req,dasar=cap(plan),kunci=uuid4().hex);await db.commit()
        assert await jeda.jeda_terbuka(db,'penyosohan',pid)
        assert (await db.get(PolishingProcess,pid)).status=='proses'
        assert (await auto.ringkasan(db,await db.get(PolishingProcess,pid),'broken'))['karung']==23
