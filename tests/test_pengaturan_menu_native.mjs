import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {configuration}=createRequire(import.meta.url)('../app/web/static/pengaturan-menu-native.js');
test('settings adapter is explicit for index and session only',()=>{
 for(const address of ['/pengaturan','/pengaturan/sesi']){
  const config=configuration(address);assert.equal(config.address,address);
  assert.equal(config.rootSelector,'[data-pengaturan-menu-kerangka]');
 }
 for(const address of ['/pengaturan/peran','/pengaturan/akses','/pengaturan/akun','/pengaturan?err=x','/pengaturan/sesi?company_id=1','https://uji.invalid/pengaturan',undefined])assert.equal(configuration(address),null);
});
test('retry focus is read content, never a session mutation control',()=>{
 const config=configuration('/pengaturan/sesi');let focused=false;
 const retry={},content={focus(){focused=true;}};
 config.restoreFocus({focus:retry,retry,content});assert.equal(focused,true);assert.equal(content.tabIndex,-1);
});
