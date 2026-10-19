"""Selesai proses bukan pernyataan bahwa seluruh silo sudah kosong."""
import pytest
from sqlalchemy import select
from app.models import User,MillingProcess,Silo,SiloStorage,MillingProcessSource
from app.penggilingan.gudang1.services import milling as m
from app.penggilingan.gudang1.services.silo import _silo_content_bobot
from tests.pg.test_pembebasan_silo_giling import dunia
from tests.pg.test_gudang2_operator_pg import gudang2
pytestmark=pytest.mark.asyncio


async def test_selesai_giling_menolak_silo_belum_diperiksa_tanpa_mengubah_angka(pg,dunia):
    async with pg() as db:
        u=await db.get(User,dunia['user'])
        p=await m.get_process_by_kode(db,dunia['kode_proses'])
        with pytest.raises(m.MillingError,match='sisa'):
            await m.finish_milling(db,user=u,kode_proses=p.kode_proses,berat_akhir=9000)
        assert p.status=='proses' and p.waktu_selesai is None
        for sid in dunia['silo'].values():
            assert (await db.get(Silo,sid)).status=='terisi'
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==10000
        assert (await _silo_content_bobot(db,dunia['silo']['B'])).kg==6000


async def test_sisa_giling_tetap_isi_silo_selesai_dan_undo_tidak_memulihkan_bahan_terpakai(pg,dunia):
    from app.services.undo import _undo_finish_milling
    async with pg() as db:
        u=await db.get(User,dunia['user']);kode=dunia['kode_proses']
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='A',sisa_kg=500)
        assert (await db.get(Silo,dunia['silo']['A'])).status=='terisi'
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==500
        with pytest.raises(m.MillingError,match='sisa'):
            await m.finish_milling(db,user=u,kode_proses=kode,berat_akhir=9000)
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='B',sisa_kg=0)
        hasil=await m.finish_milling(db,user=u,kode_proses=kode,berat_akhir=9000)
        assert hasil.proc.status=='selesai'
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==500
        assert (await db.get(Silo,dunia['silo']['A'])).status=='terisi'
        assert (await db.get(Silo,dunia['silo']['B'])).status=='kosong'
        await _undo_finish_milling(db,hasil.proc.id);await db.commit()
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==500
        assert (await db.get(Silo,dunia['silo']['B'])).status=='kosong'
        assert all(s.berat_akhir_kg is not None for s in (await db.scalars(select(MillingProcessSource))).all())


async def test_sisa_dipakai_proses_baru_tanpa_menggandakan_berat_dan_sinkronisasi(pg,dunia):
    async with pg() as db:
        u=await db.get(User,dunia['user']);kode=dunia['kode_proses']
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='A',sisa_kg=500)
        kedua=await m.start_milling(db,user=u,nama_silo='A')
        assert kedua.berat_masuk==500
        await m.resinkron_bahan_berjalan(db)
        pertama=await m.get_process_by_kode(db,kode)
        assert float(pertama.berat_gabah_masuk_kg)==16000
        assert float(kedua.proc.berat_gabah_masuk_kg)==500
        await m.tutup_silo_giling(db,user=u,kode_proses=kedua.proc.kode_proses,nama_silo='A',sisa_kg=200)
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==200
        await m.resinkron_bahan_berjalan(db)
        assert float(pertama.berat_gabah_masuk_kg)==16000 and float(kedua.proc.berat_gabah_masuk_kg)==500


async def test_sosoh_selesai_menunggu_pemeriksaan_sisa_dan_tidak_mengosongkan_sisa(pg,gudang2):
    from app.penggilingan.gudang2.polishing import mulai_penyosohan,catat_output,akhiri_penyosohan,selesai_penyosohan
    from app.penggilingan.gudang2.service import hitung_stok_silo,get_g2_silo,Gudang2Error
    async with pg() as db:
        u=gudang2['user'];p=(await mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
        await catat_output(db,user=u,kode=p.kode_proses,jenis='medium',berat_kumulatif=500)
        with pytest.raises(Gudang2Error,match='sisa'):
            await akhiri_penyosohan(db,user=u,kode=p.kode_proses)
        assert p.status=='proses' and p.waktu_selesai is None
        with pytest.raises(Gudang2Error,match='Isi sisa'):
            await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=None)
        await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=500)
        silo=await get_g2_silo(db,'B')
        assert await hitung_stok_silo(db,silo.id)==500 and silo.status=='terisi'
        await akhiri_penyosohan(db,user=u,kode=p.kode_proses)
        assert await hitung_stok_silo(db,silo.id)==500 and silo.status=='terisi'

@pytest.mark.parametrize('sisa',[None,-1,float('nan'),float('inf'),10001])
async def test_giling_sisa_kosong_atau_tidak_sah_tidak_mengubah_silo(pg,dunia,sisa):
    async with pg() as db:
        u=await db.get(User,dunia['user'])
        with pytest.raises(m.MillingError):
            await m.tutup_silo_giling(db,user=u,kode_proses=dunia['kode_proses'],nama_silo='A',sisa_kg=sisa)
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==10000
        assert all(s.berat_akhir_kg is None for s in (await db.scalars(select(MillingProcessSource))).all())

