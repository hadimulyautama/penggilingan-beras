import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const ui=require('../app/web/static/kerangka-retur-baca-ui-runtime.js');
const ORIGIN='https://fixture.invalid',SOURCE='/retur',CTX='fixture-context',CAP='fixture-cap',TOKEN='fixture-token',SHA='a'.repeat(64),DIGEST='b'.repeat(64);
const component={html:'<div></div>',title:'shape',breadcrumb:'<nav></nav>',header_menu:'<button></button>'};
function data(){return {versi:1,sumber:SHA,variants:{list:component,receipt:component,ticket:component},styles:{},scripts:{}};}
function flags(){return {versi:1,sumber:SHA,cap:CAP,konteks:CTX,sesi:TOKEN,targets:['/retur']};}
function catalog(){return {versi:1,sumber:SHA,cap:CAP,konteks:CTX,sesi:TOKEN,source_address:SOURCE,sumber_sha256:DIGEST,entries:[{kind:'receipt',id:7,code:'R-FIXTURE',target:'/retur/7'}]};}
function link({href='/retur/7',text='R-FIXTURE',hidden=false,target=false,download=false,disabled=false,rects=true,code='RTP-FIXTURE'}={}){
 return {textContent:text,isConnected:true,getAttribute(k){return k==='href'?href:k==='aria-disabled'&&disabled?'true':null;},hasAttribute(k){return k==='target'&&target||k==='download'&&download;},closest(selector){return selector==='section'?{querySelector(){return {textContent:code};}}:hidden?{}:null;},getClientRects(){return rects?[{}]:[];}};
}
function style(){return {visibility:'visible'};}
const positives=[['/retur',{kind:'list',id:null,tab:null}],['/retur?sebelum=50&sebelum_pengajuan=41',{kind:'list',id:null,tab:null}],['/retur/1',{kind:'receipt',id:1,tab:'ringkasan'}],['/retur/9?tab_detail=barang',{kind:'receipt',id:9,tab:'barang'}],['/retur/tiket/7',{kind:'ticket',id:7,tab:null}]];
for(const [value,expected] of positives)test('native read address '+value,()=>assert.deepEqual(ui.address(value,ORIGIN),expected));
const negatives=['/retur?','/retur/0','/retur/01','/retur/2147483648','/retur?sebelum=0','/retur?sebelum=01','/retur?sebelum=1&sebelum=2','/retur?company_id=1','/retur?pesan=ok','/retur?tiket=3','/retur/1?tab_detail=bad','/retur/1?kembali_kerja=%2Fpekerjaan','/retur/1?tab_detail=barang&tab_detail=tiket','/retur/1#panel-tiket','/retur/tiket/1?tab_detail=tiket','/retur/pengajuan/1','/barang-keluar/1/retur','/retur-supplier/1','/pelanggan/retur','//other/retur','https://other/retur','/retur\\x','/retur\n'];
for(const value of negatives)test('decline nonadopted target '+JSON.stringify(value),()=>assert.equal(ui.address(value,ORIGIN),null));
test('private flags exact program CAP scope opening nonce and targets',()=>{
 assert.ok(ui.validFlags(data(),flags(),CTX,CAP,TOKEN));
 for(const patch of [{cap:'old'}, {konteks:'other'},{sesi:'old'},{sumber:'c'.repeat(64)},{targets:['/retur','/retur/pengajuan/9']},{targets:['/retur-supplier']},{allowed:true}])assert.equal(ui.validFlags(data(),{...flags(),...patch},CTX,CAP,TOKEN),false);
 assert.equal(ui.validFlags(data(),flags(),CTX,CAP,'other'),false);
 assert.equal(ui.validFlags({...data(),variants:{list:component}},flags(),CTX,CAP,TOKEN),false);
});
test('catalog exact source and one native record reference, no broad ID fallback',()=>{
 assert.ok(ui.validCatalog(data(),catalog(),SOURCE,CTX,CAP,TOKEN,DIGEST,ORIGIN));
 for(const patch of [{cap:'old'},{konteks:'other'},{sesi:'old'},{sumber:'c'.repeat(64)},{source_address:'/retur?sebelum=5'},{sumber_sha256:'c'.repeat(64)},{entries:[]},{entries:[...catalog().entries,...catalog().entries]},{extra:true}])assert.equal(ui.validCatalog(data(),{...catalog(),...patch},SOURCE,CTX,CAP,TOKEN,DIGEST,ORIGIN),false);
 for(const patch of [{kind:'list'},{id:8},{target:'/retur/8'},{target:'/retur/pengajuan/7'},{target:'https://other/retur/7'},{target:'/retur/7#panel-tiket'},{code:''},{code:'x'.repeat(201)},{actor:7}])assert.equal(ui.validCatalog(data(),{...catalog(),entries:[{...catalog().entries[0],...patch}]},SOURCE,CTX,CAP,TOKEN,DIGEST,ORIGIN),false);
 assert.equal(ui.validCatalog(null,catalog(),SOURCE,CTX,CAP,TOKEN,DIGEST,ORIGIN),false);
});
test('selection requires still-visible exact native receipt label and source',()=>{
 const doc=a=>({querySelectorAll(selector){assert.equal(selector,'#isi-halaman [data-retur-receipts] td[data-sel="utama"] > a.tabel-standar__kode[href]');return [a];}});
 assert.equal(ui.select(catalog(),'/retur/7',SOURCE,doc(link()),style,ORIGIN).code,'R-FIXTURE');
 assert.equal(ui.select(catalog(),'/retur/8',SOURCE,doc(link()),style,ORIGIN),null);
 assert.equal(ui.select(catalog(),'/retur/7','/retur?sebelum=8',doc(link()),style,ORIGIN),null);
 for(const patch of [{text:'different'},{href:'/retur/8'},{href:'https://other/retur/7'},{hidden:true},{target:true},{download:true},{disabled:true},{rects:false}])assert.equal(ui.select(catalog(),'/retur/7',SOURCE,doc(link(patch)),style,ORIGIN),null);
 assert.equal(ui.select(catalog(),'/retur/7',SOURCE,doc(link()),()=>({visibility:'hidden'}),ORIGIN),null);
});
test('ticket selection uses actual application panel link, never guessed receipt ID',()=>{
 const p={...catalog(),source_address:'/retur/pengajuan/8',entries:[{kind:'ticket',id:17,code:'RTP-FIXTURE',target:'/retur/tiket/17'}]};
 const doc={querySelectorAll(selector){assert.equal(selector,'#isi-halaman #panel-tiket a[href]');return [link({href:'/retur/tiket/17',text:'Lihat tiket RTP terkait'})];}};
 assert.equal(ui.select(p,'/retur/tiket/17',p.source_address,doc,style,ORIGIN).code,'RTP-FIXTURE');
 assert.equal(ui.select(p,'/retur/tiket/7',p.source_address,doc,style,ORIGIN),null);
});
test('ordinary visible list links still require genuine current DOM link',()=>{
 assert.ok(ui.visibleLink({querySelectorAll(){return [link({href:'/retur',text:'Barang Retur'})];}},'/retur','/barang-keluar',ORIGIN,style));
 assert.equal(ui.visibleLink({querySelectorAll(){return [];}},'/retur','/barang-keluar',ORIGIN,style),null);
 assert.equal(ui.visibleLink({querySelectorAll(){return [link({href:'/retur',hidden:true})];}},'/retur','/barang-keluar',ORIGIN,style),null);
});
