"""Rekap layar/PDF bersama, termasuk PK tanpa SKU dan batas pelanggan."""
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader
import pytest
from sqlalchemy import select

from tests.pg.test_gabung_jasa import dunia, test_gabah_kering_dryer_digabung_di_silo_yang_sama_lalu_digiling as _campur
from tests.pg.test_portal_pelanggan import portal, client, qc
from tests.pg.test_riwayat_giling import _klien
from tests.pg.skenario_silo import pastikan_silo_kosong

pytestmark = pytest.mark.asyncio


def teks_pdf(response):
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    reader = PdfReader(BytesIO(response.content))
    assert reader.metadata.title == 'Rekap Barang Jasa'
    return '\n'.join(p.extract_text() for p in reader.pages)


async def test_gabah_basah_kering_digabung_lalu_pk_diambil(pg, dunia):
    from app.models import User, MillingProcess
    from app.services import barang_keluar as bk
    from app.services.jasa import nota_jasa, rekap_barang_jasa, sisa_jasa
    from app.penggilingan.gudang1.services.milling import finish_milling
    from app.web.rekap_jasa import buat_pdf

    # Dua penerimaan, pengeringan, dan penggabungan fisik menggunakan layanan asli.
    await _campur(pg, dunia)
    jid = min(dunia['jasa1'], dunia['jasa2'])
    async with pg() as db:
        proc = await db.scalar(select(MillingProcess).where(MillingProcess.jasa_id == jid))
        uid, mid, kode = dunia['user'], proc.id, proc.kode_proses
        u = await db.get(User, uid)
        await pastikan_silo_kosong(db, user=u, kode_proses=kode)
        await finish_milling(db, user=u, kode_proses=kode, berat_akhir=3000)
    async with pg() as db:
        u = await db.get(User, uid)
        perintah = await bk.buat_perintah(db, user=u, jasa_id=jid,
            baris=[bk.BarisPerintah(tipe='pk_langsung', milling_process_id=mid, berat_kg=2500)],
            no_polisi='AD 1 REKAP')
    async with pg() as db:
        u = await db.get(User, uid)
        await bk.muat_semua(db, user=u, rec_id=perintah.rec.id)
    async with pg() as db:
        data = await rekap_barang_jasa(db, jid)
        teks = data['teks']
        sisa = await sisa_jasa(db, jid)
        lama = await nota_jasa(db, max(dunia['jasa1'], dunia['jasa2']))
    assert 'GB-SATU-SILO-KERING' in teks and 'GB-SATU-SILO-BASAH' in teks
    assert '3.000 kg' in teks and '2.000 kg' in teks
    assert 'beras PK' in teks and '2.500 kg' in teks.split('Total kembali')[1].splitlines()[0]
    assert sisa.pk_g1_kg == 500
    assert '2.000 kg' in teks.split('Selisih')[1]
    assert 'sudah digabung' in lama and 'GB-SATU-SILO' not in lama
    pdf = buat_pdf(data)
    reader = PdfReader(BytesIO(pdf))
    result = '\n'.join(p.extract_text() for p in reader.pages)
    assert data['kode'] == 'JAS-2610-301'
    assert [j['kode'] for j in data['pesanan_asal']] == ['JAS-2610-302']
    for value in ['REKAP BARANG JASA','JAS-2610-301','JAS-2610-302',
                  'Gabah basah','Gabah kering','Beras PK','2.500 kg','500 kg','2.000 kg']:
        assert value in result
    out = Path('output/rekap-barang-jasa');out.mkdir(parents=True, exist_ok=True)
    (out/'campuran-pk.pdf').write_bytes(pdf)
    (out/'campuran-pk.txt').write_text(teks)

    from app.models.portal import PortalAccount
    from app.web.security import hash_sandi
    async with pg() as db:
        account = PortalAccount(username='rekap-uji', pelanggan_id=dunia['catur'],
            password_hash=hash_sandi('rahasia123'), active=True, token_version=1)
        db.add(account);await db.commit()
    async with client(account) as c:
        laporan = await c.get('/pelanggan/laporan')
        soup = BeautifulSoup(laporan.text, 'html.parser')
        links = soup.find('h2', string='Rekap Barang Jasa').parent.find_all('a', string='Baca PDF')
        assert len(links) == 1  # Satu rekap utama, dua penerimaan.
        assert links[0]['href'] == f'/pelanggan/jasa/{jid}/nota.pdf'
        assert soup.find('a', string='Lihat rekap pesanan gabungan')['href'] == f'/pelanggan/jasa/{jid}/nota'
        old = await c.get(f"/pelanggan/jasa/{max(dunia['jasa1'], dunia['jasa2'])}/nota")
        assert 'sudah digabung' in old.text and 'Neraca bobot' not in old.text
        assert 'Baca PDF' not in BeautifulSoup(old.text, 'html.parser').get_text()
        old_pdf = await c.get(f"/pelanggan/jasa/{max(dunia['jasa1'], dunia['jasa2'])}/nota.pdf?unduh=1")
        assert old_pdf.status_code == 303
        assert old_pdf.headers['location'] == f'/pelanggan/jasa/{jid}/nota.pdf?unduh=1'


