"""Satu perjalanan, alokasi per pelanggan, dan satu saldo bersama yang terkunci."""
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from app.database import now_local
from app.models import (ActivityLog, DrafKeluar, FinishedGoodsStock, KemasanTara,
                        OutgoingItem, OutgoingRecord, Pelanggan, ProductSku, User)
from app.penggilingan.inventory.models import KirimanKeluar
from app.services import barang_keluar as bk
from app.web.aksi_inventory import PerintahKeluarReq, _kelompok_dari_borang, pratinjau_kiriman
from app.web.draf_keluar import SimpanDraf, TerbitDraf, simpan, terbitkan
from tests.pg.test_barang_keluar import gudang, _pelanggan, _stok, _tiket, _klien

pytestmark = pytest.mark.asyncio

async def _data(pg, g, jumlah=(20, 30)):
    a=await _pelanggan(pg,'Penerima A'); b=await _pelanggan(pg,'Penerima B')
    return dict(kelompok=[dict(pelanggan=str(pid), barang=[
        dict(pilih=f"bj:{g['sku']}|{g['std']}",jumlah=str(n)),
        dict(pilih=f"bj:{g['sku']}|{g['std']}",jumlah='2')]) for pid,n in zip((a,b),jumlah)],
        metode='diantar',nama_ekspedisi='Uji bersama')

async def _buat(pg,g,data):
    async with pg() as db:
        req=PerintahKeluarReq.model_validate(data)
        return await bk.buat_kiriman(db,user=await db.get(User,g['adm']),
            kelompok=await _kelompok_dari_borang(db,req),metode=req.metode,
            nama_ekspedisi=req.nama_ekspedisi,
            tiket_armada_id=int(req.tiket_armada) if req.tiket_armada else None)

async def _muat(pg,g,rs):
    for r in rs:
        async with pg() as db:
            await bk.muat_semua(db,user=await db.get(User,g['op']),rec_id=r.rec.id)

async def _tiket_armada(pg,g,rs,berat=1350):
    tid=await _tiket(pg,'KLR-KIRIMAN',barang=berat)
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET nomor_polisi='B 1234 XY', timbang1_kg=9000, timbang2_kg=:br, total_tara_kg=0 WHERE id=:tid"),{'br':9000+berat,'tid':tid})
        await db.commit()
        await bk.pilih_tiket_armada(db,user=await db.get(User,g['adm']),rec_id=rs[-1].rec.id,tiket_id=tid)
    return tid

async def test_empat_item_penerima_terpisah_reservasi_dan_fisik(pg,gudang):
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    assert len(rs)==2 and rs[0].rec.kiriman_id==rs[1].rec.kiriman_id
    assert rs[0].rec.pelanggan_id!=rs[1].rec.pelanggan_id
    assert [sum(float(i.berat_perintah_kg) for i in r.baris) for r in rs]==[550,800]
    assert await _stok(pg,gudang)==10000
    async with pg() as db:
        stok,_=await bk.tersedia(db,bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std']))
        assert stok==8650
        assert await db.scalar(select(func.count()).select_from(OutgoingItem))==4
        assert await db.scalar(select(func.count()).select_from(KirimanKeluar))==1
    await _muat(pg,gudang,rs)
    assert await _stok(pg,gudang)==8650
    async with pg() as db:
        with pytest.raises(bk.BarangKeluarError):
            await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=rs[0].rec.id)
    assert await _stok(pg,gudang)==8650

async def test_sumber_bersama_kelebihan_tidak_menyimpan_pelanggan_pertama(pg,gudang):
    data=await _data(pg,gudang,(250,200))
    async with pg() as db:
        req=PerintahKeluarReq.model_validate(data)
        with pytest.raises(bk.BarangKeluarError,match='tinggal'):
            await bk.buat_kiriman(db,user=await db.get(User,gudang['adm']),kelompok=await _kelompok_dari_borang(db,req))
        # Bahkan jika pemanggil meng-commit setelah menangkap galat, tidak ada sisa.
        await db.commit()
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0
        assert await db.scalar(select(func.count()).select_from(KirimanKeluar))==0
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='outgoing_records'))==0
    assert await _stok(pg,gudang)==10000

async def test_dua_transaksi_berebut_saldo_global(pg,gudang):
    d1=await _data(pg,gudang,(100,100));d2=await _data(pg,gudang,(100,100))
    hasil=await asyncio.gather(_buat(pg,gudang,d1),_buat(pg,gudang,d2),return_exceptions=True)
    assert sum(isinstance(x,bk.BarangKeluarError) for x in hasil)==1
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==2
        assert await db.scalar(select(func.count()).select_from(KirimanKeluar))==1
    assert await _stok(pg,gudang)==10000

