"""Regresi Kabar atas pengguna, sesi HTTP, migrasi dan PostgreSQL sungguhan."""
import re
import pytest
from sqlalchemy import select, update, func
from fastapi import HTTPException
from app.models import Notification, User, NotificationRead
from app.services import kabar as svc
from tests.pg.test_kabar import orang, _tulis
from tests.pg.test_grup_keputusan_http import _klien

pytestmark = pytest.mark.asyncio


async def test_status_pribadi_seluruh_histori_dan_tidak_mengubah_peristiwa(pg, orang):
    for i in range(65):
        await _tulis(pg, tipe='permintaan_pk', untuk='operator', pesan=f'kabar {i}', umur_hari=30 if i < 10 else 0)
    async with pg() as db:
        a, b = await db.get(User, orang['op1']), await db.get(User, orang['op2'])
        assert len(await svc.daftar(db, a, batas=30)) == 30
        assert await svc.jumlah_baru(db, a) == 65
        await svc.tandai(db, a, dibaca=True)
        assert await svc.jumlah_baru(db, a) == 0
        assert await svc.jumlah_baru(db, b) == 65
        assert len(await svc.daftar(db, a)) == 65
        assert set(await db.scalars(select(Notification.status))) == {'baru'}
        assert await db.scalar(select(func.count()).select_from(Notification)) == 65
        id_ = (await svc.daftar(db, a))[0].id
        await svc.tandai(db, a, dibaca=False, id_=id_)
    async with pg() as db:
        a = await db.get(User, orang['op1'])
        assert await svc.jumlah_baru(db, a) == 1
        assert len(await svc.daftar(db, a, belum=True)) == 1


async def test_bawaan_histori_dan_penanda_belum_dibaca(pg, orang):
    id_ = await _tulis(pg, tipe='lama', untuk='admin', pesan='histori')
    async with pg() as db:
        await db.execute(update(Notification).where(Notification.id == id_).values(status='selesai'))
        await db.commit()
        a = await db.get(User, orang['admin'])
        assert not (await svc.daftar(db, a))[0].baru
        await svc.tandai(db, a, dibaca=False, id_=id_)
        assert (await svc.daftar(db, a))[0].baru
        assert await db.scalar(select(Notification.status)) == 'selesai'


async def test_filter_kombinasi_dan_snapshot_pemuatan(pg, orang):
    ids = [await _tulis(pg, tipe='a' if i % 2 else 'b', untuk='admin', pesan=str(i)) for i in range(38)]
    async with pg() as db:
        a = await db.get(User, orang['admin'])
        await svc.tandai(db, a, dibaca=True, id_=ids[-1])
        assert len(await svc.daftar(db, a, jenis='a', belum=True)) == 18
        awal = await svc.daftar(db, a, batas=30, sampai=ids[-1])
    await _tulis(pg, tipe='a', untuk='admin', pesan='baru datang')
    async with pg() as db:
        a = await db.get(User, orang['admin'])
        lanjut = await svc.daftar(db, a, batas=60, sampai=ids[-1])
        assert len(lanjut) == 38
        assert [k.id for k in awal] == [k.id for k in lanjut[:30]]
        assert len({k.id for k in lanjut}) == 38
        assert await svc.jumlah_baru(db, a) == 38


