"""Native report program and permission URI guards, no runtime/DB/browser."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import sys
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]

def build():
    spec=importlib.util.spec_from_file_location('report_public_build',ROOT/'scripts/buat_kerangka_dokumen.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    before=set(sys.modules);payload,manifest=m.build()
    assert not any(n.startswith('app.') for n in set(sys.modules)-before)
    return m,payload,json.loads(manifest),json.loads(payload.decode().split('window.PadiKerangkaDokumenData=',1)[1].split(';\n',1)[0])

def test_native_report_program_is_exact_reproducible_and_contains_no_values():
    m,payload,meta,data=build()
    assert payload==(ROOT/'app/web/static/kerangka-dokumen-ui.js').read_bytes()
    assert m.build()[0]==payload and json.loads(m.build()[1])==meta
    assert meta['aset_sha256']==hashlib.sha256(payload).hexdigest()
    for name,sha in meta['inputs'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha
    assert len(data['variants'])==13 and '/laporan/transfer_pk' not in data['variants']
    assert '/kabar' in data['variants']
    for path,v in data['variants'].items():
        if path=='/kabar':continue
        doc=BeautifulSoup(v['html'],'html.parser')
        assert len(doc.select('[data-laporan-detail-native]'))==1
        assert not doc.select('#laporan-data,[data-post],[data-kirim],form[method=post],script[src],link[rel=stylesheet],h1')
        assert len(doc.select('tbody tr'))==1
        assert int(doc.select_one('tbody td')['colspan'])==v['columns']
        assert {n.get_text() for n in doc.select('.lp-detail-native-fields dd')}=={'Belum dibaca'}
        assert all(f.get('method')=='get' and f['action']==path for f in doc.select('form'))
        assert {n['name'] for n in doc.select('input[name],select[name]')}=={'periode','dari','sampai'}
        assert '0 kg' not in v['html']

def test_native_report_identity_date_scope_and_schema_negatives():
    _,_,_,data=build()
    program=r"""
const assert=require('assert').strict,fs=require('fs'),input=JSON.parse(fs.readFileSync(0,'utf8')),ui=require(input.path),d=input.data;
const periods=['hari_ini','kemarin','minggu_ini','bulan_ini','30_hari','3_bulan','tahun_ini','tahun_lalu','semua'];
const ctx='context',cap='cap',token='session';
function p(){return {versi:1,sumber:d.sumber,cap,konteks:ctx,sesi:token,kabar:true,laporan:{targets:['penggilingan'],choices:['penggilingan','transfer_pk'],rentang:Object.fromEntries(periods.map(k=>[k,{dari:'2026-11-01',sampai:'2026-11-24'}]))}};}
assert.equal(ui.valid(d,p(),ctx,cap,token),true);
for(const mutate of [x=>x.sesi='other',x=>x.konteks='other',x=>x.cap='old',x=>x.sumber='x',x=>x.laporan.targets.push('transfer_pk'),x=>x.laporan.targets.push('penggilingan'),x=>x.laporan.choices=[],x=>x.laporan.rentang.bulan_ini.sampai='2026-02-30',x=>x.laporan.rentang.semua.dari='2030-01-01',x=>x.company_id=1,x=>x.kabar='true']){const v=p();mutate(v);assert.equal(ui.valid(d,v,ctx,cap,token),false);}
for(const value of ['/kabar','/kabar?tab=belum&jenis=peristiwa&batas=30&sampai=3','/laporan/penggilingan','/laporan/pk_masuk?periode=khusus&dari=2026-11-01&sampai=2026-11-24'])assert.ok(ui.address(value,'https://fixture.invalid'));
for(const value of ['/kabar?company_id=2','/kabar?batas=0','/kabar?tab=belum&tab=','/laporan/transfer_pk','/laporan/penggilingan?periode=','/laporan/penggilingan?periode=unknown','/laporan/penggilingan?periode=khusus','/laporan/penggilingan?dari=2026-02-30','/laporan/penggilingan?periode=khusus&dari=2026-11-24&sampai=2026-11-01','/laporan/penggilingan?periode=khusus&dari=2026-11-01&sampai=9999-12-31','/laporan/penggilingan?company=1','/laporan/penggilingan?periode=semua&periode=bulan_ini','//outside.invalid/laporan/pk_masuk'])assert.equal(ui.address(value,'https://fixture.invalid'),null,value);
console.log('native report permission/address negatives PASS');
"""
    result=subprocess.run([shutil.which('node'),'--eval',program],input=json.dumps({'path':str(ROOT/'app/web/static/kerangka-dokumen-ui-runtime.js'),'data':data}),text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_kabar_structure_has_no_notification_records_or_write_forms():
    _,_,meta,data=build()
    item=data['variants']['/kabar'];doc=BeautifulSoup(item['html'],'html.parser')
    assert item['columns']==0 and doc.select_one('[data-kabar-native]')
    assert not doc.select('form,input,[name],.kb-item,[data-post],[data-kirim],[data-sampai]')
    assert len(doc.select('[data-kabar-native-tab]'))==2
    assert doc.select_one('[data-kabar-native-status]') and doc.select_one('[data-kabar-native-retry]')
    assert 'hmu_tampilan/templates/kabar.html' in meta['inputs']
    assert 'aria-label="Jejak halaman"' in item['breadcrumb']
