"""Koreksi fakta transfer menjaga tumpukan, silo, proses dan buku bersama."""
import copy
import asyncio
import uuid
from decimal import Decimal as D
import pytest
from sqlalchemy import select, func
from app.models import (User, PermintaanPk, PengirimanPk, PengirimanPkItem,
    InternalTransfer, PkGudang2Intake, PkTumpukanToSilo, PolishingSiloUsage,
    PolishingProcess, PolishingOutputLog, Peristiwa, Silo)
from app.models.peristiwa import ProyeksiTransferPk, ProyeksiPkMasukG2
from app.services import koreksi_transfer_pk as s, pengiriman_pk as kirim, peristiwa as buku
from app.services.transfer import saldo_pk, pending_transfer_kg
from app.penggilingan.gudang2 import service as g2, polishing as p
from hmu_core.proses_db import ProsesTerpadu, ArusProsesTerpadu
from tests.pg.test_pengiriman_pk_bertahap import siap
from tests.pg.test_permintaan_empat_langkah import pabrik
from tests.pg.test_transfer_tanpa_kendaraan import langsung
from tests.pg.test_masuk_detail_timbang import sidik

pytestmark = pytest.mark.asyncio


def req(kg=None, aksi='jumlah', **extra):
    return dict(aksi=aksi, berat_kg=None if kg is None else str(kg),
                alasan='Betulkan catatan sesuai pemindahan fisik', kunci=uuid.uuid4().hex, **extra)


async def simpan(db, w, body, *, jenis='transfer', ident=None):
    u = await db.get(User, w['admin'])
    ident = ident or (w['iid'] if jenis == 'transfer' else w['rid'])
    before = await sidik(db)
    review = await s.periksa(db, jenis=jenis, ident=ident, req=body, user=u)
    assert await sidik(db) == before, 'Pratinjau tidak boleh menulis tabel bisnis/audit'
    body.update(pemeriksaan=review['pemeriksaan'], konfirmasi=True)
    result = await s.simpan(db, jenis=jenis, ident=ident, req=body, user=u)
    return result, review['rancangan'], body


@pytest.fixture
async def tercatat(pg, siap):
    j = await langsung(pg, siap, '6000')
    async with pg() as db:
        i = await db.scalar(select(PengirimanPkItem).where(PengirimanPkItem.pengiriman_id == j['id']))
        it = await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id == i.internal_transfer_id))
        return dict(**siap, jid=j['id'], iid=i.id, tid=i.internal_transfer_id, intake=it.id)


async def proses(pg, w, *, pindah=4000, hasil=3000, sisa=0, selesai=True):
    from app.services.fasilitas import seed_fasilitas
    async with pg() as db:
        u = await db.get(User, w['op2'])
        from app.services.seed import seed_jenis_hasil
        await seed_jenis_hasil(db)
        await seed_fasilitas(db)
        await db.commit()
        await g2.pindah_tumpukan_ke_silo(db, user=u, intake_id=w['intake'], nama_silo='Silo A', berat=pindah)
        move = await db.scalar(select(PkTumpukanToSilo).where(PkTumpukanToSilo.pk_gudang2_intake_id == w['intake']))
        started = await p.mulai_penyosohan(db, user=u, nama_silos=['Silo A'])
        await p.catat_output(db, user=u, kode=started.proc.kode_proses, jenis='medium', berat_kumulatif=hasil)
        if selesai:
            await p.selesai_penyosohan(db, user=u, kode=started.proc.kode_proses, nama_silo='Silo A', sisa_kg=sisa)
            await p.akhiri_penyosohan(db, user=u, kode=started.proc.kode_proses)
        return dict(**w, pol=started.proc.id, kode=started.proc.kode_proses, move=move.id, silo=move.silo_id)


async def bahan(db, pid):
    return sum((u.berat_terpakai_kg if u.berat_akhir_kg is not None else u.berat_awal_kg + u.berat_masuk_kg)
        for u in (await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id == pid))).all())