@pytest.mark.parametrize('tipe,jenis,sebut', [
    ('pk_langsung', None, 'beras PK'), ('pk_g2', None, 'beras PK'),
    ('gabah_langsung', None, 'gabah kering'), ('byproduct_curah', 'bekatul', 'Bekatul')])
async def test_pengambilan_tanpa_sku_tetap_terbaca_dan_batal_tidak_dihitung(pg, dunia, tipe, jenis, sebut):
    from app.database import now_local
    from app.models import OutgoingRecord, OutgoingItem
    from app.services.jasa import nota_jasa
    async with pg() as db:
        for i, status in enumerate(['selesai','batal']):
            rec = OutgoingRecord(kode='OUT-REKAP-'+str(i), tanggal=now_local().date(),
                waktu=now_local(), input_by=dunia['user'], status=status)
            db.add(rec);await db.flush()
            db.add(OutgoingItem(outgoing_record_id=rec.id, jasa_id=dunia['jasa1'],
                item_type=tipe, jenis_byproduct=jenis, berat_kg=1250, product_sku_id=None))
        await db.commit()
        teks = await nota_jasa(db, dunia['jasa1'])
    assert sebut in teks
    assert '1.250 kg' in teks.split('Total kembali')[1].splitlines()[0]
    assert 'OUT-REKAP-1' not in teks


async def test_rekap_staff_portal_pdf_sama_dan_pelanggan_lain_ditolak(pg, portal):
    jid, asing = [j.id for j in portal.orders]
    async with client(portal.accounts[0]) as c:
        halaman = await c.get(f'/pelanggan/jasa/{jid}/nota')
        assert halaman.status_code == 200
        soup = BeautifulSoup(halaman.text, 'html.parser')
        assert soup.title.get_text(strip=True) == 'Rekap Barang Jasa · PadiFlow Pelanggan'
        teks = soup.select_one('.rekap-jasa').get_text(' ',strip=True)
        assert soup.find('a', string='Baca PDF')['href'] == f'/pelanggan/jasa/{jid}/nota.pdf'
        pdf = await c.get(f'/pelanggan/jasa/{jid}/nota.pdf')
        isi = teks_pdf(pdf)
        flattened = ' '.join(isi.split())
        for row in soup.select('.rekap-table tbody tr'):
            for td in row.find_all('td'):
                text = td.get_text(' ',strip=True)
                if text not in ('Belum ada barang masuk.','Belum ada hasil yang diambil.'):
                    assert text in flattened
        assert 'REKAP BARANG JASA' in isi
        assert 'Rahasia Pelanggan B' not in isi
        unduh = await c.get(f'/pelanggan/jasa/{jid}/nota.pdf?unduh=1')
        assert unduh.headers['content-disposition'].startswith('attachment;')
        assert 'rekap-barang-jasa-' in unduh.headers['content-disposition']
        assert (await c.get(f'/pelanggan/jasa/{asing}/nota.pdf')).status_code == 404
        assert (await c.get(f'/pelanggan/jasa/{jid}/nota.pdf?pelanggan_id={portal.owners[1].id}')).status_code == 404
        assert (await c.get(f'/jasa/{jid}/nota.pdf')).status_code == 303
        laporan = await c.get('/pelanggan/laporan')
        assert 'Rekap Barang Jasa' in laporan.text and 'Nota pesanan' not in laporan.text
    async with await _klien(pg, peran='admin') as c:
        native = await c.get(f'/jasa/{jid}/nota')
        assert BeautifulSoup(native.text, 'html.parser').select_one('.rekap-jasa').get_text(' ',strip=True) == teks
        assert teks_pdf(await c.get(f'/jasa/{jid}/nota.pdf')) == isi
    async with await _klien(pg, peran='operator', gudang='g1') as c:
        assert (await c.get(f'/jasa/{jid}/nota.pdf')).status_code == 403
    async with client() as c:
        assert (await c.get(f'/pelanggan/jasa/{jid}/nota.pdf')).status_code == 401
