"""Selisih stok nyata di database uji terpisah, bukan transaksi produksi."""
from decimal import Decimal as D
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select,text,func
from app.database import now_local
from app.models import FinishedGoodsStock,Peristiwa,Warehouse,User
from app.models.retur_supplier import ReturSupplierItem as I,ReturSupplierAktual as A,ReturSupplierKeluar as K
from app.models.retur_supplier_koreksi import ReturSupplierPerubahan as P,ReturSupplierEfektif as E
from app.services import retur_supplier as s,retur_supplier_selesai as f,retur_supplier_koreksi as k
from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
from hmu_identitas import peran as ROLE
from tests.pg.test_retur_supplier import asal,skema_retur_timbang,user,jumlah,siap_keluar,tiket,sidik_stok

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def keluar_dua(pg,asal,request):
    async with pg() as db:
        old,_,_=await siap_keluar(db,asal)
        await s.batalkan(db,user=user(asal),identitas=old.id,alasan='Siapkan dua sumber untuk uji koreksi')
        mode=getattr(request,'param','biasa')
        first=await db.get(FinishedGoodsStock,asal['fid'])
        if mode=='pecahan':first.jumlah_karung=30
        if mode=='curah':first.jumlah_karung=0;first.curah_kemas_ulang=True
        b=FinishedGoodsStock(product_sku_id=asal['sku'],source_type='timbangan',source_id=asal['tid'],jumlah_karung=10,berat_total_kg=499,warehouse_id=asal['wh'],input_by=asal['uid'],waktu=now_local())
        if mode=='pecahan':b.jumlah_karung=30;b.berat_total_kg=998
        if mode=='curah':b.jumlah_karung=0;b.curah_kemas_ulang=True
        if mode=='campuran':
            from app.models import ProductSku,PackageSize,KemasanTara
            size=await db.scalar(select(PackageSize.id).where(PackageSize.ukuran_kg==50))
            original_sku=await db.get(ProductSku,asal['sku'])
            sku=ProductSku(kategori='beras_putih',aktif=True,package_size_id=size,packaging_material_id=original_sku.packaging_material_id)
            db.add(sku);await db.flush();b.product_sku_id=sku.id
            tara=await db.scalar(select(KemasanTara).where(KemasanTara.package_size_id==size,KemasanTara.packaging_material_id==sku.packaging_material_id))
            if tara:tara.tara_per_karung_kg=D('.2')
            else:db.add(KemasanTara(package_size_id=size,packaging_material_id=sku.packaging_material_id,tara_per_karung_kg=D('.2')))
        db.add(b);await db.flush()
        p=[dict(kunci=f'beras:{asal["fid"]}',jumlah='3'),dict(kunci=f'beras:{b.id}',jumlah='2')]
        check=await s.periksa(db,asal['tid'],user(asal),p,'Kembalikan mutu','Catatan awal')
        r=await s.simpan(db,user=user(asal),tid=asal['tid'],jumlah=p,alasan=check['alasan'],catatan=check['catatan'],kunci=uuid4().hex,dasar=check['dasar'])
        t=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR')
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5000::numeric+:kg,berat_barang_kg=:kg,status_tiket='SELESAI' WHERE id=:id"),{'id':t,'kg':check['total_kg']})
        await s.hubungkan(db,user=user(asal),identitas=r.id,tiket_id=t);await db.commit()
        items=(await db.scalars(select(I).where(I.retur_supplier_id==r.id).order_by(I.id))).all()
        snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah=str(n)) for i,n in zip(items,[3,2])]);await db.commit()
        out=await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit()
        return dict(asal,rid=r.id,items=[i.id for i in items],tid_out=t,kode_keluar=out.kode,stok2=b.id)


def payload(x,a='4',b='1',**extra):
    return dict(identitas=x['rid'],kunci=uuid4().hex,jenis='jumlah',jumlah=[dict(item_id=i,jumlah=n) for i,n in zip(x['items'],[a,b])],alasan='Kesalahan pencatatan partai telah diperiksa',konfirmasi=True,**extra)


