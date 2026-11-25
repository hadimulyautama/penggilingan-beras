/* Actual native driver, no browser/server: a missing form must end ownership. */
'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const path=require('node:path');

function run(kind,{formPresent=false,removeGuard=false}={}){
 const source=fs.readFileSync(path.join(__dirname,'../app/web/static/riwayat-'+kind+'-desain.js'),'utf8');
 const listeners=[],writes=[],restores=[];
 const control={addEventListener:(type,fn)=>listeners.push(type),close(){},showModal(){}};
 const oldForm={dataset:{rhsFormReady:'1'},closest:()=>({open:false})};
 const currentForm={replaceWith:node=>restores.push(node),dataset:{}};
 const actor='7:native-fixture::12',token=formPresent?'native-form-token':'';
 const cache={tab:'ringkasan',form:oldForm};
 const namespace='PADI_RIWAYAT_'+kind.toUpperCase()+'_DRAF';
 const root={dataset:{rhsActor:actor,tabAwal:'ringkasan',rhsReturn:'0'},parentElement:null,
  querySelectorAll:()=>[],
  querySelector(selector){
   if(selector==='.riwayat-koreksi__form')return formPresent?currentForm:null;
   if(selector==='.riwayat-koreksi__form [name=_csrf]')return formPresent?{value:token}:null;
   if(selector==='.rhs-tabs'||selector==='#rhs-panduan'||selector==='[data-rhs-guide-close]')return control;
   return null;
  }};
 const window={PINDAH:{pasang:(_target,type)=>listeners.push(type)},[namespace]:{[actor+'|'+token]:cache}};
 const document={querySelector:()=>root,getElementById:()=>null,createElement(){throw Error('No form UI should be constructed');}};
 const context={window,PINDAH:window.PINDAH,document,location:{hash:''},fetch(...args){writes.push(args);throw Error('No native POST is allowed without a form');},MutationObserver:class{constructor(){throw Error('No writer observer should be created');}}};
 const program=removeGuard?source.replace('if(!form)return;',''):source;
 if(removeGuard)assert.notEqual(program,source);
 vm.runInNewContext(program,context,{filename:'riwayat-'+kind+'-desain.js'});
 return {cache,oldForm,restores,listeners,writes};
}

for(const kind of ['giling','sosoh']){
 test(kind+': cached editable node cannot be reinserted into actual readonly native root',()=>{
  const result=run(kind);
  assert.equal(result.cache.form,result.oldForm);
  assert.equal(result.restores.length,0);assert.equal(result.writes.length,0);
  assert.ok(!result.listeners.includes('submit')&&!result.listeners.includes('input')&&!result.listeners.includes('change'));
 });
 test(kind+': actual editable native path still restores its existing form (marker must remain)',()=>{
  const result=run(kind,{formPresent:true});
  assert.equal(result.restores.length,1);assert.equal(result.restores[0],result.oldForm);
  assert.equal(result.writes.length,0);
 });
 test(kind+': removing native no-form guard makes the cached-form control fail',()=>{
  assert.throws(()=>run(kind,{removeGuard:true}),/replaceWith/);
 });
}

test('shared native correction dispatcher does not POST without its matching form',async()=>{
 const handlers=[],requests=[];
 const document={addEventListener:(type,fn)=>handlers.push({type,fn})};
 const context={window:{},document,fetch:(...args)=>{requests.push(args);throw Error('Unexpected POST');}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../hmu_tampilan/static/koreksi.js'),'utf8'),context);
 assert.equal(handlers.length,1);assert.equal(handlers[0].type,'submit');
 assert.equal(requests.length,0);
 await handlers[0].fn({target:{matches:()=>false},preventDefault(){throw Error('Unrelated submit must remain untouched');}});
 assert.equal(requests.length,0);
});
