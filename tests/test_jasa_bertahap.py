"""Kontrak kerangka Jasa tanpa database; runtime ACL/browser dilanjut pemilik."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from starlette.requests import Request

from app.web import jasa_bertahap, halaman_bertahap


def permintaan(path='/jasa', query=b'', headers=()):
    return Request(dict(type='http', method='GET', scheme='https', server=('uji',443),
                        path=path, raw_path=path.encode(), query_string=query,
                        headers=headers, state={}))


@pytest.mark.asyncio
async def test_gerbang_dulu_dan_kerangka_tanpa_pembaca_saldo(monkeypatch):
    from app.web import layar_jasa
    from app import peran
    from fastapi import HTTPException
    account=NS(user=NS())
    calls=[]
    async def shell(request, akun, jenis):
        assert jenis == 'jasa'
        calls.append(akun)
        return 'shell'
    monkeypatch.setattr(halaman_bertahap,'kerangka',shell)
    monkeypatch.setattr(peran,'can_see_financials',lambda user:False)
    with pytest.raises(HTTPException) as denied:
        await layar_jasa.halaman_jasa(permintaan(),account)
    assert denied.value.status_code==403 and not calls
    monkeypatch.setattr(peran,'can_see_financials',lambda user:True)
    assert await layar_jasa.halaman_jasa(permintaan(headers=[(b'x-kerangka-halaman',b'1')]),account)=='shell'
    assert calls==[account]


@pytest.mark.asyncio
async def test_api_mengulang_native_dan_bypass_tidak_dari_query(monkeypatch):
    import json
    from fastapi.responses import HTMLResponse
    from app.web import layar_jasa
    request=permintaan('/api/halaman-bertahap/jasa',b'cari=Fixture&status=berjalan')
    account=NS()
    seen=[]
    async def native(r,a):
        assert a is account
        seen.append(r)
        return HTMLResponse('<html>native fixture</html>')
    monkeypatch.setattr(layar_jasa,'halaman_jasa',native)
    monkeypatch.setattr(halaman_bertahap,'penanda',lambda r,a,j:r.url.path+'?'+r.url.query)
    response=await halaman_bertahap.isi_halaman('jasa',request,account)
    payload=json.loads(response.body)
    assert payload==dict(stamp='/jasa?cari=Fixture&status=berjalan',html='<html>native fixture</html>')
    assert response.headers['cache-control']=='private, no-store'
    assert seen[0].state.isi_halaman_bertahap is True
    assert not getattr(request.state,'isi_halaman_bertahap',False)
    assert request.url.path=='/api/halaman-bertahap/jasa'


def test_kerangka_memakai_kontrol_native_dan_nilai_belum_dibaca():
    root=Path(__file__).parents[1]
    env=Environment(loader=ChoiceLoader([
        DictLoader({'base.html':'{% block isi %}{% endblock %}'}),
        FileSystemLoader([str(root/'app/web/templates'),str(root/'hmu_tampilan/templates')])]))
    env.globals['VERSI']='fixture-release'
    html=env.get_template('jasa_bertahap.html').render(
        JASA_SHELL=dict(stamp='fixture-stamp',url='/api/jasa-daftar',filtered=False),
        tapis='',cari='',STATUS_PILIHAN=[('','Semua pesanan'),('berjalan','Berjalan')])
    assert '<h1>Pesanan Jasa</h1>' in html
    assert '<h3>Bahan titipan</h3>' in html
    assert 'name="cari"' in html and 'name="status"' in html
    assert 'data-jasa-baca-ulang hidden' in html
    for label in ('PK tersedia','Beras tersisa','Hasil samping','Penerimaan','Pesanan','Proses berjalan','Bahan titipan'):
        assert label in html
    assert 'Jumlah pelanggan belum dibaca.' in html
    assert 'disabled aria-describedby="jasa-detail-alasan"' in html
    assert 'href="/jasa/pelanggan/' not in html
    assert ' 0 kg' not in html and ' 0 pelanggan' not in html


def test_penanda_berubah_untuk_aktor_perusahaan_dan_gudang():
    request=permintaan(query=b'status=berjalan')
    request.state.csrf='synthetic-nonce-not-a-credential'
    request.state.view='fixture-view'
    request.state.akses_produk=NS(company_id=101)
    account=NS(id=1,user=NS(id=2,role='fixture-role',default_warehouse_id=3))
    original=halaman_bertahap.penanda(request,account,'jasa')
    assert halaman_bertahap.penanda(request,account,'jasa')==original
    request.state.akses_produk=NS(company_id=102)
    assert halaman_bertahap.penanda(request,account,'jasa')!=original
    request.state.akses_produk=NS(company_id=101)
    account.user.default_warehouse_id=4
    assert halaman_bertahap.penanda(request,account,'jasa')!=original
    account.user.default_warehouse_id=3
    account.id=9
    assert halaman_bertahap.penanda(request,account,'jasa')!=original


@pytest.mark.asyncio
async def test_x_pindah_tetap_menggunakan_pembaca_native(monkeypatch):
    from app.web import layar_jasa
    from app import peran
    class NativeReadReached(Exception):
        pass
    class Session:
        async def __aenter__(self):
            raise NativeReadReached
        async def __aexit__(self,*args):
            pass
    monkeypatch.setattr(peran,'can_see_financials',lambda user:True)
    monkeypatch.setattr(layar_jasa,'SessionLocal',Session)
    request=permintaan(headers=[(b'x-pindah',b'1')])
    with pytest.raises(NativeReadReached):
        await layar_jasa.halaman_jasa(request,NS(user=NS()))
