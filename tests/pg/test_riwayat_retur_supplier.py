"""Riwayat nyata dengan basis data sintetis loopback; tidak ada CI otomatis."""
from datetime import datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace
import pytest
from sqlalchemy import select,text,func
from app.models import User,Warehouse,ActivityLog
from app.models.retur_supplier import ReturSupplier,ReturSupplierItem as Item,ReturSupplierKeluar as Keluar
from app.services import riwayat_retur_supplier as h,retur_supplier_selesai as f
from hmu_identitas import peran as P
from tests.pg.test_retur_supplier import (asal,skema_retur_timbang,buat,user,jumlah,tiket,siap_keluar,sidik_stok,api_uji)

pytestmark=pytest.mark.asyncio


async def sidik_semua(db):
    out=await sidik_stok(db)
    for t in ('retur_supplier','retur_supplier_items','retur_supplier_aktual','retur_supplier_pemeriksaan','retur_supplier_keluar','activity_logs'):
        out[t]=await db.scalar(text(f"SELECT md5(COALESCE(string_agg(row_to_json(x)::text,'' ORDER BY row_to_json(x)::text),'')) FROM {t} x"))
    return out


async def selesai(db,x):
    r,i,tid=await siap_keluar(db,x)
    snap=await f.periksa(db,identitas=r.id,user=user(x),jumlah=[dict(item_id=i.id,jumlah='5')])
    await f.catat_keluar(db,identitas=r.id,user=user(x),dasar=snap['dasar'],konfirmasi=True)
    await db.commit();return r,i,tid


async def test_rekap_seluruh_filter_tidak_ganda_oleh_item_audit_atau_halamaan(pg,asal,monkeypatch):
    async with pg() as db:
        a,i,tid=await selesai(db,asal)
        b,_,_=await selesai(db,asal)
        c=await buat(db,asal,n='1');await db.commit()
        # Banyak audit dan dua pengajuan selesai tidak boleh mengalikan ledger.
        assert await db.scalar(select(func.count()).select_from(ActivityLog))>5
        monkeypatch.setattr(h,'UKURAN_HALAMAN',1)
        d=await h.daftar(db,user(asal));assert d['total']==3 and d['pages']==3
        assert len(d['rows'])==1 and d['total_keluar']==D('499') and d['jumlah_keluar']==2
        d=await h.daftar(db,user(asal),halaman=3);assert len(d['rows'])==1 and d['total_keluar']==D('499')
        d=await h.daftar(db,user(asal),status='ticket');assert d['total']==1 and d['total_keluar']==0
        # Ledger historis tetap berlaku walau label status tak cocok; GET tidak
        # mencoba membalik stok atau menebak pembalikan dari label tersebut.
        a.status='dibatalkan';await db.commit()
        d=await h.daftar(db,user(asal),status='done');assert d['jumlah_keluar']==2 and d['total_keluar']==499


async def test_pencarian_dan_filter_bersama_tanggal_wib(pg,asal):
    async with pg() as db:
        r,_,tid=await siap_keluar(db,asal);r.waktu=datetime(2026,10,26,18,0,tzinfo=timezone.utc)
        r.sumber=dict(r.sumber,nota='NOTA-UJI-PENCARIAN');await db.commit()
        kode_tiket=await db.scalar(text('SELECT kode FROM timbangan_transaksi WHERE id=:id'),{'id':tid})
        for q in [r.kode.lower(),'supplier uji',r.sumber['kode_tiket'],(await db.get(Item,1)).snapshot['kode'],kode_tiket,'B UJI','NOTA-UJI-PENCARIAN']:
            d=await h.daftar(db,user(asal),q=q,awal='2026-10-27',akhir='2026-10-27',supplier=asal['sid'],gudang=asal['wh'],penerimaan=asal['tid'])
            assert d['total']==1
        assert (await h.daftar(db,user(asal),awal='2026-10-26',akhir='2026-10-26'))['total']==0
        assert (await h.daftar(db,user(asal),q='tidak-ada'))['total']==0


@pytest.mark.parametrize('a,b',[('2026-10-28','2026-10-27'),('bukan-tanggal',''),('','2026-02-30')])
async def test_tanggal_tidak_sah_ditolak(pg,asal,a,b):
    async with pg() as db:
        with pytest.raises(ValueError,match='Rentang tanggal'):await h.daftar(db,user(asal),awal=a,akhir=b)


