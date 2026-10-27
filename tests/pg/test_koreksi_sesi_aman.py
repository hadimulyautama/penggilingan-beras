"""Regresi koreksi, pratinjau pembatalan, dan perangkat bersama — PostgreSQL nyata."""

from tests.pg.kontak import pelanggan_kledo
import asyncio
import re
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, func

from app.main import app
from app.models import User, ProduksiAkun, MillingProcess, ActivityLog
from app.database import now_local
from app.web import csrf, security
from app.services import undo
from tests.pg.test_riwayat_giling import pabrik, _giling_selesai

pytestmark = pytest.mark.asyncio


def cap(c, token=None, gudang=None):
    return csrf.untuk_sesi(c.cookies.get(csrf.NAMA_COOKIE),
        security.baca_token(token or c.cookies.get(security.NAMA_COOKIE)),
        gudang if gudang is not None else c.cookies.get('produksi_lihat', ''))


async def klien(pg, nama='A', mode='pribadi'):
    from hmu_identitas.sandi import hash_sandi
    async with pg() as db:
        u = User(nama=nama, role='superadmin', status='aktif')
        db.add(u); await db.flush()
        a = ProduksiAkun(user_id=u.id, username=nama.lower(), password_hash=hash_sandi('UjiKoreksi2026'),
                         status='aktif', harus_ganti_sandi=False, mode_perangkat=mode)
        db.add(a); await db.commit()
        token = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://uji')
    c.cookies.set(security.NAMA_COOKIE, token, domain='uji.local')
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru(), domain='uji.local')
    return c, u.id


async def giling(pg, pabrik):
    kode = await _giling_selesai(pg, pabrik)
    async with pg() as db:
        return await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses == kode))


async def test_koreksi_ditolak_menjaga_angka_dan_alasan(pg, pabrik):
    p = await giling(pg, pabrik)
    c, _ = await klien(pg)
    async with c:
        r = await c.post(f'/riwayat-giling/{p.id}/koreksi', data={
            '_csrf':cap(c), 'hasil_pk':'-7.25', 'dasar_pk':'6500', 'alasan':'Jangan hilangkan alasan saya'})
    assert r.status_code == 422
    assert 'value="-7.25"' in r.text and 'Jangan hilangkan alasan saya</textarea>' in r.text
    assert 'Saya sudah memeriksa nilai terbaru' in r.text
    async with pg() as db:
        assert not await db.scalar(select(ActivityLog.id).where(ActivityLog.aksi == 'koreksi_hasil_giling'))


async def test_konflik_menampilkan_pembanding_dan_minta_periksa_ulang(pg, pabrik):
    p = await giling(pg, pabrik)
    c, _ = await klien(pg)
    async with c:
        url = f'/riwayat-giling/{p.id}/koreksi'
        data = {'_csrf':cap(c), 'hasil_pk':'6400', 'dasar_pk':'6500', 'alasan':'Koreksi pertama'}
        assert (await c.post(url, data=data)).status_code == 303
        data.update(hasil_pk='6300', alasan='Angka tab lama')
        r = await c.post(url, data=data)
        assert r.status_code == 422
        assert '6400' in r.text and 'value="6300"' in r.text and 'Angka tab lama</textarea>' in r.text
        data.update(dasar_pk='6400', wajib_periksa='1')
        assert (await c.post(url, data=data)).status_code == 422
        data['periksa_ulang'] = 'ya'
        assert (await c.post(url, data=data)).status_code == 303


async def test_formulir_A_dengan_sesi_B_ditolak_server(pg, pabrik):
    p = await giling(pg, pabrik)
    a, _ = await klien(pg, 'A'); b, _ = await klien(pg, 'B')
    async with a, b:
        halaman = await a.get(f'/riwayat-giling/{p.id}')
        token_form = re.search(r'name="_csrf" value="([^"]+)"', halaman.text)[1]
        a.cookies.set(security.NAMA_COOKIE, b.cookies.get(security.NAMA_COOKIE), domain='uji.local')
        # Nonce sengaja sama: cap server juga harus memeriksa identitas, bukan hanya rotasi cookie.
        r = await a.post(f'/riwayat-giling/{p.id}/koreksi', data={
            '_csrf':token_form, 'hasil_pk':'6400', 'dasar_pk':'6500', 'alasan':'Tab A'})
    assert r.status_code == 403
    assert 'identitas pembuka' in r.text
    async with pg() as db:
        assert not await db.scalar(select(ActivityLog.id).where(ActivityLog.aksi == 'koreksi_hasil_giling'))


