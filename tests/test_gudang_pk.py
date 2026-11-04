from decimal import Decimal as D
import pytest
from app.domain.gudang import Gudang, PersediaanError


@pytest.mark.parametrize('ident,nama', [(1,'Selepan'),(2,'Polesan'),(57,'Gudang cabang baru')])
def test_gudang_mengalihkan_dua_arah_tanpa_mengubah_fisik(ident,nama):
    stok=Gudang(ident,nama).tempatkan_pk('sumber:11',None,1000)
    stok.alihkan(None,91,400,transaksi_id=7)
    assert stok.saldo(None)==600 and stok.saldo(91)==400
    stok.alihkan(91,None,150,transaksi_id=8)
    assert stok.saldo(None)==750 and stok.saldo(91)==250
    assert stok.fisik_kg==1000 and stok.gudang.id==ident


def test_bagian_yang_dipakai_tidak_diganti_dengan_saldo_transaksi_lain():
    stok=Gudang(3,'Baru').tempatkan_pk('intake:8',None,1000)
    stok.alihkan(None,91,400,transaksi_id=7)
    stok.ambil(91,300)
    stok.alihkan(None,91,400,transaksi_id=8)
    with pytest.raises(PersediaanError,match='Bagian bebas'):
        stok.alihkan(91,None,200,transaksi_id=0,sumber_transaksi_id=7)
    assert stok.saldo(91,transaksi_id=7)==100
    assert stok.saldo(91,transaksi_id=8)==400


@pytest.mark.parametrize('amount',['NaN','Infinity',-1,0,'1.001'])
def test_jumlah_tidak_sah_tidak_mengubah_stok(amount):
    stok=Gudang(3,'Baru').tempatkan_pk('intake:8',None,1000)
    with pytest.raises(PersediaanError):stok.alihkan(None,91,amount,transaksi_id=7)
    assert stok.fisik_kg==1000 and stok.saldo(None)==1000


def test_silo_proses_dan_gudang_nonaktif_ditolak():
    stok=Gudang(3,'Baru').tempatkan_pk('intake:8',None,1000,bebas=False)
    with pytest.raises(PersediaanError,match='silo atau proses'):stok.alihkan(None,91,100,transaksi_id=7)
    with pytest.raises(PersediaanError,match='tidak aktif'):Gudang(3,'Tutup',False).tempatkan_pk('intake:8',None,1000)
