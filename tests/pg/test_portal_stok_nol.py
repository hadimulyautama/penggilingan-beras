"""Stok habis tidak mencabut login, riwayat, atau PDF pelanggan yang sah."""
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import json

import pytest
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import select, text

from app.database import now_local
from app.models import Jasa, MillingProcess, PurchaseBatch, User
from app.models.portal import PortalAccount
from app.services import barang_keluar as keluar
from app.services.jasa import sisa_jasa, tutup_pesanan
from app.penggilingan.gudang1.services.milling import start_milling, finish_milling
from app.web import security
from app.web.portal.security import COOKIE
from tests.pg.test_gabung_jasa import (dunia, _isi_silo_g1,
    test_gabah_kering_dryer_digabung_di_silo_yang_sama_lalu_digiling as _campur)
from tests.pg.test_jasa_ketaatan import _tiket
from tests.pg.test_portal_pelanggan import client, token
from tests.pg.skenario_silo import pastikan_silo_kosong

pytestmark = pytest.mark.asyncio
PASSWORD = 'ujiPortalNol2026'


async def login(c, username):
    page = await c.get('/pelanggan/masuk')
    assert page.status_code == 200
    result = await c.post('/pelanggan/masuk', data={
        'username': username, 'sandi': PASSWORD, '_csrf': token(page)})
    assert result.status_code == 303 and result.headers['location'] == '/pelanggan/'
    assert c.cookies.get(COOKIE)


async def ambil(pg, dunia, *, jid, mid, pid, kg, kode):
    async with pg() as db:
        u = await db.get(User, dunia['user'])
        result = await keluar.buat_perintah(db, user=u, jasa_id=jid,
            baris=[keluar.BarisPerintah(tipe='pk_langsung', milling_process_id=mid, berat_kg=kg)],
            no_polisi='AD 0 UJI')
        oid = result.rec.id
        await keluar.muat_semua(db, user=u, rec_id=oid)
        tid = await _tiket(db, kode=kode, berat=kg, pelanggan_id=pid, jasa_id=jid,
                           jenis='BERAS_PK', nopol='AD 0 UJI')
        await db.execute(text("""UPDATE timbangan_transaksi SET arah='KELUAR',
            nama_sopir='Sopir Uji',timbang2_kg=20000+:kg,timbang2_waktu=:w,
            netto_timbangan_kg=:kg,total_tara_kg=0,berat_barang_kg=:kg WHERE id=:id"""),
            {'kg':kg,'w':now_local(),'id':tid})
        await db.commit()
        rec, _ = await keluar.verifikasi(db, user=u, rec_id=oid, timbangan_transaksi_id=tid)
        assert rec.status == 'selesai'
        return oid, rec.kode


def pdf_text(response):
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['content-disposition'].startswith('attachment;')
    assert 'no-store' in response.headers['cache-control']
    reader = PdfReader(BytesIO(response.content))
    return '\n'.join(page.extract_text() for page in reader.pages)