async def test_gudang_sama_akun_membatalkan_cap_formulir_lama(pg):
    c, _ = await klien(pg)
    async with c:
        lama = cap(c)
        c.cookies.set('produksi_lihat','operator:g2', domain='uji.local')
        r = await c.post('/lihat-sebagai/selesai', data={'_csrf':lama})
        assert r.status_code == 403
        r = await c.post('/lihat-sebagai/selesai', data={'_csrf':cap(c)})
        assert r.status_code == 303


async def test_keluar_masuk_reset_gudang_dan_nonce(pg):
    c, _ = await klien(pg)
    async with c:
        c.cookies.set('produksi_lihat','operator:g2', domain='uji.local')
        lama = c.cookies.get(csrf.NAMA_COOKIE)
        r = await c.post('/keluar', data={'_csrf':cap(c)})
        assert r.status_code == 303
        assert 'produksi_lihat=""' in ','.join(r.headers.get_list('set-cookie'))
        assert c.cookies.get(csrf.NAMA_COOKIE) != lama
        # Masuk kembali tetap menghasilkan nonce baru dan gudang bawaan.
        await c.get('/masuk')
        token = c.cookies.get(csrf.NAMA_COOKIE)
        r = await c.post('/masuk', data={'_csrf':token,'username':'a','sandi':'UjiKoreksi2026'})
        assert r.status_code == 303
        assert c.cookies.get(csrf.NAMA_COOKIE) != token


async def test_pratinjau_menolak_umur_dukungan_dan_hilir_tanpa_mutasi(pg, pabrik):
    p = await giling(pg, pabrik)
    async with pg() as db:
        log = await db.scalar(select(ActivityLog).where(ActivityLog.aksi == 'selesai_giling_terperiksa').order_by(ActivityLog.id.desc()))
        if log is None:
            log = await db.scalar(select(ActivityLog).where(ActivityLog.table_name == 'milling_process').order_by(ActivityLog.id.desc()))
        log.waktu_perubahan = now_local() - timedelta(hours=49)
        await db.commit()
        assert '48 jam' in await undo.sebab_terkunci(db, log)
        log.waktu_perubahan = now_local(); log.aksi = 'koreksi_hasil_giling'; await db.commit()
        assert 'Catatan hasil' in await undo.sebab_terkunci(db, log)
        log.aksi = 'selesai_giling_terperiksa'; await db.commit()
        jumlah = await db.scalar(select(func.count(ActivityLog.id)))
        assert await undo.sebab_terkunci(db, log) is None
        proc = await db.get(MillingProcess,p.id)
        await db.refresh(proc)
        assert proc.status == 'selesai'
        assert await db.scalar(select(func.count(ActivityLog.id))) == jumlah
        from app.services.transfer import create_internal_transfer
        await create_internal_transfer(db,user=await db.get(User,pabrik['user']),kode_proses=p.kode_proses,lokasi_tujuan='ditumpuk',berat=100)
        assert await undo.sebab_terkunci(db, log) is not None


async def test_penghalang_transfer_memuat_kode_jumlah_status_dan_tautan(pg,pabrik):
    p = await giling(pg,pabrik)
    from app.services.transfer import create_internal_transfer
    async with pg() as db:
        await create_internal_transfer(db,user=await db.get(User,pabrik['user']),kode_proses=p.kode_proses,lokasi_tujuan='ditumpuk',berat=100)
    c,_ = await klien(pg)
    async with c:
        r = await c.get(f'/riwayat-giling/{p.id}')
    assert r.status_code == 200
    assert '/riwayat-transfer/' in r.text and '100.0 kg' in r.text and 'terkirim' in r.text
    assert 'Tidak ada pekerjaan hilir yang dibatalkan otomatis' in r.text


