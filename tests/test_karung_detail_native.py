"""Pure current-native DTO/link/structure protocol, not runtime authorization."""
import ast,hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
from types import ModuleType
from bs4 import BeautifulSoup
from starlette.requests import Request
from starlette.responses import HTMLResponse
import pytest
from app.web import karung_detail_native as ui
ROOT=Path(__file__).resolve().parents[1]
BIND=dict(source='/stok?tab=karung',cap='fixture-cap',context='fixture-ctx',session='fixture-token')
URL='/stok/karung/detail?material=biasa&ukuran=50&merk=&pemilik=pabrik'


def compiler():
    spec=importlib.util.spec_from_file_location('karung_detail_build',ROOT/'scripts/buat_kerangka_karung_detail.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def reference_rows():
    # Exact keys/shape of existing stok_kemasan_rinci() read DTO, never ORM.
    return dict(karung=[dict(gudang='Gudang fixture',warehouse_id=53,kode='biasa',nama='Karung fixture',merk=None,ukuran=50,lembar=98765,menipis=False,pemilik_id=None,pemilik_tunggal=True)])


def native_html(url=URL,extra='',cls='btn'):
    return '<html><body><main id="isi-halaman"><table class="karung-tabel"><tbody><tr><td><div class="karung-tabel__status"><a class="'+cls+'" href="'+url+'" '+extra+'>Detail karung</a></div></td></tr></tbody></table></main></body></html>'


def test_public_program_deterministic_native_shape_chrome_and_no_source_editor():
    before=set(sys.modules);builder=compiler();program,manifest=builder.build()
    assert not any(n.startswith('app.') for n in set(sys.modules)-before)
    assert (program,manifest)==builder.build()
    assert program==(ROOT/'app/web/static/kerangka-karung-detail-ui.js').read_bytes()
    assert manifest==(ROOT/'app/web/static/kerangka-karung-detail-ui.meta.json').read_bytes()
    meta=json.loads(manifest)
    for path,digest in meta['inputs'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    data=json.loads(program.decode().split('window.PadiKerangkaKarungDetailData=',1)[1].split(';\n',1)[0]);component=data['component']
    doc=BeautifulSoup(component['html'],'html.parser')
    assert doc.select_one('h1').text=='Detail karung kosong'
    assert doc.select_one('section.riwayat-detail__card[aria-labelledby="judul-sumber-kepemilikan"] .daftar-standar[aria-busy="true"]')
    assert 'belum diketahui kosong atau berisi' in doc.text
    assert not doc.select('form,input,select,textarea,[data-kod-awal],[data-kepemilikan-sumber],[data-kirim],[data-post],a[href],article')
    assert all(n.has_attr('disabled') for n in doc.select('button:not([data-karung-detail-retry])'))
    assert [n.text for n in BeautifulSoup(component['breadcrumb'],'html.parser').select('.nav-rantai>li a,.nav-rantai>li [aria-current=page]')]==['Beranda','Stok','Karung','Detail karung kosong']
    assert BeautifulSoup(component['menu_markup'],'html.parser').select_one('#buka-laci.bar__menu')
    assert BeautifulSoup(component['back_markup'],'html.parser').select_one('a.bar__balik svg')
    assert '[data-kod-awal],[data-kepemilikan-sumber]' in program.decode()  # Decline native editor markers; never create them.
    for forbidden in ['kepemilikan-detail.js','sessionStorage','localStorage','beforeunload',"method:'POST'",'98765','warehouse_id']:
        assert forbidden not in program.decode()


@pytest.mark.parametrize('target',[URL,'/stok/karung/detail?material=laminasi&ukuran=25&merk=Merk%20fixture&pemilik=13&sumber_page=2'])
def test_finite_karung_read_address(target):assert ui.address(target)


@pytest.mark.parametrize('target',[
    '/stok/sumber/karung/13','/stok/karung/detail?material=x&ukuran=0','/stok/karung/detail?material=x&ukuran=50&pemilik=',
    '/stok/karung/detail?material=x&ukuran=50&pemilik=0','/stok/karung/detail?material=x&ukuran=50&sumber_page=0',
    URL+'&buka=pindah_kepemilikan_karung',URL+'&tindakan=pindah',URL+'&curah=curah:1',URL+'&material=lain',
    '//external.invalid'+URL,'https://external.invalid'+URL,URL+'#edit'])
def test_action_source_foreign_or_ambiguous_target_declined(target):assert ui.address(target) is None


def test_reference_uses_only_real_native_dto_identity_not_balances_or_names():
    data=reference_rows();refs=ui.references(data)
    assert refs==[ui.Reference(('biasa','50','','pabrik'),'biasa · 50 kg · Tanpa merek')]
    assert all(value not in str(refs) for value in ['98765','Gudang fixture','53','menipis'])
    data['karung'][0]['pemilik_tunggal']=False;assert ui.references(data)==[]
    data=reference_rows();data['karung'][0]['pemilik_id']=13
    assert ui.references(dict(stok_jasa=dict(daftar=[data])))[0].identity[-1]=='13'


def test_catalog_requires_actual_visible_native_link_plus_matching_read_dto():
    refs=ui.references(reference_rows());catalog=ui.catalog(native_html(),offers=refs,**BIND)
    assert catalog['entries']==[dict(alamat=URL,identity_label='biasa · 50 kg · Tanpa merek')]
    assert catalog['asal_sha256']==hashlib.sha256(BIND['source'].encode()).hexdigest()
    for html,offers in [(native_html(),[]),(native_html(URL.replace('biasa','other')),refs),(native_html(extra='hidden'),refs),(native_html(extra='target="_blank"'),refs),(native_html(cls='invented'),refs),(native_html().replace('karung-tabel','other-table'),refs)]:
        assert ui.catalog(html,offers=offers,**BIND) is None
    assert '98765' not in str(catalog) and 'Gudang fixture' not in str(catalog)


def test_native_guard_and_editor_source_not_changed_by_presentation():
    source=(ROOT/'app/web/kepemilikan_detail.py').read_bytes()
    assert source==subprocess.check_output(['git','show','e7f6370:app/web/kepemilikan_detail.py'],cwd=ROOT)
    editor=(ROOT/'app/web/static/kepemilikan-detail.js').read_bytes()
    assert editor==subprocess.check_output(['git','show','e7f6370:app/web/static/kepemilikan-detail.js'],cwd=ROOT)
    for name in ['halaman_stok_karung','halaman_stok_karung_jasa','halaman_stok_semua']:
        def prefix(text):
            func=next(n for n in ast.parse(text).body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
            for i,node in enumerate(func.body):
                call=node.value if isinstance(node,(ast.Assign,ast.Return)) else None
                if isinstance(call,ast.Await):call=call.value
                if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='render_laci':return [ast.dump(n,include_attributes=False) for n in func.body[:i]],ast.dump(call,include_attributes=False)
            raise AssertionError('Native render boundary missing')
        assert prefix((ROOT/'app/web/layar_produk.py').read_text())==prefix(subprocess.check_output(['git','show','e7f6370:app/web/layar_produk.py'],cwd=ROOT,text=True))


def test_catalog_decoration_preserves_complete_native_and_marker_boundary(monkeypatch):
    portal=ModuleType('app.web.portal.scope');portal.is_customer_read=lambda request:bool(getattr(request.state,'customer',False));monkeypatch.setitem(sys.modules,'app.web.portal.scope',portal)
    html=native_html().replace('<html>','<html data-versi="fixture-cap">').replace('<body>','<body><div class="bingkai" data-pindah-konteks="fixture-ctx"><div id="formulir-sesi" data-token="fixture-token"></div>').replace('</body>','</div></body>').replace('<table','<!-- isi-halaman:mulai --><table',1).replace('</main>','<!-- isi-halaman:akhir --></main>')
    def request(method='GET',state=None):return Request(dict(type='http',method=method,path='/stok',query_string=b'tab=karung',headers=[],scheme='https',server=('uji',443),state=state or {}))
    response=ui.finish(HTMLResponse(html),request(),offers=ui.references(reference_rows()))
    doc=BeautifulSoup(response.body,'html.parser');host=doc.select_one('#padi-karung-detail-catalog');assert host
    c=json.loads(host.string);assert host['data-source-sha']==c['asal_sha256']
    start=response.body.index(b'<script type="application/json" id="padi-karung-detail-catalog"');end=response.body.index(b'</script>',start)+len(b'</script>')
    assert response.body[:start]+response.body[end:]==html.encode()
    assert response.body.index(b'<!-- isi-halaman:mulai -->')<start<response.body.index(b'<!-- isi-halaman:akhir -->')
    assert not doc.select('[data-karung-detail-native],[data-kod-awal],[data-kepemilikan-sumber]')
    for req,status in [(request('POST'),200),(request(state={'customer':True}),200),(request(state={'portal_scope':object()}),200),(request(),403)]:
        r=HTMLResponse(html,status_code=status);before=r.body;assert ui.finish(r,req,offers=ui.references(reference_rows())).body==before
