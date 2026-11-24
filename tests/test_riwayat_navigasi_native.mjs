import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {resolve}=require('../app/web/static/riwayat-navigasi-native.js');
const frames=['/riwayat-sosoh','/riwayat-giling','/riwayat-qc/pk-luar'];
const menu={default:'/riwayat-sosoh',tabs:{
 proses:{first:'/riwayat-sosoh',allowed:['/riwayat-sosoh','/riwayat-giling']},
 qc:{first:'/riwayat-qc/pk-luar',allowed:['/riwayat-qc/pk-luar']},
 audit:{first:'/audit',allowed:['/audit']}}};
menu.tabs.laporan={first:'/laporan',allowed:['/laporan']};
test('uses the actual native default when no remembered choice exists',()=>{
 assert.equal(resolve(menu,frames,'/kabar',null,null),'/riwayat-sosoh');
});
test('retains current native history family before remembered choice',()=>{
 assert.equal(resolve(menu,frames,'/riwayat-giling','qc','/riwayat-qc/pk-luar'),'/riwayat-giling');
});
test('the report catalogue does not replace the remembered history destination',()=>{
 assert.equal(resolve(menu,frames,'/laporan','proses','/riwayat-giling'),'/riwayat-giling');
});
test('only a remembered native allowed address is reused',()=>{
 assert.equal(resolve(menu,frames,'/kabar','proses','/riwayat-giling'),'/riwayat-giling');
 for(const stale of ['/audit','/riwayat-transfer','https://foreign.invalid/riwayat-giling','/riwayat-giling?company=other'])
  assert.equal(resolve(menu,frames,'/kabar','proses',stale),'/riwayat-sosoh');
});
test('unadopted doors and missing frames fall back to native navigation',()=>{
 assert.equal(resolve(menu,frames,'/kabar','audit','/audit'),null);
 assert.equal(resolve(menu,[],'/kabar',null,null),null);
 assert.equal(resolve(null,frames,'/kabar',null,null),null);
 assert.equal(resolve({default:'/riwayat-transfer',tabs:{}},frames,'/kabar',null,null),null);
});
