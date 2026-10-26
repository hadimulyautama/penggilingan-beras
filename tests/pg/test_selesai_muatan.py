"""Penyelesaian pelanggan memakai aktual, reservasi, izin, audit dan undo lama."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func,text
from app.models import OutgoingRecord,OutgoingItem,ActivityLog,Notification,User,Warehouse
from app.services import barang_keluar as bk
from app.web import selesai_muatan as layar
from app.web.aksi_inventory import SelesaiMuatReq,act_selesai_muat
from tests.pg.test_barang_keluar import gudang,_stok,_klien,_undo
from tests.pg.test_kiriman_pelanggan import _data,_buat,_tiket_armada
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio

async def _u(pg,g,key='op'):
    async with pg() as db:return await db.get(User,g[key])

async def _setup(pg,g,muat=True):
    rs=await _buat(pg,g,await _data(pg,g,(40,30)))
    if muat:
        for r,n in zip(rs,(20,5)):
            async with pg() as db:await bk.catat_muatan(db,user=await db.get(User,g['op']),item_id=r.baris[0].id,jumlah_karung=n)
    return rs

async def _body(pg,r,sebab='Stok fisik kurang saat muat'):
    async with pg() as db:
        rec=await db.get(OutgoingRecord,r.rec.id);snap=await bk.ringkasan_muat(db,rec)
        return dict(perintah=str(rec.id),kiriman_id=rec.kiriman_id,pelanggan_id=rec.pelanggan_id,
            item_ids=[i['id'] for i in snap['baris']],dasar=snap['dasar'],sebab=sebab)

async def _items(pg):
    async with pg() as db:
        return list((await db.execute(select(OutgoingItem.id,OutgoingItem.outgoing_record_id,
            OutgoingItem.berat_kg,OutgoingItem.jumlah_karung,OutgoingItem.product_sku_id,
            OutgoingItem.rice_quality_standard_id,OutgoingItem.jasa_id).order_by(OutgoingItem.id))).all())

async def _tutup(pg,g,body):return await act_selesai_muat(SelesaiMuatReq(**body),await _u(pg,g))

async def test_kurang_item_nol_stok_tetap_reservasi_lepas_dan_pelanggan_lain_terbuka(pg,gudang):
    rs=await _setup(pg,gudang);body=await _body(pg,rs[0]);u=await _u(pg,gudang)
    awal=await _items(pg);stok=await _stok(pg,gudang)
    plan=await layar.periksa(SelesaiMuatReq(**body),u)
    assert plan['total_perintah_kg']==1050 and plan['total_aktual_kg']==500
    assert plan['tidak_terkirim_kg']==550 and plan['perubahan_stok_kg']==0
    assert len(plan['barang'])==2 and plan['barang'][1]['dimuat']==0
    async with pg() as db:reserved=await bk._sudah_dipesan(db,sku_id=gudang['sku'],std_id=gudang['std'])
    assert reserved==1225
    await _tutup(pg,gudang,body)
    assert await _items(pg)==awal and await _stok(pg,gudang)==stok
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='dimuat'
        assert (await db.get(OutgoingRecord,rs[1].rec.id)).status=='perintah'
        assert await bk._sudah_dipesan(db,sku_id=gudang['sku'],std_id=gudang['std'])==675
        logs=(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='barang_keluar_muat'))).all()
        assert len(logs)==1 and logs[0].changed_by==gudang['op'] and logs[0].alasan_perubahan==body['sebab']
        assert logs[0].old_value=='' and logs[0].field_name=='diisi'
        k=(await layar.papan_selesai(db,rs[0].rec.id))['kiriman'][0]
        assert k['pelanggan_selesai']==1 and not k['semua_selesai_muat'] and k['kesiapan']=='menunggu_pelanggan'
        assert k['pelanggan'][0]['penutupan']['alasan']==body['sebab']
        assert k['total_tidak_terkirim_kg']==550 and k['pelanggan'][1]['penutupan'] is None
        notif=(await db.scalars(select(Notification).where(Notification.record_id==rs[0].rec.id,
            Notification.table_name=='outgoing_records').order_by(Notification.id.desc()))).first()
        assert 'menunggu semua pelanggan selesai muat' in notif.pesan


async def test_sesuai_perintah_alasan_opsional_aktual_tidak_ditulis_ulang(pg,gudang):
    rs=await _setup(pg,gudang,False);u=await _u(pg,gudang)
    for it in rs[0].baris:
        async with pg() as db:await bk.catat_muatan(db,user=u,item_id=it.id,jumlah_karung=it.jumlah_karung_perintah)
    body=await _body(pg,rs[0],sebab='');awal=await _items(pg);stok=await _stok(pg,gudang)
    plan=await layar.periksa(SelesaiMuatReq(**body),u);assert plan['tidak_terkirim_kg']==0
    await _tutup(pg,gudang,body)
    assert await _items(pg)==awal and await _stok(pg,gudang)==stok

@pytest.mark.parametrize('sebab',['','   ','\n\t'])
async def test_kekurangan_wajib_alasan_bukan_spasi(pg,gudang,sebab):
    rs=await _setup(pg,gudang);body=await _body(pg,rs[0],sebab=sebab);u=await _u(pg,gudang)
    for fn in (layar.periksa,act_selesai_muat):
        with pytest.raises(HTTPException) as e:await fn(SelesaiMuatReq(**body),u)
        assert e.value.status_code==400 and 'alasan' in str(e.value.detail).lower()
    async with pg() as db:assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'

async def test_seluruh_item_nol_tidak_dapat_ditutup_hanya_dengan_alasan(pg,gudang):
    rs=await _setup(pg,gudang,False);body=await _body(pg,rs[0]);u=await _u(pg,gudang)
    async with pg() as db:
        p=(await layar.papan_selesai(db,rs[0].rec.id))['kiriman'][0]['pelanggan'][0]
        assert not p['bisa_selesai'] and not p['ada_muatan']
    for fn in (layar.periksa,act_selesai_muat):
        with pytest.raises(HTTPException) as e:await fn(SelesaiMuatReq(**body),u)
        assert 'Catat muatannya dulu' in e.value.detail
    assert await _stok(pg,gudang)==10000

@pytest.mark.parametrize('selisih,wajib',[(.5,False),(.501,True)])
async def test_ambang_kekurangan_sama_dengan_layanan_lama(selisih,wajib):
    row=SimpleNamespace(berat_kg=1,berat_perintah_kg=1+selisih)
    assert bk.syarat_selesai_muat([row])['alasan_wajib']==wajib
    if wajib:
        with pytest.raises(bk.BarangKeluarError):bk.periksa_selesai_muat(SimpleNamespace(kode='UJI'),[row],'')
    else:bk.periksa_selesai_muat(SimpleNamespace(kode='UJI'),[row],'')

@pytest.mark.parametrize('ubah',['aktual','perintah','status','penerima','armada','pelanggan_lain','hapus_item'])
async def test_snapshot_berubah_tahan_penyelesaian_dan_tidak_ada_pengulangan_otomatis(pg,gudang,ubah):
    rs=await _setup(pg,gudang);u=await _u(pg,gudang);body=await _body(pg,rs[0])
    await layar.periksa(SelesaiMuatReq(**body),u)
    async with pg() as db:
        if ubah=='aktual':await bk.catat_muatan(db,user=u,item_id=rs[0].baris[0].id,jumlah_karung=21)
        elif ubah=='pelanggan_lain':await bk.catat_muatan(db,user=u,item_id=rs[1].baris[0].id,jumlah_karung=6)
        elif ubah=='perintah':await bk.ubah_baris_perintah(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id,item_id=rs[0].baris[0].id,jumlah=39,dasar=body['dasar'],alasan='Koreksi target')
        elif ubah=='status':await bk.selesai_muat(db,user=u,rec_id=rs[0].rec.id,sebab='Selesai oleh rekan')
        elif ubah=='penerima':r=await db.get(OutgoingRecord,rs[0].rec.id);r.nama_pembeli='Nama terkoreksi';await db.commit()
        elif ubah=='armada':await bk.koreksi_plat(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id,no_polisi='AD 9988 ZZ',alasan='Koreksi armada')
        elif ubah=='hapus_item':await bk.ubah_baris_perintah(db,jumlah=None,hapus=True,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id,item_id=rs[0].baris[1].id,dasar=body['dasar'],alasan='Hapus kosong')
    awal=await _items(pg);stok=await _stok(pg,gudang)
    with pytest.raises(HTTPException) as e:await _tutup(pg,gudang,body)
    assert e.value.status_code==409
    assert await _items(pg)==awal and await _stok(pg,gudang)==stok

@pytest.mark.parametrize('cacat',['pelanggan','kiriman','item_asing','item_kurang','item_ganda'])
async def test_server_memeriksa_hubungan_seluruh_item_dan_penerima(pg,gudang,cacat):
    rs=await _setup(pg,gudang);body=await _body(pg,rs[0]);u=await _u(pg,gudang)
    if cacat=='pelanggan':body['pelanggan_id']=rs[1].rec.pelanggan_id
    elif cacat=='kiriman':body['kiriman_id']+=1
    elif cacat=='item_asing':body['item_ids'][0]=rs[1].baris[0].id
    elif cacat=='item_kurang':body['item_ids'].pop()
    else:body['item_ids']=[body['item_ids'][0]]*2
    for fn in (layar.periksa,act_selesai_muat):
        with pytest.raises(HTTPException) as e:await fn(SelesaiMuatReq(**body),u)
        assert e.value.status_code==400
    async with pg() as db:assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'

async def test_dua_pelanggan_selesai_tiket_menyusul_alasan_terpisah_dan_tanpa_verifikasi(pg,gudang):
    rs=await _setup(pg,gudang)
    for r,sebab in zip(rs,['Kekurangan A','Kekurangan B']):await _tutup(pg,gudang,await _body(pg,r,sebab))
    async with pg() as db:
        k=(await layar.papan_selesai(db,rs[0].rec.id))['kiriman'][0]
        assert k['pelanggan_selesai']==2 and k['semua_selesai_muat']
        assert not k['terverifikasi'] and k['kesiapan']=='menunggu_tiket' and k['tiket'] is None
        assert k['total_dimuat_kg']==625 and k['total_tidak_terkirim_kg']==1225
        assert [p['penutupan']['alasan'] for p in k['pelanggan']]==['Kekurangan A','Kekurangan B']
        for r in rs:assert (await db.get(OutgoingRecord,r.rec.id)).diverifikasi_oleh is None

async def test_dua_operator_satu_snapshot_hanya_satu_audit_penutupan(pg,gudang):
    rs=await _setup(pg,gudang);body=await _body(pg,rs[0]);u=await _u(pg,gudang);stok=await _stok(pg,gudang)
    results=await asyncio.gather(*(act_selesai_muat(SelesaiMuatReq(**body),u) for _ in range(2)),return_exceptions=True)
    assert sum(isinstance(x,HTTPException) and x.status_code==409 for x in results)==1
    assert await _stok(pg,gudang)==stok
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_muat'))==1

async def test_gagal_audit_seluruh_penutupan_rollback_meski_pemanggil_commit(pg,gudang,monkeypatch):
    rs=await _setup(pg,gudang);u=await _u(pg,gudang);stok=await _stok(pg,gudang)
    async def gagal(*args,**kwargs):raise RuntimeError('Audit uji gagal')
    monkeypatch.setattr(bk,'_jejak',gagal)
    async with pg() as db:
        notif=await db.scalar(select(func.count()).select_from(Notification))
        with pytest.raises(RuntimeError):await bk.selesai_muat(db,user=u,rec_id=rs[0].rec.id,sebab='Kurang')
        await db.commit()
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'
        assert await db.scalar(select(func.count()).select_from(Notification))==notif
    assert await _stok(pg,gudang)==stok

async def test_pembatalan_penutupan_mempertahankan_aktual_dan_stok(pg,gudang):
    rs=await _setup(pg,gudang);awal=await _items(pg);stok=await _stok(pg,gudang)
    await _tutup(pg,gudang,await _body(pg,rs[0]));await _undo(pg,gudang['op'])
    assert await _items(pg)==awal and await _stok(pg,gudang)==stok
    async with pg() as db:
        p=(await layar.papan_selesai(db,rs[0].rec.id))['kiriman'][0]['pelanggan'][0]
        assert p['status']=='perintah' and p['penutupan'] is None
        logs=list((await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='barang_keluar_muat'))).all())
        assert logs[0].dibatalkan_pada is not None

async def test_http_g1_g2_saling_menggantikan_csrf_dan_konteks_dari_detail(pg,gudang):
    rs=await _setup(pg,gudang);c=await _klien(pg,gudang['op'],'selesai-lintas',mode='operator')
    async with c:
        for kode in ('g1','g2'):
            async with pg() as db:
                op=await db.get(User,gudang['op']);op.default_warehouse_id=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==kode));await db.commit()
            h=await c.get('/selesai-muat',params={'perintah':rs[0].rec.id});assert h.status_code==200,h.text
            assert 'data-boleh="1"' in h.text
            body=await _body(pg,rs[0]);preview=await c.post('/api/actions/periksa-selesai-muat',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
            assert preview.status_code==200,preview.text
        bad=await c.post('/api/actions/selesai-muat',json=body);assert bad.status_code==403
        # Payload tambahan tidak dapat menulis ulang aktual dari formulir penyelesaian.
        body.update(jumlah=9999,berat_kg=999999)
        awal=await _items(pg);stok=await _stok(pg,gudang)
        ok=await c.post('/api/actions/selesai-muat',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
        assert ok.status_code==200,ok.text
        assert await _items(pg)==awal and await _stok(pg,gudang)==stok
        detail=await c.get(f'/barang-keluar/{rs[0].rec.id}');assert detail.status_code==200
        assert f'/selesai-muat?perintah={rs[0].rec.id}&amp;buka=1' in detail.text
    async with pg() as db:
        op=await db.get(User,gudang['op']);op.default_warehouse_id=None;await db.commit()
    with pytest.raises(HTTPException) as e:await _tutup(pg,gudang,await _body(pg,rs[1]))
    assert e.value.status_code==403


@pytest.mark.parametrize('status,kesiapan',[('TERBUKA','menunggu_timbang_kedua'),('SELESAI','menunggu_pemeriksaan')])
async def test_tiket_dan_kesiapan_terpisah_dari_status_pelanggan(pg,gudang,status,kesiapan):
    rs=await _setup(pg,gudang)
    tid=await _tiket_armada(pg,gudang,rs,625)
    for r in rs:await _tutup(pg,gudang,await _body(pg,r))
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET status_tiket=:s WHERE id=:id'),{'s':status,'id':tid});await db.commit()
        k=(await layar.papan_selesai(db,rs[0].rec.id))['kiriman'][0]
        assert k['semua_selesai_muat'] and k['kesiapan']==kesiapan and not k['terverifikasi']
        assert k['tiket']['status_tiket']==status


async def test_pengambilan_jasa_menjaga_pemilik_stok_dan_item_asal(pg,gudang):
    from app.models import Jasa,FinishedGoodsStock
    from app.database import now_local
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    rs=await _setup(pg,gudang,False)
    async with pg() as db:
        jasa=Jasa(kode='JAS-SELESAI-UJI',pelanggan_id=rs[0].rec.pelanggan_id,status='berjalan');db.add(jasa);await db.flush()
        db.add(FinishedGoodsStock(product_sku_id=gudang['sku'],rice_quality_standard_id=gudang['std'],source_type='retur',jumlah_karung=10,berat_total_kg=250,input_by=gudang['op'],waktu=now_local(),jasa_id=jasa.id));await db.commit()
        r=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),jasa_id=jasa.id,baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=5)])
        await bk.catat_muatan(db,user=await db.get(User,gudang['op']),item_id=r.baris[0].id,jumlah_karung=3)
        saldo=await hitung_stok_finished_goods(db,gudang['sku'],gudang['std'],jasa_id=jasa.id)
        jid=jasa.id
    awal=await _items(pg);pabrik=await _stok(pg,gudang)
    await _tutup(pg,gudang,await _body(pg,r))
    assert await _items(pg)==awal and await _stok(pg,gudang)==pabrik
    async with pg() as db:
        sesudah=await hitung_stok_finished_goods(db,gudang['sku'],gudang['std'],jasa_id=jid)
        assert sesudah['kg']==saldo['kg']==175
        p=(await layar.papan_selesai(db,r.rec.id))['kiriman'][0]['pelanggan'][0]
        assert p['barang'][0]['jasa_id']==jid and p['pelanggan_id']==rs[0].rec.pelanggan_id
