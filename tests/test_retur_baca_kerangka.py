"""Staff read presentation/source protocol only; no PG/account/browser claim."""
import ast
import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType,ModuleType,SimpleNamespace
from bs4 import BeautifulSoup
from jinja2 import Environment,FileSystemLoader,StrictUndefined
from starlette.requests import Request
from starlette.responses import HTMLResponse
import pytest
from app.web import retur_baca_kerangka as ui,retur_baca_catalog as catalog
from tests.native_source_oracle import digest,fingerprint,functions

ROOT=Path(__file__).parents[1]
CAP='fixture-cap';CTX='fixture-context';TOKEN='fixture-token';PROGRAM='a'*64


def builder():
    spec=importlib.util.spec_from_file_location('retur_read_test_compiler',ROOT/'scripts/buat_kerangka_retur_baca.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def request(path='/retur',query=b'',state=None,endpoint=None,method='GET'):
    return Request(dict(type='http',method=method,scheme='https',server=('fixture.invalid',443),path=path,query_string=query,headers=[],state=state or {},endpoint=endpoint))


def fake_native(monkeypatch,allowed=True):
    native=ModuleType('app.web.layar_retur');native.calls=[]
    def financial(account):native.calls.append(account);return allowed
    native._boleh=financial;native.halaman_retur=lambda:None;native.detail_retur=lambda:None
    origin=ModuleType('app.web.layar_retur_asal');origin.tiket_retur=lambda:None
    portal=ModuleType('app.web.portal.scope');portal.is_customer_read=lambda r:bool(getattr(r.state,'customer',False))
    monkeypatch.setitem(sys.modules,'app.web.layar_retur',native);monkeypatch.setitem(sys.modules,'app.web.layar_retur_asal',origin);monkeypatch.setitem(sys.modules,'app.web.portal.scope',portal)
    return native,origin


@pytest.mark.parametrize('value,kind,id_',[
    ('/retur','list',None),('/retur?sebelum=50&sebelum_pengajuan=41','list',None),
    ('/retur/1','receipt',1),('/retur/9?tab_detail=barang','receipt',9),('/retur/tiket/7','ticket',7)])
def test_declared_native_read_addresses(value,kind,id_):
    assert ui.deskripsi(value)['kind']==kind and ui.deskripsi(value)['id']==id_


@pytest.mark.parametrize('value',['/retur?','/retur/0','/retur/01','/retur/2147483648','/retur?sebelum=0','/retur?sebelum=01','/retur?sebelum=1&sebelum=2','/retur?company_id=1','/retur?pesan=ok','/retur?tiket=3','/retur/1?tab_detail=bad','/retur/1?kembali_kerja=%2Fpekerjaan','/retur/1?tab_detail=barang&tab_detail=tiket','/retur/1#panel-tiket','/retur/tiket/1?tab_detail=tiket','/retur/pengajuan/1','/barang-keluar/1/retur','/retur-supplier/1','/pelanggan/retur','//other/retur','https://other/retur','/retur\\x','/retur\n'])
def test_no_guessing_other_forms_feedback_back_queries_portal_or_supplier(value):assert ui.deskripsi(value) is None


def test_program_current_source_only_shapes_native_columns_and_no_transaction_state():
    before=set(sys.modules);b=builder();program,manifest=b.build();assert b.build()==(program,manifest)
    assert not any(n.startswith('app.') for n in set(sys.modules)-before)
    assert program==(ROOT/'app/web/static/kerangka-retur-baca-ui.js').read_bytes()
    assert manifest==(ROOT/'app/web/static/kerangka-retur-baca-ui.meta.json').read_bytes()
    meta=json.loads(manifest);assert meta['aset_sha256']==digest(program)
    for path,sha in meta['inputs'].items():assert digest((ROOT/path).read_bytes())==sha,path
    data=json.loads(program.decode().split('window.PadiKerangkaReturBacaData=',1)[1].split(';\n',1)[0])
    assert set(data['variants'])==set(ui.VARIANTS)
    for kind,c in data['variants'].items():
        doc=BeautifulSoup(c['html'],'html.parser');root=doc.select_one('[data-retur-baca-native]');assert root['data-kind']==kind
        assert not doc.select('form,input,select,textarea,[name],[data-detail-tab],[data-retur-form],[data-post],[data-kirim],script[src],link[rel=stylesheet]')
        assert all(n.has_attr('disabled') for n in doc.select('button:not([data-retur-baca-retry])'))
        assert doc.select_one('[data-retur-baca-status]')['role']=='status'
        assert doc.select_one('[data-retur-baca-retry]')['type']=='button'
        for text in ['input_by','jumlah_karung','retur_rincian','total_kg','_csrf','data-key','data-actor']:assert text not in c['html']
        if kind=='list':
            assert doc.h1 is None # native list has no transient large heading
            assert [[n.get_text() for n in t.select('th')] for t in doc.select('table')]==[list(ui.COLUMNS[k]) for k in ['applications','receipts']]
        if kind=='receipt':
            assert [n.get_text() for n in doc.select('[data-retur-tab]')]==[v for k,v in ui.TABS]
            assert [n.get_text() for n in doc.select('table th')]==list(ui.COLUMNS['items'])
            assert [n.get_text() for n in doc.select('.detail-kirim-identitas dt')]==['Pelanggan','Nomor polisi','Diterima pada','Diterima oleh','Gudang tujuan']
        if kind=='ticket':assert [n.get_text() for n in doc.select('dt')]==['Timbang pertama','Timbang kedua','Berat barang']
    assert 'document.currentScript' not in program.decode()


def test_native_empty_list_keeps_both_tables_and_existing_single_messages():
    # Template alone with no role/session/account/database or writer controller.
    env=Environment(loader=FileSystemLoader(ROOT/'app/web/templates'),undefined=StrictUndefined,autoescape=True)
    env.filters['jam']=lambda *args:(_ for _ in ()).throw(AssertionError('Empty row must not format record data'))
    source=(ROOT/'app/web/templates/retur_daftar.html').read_text()
    start=source.index('<section class="keluar-ringkas__bagian"');source=source[start:source.rindex('</section></div>')+len('</section>')]
    doc=BeautifulSoup(env.from_string(source).render(pengajuan=[],pengajuan_berikut=None,lama=[],recent=[],sebelum_berikut=None),'html.parser')
    tables=doc.select('table');assert len(tables)==2
    for table,n,note in zip(tables,[4,6],['Tidak ada pengajuan retur menunggu pemeriksaan.','Belum ada penerimaan retur.']):
        assert len(table.select('th'))==n and len(table.select('tbody tr'))==1
        cell=table.select_one('tbody td');assert cell['colspan']==str(n) and cell.get_text()==note
        assert not table.select('a,button,input,form')


def test_receipt_native_assets_use_release_cap_and_prepare_styles_before_install():
    source=(ROOT/'app/web/templates/retur_detail.html').read_text()
    opening=source.split('{% block isi %}',1)[1].split('<div class="riwayat-detail"',1)[0]
    env=Environment(undefined=StrictUndefined,autoescape=True)
    styles=BeautifulSoup(env.from_string(opening).render(VERSI='fixture-release-cap'),'html.parser')
    assert [n['href'] for n in styles.select('link[rel=stylesheet]')]==[
        '/static/pengiriman-retur.css?v=fixture-release-cap',
        '/static/riwayat.css?v=fixture-release-cap',
        '/static/detail_kirim_retur.css?v=fixture-release-cap']
    assert not styles.select('style') # No hidden @import can outlive the prepared read.
    script=source[source.index('<script src="/static/detail_kirim_retur.js'):].split('</script>',1)[0]+'</script>'
    native=BeautifulSoup(env.from_string(script).render(VERSI='fixture-release-cap'),'html.parser')
    assert native.script['src']=='/static/detail_kirim_retur.js?v=fixture-release-cap'


def test_optional_metadata_uses_actual_predicate_same_actor_and_default_deny(monkeypatch):
    native,_=fake_native(monkeypatch);monkeypatch.setattr(ui,'aset',lambda:dict(sumber=PROGRAM))
    actor=SimpleNamespace(harus_ganti_sandi=False);req=request(state={'akun':actor})
    registry=dict(cap=CAP,konteks=CTX,sesi=TOKEN)
    p=asyncio.run(ui.susun(req,actor,registry=registry));assert native.calls==[actor] and p['targets']==['/retur']
    assert set(p)=={'versi','sumber','cap','konteks','sesi','targets'}
    native._boleh=lambda account:False;assert asyncio.run(ui.susun(req,actor,registry=registry)) is None
    native._boleh=lambda account:True
    for state in [{'akun':object()},{'akun':actor,'portal_scope':object()},{'akun':actor,'customer':True}]:
        assert asyncio.run(ui.susun(request(state=state),actor,registry=registry)) is None
    actor.harus_ganti_sandi=True;assert asyncio.run(ui.susun(req,actor,registry=registry)) is None
    actor.harus_ganti_sandi=False
    assert asyncio.run(ui.susun(request(method='POST',state={'akun':actor}),actor,registry=registry)) is None
    assert asyncio.run(ui.susun(req,actor,registry={**registry,'sesi':''})) is None


def document(source='/retur',link='/retur/7',label='R-FIXTURE',hidden=''):
    return ('<html data-versi="'+CAP+'"><body><div class="bingkai" data-pindah-alamat="'+source+'" data-pindah-konteks="'+CTX+'"><div id="formulir-sesi" data-token="'+TOKEN+'"></div><main id="isi-halaman"><!-- isi-halaman:mulai --><section data-retur-receipts '+hidden+'><table><tr><td data-sel="utama"><a class="tabel-standar__kode" href="'+link+'">'+label+'</a></td></tr></table></section><!-- isi-halaman:akhir --></main></div></body></html>').encode()


def data(body=None,offers=None,source='/retur'):
    return catalog.susun_data(source,document(source) if body is None else body,[catalog.Reference('receipt',7,'R-FIXTURE')] if offers is None else offers,origin='https://fixture.invalid',cap=CAP,konteks=CTX,sesi=TOKEN,sumber=PROGRAM)


def test_only_native_current_receipt_dto_and_visible_matching_link_publish():
    refs=catalog.references(dict(recent=[MappingProxyType(dict(id=7,kode='R-FIXTURE'))]))
    assert refs==[catalog.Reference('receipt',7,'R-FIXTURE')]
    p=data(offers=refs);assert p['entries']==[dict(kind='receipt',id=7,code='R-FIXTURE',target='/retur/7')]
    assert p['sumber_sha256']==digest('/retur')
    for body in [document(label='foreign'),document(link='/retur/9'),document(hidden='hidden'),document().replace(b'data-pindah-konteks',b'data-other'),document().replace(TOKEN.encode(),b'old-token'),document()+b'<div class="bingkai"></div>']:
        assert data(body) is None
    assert data(offers=refs+refs) is None
    assert data(offers=[catalog.Reference('receipt',9,'R-FIXTURE')]) is None
    assert catalog.references(dict(recent=[dict(id=True,kode='x')]))==[]
    assert catalog.references(dict(recent=[dict(id=7,kode='x')]*51))==[]


def test_ticket_builder_only_actual_existing_application_visible_ticket_link():
    context=dict(rincian=SimpleNamespace(timbangan_transaksi_id=17),tiket_detail=dict(kode='RTP-FIXTURE'))
    refs=catalog.references(context);assert refs==[catalog.Reference('ticket',17,'RTP-FIXTURE')]
    source='/retur/pengajuan/8'
    body=document(source).replace(b'<section data-retur-receipts >',b'<section id="panel-tiket"><h3>RTP-FIXTURE</h3>').replace(b'/retur/7',b'/retur/tiket/17').replace(b'R-FIXTURE',b'Lihat tiket RTP terkait')
    p=data(body,refs,source);assert p['entries']==[dict(kind='ticket',id=17,code='RTP-FIXTURE',target='/retur/tiket/17')]
    assert data(body.replace(b'id="panel-tiket"',b'id="panel-tiket" hidden'),refs,source) is None
    assert data(body,refs,'/retur/8') is None
    assert catalog.references(dict(tiket_detail=dict(kode='RTP-FIXTURE')))==[]
    # No mutable application caller is adopted by pasang() in this batch.
    assert 'formulir' not in ast.unparse(next(n for n in ast.parse((ROOT/'app/web/retur_baca_catalog.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='pasang'))


def test_response_decoration_exact_native_endpoint_no_form_or_second_read(monkeypatch):
    native,_=fake_native(monkeypatch);monkeypatch.setattr(catalog,'aset',lambda:dict(sumber=PROGRAM))
    import hmu_tampilan
    monkeypatch.setattr(hmu_tampilan,'CAP_ASET',CAP)
    actor=SimpleNamespace(harus_ganti_sandi=False);req=request(state={'akun':actor},endpoint=native.halaman_retur)
    def response():
        out=HTMLResponse(document());out.context=dict(akun=actor,recent=[dict(id=7,kode='R-FIXTURE')],PINDAH_KONTEKS=CTX,CSRF=TOKEN);return out
    out=catalog.pasang(req,actor,response());assert HOST_IN(out.body)
    assert out.headers['cache-control']=='private, no-store' and int(out.headers['content-length'])==len(out.body)
    p=json.loads(BeautifulSoup(out.body,'html.parser').select_one('#'+catalog.HOST).string);assert p['entries'][0]['code']=='R-FIXTURE'
    assert catalog.pasang(req,actor,out).body==out.body
    req.scope['endpoint']=lambda:None;out=response();assert catalog.pasang(req,actor,out) is out and not HOST_IN(out.body)
    req.scope['endpoint']=native.halaman_retur;req.state.portal_scope=object();out=response();assert not HOST_IN(catalog.pasang(req,actor,out).body)


def HOST_IN(body):return catalog.HOST.encode() in body


def test_fixed_native_baseline_preserves_all_guards_readers_writers_and_mutable_forms(monkeypatch):
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No Git/command in source baseline test')))
    raw=(ROOT/'tests/fixtures/retur_baca_prechange/baseline.json').read_bytes()
    assert digest(raw)=='6d9646a26737c3f5c425a6a7e31c39c77b636ad001dc7636b1814301bc92481d'
    receipt=json.loads(raw)
    assert receipt['baseline_commit']=='05d3651accc0f012909bc21da6b9e131c62b1ca4'
    changed_functions={'app/web/layar_retur.py':{'halaman_retur','detail_retur'},'app/web/layar_retur_asal.py':{'tiket_retur'}}
    for path,baseline in receipt['modules'].items():
        source=(ROOT/path).read_text();tree=ast.parse(source);current=functions(source)
        assert current.keys()==baseline['functions'].keys()
        envelope=ast.Module(body=[n for n in tree.body if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))],type_ignores=tree.type_ignores)
        assert fingerprint(envelope)==baseline['envelope']
        for name,node in current.items():
            if name in changed_functions[path]:
                assign,import_,return_=node.body[-3:]
                assert isinstance(assign,ast.Assign) and ast.unparse(assign.targets[0])=='response'
                assert isinstance(import_,ast.ImportFrom) and import_.module=='app.web.retur_baca_catalog' and ast.unparse(return_)=='return pasang(request, akun, response)'
                node.body=node.body[:-3]+[ast.Return(value=assign.value)]
            assert fingerprint(node)==baseline['functions'][name],(path,name)
        writer=current['terima_retur'] if path.endswith('layar_retur.py') else current['simpan']
        altered=copy.deepcopy(writer);commit=next(n for n in ast.walk(altered) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='commit');commit.func.attr='rollback'
        assert fingerprint(altered)!=baseline['functions'][writer.name]
    for path,sha in receipt['untouched_sha256'].items():
        text=(ROOT/path).read_text()
        if path.endswith('retur_detail.html'):
            # Only the reviewed asset transport change is exempted from the
            # old whole-template hash. All field/status/tab/data markup remains
            # compared to the original immutable baseline below.
            links='<link rel="stylesheet" href="/static/riwayat.css?v={{ VERSI }}"><link rel="stylesheet" href="/static/detail_kirim_retur.css?v={{ VERSI }}">'
            script='/static/detail_kirim_retur.js?v={{ VERSI }}'
            assert text.count(links)==1 and text.count(script)==1
            text=text.replace(links,"<style>@import url('/static/riwayat.css?v={{ VERSI }}');@import url('/static/detail_kirim_retur.css?v=2');</style>",1)
            text=text.replace(script,'/static/detail_kirim_retur.js?v=1',1)
        if path.endswith('retur_daftar.html'):
            text=text.replace(' data-retur-applications','').replace(' data-retur-receipts','')
            text=text.replace('<div class="tabel-standar__scroll">','{% if pengajuan %}\n<div class="tabel-standar__scroll">',1)
            position=text.index('<h2>Riwayat penerimaan retur</h2>')+len('<h2>Riwayat penerimaan retur</h2>');text=text[:position]+text[position:].replace('\n    <div class="tabel-standar__scroll">','\n{% if recent %}\n    <div class="tabel-standar__scroll">',1)
            text=text.replace('{% else %}<tr><td colspan="4" class="bantu">Tidak ada pengajuan retur menunggu pemeriksaan.</td></tr>{% endfor %}','{% endfor %}',1)
            text=text.replace('{% else %}<tr><td colspan="6" class="bantu">Belum ada penerimaan retur.</td></tr>{% endfor %}','{% endfor %}',1)
            text=text.replace('{% if pengajuan_berikut %}','{% else %}<p class="bantu">Tidak ada pengajuan retur menunggu pemeriksaan.</p>{% endif %}\n{% if pengajuan_berikut %}',1)
            text=text.replace('{% if sebelum_berikut %}','{% else %}<p class="bantu">Belum ada penerimaan retur.</p>{% endif %}\n{% if sebelum_berikut %}',1)
        assert digest(text)==sha,path


def test_adapters_have_no_new_db_stock_writer_or_editor_controller():
    for name in ['app/web/retur_baca_kerangka.py','app/web/retur_baca_catalog.py','app/web/static/retur-baca-native.js','app/web/static/kerangka-retur-baca-ui-runtime.js']:
        source=(ROOT/name).read_text()
        for token in ['SessionLocal','db.execute(','.commit(','.flush(','create_all','sessionStorage','localStorage','beforeunload','fetch(','retur_penerimaan','periksa_dan_terima']:
            assert token not in source,(name,token)
