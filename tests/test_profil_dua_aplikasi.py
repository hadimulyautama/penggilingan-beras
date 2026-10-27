"""Profil integrasi tidak boleh menjatuhkan/migrasi database CI umum."""
import pytest
from tests.pg.test_teraflow_kiriman import _profil_url


def test_tanpa_source_profil_dilaporkan_bukan_dijalankan(monkeypatch):
    monkeypatch.delenv('UJI_TF_ROOT',raising=False)
    monkeypatch.setenv('UJI_PG_URL','postgresql+asyncpg://uji:uji@127.0.0.1:5432/uji_ci')
    with pytest.raises(pytest.skip.Exception,match='UJI_TF_ROOT'):_profil_url()


@pytest.mark.parametrize('url',[
    'postgresql+asyncpg://uji:uji@127.0.0.1:5432/uji_tf_kiriman_ci',
    'postgresql+asyncpg://uji:uji@192.0.2.1:56627/uji_tf_kiriman_ci',
    'postgresql+asyncpg://uji:uji@127.0.0.1:56627/operasional',
    'postgresql+asyncpg://uji:uji@127.0.0.1:56627/uji_ci',
])
def test_profil_eksplisit_tetap_menolak_database_salah(monkeypatch,url):
    monkeypatch.setenv('UJI_TF_ROOT','/source/terpin')
    monkeypatch.setenv('UJI_PG_URL',url)
    with pytest.raises(AssertionError,match='loopback56627'):_profil_url()


def test_profil_khusus_menerima_database_yang_dijaga(monkeypatch):
    url='postgresql+asyncpg://uji:uji@127.0.0.1:56627/uji_tf_kiriman_ci'
    monkeypatch.setenv('UJI_TF_ROOT','/source/terpin')
    monkeypatch.setenv('UJI_PG_URL',url)
    assert _profil_url()==url
