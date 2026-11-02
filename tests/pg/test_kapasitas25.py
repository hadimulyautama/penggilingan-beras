"""Kesetaraan akses dan batas pembacaan untuk riwayat pelanggan besar."""
import pytest
from sqlalchemy import select
from tests.pg.test_portal_pelanggan import portal,qc,client
from tests.pg.test_beban_besar import semai
from tests.pg.test_portal_transaksi_detail import transaksi
from tests.pg.scope_acuan_beban import load_scope_acuan
from app.web.portal.scope import load_scope
from app.web.portal.security import CustomerReader

pytestmark=pytest.mark.asyncio

async def test_scope_sql_setara_acuan_dengan_riwayat_dua_pemilik(pg,portal):
    await semai(pg,portal,120,selesai_mutu=True)
    for account in portal.accounts:
        reader=CustomerReader(account.id,account.pelanggan_id,'Uji')
        assert await load_scope(reader)==await load_scope_acuan(reader)

async def test_penerimaan_dipilih_sebelum_rincian_dan_cari_tetap_lengkap(pg,portal):
    from app.services import jasa_pelanggan as svc
    from app.web.portal.beranda import penerimaan_diterima
    from app.services.penerimaan_halaman import pilih,detail
    await semai(pg,portal,120,selesai_mutu=True)
    owner=portal.owners[0].id
    reader=CustomerReader(portal.accounts[0].id,owner,'Pemilik Portal A')
    scope=await load_scope(reader)
    async with pg() as db:
        lama=await svc.pelanggan(db,owner,rinci=False)
        wanted={r['kode'] for r in penerimaan_diterima(lama['penerimaan'])}
        seen=[]
        for page in (1,2,3):
            rows,pag,total=await pilih(db,owner,portal=True,scope=scope,nama=reader.nama,pilihan={'halaman':page})
            assert total==len(wanted) and len(rows)<=25
            seen.extend(r['kode'] for r in rows)
        assert len(seen)==len(set(seen)) and set(seen)==wanted
        rows,pag,_=await pilih(db,owner,portal=True,scope=scope,pilihan={'cari':'BG-0000000'})
        assert [r['kode'] for r in rows]==['BG-0000000']
        rows,pag,_=await pilih(db,owner,portal=True,scope=scope,pilihan={'cari':'BG-0000001'})
        assert rows==[] and pag['jumlah']==0
        nieuw=await svc.pelanggan(db,owner,rincian={'tab':'penerimaan'})
        assert nieuw['penerimaan_jumlah']==len(lama['penerimaan']) and len(nieuw['penerimaan'])==25
        cards=await svc.daftar(db)
        card=next(r for r in cards['kartu'] if r['id']==owner)
        assert card['pesanan_jumlah']==len(lama['pesanan'])
        assert card['penerimaan_jumlah']==len(lama['penerimaan'])


async def test_saldo_sql_sama_dengan_pembaca_ledger_asli(pg,portal):
    from app.models import MillingProcess
    from app.penggilingan.gudang1.services.milling import pk_saldo_query,pk_breakdown_banyak,stok_pk_g1_pemilik
    await semai(pg,portal,120,selesai_mutu=True)
    async with pg() as db:
        rows=(await db.execute(pk_saldo_query())).all()
        lama=await pk_breakdown_banyak(db,[r.id for r in rows])
        for r in rows:
            assert r.produced==pytest.approx(lama[r.id].produced)
            assert r.transferred==pytest.approx(lama[r.id].transferred)
            assert r.tersedia==pytest.approx(lama[r.id].tersedia)
        total=await stok_pk_g1_pemilik(db)
        expected=tuple(sum(lama[r.id].tersedia for r in rows if (r.jasa_id is not None)==owner) for owner in (False,True))
        assert total==pytest.approx(expected)


async def test_penerimaan_tiket_tidak_menjumlah_pk_pending_atau_ditolak(pg,portal,transaksi):
    from app.models import PkPurchaseBatch
    from app.database import now_local
    from app.web.portal.masuk import daftar
    from starlette.requests import Request
    async with pg() as db:
        asal=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-QC-DETAIL'))
        expected=asal.berat_total_kg
        from app.models import PurchaseBatch
        db.add(PkPurchaseBatch(kode_batch='PK-UJI-baru',jasa_id=portal.orders[0].id,
            berat_total_kg=999,sumber_berat='manual',status_batch='baru',
            tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=1))
        db.add(PurchaseBatch(kode_batch='GB-UJI-ditolak',jasa_id=portal.orders[0].id,kondisi_gabah='kering',
            berat_total_kg=999,sumber_berat='manual',status_batch='ditolak',
            tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=1,
            timbangan_transaksi_id=transaksi['masuk']['BERAS_PK']))
        await db.commit()
    scope=await load_scope(CustomerReader(portal.accounts[0].id,portal.owners[0].id,'Pemilik Portal A'))
    async with pg() as db:
        data=await daftar(db,scope,[],Request({'type':'http','query_string':b''}))
        assert data['jenis']=='' and 'jenis=' not in data['href'](halaman=2)
        row=next(r for r in data['riwayat'] if r['kode']=='TB-DETAIL-BERAS_PK')
        assert all(r['kode']!='PK-UJI-baru' for r in data['riwayat'])
        assert float(row['berat_diterima'])==float(expected)
        assert all(c['status'] not in ('baru','ditolak') for c in row['catatan'])


async def test_sumber_berkelompok_sama_dengan_pembaca_asli(pg,portal):
    import copy
    from app.services import jasa_pelanggan as svc
    await semai(pg,portal,120,selesai_mutu=True)
    async with pg() as db:
        d=await svc.pelanggan(db,portal.owners[0].id,rinci=False)
        rows=[]
        for kind in ('pengeringan','giling','transfer','sosoh'):
            rows.extend([r for r in d['proses'] if r['jenis']==kind][:3])
        from app.models import Jasa
        ids=set((await db.scalars(select(Jasa.id).where(Jasa.pelanggan_id==portal.owners[0].id))).all())
        old=copy.deepcopy(rows);new=copy.deepcopy(rows)
        for r in old:await svc._sumber_proses(db,r,ids)
        await svc._sumber_proses_banyak(db,new,ids)
        assert old==new


async def test_scope_bersama_tetap_mencabut_akses_setelah_commit_lain(pg,portal):
    from app.models import MillingProcess
    from app.performa import lupakan_cache
    reader=CustomerReader(portal.accounts[0].id,portal.owners[0].id,'Pemilik Portal A')
    lupakan_cache()
    first=await load_scope(reader)
    ident=portal.process[0]['giling']
    assert ident in first.ids(MillingProcess)
    # Pembacaan kembali boleh dibagi bila WAL belum berubah.
    same=await load_scope(reader)
    assert same==first
    from sqlalchemy import update
    # Commit Core meniru aplikasi lain: tidak memanggil invalidasi cache ORM
    # proses ini atau menulis marker lokal.
    async with pg.kw['bind'].begin() as conn:
        await conn.execute(update(MillingProcess).where(MillingProcess.id==ident).values(jasa_id=portal.orders[1].id))
    last=await load_scope(reader)
    assert ident not in last.ids(MillingProcess)