async def test_koreksi_tumpukan_idempoten_dan_replay(pg, tercatat):
    w = tercatat
    async with pg() as db:
        t = await db.get(InternalTransfer, w['tid'])
        asal = copy.deepcopy((await db.get(Peristiwa, t.peristiwa_id)).muatan)
        result, plan, body = await simpan(db, w, req(5500))
        assert D(plan['tumpukan_before']) == 6000 and D(plan['tumpukan_after']) == 5500
        assert await g2._sisa_tumpukan_intake(db, w['intake']) == 5500
        assert await saldo_pk(db, w['proses_id']) == await pending_transfer_kg(db, w['proses_id'], bebas=True) == 500
        r = await db.get(PermintaanPk, w['rid'])
        assert r.status == 'selesai' and r.berat_setuju_kg == 6000 and r.berat_final_kg == 5500
        n = await db.scalar(select(func.count()).select_from(Peristiwa))
        repeated = await s.simpan(db, jenis='transfer', ident=w['iid'], req=body, user=await db.get(User, w['admin']))
        assert repeated['ulang'] and repeated['peristiwa_id'] == result['peristiwa_id']
        assert await db.scalar(select(func.count()).select_from(Peristiwa)) == n
        assert (await db.get(Peristiwa, t.peristiwa_id)).muatan == asal
        await buku.bangun_ulang(db)
        assert (await db.get(ProyeksiTransferPk, t.peristiwa_id)).berat_kg == 5500
        it = await db.get(PkGudang2Intake, w['intake'])
        assert (await db.get(ProyeksiPkMasukG2, it.peristiwa_id)).berat_kg == 5500


async def test_tumpukan_didahulukan_sebelum_produksi_selesai(pg, tercatat):
    w = await proses(pg, tercatat)
    async with pg() as db:
        _, plan, _ = await simpan(db, w, req(4500))
        assert plan['pk_chain']['processes'] == []
        assert await bahan(db, w['pol']) == 4000
        assert await g2._sisa_tumpukan_intake(db, w['intake']) == 500
        assert (await db.get(PkTumpukanToSilo, w['move'])).berat_kg == 4000


async def test_kurang_catat_bahan_memakai_tumpukan_tanpa_transfer_tambahan(pg, tercatat):
    w = await proses(pg, tercatat)
    async with pg() as db:
        _, plan, _ = await simpan(db, w, req(5000, aksi='bahan', pemindahan_id=w['move']))
        assert plan['items'] == plan['permintaan'] == []
        assert await bahan(db, w['pol']) == 5000
        assert await g2._sisa_tumpukan_intake(db, w['intake']) == 1000
        assert await saldo_pk(db, w['proses_id']) == 0
        assert (await db.get(InternalTransfer, w['tid'])).berat_kg == 6000
        assert (await db.get(PengirimanPkItem, w['iid'])).berat_kg == 6000
        assert await g2.hitung_stok_silo(db, w['silo']) == 0
        proc = plan['pk_chain']['processes'][0]
        assert D(proc['susut_before']) == 1000 and D(proc['susut_after']) == 2000
        await simpan(db, w, req(3500, aksi='bahan', pemindahan_id=w['move']))
        assert await bahan(db, w['pol']) == 3500
        assert await g2._sisa_tumpukan_intake(db, w['intake']) == 2500
        await buku.bangun_ulang(db)


async def test_tambahan_bahan_melebihi_tumpukan_ditolak(pg, tercatat):
    w = await proses(pg, tercatat)
    async with pg() as db:
        before = await sidik(db)
        with pytest.raises(kirim.PengirimanError, match='Sisa tumpukan tidak cukup'):
            await s.periksa(db, jenis='transfer', ident=w['iid'], req=req(6500, aksi='bahan', pemindahan_id=w['move']), user=await db.get(User, w['admin']))
        assert await sidik(db) == before


