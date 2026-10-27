"""Satu timbang total; preview, sebab manual, sumber, audit dan akses lama."""
import asyncio
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import select,text,func
from app.models import User,OutgoingRecord,OutgoingItem,ActivityLog,KemasanTara,ProductSku
from app.services import barang_keluar as bk
from app.services import pemeriksaan_pengiriman as pemeriksaan
from app.web import verifikasi_pengiriman as layar
from app.web.aksi_inventory import VerifikasiKeluarReq,act_verifikasi_keluar
from tests.pg.test_barang_keluar import gudang,_stok,_perintah,_undo,_klien
from tests.pg.test_selesai_muatan import _setup as setup_muat
from tests.pg.test_kiriman_pelanggan import _tiket_armada
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio

async def _u(pg,g,key='adm'):
    async with pg() as db:return await db.get(User,g[key])

async def _setup(pg,g,delta=0,loading=False,tiket_dulu=False):
    rs=await setup_muat(pg,g)
    tid=await _tiket_armada(pg,g,rs,625+delta) if tiket_dulu else None
    for index,r in enumerate(rs):
        if loading and index==1:continue
        async with pg() as db:await bk.selesai_muat(db,user=await db.get(User,g['op']),rec_id=r.rec.id,sebab='Tidak terkirim '+str(index))
    if tid is None:tid=await _tiket_armada(pg,g,rs,625+delta)
    return rs,tid

async def _data(pg,r):
    async with pg() as db:return await layar.baca(db,r.rec.id)

async def _body(pg,r,cause=''):
    d=await _data(pg,r)
    return dict(perintah=str(d['perintah_id']),tiket=str(d['tiket']['id']) if d['tiket'] else None,
        dasar=d['dasar'],kiriman_id=d['kiriman_id'],perintah_ids=d['perintah_ids'],sebab_selisih=cause)

async def _save(pg,g,body):return await act_verifikasi_keluar(VerifikasiKeluarReq(**body),await _u(pg,g))

async def _items(pg):
    async with pg() as db:return list((await db.execute(select(OutgoingItem.id,OutgoingItem.berat_kg,
        OutgoingItem.jumlah_karung,OutgoingItem.product_sku_id,OutgoingItem.rice_quality_standard_id,
        OutgoingItem.jasa_id,OutgoingItem.outgoing_record_id).order_by(OutgoingItem.id))).all())

async def test_satu_total_tiket_setelah_tara_tidak_dipotong_ulang_dan_sebab_manual_opsional(pg,gudang):
    rs,tid=await _setup(pg,gudang,5)
    async with pg() as db:
        await db.execute(text('''UPDATE timbangan_transaksi SET netto_timbangan_kg=633,total_tara_kg=3,tara_lain_kg=.2,
            berat_barang_kg=630,berat_kosong_kg=9000,berat_bermuatan_kg=9633,timbang1_kg=9000,timbang2_kg=9633 WHERE id=:id'''),{'id':tid});await db.commit()
    d=await _data(pg,rs[1])
    assert d['jumlah_pelanggan']==2 and d['jumlah_item']==4
    assert d['total_aktual_kg']==625 and d['berat_tiket_kg']==630 and d['selisih_kg']==5
    assert d['tiket']['tara_karung_kg']==2.8 and d['tiket']['total_tara_kg']==3
    assert d['batas_otomatis_kg']==1.25 and d['ambang_manual_kg']==100 and not d['sebab_wajib']
    assert 'melewati batas verifikasi otomatis' in d['catatan_otomatis'] and d['boleh_manual']
    assert [p['total_dimuat_kg'] for p in d['pelanggan']]==[500,125]
    awal=await _items(pg);stok=await _stok(pg,gudang)
    await _save(pg,gudang,await _body(pg,rs[0]))
    assert await _items(pg)==awal and await _stok(pg,gudang)==stok
    latest=await _data(pg,rs[0]);assert latest['terverifikasi'] and len(latest['jejak'])==2
    assert all(j['metode']=='manual' for j in latest['jejak'])

