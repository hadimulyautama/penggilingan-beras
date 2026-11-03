"""Contextual UI uses the existing authorized, read-only correction contract."""
import os,json
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.models import User,ProduksiAkun,Peristiwa
from app.services import koreksi_bahan_berjalan as koreksi
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_form_hasil_penggilingan import hasil,g1
from tests.pg.test_riwayat_giling import _klien
pytestmark=pytest.mark.asyncio

async def check(pg,kind,code,warehouse):
    async with await _klien(pg,peran='operator',gudang=warehouse) as client:
        async with pg() as db:
            acct=await db.scalar(select(ProduksiAkun).order_by(ProduksiAkun.id.desc()).limit(1))
            user=await db.get(User,acct.user_id)
            before=await koreksi.konteks(db,jenis=kind,kode=code,user=user)
            count=await db.scalar(select(func.count()).select_from(Peristiwa))
        page=await client.get(f'/proses-aktif/{kind}/{code}')
        assert page.status_code==200,page.text
        assert 'Perbaiki bahan &amp; hasil' not in page.text
        assert 'Perbaiki bahan & hasil' not in page.text
        assert page.text.index('/static/koreksi-bahan-berjalan.js')<page.text.index('/static/koreksi-di-detail.js')<page.text.index(f'/static/{kind}-ringkas.js')
        api=await client.get(f'/api/actions/koreksi-bahan/{kind}/{code}')
        assert api.status_code==200 and api.headers['cache-control']=='no-store'
        assert api.json()['dasar']==before['dasar']
        async with pg() as db:
            user=await db.get(User,user.id)
            after=await koreksi.konteks(db,jenis=kind,kode=code,user=user)
            assert after['dasar']==before['dasar']
            assert await db.scalar(select(func.count()).select_from(Peristiwa))==count
        if os.environ.get('UJI_DETAIL_VISUAL')=='1':
            Path('../visual-detail-giling.json').write_text(json.dumps(dict(username=acct.username,password='rahasia123',kode=code)))

async def test_detail_sosoh_operator_memakai_koreksi_lama_tanpa_mutasi(pg,running):
    await check(pg,'sosoh',running[1],'Gudang 2')

async def test_detail_giling_operator_memakai_koreksi_lama_tanpa_mutasi(pg,hasil):
    await check(pg,'giling',hasil[1].kode_proses,'Gudang 1')