@pytest.mark.parametrize('tutup', [False, True], ids=['stok-nol-pesanan-berjalan','stok-nol-pesanan-selesai'])
async def test_stok_habis_login_riwayat_pdf_dan_batas_pelanggan(pg, dunia, tutup):
    await _campur(pg, dunia)
    jid = min(dunia['jasa1'], dunia['jasa2'])
    async with pg() as db:
        own = await db.scalar(select(MillingProcess).where(MillingProcess.jasa_id == jid))
        mid, kode = own.id, own.kode_proses
        u = await db.get(User, dunia['user'])
        await pastikan_silo_kosong(db, user=u, kode_proses=kode)
        await finish_milling(db, user=u, kode_proses=kode, berat_akhir=3000)

    # Pelanggan lain benar-benar mempunyai riwayat dan stok positif.
    await _isi_silo_g1(pg, dunia, huruf='B', kode='GB-RAHASIA-POSITIF', kg=1000, jasa_id=dunia['jasa3'])
    async with pg() as db:
        u = await db.get(User, dunia['user'])
        result = await start_milling(db, user=u, nama_silo='B')
        foreign_mid, foreign_code = result.proc.id, result.proc.kode_proses
        await pastikan_silo_kosong(db, user=u, kode_proses=foreign_code)
        await finish_milling(db, user=u, kode_proses=foreign_code, berat_akhir=700)
        for name, pid in [('stok-nol-catur',dunia['catur']),('stok-nol-budi',dunia['budi'])]:
            db.add(PortalAccount(username=name, pelanggan_id=pid,
                password_hash=security.hash_sandi(PASSWORD), active=True, token_version=1))
        await db.commit()
        assert (await sisa_jasa(db, jid)).pk_g1_kg == 3000

    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
    for code, wet in [('GB-SATU-SILO-BASAH',True),('GB-SATU-SILO-KERING',False),
                      ('GB-RAHASIA-POSITIF',False)]:
        async with pg() as db:
            for _ in range(5):
                await catat_qc_gabah(db,user=await db.get(User,dunia['user']),kode_batch=code,
                    kadar_air_1=20 if wet else 14,kadar_air_2=21 if wet else 14,
                    biji_hijau='sedikit',densiti='padat',
                    lamur=False if wet else None,jumlah_sak_lamur=0 if wet else None)

    foreign_oid, foreign_out_code = await ambil(pg, dunia, jid=dunia['jasa3'],
        mid=foreign_mid, pid=dunia['budi'], kg=200, kode='KLR-RAHASIA-POSITIF')

    async with client() as c:
        await login(c, 'stok-nol-catur')
        assert (await c.get('/pelanggan')).status_code == 200
    oid, out_code = await ambil(pg, dunia, jid=jid, mid=mid,
        pid=dunia['catur'], kg=3000, kode='KLR-STOK-HABIS')
    async with pg() as db:
        remaining = await sisa_jasa(db, jid)
        assert remaining.total == 0 and not remaining.ada
        assert all(value == 0 for value in asdict(remaining).values())
        assert (await sisa_jasa(db, dunia['jasa3'])).pk_g1_kg == 500
        if tutup:
            await tutup_pesanan(db, user=await db.get(User, dunia['user']), jasa_id=jid)
        order = await db.get(Jasa, jid)
        assert order.status == ('selesai' if tutup else 'berjalan')
        batch = await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-SATU-SILO-BASAH'))
        own_batch_code = batch.kode_batch
        state = order.status

    report = dict(stockKg=asdict(remaining), orderStatus=state, realLoginBeforeAndAfter=True,
                  historyChecks=[], pdfChecks=[], deniedForeignPaths=[])
    forbidden = ['Budi','JAS-2610-303','GB-RAHASIA-POSITIF',foreign_code,foreign_out_code,'KLR-RAHASIA-POSITIF']
    pages = ['/pelanggan','/pelanggan/ringkasan','/pelanggan/pekerjaan',
        '/pelanggan/stok','/pelanggan/stok?tab=produk','/pelanggan/stok?tab=karung',
        '/pelanggan/barang-keluar','/pelanggan/riwayat-giling','/pelanggan/riwayat-pengeringan',
        '/pelanggan/riwayat-qc/gabah-basah','/pelanggan/laporan','/pelanggan/serah-terima',
        '/pelanggan/riwayat-qc/gabah-basah/GB-SATU-SILO-BASAH',
        f'/pelanggan/riwayat-giling/{mid}',f'/pelanggan/jasa/{jid}/nota',f'/pelanggan/barang-keluar/{oid}']
    out = Path('output/portal-stok-nol');out.mkdir(parents=True, exist_ok=True)
    # Sesi baru sesudah saldo nol: benar-benar POST username/password, tanpa menyuntik cookie.
    async with client() as c:
        await login(c, 'stok-nol-catur')
        for path in pages:
            r = await c.get(path)
            assert r.status_code == 200, (path,r.text[:200])
            assert all(value not in r.text for value in forbidden),path
            report['historyChecks'].append(dict(path=path,status=200))
        assert kode in (await c.get('/pelanggan/riwayat-giling')).text
        assert 'PGR-SATU-SILO' in (await c.get('/pelanggan/riwayat-pengeringan')).text
        assert own_batch_code in (await c.get('/pelanggan/riwayat-qc/gabah-basah')).text
        assert out_code in (await c.get('/pelanggan/barang-keluar')).text
        for label,path,expected in [
            ('rekap',f'/pelanggan/jasa/{jid}/nota.pdf?unduh=1','JAS-2610-301'),
            ('giling',f'/pelanggan/riwayat-giling/{mid}/laporan.pdf?unduh=1',kode),
            ('pengeluaran',f'/pelanggan/barang-keluar/{oid}/serah-terima.pdf?unduh=1',out_code)]:
            r=await c.get(path);body=pdf_text(r)
            assert expected in body and all(value not in body for value in forbidden)
            (out/f'{state}-{label}.pdf').write_bytes(r.content)
            report['pdfChecks'].append(dict(path=path,status=200,contentType='application/pdf',download=True))
        paths=[f'/pelanggan/jasa/{dunia["jasa3"]}/nota',f'/pelanggan/jasa/{dunia["jasa3"]}/nota.pdf?unduh=1',
            f'/pelanggan/riwayat-giling/{foreign_mid}',f'/pelanggan/riwayat-giling/{foreign_mid}/laporan.pdf?unduh=1',
            f'/pelanggan/barang-keluar/{foreign_oid}',f'/pelanggan/barang-keluar/{foreign_oid}/serah-terima.pdf?unduh=1',
            '/pelanggan/riwayat-qc/gabah-kering/GB-RAHASIA-POSITIF',
            f'/pelanggan/stok?pelanggan_id={dunia["budi"]}',
            f'/pelanggan/jasa/{jid}/nota.pdf?unduh=1&pelanggan_id={dunia["budi"]}']
        for path in paths:
            assert (await c.get(path)).status_code == 404,path
            report['deniedForeignPaths'].append(dict(path=path,status=404))
        for path in ['/pengaturan','/pengguna',f'/jasa/{jid}/nota.pdf']:
            assert (await c.get(path)).status_code in (303,401,403)
    # Objek asing tersebut memang tersedia bagi pemiliknya, bukan 404 karena datanya tidak ada.
    async with client() as c:
        await login(c, 'stok-nol-budi')
        for path in [f'/pelanggan/jasa/{dunia["jasa3"]}/nota.pdf?unduh=1',
                     f'/pelanggan/riwayat-giling/{foreign_mid}/laporan.pdf?unduh=1',
                     f'/pelanggan/barang-keluar/{foreign_oid}/serah-terima.pdf?unduh=1']:
            assert (await c.get(path)).status_code == 200
        assert (await c.get(f'/pelanggan/jasa/{jid}/nota.pdf?unduh=1')).status_code == 404
    (out/f'{state}-result.json').write_text(json.dumps(report,indent=2))
    (out/'browser-fixture.json').write_text(json.dumps(dict(jid=jid,mid=mid,oid=oid,
        foreignJid=dunia['jasa3'],foreignMid=foreign_mid,foreignOid=foreign_oid,
        kode=kode,outCode=out_code,foreignCode=foreign_code,foreignOutCode=foreign_out_code)))