async def terapkan(db,x,p):
    snap=await k.periksa(db,user=user(x),**p);await db.commit()
    assert snap['status']=='terverifikasi_otomatis'
    rec=await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=snap['dasar'],konfirmasi=True);await db.commit()
    return snap,rec


async def test_antarpartai_selisih_beruntun_awal_utuh_dan_retry(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        ledger=await db.scalar(select(K));awal=ledger.snapshot.copy()
        original=[(a.item_id,a.jumlah,a.bobot_kg) for a in (await db.scalars(select(A))).all()]
        p=payload(x);snap,rec=await terapkan(db,x,p)
        assert [D(i['mutasi_kg']) for i in snap['items']]==[D('-49.9'),D('49.9')]
        again=await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=snap['dasar'],konfirmasi=True);await db.commit();assert again.peristiwa_id==rec.peristiwa_id
        snap,_=await terapkan(db,x,payload(x,'2','3'))
        assert [D(i['mutasi_kg']) for i in snap['items']]==[D('99.8'),D('-99.8')]
        data=await k.data(db,x['rid'],user(x));assert data['versi']==2
        assert [data['efektif'][i]['jumlah'] for i in x['items']]==[2,3]
        assert (await hitung_stok_finished_goods(db,x['sku'],None))['kg']==1247.5
        await db.refresh(ledger);assert ledger.snapshot==awal
        assert [(a.item_id,a.jumlah,a.bobot_kg) for a in (await db.scalars(select(A))).all()]==original
        assert await db.scalar(select(func.count()).select_from(P))==2


async def test_keterangan_dan_pembatalan_tidak_mengembalikan_stok(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        awal=await sidik_stok(db)
        for jenis,extra in [('keterangan',{'keterangan':'Keterangan yang benar'}),('batal',{'keberadaan':'kembali'})]:
            p=dict(identitas=x['rid'],kunci=uuid4().hex,jenis=jenis,alasan='Periksa dokumen dan barang',konfirmasi=True,**extra)
            snap=await k.periksa(db,user=user(x),**p);await db.commit()
            await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=snap['dasar'],konfirmasi=True);await db.commit()
        assert (await hitung_stok_finished_goods(db,x['sku'],None))['kg']==1247.5
        st=await db.get(E,x['rid']);assert st.dibatalkan and st.keterangan=='Keterangan yang benar'
        data=await k.data(db,x['rid'],user(x));assert data['penerimaan_kembali']['jumlah'] is None
        assert (await db.scalar(select(P).where(P.jenis=='batal'))).snapshot['status_fisik']=='menunggu_penerimaan'
        assert await db.scalar(select(func.count()).select_from(K))==1


@pytest.mark.parametrize('kasus',['negatif','pecahan','kosong','nan','lebih','tetap','alasan','konfirmasi','asing','ganda'])
async def test_jumlah_tidak_sah_dan_relasi_ditolak(pg,keluar_dua,kasus):
    x=keluar_dua;p=payload(x)
    if kasus in ('negatif','pecahan','kosong','nan','lebih'):p['jumlah'][0]['jumlah']={'negatif':'-1','pecahan':'4.5','kosong':'','nan':'NaN','lebih':'999999'}[kasus]
    if kasus=='tetap':p=payload(x,'3','2')
    if kasus=='alasan':p['alasan']='   '
    if kasus=='konfirmasi':p['konfirmasi']=False
    if kasus=='asing':p['jumlah'][0]['item_id']=2147483647
    if kasus=='ganda':p['jumlah'][1]['item_id']=p['jumlah'][0]['item_id']
    async with pg() as db:
        with pytest.raises(ValueError):await k.periksa(db,user=user(x),**p)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(P))==0
        assert (await hitung_stok_finished_goods(db,x['sku'],None))['kg']==1247.5