@pytest.mark.parametrize('delta,lulus',[(1.25,True),(-1.25,True),(1.251,False),(-1.251,False)])
async def test_batas_auto_tepat_dan_pelaksana_asli_tidak_menjadi_admin(pg,gudang,delta,lulus):
    rs,tid=await _setup(pg,gudang,delta);d=await _data(pg,rs[0]);stok=await _stok(pg,gudang)
    async with pg() as db:
        if lulus:await bk.verifikasi(db,user=await db.get(User,gudang['op']),rec_id=rs[0].rec.id,timbangan_transaksi_id=tid,otomatis=True,sidik_sumber=d['sidik_sumber'])
        else:
            with pytest.raises(bk.VerifikasiOtomatisDitahan):await bk.verifikasi(db,user=await db.get(User,gudang['op']),rec_id=rs[0].rec.id,timbangan_transaksi_id=tid,otomatis=True,sidik_sumber=d['sidik_sumber'])
    d=await _data(pg,rs[0]);assert d['terverifikasi']==lulus
    if lulus:
        op=await _u(pg,gudang,'op');assert d['status']=='Terverifikasi otomatis'
        assert all(j['metode']=='otomatis' and j['pelaksana']==op.nama and j['waktu'] for j in d['jejak'])
    else:assert d['boleh_manual'] and not d['sebab_wajib']
    assert await _stok(pg,gudang)==stok

@pytest.mark.parametrize('cause',['','  ','\n\t'])
async def test_selisih_besar_wajib_sebab_bukan_spasi(pg,gudang,cause):
    rs,_=await _setup(pg,gudang,101);d=await _data(pg,rs[0]);assert d['sebab_wajib']
    body=await _body(pg,rs[0],cause)
    with pytest.raises(HTTPException) as e:await _save(pg,gudang,body)
    assert e.value.status_code==400 and 'tulis sebab' in str(e.value.detail).lower()
    async with pg() as db:assert all(r.status=='dimuat' for r in (await db.scalars(select(OutgoingRecord))).all())

async def test_sebab_besar_terpisah_dari_tidak_terkirim_dan_tersimpan_di_audit(pg,gudang):
    rs,_=await _setup(pg,gudang,101);body=await _body(pg,rs[0],'Timbangan berbeda setelah pemeriksaan')
    await _save(pg,gudang,body);d=await _data(pg,rs[0])
    assert [p['penutupan']['alasan'] for p in d['pelanggan']]==['Tidak terkirim 0','Tidak terkirim 1']
    assert all(j['sebab_selisih']==body['sebab_selisih'] for j in d['jejak'])
    async with pg() as db:
        logs=list((await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='barang_keluar_verifikasi'))).all())
        assert len(logs)==2 and all(x.alasan_perubahan==body['sebab_selisih'] for x in logs)

@pytest.mark.parametrize('invalid',['belum_selesai','batal','tutup_paksa','arah','dipakai_lain'])
async def test_tiket_tidak_sah_dan_dipakai_perjalanan_lain_ditolak(pg,gudang,invalid):
    rs,tid=await _setup(pg,gudang)
    async with pg() as db:
        if invalid=='belum_selesai':await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='TERBUKA' WHERE id=:id"),{'id':tid})
        elif invalid=='batal':await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi='DIBATALKAN' WHERE id=:id"),{'id':tid})
        elif invalid=='tutup_paksa':await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='DITUTUP_PAKSA' WHERE id=:id"),{'id':tid})
        elif invalid=='arah':await db.execute(text("UPDATE timbangan_transaksi SET arah='MASUK' WHERE id=:id"),{'id':tid})
        await db.commit()
    if invalid=='dipakai_lain':
        other=await _perintah(pg,gudang,karung=5,pembeli='Pihak lain')
        async with pg() as db:
            await db.execute(text('UPDATE outgoing_records SET timbangan_transaksi_id=:tid WHERE id=:id'),{'tid':tid,'id':other.rec.id});await db.commit()
    d=await _data(pg,rs[0]);assert not d['boleh_manual'] and d['halangan']
    with pytest.raises(HTTPException):await _save(pg,gudang,await _body(pg,rs[0],'Periksa'))

async def test_pelanggan_belum_selesai_muat_memblokir_verifikasi_seluruh_kiriman(pg,gudang):
    rs,_=await _setup(pg,gudang,loading=True);d=await _data(pg,rs[0])
    assert d['pelanggan_selesai']==1 and not d['boleh_manual']
    with pytest.raises(HTTPException):await _save(pg,gudang,await _body(pg,rs[0]))
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='dimuat'
        assert (await db.get(OutgoingRecord,rs[1].rec.id)).status=='perintah'