async def test_giling_dua_operator_dan_konfirmasi_basi_tidak_menimpa_sisa(pg,dunia):
    import asyncio
    from app.services.penyelesaian_proses import ringkasan_bebaskan
    kode=dunia['kode_proses']
    async with pg() as db:
        dasar=(await ringkasan_bebaskan(db,jenis='giling',kode=kode,silo='A',sisa=0))['dasar']
    async def kirim():
        async with pg() as db:
            try:
                await m.tutup_silo_giling(db,user=await db.get(User,dunia['user']),kode_proses=kode,nama_silo='A',sisa_kg=0,dasar=dasar)
                return 'ok'
            except m.MillingError:
                await db.rollback();return 'ditolak'
    assert sorted(await asyncio.gather(kirim(),kirim()))==['ditolak','ok']
    async with pg() as db:
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==0
        from app.models import PurchaseBatch
        from app.database import now_local
        from datetime import date
        asal=await db.scalar(select(PurchaseBatch).limit(1))
        batch=PurchaseBatch(kode_batch='GB-SIKLUS-BARU',supplier_id=asal.supplier_id,
            berat_total_kg=300,kondisi_gabah='kering',tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(),input_by=dunia['user'],flag_unverified=False,
            sumber_berat='timbangan',status_batch='di_silo')
        db.add(batch);await db.flush()
        db.add(SiloStorage(silo_id=dunia['silo']['A'],purchase_batch_id=batch.id,
            tipe_masuk='langsung_kering',tanggal_masuk=now_local(),input_by=dunia['user'],status='terisi'))
        await db.commit()
        await m.tambah_silo_giling(db,user=await db.get(User,dunia['user']),kode_proses=kode,nama_silo=['A'])
        with pytest.raises(m.MillingError,match='berubah'):
            await m.tutup_silo_giling(db,user=await db.get(User,dunia['user']),kode_proses=kode,nama_silo='A',sisa_kg=0,dasar=dasar)
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==300

async def test_sosoh_siklus_baru_menolak_konfirmasi_sisa_lama(pg,gudang2):
    from app.penggilingan.gudang2.polishing import mulai_penyosohan,selesai_penyosohan,tambah_silo_penyosohan
    from app.penggilingan.gudang2.service import Gudang2Error,hitung_stok_silo,get_g2_silo
    from app.services.penyelesaian_proses import ringkasan_bebaskan
    async with pg() as db:
        u=gudang2['user'];p=(await mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
        dasar=(await ringkasan_bebaskan(db,jenis='sosoh',kode=p.kode_proses,silo='B',sisa=500))['dasar']
        await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=500,dasar=dasar)
        await tambah_silo_penyosohan(db,user=u,kode=p.kode_proses,nama_silos=['B'])
        with pytest.raises(Gudang2Error,match='berubah'):
            await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=500,dasar=dasar)
        silo=await get_g2_silo(db,'B')
        assert await hitung_stok_silo(db,silo.id)==500 and silo.status=='terisi'

async def test_undo_giling_tidak_merebut_sisa_yang_sudah_dipakai_proses_lain(pg,dunia):
    from app.services.undo import _undo_finish_milling
    async with pg() as db:
        u=await db.get(User,dunia['user']);kode=dunia['kode_proses']
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='A',sisa_kg=500)
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='B',sisa_kg=0)
        awal=await m.finish_milling(db,user=u,kode_proses=kode,berat_akhir=9000)
        baru=await m.start_milling(db,user=u,nama_silo='A')
        await _undo_finish_milling(db,awal.proc.id);await db.commit()
        st=await db.scalar(select(SiloStorage).where(SiloStorage.silo_id==dunia['silo']['A']))
        assert st.milling_process_id==baru.proc.id and st.status=='terisi'
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==500

async def test_pembatalan_selesai_lama_tidak_mengisi_silo_tanpa_bukti(pg,dunia):
    from app.services.undo import _undo_finish_milling,UndoError
    async with pg() as db:
        proc=await m.get_process_by_kode(db,dunia['kode_proses'])
        proc.status='selesai';await db.commit()
        with pytest.raises(UndoError,match='Penyelesaian lama'):
            await _undo_finish_milling(db,proc.id)
        assert proc.status=='selesai'
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==10000

@pytest.mark.parametrize('kelas',['TutupSiloGilingReq','SelesaiPenyosohanReq'])
async def test_api_membedakan_sisa_kosong_dan_nol(kelas):
    from app.web import api
    from pydantic import ValidationError
    req=getattr(api,kelas)
    with pytest.raises(ValidationError):req(kode_proses='UJI',sisa=None)
    with pytest.raises(ValidationError):req(kode_proses='UJI')
    assert req(kode_proses='UJI',sisa=0).sisa==0