async def test_api_cakupan_dan_mutasi_terlarang(pg, orang):
    rahasia = await _tulis(pg, tipe='harga', untuk='admin', pesan='RAHASIA ADMIN')
    g1 = await _tulis(pg, tipe='pengeringan_telat', untuk='operator', pesan='KHUSUS G1')
    for peran, total in [('admin', 1), ('op1', 1), ('op2', 0)]:
        async with await _klien(pg, orang[peran]) as c:
            r = await c.get('/kabar')
            assert r.status_code == 200
            assert (await c.get('/api/kabar/jumlah')).json()['belum'] == total
            if peran != 'admin':
                assert 'RAHASIA ADMIN' not in r.text
            if peran == 'op2':
                assert 'KHUSUS G1' not in r.text
                assert (await c.get('/kabar?tab=belum&sampai=0')).status_code == 200
            token = re.search(r'name="_csrf" value="([^"]+)"', r.text)[1]
            if peran == 'op2':
                for id_ in [rahasia, g1]:
                    r = await c.post('/kabar/status', data={'_csrf':token,'id':id_,'status':'dibaca'})
                    assert r.status_code == 404
                    r = await c.post(f'/kabar/{id_}/buka', data={'_csrf':token})
                    assert r.status_code == 404
                assert (await c.post('/kabar/status', data={'id':g1,'status':'dibaca'})).status_code == 403
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(NotificationRead)) == 0


async def test_http_status_kembali_filter_dan_catatan_hilang(pg, orang):
    id_ = await _tulis(pg, tipe='permintaan_pk', untuk='admin', pesan='satu')
    konteks = '/kabar?tab=belum&jenis=permintaan_pk&batas=60&sampai=1'
    async with await _klien(pg, orang['admin']) as c:
        c.follow_redirects = False
        r = await c.get('/kabar')
        token = re.search(r'name="_csrf" value="([^"]+)"', r.text)[1]
        r = await c.post('/kabar/status', data={'_csrf':token,'id':id_,'status':'dibaca','kembali':konteks})
        assert r.status_code == 303 and r.headers['location'] == konteks
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 0
        assert 'Sudah dibaca' in (await c.get('/kabar')).text
        assert 'class="kb-item"' not in (await c.get('/kabar?tab=belum')).text
        await c.post('/kabar/status', data={'_csrf':token,'id':id_,'status':'belum'})
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 1
        r = await c.post(f'/kabar/{id_}/buka', data={'_csrf':token,'kembali':konteks})
        assert r.status_code == 200 and 'Catatan tidak tersedia' in r.text
        assert 'tab=belum' in r.text and 'batas=60' in r.text
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 0
        assert (await c.post('/kabar/status', data={'_csrf':token,'status':'belum'})).status_code == 422


async def test_tujuan_terstruktur_tidak_menebak_judul(pg, orang):
    from types import SimpleNamespace
    async with pg() as db:
        a = await db.get(User, orang['admin'])
        for tabel in [None, 'tidak_dikenal', 'purchase_batches', 'drying_lots', 'outgoing_records']:
            n = SimpleNamespace(table_name=tabel, record_id=999999, pesan='Hasil QC transfer tiket', tipe='apa_saja')
            assert await svc.tujuan(db, a, n) is None


from tests.pg.test_permintaan_pk import pabrik, _minta
from tests.pg.test_proses_aktif_detail import pengeringan, dryer_pabrik


async def test_buka_proses_asli_menandai_tanpa_mengubah_proses(pg, pengeringan):
    from app.models import DryingLot
    from tests.pg.test_riwayat_giling import _klien as klien_peran
    async with pg() as db:
        n = Notification(tipe='pengeringan_telat', target_role='operator', pesan='judul boleh berubah',
                         table_name='drying_lots', record_id=pengeringan['id'])
        db.add(n)
        await db.commit()
        nid = n.id
        sebelum = (await db.get(DryingLot, pengeringan['id'])).status
    async with await klien_peran(pg, peran='operator', gudang='Gudang 1') as c:
        r = await c.get('/kabar')
        token = re.search(r'name="_csrf" value="([^"]+)"', r.text)[1]
        konteks = '/kabar?tab=belum&jenis=pengeringan_telat&batas=30'
        r = await c.post(f'/kabar/{nid}/buka', data={'_csrf':token, 'kembali':konteks})
        assert r.status_code == 200 and r.url.path == f"/proses-aktif/pengeringan/{pengeringan['kode']}"
        assert 'kembali_kerja' in str(r.url)
        from html import escape
        assert escape(konteks, quote=True) in r.text
    async with pg() as db:
        assert (await db.get(DryingLot, pengeringan['id'])).status == sebelum
        assert (await db.get(Notification, nid)).status == 'baru'


