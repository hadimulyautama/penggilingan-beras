/* Pure metadata/address/DOM-protocol checks only; no browser or requests. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const require=createRequire(import.meta.url),runtime=require('../app/web/static/kerangka-pengaturan-master-ui-runtime.js'),adapter=require('../app/web/static/pengaturan-master-native.js');
const sandbox={window:{},module:{exports:{}},URL};
vm.runInNewContext(readFileSync(new URL('../app/web/static/kerangka-pengaturan-master-ui.js',import.meta.url),'utf8'),sandbox);
const data=sandbox.window.PadiKerangkaPengaturanMasterData,paths=['/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping'];
const p={versi:1,cap:'fixture-cap',konteks:'fixture-context',sesi:'fixture-session',sumber:data.sumber,allowed:true};
test('only declared same-origin bare read paths can mount, query/feedback/other families decline',()=>{
 for(const path of paths){assert.equal(runtime.nativeAddress(path),path);const c=adapter.configuration(path,'https://fixture.invalid');assert.equal(c.address,path);assert.equal(c.rootSelector,'[data-pengaturan-master-kerangka]');assert.equal(c.shellSelector,c.rootSelector);}
 for(const value of [...paths.map(p=>p+'?berhasil=tambah'),...paths.map(p=>p+'/ubah'),'/pengaturan','/pengguna','/pengaturan/akun','/pelanggan/pengaturan/hasil-samping','https://other.invalid'+paths[0],'//other.invalid'+paths[0],paths[0]+'#editor']){assert.equal(runtime.nativeAddress(value),null);assert.equal(adapter.configuration(value,'https://fixture.invalid'),null);}
});
test('private presentation metadata is exact, allow must be explicit and identity fresh',()=>{
 const valid=x=>runtime.valid(data,x,p.konteks,p.cap,p.sesi);assert.equal(valid(p),true);
 for(const [key,value] of [['allowed',false],['allowed',null],['allowed',1],['cap','old'],['konteks','old'],['sesi','old'],['sumber','b'.repeat(64)]])assert.equal(valid({...p,[key]:value}),false,key);
 for(const key of Object.keys(p)){const copy={...p};delete copy[key];assert.equal(valid(copy),false,key);}
 assert.equal(valid({...p,user_id:1}),false);assert.equal(valid({...p,company_id:1}),false);assert.equal(valid(null),false);
 assert.equal(runtime.valid(data,p,'',p.cap,p.sesi),false);
});
test('frame binding requires exact current address, context/CAP/session and actual containment',()=>{
 const main={},session={dataset:{token:p.sesi}},frame={dataset:{pindahAlamat:paths[0],pindahKonteks:p.konteks},contains:n=>[main,session].includes(n)};
 const doc={documentElement:{dataset:{versi:p.cap}},querySelector:()=>frame,querySelectorAll:()=>[{}],getElementById:id=>id==='isi-halaman'?main:session};
 const valid=()=>runtime.frameBound(doc,p.konteks,p.cap,p.sesi,paths[0]);assert.equal(valid(),true);
 frame.dataset.pindahAlamat=paths[1];assert.equal(valid(),false);frame.dataset.pindahAlamat=paths[0];
 session.dataset.token='old';assert.equal(valid(),false);session.dataset.token=p.sesi;
 frame.contains=()=>false;assert.equal(valid(),false);frame.contains=n=>[main,session].includes(n);
 doc.querySelectorAll=()=>[{},{}];assert.equal(valid(),false);
});
test('retry focuses read content, not a mutation field; unrelated links do not select actions',()=>{
 const config=adapter.configuration(paths[0],'https://fixture.invalid'),retry={},calls=[],content={focus:opts=>calls.push(opts),querySelectorAll:()=>[]};
 config.restoreFocus({focus:retry,retry,content});assert.equal(content.tabIndex,-1);assert.deepEqual(calls,[{preventScroll:true}]);
 config.restoreFocus({focus:{closest:()=>null},retry,content});assert.equal(calls.length,1);
});