async def test_koreksi_melampaui_tumpukan_menghitung_ulang_proses_selesai(pg, tercatat):
    w = await proses(pg, tercatat)
    async with pg() as db:
        _, plan, _ = await simpan(db, w, req(3500))
        assert D(plan['pk_chain']['processes'][0]['susut_before']) == 1000
        assert D(plan['pk_chain']['processes'][0]['susut_after']) == 500
        assert await bahan(db, w['pol']) == 3500
        assert await g2._sisa_tumpukan_intake(db, w['intake']) == 0
        assert await g2.hitung_stok_silo(db, w['silo']) == 0
        assert await saldo_pk(db, w['proses_id']) == 2500
        proc = await db.get(PolishingProcess, w['pol'])
        assert proc.status == 'selesai'
        assert await db.scalar(select(func.sum(PolishingOutputLog.berat_kg)).where(PolishingOutputLog.polishing_process_id == proc.id)) == 3000
        combined = await db.scalar(select(ProsesTerpadu).where(ProsesTerpadu.tabel_sumber == 'polishing_process', ProsesTerpadu.id_sumber == str(proc.id)))
        assert combined.metadata_domain['berat_pk_terpakai_kg'] == 3500
        assert combined.metadata_domain['catatan_penutupan']['berat_pk_terpakai_kg'] == 4000
        total = await db.scalar(select(func.sum(ArusProsesTerpadu.berat_kg)).where(ArusProsesTerpadu.proses_id == combined.id, ArusProsesTerpadu.arah == 'bahan'))
        assert total == 3500
        from app.web.laporan_sosoh import ambil_data
        laporan = await ambil_data(proc.id)
        assert laporan['balance'].bahan_kg == 3500 and laporan['balance'].susut.kg == 500


async def test_sisa_silo_dikurangi_sebelum_bahan_terpakai(pg, tercatat):
    w = await proses(pg, tercatat, pindah=6000, hasil=3000, sisa=2000)
    async with pg() as db:
        await simpan(db, w, req(5000))
        assert await bahan(db, w['pol']) == 4000
        assert await g2.hitung_stok_silo(db, w['silo']) == 1000
        assert (await db.scalar(select(PolishingSiloUsage))).berat_akhir_kg == 1000


async def test_sisa_yang_dipakai_proses_berikutnya_ikut_disesuaikan(pg, tercatat):
    w = await proses(pg, tercatat, pindah=6000, hasil=3000, sisa=2000)
    async with pg() as db:
        u = await db.get(User, w['op2'])
        second = await p.mulai_penyosohan(db, user=u, nama_silos=['Silo A'])
        await p.catat_output(db, user=u, kode=second.proc.kode_proses, jenis='medium', berat_kumulatif=1000)
        await p.selesai_penyosohan(db, user=u, kode=second.proc.kode_proses, nama_silo='Silo A', sisa_kg=500)
        await p.akhiri_penyosohan(db, user=u, kode=second.proc.kode_proses)
        await simpan(db, w, req(5000))
        assert await bahan(db, w['pol']) == 4000
        assert await bahan(db, second.proc.id) == 1000
        assert await g2.hitung_stok_silo(db, w['silo']) == 0
        assert await saldo_pk(db, w['proses_id']) == 1000


async def test_tambahan_yang_sudah_diproses_ditautkan_ke_pemindahan_nyata(pg, tercatat):
    w = await proses(pg, tercatat, pindah=6000, hasil=3000)
    async with pg() as db:
        await simpan(db, w, req(4500))
        await simpan(db, w, req(5500, pemindahan_id=w['move']))
        assert await bahan(db, w['pol']) == 5500
        assert await g2._sisa_tumpukan_intake(db, w['intake']) == 0
        assert await g2.hitung_stok_silo(db, w['silo']) == 0
        assert await saldo_pk(db, w['proses_id']) == 500


async def test_hasil_melebihi_bahan_selesai_ditolak_tanpa_mutasi(pg, tercatat):
    w = await proses(pg, tercatat, pindah=6000, hasil=5500)
    async with pg() as db:
        before = await sidik(db)
        with pytest.raises(kirim.PengirimanError, match='hasil tercatat melebihi bahan'):
            await s.periksa(db, jenis='transfer', ident=w['iid'], req=req(5000), user=await db.get(User, w['admin']))
        assert await sidik(db) == before