async def test_draf_gabungan_penerbitan_idempoten_dan_gagal_tetap_utuh(pg,gudang):
    data=await _data(pg,gudang);ident=uuid4()
    async with pg() as db:u=await db.get(User,gudang['adm'])
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=data),u)
    a,b=await asyncio.gather(terbitkan(ident,TerbitDraf(revisi=1),u),terbitkan(ident,TerbitDraf(revisi=1),u))
    assert a['tujuan']==b['tujuan']
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==2
        assert (await db.get(DrafKeluar,str(ident))).isi==data
    ident=uuid4();data['kelompok'][1]['barang'][0]['jumlah']='1000'
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=data),u)
    with pytest.raises(HTTPException):await terbitkan(ident,TerbitDraf(revisi=1),u)
    async with pg() as db:
        assert (await db.get(DrafKeluar,str(ident))).isi==data
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==2

@pytest.mark.parametrize('cacat',['ganda','parsial','nol','pecahan','titipan','kosong','lebih12','nonkledo'])
async def test_validasi_tidak_membuang_isian(pg,gudang,cacat):
    data=await _data(pg,gudang)
    if cacat=='ganda':data['kelompok'][1]['pelanggan']=data['kelompok'][0]['pelanggan']
    elif cacat=='parsial':data['kelompok'][1]['barang'].append(dict(pilih='',jumlah='7'))
    elif cacat=='nol':data['kelompok'][1]['barang'][0]['jumlah']='0'
    elif cacat=='pecahan':data['kelompok'][1]['barang'][0]['jumlah']='1.5'
    elif cacat=='titipan':data['kelompok'][1]['barang'][0]['pilih']+='@99'
    elif cacat=='kosong':data['kelompok'][1]['barang']=[dict(pilih='',jumlah='')]
    elif cacat=='lebih12':data['kelompok'][1]['barang']*=7
    elif cacat=='nonkledo':
        async with pg() as db:
            p=Pelanggan(nama_pelanggan='Nama bebas tanpa Kledo');db.add(p);await db.commit()
            data['kelompok'][1]['pelanggan']=str(p.id)
    ident=uuid4()
    async with pg() as db:u=await db.get(User,gudang['adm'])
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=data),u)
    with pytest.raises(HTTPException):await terbitkan(ident,TerbitDraf(revisi=1),u)
    async with pg() as db:
        assert (await db.get(DrafKeluar,str(ident))).isi==data
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0

async def test_pratinjau_baris_kosong_saldo_fisik_terikat_rancangan(pg,gudang):
    data=await _data(pg,gudang)
    await _buat(pg,gudang,data)
    data['kelompok'][0]['barang'].append(dict(pilih='',jumlah=''))
    async with pg() as db:u=await db.get(User,gudang['adm'])
    r=await pratinjau_kiriman(PerintahKeluarReq.model_validate(data),u)
    source=next(iter(r['sumber'].values()))
    assert (source['fisik'],source['terikat'],source['rancangan'],r['total'])==(10000,1350,1350,1350)
    assert r['subtotal']==[550,800]
    assert await _stok(pg,gudang)==10000

