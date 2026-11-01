"""Tahap adalah proyeksi baca: saldo lama, pemilik, dan transaksi tetap sama."""
from datetime import date

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import event, select

from app.database import now_local
from app.models import PurchaseBatch, User, MillingProcess, PolishingProcess
from app.services.stok_lokasi import bahan
from app.web.portal.barang import per_tahap
from tests.pg.test_gabung_jasa import dunia, _isi_silo_g1  # noqa: F401
from tests.pg.test_portal_transit import _pk, _akun
from tests.pg.test_portal_komoditas import ringkasan
from tests.pg.test_portal_pelanggan import client
from tests.pg.test_stok_pk_g1_polesan import _klien

pytestmark = pytest.mark.asyncio


async def siapkan(pg, dunia, *, jasa=True):
    from app.penggilingan.gudang1.services.milling import start_milling, log_progress
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, catat_output
    jid = dunia['jasa1'] if jasa else None
    for letter, kg in [('A', 6000), ('B', 4000)]:
        await _isi_silo_g1(pg, dunia, huruf=letter, kode='GB-TAHAP-'+letter, kg=kg, jasa_id=jid or dunia['jasa1'])
    for letter in ('C', 'D'):
        await _pk(pg, dunia, silo=letter, jid=jid or dunia['jasa1'], code='PKB-TAHAP-'+letter)
    async with pg() as db:
        if not jasa:
            # Helper asal khusus jasa. Siapkan padanan pembelian pabrik
            # sebelum proses dimulai; hanya fixture database uji.
            from app.models import Supplier, SiloStorage, PkPurchaseBatch, PkGudang2Intake
            supplier = Supplier(nama_supplier='Pemasok uji tahap')
            db.add(supplier)
            await db.flush()
            for model in (PurchaseBatch, PkPurchaseBatch, SiloStorage, PkGudang2Intake):
                for row in (await db.scalars(select(model))).all():
                    row.jasa_id = None
                    if model in (PurchaseBatch, PkPurchaseBatch):
                        row.supplier_id = supplier.id
            await db.commit()
        u = await db.get(User, dunia['user'])
        p = (await start_milling(db, user=u, nama_silo='A')).proc
        await log_progress(db, user=u, kode_proses=p.kode_proses, berat_kumulatif=1500)
        q = (await mulai_penyosohan(db, user=u, nama_silos=['C'])).proc
        await catat_output(db, user=u, kode=q.kode_proses, jenis='medium', berat_kumulatif=500)
        await catat_output(db, user=u, kode=q.kode_proses, jenis='broken', berat_kumulatif=100)
    return p.kode_proses, q.kode_proses


def sections(html):
    return {s['data-tahap']: s for s in BeautifulSoup(html, 'html.parser').select('section[data-tahap]')}


@pytest.mark.parametrize('jasa', [False, True], ids=['pabrik', 'pelanggan'])
async def test_stok_tiga_tahap_memakai_saldo_lama_tanpa_menulis(pg, dunia, jasa, monkeypatch):
    from app.web import tampilan
    from app.penggilingan.gudang1.services.silo import _silo_content_bobot
    from app.penggilingan.gudang2.service import hitung_stok_silo
    kode, pol = await siapkan(pg, dunia, jasa=jasa)
    hasil = []; asli = tampilan.render
    def rekam(req, nama, **k):
        hasil.append(k)
        return asli(req, nama, **k)
    monkeypatch.setattr(tampilan, 'render', rekam)
    c = await _klien(pg, role='admin')
    async with pg() as db:
        mesin = db.bind.sync_engine
        sebelum = ((await _silo_content_bobot(db, dunia['silo']['A'])).kg,
                    await hitung_stok_silo(db, dunia['silo']['C']))
    writes = []
    def tulis(conn, cursor, statement, params, ctx, many):
        if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
            writes.append(statement)
    event.listen(mesin, 'before_cursor_execute', tulis)
    try:
        async with c:
            pemilik = 'jasa' if jasa else 'pabrik'
            response = await c.get('/stok?pemilik='+pemilik)
            assert response.status_code == 200, response.text
            s = sections(response.text)
            assert set(s) == {'menunggu', 'dalam_proses', 'hasil'}
            assert 'GB-TAHAP-B' in s['menunggu'].get_text()
            assert 'Silo D' in s['menunggu'].get_text()
            assert 'GB-TAHAP-A' not in s['menunggu'].get_text()
            assert 'GB-TAHAP-A' in s['dalam_proses'].get_text()
            assert 'Silo C' in s['dalam_proses'].get_text()
            assert 'Bahan masuk tercatat' in s['dalam_proses'].get_text()
            assert 'Sisa aktual belum dikonfirmasi' in s['dalam_proses'].get_text()
            assert kode in s['hasil'].get_text() and 'giling masih berjalan' in s['hasil'].get_text()
            k = hasil[-1]
            assert k['total'] == 1500  # nilai lama tidak memasukkan gabah/silo G2
            groups = k['kelompok_pk'][0]['tahap_stok'] if jasa else k['TAHAP_STOK']
            assert sum(r['kg'] for g in groups for r in g['baris'] if r['tahap']=='dalam_proses') == 8000
            produk = await c.get('/stok?tab=produk&pemilik='+pemilik)
            assert produk.status_code == 200
            assert '500' in sections(produk.text)['hasil'].get_text()
            assert 'proses berjalan masih sementara' in produk.text
    finally:
        event.remove(mesin, 'before_cursor_execute', tulis)
    assert writes == []
    async with pg() as db:
        assert sebelum == (6000, 2000) == ((await _silo_content_bobot(db, dunia['silo']['A'])).kg,
                                              await hitung_stok_silo(db, dunia['silo']['C']))