async def test_tiket_lama_netto_dan_pengiriman_kecil_tanpa_tiket_tetap_sah(pg,gudang):
    rs,tid=await _setup(pg,gudang)
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET berat_barang_kg=NULL,netto_timbangan_kg=625,total_tara_kg=5 WHERE id=:id'),{'id':tid});await db.commit()
    d=await _data(pg,rs[0]);assert d['sumber_berat']=='netto_kompatibilitas' and d['berat_tiket_kg']==625
    assert d['tiket']['berat_barang_kg'] is None and 'belum lengkap' in d['catatan_otomatis']
    await _save(pg,gudang,await _body(pg,rs[0]))
    small=await _perintah(pg,gudang,karung=4,pembeli='Kecil')
    async with pg() as db:await bk.muat_semua(db,user=await db.get(User,gudang['op']),rec_id=small.rec.id)
    d=await _data(pg,small);assert d['tiket'] is None and d['berat_tiket_kg'] is None and d['boleh_manual']
    await _save(pg,gudang,await _body(pg,small));assert (await _data(pg,small))['terverifikasi']

@pytest.mark.parametrize('ubah',['aktual','penerima','tara_master','berat_tiket','status','alasan_tidak_terkirim'])
async def test_sumber_berubah_menolak_snapshot_lama_tanpa_mengubah_catatan(pg,gudang,ubah):
    rs,tid=await _setup(pg,gudang,tiket_dulu=ubah=='alasan_tidak_terkirim')
    body=await _body(pg,rs[0],'Catatan Admin tetap')
    async with pg() as db:
        if ubah=='aktual':
            it=await db.get(OutgoingItem,rs[0].baris[0].id);it.berat_kg+=25;it.jumlah_karung+=1
        elif ubah=='penerima':r=await db.get(OutgoingRecord,rs[1].rec.id);r.nama_pembeli='Nama penerima diperbarui'
        elif ubah=='tara_master':
            sku=await db.get(ProductSku,gudang['sku']);tara=await db.scalar(select(KemasanTara).where(KemasanTara.packaging_material_id==sku.packaging_material_id,KemasanTara.package_size_id==sku.package_size_id))
            if tara:tara.tara_per_karung_kg+=Decimal('.01')
            else:db.add(KemasanTara(packaging_material_id=sku.packaging_material_id,package_size_id=sku.package_size_id,tara_per_karung_kg=Decimal('.13')))
        elif ubah=='berat_tiket':await db.execute(text('UPDATE timbangan_transaksi SET berat_barang_kg=626 WHERE id=:id'),{'id':tid})
        elif ubah=='status':r=await db.get(OutgoingRecord,rs[1].rec.id);r.status='perintah'
        elif ubah=='alasan_tidak_terkirim':
            await _undo(pg,gudang['op'])
            await bk.selesai_muat(db,user=await db.get(User,gudang['op']),rec_id=rs[1].rec.id,sebab='Alasan tidak terkirim dikoreksi')
        await db.commit()
    stok=await _stok(pg,gudang)
    with pytest.raises(HTTPException) as e:await _save(pg,gudang,body)
    assert e.value.status_code==409 and body['sebab_selisih']=='Catatan Admin tetap'
    assert await _stok(pg,gudang)==stok

async def test_otomatis_mendahului_admin_dan_buka_hasil_tidak_menambah_audit(pg,gudang):
    rs,tid=await _setup(pg,gudang);body=await _body(pg,rs[0]);d=await _data(pg,rs[0])
    async with pg() as db:await bk.verifikasi(db,user=await db.get(User,gudang['op']),rec_id=rs[0].rec.id,timbangan_transaksi_id=tid,otomatis=True,sidik_sumber=d['sidik_sumber'])
    with pytest.raises(HTTPException) as e:await _save(pg,gudang,body)
    assert e.value.status_code==409
    for _ in range(3):assert (await _data(pg,rs[0]))['terverifikasi']
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_verifikasi'))==2

async def test_dua_permohonan_sama_hanya_satu_transaksi_dan_undo_tidak_mengubah_stok(pg,gudang):
    rs,_=await _setup(pg,gudang);body=await _body(pg,rs[0]);u=await _u(pg,gudang);awal=await _items(pg);stok=await _stok(pg,gudang)
    hasil=await asyncio.gather(*(act_verifikasi_keluar(VerifikasiKeluarReq(**body),u) for _ in range(2)),return_exceptions=True)
    assert sum(isinstance(r,HTTPException) and r.status_code==409 for r in hasil)==1
    assert await _items(pg)==awal and await _stok(pg,gudang)==stok
    await _undo(pg,gudang['adm'])
    async with pg() as db:
        assert all(r.status=='dimuat' and r.timbangan_transaksi_id is None for r in (await db.scalars(select(OutgoingRecord))).all())
    assert await _items(pg)==awal and await _stok(pg,gudang)==stok

