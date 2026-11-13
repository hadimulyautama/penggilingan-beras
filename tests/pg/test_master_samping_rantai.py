"""Jenis baru mengikuti penerimaan, saldo, silo, proses dan reservasi nyata."""
import pytest
from sqlalchemy import select,func
from app.database import now_local
from app.models import User,ByproductStock,PolishingOutputLog,PolishingProcess,HasilSampingKeSilo,Silo
from app.services import jenis_hasil_samping as hs,stok,barang_keluar as bk
from app.penggilingan.gudang2 import service as g2,polishing as p
from tests.pg.test_masukkan_beras_silo import sosoh
from tests.pg.test_tiket_produk_sekali import tiket,masuk
from tests.pg.test_barang_keluar import _klien,_pelanggan

pytestmark=pytest.mark.asyncio

async def tambah(db,u,nama='Hasil master <uji>'):
    kode=await hs.simpan(db,user=u,aksi='tambah',nama=nama,bentuk='karung',kg_karung='37')
    await db.commit();return kode

@pytest.mark.parametrize('jasa',[False,True])
@pytest.mark.fondasi_multi
async def test_penerimaan_tepat_sekali_silo_proses_pemilik(pg,sosoh,jasa):
    async with pg() as db:
        kode=await tambah(db,await db.get(User,sosoh['user']))
    tid=await tiket(pg,kind=kode.upper()+'_MASUK',kode='MSK-HS-BARU',jasa=jasa)
    async with await _klien(pg,sosoh['user'],'master-samping',mode='admin') as c:
        menu=(await c.get('/api/actions/menu')).json()
        assert next(a for a in menu if a['id']=='masukkan_samping_'+kode)['boleh']
        assert any(a['id']=='terima_samping_'+kode for a in menu)
        assert (await masuk(c,tid)).status_code==200
        async with pg() as db:
            raw=await db.scalar(select(ByproductStock).where(ByproductStock.source_id==tid,ByproductStock.source_type=='timbangan'))
            owner=raw.jasa_id;rid=raw.id
            assert bool(owner)==jasa and raw.berat_kg==998
            picker=await c.get('/api/actions/hasil-samping-pemilik-tersedia',params={'jenis':kode})
            assert picker.status_code==200 and any(x['value']==(str(owner) if owner else 'pabrik') for x in picker.json()),picker.text
            u=await db.get(User,sosoh['user'])
            card=next(k for k in await stok.stok_produk(db,jasa_id=owner) if k.jenis==kode)
            assert card.sisa_kg==998 and card.jumlah_karung_otomatis==26 and card.curah_otomatis_kg==36
            # Seed default allowlist remains compatible with newly configured kinds.
            silo=await db.get(Silo,sosoh['silo_beras']);silo.komoditas_diizinkan=['pk','beras_putih','reject','broken','menir'];await db.commit()
            await g2.masukkan_hasil_samping_ke_silo(db,user=u,jenis=kode,jasa_id=owner,nama_silo='C',berat_kg=998)
            move=await db.scalar(select(HasilSampingKeSilo).where(HasilSampingKeSilo.byproduct_stock_id==rid))
            assert move.polishing_process_id is None and move.berat_kg==998
            assert await g2.hitung_stok_silo(db,silo.id)==998
            assert next(k for k in await stok.stok_produk(db,jasa_id=owner) if k.jenis==kode).sisa_kg==0
            with pytest.raises(g2.Gudang2Error):
                await g2.masukkan_hasil_samping_ke_silo(db,user=u,jenis=kode,jasa_id=owner,nama_silo='C',berat_kg=1)
            await db.rollback()
            u=await db.get(User,sosoh['user'])
            start=await p.mulai_penyosohan(db,user=u,nama_silos=['C'])
            assert start.proc.jasa_id==owner and start.berat_awal_total==998
            from app.services.koreksi_bahan_berjalan import konteks_curah
            from app.models import PolishingSiloUsage
            usages=(await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==start.proc.id))).all()
            entries,sources=await konteks_curah(db,start.proc,usages)
            assert entries[0]['sumber']==f'samping:{kode}:stok:{rid}'
            assert sources[entries[0]['sumber']]['bebas']==0
            await p.catat_output(db,user=u,kode=start.proc.kode_proses,jenis='medium',berat_kumulatif=900)
            await p.catat_output(db,user=u,kode=start.proc.kode_proses,jenis=kode,berat_kumulatif=49)
            await p.selesai_penyosohan(db,user=u,kode=start.proc.kode_proses,nama_silo='C',sisa_kg=48)
            result=await p.akhiri_penyosohan(db,user=u,kode=start.proc.kode_proses)
            assert result.pk_terpakai_total==950 and result.beras_total==900
            assert next(k for k in await stok.stok_produk(db,jasa_id=owner) if k.jenis==kode).sisa_kg==49
        assert (await masuk(c,tid)).status_code==409
        assert (await c.get(f'/barang-masuk/{tid}')).status_code==200
        assert (await c.get('/barang-masuk')).status_code==200

