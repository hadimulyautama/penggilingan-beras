/* Pure metadata/protocol tests. Role decisions remain entirely server-native. */
import test from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {readFileSync} from 'node:fs';import vm from 'node:vm';
const require=createRequire(import.meta.url),api=require('../app/web/static/kerangka-pengaturan-detail-ui-runtime.js'),adapter=require('../app/web/static/pengaturan-detail-native.js');
const sandbox={window:{},module:{exports:{}},URL};vm.runInNewContext(readFileSync(new URL('../app/web/static/kerangka-pengaturan-detail-ui.js',import.meta.url),'utf8'),sandbox);
const data=sandbox.window.PadiKerangkaPengaturanDetailData,p={versi:1,cap:'cap',konteks:'ctx',sesi:'fixture-token',sumber:data.sumber,targets:{'/pengaturan/peran':'peran-gudang','/pengaturan/akses':'akses','/pengaturan/sistem':'sistem-umum'},...data.references};
test('all six exact native addresses and no query/other families can mount',()=>{
 for(const path of Object.keys(api.choices))assert.equal(adapter.configuration(path,'https://fixture.invalid').address,path);
 for(const path of ['/pengaturan','/pengaturan/akun','/pengaturan/alat','/pengguna','/pengaturan/mutu?err=x','/pengaturan/kledo?company_id=1','/pengaturan/peran#draft','//other.invalid/pengaturan/mutu'])assert.equal(adapter.configuration(path,'https://fixture.invalid'),null);
});
test('only actual exact target/variant metadata admits a public shape; reference drift is closed',()=>{
 const valid=x=>api.valid(data,x,p.konteks,p.cap,p.sesi);assert.equal(valid(p),true);
 for(const key of ['cap','konteks','sesi','sumber'])assert.equal(valid({...p,[key]:'old'}),false);
 for(const targets of [{},{'/pengaturan/mutu':'sistem-admin'},{'/pengaturan/peran':'akses'},{'/pengguna':'akses'}])assert.equal(valid({...p,targets}),false);
 assert.equal(valid({...p,columns:['guess']}),false);assert.equal(valid({...p,processes:[]}),false);
 assert.equal(valid({...p,allowed:true}),false);assert.equal(valid({...p,user_id:1}),false);assert.equal(valid(null),false);
});
test('native frame must remain current and bind CAP/session/context within same container',()=>{
 const main={},session={dataset:{token:p.sesi}},frame={dataset:{pindahAlamat:'/pengaturan/akses',pindahKonteks:p.konteks},contains:n=>[main,session].includes(n)};
 const doc={documentElement:{dataset:{versi:p.cap}},querySelector:()=>frame,querySelectorAll:()=>[{}],getElementById:id=>id==='isi-halaman'?main:session};
 const valid=()=>api.frameBound(doc,p.konteks,p.cap,p.sesi,'/pengaturan/akses');assert.equal(valid(),true);
 frame.contains=()=>false;assert.equal(valid(),false);frame.contains=n=>[main,session].includes(n);session.dataset.token='old';assert.equal(valid(),false);
});
test('retry targets read content instead of any configuration action',()=>{
 const config=adapter.configuration('/pengaturan/akses','https://fixture.invalid'),retry={},calls=[],content={focus:o=>calls.push(o),querySelectorAll:()=>[]};
 config.restoreFocus({focus:retry,retry,content});assert.equal(content.tabIndex,-1);assert.equal(calls.length,1);
 config.restoreFocus({focus:{closest:()=>null},retry,content});assert.equal(calls.length,1);
});
