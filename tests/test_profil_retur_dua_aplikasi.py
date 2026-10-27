"""Profil retur tidak boleh mengubah database umum, nonlokal, atau lewat query."""
import pytest
from tests.pg.test_retur_dua_app import _profil_url

def test_profil_retur_tanpa_db_dilaporkan(monkeypatch):
    monkeypatch.delenv('UJI_PG_URL',raising=False)
    with pytest.raises(pytest.skip.Exception,match='UJI_PG_URL'):_profil_url()

@pytest.mark.parametrize('url',[
    'postgresql+asyncpg://uji:uji@127.0.0.1:5432/uji_tf_retur_ci',
    'postgresql+asyncpg://uji:uji@192.0.2.1:56639/uji_tf_retur_ci',
    'postgresql+asyncpg://uji:uji@127.0.0.1:56639/operasional',
    'postgresql+asyncpg://uji:uji@127.0.0.1:56639/uji_ci',
    'postgresql+asyncpg://uji:uji@127.0.0.1:56639/uji_tf_retur_ci?host=192.0.2.1',
    'postgresql+asyncpg://uji:uji@127.0.0.1:56639/uji_tf_retur_ci#abaikan',
])
def test_profil_retur_menolak_db_salah(monkeypatch,url):
    monkeypatch.setenv('UJI_PG_URL',url)
    with pytest.raises(AssertionError,match='loopback56639'):_profil_url()

@pytest.mark.parametrize('nama',['uji_tf_retur_ci','uji_detail_retur_duaapp'])
def test_profil_retur_ci_dan_lokal_lama_diterima(monkeypatch,nama):
    url=f'postgresql+asyncpg://uji:uji@127.0.0.1:56639/{nama}'
    monkeypatch.setenv('UJI_PG_URL',url)
    assert _profil_url()==url