async def test_audit_gagal_tidak_meninggalkan_pelanggan_terverifikasi_sebagian(pg,gudang,monkeypatch):
    rs,_=await _setup(pg,gudang);body=await _body(pg,rs[0]);old=bk._jejak;counter=0
    async def gagal_kedua(*args,**kw):
        nonlocal counter
        counter+=1
        if counter==2:raise RuntimeError('Audit kedua gagal')
        return await old(*args,**kw)
    monkeypatch.setattr(bk,'_jejak',gagal_kedua)
    async with pg() as db:
        with pytest.raises(RuntimeError):await bk.verifikasi(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id,dasar=body['dasar'])
        await db.commit()
    async with pg() as db:
        assert all(r.status=='dimuat' for r in (await db.scalars(select(OutgoingRecord))).all())
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_verifikasi'))==0

async def test_http_hak_manual_csrf_konteks_dan_kompatibilitas_payload_lama(pg,gudang):
    rs,_=await _setup(pg,gudang);op=await _klien(pg,gudang['op'],'verifikasi-op',mode='operator')
    async with op:
        assert (await op.get('/verifikasi-pengiriman',params={'perintah':rs[0].rec.id})).status_code==403
        assert (await op.get('/api/actions/pratinjau-muat',params={'tujuan':'verifikasi','perintah':rs[0].rec.id})).status_code==403
        r=await op.post('/api/actions/verifikasi-keluar',json=await _body(pg,rs[0]),headers={'X-CSRF-Token':cap_formulir(op)});assert r.status_code==403
    c=await _klien(pg,gudang['adm'],'verifikasi-adm')
    async with c:
        r=await c.get('/verifikasi-pengiriman',params={'perintah':rs[0].rec.id});assert r.status_code==200,r.text
        r=await c.get('/api/actions/pratinjau-muat',params={'tujuan':'verifikasi','perintah':rs[0].rec.id});assert r.status_code==200,r.text
        assert 'harga_per_kg' not in r.text and 'hpp' not in r.text
        body=await _body(pg,rs[0]);bad=await c.post('/api/actions/verifikasi-keluar',json=body);assert bad.status_code==403
        body['perintah_ids']=[rs[0].rec.id]
        r=await c.post('/api/actions/verifikasi-keluar',json=body,headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==400,r.text
        # Pemanggil lama masih sah; endpoint tidak dipaksa memakai field baru.
        r=await c.post('/api/actions/verifikasi-keluar',json={'perintah':str(rs[0].rec.id)},headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==200,r.text


@pytest.mark.parametrize('aktual,delta,auto,manual,wajib',[(500,5,1,100,False),(10000,200,20,200,False),(10000,200.01,20,200,True),(20000,-401,40,400,True)])
async def test_dua_ambang_dari_aturan_server_sama_dengan_pemeriksaan(aktual,delta,auto,manual,wajib):
    d=bk.angka_verifikasi(aktual,aktual+delta)
    assert d['batas_otomatis_kg']==auto and d['ambang_manual_kg']==manual and d['sebab_wajib']==wajib


async def test_catatan_manual_tidak_bisa_menyamar_sebagai_audit_otomatis(pg,gudang):
    rs,_=await _setup(pg,gudang)
    await _save(pg,gudang,await _body(pg,rs[0],'Verifikasi otomatis: ini catatan manual Admin'))
    d=await _data(pg,rs[0]);assert d['terverifikasi'] and d['status']!='Terverifikasi otomatis'
    assert all(j['metode']=='manual' for j in d['jejak'])

@pytest.mark.parametrize('view',['operator:g1','operator:g2'])
async def test_admin_lihat_sebagai_operator_tidak_mendapat_hak_manual(pg,gudang,view):
    rs,_=await _setup(pg,gudang);c=await _klien(pg,gudang['adm'],'admin-view-verifikasi')
    async with c:
        await c.get('/verifikasi-pengiriman',params={'perintah':rs[0].rec.id})
        c.cookies.set('produksi_lihat',view,domain='uji.local')
        page=await c.get('/verifikasi-pengiriman',params={'perintah':rs[0].rec.id});assert page.status_code==403,page.text
        r=await c.post('/api/actions/verifikasi-keluar',json=await _body(pg,rs[0]),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==403,r.text
