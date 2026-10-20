"""Penyerahan <200 kg atomik, tanpa operator/tiket, berdasarkan aktual."""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select
from tests.pg.test_barang_keluar import gudang, _perintah, _stok, _klien, _undo, _bekatul_curah, _pelanggan
from app.models import User, OutgoingRecord, OutgoingItem, ActivityLog
from app.services import barang_keluar as bk

pytestmark = pytest.mark.asyncio

async def payload(pg, r, jumlah=None):
    async with pg() as db:
        rec = await db.get(OutgoingRecord, r.rec.id)
        snap = await bk.ringkasan_muat(db, rec)
        return dict(rec_id=rec.id, dasar=snap['dasar'], diserahkan=True,
                    baris=[{'id': b['id'], 'jumlah': b['perintah'] if jumlah is None else jumlah}
                           for b in snap['baris']])

async def kirim(pg, g, data, uid=None):
    async with pg() as db:
        return await bk.konfirmasi_keluar_cepat(db, user=await db.get(User, uid or g['adm']), **data)

@pytest.mark.parametrize('berat,lolos', [(199.99,True),(200,False),(200.01,False)])
async def test_batas_total_perintah(pg,gudang,berat,lolos):
    await _bekatul_curah(pg,gudang,1000)
    pid=await _pelanggan(pg,'Pembeli curah uji')
    async with pg() as db:
        r=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=pid,
            baris=[bk.BarisPerintah(tipe='byproduct_curah',jenis='bekatul',berat_kg=berat)])
    from app.web.aksi_inventory import _ringkas_perintah
    if berat==199.99:
        assert "199,99 kg" in _ringkas_perintah(r.rec,r.baris)
    data=await payload(pg,r)
    if lolos:
        hasil=await kirim(pg,gudang,data)
        assert hasil.rec.status=='selesai' and hasil.rec.timbangan_transaksi_id is None
        assert float(hasil.baris[0].berat_kg)==berat
    else:
        with pytest.raises(bk.BarangKeluarError,match='di bawah 200'):
            await kirim(pg,gudang,data)
    from app.penggilingan.inventory.finished_goods import hitung_stok_byproduct_total
    async with pg() as db:
        assert float(await hitung_stok_byproduct_total(db,'bekatul'))==pytest.approx(1000-berat if lolos else 1000)

async def test_aktual_audit_dan_undo(pg,gudang):
    r=await _perintah(pg,gudang,karung=7)
    data=await payload(pg,r,6);data['sebab']='Satu karung belum diambil'
    hasil=await kirim(pg,gudang,data)
    assert hasil.rec.status=='selesai'
    assert hasil.rec.dimuat_oleh==hasil.rec.diverifikasi_oleh==gudang['adm']
    assert await _stok(pg,gudang)==9850
    async with pg() as db:
        it=await db.get(OutgoingItem,r.baris[0].id)
        assert it.jumlah_karung_perintah==7 and it.jumlah_karung==6
        logs=list((await db.execute(select(ActivityLog).where(ActivityLog.record_id==r.rec.id,ActivityLog.table_name=='outgoing_records').order_by(ActivityLog.id))).scalars())
        assert logs[-1].aksi=='barang_keluar_verifikasi'
        assert 'penyerahan' in logs[-1].alasan_perubahan
    await _undo(pg,gudang['adm'])
    await _undo(pg,gudang['adm'])
    assert await _stok(pg,gudang)==10000

@pytest.mark.parametrize('jumlah,sebab,diserahkan,dasar', [
    (None,'',True,True),(1.5,'kurang',True,True),(-1,'',True,True),
    (8,'',True,True),(0,'kurang',True,True),(6,'',True,True),
    (7,'',False,True),(7,'',True,False),(float('nan'),'',True,True)])
async def test_tolak_isian_tidak_sah_tanpa_ubah_stok(pg,gudang,jumlah,sebab,diserahkan,dasar):
    r=await _perintah(pg,gudang,karung=7)
    data=await payload(pg,r);data.update(sebab=sebab,diserahkan=diserahkan)
    data['baris'][0]['jumlah']=jumlah
    if not dasar:data['dasar']=''
    with pytest.raises(bk.BarangKeluarError):await kirim(pg,gudang,data)
    assert await _stok(pg,gudang)==10000