async def test_portal_memisahkan_pk_hasil_dan_pk_dalam_proses_tanpa_total_gabungan(pg, dunia):
    from copy import deepcopy
    kode, pol = await siapkan(pg, dunia)
    async with pg() as db:
        db.add(PurchaseBatch(kode_batch='GB-RAHASIA-BUDI', jasa_id=dunia['jasa3'],
            berat_total_kg=9876, kondisi_gabah='basah', tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=dunia['user'], status_batch='baru'))
        await db.commit()
    lama = await ringkasan(pg, dunia); original = deepcopy(lama)
    groups = per_tahap(lama)
    assert lama == original
    stages = {g['kunci']: {c['kunci']: c for c in g['komoditas']} for g in groups}
    assert stages['menunggu']['gabah']['kg'] == 4000
    assert stages['dalam_proses']['gabah']['kg'] == 6000
    assert stages['menunggu']['pk']['kg'] == 2000
    assert stages['dalam_proses']['pk']['kg'] == 2000
    assert stages['hasil']['pk']['kg'] == 1500
    assert stages['hasil']['beras']['kg'] == 500
    assert stages['hasil']['broken']['kg'] == 100
    assert next(g for g in lama if g['kunci']=='pk')['kg'] == 5500  # pembaca kompatibel
    ids = [c['id'] for g in groups for c in g['komoditas']]
    assert len(ids) == len(set(ids))
    async with client(await _akun(pg, dunia)) as c:
        for path in ('/pelanggan/', '/pelanggan/barang-saya', '/pelanggan/stok-pk-jasa'):
            r = await c.get(path)
            assert r.status_code == 200, r.text
            s = sections(r.text)
            assert set(s) == {'menunggu', 'dalam_proses', 'hasil'}
            assert '6.000' in s['dalam_proses'].get_text()
            assert '1.500' in s['hasil'].get_text()
            assert 'GB-RAHASIA-BUDI' not in r.text
            assert not BeautifulSoup(r.text, 'html.parser').select('[data-post],[data-aksi],dialog')
            assert '5.500 kg' not in r.text


async def test_sisa_silo_dilepas_kembali_menunggu_walau_proses_belum_selesai(pg, dunia):
    from app.penggilingan.gudang1.services.milling import tutup_silo_giling
    from app.penggilingan.gudang2.polishing import selesai_penyosohan
    kode, pol = await siapkan(pg, dunia)
    async with pg() as db:
        user = await db.get(User, dunia['user'])
        await tutup_silo_giling(db, user=user, kode_proses=kode, nama_silo='A', sisa_kg=500)
        await selesai_penyosohan(db, user=user, kode=pol, nama_silo='C', sisa_kg=300)
        assert (await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses==kode))).status == 'proses'
        assert (await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==pol))).status == 'proses'
        rows = await bahan(db, jasa_ids=[dunia['jasa1'], dunia['jasa2']])
        assert all(r['tahap']=='menunggu' for r in rows)
        assert next(r['kg'] for r in rows if r['kode']=='GB-TAHAP-A') == 500
        assert next(r['kg'] for r in rows if r['kode']=='Silo C') == 300
    groups = per_tahap(await ringkasan(pg, dunia))
    assert next(g['baris'] for g in groups if g['kunci']=='dalam_proses') == []
    hasil = next(g for g in groups if g['kunci']=='hasil')
    assert next(g['kg'] for g in hasil['komoditas'] if g['kunci']=='pk') == 1500


