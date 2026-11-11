"""Angka penting mengikuti proses, memakai alur produksi sungguhan."""
from datetime import timedelta
import pytest
from app.database import now_local
from app.services.laporan_periode import ambil
from tests.pg.test_riwayat_giling import pabrik, _giling_selesai
from tests.pg.test_riwayat_sosoh import _sosoh_selesai

pytestmark=pytest.mark.asyncio

def keys(data):return {c['kunci'] for c in data['kolom']}

async def test_giling_bahan_dan_hasil_verifikasi_mengalahkan_progres(pg,pabrik):
    from app.models import MillingProcess,MillingProcessVerification
    from sqlalchemy import select
    await _giling_selesai(pg,pabrik,masuk_kg=10000,berat_akhir=6500)
    async with pg() as db:
        p=await db.scalar(select(MillingProcess))
        db.add(MillingProcessVerification(milling_process_id=p.id,berat_output_final_kg=6400))
        await db.commit()
        d=await ambil(db,'penggilingan',now_local().date(),now_local().date())
        assert not {'nota','timbangan'} & keys(d)
        r=d['rincian'][0]
        assert r['bahan'].startswith('10.000')
        assert r['hasil']=='6.400'
        assert r['asal'].startswith('GB-RGL-') and 'Silo' not in r['asal']
        assert r['bahan_basah']=='-' and r['bahan_kering']=='10.000'
        assert len(d['kepala_tabel'])==3
        assert 'rendemen' in keys(d) and 'asal' in keys(d)


from tests.pg.test_giling_beberapa_silo import silos


async def test_giling_memisahkan_asal_basah_dari_kering_tanpa_mengubah_total(pg,silos):
    from sqlalchemy import select
    from app import models as m
    from tests.pg.test_giling_beberapa_silo import _mulai
    from app.services.laporan_bahan_giling import per_kondisi
    result=await _mulai(pg,silos,['A','B'])
    async with pg() as db:
        # Cuplikan sumber giling tetap 10.000: bahan ini berasal dari lot
        # pengeringan gabah basah, sementara sumber lain langsung kering.
        src=await db.scalar(select(m.MillingProcessSource).where(m.MillingProcessSource.purchase_batch_id==silos['isi']['A']['batch']))
        batch=await db.get(m.PurchaseBatch,src.purchase_batch_id);batch.kondisi_gabah='basah'
        lot=m.DryingLot(kode_lot='PGR-ASAL-BASAH',created_by=silos['user'],status='selesai')
        db.add(lot);await db.flush()
        db.add(m.DryingLotBatch(drying_lot_id=lot.id,purchase_batch_id=batch.id))
        src.drying_lot_id=lot.id;src.purchase_batch_id=None
        st=await db.get(m.SiloStorage,src.silo_storage_id)
        st.drying_lot_id=lot.id;st.purchase_batch_id=None;st.tipe_masuk='dari_pengeringan'
        await db.commit()
        d=await ambil(db,'penggilingan',now_local().date(),now_local().date())
        r=d['rincian'][0]
        assert (r['bahan_basah'],r['bahan_kering'],r['bahan'])==('10.000','6.000','16.000')
        assert 'Silo' not in r['asal'] and 'PGR-ASAL-BASAH' in r['asal']
        assert any(c['nama']=='Gabah terpakai' and c['kolom']==3 for c in d['kepala_tabel'][1])
        assert {'Gabah basah','Gabah kering'}<={x['nama'] for x in d['ringkasan']}
        # Ketidakcocokan sumber tidak boleh diatasi dengan membagi total
        # secara proporsional dan menghasilkan dua angka yang tampak pasti.
        src.berat_kg=9000;await db.commit()
        p=await db.get(m.MillingProcess,result.proc.id)
        split=(await per_kondisi(db,{p.id:p}))[p.id]
        assert split=={'basah':None,'kering':None}

