"""Pure source/adapter proposal tests; no runtime account, DB or browser."""
import asyncio
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
import pytest
from starlette.requests import Request
from starlette.responses import HTMLResponse

from app.web import riwayat_daftar_metadata as meta
from app.web import riwayat_daftar_bertahap as builder

ROOT=Path(__file__).parents[1]
PATHS=tuple(meta.PROCESS)+tuple('/riwayat-qc/'+q for q in sorted(meta.QC))
BASE='d147691f1650d623df2a2f5ebda5b0665e43404f'


def env():
    engine=Environment(loader=ChoiceLoader([
        DictLoader({'base.html':'{% block isi %}{% endblock %}'}),
        FileSystemLoader([ROOT/'app/web/templates',ROOT/'hmu_tampilan/templates']),
    ]),autoescape=True,undefined=StrictUndefined)
    def forbidden(*args):raise AssertionError('Empty structure must not format record data')
    engine.filters['jam']=forbidden
    return engine


def request(path='/riwayat-giling',query='',method='GET',state=None):
    return Request(dict(type='http',method=method,path=path,query_string=query.encode(),
        headers=[],scheme='http',server=('fixture.invalid',80),state=state or {}))


def context(path,status='loading'):
    d=meta.metadata(path)
    return dict(VERSI='uji',PORTAL_READ_ONLY=False,RIWAYAT_META=d,
        RIWAYAT_STATE=meta.keadaan(status),RIWAYAT_URL=path,RIWAYAT_STAMP='uji|'+path,
        request=request(path),LAPORAN_NAV=dict(aktif=d['family'],jenis=d['kind'],detail=False,
            boleh_alamat=[path]))


@pytest.mark.parametrize('path',PATHS)
@pytest.mark.parametrize('status',['loading','empty','filtered-empty','error'])
def test_seven_native_headers_retained_in_all_explicit_states(path,status):
    d=meta.metadata(path)
    name='riwayat_proses_daftar_kerangka.html' if path in meta.PROCESS else 'riwayat_qc_daftar_kerangka.html'
    html=env().get_template(name).render(**context(path,status));doc=BeautifulSoup(html,'html.parser')
    root=doc.select_one('[data-riwayat-daftar-native]')
    assert root and root['data-url']==path
    assert not root.select('a[href],form,input,select,textarea,[data-post],[data-kirim]')
    assert root.select_one('[data-riwayat-native-status]').get_text()==meta.MESSAGES[status]
    assert root.select_one('[data-riwayat-native-retry]').has_attr('hidden')==(status!='error')
    assert 'Belum dibaca' in html and '<strong>0' not in html
    for label in d['columns']:
        if label:assert label in html
    # Keep exact header markup from source, not a generic field list.
    assert d['header'] in html
    assert 'Panduan' in html and not root.select('h1')


@pytest.mark.parametrize('path,query',[
    ('/riwayat-giling','sebelum=12'),('/riwayat-sosoh','sebelum=abc'),
    ('/riwayat-pengeringan','sebelum='),('/riwayat-giling','sebelum=%31%32'),
])
def test_cursor_query_is_preserved_without_changing_native_semantics(path,query):
    assert meta.alamat(path,query)==path+'?'+query


@pytest.mark.parametrize('path,query',[
    ('/riwayat',''),('/laporan-riwayat',''),('/riwayat-transfer',''),
    ('/riwayat-giling/1',''),('/riwayat-qc/beras-hasil-sosoh',''),
    ('/riwayat-qc/pk-luar/LOT-1',''),('/riwayat-qc/pk-luar','cari=x'),
    ('/riwayat-giling','buka=koreksi'),('/riwayat-giling','sebelum=1&sebelum=2'),
])
def test_aliases_details_actions_and_unsupported_filters_decline(path,query):
    assert meta.alamat(path,query) is None


@pytest.mark.parametrize('path',PATHS)
def test_native_guard_predicates_are_delegated_without_role_mapping(monkeypatch,path):
    calls=[];mod=ModuleType('app.web.api');user=object()
    async def jenis(u,k):assert u is user;calls.append(('jenis',k));return True
    async def gabah(u):assert u is user;calls.append(('gabah',));return True
    async def g2(u):assert u is user;calls.append(('g2',));return True
    mod._is_jenis_operator=jenis;mod._is_gabah_operator=gabah;mod._is_g2_operator=g2
    monkeypatch.setitem(sys.modules,'app.web.api',mod)
    assert asyncio.run(builder._boleh(user,path))
    expected=('jenis',meta.PROCESS[path][1]) if path in meta.PROCESS else (
        ('gabah',) if path.endswith(('gabah-basah','gabah-kering')) else
        ('jenis','penggilingan') if path.endswith('pk-hasil-giling') else ('g2',))
    assert calls==[expected]


