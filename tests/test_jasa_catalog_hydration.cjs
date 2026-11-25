'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {catalogFromRead}=require('../app/web/static/kerangka-jasa-detail-ui-runtime.js');
const ORIGIN='https://fixture.invalid',SOURCE='/jasa?status=berjalan';

function ordinaryRead(){
 const data={versi:1,sumber:'a'.repeat(64),styles:{},scripts:{},variants:Object.fromEntries(
  ['ringkasan','penerimaan','proses','stok','pengambilan'].map(tab=>[tab,{title:'__PADI_JASA_LABEL__ · Pesanan Jasa',html:'<section></section>',breadcrumb:'<nav></nav>'}]))};
 const payload={versi:1,mode:'list',cap:'fixture-release',konteks:'fixture-company-warehouse',sesi:'fixture-session',sumber:data.sumber,source_address:SOURCE,sumber_sha256:'b'.repeat(64),entries:[{id:17,label:'Pelanggan sintetis',filter:false,targets:['/jasa/pelanggan/17']}]};
 const attrs={type:'application/json',id:'padi-jasa-detail-catalog','data-cap':payload.cap,'data-konteks':payload.konteks,'data-source-address':SOURCE,'data-source-sha':payload.sumber_sha256};
 const host={tagName:'SCRIPT',attributes:Object.keys(attrs),getAttribute:k=>attrs[k],hasAttribute:k=>Object.hasOwn(attrs,k),dataset:{cap:payload.cap,konteks:payload.konteks,sourceAddress:SOURCE,sourceSha:payload.sumber_sha256},textContent:'',cloneNode(){return {cloned:true,textContent:this.textContent,dataset:{...this.dataset}};}};
 function document(fresh){
  const main={contains:n=>fresh&&n===host},session={dataset:{token:payload.sesi}},frame={dataset:{pindahAlamat:SOURCE,pindahKonteks:payload.konteks},contains:n=>n===main||n===session};
  const nodes={'.bingkai':[frame],'#isi-halaman':[main],'#formulir-sesi':[session],'#padi-jasa-detail-catalog':fresh?[host]:[]};
  return {nodes,documentElement:{dataset:{versi:payload.cap}},querySelector:s=>nodes[s]?.[0]||null,querySelectorAll:s=>nodes[s]||[],getElementById:id=>nodes['#'+id]?.[0]||null};
 }
 const live=document(false),fresh=document(true);
 return {data,payload,host,attrs,live,fresh,raw:null};
}
function read(r){r.host.textContent=r.raw===null?JSON.stringify(r.payload):r.raw;return catalogFromRead(r.data,r.fresh,r.live,SOURCE,ORIGIN);}

test('copies only the current native inert list catalog without mutating either document',()=>{
 const r=ordinaryRead(),before=JSON.stringify(r.payload),copy=read(r);
 assert.equal(copy.cloned,true);assert.notEqual(copy,r.host);
 assert.equal(copy.textContent,JSON.stringify(r.payload));assert.equal(JSON.stringify(r.payload),before);
 assert.equal(r.live.querySelectorAll('#padi-jasa-detail-catalog').length,0);
 assert.equal(r.fresh.querySelectorAll('#padi-jasa-detail-catalog')[0],r.host);
});

for(const [name,change] of Object.entries({
 'old session':r=>r.payload.sesi='previous-session',
 'other company or warehouse':r=>r.payload.konteks='another-context',
 'old release':r=>r.payload.cap='previous-release',
 'different filtered list':r=>r.payload.source_address='/jasa?status=selesai',
 'other compiled source':r=>r.payload.sumber='c'.repeat(64),
 'foreign source':r=>r.payload.source_address='https://other.invalid/jasa',
 'detail rather than list':r=>r.payload.mode='detail',
 'other wire version':r=>r.payload.versi=2,
 'host context differs':r=>r.host.dataset.konteks='another-context',
 'host release differs':r=>r.host.dataset.cap='previous-release',
 'host source differs':r=>r.host.dataset.sourceAddress='/jasa',
 'host digest differs':r=>r.host.dataset.sourceSha='c'.repeat(64),
 'malformed digest':r=>{r.payload.sumber_sha256='not-a-hash';r.host.dataset.sourceSha='not-a-hash';},
 'fresh document context changed':r=>r.fresh.nodes['.bingkai'][0].dataset.pindahKonteks='another-context',
 'fresh document session changed':r=>r.fresh.nodes['#formulir-sesi'][0].dataset.token='another-session',
 'fresh document release changed':r=>r.fresh.documentElement.dataset.versi='previous-release',
 'fresh document address changed':r=>r.fresh.nodes['.bingkai'][0].dataset.pindahAlamat='/jasa?status=selesai',
 'live document address changed':r=>r.live.nodes['.bingkai'][0].dataset.pindahAlamat='/jasa?status=selesai',
 'no catalog':r=>r.fresh.nodes['#padi-jasa-detail-catalog']=[],
 'duplicate catalog':r=>r.fresh.nodes['#padi-jasa-detail-catalog'].push(r.host),
 'missing current session':r=>r.live.nodes['#formulir-sesi']=[],
 'catalog outside native main':r=>r.fresh.nodes['#isi-halaman'][0].contains=()=>false,
 'executable script':r=>r.attrs.type='application/javascript',
 'additional host attribute':r=>r.host.attributes.push('onload'),
 'invalid JSON':r=>r.raw='{',
 'empty entries':r=>r.payload.entries=[],
 'duplicate customer':r=>r.payload.entries.push({...r.payload.entries[0]}),
 'action instead of read link':r=>r.payload.entries[0].targets=['/jasa/pelanggan/17?buka=tutup_jasa'],
 'different customer target':r=>r.payload.entries[0].targets=['/jasa/pelanggan/18'],
}))test('does not transfer catalog with '+name,()=>{
 const r=ordinaryRead();change(r);assert.equal(read(r),null);
});
