"""Batas daftar layar tidak boleh membatasi kontrak tiket antaraplikasi."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select,delete
from app.models import OutgoingRecord,OutgoingItem,KemasanTara,User
from app.database import now_local
from app.web import internal
from app.services import barang_keluar as bk
from tests.pg.test_barang_keluar import gudang,_perintah,_tiket,_stok

async def dimuat(pg,g):
    r=await _perintah(pg,g,karung=20)
    async with pg() as db:
        await bk.muat_semua(db,user=await db.get(User,g['op']),rec_id=r.rec.id)
    return r.rec.id

async def pengalih(pg,g):
    async with pg() as db:
        now=now_local()
        db.add_all([OutgoingRecord(kode=f'OUT-PENGALIH-{i:03}',nama_pembeli='Penerima lain',
            no_polisi='D 1 UJ',tanggal=now.date(),waktu=now,input_by=g['adm'],status='selesai') for i in range(501)])
        await db.commit()

@pytest.mark.parametrize('tertaut',[False,True])
async def test_sumber_lama_tetap_terbaca_melewati_500_transaksi(pg,gudang,tertaut):
    rid=await dimuat(pg,gudang);tid=await _tiket(pg,'KLR-LAMA-500')
    if tertaut:
        async with pg() as db:
            r=await db.get(OutgoingRecord,rid);r.timbangan_transaksi_id=tid;await db.commit()
    await pengalih(pg,gudang)
    awal=await _stok(pg,gudang)
    async with pg() as db:
        _,r,items=await internal._cocokkan_pengiriman_tiket(db,tid)
        assert r.id==rid and len(items)==1
    assert await _stok(pg,gudang)==awal

async def test_kecocokan_ganda_di_luar_500_tetap_ditolak(pg,gudang):
    await dimuat(pg,gudang);await pengalih(pg,gudang)
    await dimuat(pg,gudang);tid=await _tiket(pg,'KLR-AMBIGU-500')
    async with pg() as db:
        with pytest.raises(HTTPException) as e:
            await internal._cocokkan_pengiriman_tiket(db,tid)
        assert e.value.status_code==409 and 'lebih dari satu' in str(e.value.detail)

@pytest.mark.parametrize('tipe',['pk_langsung','pk_g2','gabah_langsung'])
async def test_muatan_kg_tanpa_karung_tidak_memerlukan_master_tara(pg,gudang,monkeypatch,tipe):
    tid=await _tiket(pg,'KLR-CURAH',pembeli='Penerima curah',barang=123)
    async with pg() as db:
        now=now_local();rec=OutgoingRecord(kode='OUT-CURAH',nama_pembeli='Penerima curah',
            no_polisi='B 1234 XY',tanggal=now.date(),waktu=now,input_by=gudang['adm'],status='dimuat')
        db.add(rec);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=rec.id,item_type=tipe,berat_kg=123,berat_perintah_kg=123,jumlah_karung=0))
        await db.execute(delete(KemasanTara));await db.commit()
    monkeypatch.setattr(internal.settings,'internal_api_token','uji-curah')
    data=await internal.pengiriman_muatan_tiket(tid,'uji-curah')
    assert len(data['muatan'])==1
    assert data['muatan'][0]['jumlah_karung']==0 and float(data['muatan'][0]['tara_per_karung_kg'])==0
