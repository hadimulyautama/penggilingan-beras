import {test} from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ui=require('../app/web/static/kerangka-karung-detail-ui-runtime.js');
const origin='https://fixture.invalid',url='/stok/karung/detail?material=biasa&ukuran=50&merk=&pemilik=pabrik',source='/stok?tab=karung',ctx='ctx',cap='cap',token='session',digest='b'.repeat(64),data={sumber:'a'.repeat(64)};
function catalog(){return {versi:1,sumber:data.sumber,cap,konteks:ctx,sesi:token,asal:source,asal_sha256:digest,entries:[{alamat:url,identity_label:'biasa · 50 kg · Tanpa merek'}]};}
test('finite readonly source-list URI excludes editor/action targets',()=>{
 assert(ui.address(url,origin));for(const bad of [url+'&buka=edit',url+'&tindakan=pindah',url+'&curah=curah:1',url+'&material=other','/stok/sumber/karung/1','//outside.invalid'+url,url+'#edit',url.replace('ukuran=50','ukuran=0'),url.replace('pemilik=pabrik','pemilik=')])assert.equal(ui.address(bad,origin),null,bad);
});
test('catalog is exact source CAP context session digest and bounded identity references',()=>{
 assert(ui.valid(catalog(),data,source,ctx,cap,token,digest));
 for(const mutate of [c=>c.cap='old',c=>c.konteks='other',c=>c.sesi='other',c=>c.sumber='other',c=>c.asal='/other',c=>c.asal_sha256='0'.repeat(64),c=>c.entries=[],c=>c.entries.push(c.entries[0]),c=>c.entries[0].alamat='/stok/sumber/karung/1',c=>c.entries[0].alamat=url+'&buka=write',c=>c.entries[0].alamat='//other.invalid'+url,c=>c.entries[0].quantity=0,c=>c.entries[0].identity_label='',c=>c.entries[0].identity_label='a'.repeat(513)]){const c=catalog();mutate(c);assert.equal(ui.valid(c,data,source,ctx,cap,token,digest),false);}
 for(const value of [undefined,'','wrong','c'.repeat(64)])assert.equal(ui.valid(catalog(),data,source,ctx,cap,token,value),false);
});
test('same current computed-visible native link required; hidden/foreign fails',()=>{
 const link={getAttribute:k=>k==='href'?url:null,closest:()=>null,hasAttribute:()=>false},doc={querySelectorAll:()=>[link]};
 assert(ui.visible(doc,url,()=>true));assert.equal(ui.visible(doc,url,()=>false),false);assert.equal(ui.visible(doc,'/other',()=>true),false);assert.equal(ui.visible({querySelectorAll:()=>Array(101).fill(link)},url,()=>true),false);link.closest=()=>({});assert.equal(ui.visible(doc,url,()=>true),false);
});