async def test_tiket_satu_tautan_total_armada_identitas_tidak_ditimpa(pg,gudang,monkeypatch):
    from app.web import internal
    monkeypatch.setattr(internal.settings,'internal_api_token','uji-kiriman')
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    tid=await _tiket_armada(pg,gudang,rs)
    async with pg() as db:
        snapshot=(await db.execute(text('SELECT pelanggan_id,pihak_nama FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).first()
        assert await db.scalar(text('SELECT count(*) FROM outgoing_records WHERE timbangan_transaksi_id=:id'),{'id':tid})==0
        assert await db.scalar(text('SELECT count(*) FROM kiriman_keluar WHERE timbangan_transaksi_id=:id'),{'id':tid})==1
        for r in rs:assert (await db.get(OutgoingRecord,r.rec.id)).timbangan_transaksi_id==tid
        with pytest.raises(HTTPException):await internal._cocokkan_pengiriman_tiket(db,tid)
    await _muat(pg,gudang,rs)
    # Tara produk untuk payload Timbangan.
    async with pg() as db:
        sku=await db.get(ProductSku,gudang['sku'])
        tara=await db.scalar(select(KemasanTara).where(KemasanTara.packaging_material_id==sku.packaging_material_id,KemasanTara.package_size_id==sku.package_size_id))
        if not tara:db.add(KemasanTara(packaging_material_id=sku.packaging_material_id,package_size_id=sku.package_size_id,tara_per_karung_kg='.1'))
        await db.commit()
    payload=await internal.pengiriman_muatan_tiket(tid,'uji-kiriman')
    assert len(payload['muatan'])==4 and sum(b['berat_kg'] for b in payload['muatan'])==1350
    assert {b['pelanggan_id'] for b in payload['muatan']}=={r.rec.pelanggan_id for r in rs}
    assert len({b['outgoing_item_id'] for b in payload['muatan']})==4
    async with pg() as db:
        await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rs[1].rec.id,otomatis=True)
    async with pg() as db:
        for r in rs:assert (await db.get(OutgoingRecord,r.rec.id)).status=='selesai'
        assert (await db.execute(text('SELECT pelanggan_id,pihak_nama FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).first()==snapshot
    assert await _stok(pg,gudang)==8650
    c=await _klien(pg,gudang['adm'],'kiriman-detail')
    async with c:
        page=await c.get(f'/barang-keluar/{rs[0].rec.id}')
        assert page.status_code==200,page.text
        assert 'Penerima A' in page.text and 'Penerima B' in page.text and '1.350' in page.text
        assert 'Hasil timbang total satu armada untuk 2 pelanggan' in page.text
        import os
        from pathlib import Path
        if os.environ.get('UJI_KIRIMAN_OUT'):
            Path(os.environ['UJI_KIRIMAN_OUT'],'detail-pf470.html').write_text(page.text)

async def test_koreksi_selesai_kurang_batal_dan_undo_gabungan(pg,gudang):
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    async with pg() as db:
        await bk.koreksi_plat(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id,no_polisi='AD 7788 ZZ',alasan='Armada datang')
    async with pg() as db:
        assert all(r.no_polisi=='AD 7788 ZZ' for r in await bk.anggota_kiriman(db,await db.get(OutgoingRecord,rs[0].rec.id)))
        await bk.catat_muatan(db,user=await db.get(User,gudang['op']),item_id=rs[0].baris[0].id,jumlah_karung=10)
        with pytest.raises(bk.BarangKeluarError,match='alasan'):
            await bk.selesai_muat(db,user=await db.get(User,gudang['op']),rec_id=rs[0].rec.id)
        await bk.selesai_muat(db,user=await db.get(User,gudang['op']),rec_id=rs[0].rec.id,sebab='Persediaan belum dimuat seluruhnya')
        await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=rs[1].rec.id)
        await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id)
        await bk.balik_verifikasi(db,rec_id=rs[1].rec.id);await db.commit()
    async with pg() as db:
        for r in rs:assert (await db.get(OutgoingRecord,r.rec.id)).status=='dimuat'
    assert await _stok(pg,gudang)==8950

async def test_peran_endpoint_langsung_tetap_ditolak(pg,gudang):
    data=await _data(pg,gudang)
    async with pg() as db:u=await db.get(User,gudang['op'])
    with pytest.raises(HTTPException) as e:await pratinjau_kiriman(PerintahKeluarReq.model_validate(data),u)
    assert e.value.status_code==403
    with pytest.raises(HTTPException) as e:await simpan(uuid4(),SimpanDraf(revisi=0,kiriman=uuid4(),isi=data),u)
    assert e.value.status_code==403

async def test_beragam_barang_dan_hasil_samping_otomatis(pg,gudang):
    from app.models import ByproductStock
    data=await _data(pg,gudang)
    async with pg() as db:
        now=now_local()
        db.add(ByproductStock(jenis_produk='bekatul',source_type='retur',source_id=None,
            berat_kg=1000,tanggal=now.date(),waktu=now,input_by=gudang['op']))
        await db.commit()
    for k,n in zip(data['kelompok'],(100,150)):
        k['barang'][1]=dict(pilih='cr:bekatul',jumlah=str(n))
    rs=await _buat(pg,gudang,data)
    assert [sum(float(it.berat_perintah_kg) for it in r.baris) for r in rs]==[600,900]
    async with pg() as db:
        ada,_=await bk.tersedia(db,bk.BarisPerintah(tipe='byproduct_curah',jenis='bekatul'))
        assert ada==750
    await _muat(pg,gudang,rs)
    async with pg() as db:
        # Perhitungan gabungan kemasan otomatis dan curah tetap melalui layanan lama.
        ada,_=await bk.tersedia(db,bk.BarisPerintah(tipe='byproduct_curah',jenis='bekatul'),abaikan_pesanan=True)
        assert ada==750
    assert await _stok(pg,gudang)==8750

async def test_retur_penerima_dan_item_asal_tidak_tertukar(pg,gudang):
    from decimal import Decimal
    from app.models import CustomerReturn, CustomerReturnItem
    from app.services import retur_pengajuan as rp, retur_penerimaan as rt
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data);await _muat(pg,gudang,rs)
    async with pg() as db:
        user=await db.get(User,gudang['adm'])
        await bk.verifikasi(db,user=user,rec_id=rs[0].rec.id)
        sku=await db.get(ProductSku,gudang['sku'])
        tara=await db.scalar(select(KemasanTara.tara_per_karung_kg).where(
            KemasanTara.packaging_material_id==sku.packaging_material_id,KemasanTara.package_size_id==sku.package_size_id))
        await db.execute(text('ALTER TABLE timbangan_transaksi ALTER COLUMN arah TYPE varchar(16)'))
        tiket=[]
        for i in range(3):
            tiket.append(await db.scalar(text("""INSERT INTO timbangan_transaksi
                (kode,tanggal,arah,jenis_kode,timbang1_kg,timbang2_kg,berat_barang_kg,status_tiket,status_transaksi,pelanggan_id)
                VALUES (:kode,CURRENT_DATE,'RETUR_MASUK','RETUR_PELANGGAN',9000,8950,:berat,'SELESAI','AKTIF',:pid) RETURNING id"""),
                dict(kode=f'RTP-KIRIMAN-{i}',berat=Decimal(50)+Decimal(tara)*2,pid=rs[0].rec.pelanggan_id)))
        await db.commit()
    async with pg() as db:
        with pytest.raises(ValueError,match='pelanggan'):
            await rp.simpan(db,pengiriman_id=rs[1].rec.id,tiket_id=tiket[0],jumlah={rs[1].baris[0].id:'2'},pelaku_id=gudang['adm'])
        with pytest.raises(ValueError,match='bukan bagian'):
            await rp.simpan(db,pengiriman_id=rs[0].rec.id,tiket_id=tiket[0],jumlah={rs[1].baris[0].id:'2'},pelaku_id=gudang['adm'])
        r=await rp.simpan(db,pengiriman_id=rs[0].rec.id,tiket_id=tiket[0],jumlah={rs[0].baris[0].id:'2'},pelaku_id=gudang['adm'])
        assert Decimal(r.hasil_pemeriksaan['toleransi_kg'])==Decimal(tara)*2
        rid=r.id;await db.commit()
    async with pg() as db:
        a=await rt.periksa_dan_terima(db,rid);await db.commit()
        assert a and a.pelanggan_id==rs[0].rec.pelanggan_id
        b=await rt.periksa_dan_terima(db,rid);assert b.id==a.id;await db.commit()
    assert await _stok(pg,gudang)==8700
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(CustomerReturn))==1
        item=await db.scalar(select(CustomerReturnItem));assert item.outgoing_item_id==rs[0].baris[0].id
        with pytest.raises(ValueError,match='kumulatif'):
            await rp.simpan(db,pengiriman_id=rs[0].rec.id,tiket_id=tiket[1],jumlah={rs[0].baris[0].id:'19'},pelaku_id=gudang['adm'])
        # Retur salah satu pelanggan juga melindungi undo verifikasi seluruh armada.
        with pytest.raises(bk.BarangKeluarError,match='retur terkait'):
            await bk.balik_verifikasi(db,rec_id=rs[1].rec.id)
        await db.commit()
    async with pg() as db:
        for r in rs:assert (await db.get(OutgoingRecord,r.rec.id)).status=='selesai'

async def test_tiket_bersama_tidak_dapat_dipakai_kiriman_atau_perintah_lain(pg,gudang):
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    tid=await _tiket_armada(pg,gudang,rs)
    lainnya=await _data(pg,gudang);lainnya['tiket_armada']=str(tid)
    with pytest.raises(bk.BarangKeluarError,match='pengiriman lain'):await _buat(pg,gudang,lainnya)
    # Endpoint verifikasi lama juga harus menghormati tautan di tabel induk baru.
    async with pg() as db:
        req=PerintahKeluarReq.model_validate(lainnya)
        kelompok=await _kelompok_dari_borang(db,req)
        r=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=kelompok[0][0],baris=kelompok[0][1])
        await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=r.rec.id)
        with pytest.raises(bk.BarangKeluarError,match='pengiriman lain'):
            await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=r.rec.id,timbangan_transaksi_id=tid)

