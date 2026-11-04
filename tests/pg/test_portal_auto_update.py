"""Pembaruan baca portal mengikuti transisi pengeringan tanpa mutasi."""
import os,json
from pathlib import Path
import pytest
from sqlalchemy import select,text
from app.models import Pelanggan,Jasa,DryingLot,PurchaseBatch,User,Silo,Peristiwa,ActivityLog
from app.models.portal import PortalAccount
from app.web import security
from app.penggilingan.gudang1.services import drying
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik
from tests.pg.test_portal_pelanggan import client
pytestmark=pytest.mark.asyncio

async def prepare(pg,data):
    async with pg() as db:
        p=Pelanggan(nama_pelanggan='Pelanggan Uji Pembaruan');db.add(p);await db.flush()
        j=Jasa(kode='JAS-UJI-PEMBARUAN',pelanggan_id=p.id);db.add(j);await db.flush()
        lot=await db.get(DryingLot,data['id']);lot.jasa_id=j.id
        b=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==data['batch']));b.jasa_id=j.id;b.supplier_id=None
        a=PortalAccount(username='uji-pembaruan',pelanggan_id=p.id,password_hash=security.hash_sandi('rahasia123'),active=True,token_version=1);db.add(a);await db.commit();return a

async def fingerprint(pg):
    async with pg() as db:
        out={}
        for model in (DryingLot,PurchaseBatch,Silo,Peristiwa,ActivityLog):
            table=model.__tablename__
            out[table]=await db.scalar(text(f"SELECT md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY id),'')) FROM {table} t"))
        return out

async def test_baca_ulang_status_pengeringan_selesai_tanpa_mutasi(pg,pengeringan):
    data=pengeringan;account=await prepare(pg,data)
    async with client(account) as c:
        before=await c.get('/pelanggan/jasa-saya',headers={'X-Portal-Navigasi':'1'})
        assert before.status_code==200 and 'Sedang dikeringkan' in before.text
        async with pg() as db:
            await drying.finish_drying(db,user=await db.get(User,data['user']),kode_lot=data['kode'],kadar_air_akhir=13)
        snapshot=await fingerprint(pg)
        for url in ('/pelanggan/','/pelanggan/jasa-saya','/pelanggan/barang-saya'):
            r=await c.get(url,headers={'X-Portal-Navigasi':'1'})
            assert r.status_code==200 and 'no-store' in r.headers['cache-control']
            assert 'Sedang dikeringkan' not in r.text
        detail=await c.get('/pelanggan/proses-aktif/pengeringan/'+data['kode'],follow_redirects=True)
        assert detail.status_code==200 and '/pendinginan/' in detail.url.path
        assert await fingerprint(pg)==snapshot
        async with pg() as db:
            await drying.finish_cooling(db,user=await db.get(User,data['user']),kode_lot=data['kode'])
        r=await c.get('/pelanggan/jasa-saya')
        assert 'Sedang dikeringkan' not in r.text
        detail=await c.get('/pelanggan/proses-aktif/pendinginan/'+data['kode'],follow_redirects=True)
        assert '/riwayat-pengeringan/' in detail.url.path and detail.status_code==200

async def test_seed_visual_portal_auto(pg,pengeringan):
    if os.environ.get('UJI_PORTAL_AUTO_VISUAL')!='1':pytest.skip('Seed visual terpisah.')
    account=await prepare(pg,pengeringan)
    Path('../../portal-auto-update-20261104/visual.json').write_text(json.dumps(dict(username=account.username,password='rahasia123',**pengeringan)))
