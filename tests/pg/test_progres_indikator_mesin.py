"""Progres memakai indikator terbaru, tidak berganti sumber karena log alat tes."""
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.database import now_local
from app.models import DryingMoistureLog,User
from app.penggilingan.gudang1.services import drying as dr
from app.services import berjalan,dashboard
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik
from tests.pg.test_riwayat_pengeringan import pabrik
pytestmark=pytest.mark.asyncio

async def isi(pg,w,rows):
 async with pg() as db:
  old=list((await db.scalars(select(DryingMoistureLog))).all())
  for r in old:await db.delete(r)
  for i,(mesin,tes) in enumerate(rows):db.add(DryingMoistureLog(drying_lot_id=w['id'],kadar_air_indikator=mesin,kadar_air_tes_manual=tes,waktu_update=now_local()-timedelta(minutes=20-i),input_by=w['user']))
  await db.commit()
async def snapshot(pg):
 async with pg() as db:return [tuple(getattr(r,c.name) for c in r.__table__.columns) for r in (await db.scalars(select(DryingMoistureLog).order_by(DryingMoistureLog.id))).all()]
@pytest.mark.parametrize('rows,latest',[([(20,20),(16,13),(None,11)],16), ([(20,20),(13,18)],13), ([(20,20),(24,11)],24), ([(None,20),(None,12)],None), ([(20,20),(0,17),(None,12)],0), ([],None)])
async def test_progres_beranda_dashboard_sama_sumber_tanpa_mengubah_log(pg,pengeringan,rows,latest):
 await isi(pg,pengeringan,rows);before=await snapshot(pg)
 async with pg() as db:
  assert await dr.indikator_mesin_terakhir(db,pengeringan['id'])==latest
  u=await db.get(User,pengeringan['user']);cards=(await berjalan.untuk(db,u)).berjalan
  card=next(x for x in cards if x.kode==pengeringan['kode']);data=next(x for x in await dashboard._pengeringan_berjalan(db,now_local()) if x['kode']==pengeringan['kode'])
  expected=dr.kemajuan(await dr.kadar_air_awal(db,pengeringan['id']),latest,data['target'])
  assert card.maju==data['maju']==expected
  assert data['indikator_progres']==latest
  if latest is None:assert card.maju is None
 assert await snapshot(pg)==before

async def test_indikator_urut_waktu_lalu_id_bukan_urutan_insert(pg,pengeringan):
 await isi(pg,pengeringan,[(20,20),(17,15),(16,13)])
 async with pg() as db:
  logs=(await db.scalars(select(DryingMoistureLog).order_by(DryingMoistureLog.id))).all()
  logs[1].waktu_update=logs[2].waktu_update+timedelta(minutes=10)
  await db.commit()
  assert await dr.indikator_mesin_terakhir(db,pengeringan['id'])==17
  assert await dr.indikator_mesin_terakhir(db,999999) is None
  logs[2].waktu_update=logs[1].waktu_update;await db.commit()
  assert await dr.indikator_mesin_terakhir(db,pengeringan['id'])==16
