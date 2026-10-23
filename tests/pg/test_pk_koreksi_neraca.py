"""Regresi koreksi bobot dan kepastian neraca, tanpa mengubah hasil ukur."""
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import selectinload
from tests.pg.test_pk_karung import dunia, batch_baru, pindah, habiskan, dunia_g1
from app.models import User, PkGudang2Intake, PolishingSiloUsage, MillingProcess
from app.penggilingan.gudang2 import service as g2, polishing as sosoh
from hmu_core.proses_db import ProsesTerpadu, ArusProsesTerpadu

pytestmark=pytest.mark.asyncio

async def test_review_koreksi_w_harus_sampai_ke_neraca_proses_bersama(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,w=10240,sumber='perkiraan')
        await pindah(db,u,it,128)
        mulai=await sosoh.mulai_penyosohan(db,user=u,nama_silos=['A'])
        b.berat_total_kg=10140;b.sumber_berat='timbangan'
        await db.commit()
        await g2.resinkron_intake_g2(db)
        selesai=await sosoh.selesai_penyosohan(db,user=u,kode=mulai.proc.kode_proses,nama_silo='A',sisa_kg=0)
        assert selesai.pk_terpakai_total == 10140
        bahan_bersama=await db.scalar(select(func.sum(ArusProsesTerpadu.berat_kg)).join(ProsesTerpadu)
            .where(ProsesTerpadu.tabel_sumber=='polishing_process',ProsesTerpadu.id_sumber==str(mulai.proc.id),ArusProsesTerpadu.arah=='bahan'))
        assert bahan_bersama == 10140, f'domain={selesai.pk_terpakai_total}, bersama={bahan_bersama}'

async def test_review_laporan_jangan_menganggap_perkiraan_sudah_final(pg,dunia):
    async with pg() as db:
        u,_,diketahui=await batch_baru(db,dunia,n=None,w=1000,kode='PKB-PASTI-01')
        await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=diketahui.id,nama_silo='A',berat=1000)
        _,b,it=await batch_baru(db,dunia,w=None,sumber='perkiraan')
        await pindah(db,u,it,128)
        selesai=await habiskan(db,u,hasil=990)
        from app.web.laporan_sosoh import ambil_data
        laporan=await ambil_data(selesai.proc.id)
        assert not it.bobot_final and b.berat_total_kg is None
        assert laporan['input_complete'] is False, f"Laporan menyebut bahan={laporan['balance'].bahan_kg}, susut={laporan['balance'].susut.kg}; 128 karung W=NULL dihitung nol"

async def test_review_pk_giling_sendiri_sampai_neraca_tetap_sama(pg,dunia_g1):
    from app.services.transfer import saldo_pk
    async with pg() as db:
        it=await db.get(PkGudang2Intake,dunia_g1['giling_intake_id'])
        u=await db.get(User,dunia_g1['user'].id)
        proc=(await db.scalars(select(MillingProcess))).one()
        assert await saldo_pk(db,proc.id)==2000
        assert it.berat_kg==6000
        await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',berat=6000)
        selesai=await habiskan(db,u,hasil=5940)
        neraca=sosoh.neraca_sosoh(selesai.pk_terpakai_total,selesai.outputs)
        assert neraca.bahan_kg==6000 and neraca.susut.kg==60
        usage=(await db.scalars(select(PolishingSiloUsage))).one()
        assert not usage.bobot_karung_dinamis
        assert await saldo_pk(db,proc.id)==2000
        bersama = (await db.scalars(select(ProsesTerpadu).options(selectinload(ProsesTerpadu.arus)).where(
            ProsesTerpadu.tabel_sumber == 'polishing_process'))).one()
        sebelum = dict(bersama.metadata_domain)
        arus = [(a.id, a.arah, a.berat_kg) for a in bersama.arus]
        await g2.resinkron_intake_g2(db)
        await db.refresh(bersama, ["arus", "metadata_domain"])
        assert bersama.metadata_domain == sebelum
        assert [(a.id, a.arah, a.berat_kg) for a in bersama.arus] == arus