async def test_sosoh_semua_catatan_hasil_spek_samping_dan_neraca(pg,pemakai):
    await _sosoh_selesai(pg,pemakai.id,masuk=10000,hasil=(('medium',4000),('medium',2000),('premium',500),('broken',1200),('menir',700),('bekatul',1500),('reject',50)))
    async with pg() as db:
        d=await ambil(db,'penyosohan',now_local().date(),now_local().date())
        assert not {'nota','timbangan'} & keys(d)
        r=d['rincian'][0]
        assert '6.000' in r['hasil_beras'] and '500' in r['hasil_beras']
        assert all(v in r['hasil_samping'] for v in ['1.200','700','1.500','50'])
        assert r['hasil']=='9.950'
        assert 'asal' not in keys(d)
        assert any(c['kelompok']=='Bahan' for c in d['kolom'])
        assert any(c['kelompok']=='Hasil' and c['nama']=='Broken' for c in d['kolom'])
        assert not any('silo' in c['nama'].lower() for c in d['kolom'])
        assert '10.000' in r['bahan_jenis']
        assert r['susut']=='50'
        assert r['rendemen']=='65,00%'
        assert any(x['nama']=='Rendemen beras' and x['nilai']=='65,00%' for x in d['ringkasan'])

async def test_sosoh_berjalan_tidak_mengarang_bahan_akhir(pg,pemakai):
    from tests.pg.test_riwayat_sosoh import _silo_berisi
    from app.services.seed import seed_master
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.models import User
    from tests.pg.fasilitas import di_gudang
    await seed_master();await _silo_berisi(pg,'A',10000,pemakai.id)
    async with pg() as db:
        await mulai_penyosohan(db,user=await di_gudang(db,await db.get(User,pemakai.id),'g2'),nama_silos=['A'])
        d=await ambil(db,'penyosohan',now_local().date(),now_local().date())
        assert d['rincian'][0]['bahan']=='Belum final'
        assert d['rincian'][0]['rendemen']=='Belum dapat dihitung'
        assert d['rincian'][0]['susut']=='Belum dapat dihitung'


async def test_hasil_samping_tambahan_dari_master_ikut_laporan(pg,pemakai):
    import json
    from sqlalchemy import select
    from app.models import PolishingProcess,PolishingOutputLog,SetelanPabrik
    await _sosoh_selesai(pg,pemakai.id)
    async with pg() as db:
        pid=await db.scalar(select(PolishingProcess.id))
        db.add(SetelanPabrik(kunci='jenis_hasil_samping:hs_serbuk',nilai=json.dumps(dict(kode='hs_serbuk',nama='Serbuk khusus',aktif=True,kg_karung=None))))
        db.add(PolishingOutputLog(polishing_process_id=pid,jenis='hs_serbuk',berat_kg=25,waktu_update=now_local(),input_by=pemakai.id))
        await db.commit()
        d=await ambil(db,'penyosohan',now_local().date(),now_local().date())
        assert 'Serbuk khusus: 25' in d['rincian'][0]['hasil_samping']
        assert any(x['nama']=='Serbuk khusus' and x['nilai']=='25' for x in d['ringkasan'])
        hasil=next(g for g in d['ringkasan_kelompok'] if g['nama']=='Hasil')
        assert any(x['nama']=='Serbuk khusus' and x['bagian']=='Hasil samping' for x in hasil['rincian'])
        from app.web.pdf_periode import buat_pdf
        from pypdf import PdfReader
        from io import BytesIO
        text=' '.join(p.extract_text() for p in PdfReader(BytesIO(buat_pdf(d))).pages)
        assert 'Serbuk khusus' in text and '25' in text

from tests.pg.test_gabung_jasa import dunia
from tests.pg.test_stok_produk_jasa import sosoh_jasa

async def test_pengeringan_memisahkan_estimasi_dari_hasil_terukur(pg,dunia):
    from tests.pg.test_estimasi_pengeringan import buat
    await buat(pg,dunia)
    async with pg() as db:
        d=await ambil(db,'pengeringan',now_local().date()-timedelta(days=2),now_local().date())
        r=d['rincian'][0]
        assert float(r['estimasi'].replace('.','').replace(',','.'))>0
        assert r['hasil']=='Belum ditimbang'
        assert r['alat']!='Belum tercatat'
        assert not {'nota','timbangan'} & keys(d)

async def test_kemas_ulang_bobot_dibuka_hasil_baru_dan_sisa(pg,sosoh_jasa):
    from tests.pg.test_kemas_ulang import awal
    from app.services import kemas_ulang
    from app.models import User
    req,_,_=await awal(pg,sosoh_jasa)
    async with pg() as db:
        await kemas_ulang.simpan(db,user=await db.get(User,sosoh_jasa['user']),**req)
        d=await ambil(db,'kemas_ulang',now_local().date(),now_local().date())
        r=d['rincian'][0]
        assert r['bahan']=='100' and r['hasil']=='80' and r['sisa']=='20'
        assert r['karung_asal']=='4' and r['karung']=='2'
        assert not {'nota','timbangan'} & keys(d)
