"""Perintah Admin hanya menyatukan dua langkah administratif yang sudah sah."""
import asyncio
import uuid
from decimal import Decimal as D
import pytest
from sqlalchemy import select, func
from app.models import (User, PermintaanTransferBarang, PermintaanPk,
    TransferBarang, InternalTransfer, PengirimanPk, PkGudang2Intake,
    FinishedGoodsStock, ActivityLog, Silo, Notification)
from hmu_identitas import peran as P
from app.services import perintah_transfer as s, transfer_barang as barang, pengiriman_pk as pk
from tests.pg.test_transfer_barang import lokasi, world
from tests.pg.test_transfer_pk_multilokasi import antar_pabrik, pabrik
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio


def body(w, **kw):
    return dict(jenis='barang',sumber_id=str(w['source']),jumlah='20',
                asal_id=w['wh'],tujuan_id=w['target'],tujuan='gudang:'+str(w['target']),
                kunci=uuid.uuid4().hex,**kw)


async def buat(pg,w,req,user=None):
    async with pg() as db:
        return await s.buat(db,user=await db.get(User,user or w['user']),**req)


async def test_admin_sudah_boleh_meminta_dan_menyetujui_sendiri(pg,lokasi):
    w=lokasi
    async with pg() as db:
        u=await db.get(User,w['user'])
        out=await barang.minta(db,user=u,jenis='barang',id=str(w['source']),tujuan_id=w['target'],jumlah='20',kunci_kiriman=uuid.uuid4().hex)
        await barang.setujui_banyak(db,user=u,items=[dict(permintaan_id=-out['id'],berat_kg='20')])
        r=await db.get(PermintaanTransferBarang,-out['id'])
        assert r.diminta_oleh==r.disetujui_oleh==u.id and r.status=='disetujui'
        notes=(await db.scalars(select(Notification).where(Notification.table_name==r.__tablename__,Notification.record_id==r.id))).all()
        assert len(notes)==1 and notes[0].target_role==P.ADMIN and notes[0].pesan.startswith('Permintaan transfer')


@pytest.mark.parametrize('jenis,field,jumlah',[('barang','source','20'),('curah','broken','25.25'),('karung','pack','30')])
async def test_perintah_barang_disetujui_tanpa_transfer_dan_pemilik_tetap(pg,lokasi,jenis,field,jumlah):
    w=lokasi;req=body(w);req.update(jenis=jenis,sumber_id=str(w[field]),jumlah=jumlah)
    out=await buat(pg,w,req)
    async with pg() as db:
        r=await db.get(PermintaanTransferBarang,-out['id'])
        assert r.status=='disetujui' and r.jumlah_minta==r.jumlah_setuju==D(jumlah)
        assert r.diminta_oleh==r.disetujui_oleh==w['user']
        assert s.jenis_dokumen(r.kunci)=='perintah'
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==100
        assert await db.scalar(select(func.count()).select_from(TransferBarang))==0
        acts=set((await db.scalars(select(ActivityLog.aksi).where(ActivityLog.table_name=='permintaan_transfer_barang',ActivityLog.record_id==r.id))).all())
        assert {'transfer_barang_minta','transfer_barang_setujui','transfer_perintah'}<=acts
        notes=(await db.scalars(select(Notification).where(Notification.table_name==r.__tablename__,Notification.record_id==r.id))).all()
        assert not notes
    # Pelaksanaan tetap melewati penulis lama dan izin gudang asal.
    async with pg() as db:
        with pytest.raises(PermissionError):
            await barang.buat(db,user=await db.get(User,w['penerima']),items=[dict(permintaan_id=-out['id'],berat_kg=jumlah)],kunci_kiriman=uuid.uuid4().hex)
    async with pg() as db:
        await barang.buat(db,user=await db.get(User,w['operator']),items=[dict(permintaan_id=-out['id'],berat_kg=jumlah)],kunci_kiriman=uuid.uuid4().hex)
    again=await buat(pg,w,req)
    assert again['id']==out['id'] and again['ulang']


async def test_nonce_perintah_aman_balapan_dan_muatan_berbeda(pg,lokasi):
    w=lokasi;req=body(w)
    a,b=await asyncio.gather(buat(pg,w,req),buat(pg,w,req))
    assert a['id']==b['id'] and sorted([a['ulang'],b['ulang']])==[False,True]
    for changed in [dict(jumlah='21'),dict(asal_id=w['target']),dict(jenis='curah',sumber_id=str(w['broken']))]:
        with pytest.raises(ValueError,match='berbeda'):await buat(pg,w,{**req,**changed})
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PermintaanTransferBarang))==1
        assert await db.scalar(select(func.count()).select_from(TransferBarang))==0


