/* Pure protocol negatives, not browser/auth/runtime fixture evidence. */
import test from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {readFileSync} from 'node:fs';import vm from 'node:vm';
const require=createRequire(import.meta.url),api=require('../app/web/static/kerangka-fasilitas-parent-ui-runtime.js'),adapter=require('../app/web/static/fasilitas-parent-native.js');
const sandbox={window:{},module:{exports:{}},URL};vm.runInNewContext(readFileSync(new URL('../app/web/static/kerangka-fasilitas-parent-ui.js',import.meta.url),'utf8'),sandbox);
const data=sandbox.window.PadiKerangkaFasilitasParentData,p={versi:1,cap:'cap',konteks:'ctx',sesi:'fixture-token',sumber:data.sumber,targets:[...api.TARGETS]};
test('four bare parent addresses only; no detail/query/feedback/config/POST endpoints',()=>{
 for(const address of api.TARGETS)assert.equal(adapter.configuration(address,'https://fixture.invalid').address,address);
 for(const target of ['/pengaturan/alat','/pengaturan/dryer/7','/pengaturan/mesin/7','/pengaturan/fasilitas',api.TARGETS[0]+'?tersimpan=1',api.TARGETS[1]+'#edit','https://other.invalid'+api.TARGETS[2],'//fixture.invalid'+api.TARGETS[2]])assert.equal(adapter.configuration(target,'https://fixture.invalid'),null);
});
test('exact current program/cap/session/context and targets; metadata is not a role',()=>{
 const valid=x=>api.valid(data,x,p.konteks,p.cap,p.sesi);assert.equal(valid(p),true);
 for(const key of ['cap','konteks','sesi','sumber'])assert.equal(valid({...p,[key]:'old'}),false);
 for(const targets of [[],['/pengaturan/alat'],p.targets.slice(0,3),[...p.targets].reverse(),[...p.targets,'/pengaturan/mesin/7']])assert.equal(valid({...p,targets}),false);
 for(const extra of [{allowed:true},{is_admin:true},{user_id:1}])assert.equal(valid({...p,...extra}),false);
 assert.equal(valid(null),false);
});
test('a frame and contained session/root must be unique and current',()=>{
 const address=api.TARGETS[0],main={},session={dataset:{token:p.sesi}},frame={dataset:{pindahAlamat:address,pindahKonteks:p.konteks},contains:n=>[main,session].includes(n)};
 const doc={documentElement:{dataset:{versi:p.cap}},querySelector:()=>frame,querySelectorAll:()=>[{}],getElementById:id=>id==='isi-halaman'?main:session};
 const valid=()=>api.frameBound(doc,p.konteks,p.cap,p.sesi,address);assert.equal(valid(),true);
 for(const [key,value] of [['pindahAlamat','/pengaturan'],['pindahKonteks','old']]){const old=frame.dataset[key];frame.dataset[key]=value;assert.equal(valid(),false);frame.dataset[key]=old;}
 session.dataset.token='old';assert.equal(valid(),false);session.dataset.token=p.sesi;
 frame.contains=()=>false;assert.equal(valid(),false);frame.contains=n=>[main,session].includes(n);
 doc.querySelectorAll=()=>[{},{}];assert.equal(valid(),false);
});
test('invalid or oversized public component and unexpected program shape decline',()=>{
 const copy=()=>JSON.parse(JSON.stringify(data)),valid=x=>api.valid(x,p,p.konteks,p.cap,p.sesi);
 let d=copy();d.variants[api.TARGETS[0]].title='Invented role title';assert.equal(valid(d),false);
 d=copy();d.variants[api.TARGETS[0]].html='x'.repeat(65537);assert.equal(valid(d),false);
 d=copy();d.variants['/pengaturan/alat']=d.variants[api.TARGETS[0]];assert.equal(valid(d),false);
 d=copy();d.scripts.bad=42;assert.equal(valid(d),false);
});
test('retry focus is read content; only matching native peer link gets focus',()=>{
 const config=adapter.configuration(api.TARGETS[0],'https://fixture.invalid'),retry={},calls=[],content={focus:o=>calls.push(o),querySelectorAll:()=>[]};
 config.restoreFocus({focus:retry,retry,content});assert.equal(content.tabIndex,-1);assert.equal(calls.length,1);
 const source={getAttribute:()=>'/pengaturan'},peer={getAttribute:()=>'/pengaturan',focus:o=>calls.push(o)};content.querySelectorAll=()=>[peer];
 config.restoreFocus({focus:{closest:()=>source},retry,content});assert.equal(calls.length,2);
 config.restoreFocus({focus:{closest:()=>null},retry,content});assert.equal(calls.length,2);
});
test('factory refuses cross-address/stale scope before parsing or touching controls',()=>{
 let parses=0;const window={PadiKerangkaFasilitasParentData:data},session={dataset:{token:p.sesi}},main={},frame={dataset:{pindahAlamat:'/pengaturan',pindahKonteks:p.konteks},contains:n=>n===main||n===session};
 const document={documentElement:{dataset:{versi:p.cap}},querySelector:()=>frame,querySelectorAll:()=>[{}],getElementById:id=>id==='isi-halaman'?main:session};
 const context={window,document,location:{pathname:'/pengaturan',search:''},DOMParser:class{parseFromString(){parses++;throw Error('must not parse');}}};
 vm.runInNewContext(readFileSync(new URL('../app/web/static/kerangka-fasilitas-parent-ui-runtime.js',import.meta.url),'utf8'),context);
 for(const target of ['/pengaturan/mesin/7','https://other.invalid'+api.TARGETS[0],api.TARGETS[0]+'?x=1'])assert.equal(window.PadiKerangkaFasilitasParentUI.buat(target,'base',p.konteks,p.cap,p.sesi),null);
 assert.equal(window.PadiKerangkaFasilitasParentUI.buat(api.TARGETS[0],'x'.repeat(8388609),p.konteks,p.cap,p.sesi),null);
 frame.dataset.pindahKonteks='old';assert.equal(window.PadiKerangkaFasilitasParentUI.buat(api.TARGETS[0],'base',p.konteks,p.cap,p.sesi),null);assert.equal(parses,0);
});
