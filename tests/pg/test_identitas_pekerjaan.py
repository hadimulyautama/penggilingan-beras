"""Label kepemilikan berasal dari sumber, termasuk proses berjalan dan packing."""
import pytest
from sqlalchemy import select
from tests.pg.test_qc_berjalan import giling

pytestmark = pytest.mark.asyncio

async def test_proses_pabrik_jasa_dan_tidak_diketahui(pg, giling):
    from app.models import MillingProcess, Pelanggan, Jasa
    from app.services.berjalan import Baris
    from app.services.identitas_pekerjaan import lengkapi
    async with pg() as db:
        nyata = Baris(kode=giling['kode'], isi='', keadaan='')
        tak_dikenal = Baris(kode='BUKAN-SUMBER', judul='JASA Pak Budi', isi='', keadaan='')
        await lengkapi(db, [nyata, tak_dikenal])
        assert nyata.kepemilikan == 'pabrik'
        assert tak_dikenal.kepemilikan == 'periksa'  # nama bukan bukti kepemilikan
        pemilik = Pelanggan(nama_pelanggan='Pak Budi Uji')
        db.add(pemilik)
        await db.flush()
        jasa = Jasa(kode='JAS-UJI-001', pelanggan_id=pemilik.id)
        db.add(jasa)
        await db.flush()
        proses = await db.get(MillingProcess, giling['id'])
        proses.jasa_id = jasa.id
        await db.flush()
        packing = Baris(kode=giling['kode'], isi='', keadaan='', jasa_id=jasa.id)
        await lengkapi(db, [nyata, packing])
        for b in [nyata, packing]:
            # Baris baru dibangun tiap request; metadata lama tidak digunakan ulang.
            if b is nyata:
                b.pemilik_ids = None
                await lengkapi(db, [b])
            assert b.kepemilikan == 'jasa'
            assert b.pemilik_tampil == 'JAS-UJI-001 Pak Budi Uji'

async def test_tiket_baru_belum_punya_pesanan_tetap_jasa(pg):
    from app.services.berjalan import Baris
    from app.services.identitas_pekerjaan import lengkapi
    b = Baris(kode='TIKET-BARU', isi='', keadaan='', status_jasa=True,
              pemilik_tampil='Nama bebas dari tiket')
    async with pg() as db:
        await lengkapi(db, [b])
    assert b.kepemilikan == 'jasa' and b.pemilik_tampil == 'Nama bebas dari tiket'

async def test_muatan_campuran_tidak_dilabel_pabrik(pg):
    from app.services.berjalan import Baris
    from app.services.identitas_pekerjaan import lengkapi
    b = Baris(kode='MUAT-UJI', isi='', keadaan='', pemilik_ids=(None, 987654))
    async with pg() as db:
        await lengkapi(db, [b])
    assert b.kepemilikan == 'campuran'
    assert b.pemilik_tampil == 'Pesanan #987654'
