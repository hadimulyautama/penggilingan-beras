"""Pembaca tiket harus membawa timbang kedua sementara ke penerimaan PK."""
from decimal import Decimal
import pytest
from sqlalchemy import text,select
from app.models import User,PkPurchaseBatch
from app.penggilingan.gudang2 import service as g2
from app.penggilingan.gudang1.services.timbang_link import ambil_tiket,tiket_masuk_aktif
from tests.pg.test_masuk_detail_timbang import contoh

@pytest.mark.parametrize('nota',[0,10000])
async def test_pk_diterima_setelah_simpan_sementara_memakai_bobot_terkini(pg,contoh,nota):
    x=contoh
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET jenis_kode='BERAS_PK',berat_acuan_kg=:nota,timbang2_kg=5250,timbang2_waktu=NOW() WHERE id=:id"),dict(nota=nota,id=x['tid']));await db.commit()
        t=await ambil_tiket(db,x['tid'])
        assert t.get('timbang2_kg')==5250 and t.get('cara_timbang')=='DUA_KALI'
        pilihan=next(t for t in await tiket_masuk_aktif(db) if t['id']==x['tid'])
        assert pilihan.get('timbang2_kg')==5250
        u=await db.get(User,x['uid'])
        b=(await g2.create_pk_purchase_dari_timbang(db,user=u,timbangan_transaksi_id=x['tid'],jenis_pk='ks',jumlah_karung=125,ukuran_karung_kg=80)).batch
        assert b.berat_total_kg==9750 and b.sumber_berat=='perkiraan'

async def test_acuan_surat_jalan_tidak_mengembalikan_nota_setelah_timbang_kedua_sementara(pg,contoh):
    x=contoh
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET jenis_kode='BERAS_PK',berat_acuan_kg=10000,timbang2_kg=5250,timbang2_waktu=NOW() WHERE id=:id"),dict(id=x['tid']));await db.commit()
        b=(await g2.create_pk_purchase_dari_timbang(db,user=await db.get(User,x['uid']),timbangan_transaksi_id=x['tid'],jenis_pk='ks',jumlah_karung=125,ukuran_karung_kg=80)).batch
        b.berat_total_kg=9750;await db.commit()
        acuan=await g2.acuan_karung_surat_jalan(db,b,125)
        assert acuan.berat_total_kg==9750 and acuan.sumber_berat=='perkiraan'

@pytest.mark.parametrize('cara',['PARTAI','SEKALI'])
async def test_timbang_partai_dan_sekali_tidak_ditafsirkan_sebagai_tara_truk(pg,contoh,cara):
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET jenis_kode='BERAS_PK',cara_timbang=:cara,berat_acuan_kg=10000,timbang2_kg=5250 WHERE id=:id"),dict(cara=cara,id=contoh['tid']));await db.commit()
        t=await ambil_tiket(db,contoh['tid'])
        from app.penggilingan.gudang2.karung import bobot_awal_karung
        berat,sumber,_=await bobot_awal_karung(db,t,125,80)
        assert berat==10000 and sumber=='perkiraan'

@pytest.mark.parametrize('jenis',['GABAH_BASAH','GABAH_KERING','BERAS_PK'])
async def test_penerimaan_tanpa_nota_memakai_timbang_kedua_hari_ini_bukan_menunggu_poller(pg,contoh,jenis):
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET jenis_kode=:jenis,berat_acuan_kg=0,timbang2_kg=5250,timbang2_waktu=NOW() WHERE id=:id"),dict(jenis=jenis,id=contoh['tid']));await db.commit()
        t=await ambil_tiket(db,contoh['tid'])
        from app.penggilingan.gudang1.services.timbang_link import bobot_awal_dari_tiket
        assert await bobot_awal_dari_tiket(db,t)==(9750,'perkiraan',None)
        u=await db.get(User,contoh['uid'])
        if jenis=='BERAS_PK':
            batch=(await g2.create_pk_purchase_dari_timbang(db,user=u,timbangan_transaksi_id=contoh['tid'],jenis_pk='ks')).batch
        else:
            from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang
            batch=(await create_purchase_batch_dari_timbang(db,user=u,timbangan_transaksi_id=contoh['tid'],kondisi_gabah='basah' if jenis=='GABAH_BASAH' else 'kering')).batch
        assert batch.berat_total_kg==9750 and batch.sumber_berat=='perkiraan'