@pytest.mark.parametrize('perubahan',['saldo','revisi','versi'])
async def test_snapshot_lama_ditolak_tanpa_mutasi(pg,keluar_dua,perubahan):
    x=keluar_dua;p=payload(x)
    async with pg() as db:
        snap=await k.periksa(db,user=user(x),**p);await db.commit()
        if perubahan=='saldo':
            row=await db.get(FinishedGoodsStock,x['fid']);row.berat_total_kg=997
        elif perubahan=='revisi':await db.execute(text('UPDATE timbangan_transaksi SET jumlah_revisi=jumlah_revisi+1 WHERE id=:id'),{'id':x['tid_out']})
        else:
            st=await db.get(E,x['rid']);st.versi=1
        await db.commit()
        with pytest.raises(ValueError,match='berubah|Belum ada perubahan'):await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=snap['dasar'],konfirmasi=True)
        await db.commit();assert await db.scalar(select(func.count()).select_from(P))==0


async def test_saldo_sumber_dan_alokasi_lain_tidak_dipakai_ulang(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        req=[dict(kunci=f'beras:{x["stok2"]}',jumlah='8')]
        c=await s.periksa(db,x['tid'],user(x),req,'Alokasi permintaan lain','')
        await s.simpan(db,user=user(x),tid=x['tid'],jumlah=req,alasan=c['alasan'],catatan='',kunci=uuid4().hex,dasar=c['dasar']);await db.commit()
        with pytest.raises(ValueError,match='stok bebas|Karung bebas'):
            await k.periksa(db,user=user(x),**payload(x,'2','3'))
        assert await db.scalar(select(func.count()).select_from(P))==0


async def test_besar_tetap_manual_setelah_reload_draf_baru_dan_alasan_saja(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        bad=payload(x,'4','2');snap=await k.periksa(db,user=user(x),**bad);await db.commit()
        assert snap['status']=='perlu_koreksi'
        # Memuat halaman/draf baru tidak menghapus penahanan pada retur.
        await k.data(db,x['rid'],user(x))
        again=await k.periksa(db,user=user(x),**dict(bad,alasan='Mengganti alasan saja'));await db.commit()
        assert again['status']=='perlu_koreksi'
        good=payload(x,'4','1');snap=await k.periksa(db,user=user(x),**good);await db.commit()
        assert snap['status']=='siap_manual'
        with pytest.raises(ValueError):await k.simpan(db,user=user(x),identitas=x['rid'],kunci=good['kunci'],dasar=snap['dasar'],konfirmasi=True)
        with pytest.raises(ValueError):await k.manual(db,user=user(x),identitas=x['rid'],kunci=good['kunci'],dasar=snap['dasar'],catatan=' ',konfirmasi=True)
        m=await k.manual(db,user=user(x),identitas=x['rid'],kunci=good['kunci'],dasar=snap['dasar'],catatan='Periksa kesalahan rincian fisik dan timbang',konfirmasi=True);await db.commit();assert m['status']=='terverifikasi_manual'
        await k.simpan(db,user=user(x),identitas=x['rid'],kunci=good['kunci'],dasar=snap['dasar'],konfirmasi=True);await db.commit()
        assert (await db.get(E,x['rid'])).wajib_manual


async def test_audit_gagal_rollback_seluruh_sumber(pg,keluar_dua,monkeypatch):
    x=keluar_dua;p=payload(x)
    async with pg() as db:
        snap=await k.periksa(db,user=user(x),**p);await db.commit()
        async def gagal(*a,**kw):raise RuntimeError('Gangguan audit sintetis')
        monkeypatch.setattr(k,'log_activity',gagal)
        with pytest.raises(RuntimeError):await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=snap['dasar'],konfirmasi=True)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(P))==0
        assert (await db.get(E,x['rid'])).versi==0
        assert (await hitung_stok_finished_goods(db,x['sku'],None))['kg']==1247.5


async def test_dua_sesi_kunci_sama_hanya_satu_perubahan(pg,keluar_dua):
    import asyncio
    x=keluar_dua;p=payload(x)
    async with pg() as db:snap=await k.periksa(db,user=user(x),**p);await db.commit()
    async def simpan():
        async with pg() as db:
            rec=await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=snap['dasar'],konfirmasi=True);await db.commit();return rec.peristiwa_id
    ids=await asyncio.gather(simpan(),simpan());assert ids[0]==ids[1]
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(P))==1