@pytest.mark.parametrize('keadaan',['ticket','weigh','check','correction','manual','ready','done','cancel','stale','blocked','unknown'])
async def test_status_dari_proses_bukan_bobot_saja(pg,asal,keadaan,monkeypatch):
    async with pg() as db:
        if keadaan in ('ticket','cancel'):
            r=await buat(db,asal)
            if keadaan=='cancel':
                from app.services import retur_supplier as s
                await s.batalkan(db,user=user(asal),identitas=r.id,alasan='Tidak jadi')
            await db.commit()
        else:
            r,i,tid=await siap_keluar(db,asal,hasil='260' if keadaan=='correction' else '249.5')
            if keadaan not in ('weigh','check'):
                snap=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')])
                if keadaan=='manual':r.wajib_manual=True;r.verifikasi=None
                if keadaan=='done':await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True)
            if keadaan=='weigh':await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='TERBUKA',timbang2_kg=NULL,berat_barang_kg=NULL WHERE id=:id"),{'id':tid})
            if keadaan=='blocked':await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi='VOID' WHERE id=:id"),{'id':tid})
            if keadaan=='stale':await db.execute(text('UPDATE timbangan_transaksi SET jumlah_revisi=jumlah_revisi+1 WHERE id=:id'),{'id':tid})
            if keadaan=='unknown':
                async def gagal(*a):return {},True
                monkeypatch.setattr(h,'tiket_banyak',gagal)
            await db.commit()
        d=await h.daftar(db,user(asal));assert d['rows'][0]['status']==keadaan
        assert (d['rows'][0]['keluar'] is not None)==(keadaan=='done')


async def test_snapshot_transaksi_bukan_saldo_sekarang_dan_baca_tidak_menulis(pg,asal):
    async with pg() as db:
        r,i,tid=await selesai(db,asal)
        before=await sidik_semua(db)
        for _ in range(2):
            d=await h.detail(db,r.id,user(asal))
            assert D(d['barang'][0]['keluar']['stok_sebelum_kg'])==998
            assert D(d['barang'][0]['keluar']['stok_sesudah_kg'])==D('748.5')
            assert D(d['barang'][0]['keluar']['karung_sesudah'])==15
            assert d['total_pengajuan']==D('249.5') and d['total_aktual']==D('249.5')
            await h.daftar(db,user(asal))
        assert await sidik_semua(db)==before
        ledger=d['ledger'];ledger.snapshot=dict(ledger.snapshot,items=[]);await db.commit()
        d=await h.detail(db,r.id,user(asal));assert d['barang'][0]['keluar'] is None
        assert d['ledger'] is not None  # incomplete historical snapshot, never fabricated


async def test_aktual_belum_dicatat_bukan_nol_dan_batal_tidak_ada_mutasi(pg,asal):
    async with pg() as db:
        r=await buat(db,asal);await db.commit()
        d=await h.detail(db,r.id,user(asal));assert d['total_aktual'] is None and d['snap'] is None and d['ledger'] is None
        assert d['barang'][0]['aktual'] is None
        from app.services import retur_supplier as s
        await s.batalkan(db,user=user(asal),identitas=r.id,alasan='Sumber tetap');await db.commit()
        d=await h.detail(db,r.id,user(asal));assert d['status']=='cancel' and d['ledger'] is None


async def test_akses_daftar_filter_rekap_detail_role_efektif(pg,asal):
    async with pg() as db:
        r=await buat(db,asal);await db.commit()
        g1=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        u=user(asal,P.OPERATOR,wh=g1)
        d=await h.daftar(db,u);assert d['total']==0 and d['suppliers']=={} and d['total_keluar']==0
        with pytest.raises(PermissionError):await h.detail(db,r.id,u)
        with pytest.raises(PermissionError):await h.daftar(db,u,gudang=asal['wh'])
        with pytest.raises(PermissionError):await h.daftar(db,u,supplier=asal['sid'])
        with pytest.raises(PermissionError):await h.daftar(db,u,penerimaan=asal['tid'])
        # Operator tidak dapat menaikkan hak dengan mengganti input role.
        stored=await db.get(User,asal['uid']);stored.role=P.OPERATOR;stored.default_warehouse_id=g1;await db.commit()
        with pytest.raises(PermissionError):await h.detail(db,r.id,user(asal,P.SUPERADMIN,wh=g1))


