"""Borang nyata PK karung: angka yang terlihat sama dengan yang disimpan."""
import pytest
from tests.pg.test_pk_karung import dunia, batch_baru
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('w,sumber', [(10140, 'timbangan'), (10240, 'perkiraan'), (None, 'menunggu')])
async def test_operator_memindahkan_karung_lewat_http(pg, dunia, w, sumber):
    async with pg() as db:
        u, _, it = await batch_baru(db, dunia, w=w, sumber=sumber)
        uid, intake_id = u.id, it.id
    async with await _klien(pg, uid, 'op-karung', mode='operator') as c:
        pilihan = await c.get('/api/actions/tumpukan-sisa')
        assert pilihan.status_code == 200
        assert pilihan.json()[0]['value'] == str(intake_id)
        r = await c.post('/api/actions/pindah-tumpukan-silo', json={
            'tumpukan': str(intake_id), 'silo': 'A', 'jumlah_karung': 126,
            'hasil_timbang': 'karung', 'berat_kg': None,
        }, headers={'X-CSRF-Token': cap_formulir(c)})
        assert r.status_code == 200, r.text
        assert '126 karung' in r.json()['pesan']


@pytest.mark.parametrize('w,sumber,teks', [
    (10140, 'timbangan', '79,2 kg per karung × 126 karung = 9.981,6 kg'),
    (10240, 'perkiraan', '± 80,0 kg per karung'),
    (None, 'menunggu', 'Bobot per karung dan total kg belum diketahui'),
])
async def test_pratinjau_bobot_final_perkiraan_dan_belum_ada(pg, dunia, w, sumber, teks):
    async with pg() as db:
        u, _, it = await batch_baru(db, dunia, w=w, sumber=sumber)
        uid, iid = u.id, it.id
    async with await _klien(pg, uid, 'pratinjau-karung', mode='operator') as c:
        r = await c.get('/api/actions/pratinjau-pk-karung', params={'tumpukan': iid, 'jumlah_karung': 126})
        assert r.status_code == 200, r.text
        assert teks in r.json()['teks']
        assert 'berat_kg' in r.json()['nonaktif']
        from app.models import PkTumpukanToSilo
        from sqlalchemy import select, func
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo)) == 0


async def test_lengkapi_surat_jalan_dan_pindah_karung_atomik(pg, dunia):
    from app.models import PkPurchaseBatch, PkTumpukanToSilo
    from sqlalchemy import select
    async with pg() as db:
        u, b, it = await batch_baru(db, dunia, n=None)
        uid, bid, iid = u.id, b.id, it.id
    async with await _klien(pg, uid, 'lengkapi-karung', mode='operator') as c:
        url = '/api/actions/pratinjau-pk-karung'
        r = await c.get(url, params={'tumpukan': iid, 'jumlah_karung': 20})
        assert 'Jumlah seluruh karung separtai belum tercatat' in r.json()['teks']
        r = await c.get(url, params={'tumpukan': iid, 'jumlah_karung_partai': 128, 'jumlah_karung': 20})
        assert '79,2 kg per karung × 20 karung = 1.584,4 kg' in r.json()['teks']
        isi = dict(tumpukan=str(iid), silo='A', jumlah_karung=129,
                   jumlah_karung_partai=128, ukuran_karung_kg=80, hasil_timbang='karung')
        r = await c.post('/api/actions/pindah-tumpukan-silo', json=isi, headers={'X-CSRF-Token': cap_formulir(c)})
        assert r.status_code == 400, r.text
        async with pg() as db:
            assert (await db.get(PkPurchaseBatch, bid)).jumlah_karung is None
        isi['jumlah_karung'] = 20
        r = await c.post('/api/actions/pindah-tumpukan-silo', json=isi, headers={'X-CSRF-Token': cap_formulir(c)})
        assert r.status_code == 200, r.text
        async with pg() as db:
            b = await db.get(PkPurchaseBatch, bid)
            assert b.jumlah_karung == 128 and b.ukuran_karung_kg == 80
            m = (await db.scalars(select(PkTumpukanToSilo))).one()
            assert m.jumlah_karung == 20 and m.berat_timbang_kg is None
        r = await c.get(url, params={'tumpukan': iid, 'jumlah_karung': 5})
        assert 'Jumlah karung surat jalan akan disimpan' not in r.json()['teks']
        assert 'jumlah_karung_partai' in r.json()['nonaktif']


async def test_riwayat_kg_lama_tidak_diubah_ke_karung(pg, dunia):
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
    from app.models import PkPurchaseBatch
    async with pg() as db:
        u, b, it = await batch_baru(db, dunia, n=None)
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=it.id, nama_silo='A', berat=1000)
        uid, bid, iid = u.id, b.id, it.id
    async with await _klien(pg, uid, 'lama-karung', mode='operator') as c:
        r = await c.get('/api/actions/pratinjau-pk-karung', params={'tumpukan': iid})
        assert 'jumlah_karung' in r.json()['nonaktif']
        r = await c.post('/api/actions/pindah-tumpukan-silo', json={
            'tumpukan': str(iid), 'silo': 'A', 'jumlah_karung': 2, 'jumlah_karung_partai': 128,
        }, headers={'X-CSRF-Token': cap_formulir(c)})
        assert r.status_code == 400 and 'riwayat lama tetap utuh' in r.text
        async with pg() as db:
            assert (await db.get(PkPurchaseBatch, bid)).jumlah_karung is None


@pytest.mark.parametrize('w,sumber', [(10240, 'perkiraan'), (None, 'menunggu')])
async def test_lengkapi_surat_jalan_sebelum_bobot_final(pg, dunia, w, sumber):
    from app.models import PkPurchaseBatch, PkTumpukanToSilo
    from sqlalchemy import select
    async with pg() as db:
        u, b, it = await batch_baru(db, dunia, n=None, w=w, sumber=sumber)
        uid, bid, iid = u.id, b.id, it.id
    async with await _klien(pg, uid, 'surat-belum-final', mode='operator') as c:
        r = await c.post('/api/actions/pindah-tumpukan-silo', json={
            'tumpukan': str(iid), 'silo': 'A', 'jumlah_karung': 20,
            'jumlah_karung_partai': 128, 'ukuran_karung_kg': 80,
        }, headers={'X-CSRF-Token': cap_formulir(c)})
        assert r.status_code == 200, r.text
        async with pg() as db:
            assert (await db.get(PkPurchaseBatch, bid)).jumlah_karung == 128
            m = (await db.scalars(select(PkTumpukanToSilo))).one()
            assert m.jumlah_karung == 20 and m.berat_timbang_kg is None
        assert ('belum diketahui' if w is None else 'bobot truk belum final') in r.json()['pesan']