@pytest.mark.parametrize('tempat',['','kembali','di_luar'])
async def test_pembatalan_keberadaan_eksplisit_dan_tidak_mengubah_stok(pg,keluar_dua,tempat):
    x=keluar_dua;p=dict(identitas=x['rid'],kunci=uuid4().hex,jenis='batal',alasan='Dokumen dan posisi barang sudah diperiksa',konfirmasi=True,keberadaan=tempat)
    async with pg() as db:
        if not tempat:
            with pytest.raises(ValueError,match='Pilih keberadaan'):await k.periksa(db,user=user(x),**p)
        else:
            snap=await k.periksa(db,user=user(x),**p);await db.commit()
            await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=snap['dasar'],konfirmasi=True);await db.commit()
            from app.services import riwayat_retur_supplier as h
            d=await h.daftar(db,user(x));assert d['total_keluar']==D('249.5')
            assert next(r['status'] for r in d['rows'] if r['rec'].id==x['rid'])=='cancel_after'
        assert (await hitung_stok_finished_goods(db,x['sku'],None))['kg']==1247.5


async def test_izin_efektif_operator_tidak_dapat_koreksi_batal_manual(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        for jenis in ('jumlah','keterangan','batal'):
            with pytest.raises(PermissionError):await k.periksa(db,user=user(x,ROLE.OPERATOR),**dict(payload(x),jenis=jenis))
        g1=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        with pytest.raises(PermissionError):await k.data(db,x['rid'],user(x,ROLE.OPERATOR,wh=g1))


async def test_bangun_ulang_proyeksi_dan_baca_readonly(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        await terapkan(db,x,payload(x))
        from app.services.peristiwa import bangun_ulang
        await bangun_ulang(db)
        assert (await hitung_stok_finished_goods(db,x['sku'],None))['kg']==1247.5
        assert (await db.get(E,x['rid'])).versi==1
        await db.rollback();await db.execute(text('SET TRANSACTION READ ONLY'))
        assert (await k.data(db,x['rid'],user(x)))['versi']==1


async def test_kontrak_baca_tetap_memiliki_snapshot_awal_dan_opsional_efektif(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        await terapkan(db,x,payload(x))
        from app.services.retur_supplier_detail import kontrak
        d=await kontrak(db,x['tid_out'],user(x))
        assert d['penyelesaian']['total_kg']=='249.5' and d['pencatatan_efektif']['versi']==1
        assert [D(v['jumlah']) for v in d['pencatatan_efektif']['items']]==[4,1]


@pytest.mark.parametrize('mode',['partial','full','draft','duplicate','foreign','over','wrong_composition'])
async def test_kontrak_baca_penerimaan_per_item_tanpa_dokumen_ganda(pg,keluar_dua,mode):
    x=keluar_dua
    from app.services import retur_supplier_kembali as b
    async with pg() as db:
        rec,items,_,_,ef,_=await k.konteks(db,x['rid'],user(x))
        rows=[dict(status='diterima',retur_supplier_id=rec.id,item_id=items[0].id,pemilik_id=None,warehouse_id=items[0].warehouse_id,mutasi_id='uji-masuk-1',bobot_kg='49.9')]
        if mode=='full':rows=[dict(rows[0],item_id=i.id,mutasi_id='uji-'+str(i.id),bobot_kg=str(ef[i.id]['bobot_kg'])) for i in items]
        if mode=='draft':rows[0]['status']='draft'
        if mode=='duplicate':rows.append(rows[0].copy())
        if mode=='foreign':rows[0]['item_id']=999999
        if mode in ('over','wrong_composition'):rows[0]['bobot_kg']='249.5'
        if mode in ('duplicate','foreign','over','wrong_composition'):
            with pytest.raises(ValueError):b.rekap(rec,items,ef,rows)
        else:
            got=b.rekap(rec,items,ef,rows)
            assert got['lengkap']==(mode=='full')
            assert got['jumlah'][items[0].id]==(D(0) if mode=='draft' else ef[items[0].id]['bobot_kg'] if mode=='full' else D('49.9'))


@pytest.mark.parametrize('jenis',['jumlah','keterangan','batal'])
async def test_http_form_simpan_hasil_dan_baca_tidak_memutasi(pg,keluar_dua,monkeypatch,jenis):
    import httpx
    from app.web import retur_supplier_koreksi as web,riwayat_retur_supplier as hist
    from tests.pg.test_retur_supplier import api_uji
    x=keluar_dua
    monkeypatch.setattr(web,'SessionLocal',pg);monkeypatch.setattr(hist,'SessionLocal',pg)
    app=api_uji(pg,x);app.include_router(web.router);app.include_router(hist.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        page=await c.get(f'/retur-supplier/{x["rid"]}/tindakan?jenis={jenis}')
        assert page.status_code==200,page.text
        assert 'name="alasan"' in page.text and 'name="konfirmasi"' in page.text
        p=payload(x) if jenis=='jumlah' else dict(identitas=x['rid'],kunci=uuid4().hex,jenis=jenis,alasan='Pemeriksaan barang dan dokumen',konfirmasi=True,**({'keterangan':'Keterangan benar'} if jenis=='keterangan' else {'keberadaan':'kembali'}))
        p.pop('identitas')
        r=await c.post(f'/retur-supplier/{x["rid"]}/tindakan/periksa',json=p);assert r.status_code==200,r.text
        snap=r.json();r=await c.post(f'/retur-supplier/{x["rid"]}/tindakan/simpan',json=dict(kunci=p['kunci'],dasar=snap['dasar'],konfirmasi=True));assert r.status_code==200,r.text
        location=r.json()['alamat']
        async with pg() as db:
            before=await sidik_stok(db);versions=await db.scalar(select(func.count()).select_from(P))
        for url in [location,f'/riwayat-retur-supplier/{x["rid"]}?tab=ringkasan',f'/riwayat-retur-supplier/{x["rid"]}?tab=timbang',f'/riwayat-retur-supplier/{x["rid"]}?tab=stok',f'/riwayat-retur-supplier/{x["rid"]}?tab=jejak',f'/retur-supplier/{x["rid"]}/tindakan/status?kunci={p["kunci"]}']:
            r=await c.get(url);assert r.status_code==200,r.text
        assert r.json()['ditemukan']
        async with pg() as db:
            assert await sidik_stok(db)==before and await db.scalar(select(func.count()).select_from(P))==versions
        assert (await c.get(f'/retur-supplier/{x["rid"]}/tindakan/hasil/2147483647')).status_code==404


@pytest.mark.parametrize('portal',[False,True])
async def test_http_tindakan_tolak_role_efektif_dan_portal(pg,keluar_dua,monkeypatch,portal):
    import httpx
    from app.web import retur_supplier_koreksi as web
    from tests.pg.test_retur_supplier import api_uji
    x=keluar_dua;monkeypatch.setattr(web,'SessionLocal',pg)
    app=api_uji(pg,x,role=ROLE.OPERATOR,portal=portal);app.include_router(web.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        assert (await c.get(f'/retur-supplier/{x["rid"]}/tindakan')).status_code==403
        p=payload(x);p.pop('identitas')
        assert (await c.post(f'/retur-supplier/{x["rid"]}/tindakan/periksa',json=p)).status_code==403
        for action in ['manual','simpan']:
            data=dict(kunci=uuid4().hex,dasar='x',konfirmasi=True)
            if action=='manual':data['catatan']='Catatan'
            assert (await c.post(f'/retur-supplier/{x["rid"]}/tindakan/{action}',json=data)).status_code==403


@pytest.mark.parametrize('jenis',['gabah','pk','broken','curah'])
async def test_koreksi_curah_presisi_dan_tara_nol(pg,asal,jenis):
    from tests.pg.test_retur_supplier import buat_sumber
    async with pg() as db:
        tid,row,key=await buat_sumber(db,asal,jenis)
        req=[dict(kunci=key,jumlah='125.25')]
        c=await s.periksa(db,tid,user(asal),req,'Uji curah','')
        r=await s.simpan(db,user=user(asal),tid=tid,jumlah=req,alasan='Uji curah',catatan='',kunci=uuid4().hex,dasar=c['dasar'])
        t=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await s.hubungkan(db,user=user(asal),identitas=r.id,tiket_id=t)
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5125.25,berat_barang_kg=125.25,status_tiket='SELESAI' WHERE id=:id"),dict(id=t));await db.commit()
        i=await db.scalar(select(I).where(I.retur_supplier_id==r.id))
        c=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='125.25')]);await db.commit()
        await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=c['dasar'],konfirmasi=True);await db.commit()
        p=dict(identitas=r.id,kunci=uuid4().hex,jenis='jumlah',jumlah=[dict(item_id=i.id,jumlah='125.251')],alasan='Pemeriksaan fisik',konfirmasi=True)
        with pytest.raises(ValueError):await k.periksa(db,user=user(asal),**p)
        p['jumlah'][0]['jumlah']='120.25'
        c=await k.periksa(db,user=user(asal),**p);await db.commit()
        assert c['toleransi_kg']=='0' and c['status']=='perlu_koreksi'
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5120.25,berat_barang_kg=120.25,jumlah_revisi=jumlah_revisi+1 WHERE id=:id"),dict(id=t));await db.commit()
        # Kenaikan revisi dan angka cocok tanpa audit koreksi tiket tidak cukup.
        c=await k.periksa(db,user=user(asal),**p);await db.commit();assert c['status']=='perlu_koreksi'
        assert await db.scalar(select(func.count()).select_from(P))==0
        assert c['items'][0]['karung_sesudah'] is None


async def test_dua_draf_beda_kunci_hanya_satu_versi_diterapkan(pg,keluar_dua):
    import asyncio
    x=keluar_dua;draft=[]
    async with pg() as db:
        for _ in range(2):
            p=payload(x);c=await k.periksa(db,user=user(x),**p);await db.commit();draft.append((p,c))
    async def save(p,c):
        async with pg() as db:
            try:
                await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=c['dasar'],konfirmasi=True);await db.commit();return True
            except ValueError:await db.rollback();return False
    assert sorted(await asyncio.gather(*(save(p,c) for p,c in draft)))==[False,True]
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(P))==1


