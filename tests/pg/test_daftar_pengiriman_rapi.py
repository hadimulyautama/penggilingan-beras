"""Penataan daftar tidak memberi tindakan baru atau mengubah stok."""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.web.draf_keluar import SimpanDraf, simpan
from tests.pg.test_barang_keluar import gudang, _klien, _perintah, _stok
from tests.pg.test_draf_keluar import _isi, _user

pytestmark = pytest.mark.asyncio


async def test_daftar_kosong_panduan_dan_filter_tetap_berizin(pg, gudang):
    stok = await _stok(pg, gudang)
    for uid, nama, boleh in [(gudang['adm'], 'rapi-admin', True), (gudang['op'], 'rapi-operator', False)]:
        async with await _klien(pg, uid, nama) as c:
            r = await c.get('/barang-keluar')
            assert r.status_code == 200
            assert 'data-daftar-draf' not in r.text
            assert 'data-bantuan-kirim' in r.text
            assert r.text.count('role="tabpanel"') == 3
            assert 'id="panduan-tahap-3"' in r.text
            assert ('href="/barang-keluar/baru"' in r.text) is boleh
            assert 'name="q"' in r.text and 'name="sejak"' in r.text
            assert 'Belum ada pengiriman berjalan' in r.text
            if os.environ.get('BUKTI_DAFTAR_KELUAR'):
                folder = Path(os.environ['BUKTI_DAFTAR_KELUAR']); folder.mkdir(parents=True, exist_ok=True)
                (folder / f'{nama}-kosong.html').write_text(r.text)
    assert await _stok(pg, gudang) == stok


async def test_draf_terisi_dan_filter_tidak_mengubah_transaksi(pg, gudang):
    stok = await _stok(pg, gudang)
    ident = uuid4()
    await simpan(ident, SimpanDraf(revisi=0, kiriman=uuid4(), isi=await _isi(pg, gudang)), await _user(pg, gudang))
    hasil = await _perintah(pg, gudang, karung=12)
    oid = hasil.rec.id
    async with await _klien(pg, gudang['adm'], 'rapi-daftar') as c:
        r = await c.get('/barang-keluar')
        assert r.status_code == 200
        assert 'data-daftar-draf' in r.text
        assert f'data-hapus-draf="{ident}"' in r.text
        assert f'href="/barang-keluar/draf/{ident}"' in r.text
        assert f'/barang-keluar/{oid}' in r.text
        kosong = await c.get('/barang-keluar?q=tidak-ada&status=perintah&sejak=2020-01-01')
        assert kosong.status_code == 200
        assert 'value="tidak-ada"' in kosong.text
        assert 'value="perintah" selected' in kosong.text
        assert 'value="2020-01-01"' in kosong.text
        assert 'Belum ada pengiriman berjalan' in kosong.text
        assert f'/barang-keluar/{oid}"' not in kosong.text
        if os.environ.get('BUKTI_DAFTAR_KELUAR'):
            folder = Path(os.environ['BUKTI_DAFTAR_KELUAR']); folder.mkdir(parents=True, exist_ok=True)
            (folder / 'admin-terisi.html').write_text(r.text)
            (folder / 'admin-filter.html').write_text(kosong.text)
            (Path('/tmp/daftar-keluar-session.json')).write_text(json.dumps({'cookies': {x.name: x.value for x in c.cookies.jar}, 'draf': str(ident), 'perintah': oid}))
    assert await _stok(pg, gudang) == stok


async def test_batal_tidak_memenuhi_paginasi_riwayat_normal(pg, gudang):
    from sqlalchemy import select
    from app.database import now_local
    from app.models import OutgoingItem, OutgoingRecord

    # Lebih banyak catatan batal daripada kapasitas halaman. Menyaring di
    # templat setelah LIMIT akan menghilangkan pengiriman selesai yang lama.
    async with pg() as db:
        ids = []
        for n in range(53):
            rec = OutgoingRecord(kode=f'OUT-RAPI-{n:03}', status='selesai' if n == 0 else 'batal',
                nama_pembeli='Pelanggan uji riwayat', tanggal=now_local().date(),
                waktu=now_local(), input_by=gudang['adm'])
            db.add(rec)
            await db.flush()
            ids.append(rec.id)
            db.add(OutgoingItem(outgoing_record_id=rec.id, item_type='finished_goods',
                product_sku_id=gudang['sku'], rice_quality_standard_id=gudang['std'],
                berat_kg=25 if n == 0 else 0, berat_perintah_kg=25,
                jumlah_karung=1 if n == 0 else 0, jumlah_karung_perintah=1))
        await db.commit()
        before = (await db.execute(select(OutgoingRecord.id, OutgoingRecord.status)
                                  .order_by(OutgoingRecord.id))).all()
    stok = await _stok(pg, gudang)
    for uid, nama in [(gudang['adm'], 'riwayat-admin'), (gudang['op'], 'riwayat-op')]:
        async with await _klien(pg, uid, nama) as c:
            for query in ('', '?q=OUT-RAPI', '?status=selesai'):
                page = await c.get('/barang-keluar' + query)
                assert page.status_code == 200
                assert 'OUT-RAPI-000' in page.text
                assert 'OUT-RAPI-052' not in page.text
                assert 'Riwayat sebelumnya' not in page.text
            cancelled = await c.get('/barang-keluar?status=batal')
            assert cancelled.status_code == 200
            assert 'OUT-RAPI-052' in cancelled.text
            assert 'OUT-RAPI-000' not in cancelled.text
            assert 'Riwayat sebelumnya' in cancelled.text
            assert (await c.get(f'/barang-keluar/{ids[-1]}')).status_code == 200
    async with pg() as db:
        assert (await db.execute(select(OutgoingRecord.id, OutgoingRecord.status)
                                .order_by(OutgoingRecord.id))).all() == before
    assert await _stok(pg, gudang) == stok
