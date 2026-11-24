"""Read-only report structure contracts; no DB, application factory or browser."""
import ast
import asyncio
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
import pytest
from starlette.requests import Request

from app.web import laporan_detail_kerangka as frame

ROOT = Path(__file__).parents[1]
CODES = tuple(k for k in frame._source()[0] if k != 'transfer_pk')


def request(path='/laporan/penggilingan', query='', headers=(), method='GET'):
    return Request(dict(type='http', method=method, path=path, query_string=query.encode(),
                        headers=[(k.lower().encode(), v.encode()) for k, v in headers],
                        scheme='http', server=('fixture.invalid', 80), state={}))


def engine():
    return Environment(loader=ChoiceLoader([DictLoader({'base.html': '{% block isi %}{% endblock %}'}),
                       FileSystemLoader([ROOT/'app/web/templates', ROOT/'hmu_tampilan/templates'])]),
                       undefined=StrictUndefined, autoescape=True)


def context(code='penggilingan', custom=False):
    meta = frame.metadata(code)
    return dict(laporan=dict(nama=meta['nama']), tahap=code, VERSI='source-pin',
                periode=[('bulan_ini', 'Bulan ini'), ('khusus', 'Rentang tanggal')],
                periode_aktif='khusus' if custom else 'bulan_ini', dari=date(2026, 11, 1), sampai=date(2026, 11, 24),
                pilihan_laporan=[dict(kode=k, nama=frame.metadata(k)['nama'], kelompok='Proses' if k in
                ('penyosohan', 'penggilingan', 'pengeringan') else 'Laporan lainnya') for k in CODES],
                DETAIL_META=meta, DETAIL_URL='/laporan/'+code, DETAIL_STAMP='source|'+code)


@pytest.mark.parametrize('code', CODES)
def test_native_metadata_and_empty_structure_never_manufacture_report_values(code):
    meta = frame.metadata(code)
    html = engine().get_template('laporan_detail_kerangka.html').render(**context(code))
    doc = BeautifulSoup(html, 'html.parser')
    assert doc.select_one('[data-laporan-detail-native]')['data-url'] == '/laporan/'+code
    assert not doc.select('h1,#laporan-data,a[href],[data-post],[data-kirim]')
    assert len(doc.select('table tbody tr')) == 1
    assert len(doc.select('table tbody td')) == 1
    assert int(doc.select_one('table tbody td')['colspan']) == len(meta['kolom'])
    assert sum(int(th['colspan']) for th in doc.select('thead tr:first-child th')) == len(meta['kolom'])
    assert len(doc.select('.lp-detail-native-fields dt')) == len(meta['kolom'])
    assert {dd.text for dd in doc.select('.lp-detail-native-fields dd')} == {'Belum dibaca'}
    assert '0 kg' not in html and '>0<' not in html
    assert 'Ringkasan' in html and 'Keterangan' in html
    assert all(button.has_attr('disabled') for button in doc.select('.lp-panel-aksi button')[:2])
    assert doc.select_one('[data-detail-native-retry]').has_attr('hidden')
    assert len(meta['source_pins']) == 2


def test_sosoh_only_invariant_six_columns_no_master_grade_or_output_guess():
    meta = frame.metadata('penyosohan')
    assert [(c['kunci'], c['nama']) for c in meta['kolom']] == [
        ('kode', 'Kode'), ('pemilik', 'Pemilik'), ('bahan', 'Total bahan'),
        ('hasil', 'Total hasil'), ('susut', 'Susut debu & bobot'), ('rendemen', 'Rendemen beras')]
    html = engine().get_template('laporan_detail_kerangka.html').render(**context('penyosohan'))
    assert 'grade dan hasil samping belum dibaca' in html
    assert not any(c['kunci'].startswith(('bahan_', 'hasil_')) for c in meta['kolom'])
    assert meta['dinamis'] is True


