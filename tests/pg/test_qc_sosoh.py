"""Sampel sebelum timbang, lab terlambat, pembekuan identitas dan gerbang HTTP."""
import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from hmu_identitas.peran import ADMIN, OPERATOR
from app.database import now_local
from app.models import PolishingOutputLog, PolishingProcess, SampelQcSosoh, User
from app.services import qc_sosoh as svc
from app.services.seed import seed_master
from tests.pg.test_riwayat_sosoh import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def dunia(pg):
    await seed_master()
    async with pg() as db:
        u = User(nama='Petugas lab', role=ADMIN, status='aktif')
        db.add(u)
        await db.flush()
        awal = now_local()-timedelta(hours=2)
        p = PolishingProcess(kode_proses='POL-UJI-QC', waktu_mulai=awal, status='proses', created_by=u.id)
        db.add(p)
        await db.commit()
        return dict(user=u, proc=p, awal=awal)


async def ambil(pg, d, jenis='medium', menit=1):
    async with pg() as db:
        return await svc.ambil_sampel(db, user=d['user'], kode_proses=d['proc'].kode_proses,
            jenis=jenis, waktu_sampel=d['awal']+timedelta(minutes=menit))


async def test_sampel_sebelum_timbang_hasil_lab_terlambat_dan_pemetaan_sesi(pg, dunia):
    d = dunia
    qs = [await ambil(pg, d, menit=i) for i in range(4)]
    qp = await ambil(pg, d, 'premium', 5)
    qakhir = await ambil(pg, d, menit=7)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PolishingOutputLog)) == 0
        data = await svc.data_proses(db, d['proc'])
        assert data['menunggu'] == 6 and len(data['belum_dipetakan']) == 6
        for i, (jenis, kg) in enumerate([('medium', 5000), ('premium', 2000), ('medium', 3000)]):
            db.add(PolishingOutputLog(polishing_process_id=d['proc'].id, jenis=jenis, berat_kg=kg,
                cara_input='kumulatif',
                waktu_update=d['awal']+timedelta(minutes=10), input_by=d['user'].id))
        p = await db.get(PolishingProcess, d['proc'].id)
        p.status, p.waktu_selesai = 'selesai', d['awal']+timedelta(minutes=10)
        await db.commit()
    for q in [qakhir, qp, *reversed(qs)]:
        async with pg() as db:
            await svc.isi_hasil(db, user=d['user'], sampel_id=q.id, kadar_air=14, broken_persen=10,
                                md='123,456', transparant='1,005', whiteness='45,678')
    async with pg() as db:
        data = await svc.data_proses(db, await db.get(PolishingProcess, d['proc'].id))
        assert [[q.id for q in s['sampel']] for s in data['sesi']] == [[q.id for q in qs], [qp.id], [qakhir.id]]
        assert [s['berat_estimasi_kg'] for s in data['sesi']] == [5000, 2000, 3000]
        assert data['menunggu'] == 0
        assert data['sesi'][0]['rata'][0] == ('Kadar air', 14.0, 4, '%')
        assert data['sesi'][0]['rata'][2] == ('MD', Decimal('123.46'), 4, '')
        assert (await db.get(SampelQcSosoh, qp.id)).jenis == 'premium'
        other = PolishingProcess(kode_proses='POL-QC-LAIN', waktu_mulai=d['awal'], status='proses', created_by=d['user'].id)
        db.add(other)
        await db.flush()
        assert not (await svc.data_proses(db, other))['sampel']
    async with await _klien(pg, peran=ADMIN) as c:
        halaman = await c.get('/riwayat-qc/beras-hasil-sosoh/'+d['proc'].kode_proses)
        assert halaman.status_code == 200
        assert '5000,00 kg' in halaman.text and '3000,00 kg' in halaman.text
        assert 'MD 123,46' in halaman.text and 'MD 123,46%' not in halaman.text
        assert 'Transparant 1,01' in halaman.text and 'Whiteness 45,68' in halaman.text
        out = Path(__file__).resolve().parents[2]/'output'/'qc-sosoh-20261104'
        out.mkdir(parents=True, exist_ok=True)
        (out/'pratinjau.html').write_text(halaman.text)
        for nama, path in [('menu', '/api/actions/menu'), ('proses', '/api/actions/proses-qc-sosoh')]:
            (out/f'{nama}.json').write_text(json.dumps((await c.get(path)).json()))