async def test_callback_sidik_auth_dan_replay_gabungan(pg,gudang,monkeypatch):
    from app.web import internal
    from hmu_identitas.model import Akun
    monkeypatch.setattr(internal.settings,'internal_api_token','uji-kiriman')
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    tid=await _tiket_armada(pg,gudang,rs);await _muat(pg,gudang,rs)
    async with pg() as db:
        a=Akun(user_id=gudang['op'],username='timbang-kiriman',password_hash='uji',status='aktif')
        db.add(a);await db.commit();aid=a.id
    payload=await internal.pengiriman_muatan_tiket(tid,'uji-kiriman')
    req=internal.VerifikasiTiketReq(sidik_sumber=payload['sidik_sumber'])
    with pytest.raises(HTTPException) as e:await internal.verifikasi_pengiriman_tiket(tid,aid,'uji-kiriman')
    assert e.value.status_code==409
    with pytest.raises(HTTPException) as e:await internal.verifikasi_pengiriman_tiket(tid,aid,'uji-kiriman',internal.VerifikasiTiketReq(sidik_sumber='salah'))
    assert e.value.status_code==409
    a,b=await asyncio.gather(internal.verifikasi_pengiriman_tiket(tid,aid,'uji-kiriman',req),internal.verifikasi_pengiriman_tiket(tid,aid,'uji-kiriman',req))
    assert a['selesai'] and b['selesai']
    ulang=await internal.pengiriman_muatan_tiket(tid,'uji-kiriman')
    assert ulang['sidik_sumber']==req.sidik_sumber
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_verifikasi'))==2
        akun=await db.get(Akun,aid);akun.status='nonaktif';await db.commit()
    with pytest.raises(HTTPException) as e:await internal.verifikasi_pengiriman_tiket(tid,aid,'uji-kiriman',req)
    assert e.value.status_code==403
    assert await _stok(pg,gudang)==8650

