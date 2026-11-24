import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {state,validData,validCatalog,menuValid,backContext,visibleLink}=require('../app/web/static/kerangka-riwayat-detail-ui-runtime.js');
const {anchorHandler,summaryHandler}=require('../app/web/static/riwayat-detail-katalog.js');
const {restoreNative}=require('../app/web/static/riwayat-detail-native.js');
const origin='https://fixture.invalid',source='a'.repeat(64),digest='b'.repeat(64);
const variants=['riwayat-giling','riwayat-sosoh','riwayat-pengeringan','qc-gabah-basah','qc-gabah-kering','qc-pk-luar','qc-pk-hasil-giling','qc-beras-hasil-sosoh','qc-beras-daftar'];
const data={versi:1,sumber:source,variants:Object.fromEntries(variants.map(v=>[v,{html:'',title:v,breadcrumb:''}])),styles:{},scripts:{}};
const binding={context:'context',cap:'cap',token:'session',source,digest};
function envelope(){return {versi:1,sumber:source,cap:'cap',konteks:'context',sesi:'session',sumber_sha256:digest,batas:30,boleh_catat_qc:false,entries:[{alamat:'/riwayat-giling/1',kode:'GL-1',variant:'riwayat-giling',boleh_koreksi:false}]};}
for(const path of ['/riwayat-giling/1','/riwayat-sosoh/2','/riwayat-pengeringan/3','/riwayat-qc/gabah-basah/GB-1','/riwayat-qc/gabah-kering/GK-1','/riwayat-qc/pk-luar/PK-1','/riwayat-qc/pk-hasil-giling/GL-1','/riwayat-qc/beras-hasil-sosoh/SH-1','/riwayat-qc/beras-hasil-sosoh'])test('narrow native route '+path,()=>assert.ok(state(path,origin)));
for(const path of ['/riwayat-transfer/1','/riwayat-giling/0','/riwayat-giling/2147483648','/riwayat-giling/1?koreksi=berhasil','/riwayat-sosoh/1?buka=','/riwayat-qc/pk-luar','/riwayat-qc/pk-luar/PK?nilai=','/riwayat-qc/pk-luar/PK?tab_qc=asal&tab_qc=putaran','/riwayat-qc/beras-hasil-sosoh?tab_qc=sampel','/riwayat-giling/1?halaman_jeda=0','/riwayat-qc/pk-luar/PK?putaran=-1','/riwayat-qc/pk-luar/PK?kembali_qc=%XX','https://other.invalid/riwayat-giling/1','//other.invalid/riwayat-giling/1'])test('native decline '+path,()=>assert.equal(state(path,origin),null));
test('drying tab precedence and ordinary QC defaults match native',()=>{
 assert.equal(state('/riwayat-pengeringan/1?halaman_ukur=2',origin).tab,'pengukuran');
 assert.equal(state('/riwayat-pengeringan/1?halaman_dingin=2',origin).tab,'riwayat');
 assert.equal(state('/riwayat-pengeringan/1?tab_detail=bahan&halaman_ukur=2',origin).tab,'bahan');
 assert.equal(state('/riwayat-qc/gabah-basah/GB?tab_qc=unknown',origin).tab,'ringkasan');
});
test('data and source are exact and bounded',()=>{
 assert.equal(validData(data),true);assert.equal(validData({...data,user_id:1}),false);
 assert.equal(validData({...data,variants:{...data.variants,'riwayat-giling':{html:'x'.repeat(262145),title:'x'}}}),false);
});
test('catalog equality protects every identity dimension and its row reference',()=>{
 assert.equal(validCatalog(envelope(),binding),true);
 for(const key of ['sumber','cap','konteks','sesi','sumber_sha256'])assert.equal(validCatalog({...envelope(),[key]:'old'},binding),false,key);
 assert.equal(validCatalog({...envelope(),entries:Array(31).fill(envelope().entries[0])},binding),false);
 assert.equal(validCatalog({...envelope(),entries:[{...envelope().entries[0],alamat:'/riwayat-transfer/1'}]},binding),false);
 assert.equal(validCatalog({...envelope(),entries:[{alamat:'/riwayat-qc/pk-luar/PK-1',kode:'PK-2',variant:'qc-pk-luar',boleh_koreksi:false}]},binding),false);
 assert.equal(validCatalog({...envelope(),entries:[{alamat:'/riwayat-qc/pk-luar/PK-1',kode:'PK-1',variant:'qc-pk-luar',boleh_koreksi:true}]},binding),false);
});
test('native menu must authorize the destination and match program/session',()=>{
 const p={versi:1,cap:'cap',konteks:'context',sesi:'session',sumber:source,targets:['/riwayat-giling'],menu:{default:'/riwayat-giling',tabs:{proses:{first:'/riwayat-giling',allowed:['/riwayat-giling']}}}};
 assert.equal(menuValid(p,{...binding,digest:source}),true);
 assert.equal(menuValid({...p,sesi:'old'},{...binding,digest:source}),false);
 assert.equal(menuValid({...p,menu:{...p.menu,tabs:{proses:{first:'/riwayat-transfer',allowed:['/riwayat-transfer']}}}},{...binding,digest:source}),false);
 assert.equal(menuValid(p,{...binding,digest:'old'}),false);
});
test('only the exact old code link handler can be removed',()=>{
 assert.equal(anchorHandler('event.preventDefault();event.stopPropagation();location.href=this.href'),true);
 assert.equal(anchorHandler('event.preventDefault(); sendBusinessWrite()'),false);
 assert.equal(summaryHandler("event.preventDefault();location.href='/riwayat-sosoh/1'",'/riwayat-sosoh/1'),true);
 assert.equal(summaryHandler("event.preventDefault();location.href='/riwayat-sosoh/2'",'/riwayat-sosoh/1'),false);
});
test('redirected/missing native content is not fabricated as history detail',()=>assert.equal(restoreNative({querySelector:()=>null},'bahan','riwayat-giling'),null));
test('native back preserves Giling cursor/hash and scoped drying context',()=>{
 assert.equal(backContext(state('/riwayat-giling/12?sebelum=30',origin),origin),'/riwayat-giling?sebelum=30#giling-12');
 assert.equal(backContext(state('/riwayat-giling/12?sebelum=0',origin),origin),'/riwayat-giling#giling-12');
 assert.equal(backContext(state('/riwayat-pengeringan/12?kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan',origin),origin),'/pekerjaan?tab=berjalan');
 assert.equal(backContext(state('/riwayat-pengeringan/12?kembali_kerja=https%3A%2F%2Fother.invalid',origin),origin),'/riwayat-pengeringan');
});
test('matching href alone outside a currently visible native row is insufficient',()=>{
 const oldDocument=global.document,oldStyle=global.getComputedStyle;
 let rowPresent=true,rowVisible=true;
 const row={getClientRects:()=>rowVisible?[{}]:[],closest:()=>null};
 const a={getClientRects:()=>[{}],getAttribute:k=>k==='href'?'/riwayat-giling/1':null,hasAttribute:()=>false,textContent:'GL-1',classList:{contains:()=>true},closest:s=>s.startsWith('article')?(rowPresent?row:null):null};
 global.document={querySelector:()=>({querySelectorAll:()=>[a]})};global.getComputedStyle=()=>({visibility:'visible'});
 try{
  const entry=envelope().entries[0];assert.equal(visibleLink(entry),a);
  rowPresent=false;assert.equal(visibleLink(entry),null); // Kontrol negatif: href/kode sama di luar baris native.
  rowPresent=true;rowVisible=false;assert.equal(visibleLink(entry),null);
 }finally{if(oldDocument===undefined)delete global.document;else global.document=oldDocument;if(oldStyle===undefined)delete global.getComputedStyle;else global.getComputedStyle=oldStyle;}
});