@pytest.mark.parametrize('custom', [False, True])
def test_filter_fields_and_labels_are_exact_native_markup_before_data(custom):
    ctx = context(custom=custom)
    native = (ROOT/'hmu_tampilan/templates/laporan_periode_detail.html').read_text()
    controls = native[native.index('<div class="lp-panel-kontrol">'):native.index('<div class="lap"')]
    old = BeautifulSoup(engine().from_string(controls).render(**ctx,
                        pdf_href='/laporan-periode/penggilingan.pdf?periode=bulan_ini'), 'html.parser')
    new = BeautifulSoup(engine().get_template('laporan_detail_kerangka.html').render(**ctx), 'html.parser')
    assert str(old.select_one('form')) == str(new.select_one('form'))
    assert [x.text for x in old.select('.lp-panel-aksi>*')] == [x.text for x in new.select('.lp-panel-aksi>*')]
    assert all(x.has_attr('disabled') for x in new.select('.lp-panel-aksi>*')[:2])
    assert new.select_one('form')['method'] == 'get'


@pytest.mark.parametrize('code', CODES)
def test_sameurl_queries_preserve_raw_date_and_period_choices(code):
    for query in ('', 'periode=bulan_ini', 'periode=khusus&dari=2026-11-01&sampai=2026-11-24',
                  'periode=inconnu', 'dari=bad-date', 'periode=khusus&dari=2026-11-24&sampai=2026-11-01'):
        assert frame.alamat('/laporan/'+code, query) == '/laporan/'+code+('?' + query if query else '')
    # Invalid date/period belongs to FastAPI/native guards, not a static schema.


@pytest.mark.parametrize('path,query', [('/laporan/transfer_pk',''), ('/laporan',''),
    ('/laporan/inconnu',''), ('/laporan/penggilingan/7',''), ('/api/laporan/tahap_penggilingan',''),
    ('/laporan-periode/penggilingan.pdf',''), ('/laporan/penggilingan','unduh=true'),
    ('/laporan/penggilingan','periode=semua&periode=bulan_ini'), ('/laporan/penggilingan','tab=edit')])
def test_unsupported_address_declines_without_changing_native_error(path, query):
    assert frame.alamat(path, query) is None


def native_contract(monkeypatch, allowed=True):
    calls = []
    native = ModuleType('app.web.laporan')
    native.PERIODE = (('bulan_ini','Bulan ini'), ('khusus','Rentang tanggal'))
    report = SimpleNamespace(kode='tahap_penggilingan', nama='Penggilingan')
    native._daftar = lambda: (report,)
    def guard(user, lap):
        calls.append(('guard', user is actor, lap is report))
        return allowed
    def dates(period, start, end):
        calls.append(('dates', period, start, end))
        if period == 'khusus' and (start is None or end is None or start>end or end==date.max):
            from fastapi import HTTPException
            raise HTTPException(422, 'Isi tanggal awal dan akhir dengan urutan yang benar.')
        return start or date(2026,11,1), end or date(2026,11,24)
    native.boleh_lihat = guard; native._rentang = dates
    actor = object()
    monkeypatch.setitem(sys.modules, 'app.web.laporan', native)
    return SimpleNamespace(user=actor), calls


def test_native_positive_guard_and_date_order_are_not_replaced_by_role_inference(monkeypatch):
    from fastapi import HTTPException
    actor, calls = native_contract(monkeypatch, allowed=False)
    with pytest.raises(HTTPException) as error:
        frame.kontrak(request(), actor, 'penggilingan')
    assert error.value.status_code == 403 and calls == [('guard',True,True)]
    actor, calls = native_contract(monkeypatch)
    with pytest.raises(HTTPException) as error:
        frame.kontrak(request(), actor, 'penggilingan', 'not-a-period')
    assert error.value.status_code == 422 and len(calls) == 1
    result = frame.kontrak(request(), actor, 'penggilingan', 'khusus', date(2026,11,1), date(2026,11,24))
    assert result['dari'] == date(2026,11,1)
    assert ('dates','khusus',date(2026,11,1),date(2026,11,24)) in calls