async def test_reservasi_hasil_baru_mengikat_silo_dan_tetap_pisah_pemilik(pg,sosoh):
    pid=await _pelanggan(pg,'Penerima hasil master')
    async with pg() as db:
        u=await db.get(User,sosoh['user']);kode=await tambah(db,u)
        db.add(PolishingOutputLog(polishing_process_id=sosoh['proc_id'],jenis=kode,berat_kg=998,waktu_update=now_local(),input_by=u.id));await db.commit()
        order=await bk.buat_perintah(db,user=u,baris=[bk.BarisPerintah(tipe='byproduct_curah',jenis=kode,berat_kg=100)],pelanggan_id=pid,no_polisi='B 4321 UJ')
        with pytest.raises(g2.Gudang2Error):
            await g2.masukkan_hasil_samping_ke_silo(db,user=u,jenis=kode,jasa_id=None,nama_silo='C',berat_kg=899)
        await db.rollback()
        u=await db.get(User,sosoh['user'])
        await g2.masukkan_hasil_samping_ke_silo(db,user=u,jenis=kode,jasa_id=None,nama_silo='C',berat_kg=898)
        assert (await bk.tersedia(db,bk.BarisPerintah(tipe='byproduct_curah',jenis=kode)))[0]==0
        assert next(k for k in await stok.stok_produk(db) if k.jenis==kode).sisa_kg==100
        assert not any(k.jenis==kode for k in await stok.stok_produk(db,jasa_id=999))

async def test_silo_khusus_tetap_menolak_jenis_lain(pg,sosoh):
    async with pg() as db:
        u=await db.get(User,sosoh['user']);kode=await tambah(db,u)
        db.add(PolishingOutputLog(polishing_process_id=sosoh['proc_id'],jenis=kode,berat_kg=100,waktu_update=now_local(),input_by=u.id))
        silo=await db.get(Silo,sosoh['silo_beras']);silo.komoditas_diizinkan=['pk'];await db.commit()
        with pytest.raises(g2.Gudang2Error,match='tidak diizinkan|hanya menerima|tidak menerima'):
            await g2.masukkan_hasil_samping_ke_silo(db,user=u,jenis=kode,jasa_id=None,nama_silo='C',berat_kg=50)
        await db.rollback()
        assert not await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))

async def test_hasil_baru_retur_dan_kemas_ulang_mengikuti_master_kemasan(pg,sosoh):
    from app.services import retur
    from app.penggilingan.inventory.packaging import find_or_create_sku
    async with pg() as db:
        u=await db.get(User,sosoh['user']);kode=await tambah(db,u)
        data=await retur.katalog(db)
        assert kode in data['jenis'] and data['jenis'][kode]=='Hasil master <uji>'
        assert any(x['nilai']=='putih:50' for x in data['kemasan'][kode])
        sku=await find_or_create_sku(db,kategori=kode,material_kode='putih',ukuran=50)
        rows=await retur.siapkan_muatan(db,[(sku.id,None,2,100,'',0)])
        assert rows[0]['berat_kg']=='100' and rows[0]['nama'].startswith('Hasil master <uji>')

@pytest.mark.parametrize('jenis',['menir','reject','bekatul'])
async def test_penerimaan_jenis_bawaan_masuk_silo_dengan_replay_aman(pg,sosoh,jenis):
    from uuid import uuid4
    from tests.pg.formulir import cap_formulir
    tid=await tiket(pg,kind=jenis.upper()+'_MASUK',kode='MSK-SAMPING-BAWAAN')
    async with await _klien(pg,sosoh['user'],'samping-bawaan',mode='admin') as c:
        assert (await masuk(c,tid)).status_code==200
        picker=await c.get('/api/actions/hasil-samping-pemilik-tersedia',params={'jenis':jenis})
        assert picker.status_code==200 and any(x['value']=='pabrik' for x in picker.json()),picker.text
        body=dict(pemilik='pabrik',silo='C',berat_kg=998,kunci_kiriman=uuid4().hex)
        path='/api/actions/masukkan-hasil-samping-silo/'+jenis
        for _ in range(2):
            result=await c.post(path,json=body,headers={'X-CSRF-Token':cap_formulir(c)})
            assert result.status_code==200,result.text
        assert (await masuk(c,tid)).status_code==409
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,sosoh['silo_beras'])==998
        assert await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))==1