async def test_simpan_yang_sudah_diterima_tetap_milik_A_saat_cookie_berganti(pg,pabrik,monkeypatch):
    p = await giling(pg,pabrik)
    from app.penggilingan.gudang1.services import milling
    mulai, lanjut = asyncio.Event(), asyncio.Event()
    asli = milling.koreksi_hasil_giling
    async def tunggu(*a,**kw):
        mulai.set(); await lanjut.wait()
        return await asli(*a,**kw)
    monkeypatch.setattr(milling,'koreksi_hasil_giling',tunggu)
    a, aid = await klien(pg,'A',mode='bersama'); b,_ = await klien(pg,'B',mode='bersama')
    async with a,b:
        task = asyncio.create_task(a.post(f'/riwayat-giling/{p.id}/koreksi',data={
            '_csrf':cap(a),'hasil_pk':'6400','dasar_pk':'6500','alasan':'Simpan sedang berjalan'}))
        await asyncio.wait_for(mulai.wait(),5)
        a.cookies.set(security.NAMA_COOKIE,b.cookies.get(security.NAMA_COOKIE),domain='uji.local')
        lanjut.set()
        hasil = await task
        assert hasil.status_code == 303
        assert not any(h.startswith(security.NAMA_COOKIE+"=") for h in hasil.headers.get_list("set-cookie"))
    async with pg() as db:
        log = await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='koreksi_hasil_giling'))
        assert log.changed_by == aid

@pytest.mark.parametrize('jenis', ['sosoh','transfer'])
async def test_koreksi_sosoh_transfer_ditolak_menjaga_semua_isian(pg,pabrik,jenis):
    c,_ = await klien(pg)
    if jenis == 'sosoh':
        from tests.pg.test_riwayat_sosoh import _sosoh_selesai
        from app.models import PolishingProcess
        kode = await _sosoh_selesai(pg,pabrik['user'],hasil=(('medium',500),('broken',200)))
        async with pg() as db:
            id_ = await db.scalar(select(PolishingProcess.id).where(PolishingProcess.kode_proses==kode))
        data={'hasil_medium':'501','hasil_broken':'-2.50','dasar_medium':'500','dasar_broken':'200'}
    else:
        p = await giling(pg,pabrik)
        from app.services.transfer import create_internal_transfer
        from app.models import InternalTransfer
        async with pg() as db:
            await create_internal_transfer(db,user=await db.get(User,pabrik['user']),kode_proses=p.kode_proses,lokasi_tujuan='ditumpuk',berat=100)
            id_ = await db.scalar(select(InternalTransfer.id))
        data={'hasil_transfer':'-2.50','dasar_transfer':'100'}
    async with c:
        data.update(_csrf=cap(c), alasan='Alasan lengkap tetap ada')
        r=await c.post(f'/riwayat-{jenis}/{id_}/koreksi',data=data)
    assert r.status_code==422
    assert 'value="-2.50"' in r.text and 'Alasan lengkap tetap ada</textarea>' in r.text
    if jenis=='sosoh':assert 'value="501"' in r.text


async def test_sesi_kedaluwarsa_dan_kirim_ulang_tidak_menambah_audit(pg,pabrik):
    p = await giling(pg,pabrik)
    c,uid = await klien(pg)
    async with c:
        data={'_csrf':cap(c),'hasil_pk':'6400','dasar_pk':'6500','alasan':'Pengiriman ulang'}
        url=f'/riwayat-giling/{p.id}/koreksi'
        assert (await c.post(url,data=data)).status_code==303
        assert (await c.post(url,data=data)).status_code==422
        from hmu_identitas.token import buat_token
        sesi=security.baca_token(c.cookies.get(security.NAMA_COOKIE))
        c.cookies.set(security.NAMA_COOKIE,buat_token(security._kunci(),akun_id=sesi[0],versi=sesi[1],umur_detik=-1),domain='uji.local')
        assert (await c.post(url,data=data)).status_code==403
    async with pg() as db:
        assert await db.scalar(select(func.count(ActivityLog.id)).where(ActivityLog.aksi=='koreksi_hasil_giling'))==1