async def test_identitas_dijaga_basis_data_dan_waktu_diperiksa(pg, dunia):
    q = await ambil(pg, dunia, 'premium')
    for kolom, nilai in [('jenis', "'medium'"), ('kunci_kiriman', "'ubah'"), ('waktu_sampel', "waktu_sampel + interval '1 minute'"),
                         ('polishing_process_id', 'polishing_process_id+1')]:
        async with pg() as db:
            with pytest.raises(DBAPIError, match='Identitas sampel'):
                await db.execute(text(f'UPDATE sampel_qc_sosoh SET {kolom}={nilai} WHERE id=:id'), {'id': q.id})
            await db.rollback()
    for waktu in [dunia['awal']-timedelta(minutes=1), now_local()+timedelta(hours=1)]:
        async with pg() as db:
            with pytest.raises(svc.QcSosohError):
                await svc.ambil_sampel(db, user=dunia['user'], kode_proses=dunia['proc'].kode_proses,
                    jenis='premium', waktu_sampel=waktu)


async def test_dua_pengiriman_hasil_lab_tidak_saling_menimpa(pg, dunia):
    q = await ambil(pg, dunia)
    async def isi(ka):
        async with pg() as db:
            try:
                await svc.isi_hasil(db, user=dunia['user'], sampel_id=q.id, kadar_air=ka)
                return 'ok'
            except svc.QcSosohError:
                return 'ditolak'
    assert sorted(await asyncio.gather(isi(13), isi(15))) == ['ditolak', 'ok']


async def test_input_kumulatif_per_jenis_tidak_berarti_urutan_garapan(pg, dunia):
    from app.penggilingan.gudang2.polishing import catat_output
    d = dunia
    await ambil(pg, d, 'medium', 0)
    await ambil(pg, d, 'premium', 5)
    await ambil(pg, d, 'medium', 7)
    async with pg() as db:
        # Operator mengisi SELURUH medium dahulu, baru premium. 5000→8000
        # kumulatif tetap 8000; bukan 13000. Jam input bukan jam garapan.
        await catat_output(db, user=d['user'], kode=d['proc'].kode_proses, jenis='medium', berat_kumulatif=5000)
        await catat_output(db, user=d['user'], kode=d['proc'].kode_proses, jenis='medium', berat_kumulatif=8000)
        await catat_output(db, user=d['user'], kode=d['proc'].kode_proses, jenis='premium', berat_kumulatif=2000)
        data = await svc.data_proses(db, d['proc'])
        assert next(h['berat_kg'] for h in data['hasil'] if h['jenis']=='medium') == 8000
        assert [s['jenis'] for s in data['sesi']] == ['medium', 'premium', 'medium']
        assert sum(s['berat_estimasi_kg'] for s in data['sesi'] if s['jenis']=='medium') == 8000


async def test_pembatalan_menyimpan_riwayat_tetapi_mengeluarkan_sampel_dari_estimasi(pg, dunia):
    q = await ambil(pg, dunia)
    async with pg() as db:
        await svc.isi_hasil(db, user=dunia['user'], sampel_id=q.id, kadar_air=14)
        await svc.batalkan_sampel(db, user=dunia['user'], sampel_id=q.id, alasan='Jenis sampel salah dipilih')
        data = await svc.data_proses(db, dunia['proc'])
        assert not data['sesi'] and len(data['sampel']) == 1 and data['menunggu']==0
        asli = await db.get(SampelQcSosoh, q.id)
        assert asli.dibatalkan_pada and float(asli.kadar_air)==14 and asli.alasan_batal
        with pytest.raises(svc.QcSosohError, match='dibatalkan'):
            await svc.isi_hasil(db, user=dunia['user'], sampel_id=q.id, kadar_air=15)