async def test_muatan_berubah_sesudah_snapshot_tidak_diam_diam_diverifikasi(pg,gudang,monkeypatch):
    from app.web import internal
    from hmu_identitas.model import Akun
    monkeypatch.setattr(internal.settings,'internal_api_token','uji-kiriman')
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    tid=await _tiket_armada(pg,gudang,rs);await _muat(pg,gudang,rs)
    payload=await internal.pengiriman_muatan_tiket(tid,'uji-kiriman')
    async with pg() as db:
        a=Akun(user_id=gudang['op'],username='timbang-kiriman',password_hash='uji',status='aktif');db.add(a)
        it=await db.get(OutgoingItem,rs[1].baris[0].id)
        it.jumlah_karung=29;it.berat_kg=725;await db.commit();aid=a.id
    with pytest.raises(HTTPException) as e:
        await internal.verifikasi_pengiriman_tiket(tid,aid,'uji-kiriman',internal.VerifikasiTiketReq(sidik_sumber=payload['sidik_sumber']))
    assert e.value.status_code==409 and 'berubah' in str(e.value.detail)
    async with pg() as db:
        for r in rs:assert (await db.get(OutgoingRecord,r.rec.id)).status=='dimuat'

async def test_saldo_berubah_di_transaksi_lain_sebelum_kunci_didapat(pg,gudang):
    data=await _data(pg,gudang,(150,150));req=PerintahKeluarReq.model_validate(data)
    async with pg() as db:u=await db.get(User,gudang['adm'])
    preview=await pratinjau_kiriman(req,u);assert preview['total']==7600
    async with pg() as db:
        await bk._kunci_saldo_keluar(db)
        proses=asyncio.create_task(_buat(pg,gudang,data))
        await asyncio.sleep(.05)
        assert not proses.done()
        stock=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.product_sku_id==gudang['sku']))
        stock.jumlah_karung=200;stock.berat_total_kg=5000
        await db.commit()
    with pytest.raises(bk.BarangKeluarError,match='tinggal'):await proses
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0

