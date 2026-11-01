from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace as Obj

import pytest

from app.penggilingan.gudang1.services.bobot import Bobot, PASTI, PERKIRAAN
from app.services.estimasi_pengeringan import hitung, ringkas


@pytest.mark.parametrize('w,a,z,expected', [
    (30251.5,25.4,14.7,Decimal('26456.76')),
    (1000,25,14,Decimal('872.09')),
    (1000,14,14,Decimal('1000.00')),
    (1000,20,0,Decimal('800.00')),
    (1000,None,14,None),(None,25,14,None),(1000,100,14,None),
    (1000,20,21,None),(1000,-1,14,None),(0,25,14,None),
    (1000,float('nan'),14,None),(1000,25,float('inf'),None),
])
def test_rumus_tidak_memakai_selisih_persen_langsung(w,a,z,expected):
    result=hitung(w,a,z)
    assert (result.quantize(Decimal('.01')) if result is not None else None)==expected


def test_indikator_bukan_tes_target_dan_bukan_catatan_sesudah_selesai():
    awal=datetime(2026,1,1,tzinfo=timezone.utc)
    lot=Obj(kode_lot='PGR-UJI',waktu_mulai_pengeringan=awal,
            waktu_selesai_pengeringan=awal+timedelta(hours=13),target_kadar_air=12)
    def log(i,minute,machine,manual):
        return Obj(id=i,waktu_update=awal+timedelta(minutes=minute),
                   kadar_air_indikator=machine,kadar_air_tes_manual=manual)
    logs=[log(1,35,25.4,24.55),log(2,60,None,11),log(3,780,14.7,13.88),log(4,800,9,9)]
    d=ringkas(lot,Bobot(30251.5,PASTI),list(reversed(logs)),snapshot_akhir=14.7)
    assert d['basah']=='30.251,50 kg' and d['kering']=='26.456,76 kg'
    assert d['awal']=='25,40 %' and d['akhir']=='14,70 %'
    assert any('35 menit' in x for x in d['catatan'])
    legacy=ringkas(lot,Bobot(30251.5,PASTI),logs)
    assert legacy['kering']==d['kering']
    assert ringkas(lot,Bobot(30251.5,PASTI),logs[2:3])['kering'] is None
    assert ringkas(lot,Bobot(None,PERKIRAAN),logs)['kering'] is None
    assert ringkas(lot,Bobot(1000,PASTI,tak_diketahui=1),logs)['kering'] is None


def test_sisa_tidak_disebut_estimasi_saldo_dan_snapshot_akhir_nol_tetap_nol():
    awal=datetime(2026,1,1,tzinfo=timezone.utc)
    lot=Obj(kode_lot='PGR-UJI',waktu_mulai_pengeringan=awal,waktu_selesai_pengeringan=awal+timedelta(hours=1))
    logs=[Obj(id=1,waktu_update=awal,kadar_air_indikator=20)]
    d=ringkas(lot,Bobot(1000,PASTI),logs,snapshot_akhir=0,terpakai=True)
    assert d['kering']=='800,00 kg' and d['akhir']=='0,00 %'
    assert d['historis'] and any('bukan saldo sisa' in s for s in d['catatan'])