async def test_perubahan_hasil_tetap_mengikuti_pembaca_asal(pg, dunia):
    from app.penggilingan.gudang1.services.milling import log_progress
    from app.penggilingan.gudang2.polishing import catat_output
    kode, pol = await siapkan(pg, dunia)
    async with pg() as db:
        user = await db.get(User, dunia['user'])
        await log_progress(db, user=user, kode_proses=kode, berat_kumulatif=1700)
        await catat_output(db, user=user, kode=pol, jenis='medium', berat_kumulatif=750)
    groups = {g['kunci']: g for g in per_tahap(await ringkasan(pg, dunia))}
    hasil = {c['kunci']: c['kg'] for c in groups['hasil']['komoditas']}
    assert hasil['pk'] == 1700 and hasil['beras'] == 750
    assert sum(r['kg'] for r in groups['dalam_proses']['baris']) == 8000


async def test_operator_g2_tidak_mendapat_bahan_gabah_g1(pg, dunia):
    await siapkan(pg, dunia, jasa=False)
    async with await _klien(pg, gudang_id=dunia['g2']) as c:
        r = await c.get('/stok')
        assert r.status_code == 200
        assert 'GB-TAHAP-A' not in sections(r.text)['dalam_proses'].get_text()
        assert 'GB-TAHAP-B' not in sections(r.text)['menunggu'].get_text()
        assert 'Silo C' in sections(r.text)['dalam_proses'].get_text()
        assert 'giling masih berjalan' in sections(r.text)['hasil'].get_text()


async def test_pelanggan_dengan_bahan_saja_muncul_dan_bobot_tidak_diketahui_tetap_none(pg, dunia):
    async with pg() as db:
        db.add(PurchaseBatch(kode_batch='GB-BELUM-TIMBANG', jasa_id=dunia['jasa1'],
            berat_total_kg=None, kondisi_gabah='basah', tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=dunia['user'], sumber_berat='menunggu', status_batch='baru'))
        await db.commit()
    async with await _klien(pg, role='admin') as c:
        r = await c.get('/stok?pemilik=jasa&pelanggan_id='+str(dunia['catur']))
        assert r.status_code == 200
        assert 'GB-BELUM-TIMBANG' in r.text and 'Belum ditimbang' in r.text
        assert 'GB-BELUM-TIMBANG' not in (await c.get('/stok')).text
    groups = per_tahap(await ringkasan(pg, dunia))
    assert groups[0]['komoditas'][0]['kg'] is None
    assert not groups[1]['baris'] and not groups[2]['baris']


@pytest.mark.parametrize('jenis', ['beras', 'broken', 'menir', 'reject'])
async def test_semua_bahan_sosoh_termasuk_beras_dan_hasil_samping_mengikuti_silo_aktif(pg, dunia, jenis):
    from app.models import (BerasKeSilo, BrokenKeSilo, HasilSampingKeSilo, ByproductStock,
                            PolishingOutputLog, Silo)
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import hitung_stok_silo
    async with pg() as db:
        p = PolishingProcess(kode_proses='POL-ASAL-TAHAP', jasa_id=dunia['jasa1'],
            status='selesai', waktu_mulai=now_local(), waktu_selesai=now_local(), created_by=dunia['user'])
        db.add(p); await db.flush()
        grade = 'medium' if jenis=='beras' else jenis
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis=grade,
            berat_kg=998, waktu_update=now_local(), input_by=dunia['user']))
        silo = await db.get(Silo, dunia['silo']['C'])
        silo.jenis_isi = 'beras' if jenis=='beras' else jenis
        kwargs = dict(kode_pindah='PIND-TAHAP', silo_id=silo.id, berat_kg=998,
            tanggal=date.today(), waktu=now_local(), input_by=dunia['user'], jasa_id=dunia['jasa1'])
        if jenis=='beras':
            row = BerasKeSilo(**kwargs, polishing_process_id=p.id, source_type='polishing', source_id=p.id, jenis=grade)
        elif jenis=='broken':
            stock = ByproductStock(jenis_produk='broken', source_type='polishing', source_id=p.id,
                berat_kg=998, tanggal=date.today(), waktu=now_local(), input_by=dunia['user'], jasa_id=dunia['jasa1'])
            db.add(stock); await db.flush()
            row = BrokenKeSilo(**kwargs, byproduct_stock_id=stock.id)
        else:
            row = HasilSampingKeSilo(**kwargs, polishing_process_id=p.id, jenis=jenis)
        db.add(row); await db.commit()
        before = await bahan(db, jasa_ids=[dunia['jasa1']])
        assert [(r['tahap'], r['kg']) for r in before] == [('menunggu', 998)]
        await mulai_penyosohan(db, user=await db.get(User, dunia['user']), nama_silos=['C'])
        after = await bahan(db, jasa_ids=[dunia['jasa1']])
        assert [(r['tahap'], r['kg']) for r in after] == [('dalam_proses', 998)]
        assert await hitung_stok_silo(db, silo.id) == 998
    groups = per_tahap(await ringkasan(pg, dunia))
    active = next(g for g in groups if g['kunci']=='dalam_proses')['komoditas']
    assert len(active)==1 and active[0]['kunci']==jenis and active[0]['kg']==998
    assert not next(g for g in groups if g['kunci']=='menunggu')['komoditas']


