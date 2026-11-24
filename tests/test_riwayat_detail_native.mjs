import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url);
const {nativeTitle,state,validData,validCatalog,menuValid,backContext,contextualBack,visibleLink}=require('../app/web/static/kerangka-riwayat-detail-ui-runtime.js');
const {anchorHandler,summaryHandler}=require('../app/web/static/riwayat-detail-katalog.js');
const {restoreNative}=require('../app/web/static/riwayat-detail-native.js');
const origin='https://fixture.invalid',source='a'.repeat(64),digest='b'.repeat(64);
const variants=['riwayat-giling','riwayat-sosoh','riwayat-pengeringan','qc-gabah-basah','qc-gabah-kering','qc-pk-luar','qc-pk-hasil-giling','qc-beras-hasil-sosoh','qc-beras-daftar'];
const data={versi:1,sumber:source,variants:Object.fromEntries(variants.map(v=>[v,{html:'',title_parts:[v],breadcrumb_parts:[v],bar_control:'',breadcrumb:''}])),styles:{},scripts:{}};
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

test('native title slot uses exact verified code without changing body H1',()=>{
 assert.equal(nativeTitle(['Detail QC ',null],'QC-A'), 'Detail QC QC-A');
 assert.equal(nativeTitle(['QC beras hasil sosoh'],'QC-A'),'QC beras hasil sosoh');
 assert.equal(nativeTitle(['Riwayat penggilingan ',null],'<LOT>'),'Riwayat penggilingan <LOT>');
 assert.equal(nativeTitle([{user:1}],'LOT'),null);
});
test('hydrated native editor hrefs load complete native controller only on explicit click',()=>{
 const {nativeActions}=require('../app/web/static/riwayat-detail-native.js');
 const hrefs=['?buka=qc_sosoh','/riwayat-pengeringan/1/bobot','/riwayat-giling/1?tab_detail=hasil','https://other.invalid/?buka=x'];
 const links=hrefs.map(href=>({href,mark:false,getAttribute:()=>href,setAttribute(k){if(k==='data-utuh')this.mark=true;}}));
 nativeActions({querySelectorAll:()=>links},origin);
 assert.deepEqual(links.map(x=>x.mark),[true,true,false,false]);
});

test('QC back context follows existing native read-only path whitelist and priority',()=>{
 const choose=query=>state('/riwayat-qc/pk-luar/PK-1?'+query,origin);
 const chosen=choose('kembali_qc=%2Fbarang-masuk%2F12%3Ftab%3Dqc&kembali_jasa=%2Fjasa');
 assert.equal(backContext(chosen,origin),'/barang-masuk/12?tab=qc');
 assert.equal(contextualBack(chosen,backContext(chosen,origin)),true);
 for(const value of ['https://other.invalid/pekerjaan','//other.invalid/pekerjaan','/pengaturan','/api/actions/save','/stok/unknown']){
  const state=choose('kembali_qc='+encodeURIComponent(value));
  assert.equal(backContext(state,origin),'/riwayat-qc/pk-luar');
  assert.equal(contextualBack(state,backContext(state,origin)),false);
 }
 const own=choose('kembali_qc=%2Friwayat-qc%2Fpk-luar');
 assert.equal(contextualBack(own,backContext(own,origin)),false);
});
test('drying native Back label uses presence of raw return query, not invented stock state',()=>{
 const plain=state('/riwayat-pengeringan/12',origin);
 assert.equal(contextualBack(plain,backContext(plain,origin)),false);
 const valid=state('/riwayat-pengeringan/12?kembali_kerja=%2Fpekerjaan',origin);
 assert.equal(contextualBack(valid,backContext(valid,origin)),true);
 const foreign=state('/riwayat-pengeringan/12?kembali_kerja=https%3A%2F%2Fother.invalid',origin);
 assert.equal(backContext(foreign,origin),'/riwayat-pengeringan');
 assert.equal(contextualBack(foreign,backContext(foreign,origin)),true);
});

test('breadcrumb identity parts distinguish History code from native QC title',()=>{
 assert.equal(nativeTitle([null],'LOT-17'),'LOT-17');
 assert.equal(nativeTitle(['Detail QC ',null],'LOT-17'),'Detail QC LOT-17');
 assert.equal(nativeTitle(['QC beras hasil sosoh'],'LOT-17'),'QC beras hasil sosoh');
 const missing={...data,variants:{...data.variants,'qc-gabah-basah':{...data.variants['qc-gabah-basah']}}};
 delete missing.variants['qc-gabah-basah'].breadcrumb_parts;
 assert.equal(validData(missing),false);
});

test('actual pending Giling and Sosoh assets do not initialize a native editor',()=>{
 const payload=readFileSync(new URL('../app/web/static/kerangka-riwayat-detail-ui.js',import.meta.url),'utf8');
 const compiled=JSON.parse(payload.split('window.PadiKerangkaRiwayatDetailData=',2)[1].split(';\n',1)[0]);
 for(const variant of ['riwayat-giling','riwayat-sosoh']){
  const html=compiled.variants[variant].html;
  assert.match(html,/data-riwayat-detail-native/);
  assert.doesNotMatch(html,/data-editor-perintah|data-kemas-ulang|data-rhs-actor|<form\b|\sname=/);
 }
 assert.equal(Object.keys(compiled.scripts).length,4);
 for(const script of Object.values(compiled.scripts))assert.doesNotMatch(script,/PadiRiwayat(?:Giling|Sosoh)Desain|PADI_RIWAYAT_(?:GILING|SOSOH)_DRAF/);
});
