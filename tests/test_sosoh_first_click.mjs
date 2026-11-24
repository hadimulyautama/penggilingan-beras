/* Pure public factory guards/DOM protocol only, not browser or DB authorization. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ui=require('../app/web/static/kerangka-sosoh-ui-runtime.js');
const origin='https://fixture.invalid',ctx='ctx',cap='cap',token='token';
const schema=[{jenis:'spek_fixture_z',nama:'Label uji Z',beras:true},{jenis:'samping_fixture_x',nama:'Label uji X',beras:false}];
function data(){return {versi:1,sumber:'a'.repeat(64),variants:{admin:{html:'<section></section>'},operator:{html:'<section></section>'}},styles:{},scripts:{}};}
function permission(){return {versi:1,sumber:'a'.repeat(64),cap,konteks:ctx,sesi:token,layout:'operator',hasil:structuredClone(schema)};}
const address='/proses-aktif/sosoh/S-FIXTURE?tab_detail=hasil';
function catalog(){return {versi:1,cap,konteks:ctx,sesi:token,sumber_sha256:'b'.repeat(64),entries:[{alamat:address,kode:'S-FIXTURE',label:'Penyosohan aktif'}]};}
test('exact sameURL native GET only',()=>{
 assert.equal(ui.address(address,origin).tab,'hasil');
 assert.equal(ui.address('/proses-aktif/sosoh/S?tab_detail=unknown',origin).tab,'ringkasan');
 for(const value of ['/proses-aktif/giling/S','/proses-sosoh/S','//other.invalid/proses-aktif/sosoh/S','/proses-aktif/sosoh/S#qc','/proses-aktif/sosoh/S?buka=hasil','/proses-aktif/sosoh/S?nilai=2','/proses-aktif/sosoh/S?tenant=2','/proses-aktif/sosoh/S?tab_detail=qc&tab_detail=hasil'])assert.equal(ui.address(value,origin),null,value);
});
test('schema, program source, layout and session/context/CAP exact fail closed',()=>{
 assert(ui.validPermission(permission(),data(),ctx,cap,token));
 for(const mutate of [p=>p.konteks='old',p=>p.cap='old',p=>p.sesi='old',p=>p.sumber='b'.repeat(64),p=>p.layout='Super',p=>p.hasil=[],p=>p.hasil.push(p.hasil[0]),p=>p.hasil[0].kg=0,p=>p.hasil[0].id=1,p=>p.hasil[0].beras=1,p=>p.account=1,p=>p.hasil[0].nama='']){
  const p=permission();mutate(p);assert.equal(ui.validPermission(p,data(),ctx,cap,token),false);
 }
});
test('catalog needs exact code/address and same private binding',()=>{
 assert(ui.validCatalog(catalog(),address,'S-FIXTURE',ctx,cap,token,'b'.repeat(64)));
 for(const mutate of [c=>c.konteks='other',c=>c.sesi='old',c=>c.cap='old',c=>c.sumber_sha256='x',c=>c.entries=[],c=>c.entries[0].alamat='/proses-aktif/sosoh/OTHER',c=>c.entries[0].kode='OTHER',c=>c.entries[0].label='Penggilingan aktif',c=>c.entries[0].kg=0]){
  const c=catalog();mutate(c);assert.equal(ui.validCatalog(c,address,'S-FIXTURE',ctx,cap,token,'b'.repeat(64)),false);
 }
});
test('schema splitting equals native operator rice / admin first six, no values',()=>{
 assert.deepEqual(ui.fieldGroups(schema,'operator'),{main:[schema[0]],more:[schema[1]]});
 const many=Array.from({length:9},(_,i)=>({jenis:'x'+i,nama:'N'+i,beras:i%2===0}));
 assert.deepEqual(ui.fieldGroups(many,'admin'),{main:many.slice(0,6),more:many.slice(6)});
});
function dom({hidden=false,shown=true,href=address,code='S-FIXTURE',disabled=false,strongShown=true,linkShown=true}={}){
 const strong={textContent:code,closest:()=>null,shown:strongShown};
 const link={getAttribute:k=>k==='href'?href:k==='aria-disabled'&&disabled?'true':null,hasAttribute:()=>false,closest:()=>null,shown:linkShown};
 const row={closest:()=>hidden?{}:null,shown,querySelector:()=>strong,matches:()=>false,querySelectorAll:()=>[link]};
 return {querySelectorAll:()=>[row]};
}
test('actual currently visible Work row and link required in addition to catalog',()=>{
 const shown=n=>n.shown;
 assert(ui.visibleRow(dom(),address,'S-FIXTURE',shown));
 for(const p of [{hidden:true},{shown:false},{strongShown:false},{linkShown:false},{href:'/proses-aktif/sosoh/OTHER'},{code:'OTHER'},{disabled:true}])assert.equal(ui.visibleRow(dom(p),address,'S-FIXTURE',shown),false,JSON.stringify(p));
 assert.equal(ui.visibleRow({querySelectorAll:()=>[]},address,'S-FIXTURE',shown),false);
 assert.equal(ui.visibleRow({querySelectorAll:()=>Array.from({length:51},()=>dom().querySelectorAll()[0])},address,'S-FIXTURE',shown),false);
});