async def test_permintaan_catatan_saat_ini_dan_potret(pg, pabrik):
    import os
    from pathlib import Path
    from app.models import PermintaanPk
    await _minta(pg, pabrik['op2'])
    async with pg() as db:
        nid = await db.scalar(select(Notification.id).where(Notification.target_role == 'admin'))
        p = await db.scalar(select(PermintaanPk))
        status_awal = p.status
    async with await _klien(pg, pabrik['adm']) as c:
        r = await c.get('/kabar')
        assert pabrik['lot'] in r.text or 'Permintaan' in r.text
        token = re.search(r'name="_csrf" value="([^"]+)"', r.text)[1]
        asal = await c.post(f'/kabar/{nid}/buka', data={'_csrf':token,'kembali':'/kabar?tab=belum&jenis=permintaan_pk'})
        assert asal.status_code == 200 and 'Status saat ini' in asal.text
        assert pabrik['lot'] in asal.text
        async with pg() as db:
            assert (await db.get(PermintaanPk, p.id)).status == status_awal
        if os.environ.get('UJI_KABAR_POTRET'):
            from datetime import timedelta
            from app.database import now_local
            async with pg() as db:
                for i in range(34):
                    db.add(Notification(tipe='permintaan_pk', target_role='admin',
                        pesan=f'Permintaan transfer PK {pabrik["lot"]} — catatan peristiwa ke-{i+1}.',
                        table_name='permintaan_pk', record_id=p.id, prioritas='kuning',
                        created_at=now_local()-timedelta(hours=i)))
                await db.commit()
            out = Path('output/kabar401'); out.mkdir(parents=True, exist_ok=True)
            for theme in ('1','0'):
                c.cookies.set('produksi_terik', theme)
                page = await c.get('/kabar')
                out.joinpath(f'kabar-{theme}.html').write_text(page.text)
            # Baseline tampilan dari Git, memakai pengguna dan kumpulan kabar
            # yang sama. Hanya tubuh daftar digambar ulang, tanpa mutasi GET lama.
            import subprocess
            from app.web.tampilan import templates
            old = subprocess.check_output(['git','show','HEAD:hmu_tampilan/templates/kabar.html'],text=True)
            old = old.replace('{% extends "base.html" %}', '').replace('{% block judul %}Kabar{% endblock %}', '')
            async with pg() as db:
                user = await db.get(User, pabrik['adm'])
                rows = await svc.daftar(db, user)
                body = templates.env.from_string(old).render(kabar=rows, baru=sum(k.baru for k in rows), hari=7)
            baseline = re.sub(r'<section class="kb".*?</section>', body, page.text, count=1, flags=re.S)
            out.joinpath('kabar-lama.html').write_text(baseline)


async def test_kursor_tanggal_sama_tidak_mengulang(pg, orang):
    ids = [await _tulis(pg, tipe='uji', untuk='admin', pesan=str(i)) for i in range(65)]
    async with pg() as db:
        a = await db.get(User, orang['admin'])
        waktu = await db.scalar(select(Notification.created_at).where(Notification.id == ids[0]))
        await db.execute(update(Notification).values(created_at=waktu))
        await db.commit()
        semua, sebelum = [], None
        for _ in range(3):
            rows = await svc.daftar(db, a, batas=30, sampai=ids[-1], sebelum=sebelum)
            semua.extend(k.id for k in rows)
            sebelum = rows[-1].id
        assert semua == list(reversed(ids))


async def test_gagal_simpan_tidak_ditampilkan_berhasil(pg, orang, monkeypatch):
    import httpx
    from app.main import app
    id_ = await _tulis(pg, tipe='uji', untuk='admin', pesan='uji gagal')
    async with await _klien(pg, orang['admin']) as c:
        r = await c.get('/kabar')
        token = re.search(r'name="_csrf" value="([^"]+)"', r.text)[1]
        async def gagal(*a, **kw):
            raise RuntimeError('simulasi gagal penyimpanan')
        monkeypatch.setattr(svc, 'tandai', gagal)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://uji',cookies=c.cookies) as d:
            r = await d.post('/kabar/status',data={'_csrf':token,'id':id_,'status':'dibaca'})
            assert r.status_code == 500
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 1


