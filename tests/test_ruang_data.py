"""Cookie, header dan konfigurasi tidak boleh berpindah perusahaan."""
import json,time
import pytest
from hmu_identitas.ruang_data import RuangData,RuangDataTidakCocok,sesi_sah,klaim_sesi,integrasi_sah,header_integrasi
A='d1d1241a-a329-464a-919e-4f2a65601bc8'
B='a1d1241a-a329-464a-919e-4f2a65601bc8'

@pytest.fixture
def ruang(monkeypatch):
    monkeypatch.setenv('HMU_COMPANY_ID','7');monkeypatch.setenv('HMU_RUANG_DATA',A)
    monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI','0')
    return RuangData.lingkungan()

@pytest.mark.parametrize('data',[{}, {'company_id':8,'ruang_id':A},{'company_id':7,'ruang_id':B},
    {'company_id':'7','ruang_id':A},{'company_id':True,'ruang_id':A},{'ruang_id':A},{'company_id':7},None])
def test_sesi_dari_ruang_lain_ditolak(ruang,data):
    assert not sesi_sah(data)

def test_klaim_dan_batas_sesi_lama(ruang,monkeypatch):
    assert sesi_sah(klaim_sesi())
    monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI',str(int(time.time())+60))
    assert sesi_sah({})
    assert not sesi_sah({'company_id':8,'ruang_id':B})
    monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI',str(int(time.time())-1))
    assert not sesi_sah({})

def test_integrasi_harus_ruang_yang_sama(ruang):
    headers={k.lower():v for k,v in header_integrasi().items()}
    assert integrasi_sah(headers)
    assert not integrasi_sah({})
    for key in headers:
        assert not integrasi_sah({**headers,key:'lain'})

def test_binding_tidak_bisa_diganti_atau_dipalsukan(ruang):
    ruang.cocokkan(json.dumps(dict(ruang.klaim(),sesi_lama_sampai=0)))
    for val in [None,'{}','null',json.dumps({'company_id':8,'ruang_id':A}),json.dumps(dict(ruang.klaim(),sesi_lama_sampai=1))]:
        with pytest.raises(RuangDataTidakCocok):ruang.cocokkan(val)
    with pytest.raises(RuangDataTidakCocok):ruang.pastikan_perusahaan(8)

@pytest.mark.parametrize('cid,rid',[('',''),('7',''),('',A),('abc',A),('0',A),('7','rusak')])
def test_konfigurasi_server_gagal_tertutup(monkeypatch,cid,rid):
    monkeypatch.setenv('HMU_COMPANY_ID',cid);monkeypatch.setenv('HMU_RUANG_DATA',rid)
    with pytest.raises(RuntimeError):RuangData.lingkungan(wajib=True)


def test_token_aplikasi_perusahaan_berbeda_dengan_kunci_sama(ruang,monkeypatch):
    from hmu_identitas import token
    from app.web.security import _kunci,baca_token
    asing=token.buat_token(_kunci(),akun_id=1,versi=1,umur_detik=60,ekstra={'company_id':8,'ruang_id':B})
    assert baca_token(asing) is None
    sendiri=token.buat_token(_kunci(),akun_id=1,versi=1,umur_detik=60,ekstra=klaim_sesi())
    assert baca_token(sendiri)==(1,1)