@pytest.mark.parametrize('diff',['0.5','-0.5','0.501','-0.501'])
async def test_toleransi_koreksi_inklusif_dua_arah(pg,keluar_dua,diff):
    x=keluar_dua
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET berat_barang_kg=:kg WHERE id=:id'),dict(kg=D('249.5')+D(diff),id=x['tid_out']));await db.commit()
        c=await k.periksa(db,user=user(x),**payload(x));await db.commit()
        assert D(c['toleransi_kg'])==D('.5')
        assert (c['status']=='terverifikasi_otomatis')==(abs(D(diff))<=D('.5'))


async def test_seluruh_jumlah_nol_ditolak_dan_tara_hilang_tidak_dikira_nol(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        with pytest.raises(ValueError):await k.periksa(db,user=user(x),**payload(x,'0','0'))
        a=await db.get(A,x['items'][0]);a.kemasan_tara_id=None;await db.commit()
        with pytest.raises(ValueError,match='Tara'):await k.periksa(db,user=user(x),**payload(x))


async def test_penerimaan_gagal_dibaca_menahan_dan_relasi_sah_menahan_koreksi(pg,keluar_dua,monkeypatch):
    x=keluar_dua
    from app.services import retur_supplier_kembali as receipts
    async def gagal(*a):raise ValueError('Penerimaan kembali gagal dibaca')
    monkeypatch.setattr(receipts,'baca',gagal)
    async with pg() as db:
        with pytest.raises(ValueError,match='gagal dibaca'):await k.periksa(db,user=user(x),**payload(x))
        async def parsial(db,rec,items,nilai):
            return receipts.rekap(rec,items,nilai,[dict(status='diterima',item_id=items[0].id,retur_supplier_id=rec.id,pemilik_id=None,warehouse_id=items[0].warehouse_id,mutasi_id=99,bobot_kg='49.9')])
        monkeypatch.setattr(receipts,'baca',parsial)
        with pytest.raises(ValueError,match='penerimaan kembali terkait'):await k.periksa(db,user=user(x),**payload(x))
        assert await db.scalar(select(func.count()).select_from(P))==0


async def test_revisi_tiket_berubah_juga_menahan_pembatalan(pg,keluar_dua):
    x=keluar_dua;p=dict(identitas=x['rid'],kunci=uuid4().hex,jenis='batal',keberadaan='di_luar',alasan='Pemeriksaan keberadaan',konfirmasi=True)
    async with pg() as db:
        c=await k.periksa(db,user=user(x),**p);await db.commit()
        await db.execute(text('UPDATE timbangan_transaksi SET jumlah_revisi=jumlah_revisi+1 WHERE id=:id'),dict(id=x['tid_out']));await db.commit()
        with pytest.raises(ValueError,match='berubah'):await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=c['dasar'],konfirmasi=True)
        assert await db.scalar(select(func.count()).select_from(P))==0


