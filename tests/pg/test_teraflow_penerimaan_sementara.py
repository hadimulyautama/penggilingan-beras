"""Timbang sementara asli → penerimaan → silo → bobot final, tanpa stok ganda."""
import re,os
import pytest,httpx
from sqlalchemy import text,select,func
from app.models import User,PkPurchaseBatch,PkGudang2Intake,PkTumpukanToSilo
from hmu_identitas.model import Akun
from hmu_identitas.sandi import hash_sandi
from app.penggilingan.gudang2 import service as g2
from app.penggilingan.gudang1.services.timbang_link import sinkron_perkiraan,sinkron_bobot_menunggu
from tests.pg.test_masuk_detail_timbang import contoh
from tests.pg.test_teraflow_kiriman import _skema_head,servers

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi]

@pytest.mark.parametrize('nota',[0,10000])
async def test_http_timbang_sementara_diterima_masuk_silo_lalu_final_tanpa_duplikasi(pg,contoh,nota):
    x=contoh
    async with pg() as db:
        a=await db.get(Akun,x['aid']);a.username='penerimaan_lintas';a.password_hash=hash_sandi('uji-lintas-aman')
        await db.execute(text('UPDATE suppliers SET kledo_contact_id=900001 WHERE id=:id'),dict(id=x['sid']))
        await db.execute(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('penerimaan_lintas','Penerima lintas uji','ADMIN',:aid,'aktif','PL',1)"),dict(aid=a.id));await db.commit()
    with servers(os.environ['UJI_PG_URL']) as (tf,pf):
        async with httpx.AsyncClient(base_url=tf,timeout=30,follow_redirects=False) as c:
            r=await c.post('/timbangan/masuk',data=dict(username='penerimaan_lintas',sandi='uji-lintas-aman',perangkat='PL'));assert r.status_code==303,r.text
            form=await c.get('/timbangan/timbang/BERAS_PK');assert form.status_code==200,form.text
            key=re.search(r'name="kunci" value="([^"]+)"',form.text).group(1)
            r=await c.post('/timbangan/timbang/BERAS_PK',data=dict(kunci=key,berat_kg=15000,supplier_id=x['sid'],nomor_polisi='B 12 PK',nama_sopir='Sopir lintas uji',jumlah_karung=125,berat_acuan_kg=nota))
            assert r.status_code==303 and 'err=' not in r.headers['location'],r.headers.get('location')
            async with pg() as db:tid=await db.scalar(text("SELECT id FROM timbangan_transaksi WHERE jenis_kode='BERAS_PK'"))
            r=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':5250,'aksi':'sementara'})
            assert r.status_code==303 and 'err=' not in r.headers['location'],r.headers.get('location')
            async with pg() as db:
                b=(await g2.create_pk_purchase_dari_timbang(db,user=await db.get(User,x['uid']),timbangan_transaksi_id=tid,jenis_pk='ks',jumlah_karung=125,ukuran_karung_kg=80)).batch
                assert b.berat_total_kg==9750 and b.sumber_berat=='perkiraan'
                it=(await g2.masukkan_pk_luar(db,user=await db.get(User,x['uid']),kode=b.kode_batch)).intake
                await g2.pindah_tumpukan_ke_silo(db,user=await db.get(User,x['uid']),intake_id=it.id,nama_silo='B',jumlah_karung=125)
                silo=await g2.get_g2_silo(db,'B');sid,bid,iid=silo.id,b.id,it.id
                assert await g2.hitung_stok_silo(db,sid)==9750 and not it.bobot_final
            r=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':5250,'jumlah_karung':125,'aksi':'selesai'})
            assert r.status_code==303 and 'err=' not in r.headers['location'],r.headers.get('location')
    async with pg() as db:
        real=await db.scalar(text('SELECT berat_barang_kg FROM timbangan_transaksi WHERE id=:id'),dict(id=tid))
        assert real>0
        await sinkron_perkiraan(db);await sinkron_bobot_menunggu(db);await g2.resinkron_intake_g2(db)
        b=await db.get(PkPurchaseBatch,bid);it=await db.get(PkGudang2Intake,iid)
        assert b.berat_total_kg==real and b.sumber_berat=='timbangan' and it.bobot_final
        assert await g2.hitung_stok_silo(db,sid)==float(real)
        assert await g2._sisa_tumpukan_intake(db,iid)==0
        for m in (PkPurchaseBatch,PkGudang2Intake,PkTumpukanToSilo):assert await db.scalar(select(func.count()).select_from(m))==1