@pytest.mark.parametrize('peran', ['operator','admin','superadmin'])
async def test_kabar_dengan_sesi_tiap_peran(pg, peran):
    from tests.pg.test_riwayat_giling import _klien as klien_peran
    await _tulis(pg, tipe='uji', untuk=None, pesan='lintas peran')
    async with await klien_peran(pg, peran=peran, gudang='Gudang 1') as c:
        assert (await c.get('/kabar')).status_code == 200
        assert (await c.get('/api/kabar/jumlah')).json()['belum'] == 1


from tests.pg.test_qc_berjalan import giling, _catat


async def test_tujuan_giling_dan_hasil_qc_sesuai_identitas(pg, giling):
    from app.models import MillingQcLog, MillingProcess
    from tests.pg.test_riwayat_giling import _klien as klien_peran
    await _catat(pg, giling, kadar_air=13, broken=5, susut=1)
    async with pg() as db:
        qc = await db.scalar(select(MillingQcLog))
        n = Notification(tipe='hasil_qc', target_role='admin', pesan='judul bebas',
                         table_name='milling_qc_logs', record_id=qc.id)
        db.add(n)
        await db.commit()
        nid = n.id
        user = await db.get(User, giling['user'])
        from app.models import Silo
        proc = await db.get(MillingProcess, giling['id'])
        user.default_warehouse_id = (await db.get(Silo, proc.silo_id)).warehouse_id
        await db.commit()
        assert await svc.tujuan(db, user, n) == f"/riwayat-qc/pk-hasil-giling/{giling['kode']}"
        from types import SimpleNamespace
        assert await svc.tujuan(db, user, SimpleNamespace(table_name='milling_process',record_id=giling['id'])) == f"/proses-aktif/giling/{giling['kode']}"
    async with await klien_peran(pg, peran='admin') as c:
        r = await c.get('/kabar')
        token = re.search(r'name="_csrf" value="([^"]+)"', r.text)[1]
        r = await c.post(f'/kabar/{nid}/buka',data={'_csrf':token,'kembali':'/kabar?jenis=hasil_qc'})
        assert r.status_code == 200 and r.url.path == f"/riwayat-qc/pk-hasil-giling/{giling['kode']}"
        assert 'Kadar air' in r.text
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(MillingQcLog)) == 1
        assert (await db.get(MillingProcess,giling['id'])).status == 'proses'


async def test_pengelompokan_waktu_memakai_zona_pabrik(pg, orang):
    from datetime import datetime, timezone
    id_ = await _tulis(pg, tipe='uji', untuk='admin', pesan='tengah malam WIB')
    async with pg() as db:
        await db.execute(update(Notification).where(Notification.id == id_).values(created_at=datetime(2026,10,22,18,3,tzinfo=timezone.utc)))
        await db.commit()
    async with await _klien(pg, orang['admin']) as c:
        r = await c.get('/kabar')
        assert '23/10/2026' in r.text and '23/10 01:03' in r.text


async def test_membaca_tidak_membuat_scheduler_mengirim_ganda(pg, pengeringan):
    from app.penggilingan.gudang1.services.drying import check_late_drying
    async with pg() as db:
        assert len(await check_late_drying(db, 0)) == 1
        user = await db.get(User, pengeringan['user'])
        await svc.tandai(db, user, dibaca=True)
        assert await check_late_drying(db, 0) == []
        assert await db.scalar(select(func.count()).select_from(Notification).where(Notification.tipe=='pengeringan_telat')) == 1
        assert await db.scalar(select(Notification.status).where(Notification.tipe=='pengeringan_telat')) == 'baru'
