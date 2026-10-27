"""Kontrak baca retur: DB uji terpisah, izin akun nyata, tanpa penerimaan dari GET."""
import json
from decimal import Decimal
import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import select,func,text
from hmu_identitas.model import Akun
from hmu_identitas import peran as P
from app.models import User,CustomerReturn,FinishedGoodsStock,OutgoingItem,OutgoingRecord
from app.penggilingan.inventory.models import ReturRincian,ReturPemeriksaanLog
from app.services import retur_detail_timbang as detail
from app.web import internal
from tests.pg.test_retur_pengajuan import asal,simpan,selesai,terima

@pytest.mark.parametrize('status',['belum','menunggu','diterima','koreksi','manual','berubah','tara-hilang'])
async def test_proyeksi_hasil_tidak_menulis(pg,asal,status):
    tid=asal['tiket'][0]
    if status!='belum':
        r=await simpan(pg,asal,10)
        if status not in ('menunggu',):
            await selesai(pg,asal,300 if status in ('koreksi','manual') else 250)
            if status=='tara-hilang':
                await pg_hapus_tara(pg)
            if status!='berubah':await terima(pg,r.id)
        if status=='manual':
            await selesai(pg,asal,250)
            async with pg() as db:
                # Identitas koreksi nyata dicatat sebagaimana service timbang.
                await db.execute(text("INSERT INTO timbangan_audit (waktu,akun_id,akun_nama,aksi,entitas,entitas_id,ringkasan) VALUES (NOW(),NULL,'Uji','KOREKSI','transaksi','RTP-UJI-A','Koreksi bobot uji')"))
                await db.commit()
            await terima(pg,r.id)

    async with pg() as db:
        models=[CustomerReturn,FinishedGoodsStock,ReturPemeriksaanLog]
        before=[await db.scalar(select(func.count()).select_from(m)) for m in models]
        for _ in range(3):
            d=await detail.baca(db,tid)
            assert d['tiket_id']==tid
            assert all(k not in json.dumps(d).lower() for k in ('hpp','harga','nilai_uang'))
        assert [await db.scalar(select(func.count()).select_from(m)) for m in models]==before
        if status=='belum':assert d['status']=='belum' and d['muatan']==[]
        if status=='menunggu':assert d['status']=='menunggu_timbang' and d['penerimaan'] is None
        if status=='diterima':
            assert d['status']=='diterima_otomatis'
            assert Decimal(d['penerimaan']['berat_stok_kg'])==250
            assert Decimal(d['pemeriksaan']['toleransi_kg'])==1
        if status=='koreksi':assert d['status']=='perlu_koreksi' and d['penerimaan'] is None
        if status=='manual':assert d['status']=='calon_manual' and d['penerimaan'] is None
        if status=='berubah':assert d['status']=='berubah'
        if status=='tara-hilang':assert d['pemeriksaan']['toleransi_kg'] is None

async def pg_hapus_tara(pg):
    async with pg() as db:
        await db.execute(text('DELETE FROM kemasan_tara'));await db.commit()

@pytest.mark.parametrize('cacat',['pelanggan','item'])
async def test_identitas_lintas_pelanggan_ditolak(pg,asal,cacat):
    r=await simpan(pg,asal,10)
    async with pg() as db:
        if cacat=='pelanggan':
            await db.execute(text('UPDATE timbangan_transaksi SET pelanggan_id=NULL WHERE id=:id'),{'id':asal['tiket'][0]})
        else:
            rr=await db.get(ReturRincian,r.id);rr.muatan=[dict(rr.muatan[0],outgoing_item_id=999999)]
        await db.commit()
        with pytest.raises(ValueError):await detail.baca(db,asal['tiket'][0])

@pytest.mark.parametrize('role,aktif,token,kode',[(P.OPERATOR,True,True,403),(P.ADMIN,True,True,200),(P.SUPERADMIN,True,True,200),(P.ADMIN,False,True,403),(P.ADMIN,True,False,403)])
async def test_endpoint_menjaga_izin_akun(pg,asal,monkeypatch,role,aktif,token,kode):
    async with pg() as db:
        u=await db.get(User,asal['uid']);u.role=role
        a=Akun(user_id=u.id,username='uji-baca-retur',password_hash='hash-uji',status='aktif' if aktif else 'nonaktif')
        db.add(a);await db.commit();aid=a.id
    monkeypatch.setattr(internal.settings,'internal_api_token','token-uji')
    app=FastAPI();app.include_router(internal.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        h={'X-Operator-Akun':str(aid),'X-Internal-Token':'token-uji' if token else 'salah'}
        r=await c.get(f'/internal/retur/tiket/{asal["tiket"][0]}/detail',headers=h)
        assert r.status_code==kode,r.text
        if kode==200:assert r.json()['status']=='belum'