async def test_basi_pengiriman_ulang_dan_balapan(pg,gudang):
    r=await _perintah(pg,gudang,karung=7);data=await payload(pg,r)
    async with pg() as db:
        it=await db.get(OutgoingItem,r.baris[0].id);it.jumlah_karung_perintah=6;it.berat_perintah_kg=150;await db.commit()
    with pytest.raises(bk.MuatanBerubah):await kirim(pg,gudang,data)
    data=await payload(pg,r)
    results=await asyncio.gather(kirim(pg,gudang,data),kirim(pg,gudang,data),return_exceptions=True)
    assert sum(isinstance(x,bk.HasilPerintah) for x in results)==1
    assert sum(isinstance(x,bk.BarangKeluarError) for x in results)==1
    assert await _stok(pg,gudang)==9850
    with pytest.raises(bk.BarangKeluarError):await kirim(pg,gudang,data)

async def test_operator_tidak_boleh_dan_barang_asing_ditolak(pg,gudang):
    r=await _perintah(pg,gudang,karung=7);data=await payload(pg,r)
    with pytest.raises(bk.BarangKeluarError,match='Admin'):await kirim(pg,gudang,data,uid=gudang['op'])
    data['baris'][0]['id']+=100
    with pytest.raises(bk.BarangKeluarError,match='daftar barang'):await kirim(pg,gudang,data)
    assert await _stok(pg,gudang)==10000

async def test_rollback_semua_baris_jika_stok_habis(pg,gudang):
    from app.penggilingan.inventory.models import FinishedGoodsStock
    r=await _perintah(pg,gudang,karung=3)
    async with pg() as db:
        db.add(OutgoingItem(outgoing_record_id=r.rec.id,item_type='finished_goods',product_sku_id=gudang['sku'],rice_quality_standard_id=gudang['std'],jumlah_karung_perintah=4,berat_perintah_kg=100,berat_kg=0))
        stock=(await db.execute(select(FinishedGoodsStock))).scalars().first()
        stock.jumlah_karung=4;stock.berat_total_kg=100;await db.commit()
    data=await payload(pg,r)
    with pytest.raises(bk.BarangKeluarError,match='Stok tidak cukup'):await kirim(pg,gudang,data)
    assert await _stok(pg,gudang)==100
    async with pg() as db:
        assert (await db.get(OutgoingRecord,r.rec.id)).status=='perintah'
        assert all(float(i.berat_kg)==0 for i in (await db.execute(select(OutgoingItem))).scalars())

async def test_pemisahan_pabrik_dan_dua_pesanan_pemilik(pg,gudang):
    from app.models import Jasa,Pelanggan
    from app.database import now_local
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    async with pg() as db:
        a=Pelanggan(nama_pelanggan='Pemilik A');b=Pelanggan(nama_pelanggan='Pemilik B');db.add_all([a,b]);await db.flush()
        jobs=[Jasa(kode=f'JAS-CEPAT-{n}',pelanggan_id=p.id,status='berjalan') for n,p in enumerate([a,a,b])]
        db.add_all(jobs);await db.flush()
        ids=[j.id for j in jobs]
        for j in jobs:db.add(FinishedGoodsStock(product_sku_id=gudang['sku'],rice_quality_standard_id=gudang['std'],source_type='retur',jumlah_karung=4,berat_total_kg=100,jasa_id=j.id,waktu=now_local(),input_by=gudang['op']))
        await db.commit()
        r=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=a.id,
            baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=2,jasa_id=j) for j in ids[:2]])
    await kirim(pg,gudang,await payload(pg,r))
    assert await _stok(pg,gudang)==10000
    async with pg() as db:
        for jid,expected in zip(ids,[50,50,100]):
            stock=await hitung_stok_finished_goods(db,gudang['sku'],gudang['std'],jasa_id=jid)
            assert float(stock['kg'])==expected
        with pytest.raises(bk.BarangKeluarError):
            await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=a.id,
                baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=1,jasa_id=j) for j in [ids[0],ids[2]]])

