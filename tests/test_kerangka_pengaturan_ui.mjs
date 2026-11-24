import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {valid,validURL}=require('../app/web/static/kerangka-pengaturan-ui-runtime.js');
const source='a'.repeat(64);
const component=()=>({title:'Pengaturan',html:'',breadcrumb:'<nav class="desktop-breadcrumb"></nav><a class="desktop-back" href="/">Kembali</a>',mobile:'<button class="bar__menu" id="buka-laci" type="button"></button>'});
const data={versi:1,sumber:source,variants:{'/pengaturan':component(),'/pengaturan/sesi':component()},styles:{},scripts:{}};
function state(){return {versi:1,cap:'cap',konteks:'context',sesi:'session',sumber:source,groups:{akun:[true,false,true],fasilitas:[true,false,false,false,false],operasional:[false,false,false,false],pengguna:[false,true],sistem:[false,false,true]},advanced:false,recovery:false,short:false,console:''};}
test('strict document binding and native boolean slots only',()=>{
 const p=state();assert.equal(valid(data,p,'context','cap','session'),true);
 for(const [key,value] of [['sesi','old'],['konteks','other'],['cap','old'],['sumber','b'.repeat(64)],['advanced','true'],['short',null]]){
  assert.equal(valid(data,{...p,[key]:value},'context','cap','session'),false,key);
 }
 for(const flags of [[true],[true,'admin',true],[true,1,true]])assert.equal(valid(data,{...p,groups:{...p.groups,akun:flags}},'context','cap','session'),false);
 assert.equal(valid(data,{...p,company_id:1},'context','cap','session'),false);
});
test('external Console address must be native HTTPS without embedded identity or query',()=>{
 assert.equal(validURL('https://console-fixture.invalid/console'),true);
 for(const u of ['http://console.invalid','https://u:p@console.invalid','https://console.invalid/?token=x','https://console.invalid/#secret','javascript:alert(1)'])assert.equal(validURL(u),false,u);
 const p=state();p.console='https://console-fixture.invalid/console';assert.equal(valid(data,p,'context','cap','session'),false);
 p.groups.fasilitas.splice(1,0,true);assert.equal(valid(data,p,'context','cap','session'),true);
});
test('both target chrome fragments are required, without changing private permission slots',()=>{
 for(const path of ['/pengaturan','/pengaturan/sesi'])for(const key of ['title','html','breadcrumb','mobile']){
  const missing=structuredClone(data);delete missing.variants[path][key];assert.equal(valid(missing,state(),'context','cap','session'),false,path+':'+key);
  const wrong=structuredClone(data);wrong.variants[path][key]={};assert.equal(valid(wrong,state(),'context','cap','session'),false,path+':'+key);
 }
 const oversized=structuredClone(data);oversized.variants['/pengaturan'].breadcrumb='x'.repeat(65537);
 assert.equal(valid(oversized,state(),'context','cap','session'),false);
 const wrongTitle=structuredClone(data);wrongTitle.variants['/pengaturan/sesi'].title='';
 assert.equal(valid(wrongTitle,state(),'context','cap','session'),false);
});
