/* Pure DOM protocol models only; not a browser/native auth/recovery proof. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const ui=require('../app/web/static/sosoh-native-html.js');
const origin='https://fixture.invalid';
test('preserves actual native address without rewrite',()=>{
 const address='/proses-aktif/sosoh/S-FIXTURE?tab_detail=hasil&kembali_kerja=%2Fpekerjaan';
 assert.equal(ui.nativeAddress(address,origin),address);
 assert.equal(ui.tabFromAddress(address,origin),'hasil');
 assert.equal(ui.tabFromAddress('/proses-aktif/sosoh/S?tab_detail=other',origin),'ringkasan');
});
for(const address of ['/proses-sosoh/X','/proses-aktif/giling/X',
 '//other.invalid/proses-aktif/sosoh/X','/proses-aktif/sosoh/X#qc',
 '/proses-aktif/sosoh/X?buka=hasil','/proses-aktif/sosoh/X?nilai=2',
 '/proses-aktif/sosoh/X?tab_detail=qc&tab_detail=hasil','/proses-aktif/sosoh/X?tenant_id=1'])
 test('declines unsupported context '+address,()=>assert.equal(ui.nativeAddress(address,origin),null));

function native(layout='admin',state={},nodes={}){
 const root={dataset:{layout},pfSosohData:{aktif:true},pfSosohPresentationState:state,
  querySelector:q=>nodes[q]||null};
 return {root,content:{querySelector:q=>q==='[data-sosoh-ringkas]'?root:null}};
}
test('admin restores only selected native readonly tab',()=>{
 let calls=0;
 const button={disabled:false,click(){calls++;}};
 const {content}=native('admin',{}, {'button[role="tab"][data-sr-tab="qc"]':button});
 assert.equal(ui.restoreNativeView(content,{layout:'admin',tab:'qc'}),button);
 assert.equal(calls,1);
});
for(const state of [{busy:true},{uncertain:true},{action:true},{review:true}])
 test('native presentation guard wins '+JSON.stringify(state),()=>{
  const {root,content}=native('admin',state);
  root.querySelector=()=>{throw Error('do not touch view');};
  assert.equal(ui.restoreNativeView(content,{layout:'admin',tab:'qc'}),null);
 });
test('mismatch and incomplete native reader fail closed',()=>{
 const {root,content}=native();
 assert.throws(()=>ui.restoreNativeView(content,{layout:'operator'}),/Susunan proses/);
 delete root.pfSosohData;
 assert.throws(()=>ui.restoreNativeView(content,{layout:'admin'}),/Status simpan/);
});
test('finished native remains finished and no tab forced',()=>{
 const {root,content}=native();root.pfSosohData.aktif=false;
 assert.equal(ui.restoreNativeView(content,{layout:'admin',tab:'hasil'}),null);
});
test('operator restores disclosure only without result or cycle selection',()=>{
 const qc={open:false},more={open:false},pack={open:true},silo={hidden:false};let toggles=0;
 const {content}=native('operator',{}, {
  '[data-sr-fold="qcTerbuka"]':qc,'[data-sr-output-samping]':more,
  '[data-sr-pack]':pack,'#sr-work-silos':silo,
  '.sr-work-source-toggle':{click(){toggles++;silo.hidden=true;}},
 });
 assert.equal(ui.restoreNativeView(content,{layout:'operator',qc:true,more:true,pack:false,silo:false}),null);
 assert.deepEqual([qc.open,more.open,pack.open,silo.hidden,toggles],[true,true,false,true,1]);
});
test('shell snapshot contains no identity/amount/key/draft',()=>{
 const state=ui.snapshot({dataset:{layout:'operator',snTab:'qc'},querySelector:q=>q==='[data-sn-silo-body]'?{hidden:true}:{open:true}});
 assert.deepEqual(state,{layout:'operator',tab:'qc',qc:true,more:true,pack:true,silo:false});
});