async def test_proses_aktif_bahan_dikoreksi_dan_hasil_berlebih_menahan_penutupan(pg, tercatat):
    w = await proses(pg, tercatat, pindah=6000, hasil=5500, selesai=False)
    async with pg() as db:
        _, plan, _ = await simpan(db, w, req(5000))
        assert plan['pk_chain']['warnings'] and await bahan(db, w['pol']) == 5000
        u = await db.get(User, w['op2'])
        await p.selesai_penyosohan(db, user=u, kode=w['kode'], nama_silo='Silo A', sisa_kg=0)
        with pytest.raises(g2.Gudang2Error, match='hasil melebihi bahan'):
            await p.akhiri_penyosohan(db, user=u, kode=w['kode'])
        assert (await db.get(PolishingProcess, w['pol'])).status == 'proses'
        await db.rollback()
        await simpan(db, w, req(6000, pemindahan_id=w['move']))
        await p.akhiri_penyosohan(db, user=await db.get(User, w['op2']), kode=w['kode'])
        assert (await db.get(PolishingProcess, w['pol'])).status == 'selesai'


async def test_pembatalan_menjaga_item_nol_dan_permohonan_bisa_dibuka(pg, tercatat):
    w = tercatat
    async with pg() as db:
        await simpan(db, w, req(0))
        assert (await db.get(PengirimanPk, w['jid'])).status == 'dibatalkan'
        assert (await db.get(PengirimanPkItem, w['iid'])).berat_kg == 0
        assert (await db.get(InternalTransfer, w['tid'])).status == 'dibatalkan'
        assert await saldo_pk(db, w['proses_id']) == 6000
        await simpan(db, w, req(aksi='buka'), jenis='permintaan')
        assert (await db.get(PermintaanPk, w['rid'])).status == 'disetujui'
        assert await pending_transfer_kg(db, w['proses_id'], bebas=True) == 0
        await langsung(pg, w, '6000')


async def test_batal_sebelum_transfer_dan_kembali_ke_permintaan(pg, siap):
    w = siap
    async with pg() as db:
        await simpan(db, w, req(aksi='kembali'), jenis='permintaan')
        assert (await db.get(PermintaanPk, w['rid'])).status == 'diminta'
        assert await pending_transfer_kg(db, w['proses_id'], bebas=True) == 6000
        await simpan(db, w, req(5500, aksi='minta'), jenis='permintaan')
        assert (await db.get(PermintaanPk, w['rid'])).berat_minta_kg == 5500
        await simpan(db, w, req(aksi='batal'), jenis='permintaan')
        assert (await db.get(PermintaanPk, w['rid'])).status == 'gugur'
        assert await saldo_pk(db, w['proses_id']) == 6000


async def test_perubahan_persetujuan_dan_tujuan_hanya_sebelum_transfer(pg, siap):
    w = siap
    async with pg() as db:
        await simpan(db, w, req(5000, aksi='persetujuan', tujuan='Silo A'), jenis='permintaan')
        assert (await db.get(PermintaanPk, w['rid'])).berat_setuju_kg == 5000
        assert await pending_transfer_kg(db, w['proses_id'], bebas=True) == 1000
    await langsung(pg, w, '1000')
    async with pg() as db:
        with pytest.raises(kirim.PengirimanError, match='Tujuan transfer'):
            await simpan(db, w, req(5000, aksi='persetujuan', tujuan='Silo B'), jenis='permintaan')