@pytest.mark.parametrize('cara', ['kumulatif', 'tambahan', 'campuran'])
async def test_snapshot_dan_tambahan_setara_tanpa_pilihan_sesi(pg, dunia, monkeypatch, cara):
    from app.penggilingan.gudang2 import polishing as pol
    for jenis, menit in [('medium',0),('premium',5),('medium',7)]:
        await ambil(pg,dunia,jenis,menit)
    async with pg() as db:
        for i, (menit, total, delta) in enumerate([(4,5000,5000),(8,6000,1000),(10,8000,2000)]):
            monkeypatch.setattr(pol,'input_time',lambda *args, m=menit: dunia['awal']+timedelta(minutes=m))
            nilai = {'berat_kumulatif':total} if cara=='kumulatif' or cara=='campuran' and i>0 else {'berat_kg':delta}
            await pol.catat_output(db,user=dunia['user'],kode=dunia['proc'].kode_proses,jenis='medium',**nilai)
        data=await svc.data_proses(db,dunia['proc'])
        assert [s['berat_estimasi_kg'] for s in data['sesi']]==[5500,None,2500]
        logs=(await db.scalars(select(PolishingOutputLog).order_by(PolishingOutputLog.id))).all()
        assert [float(r.berat_kg) for r in logs]==[5000,1000,2000]


async def test_http_sampel_sebelum_timbang_riwayat_dan_izin(pg, dunia):
    async with await _klien(pg, peran=ADMIN) as c:
        c.headers['X-CSRF-Token'] = cap_formulir(c)
        menu = (await c.get('/api/actions/menu')).json()
        for id_ in ['sampel_qc_sosoh', 'qc_sosoh']:
            a = next(a for a in menu if a['id'] == id_)
            assert a['boleh'] and a['wh'] == 'g2' and a['kartu']
        r = await c.post('/api/actions/sampel-qc-sosoh', json={'kode_proses': dunia['proc'].kode_proses, 'jenis': 'premium'})
        assert r.status_code == 200, r.text[:500]
        id_ = r.json()['sampel_id']
        options = (await c.get('/api/actions/sampel-qc-sosoh-menunggu')).json()
        assert any(o['value'] == str(id_) and 'Premium' in o['label'] for o in options)
        pending = await c.get('/pekerjaan?asal=mutu')
        assert pending.status_code == 200 and 'QC penyosohan' in pending.text and dunia['proc'].kode_proses in pending.text
        r = await c.post('/api/actions/qc-sosoh', json={'sampel_id': id_, 'kadar_air': 14, 'jenis': 'medium'})
        assert r.status_code == 422
        assert (await c.post('/api/actions/qc-sosoh', json={'sampel_id': id_, 'kadar_air': 101})).status_code == 422
        assert (await c.post('/api/actions/qc-sosoh', json={'sampel_id': id_})).status_code == 400
        r = await c.post('/api/actions/qc-sosoh', json={'sampel_id': id_, 'kadar_air': 14, 'catatan_lab': '<b>Uji lab</b>'})
        assert r.status_code == 200, r.text
        assert 'Premium' in r.json()['pesan']
        assert (await c.post('/api/actions/qc-sosoh', json={'sampel_id': id_, 'kadar_air': 15})).status_code == 400
        history = await c.get('/riwayat-qc/beras-hasil-sosoh/'+dunia['proc'].kode_proses)
        assert history.status_code == 200, history.text[:500]
        assert 'Premium' in history.text and '&lt;b&gt;Uji lab&lt;/b&gt;' in history.text
        assert 'Belum dipetakan ke hasil timbang' in history.text
    async with await _klien(pg, peran=OPERATOR, gudang='Gudang 2') as c:
        c.headers['X-CSRF-Token'] = cap_formulir(c)
        assert (await c.get('/riwayat-qc/beras-hasil-sosoh/'+dunia['proc'].kode_proses)).status_code == 200
        assert (await c.get('/api/actions/sampel-qc-sosoh-menunggu')).status_code == 403
        assert (await c.post('/api/actions/sampel-qc-sosoh', json={'kode_proses': dunia['proc'].kode_proses, 'jenis': 'medium'})).status_code == 403
    async with await _klien(pg, peran=OPERATOR, gudang='Gudang 1') as c:
        assert (await c.get('/riwayat-qc/beras-hasil-sosoh/'+dunia['proc'].kode_proses)).status_code == 403