@pytest.mark.parametrize('keluar_dua',['pecahan','curah'],indirect=True)
async def test_kg_curah_dan_berat_partai_pecahan_koreksi_beruntun(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        for a,b in [('4','1'),('2','3'),('4','1')]:
            c,_=await terapkan(db,x,payload(x,a,b))
            assert D(c['toleransi_kg'])==(0 if c['items'][0]['satuan']=='kg' else D('.5'))
            _,options=await s.siapkan(db,x['tid'],user(x))
            assert abs(sum(D(i['stok_kg']) for i in options)+D(c['total_baru'])-sum(D(i['diterima_kg']) for i in options))<D('.000001')
        data=await k.data(db,x['rid'],user(x));assert data['versi']==3
        assert [data['efektif'][i]['jumlah'] for i in x['items']]==[4,1]


async def test_kemas_ulang_hilir_menahan_koreksi_jumlah_tanpa_mengubah_stok(pg,keluar_dua):
    from app.models import KemasUlang
    x=keluar_dua
    async with pg() as db:
        db.add(KemasUlang(kunci=uuid4().hex,sidik='uji',sumber_id=x['fid'],sku_asal_id=x['sku'],sku_baru_id=x['sku'],
            karung_dibuka=1,karung_lama_dihitung=1,berat_asal_kg=D('49.9'),karung_baru=1,berat_baru_kg=D('49.9'),sisa_kg=0,petugas_id=x['uid'],waktu=now_local()))
        await db.commit()
        with pytest.raises(ValueError,match='transaksi lanjutan'):await k.periksa(db,user=user(x),**payload(x))
        assert await db.scalar(select(func.count()).select_from(P))==0


async def test_hak_dicabut_setelah_pratinjau_menahan_simpan(pg,keluar_dua):
    x=keluar_dua;p=payload(x)
    async with pg() as db:
        c=await k.periksa(db,user=user(x),**p);await db.commit()
        row=await db.get(User,x['uid']);row.role=ROLE.OPERATOR;row.default_warehouse_id=x['wh'];await db.commit()
        with pytest.raises(PermissionError):await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=c['dasar'],konfirmasi=True)
        assert await db.scalar(select(func.count()).select_from(P))==0