@pytest.mark.parametrize('start,end', [(None,None), (date(2026,11,24),date(2026,11,1)), (date(2026,11,1),date.max)])
def test_custom_invalid_ranges_use_same_native_helper(monkeypatch,start,end):
    from fastapi import HTTPException
    actor, calls = native_contract(monkeypatch)
    with pytest.raises(HTTPException) as error:
        frame.kontrak(request(), actor, 'penggilingan', 'khusus', start, end)
    assert error.value.status_code == 422 and calls[-1] == ('dates','khusus',start,end)


def test_native_read_cannot_recurse_document_even_with_inherited_header():
    req = request(headers=(('X-Pindah','1'), ('X-Kerangka-Halaman','1'),
                           ('Sec-Fetch-Mode','navigate'), ('Sec-Fetch-Dest','document')))
    assert frame.memakai_dokumen(req) is False
    assert asyncio.run(frame.dokumen(req, None, 'penggilingan')) is None
    assert frame.memakai_dokumen(request(headers=(('Sec-Fetch-Mode','navigate'), ('Sec-Fetch-Dest','document'))))
    assert not frame.memakai_dokumen(request(method='POST', headers=(('X-Kerangka-Halaman','1'),)))


def test_source_metadata_rejects_executable_and_nonliteral_nodes():
    for source in ('factory()', '[x for x in rows]', '__import__("os")', 'getattr(model,"id")'):
        with pytest.raises(ValueError):frame._literal(ast.parse(source,mode='eval').body)