async def test_perintah_dibatalkan_tidak_lagi_menghalangi_koreksi(pg,pabrik):
    p=await giling(pg,pabrik)
    c,uid=await klien(pg)
    from app.models import Pelanggan
    from app.services import barang_keluar as bk
    from app.penggilingan.gudang1.services.milling import alasan_koreksi_hasil_giling
    async with pg() as db:
        u=await db.get(User,uid);pel=pelanggan_kledo(nama_pelanggan='Pemilik perintah uji');db.add(pel);await db.flush()
        r=await bk.buat_perintah(db,user=u,baris=[bk.BarisPerintah(tipe='pk_langsung',milling_process_id=p.id,berat_kg=100)],pelanggan_id=pel.id)
        assert await alasan_koreksi_hasil_giling(db,p.id)
        await bk.batalkan(db,user=u,rec_id=r.rec.id,sebab='Barang belum dimuat; perintah salah')
        assert await alasan_koreksi_hasil_giling(db,p.id) is None
    async with c:
        r=await c.post(f'/riwayat-giling/{p.id}/koreksi',data={
            '_csrf':cap(c),'hasil_pk':'6400','dasar_pk':'6500','alasan':'Sesudah perintah dibatalkan'})
    assert r.status_code==303


async def test_tautan_packing_memuat_rincian_dan_tidak_mengubah_stok(pg,pemakai,pemasok):
    from tests.pg.test_stok_produk import sosoh
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.penggilingan.inventory.models import FinishedGoodsStock
    s=await sosoh.__wrapped__(pg,pemakai,pemasok)
    async with pg() as db:
        await catat_packing(db,user=await db.get(User,s['user']),kode_pol=s['kode'],
            kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=25,jumlah_karung=10)
        stok=await db.scalar(select(FinishedGoodsStock))
        jumlah=float(stok.berat_total_kg)
    c,_=await klien(pg)
    async with c:
        halaman=await c.get(f'/riwayat-sosoh/{s["proses_id"]}')
        assert f'/koreksi-catatan/packing/{stok.id}' in halaman.text and '250.0 kg' in halaman.text
        detail=await c.get(f'/koreksi-catatan/packing/{stok.id}')
        assert detail.status_code==200 and '250.0 kg' in detail.text and 'dicatat oleh' in detail.text
    async with pg() as db:
        assert float((await db.get(FinishedGoodsStock,stok.id)).berat_total_kg)==jumlah


async def test_pratinjau_catatan_sudah_dibatalkan_dan_id_wajib(pg,pabrik):
    p=await giling(pg,pabrik)
    async with pg() as db:
        log=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='milling_process').order_by(ActivityLog.id.desc()))
        log.dibatalkan_pada=now_local();await db.commit()
        assert 'sudah dibatalkan' in await undo.sebab_terkunci(db,log)
    c,_=await klien(pg)
    async with c:
        r=await c.post('/audit/batalkan',data={'_csrf':cap(c)})
        assert r.status_code==422
        r=await c.post('/api/actions/undo',json={'lingkup':'saya'},headers={csrf.NAMA_HEADER:cap(c)})
        assert r.status_code==403 and 'pratinjau' in r.text


async def test_pemeriksaan_identitas_tidak_menjaga_sesi_menganggur_tetap_hidup(pg):
    c,_=await klien(pg,mode='bersama')
    async with c:
        r=await c.get('/api/sesi-formulir')
        assert r.status_code==200 and r.json()['aktif']
        assert r.json()['token']==cap(c)
        assert not any(h.startswith(security.NAMA_COOKIE+'=') for h in r.headers.get_list('set-cookie'))
        # Halaman yang sungguh dibuka operator tetap memperpanjang sesi.
        r=await c.get('/pengaturan')
        assert any(h.startswith(security.NAMA_COOKIE+'=') for h in r.headers.get_list('set-cookie'))

async def test_pratinjau_selalu_rollback_meski_penangan_memanggil_commit(pg,pabrik,monkeypatch):
    await giling(pg,pabrik)
    async with pg() as db:
        log=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='milling_process').order_by(ActivityLog.id.desc()))
        u=await db.get(User,pabrik['user']);nama=u.nama
        async def simulasi(sesi, target, **kw):
            orang=await sesi.get(User,u.id)
            orang.nama='Simulasi tidak boleh tersimpan'
            await sesi.commit()
            orang.nama='Perubahan sesudah commit juga tidak boleh tersimpan'
            await sesi.flush()
            return 'bisa'
        monkeypatch.setattr(undo,'_undo_one',simulasi)
        assert await undo.sebab_terkunci(db,log) is None
        await db.refresh(u)
        assert u.nama==nama
