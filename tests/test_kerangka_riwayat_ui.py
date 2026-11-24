"""Public History compiler/schema proof; no native auth, DB or browser."""
from functools import lru_cache
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

from bs4 import BeautifulSoup
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("history_public_compiler", ROOT / "scripts/buat_kerangka_riwayat.py")
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)
PATHS = ("/riwayat-giling", "/riwayat-sosoh", "/riwayat-pengeringan",
         "/riwayat-qc/gabah-basah", "/riwayat-qc/gabah-kering",
         "/riwayat-qc/pk-hasil-giling", "/riwayat-qc/pk-luar")


@lru_cache(maxsize=1)
def built():
    before = set(sys.modules)
    payload, manifest = compiler.build()
    assert not any(name.startswith("app.") for name in set(sys.modules) - before)
    data = json.loads(payload.decode().split("window.PadiKerangkaRiwayatData=", 1)[1].split(";\n", 1)[0])
    return payload, json.loads(manifest), data


def test_exact_generated_asset_is_current_and_deterministic_with_full_input_hashes():
    payload, meta, _ = built()
    again, manifest = compiler.build()
    assert again == payload and json.loads(manifest) == meta
    assert (ROOT / "app/web/static/kerangka-riwayat-ui.js").read_bytes() == payload
    assert json.loads((ROOT / "app/web/static/kerangka-riwayat-ui.meta.json").read_text()) == meta
    assert meta["aset_sha256"] == hashlib.sha256(payload).hexdigest()
    assert meta["sumber"] == hashlib.sha256(json.dumps(meta["inputs"], sort_keys=True).encode()).hexdigest()
    for name, sha in meta["inputs"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha
    assert len(payload) <= 1572864
    # Report this separate package honestly; this is NOT the primary 45K gate.
    assert len(gzip.compress(payload, mtime=0)) < len(payload)


@pytest.mark.parametrize("path", PATHS)
def test_seven_native_blueprints_have_navigation_headers_and_pending_structure(path):
    _, meta, data = built()
    variant = data["variants"][path]
    assert set(variant) == {"title", "html", "breadcrumb"}
    doc = BeautifulSoup(variant["html"], "html.parser")
    assert doc.select_one(".laporan-riwayat > .laporan-nav")
    assert doc.select_one(".laporan-riwayat > .laporan-isi [data-riwayat-daftar-native]")
    assert len(doc.select("[data-riwayat-daftar-native]")) == 1
    assert not doc.select("h1,form,input,[name],#formulir-sesi,[data-post],[data-kirim]")
    assert not doc.select("script[src],link[rel=stylesheet]")
    assert doc.select_one("[data-riwayat-native-status]")
    assert doc.select_one("[data-riwayat-native-retry]")
    assert all(node.has_attr("disabled") for node in doc.select("[data-lk-cetak],[data-rpd-print]"))
    assert doc.select_one('[data-laporan-kontrol] [data-tab-riwayat="proses"]')
    assert doc.select_one('[data-laporan-kontrol] [data-tab-riwayat="qc"]')
    assert doc.select_one('[data-laporan-kontrol] [data-tab-riwayat="audit"]')
    assert "ui.invalid" not in variant["html"]
    kinds = doc.select_one("[data-jenis-riwayat]")
    assert kinds is not None
    assert len(kinds.select("option")) == (3 if path in PATHS[:3] else 5)
    for style in doc.select("[data-history-style-ref]"):
        assert style["data-history-style-ref"] in data["styles"]
        assert style.has_attr("data-history-ui-style") or style.has_attr("data-history-native-style")
        assert not style.get_text()
    for script in doc.select("[data-history-script-ref]"):
        assert script["data-history-script-ref"] in data["scripts"]
        assert not script.get_text()
    assert "app/web/templates/" + ("riwayat_qc.html" if path.startswith("/riwayat-qc/") else {
        "/riwayat-giling": "riwayat_giling.html",
        "/riwayat-sosoh": "riwayat_sosoh.html",
        "/riwayat-pengeringan": "riwayat_pengeringan.html",
    }[path]) in meta["inputs"]


def test_pengeringan_does_not_carry_sosoh_susut_or_other_variant_html():
    _, _, data = built()
    drying = BeautifulSoup(data["variants"]["/riwayat-pengeringan"]["html"], "html.parser")
    sosoh = BeautifulSoup(data["variants"]["/riwayat-sosoh"]["html"], "html.parser")
    assert "Susut" not in drying.get_text()
    assert "Susut" in sosoh.get_text()
    assert "Bobot basah / kering" in drying.get_text()
    assert "Bahan PK" not in drying.get_text()
    assert "riwayat-desktop-grid--sosoh" not in str(drying)
    assert len(drying.select(".riwayat-desktop-head > span")) == 8
    assert len(sosoh.select(".riwayat-desktop-head > span")) == 9


def test_parent_inheritance_and_native_navigation_are_source_derived_without_rows():
    source = (ROOT / "scripts/buat_kerangka_riwayat.py").read_text()
    assert 'parent.blocks["isi"](ctx)' in source
    assert 'ctx.blocks[name] = [child.blocks[name]]' in source
    assert '("daftar_isi", "daftar_skrip")' in source
    assert 'ast.literal_eval(node.value)' in source
    for forbidden in ("from app.", "import app.", "SimpleNamespace", "SessionLocal", "kartu=[]", "rows=[]"):
        assert forbidden not in source
    _, meta, data = built()
    assert "app/web/templates/laporan_katalog_blueprint.html" in meta["inputs"]
    assert "hmu_tampilan/templates/_laporan_navigasi.html" in meta["inputs"]
    assert set(data) == {"versi", "sumber", "variants", "styles", "scripts"}
    assert set(data["variants"]) == set(PATHS)
    assert all("@import" not in text for text in data["styles"].values())


def test_each_public_history_restores_app_navigation_adapter_after_family_scripts():
    _, meta, data = built()
    path = "app/web/static/riwayat-navigasi-native.js"
    source = (ROOT / path).read_text()
    assert "document.currentScript" not in source
    assert meta["inputs"][path] == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    expected = source.replace("</script", "<\\/script")
    for variant in data["variants"].values():
        doc = BeautifulSoup(variant["html"], "html.parser")
        scripts = doc.select("script[data-history-script-ref]")
        adapters = doc.select("script[data-history-navigation-adapter]")
        assert len(adapters) == 1 and adapters[0] is scripts[-1]
        assert data["scripts"][adapters[0]["data-history-script-ref"]] == expected


def test_runtime_schema_uri_and_tenant_session_negative_contracts_are_pure():
    node = shutil.which("node")
    assert node, "Node is required for the pure runtime contract test"
    program = r"""
const assert=require('assert').strict, fs=require('fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const ui=require(input.runtime),data=input.data;
const origin='https://fixture.invalid',ctx='context-fixture',cap='cap-fixture',token='session-fixture';
function valid(){return {versi:1,cap,konteks:ctx,sesi:token,sumber:data.sumber,
 targets:['/riwayat-giling','/riwayat-pengeringan','/riwayat-qc/gabah-basah','/riwayat-qc/gabah-kering','/riwayat-qc/pk-hasil-giling'],
 menu:{default:'/riwayat-giling',tabs:{proses:{first:'/riwayat-giling',allowed:['/riwayat-giling','/riwayat-pengeringan']},
 qc:{first:'/riwayat-qc/gabah-basah',allowed:['/riwayat-qc/gabah-basah','/riwayat-qc/gabah-kering','/riwayat-qc/pk-hasil-giling']},
 laporan:{first:'/laporan',allowed:['/laporan']}}}};}
assert.equal(ui.validData(data),true);assert.equal(ui.validPermission(valid(),data,ctx,cap,token),true);
for(const mutate of [
 p=>p.versi=2,p=>p.cap='other',p=>p.konteks='other-tenant',p=>p.sesi='other-session',p=>p.sumber='other-digest',
 p=>p.frames={},p=>p.targets={'/riwayat-giling':[0]},p=>p.targets.push('/riwayat-giling'),
 p=>p.targets.push('/riwayat-qc/pk-luar'),p=>p.menu.tabs.proses.allowed.push('/audit'),
 p=>p.menu.default='/laporan',p=>p.menu.tabs.proses.first='/riwayat-pengeringan',
 p=>p.menu.tabs.qc.allowed.push('/riwayat-qc/gabah-basah'),p=>p.menu.tabs.unknown={first:'/audit',allowed:['/audit']},
 p=>p.targets=['/riwayat-giling?sebelum=1'],p=>p.menu.tabs.proses.allowed=[]
]){const permission=valid();mutate(permission);assert.equal(ui.validPermission(permission,data,ctx,cap,token),false);}
for(const uri of ['/riwayat-giling','/riwayat-sosoh?sebelum=99','/riwayat-pengeringan?sebelum=legacy%2Fcursor','/riwayat-qc/gabah-basah'])
 assert.notEqual(ui.address(uri,origin),null);
for(const uri of ['/riwayat-giling/1','/riwayat-sosoh?x=1','/riwayat-giling?sebelum=1&sebelum=2','/riwayat-qc/gabah-basah?sebelum=1',
 '/riwayat-qc/beras-hasil-sosoh','/riwayat-transfer','//external.invalid/riwayat-giling','https://external.invalid/riwayat-giling',
 '/riwayat-pengeringan#x','/riwayat-giling?x='+('a'.repeat(2049))])assert.equal(ui.address(uri,origin),null);
for(const mutate of [d=>delete d.variants['/riwayat-giling'],d=>d.extra={},d=>d.variants['/riwayat-giling'].html={},
 d=>d.variants['/riwayat-giling'].record={},d=>d.styles.x={}]){
 const copy=JSON.parse(JSON.stringify(data));mutate(copy);assert.equal(ui.validData(copy),false);
}
console.log('History public schema/URI/permission negatives PASS');
// A pure DOM model exercises actual pruning, including the native disabled
// span/option shape. No renderer, server, account or browser is involved.
function element(text='',attrs={}){return {textContent:text,attrs:{...attrs},dataset:{},
 setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},getAttribute(k){return this.attrs[k]??null;},
 toggleAttribute(k,on){if(on)this.attrs[k]='';else delete this.attrs[k];},replaceWith(next){this.replaced=next;},
 querySelector(){return {textContent:this.textContent};}};}
const top=['proses','qc','audit'].map(key=>{const a=element(key,{href:'/PUBLIC'});a.dataset.tabRiwayat=key;return a;});
const choices=['/riwayat-sosoh','/riwayat-giling','/riwayat-pengeringan'];
const options=choices.map(p=>element(p,{value:p})),links=choices.map(p=>element(p,{href:p}));
const nav={dataset:{tujuanTab:JSON.stringify(top.map(t=>({kunci:t.dataset.tabRiwayat,nama:t.textContent,href:'/PUBLIC',boleh:true,alamat:choices})))},
 querySelectorAll(s){return s==='[data-tab-riwayat]'?top:s==='[data-jenis-riwayat]'?[{options}]:s==='.laporan-nav__jenis a[href]'?links:[];}};
ui.pruneNavigation({createElement:()=>element()},{querySelector:()=>nav},{family:'proses',path:'/riwayat-pengeringan'},valid().menu);
assert.equal(top[0].attrs.href,'/riwayat-giling');assert.equal(top[0].attrs['aria-current'],'page');
assert.equal(top[2].replaced.attrs['aria-disabled'],'true');assert.equal(top[2].replaced.attrs.href,undefined);
assert.equal(options[0].disabled,true);assert.equal(options[0].attrs.value,undefined);assert.ok(options[0].textContent.includes('tidak memiliki akses'));
assert.equal(options[2].selected,true);assert.equal(options[1].selected,false);
assert.equal(links[0].replaced.attrs['aria-disabled'],'true');assert.equal(links[2].attrs['aria-current'],'page');
assert.deepEqual(JSON.parse(nav.dataset.tujuanTab)[0].alamat,['/riwayat-giling','/riwayat-pengeringan']);
"""
    result = subprocess.run([node, "-e", program], input=json.dumps({
        "runtime": str(ROOT / "app/web/static/kerangka-riwayat-ui-runtime.js"),
        "data": built()[2],
    }), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "negatives PASS" in result.stdout


def test_runtime_has_no_business_network_storage_or_writer_and_replaces_old_history_host():
    source = (ROOT / "app/web/static/kerangka-riwayat-ui-runtime.js").read_text()
    for forbidden in ("fetch(", "XMLHttpRequest", "sessionStorage", "localStorage", ".submit(", "method:'POST'", 'method:"POST"'):
        assert forbidden not in source
    assert "permission.targets.includes(state.path)" in source
    assert "permission.menu.tabs[state.family]?.allowed.includes(state.path)" in source
    assert "pruneNavigation(doc,root,state,permission.menu)" in source
    assert "doc.importNode(host,true)" in source
    assert "main.querySelectorAll('.desktop-back')" in source
    assert "Node.DOCUMENT_POSITION_FOLLOWING" in source


def test_buat_rejects_private_scope_and_base_identity_before_restoring_dom():
    node = shutil.which("node"); assert node
    program = r"""
const assert=require('assert').strict,fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const source=fs.readFileSync(input.runtime,'utf8'),ctx='ctx-fixture',cap='cap-fixture',token='token-fixture';
function permission(){return {versi:1,cap,konteks:ctx,sesi:token,sumber:input.data.sumber,targets:['/riwayat-giling'],menu:{default:'/riwayat-giling',tabs:{proses:{first:'/riwayat-giling',allowed:['/riwayat-giling']}}}};}
function run(mutate,basePatch={},target='/riwayat-giling'){
 let parsed=0;const p=permission();mutate?.(p);
 const host={isConnected:true,dataset:{cap,konteks:ctx},textContent:JSON.stringify(p)};
 const from={nodeType:8,data:'isi-halaman:mulai',compareDocumentPosition:()=>4},to={nodeType:8,data:'isi-halaman:akhir'};
 const main={childNodes:[from,from,to]},session={dataset:{token}},frame={dataset:{pindahKonteks:ctx},contains:()=>true};
 const doc={documentElement:{dataset:{versi:cap}},querySelectorAll:s=>s==='.bingkai'?[frame]:s==='#isi-halaman'?[main]:s==='#formulir-sesi'?[session]:[],querySelector:()=>frame,getElementById:id=>id==='isi-halaman'?main:session};
 if(basePatch.context)frame.dataset.pindahKonteks=basePatch.context;
 if(basePatch.cap)doc.documentElement.dataset.versi=basePatch.cap;
 if(basePatch.token)session.dataset.token=basePatch.token;
 const window={PadiKerangkaRiwayatData:JSON.parse(JSON.stringify(input.data))};
 vm.runInNewContext(source,{window,URL,location:{origin:'https://fixture.invalid'},document:{querySelectorAll:()=>[host]},DOMParser:class{parseFromString(){parsed++;return doc;}},Node:{DOCUMENT_POSITION_FOLLOWING:4}});
 assert.equal(window.PadiKerangkaRiwayatUI.buat(target,'BASE',ctx,cap,token),null);return parsed;
}
for(const mutate of [p=>p.konteks='other',p=>p.sesi='other',p=>p.sumber='wrong',p=>p.frames={},p=>p.targets=[]])assert.equal(run(mutate),0);
assert.equal(run(()=>{}, {},'/riwayat-sosoh'),0,'not in native targets');
for(const patch of [{context:'other'},{cap:'other'},{token:'other'}])assert.equal(run(()=>{},patch),1);
assert.equal(run(()=>{}),1,'duplicate marker pair rejects base');
console.log('History buat metadata/base identity negatives PASS');
"""
    result = subprocess.run([node, "-e", program], input=json.dumps({
        "runtime": str(ROOT / "app/web/static/kerangka-riwayat-ui-runtime.js"), "data": built()[2],
    }), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "base identity negatives PASS" in result.stdout