async def test_satu_kartu_dari_mulai_sampai_tutup_termasuk_saat_hasil_lab_lengkap(pg, dunia):
    from app.services.kelompok_kerja import jenis_kerja
    async with pg() as db:
        cards=await svc.kartu_menunggu(db)
        assert len(cards)==1 and cards[0].nilai==dunia['proc'].kode_proses
        assert jenis_kerja(cards[0])=='qc'
    q=await ambil(pg,dunia)
    async with pg() as db:
        await svc.isi_hasil(db,user=dunia['user'],sampel_id=q.id,kadar_air=14)
        assert len(await svc.kartu_menunggu(db))==1
    pending=await ambil(pg,dunia,'premium',5)
    async with pg() as db:
        assert len(await svc.kartu_menunggu(db))==1
        p=await db.get(PolishingProcess,dunia['proc'].id)
        p.status,p.waktu_selesai='selesai',now_local()
        await db.commit()
        assert await svc.kartu_menunggu(db)==[]
        data=await svc.data_proses(db,p)
        assert data['menunggu']==1 and len(data['sampel'])==2
        await svc.isi_hasil(db,user=dunia['user'],sampel_id=pending.id,kadar_air=13.5)
        assert (await db.get(SampelQcSosoh,pending.id)).jenis=='premium'
        with pytest.raises(svc.QcSosohError,match='ditutup'):
            await svc.ambil_sampel(db,user=dunia['user'],kode_proses=p.kode_proses,jenis='medium',waktu_sampel=now_local())


async def test_dua_pengiriman_sampel_satu_kunci_tidak_menggandakan_sampel(pg,dunia):
    async def kirim():
        async with pg() as db:
            q=await svc.ambil_sampel(db,user=dunia['user'],kode_proses=dunia['proc'].kode_proses,
                jenis='medium',waktu_sampel=dunia['awal']+timedelta(minutes=1),kunci_kiriman='sampel-kiriman-yang-sama')
            return q.id
    ids=await asyncio.gather(kirim(),kirim())
    assert ids[0]==ids[1]
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(SampelQcSosoh))==1
        with pytest.raises(svc.QcSosohError,match='jenis lain'):
            await svc.ambil_sampel(db,user=dunia['user'],kode_proses=dunia['proc'].kode_proses,
                jenis='premium',waktu_sampel=now_local(),kunci_kiriman='sampel-kiriman-yang-sama')


