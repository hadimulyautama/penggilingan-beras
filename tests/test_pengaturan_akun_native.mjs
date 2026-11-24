/* Pure async control contract; no DOM, browser, listener, account or network. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {sameIdentity,createReader}=createRequire(import.meta.url)('../app/web/static/pengaturan-akun-native.js');
const id=()=>({cap:'fixture-cap',context:'fixture-context',token:'fixture-session',address:'/pengaturan/akun'});
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function fixture(overrides={}){
 const calls={get:0,parsed:0,prepared:0,installed:0,errors:[],signals:[]};
 const ops={identity:id(),current:()=>true,loading(){},
  async fetch(signal){calls.get++;calls.signals.push(signal);return 'synthetic native read';},
  async parse(){calls.parsed++;return {identity:id()};},
  async prepare(){calls.prepared++;return ['synthetic prepared asset'];},
  install(){calls.installed++;},failed(e){calls.errors.push(e.message);},...overrides};
 return {ops,calls,reader:createReader(ops)};
}
test('GET completes once; same route/cap/context/session all required',async()=>{
 const f=fixture();await f.reader.read();await f.reader.read();
 assert.equal(f.calls.get,1);assert.equal(f.calls.installed,1);assert.equal(f.calls.errors.length,0);
 for(const k of ['cap','context','token','address'])assert.equal(sameIdentity(id(),{...id(),[k]:'other'}),false);
 assert.equal(sameIdentity(id(),id()),true);
});
test('leaving aborts pending GET and ignores its late HTML',async()=>{
 const pending=deferred();let signal;
 const f=fixture({fetch(s){signal=s;return pending.promise;}});
 const read=f.reader.read();f.reader.stop();assert.equal(signal.aborted,true);
 pending.resolve('late');await read;assert.equal(f.calls.parsed,0);assert.equal(f.calls.installed,0);
});
test('account or route changes during asset preparation cannot activate native form',async()=>{
 const pending=deferred();let active=true;
 const f=fixture({current:()=>active,prepare:()=>pending.promise});
 const read=f.reader.read();await Promise.resolve();await Promise.resolve();
 active=false;pending.resolve([]);await read;assert.equal(f.calls.installed,0);
});
test('mismatched fresh identity stays disabled; GET retry can recover',async()=>{
 let wrong=true;
 const f=fixture({async parse(){return {identity:wrong?{...id(),context:'other-company-context'}:id()};}});
 await f.reader.read();assert.equal(f.calls.installed,0);assert.equal(f.calls.errors.length,1);
 wrong=false;await f.reader.read();assert.equal(f.calls.get,2);assert.equal(f.calls.installed,1);
});
test('retry supersedes older read without two installs',async()=>{
 const old=deferred(),recent=deferred();let count=0;const signals=[];
 const f=fixture({fetch(s){signals.push(s);return ++count===1?old.promise:recent.promise;}});
 const a=f.reader.read(),b=f.reader.read();assert.equal(signals[0].aborted,true);
 recent.resolve('new');await b;old.resolve('old');await a;
 assert.equal(f.calls.installed,1);assert.equal(f.calls.parsed,1);
});
test('read failure preserves shell for retry, never activates any native form',async()=>{
 const f=fixture({async fetch(){throw Error('synthetic read failure');}});
 await f.reader.read();assert.equal(f.calls.installed,0);assert.deepEqual(f.calls.errors,['synthetic read failure']);
});
