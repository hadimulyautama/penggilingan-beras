"""Toleransi otomatis ±0,2% aktual setelah tara, bukan ambang manual."""
import asyncio
import pytest
from sqlalchemy import text, select, func
from app.models import User, OutgoingRecord, ActivityLog
from app.services import barang_keluar as bk
from tests.pg.test_barang_keluar import gudang, _sampai_dimuat, _tiket, _stok, _perintah

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('aktual,selisih,lulus',[(10000,-20,True),(10000,20,True),(10000,20.01,False),(10000,-20.01,False),(2500,5,True),(2500,5.01,False),(2500,0,True)])
async def test_batas_otomatis_dari_aktual_setelah_tara(pg,gudang,aktual,selisih,lulus):
    rid=await _sampai_dimuat(pg,gudang,karung=aktual//25)
    tid=await _tiket(pg,'TK-OTOMATIS',barang=aktual+selisih)
    stok=await _stok(pg,gudang)
    async with pg() as db:
        if lulus:
            rec,_=await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rid,timbangan_transaksi_id=tid,otomatis=True)
            assert rec.status=='selesai'
            logs=list((await db.scalars(select(ActivityLog).where(ActivityLog.record_id==rid,ActivityLog.alasan_perubahan.like('Verifikasi otomatis:%')))).all())
            assert len(logs)==1
        else:
            with pytest.raises(bk.VerifikasiOtomatisDitahan):
                await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rid,timbangan_transaksi_id=tid,otomatis=True)
    async with pg() as db:
        rec=await db.get(OutgoingRecord,rid)
        assert rec.status==('selesai' if lulus else 'dimuat')
        if not lulus: assert rec.timbangan_transaksi_id is None
    assert await _stok(pg,gudang)==stok

@pytest.mark.parametrize('kolom',['berat_barang_kg','total_tara_kg','timbang2_kg'])
async def test_timbang_belum_lengkap_tidak_otomatis(pg,gudang,kolom):
    rid=await _sampai_dimuat(pg,gudang)
    tid=await _tiket(pg,'TK-BELUM',barang=2500)
    async with pg() as db:
        nilai = '-1' if kolom=='total_tara_kg' else 'NULL'
        await db.execute(text(f'UPDATE timbangan_transaksi SET {kolom}={nilai} WHERE id=:id'),{'id':tid});await db.commit()
        with pytest.raises(bk.BarangKeluarError):await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rid,timbangan_transaksi_id=tid,otomatis=True)
    async with pg() as db:assert (await db.get(OutgoingRecord,rid)).status=='dimuat'

async def test_perintah_belum_dimuat_tidak_otomatis(pg,gudang):
    rec=(await _perintah(pg,gudang)).rec
    tid=await _tiket(pg,'TK-AWAL',barang=2500)
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError):await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rec.id,timbangan_transaksi_id=tid,otomatis=True)
    assert await _stok(pg,gudang)==10000

async def test_callback_timbang_idempoten_dan_selisih_ditahan(pg,gudang,monkeypatch):
    from app.web import internal
    from hmu_identitas.model import Akun
    monkeypatch.setattr(internal.settings,'internal_api_token','uji-otomatis')
    rid=await _sampai_dimuat(pg,gudang)
    tid=await _tiket(pg,'TK-CALLBACK',barang=2505)
    async with pg() as db:
        akun=Akun(user_id=gudang['op'],username='operator-timbang-uji',password_hash='tidak-dipakai',status='aktif')
        db.add(akun);await db.commit();aid=akun.id
    a,b=await asyncio.gather(internal.verifikasi_pengiriman_tiket(tid,aid,'uji-otomatis'),internal.verifikasi_pengiriman_tiket(tid,aid,'uji-otomatis'),return_exceptions=True)
    assert not isinstance(a,Exception), str(a)
    assert not isinstance(b,Exception), str(b)
    assert a["selesai"] and b["selesai"]
    # Callback berikutnya harus aman diulang.
    ulang=await internal.verifikasi_pengiriman_tiket(tid,aid,'uji-otomatis');assert ulang['selesai']
    async with pg() as db:
        rec=await db.get(OutgoingRecord,rid);assert rec.status=='selesai';assert rec.diverifikasi_oleh==gudang['op']
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.record_id==rid,ActivityLog.alasan_perubahan.like('Verifikasi otomatis:%')))==1
    assert await _stok(pg,gudang)==7500
