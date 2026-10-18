"""Regresi UX operator: konteks, total aktual, QC dan konflik data nyata."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models import User, ActivityLog
from app.services import barang_keluar as bk
from tests.pg.test_barang_keluar import gudang, _perintah, _stok, _undo
from tests.pg.test_qc_gabah import _buat_batch, _isi
from tests.pg.test_giling_beberapa_silo import silos
from tests.pg.test_gudang2_operator_pg import gudang2

pytestmark = pytest.mark.asyncio


async def _cuplikan(pg, rid):
    from app.models import OutgoingRecord
    async with pg() as db:
        return await bk.ringkasan_muat(db, await db.get(OutgoingRecord, rid))


async def test_qc_ditutup_hilang_dari_picker_dengan_alasan_dan_jejak(pg,pemakai,pemasok,monkeypatch):
    from app.web import api
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah,tutup_qc_gabah,ringkasan_tutup_qc
    monkeypatch.setattr(api,'_is_g1_operator',AsyncMock(return_value=True))
    monkeypatch.setattr(api,'_wajib_mutu',AsyncMock())
    kode='GB-UX7-QC'
    await _buat_batch(pg,pemakai,pemasok,'basah',kode)
    async with pg() as db:
        u=await db.get(User,pemakai.id)
        await catat_qc_gabah(db,user=u,kode_batch=kode,**_isi(1,lamur=False,sak=0))
        ringkas=await ringkasan_tutup_qc(db,kode_batch=kode)
        assert ringkas['jumlah']==1 and '1 dari 5' in ringkas['teks']
        with pytest.raises(ValueError,match='alasan'):
            await tutup_qc_gabah(db,user=u,kode_batch=kode,dasar=ringkas['dasar'])
    assert kode in {x['value'] for x in await api.gabah_qc('basah',user=pemakai)}
    async with pg() as db:
        u=await db.get(User,pemakai.id)
        qc,n=await tutup_qc_gabah(db,user=u,kode_batch=kode,dasar=ringkas['dasar'],alasan='Truk harus diproses')
        assert n==1 and qc.ditutup_pada
        log=(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='tutup_qc_gabah'))).one()
        assert log.alasan_perubahan=='Truk harus diproses' and '1/5' in log.new_value
    assert kode not in {x['value'] for x in await api.gabah_qc('basah',user=pemakai)}
    assert kode not in {x['value'] for x in await api.gabah_qc_bisa_ditutup(user=pemakai)}
    async with pg() as db:
        with pytest.raises(ValueError,match='sudah ditutup'):
            await catat_qc_gabah(db,user=await db.get(User,pemakai.id),kode_batch=kode,**_isi(2,lamur=False,sak=0))


async def test_qc_bertambah_saat_konfirmasi_tidak_ditutup(pg,pemakai,pemasok):
    from app.models import PurchaseBatchQc
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah,tutup_qc_gabah,ringkasan_tutup_qc
    kode='GB-UX7-KONFLIK'
    await _buat_batch(pg,pemakai,pemasok,'kering',kode)
    async with pg() as db:
        u=await db.get(User,pemakai.id)
        await catat_qc_gabah(db,user=u,kode_batch=kode,**_isi(1))
        awal=await ringkasan_tutup_qc(db,kode_batch=kode)
        await catat_qc_gabah(db,user=u,kode_batch=kode,**_isi(2))
    async with pg() as db:
        u=await db.get(User,pemakai.id)
        with pytest.raises(ValueError,match='berubah'):
            await tutup_qc_gabah(db,user=u,kode_batch=kode,dasar=awal['dasar'],alasan='Truk berangkat')
    async with pg() as db:
        qc=await db.scalar(select(PurchaseBatchQc))
        assert qc.ditutup_pada is None
        baru=await ringkasan_tutup_qc(db,kode_batch=kode)
        assert baru['jumlah']==2 and baru['dasar']!=awal['dasar']
        await tutup_qc_gabah(db,user=await db.get(User,pemakai.id),kode_batch=kode,dasar=baru['dasar'],alasan='Truk berangkat')


async def test_picker_barang_dan_kartu_membawa_perintah_pemilik_plat(pg,gudang):
    from app.web.aksi_inventory import baris_perintah
    from app.web.layar_keluar import _tombol
    a=await _perintah(pg,gudang,karung=100,pembeli='Bu Sri')
    b=await _perintah(pg,gudang,karung=50,pembeli='Pak Budi')
    async with pg() as db:
        u=await db.get(User,gudang['op'])
    assert await baris_perintah(user=u)==[]
    rows=await baris_perintah(induk=str(a.rec.id),user=u)
    assert {r['value'] for r in rows}=={str(i.id) for i in a.baris}
    assert not {r['value'] for r in rows}&{str(i.id) for i in b.baris}
    assert all(a.rec.kode in r['label'] and 'Bu Sri' in r['label'] and 'B 1234 XY' in r['label'] for r in rows)
    assert ('muat_barang',str(a.rec.id),'Catat per barang',False) in _tombol(a.rec,boleh_perintah=False,boleh_muat=True)
    # Tombol halaman Barang Keluar dan antrean sama-sama membawa id truk;
    # render kartu antrean diuji oleh suite muat konfirmasi yang sudah ada.


async def test_total20_tambah10_jadi30_pecahan_ditolak_dan_undo20(pg,gudang):
    from app.web.aksi_inventory import act_muat_barang,MuatBarisReq
    from app.models import OutgoingItem
    r=await _perintah(pg,gudang,karung=100)
    async with pg() as db:u=await db.get(User,gudang['op'])
    async def kirim(jumlah,dasar):
        return await act_muat_barang(MuatBarisReq(perintah=str(r.rec.id),baris=str(r.baris[0].id),jumlah=jumlah,dasar=dasar),user=u)
    awal=await _cuplikan(pg,r.rec.id)
    await kirim(20,awal['dasar'])
    dua=await _cuplikan(pg,r.rec.id)
    assert dua['baris'][0]['dimuat']==20
    for v in (20.5,30.1):
        with pytest.raises(HTTPException) as e:await kirim(v,dua['dasar'])
        assert e.value.status_code==400 and 'bilangan bulat' in e.value.detail
    assert await _stok(pg,gudang)==9500
    await kirim(30,dua['dasar'])
    assert await _stok(pg,gudang)==9250
    await _undo(pg,gudang['op'])
    assert await _stok(pg,gudang)==9500
    async with pg() as db:assert (await db.get(OutgoingItem,r.baris[0].id)).jumlah_karung==20


async def test_form_baris_basi_atau_salah_truk_ditolak_tanpa_mutasi(pg,gudang):
    from app.web.aksi_inventory import act_muat_barang,MuatBarisReq
    from app.models import OutgoingItem
    a=await _perintah(pg,gudang,karung=100)
    b=await _perintah(pg,gudang,karung=50)
    awal=await _cuplikan(pg,a.rec.id)
    async with pg() as db:
        u=await db.get(User,gudang['op'])
        await bk.catat_muatan(db,user=u,item_id=a.baris[0].id,jumlah_karung=90)
    with pytest.raises(HTTPException) as e:
        await act_muat_barang(MuatBarisReq(perintah=str(a.rec.id),baris=str(a.baris[0].id),jumlah=80,dasar=awal['dasar']),user=u)
    assert e.value.status_code==409 and 'berubah' in e.value.detail
    with pytest.raises(HTTPException) as e:
        await act_muat_barang(MuatBarisReq(perintah=str(a.rec.id),baris=str(b.baris[0].id),jumlah=20,dasar=awal['dasar']),user=u)
    assert e.value.status_code==400
    async with pg() as db:assert (await db.get(OutgoingItem,a.baris[0].id)).jumlah_karung==90


async def test_giling_kumulatif300_500_500_menyimpan_total500(pg,silos):
    from app.penggilingan.gudang1.services.milling import start_milling,log_progress,_latest_progress
    async with pg() as db:
        u=await db.get(User,silos['user'])
        r=await start_milling(db,user=u,nama_silo=['A'])
        for total in (300,500,500):
            await log_progress(db,user=u,kode_proses=r.proc.kode_proses,berat_kumulatif=total)
            assert await _latest_progress(db,r.proc.id)==total


async def test_sosoh_total_per_jenis_dan_kirim_ulang_tidak_bertambah(pg,gudang2):
    from app.models import PolishingOutputLog
    from app.penggilingan.gudang2.polishing import mulai_penyosohan,catat_output,_output_map
    async with pg() as db:
        u=gudang2['user'];p=await mulai_penyosohan(db,user=u,nama_silos=['B'])
        for jenis,total in [('premium',300),('premium',500),('premium',500),('menir',50),('menir',50)]:
            await catat_output(db,user=u,kode=p.proc.kode_proses,jenis=jenis,berat_kumulatif=total)
        hasil=await _output_map(db,p.proc.id)
        assert float(hasil['premium'])==500 and float(hasil['menir'])==50


async def test_katalog_formulir_membawa_konteks_dan_pratinjau(pg,gudang,monkeypatch):
    from app.web import api
    from app.services import setelan
    monkeypatch.setattr(api,'_is_g1_operator',AsyncMock(return_value=True))
    monkeypatch.setattr(api,'_is_g2_operator',AsyncMock(return_value=True))
    monkeypatch.setattr(setelan,'fitur_mutu',AsyncMock(return_value=True))
    async with pg() as db:u=await db.get(User,gudang['op'])
    menu={a['id']:a for a in await api.actions_menu(user=u)}
    qc=menu['qc_gabah_tutup']
    assert qc['pratinjau_qc']
    assert next(f for f in qc['fields'] if f['name']=='alasan')['wajib']
    muat=menu['muat_barang']
    assert muat['pratinjau_muat']=='baris'
    assert muat['fields'][0]['name']=='perintah'
    assert next(f for f in muat['fields'] if f['name']=='baris')['induk']=='perintah'
    assert next(f for f in muat['fields'] if f['name']=='jumlah')['label'].startswith('Total yang sudah dimuat')