def test_javascript_query_guard_and_actual_empty_schema_are_readonly():
    asset = ROOT/'app/web/static/laporan-detail-native.js'
    program = r'''
const assert=require('assert'),api=require(process.argv[1]);
const origin='https://fixture.invalid';
assert(api.allowed('/laporan/penyosohan?periode=khusus&dari=2026-11-01&sampai=2026-11-24',origin));
for(const url of ['/laporan/transfer_pk','/laporan/penggilingan/1','/laporan/penggilingan?periode=a&periode=b','/laporan/penggilingan?unduh=true','https://other.invalid/laporan/penggilingan'])assert(!api.allowed(url,origin));
const data={kode:'penyosohan',rincian:[],kolom:[{kunci:'kode',nama:'Kode'},{kunci:'hasil_0',nama:'Jenis nyata dari data'}],kepala_tabel:[[{nama:'Kode',kolom:1,baris:2},{nama:'Hasil',kolom:1,baris:1}],[{nama:'Jenis nyata dari data',kolom:1,baris:1}]]};
const before=JSON.stringify(data),spec=api.emptySpec(data,'penyosohan');
assert.strictEqual(spec.columns,data.kolom);assert.strictEqual(spec.headers,data.kepala_tabel);assert.strictEqual(JSON.stringify(data),before);
assert.strictEqual(api.emptySpec({...data,rincian:[{kode:'actual'}]},'penyosohan'),null);
assert.throws(()=>api.emptySpec(data,'transfer_pk'));assert.throws(()=>api.emptySpec(data,'penggilingan'));
assert.throws(()=>api.emptySpec({...data,kepala_tabel:[]},'penyosohan'));
assert.throws(()=>api.emptySpec({...data,kepala_tabel:[[{nama:'wrong',kolom:3,baris:1}]]},'penyosohan'));
console.log('readonly-guard/empty-schema PASS');
'''
    program += r'''
class Element{
 constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.textContent='';}
 append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
 querySelector(tag){for(const child of this.children){if(child.tagName===tag.toUpperCase())return child;const found=child.querySelector(tag);if(found)return found;}return null;}
 replaceWith(other){const index=this.parent.children.indexOf(this);other.parent=this.parent;this.parent.children.splice(index,1,other);}
}
const doc={createElement(tag){return new Element(tag,this);}},target=doc.createElement('div'),source=doc.createElement('script');
const summary=doc.createElement('section');summary.textContent='Existing native summary stays untouched';
const empty=doc.createElement('p');empty.textContent='Tidak ada transaksi pada periode ini.';target.append(summary,empty);
source.textContent=JSON.stringify(data);
const content={ownerDocument:doc,querySelector(selector){return selector==='#laporan-data'?source:selector==='#lap-isi'?target:null;}};
assert.strictEqual(api.preserveEmptyTable(content,'penyosohan'),true);
assert.strictEqual(target.children[0],summary);assert.strictEqual(summary.textContent,'Existing native summary stays untouched');
const table=target.querySelector('table');assert(table);assert.strictEqual(table.querySelector('caption').textContent,'Rincian transaksi');
const head=table.querySelector('thead');assert.deepStrictEqual(head.children.map(row=>row.children.map(th=>[th.textContent,th.colSpan,th.rowSpan])),data.kepala_tabel.map(row=>row.map(c=>[c.nama,c.kolom,c.baris])));
assert.strictEqual(table.querySelector('tbody').children.length,1);assert.strictEqual(table.querySelector('td').colSpan,data.kolom.length);
assert.strictEqual(table.querySelector('td').textContent,'Tidak ada transaksi pada periode ini.');
assert.strictEqual(source.textContent,before);assert.strictEqual(api.preserveEmptyTable(content,'penyosohan'),false);
source.textContent=JSON.stringify({...data,rincian:[{kode:'actual'}]});
assert.strictEqual(api.preserveEmptyTable(content,'penyosohan'),false);assert.strictEqual(target.querySelector('table'),table);
function field(value=''){return {value,handlers:{},addEventListener(name,handler){this.handlers[name]=handler;},setCustomValidity(value){this.validity=value;},reportValidity(){this.reported=true;}};}
const period=field('bulan_ini'),start=field('2026-11-01'),end=field('2026-11-24'),processField=field(),guideButton=field(),closeButton=field();
const range={hidden:true,querySelectorAll(){return [start,end];}},show={hidden:true},guide={showModal(){},close(){}};
let changed=0,submits=0;
const form={elements:{periode:period,dari:start,sampai:end},handlers:{},querySelector(selector){return selector==='.lp-rentang'?range:show;},addEventListener(name,handler){this.handlers[name]=handler;},requestSubmit(){submits++;this.handlers.submit({preventDefault(){throw Error('unexpected invalid form');}});}};
const controlsRoot={querySelector(selector){return {'form':form,'[data-lp-proses]':processField,'#lp-panduan':guide,'[data-lp-panduan]':guideButton,'[data-lp-tutup]':closeButton}[selector];}};
api.controls(controlsRoot,()=>changed++);period.value='khusus';period.handlers.change();
assert.strictEqual(changed,1);assert.strictEqual(submits,0);assert(!range.hidden&&!show.hidden&&!start.disabled&&start.required);
start.value='2026-11-02';start.handlers.input();assert.strictEqual(changed,2);assert.strictEqual(submits,0);assert.strictEqual(start.value,'2026-11-02');
processField.handlers.change({target:{value:'/laporan/pk_masuk'}});assert.strictEqual(submits,1);assert.strictEqual(changed,3);assert.strictEqual(form.action,'/laporan/pk_masuk');
'''
    result = subprocess.run(['node','-e',program,str(asset)],check=True,capture_output=True,text=True)
    assert 'PASS' in result.stdout
    text = asset.read_text()
    assert 'fetch(' not in text and 'POST' not in text and 'localStorage' not in text and 'sessionStorage' not in text
    assert 'afterInstall({content}){preserveEmptyTable(content,code);}' in text


def test_native_files_and_business_readers_are_outside_proposal():
    source = (ROOT/'app/web/laporan_detail_kerangka.py').read_text()
    assert 'SessionLocal' not in source and 'await ambil(' not in source and '.commit(' not in source
    assert 'from app.web.laporan import _daftar, boleh_lihat, PERIODE, _rentang' in source
    assert 'data_laporan(' not in source and 'atur(' not in source
