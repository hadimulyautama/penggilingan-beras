/* Pure factory and address-boundary tests. No DOM/browser or real requests. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const core=createRequire(import.meta.url)('../app/web/static/padi-baca-native.js');
const ORIGIN='https://fixture.invalid';
const identity=address=>({cap:'fixture-release',context:'fixture-context',token:'fixture-session',address});
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
function fixture(address='/laporan',overrides={}){
 const calls={read:0,prepare:0,install:0,fail:[]};
 const ops={address,origin:ORIGIN,identity:identity(address),current:()=>true,loading(){},
  async fetch(){calls.read++;return 'native read fixture';},
  async parse(){return {identity:identity(address)};},
  async prepare(){calls.prepare++;return [];},install(){calls.install++;},failed(e){calls.fail.push(e.message);},...overrides};
 return {calls,reader:core.createReader(ops)};
}
test('explicit same-origin canonical route supports a declared read filter',()=>{
 assert(core.sameOriginAddress('/laporan?bagian=giling&rentang=bulan',ORIGIN));
 for(const address of [undefined,'laporan','//other.invalid/x','https://fixture.invalid/laporan','https://other.invalid/laporan','/laporan#x','/x/../laporan','/\\other.invalid/x','/laporan?'])assert.equal(core.sameOriginAddress(address,ORIGIN),false,address);
});
test('core identity requires explicit expected address, even if both identities agree',()=>{
 assert.equal(core.sameIdentity(identity('/laporan'),identity('/laporan')),false);
 assert.equal(core.sameIdentity(identity('/pengaturan/akun'),identity('/pengaturan/akun'),'/laporan'),false);
 assert.equal(core.sameIdentity(identity('/laporan'),identity('/laporan'),'/laporan'),true);
});
test('factory refuses an undeclared/cross-origin address before any operation',()=>{
 for(const address of [undefined,'//other.invalid/x','https://other.invalid/laporan'])assert.throws(()=>fixture(address===undefined?null:address),TypeError);
});
test('declared report route can install exactly once without account adapter',async()=>{
 const f=fixture();await f.reader.read();await f.reader.read();
 assert.equal(f.calls.read,1);assert.equal(f.calls.prepare,1);assert.equal(f.calls.install,1);
});
test('HTML for another address never reaches asset preparation or install',async()=>{
 const f=fixture('/laporan',{async parse(){return {identity:identity('/pengaturan/akun')};}});
 await f.reader.read();assert.equal(f.calls.prepare,0);assert.equal(f.calls.install,0);assert.equal(f.calls.fail.length,1);
});
test('wrong fresh cap/context/session cannot be silently adopted',async()=>{
 for(const key of ['cap','context','token']){
  const f=fixture('/laporan',{async parse(){return {identity:{...identity('/laporan'),[key]:'changed'}};}});
  await f.reader.read();assert.equal(f.calls.prepare,0);assert.equal(f.calls.install,0);assert.equal(f.calls.fail.length,1);
 }
});
test('navigation during asset preparation prevents native script activation',async()=>{
 let current=true;const barrier=deferred(),entered=deferred();
 const f=fixture('/laporan',{current:()=>current,async prepare(){entered.resolve();await barrier.promise;return [];}});
 const read=f.reader.read();await entered.promise;current=false;barrier.resolve();await read;
 assert.equal(f.calls.install,0);
});
test('leaving before first read is inert; after stop no retry can fetch',async()=>{
 const f=fixture();f.reader.stop();await f.reader.read();assert.equal(f.calls.read,0);assert.equal(f.calls.install,0);
});
