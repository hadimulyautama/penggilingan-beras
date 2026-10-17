"""Penilaian lengkap sama pada stok, transfer, dan detail QC meski stok habis."""
from pathlib import Path
import re

import pytest
from sqlalchemy import select, delete

from app.models import MillingQcLog, MillingProcess, MillingProgressLog, User
from app.penggilingan.gudang1.services.milling import log_qc_milling
from app.services import stok
from hmu_identitas.peran import SUPERADMIN
from tests.pg.test_stok_pk_qc import dunia, dunia_asal
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio


def penilaian(html):
    return re.search(r'<div class="penilaian-pk" data-penilaian-pk="gabungan">(.*?)</section>',html,re.S)[1].strip()


async def test_enam_komponen_rumus_dan_pedoman_identik_di_kedua_halaman(pg,dunia):
    async with pg() as db:
        await log_qc_milling(db,user=await db.get(User,dunia['user'].id),kode_proses='LOT-KODE-01',
                             kadar_air=13.2,broken=4,susut=1.5,kondisi=None,
                             butir_kuning='parah',gabah='parah',merang='parah')
        g1=await stok.riwayat_qc_pk(db,kode='LOT-KODE-01')
        g2=await stok.riwayat_qc_pk(db,intake_id=dunia['giling_intake_id'])
        assert g1['penilaian']==g2['penilaian']
        assert g1['penilaian']['nilai']==85
        assert g1['penilaian']['nilai']==(await stok.pk_gudang1(db))[0].nilai_kualitas
    async with await _klien(pg,peran=SUPERADMIN) as c:
        pages={}
        for nama,path in [
            ('stok-g1','/stok/pk/detail?gudang=g1&kode=LOT-KODE-01'),
            ('stok-transfer',f'/stok/pk/detail?gudang=g2&id={dunia["giling_intake_id"]}'),
            ('stok-luar',f'/stok/pk/detail?gudang=g2&id={dunia["beli_intake_id"]}'),
            ('qc-giling','/riwayat-qc/pk-hasil-giling/LOT-KODE-01'),
            ('qc-luar','/riwayat-qc/pk-luar/PKB-KODE-01'),
        ]:
            r=await c.get(path)
            assert r.status_code==200
            pages[nama]=penilaian(r.text)
            for label in ['Kadar air','Butir patah','Susut','Butir kuning','Gabah','Merang']:
                assert f'data-komponen="{label}"' in pages[nama]
            assert '6/6 komponen dinilai' in pages[nama]
            assert 'Penilaian lengkap' in pages[nama]
            assert 'Lihat aturan skor dan kelas kualitas' in pages[nama]
            assert 'Parah</td><td>4</td><td><strong>10' in pages[nama]
            Path('/tmp/hmu-penilaian-'+nama+'.html').write_text(r.text)
        assert pages['stok-g1']==pages['stok-transfer']==pages['qc-giling']
        assert pages['stok-luar']==pages['qc-luar']
        assert '(100 + 100 + 100 + 70 + 70 + 70) ÷ 6' in pages['stok-g1']
        detail=await c.get('/riwayat-qc/pk-hasil-giling/LOT-KODE-01')
        assert detail.text.count('data-penilaian-pk="putaran"')==2
        assert 'Nilai kualitas putaran 1 · 100,00 / 100 · A1' in detail.text
        assert 'Nilai kualitas putaran 2 · 55,00 / 100 · D' in detail.text


async def test_penilaian_tidak_mengarang_nilai_kosong_dan_tetap_ada_setelah_stok_habis(pg,dunia):
    async with pg() as db:
        pid=await db.scalar(select(MillingProcess.id))
        await db.execute(delete(MillingQcLog).where(MillingQcLog.milling_process_id==pid))
        await db.commit()
    async with await _klien(pg,peran=SUPERADMIN) as c:
        path='/stok/pk/detail?gudang=g1&kode=LOT-KODE-01'
        r=await c.get(path)
        assert r.status_code==200
        p=penilaian(r.text)
        assert p.count('Belum dinilai')==6 and '0/6 komponen dinilai' in p
        assert 'Belum ada komponen yang dapat dihitung.' in p
        Path('/tmp/hmu-penilaian-kosong.html').write_text(r.text)
        async with pg() as db:
            from app.database import now_local
            db.add(MillingQcLog(milling_process_id=pid,kadar_air=13.2,
                               waktu=now_local(),input_by=dunia['user'].id))
            await db.commit()
        r=await c.get(path)
        riwayat=await c.get('/riwayat-qc/pk-hasil-giling/LOT-KODE-01')
        p=penilaian(r.text)
        assert p==penilaian(riwayat.text)
        assert '1/6 komponen dinilai' in p and 'Penilaian belum lengkap' in p
        assert p.count('Belum dinilai')==5 and '(100) ÷ 1' in p
        Path('/tmp/hmu-penilaian-sebagian.html').write_text(r.text)
        async with pg() as db:
            hasil=await db.scalar(select(MillingProgressLog))
            hasil.berat_kumulatif_kg=6000 # Seluruh hasil sudah ditransfer.
            await db.commit()
        assert (await c.get(path)).status_code==404
        riwayat=await c.get('/riwayat-qc/pk-hasil-giling/LOT-KODE-01')
        assert riwayat.status_code==200 and penilaian(riwayat.text)==p


async def test_pk_luar_memakai_rata_asli_agar_skor_tidak_berbeda_akibat_pembulatan_snapshot(pg,dunia):
    from app.models import PkPurchaseQcLog
    from app.penggilingan.gudang2.service import log_pk_qc
    async with pg() as db:
        await db.execute(delete(PkPurchaseQcLog))
        await db.commit()
        for ka in [14.45,14.45,14.46]:
            await log_pk_qc(db,user=await db.get(User,dunia['user'].id),kode='PKB-KODE-01',
                            kadar_air=ka,broken=3.5,penyusutan_persen=1.9,
                            butir_kuning='bersih',gabah='bersih',merang='bersih')
        p=(await stok.riwayat_qc_pk(db,intake_id=dunia['beli_intake_id']))['penilaian']
        kartu=next(k for k in await stok.pk_gudang2(db) if k.intake_id==dunia['beli_intake_id'])
        assert p['rows'][0]['hasil']=='14,5%' and p['rows'][0]['skor']==80
        assert dict(kartu.mutu)['Kadar air']=='14,5%'
        assert p['nilai']==kartu.nilai_kualitas==pytest.approx(580/6)