async def test_input_qc_di_detail_dan_kartu_menu_tanpa_sesi_manual(pg,dunia):
    q=await ambil(pg,dunia)
    async with await _klien(pg,peran=ADMIN) as c:
        page=await c.get('/proses-aktif/sosoh/'+dunia['proc'].kode_proses)
        debug=Path(__file__).resolve().parents[2]/'output'/'qc-sosoh-20261104'
        debug.mkdir(parents=True,exist_ok=True)
        (debug/'detail-awal.html').write_text(page.text)
        assert page.status_code==200,page.text[:400]
        assert 'data-qc-baru' in page.text and 'data-qc-editor' in page.text
        assert 'data-qc-lengkapi="'+str(q.id)+'"' in page.text
        assert 'data-kode="'+dunia['proc'].kode_proses+'"' in page.text
        assert 'sesi_baru' not in page.text and 'hasil_sesi_penyosohan' not in page.text
        jobs=await c.get('/pekerjaan?tab=tindakan&jenis=qc')
        assert '/proses-aktif/sosoh/'+dunia['proc'].kode_proses+'?kembali_kerja=' in jobs.text and '#qc-sosoh' in jobs.text
        menu=(await c.get('/api/actions/menu')).json()
        sample=next(a for a in menu if a['id']=='sampel_qc_sosoh')
        assert all(f['name']!='sesi_baru' for f in sample['fields'])
        out=Path(__file__).resolve().parents[2]/'output'/'qc-sosoh-20261104'
        out.mkdir(parents=True,exist_ok=True)
        (out/'detail-admin.html').write_text(page.text)
        (out/'pekerjaan-admin.html').write_text(jobs.text)
    async with await _klien(pg,peran=OPERATOR,gudang='Gudang 2') as c:
        page=await c.get('/proses-aktif/sosoh/'+dunia['proc'].kode_proses)
        assert page.status_code==200 and 'data-qc-editor' not in page.text
        assert 'QC beras hasil sosoh' in page.text
        (out/'detail-operator.html').write_text(page.text)

async def test_pembatalan_dari_hal_lama_tidak_menimpa_alasan_yang_sudah_tersimpan(pg,dunia):
    q=await ambil(pg,dunia)
    async with pg() as lama:
        terbaca=await lama.get(SampelQcSosoh,q.id)
        async with pg() as baru:
            await svc.batalkan_sampel(baru,user=dunia['user'],sampel_id=q.id,alasan='Alasan pertama')
        assert terbaca.dibatalkan_pada is None
        with pytest.raises(svc.QcSosohError,match='sudah dibatalkan'):
            await svc.batalkan_sampel(lama,user=dunia['user'],sampel_id=q.id,alasan='Alasan dari halaman lama')
    async with pg() as db:
        assert (await db.get(SampelQcSosoh,q.id)).alasan_batal=='Alasan pertama'

async def test_komponen_beras_http_desimal_koma_satuan_dan_skala_database(pg,dunia):
    q=await ambil(pg,dunia,'premium')
    async with await _klien(pg,peran=ADMIN) as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        nilai=dict(kadar_air='13,455',broken_persen='9,995',md='123,456',transparant='1,005',whiteness='45,678')
        r=await c.post('/api/actions/qc-sosoh',json=dict(sampel_id=q.id,**nilai))
        assert r.status_code==200,r.text
        h=await c.get('/riwayat-qc/beras-hasil-sosoh/'+dunia['proc'].kode_proses)
        for komponen in ['Kadar air 13,46%','Broken 10,00%','MD 123,46','Transparant 1,01','Whiteness 45,68']:
            assert komponen in h.text,komponen
        assert 'MD 123,46%' not in h.text
        for nama in ('menir_persen','butir_kuning','gabah','merang'):
            assert 'name="'+nama+'"' not in h.text
    async with pg() as db:
        simpan=await db.get(SampelQcSosoh,q.id)
        for kolom,target in zip(nilai,['13.46','10.00','123.46','1.01','45.68']):
            n=getattr(simpan,kolom)
            assert n==Decimal(target) and n.as_tuple().exponent==-2
        skala=dict((await db.execute(text("SELECT column_name,numeric_scale FROM information_schema.columns WHERE table_name='sampel_qc_sosoh' AND data_type='numeric'"))).all())
        assert skala=={k:2 for k in nilai}
        with pytest.raises(DBAPIError,match='ck_sampel_sosoh_md'):
            await db.execute(text('UPDATE sampel_qc_sosoh SET md=-1 WHERE id=:id'),dict(id=q.id))
        await db.rollback()
