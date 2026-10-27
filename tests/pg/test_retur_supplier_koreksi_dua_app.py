"""Koreksi pasca-keluar dengan formulir/audit tiket TeraFlow yang sebenarnya.

Opt-in lokal yang sama dengan uji dua aplikasi lama; tidak memicu CI.
"""
import re,json
from decimal import Decimal as D
import pytest,httpx
from sqlalchemy import select,text,func
from app.models import User,ProduksiAkun
from app.web.security import hash_sandi
from app.services import retur_supplier_koreksi as k
from app.models.retur_supplier_koreksi import ReturSupplierPerubahan as P
from tests.pg.test_retur_supplier_dua_app import _skema_head,servers
from tests.pg.test_retur_supplier_koreksi import keluar_dua,payload
from tests.pg.test_retur_supplier import asal,user

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi]


async def test_koreksi_tiket_resmi_buka_manual_tanpa_menimpa_keluar_awal(pg,keluar_dua):
    x=keluar_dua
    async with pg() as db:
        u=await db.get(User,x['uid']);u.default_warehouse_id=x['wh']
        a=ProduksiAkun(user_id=u.id,username='uji_rsp',password_hash=hash_sandi('uji-rsp-lokal'));db.add(a);await db.flush()
        await db.execute(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('uji_rsp','Admin Koreksi Uji','ADMIN',:aid,'aktif','US',1)"),dict(aid=a.id));await db.commit()
        p=payload(x,'4','2');c=await k.periksa(db,user=user(x),**p);await db.commit();assert c['status']=='perlu_koreksi'
        ledger=(await db.execute(text('SELECT snapshot FROM retur_supplier_keluar'))).scalar_one()
    with servers() as (tf,pf):
        async with httpx.AsyncClient(base_url=tf,timeout=30,follow_redirects=False) as client:
            r=await client.post('/timbangan/masuk',data={'username':'uji_rsp','sandi':'uji-rsp-lokal','perangkat':'US'});assert r.status_code==303
            r=await client.get(f'/timbangan/transaksi/{x["tid_out"]}/koreksi');assert r.status_code==200,r.text
            version=re.search(r'name="versi" value="([^"]+)"',r.text).group(1)
            r=await client.post(f'/timbangan/transaksi/{x["tid_out"]}/koreksi',data=dict(versi=version,asli_timbang2_kg='5249.5',timbang2_kg='5299.4',alasan='Pemeriksaan fisik membuktikan bacaan timbang keliru pada data sintetis'))
            assert r.status_code==303 and 'err=' not in r.headers['location'],r.headers.get('location')
        async with pg() as db:
            c=await k.periksa(db,user=user(x),**p);await db.commit();assert c['status']=='siap_manual',c
            await k.manual(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=c['dasar'],catatan='Audit koreksi resmi dan komposisi fisik diperiksa',konfirmasi=True);await db.commit()
            await k.simpan(db,user=user(x),identitas=x['rid'],kunci=p['kunci'],dasar=c['dasar'],konfirmasi=True);await db.commit()
            assert await db.scalar(select(func.count()).select_from(P))==1
            assert (await db.execute(text('SELECT snapshot FROM retur_supplier_keluar'))).scalar_one()==ledger
            assert D(ledger['total_kg'])==D('249.5')
            assert (await k.data(db,x['rid'],user(x)))['efektif'][x['items'][0]]['jumlah']==4
            # Reader lama TF tetap menerima payload yang mendapat sibling opsional.
        async with httpx.AsyncClient(base_url=tf,timeout=30) as client:
            await client.post('/timbangan/masuk',data={'username':'uji_rsp','sandi':'uji-rsp-lokal','perangkat':'US'})
            r=await client.get(f'/timbangan/transaksi/{x["tid_out"]}')
            assert r.status_code==200 and 'Selesai di gudang' in r.text