async def test_saldo_atau_hasil_berubah_setelah_periksa_ditolak(pg, tercatat):
    w = await proses(pg, tercatat)
    async with pg() as db:
        u = await db.get(User, w['admin'])
        body = req(3500)
        review = await s.periksa(db, jenis='transfer', ident=w['iid'], req=body, user=u)
        db.add(PolishingOutputLog(polishing_process_id=w['pol'], jenis='medium', berat_kg=10, waktu_update=p.input_time(None), input_by=u.id))
        await db.commit()
        before = await sidik(db)
        with pytest.raises(kirim.PengirimanError, match='berubah'):
            await s.simpan(db, jenis='transfer', ident=w['iid'], req={**body, 'pemeriksaan':review['pemeriksaan'], 'konfirmasi':True}, user=u)
        assert await sidik(db) == before


async def test_gagal_sinkron_menggugurkan_seluruh_perubahan(pg, tercatat, monkeypatch):
    w = await proses(pg, tercatat)
    async with pg() as db:
        u = await db.get(User, w['admin'])
        body = req(3500)
        review = await s.periksa(db, jenis='transfer', ident=w['iid'], req=body, user=u)
        before = await sidik(db)
        async def gagal(*args, **kwargs):
            raise RuntimeError('Simulasi gagal sinkron')
        monkeypatch.setattr(s.rantai, 'sinkron_bahan', gagal)
        with pytest.raises(RuntimeError, match='Simulasi'):
            await s.simpan(db, jenis='transfer', ident=w['iid'], req={**body, 'pemeriksaan':review['pemeriksaan'], 'konfirmasi':True}, user=u)
        assert await sidik(db) == before


async def test_api_admin_saja_dan_ulang_setelah_putus_sambungan(pg, tercatat):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.web.pengiriman_pk import router
    from app.web.deps import pengguna_aksi
    app = FastAPI()
    app.include_router(router)
    w = tercatat
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://uji') as c:
        path = f'/api/transfer-bertahap/koreksi/transfer/{w["iid"]}'
        for who in ('op1', 'op2'):
            async with pg() as db:
                u = await db.get(User, w[who])
            app.dependency_overrides[pengguna_aksi] = lambda: u
            assert (await c.post(path + '/periksa', json=req(5000))).status_code == 403
            assert (await c.post(path + '/simpan', json=req(5000))).status_code == 403
        async with pg() as db:
            u = await db.get(User, w['admin'])
        app.dependency_overrides[pengguna_aksi] = lambda: u
        body = req(5000)
        review = await c.post(path + '/periksa', json=body)
        assert review.status_code == 200, review.text
        body.update(pemeriksaan=review.json()['pemeriksaan'], konfirmasi=True)
        first = await c.post(path + '/simpan', json=body)
        assert first.status_code == 200, first.text
        again = await c.post(path + '/simpan', json=body)
        assert again.status_code == 200 and again.json()['ulang']
        history = await c.get('/api/transfer-bertahap')
        assert history.status_code == 200, history.text
        audit = history.json()['koreksi'][0]
        assert audit['alasan'] == body['alasan'] and '5000 kg' in ' '.join(audit['ringkasan'])


async def test_koreksi_transfer_sebagian_mempertahankan_cadangan_sisa(pg, siap):
    w = siap
    j = await langsung(pg, w, '2000')
    async with pg() as db:
        i = await db.scalar(select(PengirimanPkItem).where(PengirimanPkItem.pengiriman_id == j['id']))
        await simpan(db, {**w, 'iid': i.id}, req(1500))
        r = await db.get(PermintaanPk, w['rid'])
        assert r.status == 'dikirim' and r.berat_kirim_kg == 1500 and r.berat_final_kg is None
        assert await kirim.sisa(db, r) == 4500
        assert await saldo_pk(db, w['proses_id']) == 4500
        assert await pending_transfer_kg(db, w['proses_id'], bebas=True) == 0