@pytest.mark.parametrize('penuh',[False,True])
async def test_kontrak_penerimaan_parsial_penuh_pembatalan_tanpa_mutasi_kedua(pg,keluar_dua,monkeypatch,penuh):
    # Adapter sintetis menguji konsumsi kontrak saja. Writer penerimaan
    # khusus supplier belum tersedia; bukan uji penerimaan end-to-end.
    from app.services import retur_supplier_kembali as receipts
    x=keluar_dua
    async def baca(db,rec,items,nilai):
        rows=[dict(status='diterima',item_id=i.id,retur_supplier_id=rec.id,pemilik_id=None,warehouse_id=i.warehouse_id,mutasi_id=100+i.id,bobot_kg=nilai[i.id]['bobot_kg'] if penuh else D('49.9')) for i in items]
        return receipts.rekap(rec,items,nilai,rows)
    monkeypatch.setattr(receipts,'baca',baca)
    async with pg() as db:
        before=await sidik_stok(db)
        p=dict(identitas=x['rid'],kunci=uuid4().hex,jenis='batal',keberadaan='kembali',alasan='Pemeriksaan dokumen penerimaan sintetis',konfirmasi=True)
        c=await k.periksa(db,user=user(x),**p);await db.commit()
        assert c['status_fisik']==('seluruh_diterima' if penuh else 'sebagian_belum_kembali')
        await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=c['dasar'],konfirmasi=True);await db.commit()
        after=await sidik_stok(db)
        for table in before:
            if table not in ('peristiwa',):assert before[table]==after[table]
        assert (await hitung_stok_finished_goods(db,x['sku'],None))['kg']==1247.5


