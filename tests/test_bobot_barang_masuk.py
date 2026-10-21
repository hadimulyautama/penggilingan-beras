"""Bobot daftar mengikuti penerimaan, termasuk pecahan dan catatan ditolak."""
from decimal import Decimal
import pytest
from app.services.barang_masuk import bobot_diterima


@pytest.mark.parametrize('catatan,berat,ket',[
    ([(100.25,'timbangan','baru'),(200.5,'nota','ditumpuk')],Decimal('300.75'),''),
    ([(100,'perkiraan','baru')],Decimal('100'),'Belum final'),
    ([(None,'menunggu','baru')],None,'Belum diukur'),
    ([(100,'timbangan','baru'),(None,'menunggu','baru')],None,'Belum lengkap'),
    ([(500,'timbangan','ditolak')],None,'Tidak diterima'),
    ([(500,'timbangan','ditolak'),(100,'timbangan','baru')],Decimal('100'),''),
    ([(0,'timbangan','baru')],Decimal('0'),''),
])
def test_bobot_penerimaan_tidak_diganti_netto_atau_saldo(catatan,berat,ket):
    assert bobot_diterima([dict(berat=b,sumber_berat=s,status=k) for b,s,k in catatan])==(berat,ket)