async def test_koreksi_sama_serentak_hanya_satu_peristiwa(pg, tercatat):
    w = tercatat
    async with pg() as db:
        body = req(5000)
        review = await s.periksa(db, jenis='transfer', ident=w['iid'], req=body, user=await db.get(User, w['admin']))
        body.update(pemeriksaan=review['pemeriksaan'], konfirmasi=True)
    async def tulis():
        async with pg() as db:
            return await s.simpan(db, jenis='transfer', ident=w['iid'], req=body, user=await db.get(User, w['admin']))
    results = await asyncio.gather(tulis(), tulis())
    assert results[0]['peristiwa_id'] == results[1]['peristiwa_id']
    async with pg() as db:
        assert await saldo_pk(db, w['proses_id']) == 1000
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis == s.JENIS)) == 1


@pytest.mark.parametrize('nilai', ['NaN', 'Infinity', '-1', '1e100000', '10000000000', '0.001'])
async def test_angka_tidak_sah_tidak_menulis(pg, tercatat, nilai):
    async with pg() as db:
        before = await sidik(db)
        with pytest.raises(kirim.PengirimanError, match='kg yang sah'):
            await s.periksa(db, jenis='transfer', ident=tercatat['iid'], req=req(nilai), user=await db.get(User, tercatat['admin']))
        assert await sidik(db) == before


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('aksi', ['jumlah', 'bahan'])
async def test_browser_koreksi_dari_baris_transfer_sampai_neraca(pg, tercatat, width, aksi):
    from urllib.parse import urlsplit
    from pathlib import Path
    from playwright.async_api import async_playwright, expect
    from tests.pg.test_riwayat_giling import _klien
    w = await proses(pg, tercatat)
    base = 'http://127.0.0.1:59996'
    async with await _klien(pg, peran='admin') as c, async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport=dict(width=width, height=1000))
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        async def app(route):
            request = route.request
            url = urlsplit(request.url)
            if not request.url.startswith(base + '/'):
                await route.abort()
                return
            if url.path == '/api/aliran':
                await route.fulfill(status=204, body='')
                return
            response = await c.request(request.method, url.path + ('?' + url.query if url.query else ''),
                content=request.post_data_buffer, headers={k:v for k,v in request.headers.items() if k.lower() in ('content-type', 'x-csrf-token')})
            await route.fulfill(status=response.status_code, headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length', 'content-encoding', 'transfer-encoding')}, body=response.content)
        await page.context.add_cookies([dict(name=x.name, value=x.value, url=base) for x in c.cookies.jar])
        await page.route('**/*', app)
        await page.goto(base + '/transfer-bertahap')
        await page.get_by_role('button', name='Koreksi jumlah', exact=True).click()
        dialog = page.locator('#pk-koreksi')
        await expect(dialog).to_be_visible()
        if aksi == 'bahan':
            await dialog.locator('[name=aksi]').select_option('bahan')
        amount = 3500 if aksi == 'jumlah' else 5000
        await dialog.locator('[name=berat_kg]').fill(str(amount))
        await dialog.locator('[name=alasan]').fill('Kelebihan catat; sesuai pemeriksaan fisik')
        await dialog.get_by_role('button', name='Periksa dampak', exact=True).click()
        await expect(dialog.locator('#pk-koreksi-dampak')).to_contain_text('Bahan proses')
        await expect(dialog.locator('#pk-koreksi-dampak')).to_contain_text('3.500 kg' if aksi == 'jumlah' else '5.000 kg')
        await expect(dialog.get_by_role('button', name='Simpan koreksi', exact=True)).to_be_disabled()
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        Path('tmp').mkdir(exist_ok=True)
        await dialog.screenshot(path=f'tmp/koreksi-transfer-pk-{aksi}-{width}.png')
        await dialog.locator('[name=konfirmasi]').check()
        await dialog.get_by_role('button', name='Simpan koreksi', exact=True).click()
        await expect(dialog).not_to_be_visible()
        await expect(page.locator('#pk-pesan')).to_contain_text('Koreksi #')
        assert not errors, errors
        await browser.close()
    async with pg() as db:
        assert await bahan(db, w['pol']) == amount
        if aksi == 'bahan':
            assert await saldo_pk(db, w['proses_id']) == 0
            assert await g2._sisa_tumpukan_intake(db, w['intake']) == 1000