def patch_runtime(monkeypatch):
    calls=[];portal=ModuleType('app.web.portal.scope');portal.is_customer_read=lambda r:False
    page=ModuleType('app.web.halaman_bertahap');page.penanda_konteks=lambda *args:'uji'
    display=ModuleType('app.web.tampilan')
    def render(r,name,**ctx):calls.append('render');return HTMLResponse('<button data-lk-cetak="">Cetak</button>'+env().get_template(name).render(**ctx))
    display.render=render
    for name,mod in [('app.web.portal.scope',portal),('app.web.halaman_bertahap',page),('app.web.tampilan',display)]:
        monkeypatch.setitem(sys.modules,name,mod)
    return calls


def test_builder_guard_precedes_metadata_and_native_nav_required(monkeypatch):
    from fastapi import HTTPException
    calls=patch_runtime(monkeypatch)
    async def deny(*args):calls.append('guard');return False
    monkeypatch.setattr(builder,'_boleh',deny)
    with pytest.raises(HTTPException) as err:
        asyncio.run(builder.kerangka(request(),SimpleNamespace(user=object()),{}))
    assert err.value.status_code==403 and calls==['guard']
    async def allow(*args):calls.append('guard');return True
    monkeypatch.setattr(builder,'_boleh',allow)
    assert asyncio.run(builder.kerangka(request(),SimpleNamespace(user=object()),{})) is None
    assert 'render' not in calls


def test_builder_exact_sameurl_context_and_print_remain_readonly(monkeypatch):
    calls=patch_runtime(monkeypatch)
    async def allow(*args):return True
    monkeypatch.setattr(builder,'_boleh',allow)
    ctx=context('/riwayat-giling');old=dict(ctx)
    result=asyncio.run(builder.kerangka(request(query='sebelum=123'),SimpleNamespace(user=object()),ctx))
    doc=BeautifulSoup(result.body,'html.parser');root=doc.select_one('[data-riwayat-daftar-native]')
    assert root['data-url']=='/riwayat-giling?sebelum=123'
    assert doc.select_one('[data-lk-cetak]').has_attr('disabled')
    assert result.headers['Cache-Control']=='private, no-store'
    assert int(result.headers['content-length'])==len(result.body)
    assert ctx==old


def test_qc_override_preserves_actual_row_branch_and_original_headers():
    # Git blob is a source fixture, no application/database is imported.
    before=subprocess.check_output(['git','show',BASE+':app/web/templates/riwayat_qc.html'],cwd=ROOT,text=True)
    after=(ROOT/'app/web/templates/riwayat_qc.html').read_text()
    # The last delimiter changes position as outer condition moves; compare
    # complete unchanged loop through its explicit final closing marker.
    marker='      {% for row in rows %}'
    end='      {% endfor %}'
    b=before[before.index(marker):before.rindex(end)+len(end)]
    a=after[after.index(marker):after.rindex(end)+len(end)]
    assert a==b
    head=r'<div class="tabel-standar__kepala"[^>]*>.*?</div>'
    assert meta._head(before,head)==meta._head(after,head)
    assert 'app.services' not in after


@pytest.mark.parametrize('note',[None,'Pemeriksaan belum tersedia pada kategori ini.'])
def test_native_qc_true_empty_keeps_six_original_columns_and_single_body_cell(note):
    engine=env();d=meta.metadata('/riwayat-qc/pk-luar')
    html=engine.get_template('riwayat_qc.html').render(judul=d['title'],rows=[],catatan_kosong=note,
        jenis='pk-luar',VERSI='uji',LAPORAN_NAV=True,PORTAL_READ_ONLY=False)
    doc=BeautifulSoup(html,'html.parser')
    assert d['header'] in html
    assert len(doc.select('.tabel-standar__kepala>span'))==6
    assert len(doc.select('[role=cell][aria-colspan="6"]'))==1
    assert len(doc.select('.tabel-standar__item'))==1
    assert not doc.select('.tabel-standar__item a')
    assert (note or 'Catatan QC yang disimpan akan muncul di halaman ini.') in html


def test_padi_adapter_delegates_only_explicit_sameurl_get():
    js=(ROOT/'app/web/static/riwayat-daftar-native.js').read_text()
    assert 'PADI_BACA_NATIVE?.mount' in js and 'fetch(' not in js and 'POST' not in js
    result=subprocess.run(['node','-e',r'''
const assert=require('assert'),a=require('./app/web/static/riwayat-daftar-native.js'),o='http://fixture.invalid';
for(const p of ['/riwayat-giling','/riwayat-sosoh','/riwayat-pengeringan']){assert(a.allowed(p,o));assert(a.allowed(p+'?sebelum=12',o));}
assert(a.allowed('/riwayat-qc/pk-luar',o));
for(const p of ['/riwayat','/riwayat-transfer','/riwayat-giling/1','/riwayat-giling?buka=x','/riwayat-qc/pk-luar?cari=x','//evil.invalid/riwayat-giling'])assert(!a.allowed(p,o),p);
'''],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