async def test_pk_998_30_memakai_bobot_partai_dan_tara_karung_aktual(pg,asal):
    from app.models import KemasanTara,PackageSize
    from tests.pg.test_retur_supplier import buat_sumber
    async with pg() as db:
        tid,a,key=await buat_sumber(db,asal,'pk',bags=30)
        tara=await db.scalar(select(KemasanTara).join(PackageSize).where(PackageSize.ukuran_kg==50));assert tara
        tara.tara_per_karung_kg=D('.1')
        req=[dict(kunci=key,jumlah='3')]
        c=await s.periksa(db,tid,user(asal),req,'Koreksi partai PK uji','')
        r=await s.simpan(db,user=user(asal),tid=tid,jumlah=req,alasan=c['alasan'],catatan='',kunci=uuid4().hex,dasar=c['dasar'])
        ticket=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await s.hubungkan(db,user=user(asal),identitas=r.id,tiket_id=ticket)
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5099.8,berat_barang_kg=99.8,status_tiket='SELESAI' WHERE id=:id"),dict(id=ticket));await db.commit()
        i=await db.scalar(select(I).where(I.retur_supplier_id==r.id))
        c=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='3',kemasan_tara_id=tara.id)]);await db.commit()
        await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=c['dasar'],konfirmasi=True);await db.commit()
        p=dict(identitas=r.id,kunci=uuid4().hex,jenis='jumlah',jumlah=[dict(item_id=i.id,jumlah='4')],alasan='Kesalahan jumlah PK telah diperiksa',konfirmasi=True)
        c=await k.periksa(db,user=user(asal),**p);await db.commit()
        assert c['status']=='perlu_koreksi' and D(c['toleransi_kg'])==D('.4')
        assert abs(D(c['total_baru'])-D(998)*4/30)<D('.000001')
        assert abs(D(c['items'][0]['mutasi_kg'])+D(998)/30)<D('.000001')
        _,choices=await s.siapkan(db,tid,user(asal))
        assert choices[0]['stok_kg']==D('898.2') and choices[0]['stok_jumlah']==27


@pytest.mark.parametrize('keluar_dua',['campuran'],indirect=True)
async def test_tara_campuran_mengikuti_kemasan_dan_jumlah_koreksi(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        c,_=await terapkan(db,x,payload(x))
        assert [D(i['tara_per_karung_kg']) for i in c['items']]==[D('.1'),D('.2')]
        assert D(c['toleransi_kg'])==D('.6')

async def test_http_pembaca_melihat_koreksi_dan_pembatalan_terkunci(pg,keluar_dua,monkeypatch):
    import httpx
    from bs4 import BeautifulSoup
    from app.web import riwayat_retur_supplier as hist,retur_supplier_koreksi as web
    from tests.pg.test_retur_supplier import api_uji
    x=keluar_dua;monkeypatch.setattr(hist,'SessionLocal',pg);monkeypatch.setattr(web,'SessionLocal',pg)
    app=api_uji(pg,x,role=ROLE.OPERATOR);app.include_router(hist.router);app.include_router(web.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        page=await c.get(f'/riwayat-retur-supplier/{x["rid"]}');assert page.status_code==200
        soup=BeautifulSoup(page.text,'html.parser')
        for label in ('Koreksi pencatatan','Pembatalan setelah keluar'):
            button=next((b for b in soup.select('button') if b.get_text(strip=True)==label),None)
            assert button is not None and button.has_attr('disabled')
        assert (await c.get(f'/retur-supplier/{x["rid"]}/tindakan?jenis=jumlah')).status_code==403
