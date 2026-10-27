"""Matriks peran asli/efektif: database sintetis, endpoint asli, tanpa lifespans."""
import json
import pytest,httpx
from fastapi import FastAPI
from sqlalchemy import select
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from app.models import User,Warehouse
from app.web import internal
from tests.pg.test_retur_pengajuan import asal as retur_asal
from tests.pg.test_retur_supplier import asal as supplier_asal,siap_keluar
from tests.pg.test_masuk_detail_timbang import contoh as masuk_asal,catat
from tests.pg.test_tiket_antrean_produksi import _klien,pabrik
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

async def identitas(pg,uid,role,gudang='g2'):
 async with pg() as db:
  u=await db.get(User,uid);u.role=role
  u.default_warehouse_id=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==gudang))
  a=await db.scalar(select(Akun).where(Akun.user_id==uid))
  if not a:a=Akun(user_id=uid,username='uji-mode-'+str(uid),password_hash='sintetis',status='aktif');db.add(a)
  await db.commit();return a.id

async def baca(pg,monkeypatch,path,aid,view,expected,uid,role):
 monkeypatch.setattr(internal.settings,'internal_api_token','uji-mode-lokal')
 app=FastAPI();app.include_router(internal.router)
 h={'X-Internal-Token':'uji-mode-lokal','X-Operator-Akun':str(aid)}
 if view:h['X-Produksi-Lihat']=view
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  r=await c.get(path,headers=h)
 assert r.status_code==expected,(role,view,expected,r.status_code)
 if expected==200:
  assert r.headers['cache-control']=='private, no-store'
  assert not any(k in r.text.lower() for k in ('hpp','harga','nilai_uang'))
 async with pg() as db:assert (await db.get(User,uid)).role==role

@pytest.mark.parametrize('role,view,expected',[(P.SUPERADMIN,None,200),(P.SUPERADMIN,'admin',200),(P.SUPERADMIN,'operator:g1',403),(P.SUPERADMIN,'operator:g2',403),(P.ADMIN,'operator:g2',403),(P.OPERATOR,'superadmin',403)])
async def test_retur_pelanggan_role_efektif(pg,retur_asal,monkeypatch,role,view,expected):
 aid=await identitas(pg,retur_asal['uid'],role)
 await baca(pg,monkeypatch,f'/internal/retur/tiket/{retur_asal["tiket"][0]}/detail',aid,view,expected,retur_asal['uid'],role)

CASES=[(P.SUPERADMIN,None,'g2',200),(P.SUPERADMIN,'admin','g2',200),(P.SUPERADMIN,'operator:g1','g2',403),(P.SUPERADMIN,'operator:g2','g1',200),(P.ADMIN,'operator:g1','g2',403),(P.OPERATOR,'superadmin','g1',403),(P.OPERATOR,'admin','g1',403),(P.OPERATOR,'operator:g2','g1',200)]
@pytest.mark.parametrize('role,view,gudang,expected',CASES)
async def test_supplier_role_efektif(pg,supplier_asal,monkeypatch,role,view,gudang,expected):
 async with pg() as db:r,i,tid=await siap_keluar(db,supplier_asal)
 aid=await identitas(pg,supplier_asal['uid'],role,gudang)
 await baca(pg,monkeypatch,f'/internal/retur-supplier/tiket/{tid}/detail',aid,view,expected,supplier_asal['uid'],role)

@pytest.mark.parametrize('role,view,gudang,expected',CASES)
async def test_masuk_role_efektif(pg,masuk_asal,monkeypatch,role,view,gudang,expected):
 async with pg() as db:await catat(db,masuk_asal,jenis='BERAS_MASUK');await db.commit()
 aid=await identitas(pg,masuk_asal['uid'],role,gudang)
 await baca(pg,monkeypatch,f'/internal/masuk/tiket/{masuk_asal["tid"]}/detail',aid,view,expected,masuk_asal['uid'],role)

@pytest.mark.parametrize('role,view,admin',[(P.SUPERADMIN,'admin',True),(P.SUPERADMIN,'operator:g1',False),(P.SUPERADMIN,'operator:g2',False),(P.OPERATOR,'superadmin',False)])
async def test_ui_http_mode_lihat_bukan_hak_tambahan(pg,pabrik,role,view,admin):
 async with await _klien(pg,role=role,gudang_id=pabrik['g1']) as c:
  c.cookies.set('produksi_lihat',view)
  page=await c.get('/pengaturan');assert page.status_code==200
  assert 'KLEDO_API_KEY' not in page.text
  assert (await c.get('/audit')).status_code==(200 if admin else 403)
  assert (await c.get('/pengguna')).status_code==403
  if not admin:
   menu=(await c.get('/api/actions/menu')).json()
   assert all(not a['boleh'] for a in menu if a['akses'] in ('admin','super'))
   r=await c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':999999},headers={'X-CSRF-Token':cap_formulir(c)})
   assert r.status_code==403