async def test_api_dan_tombol_detail(pg,gudang):
    from tests.pg.formulir import cap_formulir
    r=await _perintah(pg,gudang,karung=7);data=await payload(pg,r)
    c=await _klien(pg,gudang['adm'],'admin_cepat')
    async with c:
        page=await c.get(f'/barang-keluar/{r.rec.id}')
        assert 'Konfirmasi barang keluar' in page.text
        opts=(await c.get('/api/actions/perintah-kecil')).json()
        assert str(r.rec.id) in [o['value'] for o in opts]
        from app.web import csrf
        headers={csrf.NAMA_HEADER: cap_formulir(c)}
        data['perintah']=str(data.pop('rec_id'))
        res=await c.post('/api/actions/konfirmasi-keluar-cepat',json=data,headers=headers)
        assert res.status_code==200,res.text
        again=await c.post('/api/actions/konfirmasi-keluar-cepat',json=data,headers=headers)
        assert again.status_code==400
    assert await _stok(pg,gudang)==9825

async def test_batas_menjumlah_seluruh_barang_dan_antrean_operator(pg,gudang):
    from app.services.berjalan import _kartu_barang_keluar
    from app.models import Notification
    r=await _perintah(pg,gudang,karung=4)
    async with pg() as db:
        assert not any(k.kode==r.rec.kode for k in await _kartu_barang_keluar(db,gudang='g2'))
        kabar=(await db.execute(select(Notification).where(Notification.table_name=='outgoing_records',Notification.record_id==r.rec.id))).scalars().all()
        assert kabar and all(n.target_role=='admin' for n in kabar)
        assert 'penyerahan' in kabar[-1].pesan
        db.add(OutgoingItem(outgoing_record_id=r.rec.id,item_type='finished_goods',product_sku_id=gudang['sku'],rice_quality_standard_id=gudang['std'],jumlah_karung_perintah=4,berat_perintah_kg=100,berat_kg=0))
        await db.commit()
        assert any(k.kode==r.rec.kode for k in await _kartu_barang_keluar(db,gudang='g2'))
    with pytest.raises(bk.BarangKeluarError,match='di bawah 200'):
        await kirim(pg,gudang,await payload(pg,r))
    assert await _stok(pg,gudang)==10000

async def test_dua_perintah_berebut_stok_tidak_minus(pg,gudang):
    from app.penggilingan.inventory.models import FinishedGoodsStock
    a=await _perintah(pg,gudang,karung=3,pembeli='Pembeli A')
    b=await _perintah(pg,gudang,karung=3,pembeli='Pembeli B')
    async with pg() as db:
        stock=(await db.execute(select(FinishedGoodsStock))).scalars().first()
        stock.jumlah_karung=4;stock.berat_total_kg=100;await db.commit()
    da,dbb=await payload(pg,a),await payload(pg,b)
    hasil=await asyncio.gather(kirim(pg,gudang,da),kirim(pg,gudang,dbb),return_exceptions=True)
    assert sum(isinstance(x,bk.HasilPerintah) for x in hasil)==1
    assert sum(isinstance(x,bk.BarangKeluarError) for x in hasil)==1
    assert await _stok(pg,gudang)==25

async def test_pemilik_diperiksa_ulang_sebelum_penyerahan(pg,gudang):
    from app.models import Jasa,Pelanggan
    from app.database import now_local
    from app.penggilingan.inventory.models import FinishedGoodsStock
    async with pg() as db:
        a=Pelanggan(nama_pelanggan='Pemilik A');b=Pelanggan(nama_pelanggan='Pemilik B')
        db.add_all([a,b]);await db.flush()
        j=Jasa(kode='JAS-CEPAT-PEMILIK',pelanggan_id=a.id,status='berjalan');db.add(j);await db.flush()
        db.add(FinishedGoodsStock(product_sku_id=gudang['sku'],rice_quality_standard_id=gudang['std'],source_type='retur',jumlah_karung=4,berat_total_kg=100,jasa_id=j.id,waktu=now_local(),input_by=gudang['op']))
        await db.commit()
        r=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),jasa_id=j.id,
            baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=2)])
        r.rec.pelanggan_id=b.id;await db.commit()
    with pytest.raises(bk.BarangKeluarError,match='kepemilikan'):
        await kirim(pg,gudang,await payload(pg,r))
    async with pg() as db:
        assert float((await db.get(OutgoingItem,r.baris[0].id)).berat_kg)==0
    assert await _stok(pg,gudang)==10000