async def test_batal_semua_melepas_tiket_tanpa_stok_dan_boleh_dipakai_ulang(pg,gudang):
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    tid=await _tiket_armada(pg,gudang,rs)
    for r in rs:
        async with pg() as db:
            await bk.batalkan(db,user=await db.get(User,gudang['adm']),rec_id=r.rec.id,sebab='Kiriman tidak jadi')
    assert await _stok(pg,gudang)==10000
    lainnya=await _data(pg,gudang);lainnya['tiket_armada']=str(tid)
    baru=await _buat(pg,gudang,lainnya)
    assert baru[0].rec.timbangan_transaksi_id==tid

async def test_gagal_audit_anggota_kedua_menggagalkan_verifikasi_seluruhnya(pg,gudang,monkeypatch):
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data);await _muat(pg,gudang,rs)
    jejak=bk._jejak
    async def gagal(db,rec,**kw):
        if kw.get('langkah')=='verifikasi' and rec.id==rs[1].rec.id:raise RuntimeError('Gangguan audit uji')
        return await jejak(db,rec,**kw)
    monkeypatch.setattr(bk,'_jejak',gagal)
    async with pg() as db:
        with pytest.raises(RuntimeError,match='Gangguan audit'):
            await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id)
        await db.commit()
    async with pg() as db:
        for r in rs:assert (await db.get(OutgoingRecord,r.rec.id)).status=='dimuat'
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_verifikasi'))==0
    assert await _stok(pg,gudang)==8650

async def test_koreksi_target_dan_tambah_item_tetap_pada_pelanggan_asal(pg,gudang):
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    async with pg() as db:
        u=await db.get(User,gudang['adm'])
        dasar=(await bk.ringkasan_muat(db,await db.get(OutgoingRecord,rs[0].rec.id)))['dasar']
        await bk.ubah_baris_perintah(db,user=u,rec_id=rs[0].rec.id,item_id=rs[0].baris[0].id,jumlah=25,dasar=dasar,alasan='Perubahan pesanan pelanggan A')
        await bk.tambah_baris(db,user=u,rec_id=rs[1].rec.id,baris=bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=5))
    assert await _stok(pg,gudang)==10000
    async with pg() as db:
        a=await db.get(OutgoingItem,rs[0].baris[0].id)
        b=await db.get(OutgoingItem,rs[1].baris[0].id)
        assert a.jumlah_karung_perintah==25 and b.jumlah_karung_perintah==35
        assert a.outgoing_record_id==rs[0].rec.id and b.outgoing_record_id==rs[1].rec.id
        ada,_=await bk.tersedia(db,bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std']))
        assert ada==8400

async def test_snapshot_perintah_lama_tiket_menyusul_stabil_sesudah_tautan(pg,gudang,monkeypatch):
    from app.web import internal
    from hmu_identitas.model import Akun
    from tests.pg.test_barang_keluar import _perintah
    monkeypatch.setattr(internal.settings,'internal_api_token','uji-kiriman')
    r=await _perintah(pg,gudang,karung=100)
    await _muat(pg,gudang,[r])
    tid=await _tiket(pg,'KLR-LAMA-SNAPSHOT',barang=2500)
    async with pg() as db:
        assert (await db.get(OutgoingRecord,r.rec.id)).timbangan_transaksi_id is None
        a=Akun(user_id=gudang['op'],username='timbang-lama',password_hash='uji',status='aktif');db.add(a);await db.commit();aid=a.id
    payload=await internal.pengiriman_muatan_tiket(tid,'uji-kiriman')
    req=internal.VerifikasiTiketReq(sidik_sumber=payload['sidik_sumber'])
    for _ in range(2):assert (await internal.verifikasi_pengiriman_tiket(tid,aid,'uji-kiriman',req))['selesai']
    assert (await internal.pengiriman_muatan_tiket(tid,'uji-kiriman'))['sidik_sumber']==payload['sidik_sumber']
    assert await _stok(pg,gudang)==7500

async def test_penarikan_perintah_dengan_muatan_parsial_tidak_mengembalikan_stok(pg,gudang):
    data=await _data(pg,gudang);rs=await _buat(pg,gudang,data)
    async with pg() as db:
        await bk.catat_muatan(db,user=await db.get(User,gudang['op']),item_id=rs[0].baris[0].id,jumlah_karung=10)
        with pytest.raises(bk.BarangKeluarError,match='pencatatan muatan'):
            await bk.balik_perintah(db,rec_id=rs[0].rec.id)
        await db.commit()
    assert await _stok(pg,gudang)==9750
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'
        assert (await db.get(OutgoingItem,rs[0].baris[0].id)).jumlah_karung==10