@pytest.mark.parametrize('perubahan',[{'asal_id':1},{'tujuan':'silo:1'},{'jumlah':'101'},{'jumlah':'1.5'}])
async def test_perintah_barang_menolak_payload_tidak_sah_tanpa_dokumen(pg,lokasi,perubahan):
    w=lokasi;req=body(w)
    if 'asal_id' in perubahan:perubahan={'asal_id':w['target']}
    with pytest.raises(ValueError):await buat(pg,w,{**req,**perubahan})
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PermintaanTransferBarang))==0
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==100


async def gagal_lalu_ulang(pg,monkeypatch,req,user_id,module,M):
    original=module.setujui_banyak
    async def gagal(*args,**kw):
        await original(*args,**kw)
        raise ValueError('Persetujuan sengaja gagal setelah audit')
    monkeypatch.setattr(module,'setujui_banyak',gagal)
    async with pg() as db:
        with pytest.raises(ValueError,match='sengaja gagal'):
            await s.buat(db,user=await db.get(User,user_id),**req)
        # Bahkan caller yang menangkap galat lalu commit tidak menyisakan
        # permintaan/ACC, audit atau nonce yang setengah tersimpan.
        await db.commit()
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(M))==0
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name==M.__tablename__))==0
        assert await db.scalar(select(func.count()).select_from(Notification).where(Notification.table_name==M.__tablename__))==0
    monkeypatch.setattr(module,'setujui_banyak',original)
    async with pg() as db:
        assert not (await s.buat(db,user=await db.get(User,user_id),**req))['ulang']


async def test_persetujuan_barang_gagal_menghapus_permohonan_dan_nonce_dapat_diulang(pg,lokasi,monkeypatch):
    await gagal_lalu_ulang(pg,monkeypatch,body(lokasi),lokasi['user'],barang,PermintaanTransferBarang)


async def test_persetujuan_pk_gagal_menghapus_permohonan_dan_nonce_dapat_diulang(pg,antar_pabrik,monkeypatch):
    w=antar_pabrik
    async with pg() as db:asal=(await db.get(User,w['op1'])).default_warehouse_id
    req=dict(jenis='pk_giling',sumber_id=str(w['proses_id'])+'~0',jumlah='1000',asal_id=asal,
             tujuan_id=w['target'],tujuan='silo:'+str(w['silo_tujuan']),kunci=uuid.uuid4().hex)
    await gagal_lalu_ulang(pg,monkeypatch,req,w['admin'],pk,PermintaanPk)


@pytest.mark.parametrize('lokasi_tujuan',['gudang','silo'])
async def test_perintah_pk_memakai_acc_lama_tanpa_memindahkan_stok(pg,antar_pabrik,lokasi_tujuan):
    from app.services.transfer import saldo_pk
    w=antar_pabrik
    async with pg() as db:asal=(await db.get(User,w['op1'])).default_warehouse_id
    req=dict(jenis='pk_giling',sumber_id=str(w['proses_id'])+'~0',jumlah='1152',asal_id=asal,
             tujuan_id=w['target'],tujuan=lokasi_tujuan+':'+str(w['target'] if lokasi_tujuan=='gudang' else w['silo_tujuan']),kunci=uuid.uuid4().hex)
    async with pg() as db:out=await s.buat(db,user=await db.get(User,w['admin']),**req)
    async with pg() as db:
        r=await db.get(PermintaanPk,out['id'])
        assert r.status=='disetujui' and r.berat_setuju_kg==1152 and r.jasa_id is None
        assert r.tujuan_warehouse_id==w['target'] and r.silo_id==(w['silo_tujuan'] if lokasi_tujuan=='silo' else None)
        assert s.jenis_dokumen(r.kunci_transfer)=='perintah'
        notes=(await db.scalars(select(Notification).where(Notification.table_name==r.__tablename__,Notification.record_id==r.id))).all()
        assert len(notes)==1 and notes[0].target_role==P.OPERATOR
        assert notes[0].pesan.startswith('Perintah ') and 'siap dilaksanakan' in notes[0].pesan
        assert await saldo_pk(db,w['proses_id'])==6000
        for model in (InternalTransfer,PengirimanPk,PkGudang2Intake):
            assert await db.scalar(select(func.count()).select_from(model))==0
        again=await s.buat(db,user=await db.get(User,w['admin']),**req)
        assert again['ulang'] and again['id']==out['id']
        with pytest.raises(ValueError,match='berbeda'):
            await s.buat(db,user=await db.get(User,w['admin']),**{**req,'tujuan':'gudang:'+str(w['target']) if lokasi_tujuan=='silo' else 'silo:'+str(w['silo_tujuan'])})


