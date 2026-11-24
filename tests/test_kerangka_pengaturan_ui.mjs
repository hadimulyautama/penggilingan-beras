import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {valid,validURL}=require('../app/web/static/kerangka-pengaturan-ui-runtime.js');
const source='a'.repeat(64);
const data={versi:1,sumber:source,variants:{'/pengaturan':{title:'Pengaturan',html:''},'/pengaturan/sesi':{title:'Sesi perangkat',html:''}},styles:{},scripts:{}};
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