@pytest.mark.parametrize('w', [None, 10240])
async def test_bobot_belum_final_menular_ke_laporan_dan_mengeras_sendiri(pg, dunia, w):
    from app.web.laporan_sosoh import ambil_data, buat_pdf
    from app.penggilingan.gudang1.services.bobot import PERKIRAAN, TAK_DIKETAHUI
    async with pg() as db:
        u, _, pasti = await batch_baru(db, dunia, n=None, w=1000, kode='PKB-PASTI-01')
        await g2.pindah_tumpukan_ke_silo(db, user=u, intake_id=pasti.id, nama_silo='A', berat=1000)
        _, b, it = await batch_baru(db, dunia, w=w, sumber='perkiraan')
        await pindah(db, u, it, 128)
        selesai = await habiskan(db, u, hasil=990)
        laporan = await ambil_data(selesai.proc.id)
        assert not laporan['input_complete']
        assert laporan['bobot_bahan'].keadaan == (TAK_DIKETAHUI if w is None else PERKIRAAN)
        from io import BytesIO
        from pypdf import PdfReader
        pdf = PdfReader(BytesIO(buat_pdf(laporan)))
        teks = '\n'.join(halaman.extract_text() for halaman in pdf.pages)
        assert 'Belum dapat dipastikan' in teks and 'bobot truk belum final' in teks
        assert '• Rendemen:' not in await sosoh.laporan_penyosohan(db, selesai.proc.kode_proses)
        kartu, _ = await sosoh.riwayat_sosoh(db, process_id=selesai.proc.id)
        assert not kartu[0].bahan_pasti and kartu[0].rendemen is None
        assert await sosoh.rendemen_proses(db, selesai.proc.id) is None
        lama = (await db.scalars(select(PolishingSiloUsage))).one().terpakai_lama_kg
        b.berat_total_kg = 10140
        b.sumber_berat = 'timbangan'
        await db.commit()
        await g2.resinkron_intake_g2(db)
        laporan = await ambil_data(selesai.proc.id)
        assert laporan['input_complete']
        assert laporan['balance'].bahan_kg == 11140
        assert laporan['neraca_tercatat'].bahan_kg == float(lama)
        assert (await db.scalars(select(PolishingSiloUsage))).one().terpakai_lama_kg == lama


async def test_koreksi_w_final_sesudah_tutup_menjaga_snapshot_dan_hasil(pg, dunia):
    from app.web.laporan_sosoh import ambil_data
    async with pg() as db:
        u, b, it = await batch_baru(db, dunia, w=10240)
        await pindah(db, u, it, 128)
        selesai = await habiskan(db, u, hasil=9900)
        assert it.bobot_final
        usage = (await db.scalars(select(PolishingSiloUsage))).one()
        snapshot = usage.terpakai_lama_kg
        proyeksi = (await db.scalars(select(ProsesTerpadu).options(selectinload(ProsesTerpadu.arus)))).one()
        hasil_lama = [(a.komoditas, a.berat_kg) for a in proyeksi.arus if a.arah == 'hasil']
        b.berat_total_kg = 10140
        await db.commit()
        await g2.resinkron_intake_g2(db)
        await db.refresh(proyeksi, ["arus", "metadata_domain"])
        assert it.berat_kg == 10140
        assert usage.terpakai_lama_kg == snapshot == 10240
        assert sum(a.berat_kg for a in proyeksi.arus if a.arah == 'bahan') == 10140
        assert [(a.komoditas, a.berat_kg) for a in proyeksi.arus if a.arah == 'hasil'] == hasil_lama
        catatan = proyeksi.metadata_domain['catatan_penutupan']
        assert catatan['berat_pk_terpakai_kg'] == 10240
        assert sum(Decimal(a['berat_kg']) for a in catatan['bahan']) == 10240
        laporan = await ambil_data(selesai.proc.id)
        assert laporan['balance'].bahan_kg == 10140
        assert laporan['neraca_tercatat'].bahan_kg == 10240
        # Koreksi kedua dan poller berulang tidak boleh mengganti catatan pertama.
        b.berat_total_kg = 10120
        await db.commit()
        await g2.resinkron_intake_g2(db)
        await g2.resinkron_intake_g2(db)
        await db.refresh(proyeksi, ["arus", "metadata_domain"])
        assert proyeksi.metadata_domain['catatan_penutupan'] == catatan
        assert sum(a.berat_kg for a in proyeksi.arus if a.arah == 'bahan') == 10120
        assert proyeksi.metadata_domain['berat_pk_terpakai_kg'] == 10120
        assert [(a.komoditas, a.berat_kg) for a in proyeksi.arus if a.arah == 'hasil'] == hasil_lama


async def test_koreksi_w_dua_silo_mempertahankan_seluruh_bahan_proses(pg, dunia):
    async with pg() as db:
        u, b, it = await batch_baru(db, dunia, w=10240, sumber='perkiraan')
        await pindah(db, u, it, 126, silo='A')
        await pindah(db, u, it, 2, silo='B')
        mulai = await sosoh.mulai_penyosohan(db, user=u, nama_silos=['A', 'B'])
        b.berat_total_kg = 10140
        b.sumber_berat = 'timbangan'
        await db.commit()
        await g2.resinkron_intake_g2(db)
        proyeksi = (await db.scalars(select(ProsesTerpadu).options(selectinload(ProsesTerpadu.arus)))).one()
        assert sum(a.berat_kg for a in proyeksi.arus if a.arah == 'bahan') == 10140
        assert len([a for a in proyeksi.arus if a.arah == 'bahan']) == 2