async def test_hasil_giling_tidak_boleh_melebihi_bahan_setelah_sisa_dikurangkan(pg,dunia):
    async with pg() as db:
        u=await db.get(User,dunia['user']);kode=dunia['kode_proses']
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='A',sisa_kg=9900)
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='B',sisa_kg=5900)
        with pytest.raises(m.MillingError,match='terpakai'):
            await m.finish_milling(db,user=u,kode_proses=kode,berat_akhir=500)
        assert (await m.get_process_by_kode(db,kode)).status=='proses'
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==9900

async def test_hasil_sosoh_tidak_boleh_melebihi_bahan_setelah_sisa_dikurangkan(pg,gudang2):
    from app.penggilingan.gudang2.polishing import mulai_penyosohan,catat_output,selesai_penyosohan,akhiri_penyosohan
    from app.penggilingan.gudang2.service import Gudang2Error
    async with pg() as db:
        u=gudang2['user'];p=(await mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
        await catat_output(db,user=u,kode=p.kode_proses,jenis='medium',berat_kumulatif=500)
        await selesai_penyosohan(db,user=u,kode=p.kode_proses,nama_silo='B',sisa_kg=9700)
        with pytest.raises(Gudang2Error,match='terpakai'):
            await akhiri_penyosohan(db,user=u,kode=p.kode_proses)
        assert p.status=='proses'

async def test_undo_mulai_setelah_silo_diperiksa_tidak_menggandakan_stok(pg,dunia):
    from app.services.undo import _undo_start_milling,UndoError
    async with pg() as db:
        u=await db.get(User,dunia['user']);kode=dunia['kode_proses']
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='A',sisa_kg=500)
        proc=await m.get_process_by_kode(db,kode)
        with pytest.raises(UndoError,match='sudah diperiksa'):
            await _undo_start_milling(db,proc.id)
        assert (await _silo_content_bobot(db,dunia['silo']['A'])).kg==500
        assert await db.get(MillingProcess,proc.id) is not None

@pytest.mark.parametrize('nama',['Tong Broken','Tong Beras Campuran','Silo Campuran','silo eceran'])
async def test_nama_silo_khusus_sosoh_dari_pilihan_hingga_simpan(pg,gudang2,nama):
    from app.web import api
    from app.services.penyelesaian_proses import ringkasan_bebaskan
    from app.penggilingan.gudang2.polishing import mulai_penyosohan,catat_output,akhiri_penyosohan
    from app.penggilingan.gudang2.service import get_g2_silo,hitung_stok_silo
    from app.models import PolishingProcess
    u=gudang2['user']
    async with pg() as db:
        proc=(await mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
        silo=await get_g2_silo(db,'B');sid=silo.id;silo.nama_silo=nama
        await db.commit();kode=proc.kode_proses
        awal=await ringkasan_bebaskan(db,jenis='sosoh',kode=kode,silo=nama,sisa=500)
        besar=await ringkasan_bebaskan(db,jenis='sosoh',kode=kode,silo=nama.upper(),sisa=500)
        assert awal['dasar']==besar['dasar'] and nama in awal['teks']
    pilihan=await api.sosoh_silo(induk=kode,user=u)
    assert len(pilihan)==1
    ringkas=await api.pratinjau_bebaskan_silo(jenis='sosoh',kode_proses=kode,sisa=500,silo=pilihan[0]['value'],user=u)
    hasil=await api.act_selesai_penyosohan(api.SelesaiPenyosohanReq(kode_proses=kode,silo=pilihan[0]['value'],sisa=500,dasar=ringkas['dasar']),user=u)
    assert hasil['ok'] and await api.sosoh_silo(induk=kode,user=u)==[]
    async with pg() as db:
        assert await hitung_stok_silo(db,sid)==500
        assert (await db.get(PolishingProcess,proc.id)).status=='proses'
        await catat_output(db,user=u,kode=kode,jenis='medium',berat_kumulatif=1000)
        await akhiri_penyosohan(db,user=u,kode=kode)
        assert await hitung_stok_silo(db,sid)==500

async def test_nama_tong_giling_pratinjau_dan_simpan_memakai_siklus_sama(pg,dunia):
    from app.services.penyelesaian_proses import ringkasan_bebaskan
    async with pg() as db:
        sid=dunia['silo']['A'];silo=await db.get(Silo,sid);silo.nama_silo='Tong Gabah Campuran';await db.commit()
        kode=dunia['kode_proses'];u=await db.get(User,dunia['user'])
        awal=await ringkasan_bebaskan(db,jenis='giling',kode=kode,silo='Tong Gabah Campuran',sisa=500)
        assert awal['dasar']==(await ringkasan_bebaskan(db,jenis='giling',kode=kode,silo='TONG GABAH CAMPURAN',sisa=500))['dasar']
        await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo='TONG GABAH CAMPURAN',sisa_kg=500,dasar=awal['dasar'])
        assert (await _silo_content_bobot(db,sid)).kg==500
        with pytest.raises(ValueError,match='tidak lagi terbuka'):
            await ringkasan_bebaskan(db,jenis='giling',kode=kode,silo='Tong Gabah Campuran',sisa=0)
        with pytest.raises(ValueError,match='tidak lagi terbuka'):
            await ringkasan_bebaskan(db,jenis='giling',kode=kode,silo='Tong Bukan Milik Proses',sisa=0)