async def test_alias_portal_menolak_label_pemilik_yang_sumbernya_asing(pg, dunia):
    from app.models import BerasKeSilo, PolishingOutputLog
    await _pk(pg, dunia, silo='C', jid=dunia['jasa1'], code='PKB-LABEL-SENDIRI')
    async with pg() as db:
        p = PolishingProcess(kode_proses='POL-SUMBER-RAHASIA', jasa_id=dunia['jasa3'],
            status='selesai', waktu_mulai=now_local(), waktu_selesai=now_local(), created_by=dunia['user'])
        db.add(p); await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis='medium', berat_kg=500,
            waktu_update=now_local(), input_by=dunia['user']))
        db.add(BerasKeSilo(kode_pindah='BRS-LABEL-SALAH', silo_id=dunia['silo']['C'], berat_kg=500,
            tanggal=date.today(), waktu=now_local(), input_by=dunia['user'], jasa_id=dunia['jasa1'],
            polishing_process_id=p.id, source_type='polishing', source_id=p.id, jenis='medium'))
        await db.commit()
    async with client(await _akun(pg, dunia)) as c:
        for path in ('/pelanggan/barang-saya', '/pelanggan/stok-pk-jasa'):
            r = await c.get(path)
            assert r.status_code == 200
            assert 'POL-SUMBER-RAHASIA' not in r.text
            assert 'Silo C' not in ''.join(s.get_text() for s in sections(r.text).values())


@pytest.mark.parametrize('fase', ['menunggu', 'pengeringan', 'pendinginan', 'dingin'])
async def test_bahan_di_dryer_dikelompokkan_dari_fase_sebenarnya(pg, dunia, fase):
    from app.models import DryingLot, DryingLotBatch
    from tests.pg.test_portal_transit import _batch_dryer
    batch_id = await _batch_dryer(pg, dunia, dryer=dunia['dryer'], jid=dunia['jasa1'], code='GB-DRYER-TAHAP')
    if fase!='menunggu':
        async with pg() as db:
            lot = DryingLot(kode_lot='PGR-TAHAP', dryer_id=dunia['dryer'], jasa_id=dunia['jasa1'],
                status='proses' if fase=='pengeringan' else 'selesai', created_by=dunia['user'],
                waktu_mulai_pengeringan=now_local(),
                waktu_selesai_pengeringan=None if fase=='pengeringan' else now_local(),
                waktu_selesai_pendinginan=now_local() if fase=='dingin' else None)
            db.add(lot); await db.flush()
            db.add(DryingLotBatch(drying_lot_id=lot.id, purchase_batch_id=batch_id))
            await db.commit()
    expected = 'menunggu' if fase in ('menunggu','dingin') else 'dalam_proses'
    async with pg() as db:
        rows = await bahan(db, jasa_ids=[dunia['jasa1']])
        assert len(rows)==1 and rows[0]['tahap']==expected and rows[0]['kg']==1500
    groups = per_tahap(await ringkasan(pg, dunia))
    assert [(g['kunci'],r['kg']) for g in groups for r in g['baris']] == [(expected,1500)]