@pytest.mark.parametrize('kesalahan',['gudang_salah','nonaktif','komoditas'])
async def test_perintah_pk_menolak_silo_yang_tidak_cocok(pg,antar_pabrik,kesalahan):
    from tests.pg.test_riwayat_giling import _klien
    w=antar_pabrik
    async with pg() as db:
        asal=(await db.get(User,w['op1'])).default_warehouse_id
        silo=await db.get(Silo,w['silo_tujuan'])
        if kesalahan=='nonaktif':silo.aktif=False
        elif kesalahan=='komoditas':silo.komoditas_diizinkan=['gabah']
        else:silo.warehouse_id=asal
        await db.commit()
    req=dict(jenis='pk_giling',sumber_id=str(w['proses_id'])+'~0',jumlah='1000',asal_id=asal,
             tujuan_id=w['target'],tujuan='silo:'+str(w['silo_tujuan']),kunci=uuid.uuid4().hex)
    async with pg() as db:
        with pytest.raises(ValueError):await s.buat(db,user=await db.get(User,w['admin']),**req)
        await db.commit()
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(PermintaanPk))==0
    async with await _klien(pg,peran='admin') as c:
        await c.get('/transfer-bertahap');headers={'x-csrf-token':cap_formulir(c)}
        r=await c.post('/api/transfer-barang/perintah',json=req,headers=headers)
        assert r.status_code==409,r.text


async def test_operator_ditolak_http_dan_metadata_client_tidak_dipercaya(pg,lokasi):
    from tests.pg.test_riwayat_giling import _klien
    w=lokasi;req=body(w)
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        await c.get('/transfer-bertahap');headers={'x-csrf-token':cap_formulir(c)}
        r=await c.post('/api/transfer-barang/perintah',json=req,headers=headers)
        assert r.status_code==403,r.text
    async with await _klien(pg,peran='admin') as c:
        await c.get('/transfer-bertahap');headers={'x-csrf-token':cap_formulir(c)}
        for tambahan in ('company_id','pabrik_id','pemilik_kunci'):
            r=await c.post('/api/transfer-barang/perintah',json={**req,tambahan:'palsu'},headers=headers)
            assert r.status_code==422,r.text
        r=await c.post('/api/transfer-barang/perintah',json=req,headers=headers)
        assert r.status_code==200,r.text
        assert r.json()['jenis_dokumen']=='perintah'


async def test_perintah_beda_perusahaan_tetap_ditolak(pg,lokasi):
    from hmu_core.organisasi import Perusahaan, LokasiPabrik, PenempatanGudang
    w=lokasi
    async with pg() as db:
        company=Perusahaan(kode='PERINTAH-LAIN',nama='Perusahaan lain');db.add(company);await db.flush()
        site=LokasiPabrik(company_id=company.id,kode='LAIN',nama='Pabrik lain');db.add(site);await db.flush()
        binding=await db.get(PenempatanGudang,w['target'])
        binding.company_id=company.id;binding.lokasi_pabrik_id=site.id;await db.commit()
    with pytest.raises(ValueError,match='satu perusahaan'):await buat(pg,w,body(w))
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(PermintaanTransferBarang))==0


async def test_perintah_pk_bentrok_permohonan_lama_rollback_dan_nonce_belum_terpakai(pg,antar_pabrik):
    from app.services import permintaan_pk
    w=antar_pabrik
    async with pg() as db:
        u=await db.get(User,w['op1']);asal=u.default_warehouse_id
        old=await barang.minta(db,user=u,jenis='pk_giling',id=str(w['proses_id'])+'~0',tujuan_id=w['target'],jumlah='1000',kunci_kiriman=uuid.uuid4().hex)
        notes=(await db.scalars(select(Notification).where(Notification.table_name=='permintaan_pk',Notification.record_id==old['id']))).all()
        assert len(notes)==1 and notes[0].target_role==P.ADMIN and notes[0].pesan.startswith('Permintaan transfer PK')
    req=dict(jenis='pk_giling',sumber_id=str(w['proses_id'])+'~0',jumlah='1000',asal_id=asal,
             tujuan_id=w['target'],tujuan='gudang:'+str(w['target']),kunci=uuid.uuid4().hex)
    async with pg() as db:
        with pytest.raises(ValueError,match='permintaan aktif'):
            await s.buat(db,user=await db.get(User,w['admin']),**req)
        await db.commit()
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PermintaanPk))==1
        assert (await db.get(PermintaanPk,old['id'])).status=='diminta'
        await permintaan_pk.tolak(db,user=await db.get(User,w['admin']),permintaan_id=old['id'],sebab='Diganti perintah setelah pemeriksaan Admin')
    async with pg() as db:
        out=await s.buat(db,user=await db.get(User,w['admin']),**req)
        assert not out['ulang'] and out['id']!=old['id']
