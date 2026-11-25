/* Pure address/metadata/protocol checks; not browser or auth fixture evidence. */
import test from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {readFileSync} from 'node:fs';import vm from 'node:vm';
const require=createRequire(import.meta.url),api=require('../app/web/static/kerangka-pengaturan-alat-ui-runtime.js'),adapter=require('../app/web/static/pengaturan-alat-native.js');
const sandbox={window:{},module:{exports:{}},URL};vm.runInNewContext(readFileSync(new URL('../app/web/static/kerangka-pengaturan-alat-ui.js',import.meta.url),'utf8'),sandbox);
const data=sandbox.window.PadiKerangkaPengaturanAlatData,address='/pengaturan/alat',p={versi:1,cap:'cap',konteks:'ctx',sesi:'fixture-token',sumber:data.sumber,targets:[address]};
test('only bare Alat hub can mount, not silo/master/operation/query routes',()=>{
 assert.equal(adapter.configuration(address,'https://fixture.invalid').address,address);
 for(const target of [address+'?pesan=x',address+'#draft','/pengaturan/silo','/pengaturan/hasil-samping',address+'/status-simpan/token','https://other.invalid'+address])assert.equal(adapter.configuration(target,'https://fixture.invalid'),null);
});
test('Admin master metadata cannot authorize Alat; targets must be separately verified and exact',()=>{
 const valid=x=>api.valid(data,x,p.konteks,p.cap,p.sesi);assert.equal(valid(p),true);
 assert.equal(valid({...p,targets:[]}),false);assert.equal(valid({...p,targets:[address,'/pengaturan/silo']}),false);assert.equal(valid({...p,targets:['/pengaturan/hasil-samping']}),false);
 const admin={...p,allowed:true};delete admin.targets;assert.equal(valid(admin),false);
 for(const key of ['cap','konteks','sesi','sumber'])assert.equal(valid({...p,[key]:'old'}),false);
 assert.equal(valid({...p,user_id:1}),false);assert.equal(valid(null),false);
});
test('unique contained current native frame and identity are mandatory',()=>{
 const main={},session={dataset:{token:p.sesi}},frame={dataset:{pindahAlamat:address,pindahKonteks:p.konteks},contains:n=>[main,session].includes(n)};
 const doc={documentElement:{dataset:{versi:p.cap}},querySelector:()=>frame,querySelectorAll:()=>[{}],getElementById:id=>id==='isi-halaman'?main:session};
 const valid=()=>api.frameBound(doc,p.konteks,p.cap,p.sesi,address);assert.equal(valid(),true);
 frame.contains=()=>false;assert.equal(valid(),false);frame.contains=n=>[main,session].includes(n);
 frame.dataset.pindahAlamat='/pengaturan';assert.equal(valid(),false);frame.dataset.pindahAlamat=address;
 doc.querySelectorAll=()=>[];assert.equal(valid(),false);
});
test('retry focus goes to read content, current hub link restores only its native peer',()=>{
 const config=adapter.configuration(address,'https://fixture.invalid'),retry={},calls=[],content={focus:o=>calls.push(o),querySelectorAll:()=>[]};
 config.restoreFocus({focus:retry,retry,content});assert.equal(content.tabIndex,-1);assert.equal(calls.length,1);
 const source={getAttribute:()=>'/pengaturan/silo'},target={getAttribute:()=>'/pengaturan/silo',focus:o=>calls.push(o)};
 content.querySelectorAll=()=>[target];config.restoreFocus({focus:{closest:()=>source},retry,content});assert.equal(calls.length,2);
});