@pytest.mark.parametrize('tab',['ringkasan','timbang','stok','jejak'])
async def test_http_empat_tab_konteks_aman_dan_tanpa_mutasi(pg,asal,monkeypatch,tab):
    import httpx
    from app.web import riwayat_retur_supplier as web
    async with pg() as db:r,_,_=await selesai(db,asal);before=await sidik_semua(db)
    monkeypatch.setattr(web,'SessionLocal',pg)
    app=api_uji(pg,asal);app.include_router(web.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        resp=await c.get(f'/riwayat-retur-supplier/{r.id}?tab={tab}&q=Uji&halaman=2&penerimaan={asal["tid"]}')
        assert resp.status_code==200,resp.text
        assert 'q=Uji&amp;halaman=2' in resp.text and 'Kembali ke daftar riwayat' in resp.text
        assert all(t in resp.text for t in ['Ringkasan','Timbang &amp; verifikasi','Stok','Jejak &amp; dokumen'])
        assert 'Lanjutkan pemeriksaan' not in resp.text and 'action="/retur-supplier/' not in resp.text
        assert (await c.post(f'/riwayat-retur-supplier/{r.id}')).status_code==405
    async with pg() as db:assert await sidik_semua(db)==before


async def test_http_daftar_filter_kosong_tidak_422_dan_portal_ditolak(pg,asal,monkeypatch):
    import httpx
    from app.web import riwayat_retur_supplier as web
    async with pg() as db:r=await buat(db,asal);await db.commit()
    monkeypatch.setattr(web,'SessionLocal',pg)
    app=api_uji(pg,asal);app.include_router(web.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        resp=await c.get('/riwayat-retur-supplier?q=&awal=&akhir=&supplier=&gudang=');assert resp.status_code==200 and r.kode in resp.text
        resp=await c.get('/riwayat-retur-supplier?awal=2026-10-28&akhir=2026-10-27');assert resp.status_code==200 and 'Rentang tanggal tidak sah' in resp.text and 'value="2026-10-28"' in resp.text
    app=api_uji(pg,asal,portal=True);app.include_router(web.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        for url in ['/riwayat-retur-supplier',f'/riwayat-retur-supplier/{r.id}']:
            assert (await c.get(url)).status_code==403


async def test_gangguan_tiket_mempertahankan_snapshot_dan_pencarian_historis(pg,asal,monkeypatch):
    async with pg() as db:
        r,_,_=await selesai(db,asal)
        d=await h.detail(db,r.id,user(asal));kode=d['snap']['kode_tiket']
        before=await sidik_semua(db)
        async def gagal(*a):return {},True
        monkeypatch.setattr(h,'tiket_banyak',gagal)
        d=await h.detail(db,r.id,user(asal))
        assert d['gagal_tiket'] and d['tiket'] is None and d['snap']['hasil_kg']=='249.5'
        assert d['status']=='done'
        recap=await h.daftar(db,user(asal),q=kode);assert recap['total']==1 and recap['total_keluar']==D('249.5')
        assert await sidik_semua(db)==before


async def test_http_operator_gudang_lain_tidak_bocor_daftar_dan_url_detail(pg,asal,monkeypatch):
    import httpx
    from app.web import riwayat_retur_supplier as web
    async with pg() as db:
        r=await buat(db,asal);await db.commit()
        g1=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
    monkeypatch.setattr(web,'SessionLocal',pg)
    app=api_uji(pg,dict(asal,wh=g1),role=P.OPERATOR);app.include_router(web.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        resp=await c.get('/riwayat-retur-supplier');assert resp.status_code==200
        assert r.kode not in resp.text and 'Supplier Uji Asal' not in resp.text and '0 retur sesuai filter' in resp.text
        assert (await c.get(f'/riwayat-retur-supplier/{r.id}?tab=stok')).status_code==403
        assert (await c.get(f'/riwayat-retur-supplier?gudang={asal["wh"]}')).status_code==403


async def test_http_gagal_baca_tidak_sukses_palsu_dan_filter_tetap(pg,asal,monkeypatch):
    import httpx
    from sqlalchemy.exc import DBAPIError
    from app.web import riwayat_retur_supplier as web
    async def gagal(*a,**kw):raise DBAPIError('SELECT',{},RuntimeError('Gangguan sintetis'))
    monkeypatch.setattr(web,'SessionLocal',pg);monkeypatch.setattr(h,'daftar',gagal)
    app=api_uji(pg,asal);app.include_router(web.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        resp=await c.get('/riwayat-retur-supplier?q=IsianTetap&awal=2026-10-27')
        assert resp.status_code==503 and 'Riwayat belum dapat dimuat' in resp.text and 'value="IsianTetap"' in resp.text
        assert '0 retur sesuai filter' not in resp.text


async def test_layanan_riwayat_berjalan_dalam_transaksi_read_only(pg,asal):
    async with pg() as db:
        r,_,_=await selesai(db,asal)
        await db.execute(text('SET TRANSACTION READ ONLY'))
        assert (await h.daftar(db,user(asal)))['total_keluar']==D('249.5')
        assert (await h.detail(db,r.id,user(asal)))['status']=='done'


async def test_gudang_nonaktif_historis_admin_tetap_terbaca_operator_ditolak(pg,asal):
    async with pg() as db:
        r=await buat(db,asal);await db.commit()
        wh=await db.get(Warehouse,asal['wh']);wh.aktif=False;await db.commit()
        assert (await h.daftar(db,user(asal)))['total']==1
        assert (await h.detail(db,r.id,user(asal)))['rec'].id==r.id
        with pytest.raises(PermissionError):await h.daftar(db,user(asal,P.OPERATOR))


async def test_snapshot_total_hilang_tidak_mengaku_rekap_nol(pg,asal,monkeypatch):
    import httpx
    from app.web import riwayat_retur_supplier as web
    async with pg() as db:
        r,_,_=await selesai(db,asal)
        k=await db.scalar(select(Keluar));snap=dict(k.snapshot);snap.pop('total_kg');k.snapshot=snap;await db.commit()
    monkeypatch.setattr(web,'SessionLocal',pg)
    app=api_uji(pg,asal);app.include_router(web.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        resp=await c.get('/riwayat-retur-supplier')
        assert resp.status_code==200 and 'Total keluar belum dapat dipastikan' in resp.text
        assert 'Barang keluar tercatat: <strong>0' not in resp.text
