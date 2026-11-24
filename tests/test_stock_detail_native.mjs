/* Pure identity/catalog/visible-link protocol, not browser/permission proof. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ui=require('../app/web/static/kerangka-stock-detail-ui-runtime.js');
const origin='https://fixture.invalid',source='/stok?tab=bahan',ctx='ctx',cap='cap',token='session';
const url='/stok/pk/detail?gudang=g2&id=42&jasa=0';
const meta=()=>({variant:'pk-g2-karung',mutu:true,jasa:false,beras:false,qc_latest:null,stages:[],incoming:'',stock:''});
const data={sumber:'a'.repeat(64)};
function catalog(){return {versi:1,sumber:data.sumber,cap,konteks:ctx,sesi:token,asal:source,asal_sha256:'b'.repeat(64),entries:[{alamat:url,metadata:meta(),chrome:{title:'Detail PK',back:'/stok',chain:{items:[{nama:'Beranda',alamat:'/'},{nama:'Stok',alamat:'/stok'},{nama:'Detail PK',alamat:null}],kembali:'/stok'}}}]};}
test('finite native GET only, action/source/karung stays native',()=>{
 for(const value of [url,'/stok/pk/detail?gudang=g1&kode=LOT','/stok-produk/detail?jenis=spek_fixture','/stok-produk-jasa/detail?jenis=hs_fixture&pelanggan_id=12','/gudang/g1'])assert(ui.address(value,origin),value);
 for(const value of ['/stok/sumber/barang/1','/stok/karung/detail?material=x&ukuran=50','/stok/pk/detail?gudang=g2&id=42&buka=pindah_tumpukan_silo','/stok-produk/detail?jenis=x&sumber_stok=curah','/gudang/g3','/gudang/g1?buka=aksi','/stok-produk-jasa/detail?jenis=x','/stok-produk/detail?jenis=x&pelanggan_id=1','/stok-produk/detail?jenis=x&jenis=y','//outside.invalid/gudang/g1'])assert.equal(ui.address(value,origin),null,value);
});
test('private source/CAP/context/session/source digest required',()=>{
 assert(ui.validCatalog(catalog(),data,source,ctx,cap,token));
 for(const mutate of [c=>c.cap='old',c=>c.konteks='other',c=>c.sesi='old',c=>c.sumber='wrong',c=>c.asal='/other',c=>c.asal_sha256='wrong',c=>c.entries=[],c=>c.entries.push(c.entries[0]),c=>c.entries[0].metadata.kg=0,c=>c.entries[0].metadata.warehouse_id=1,c=>c.entries[0].metadata.mutu=1]){
  const c=catalog();mutate(c);assert.equal(ui.validCatalog(c,data,source,ctx,cap,token),false);
 }
});
test('native Stock hierarchy metadata cannot introduce external destinations',()=>{
 const c=catalog().entries[0].chrome;assert(ui.validChrome(c,origin));
 for(const mutate of [x=>x.back='javascript:alert(1)',x=>x.chain.items[1].alamat='//outside.invalid/',x=>x.chain.kembali='/wrong',x=>x.chain.items[2].alamat='/unexpected']){const copy=structuredClone(c);mutate(copy);assert.equal(ui.validChrome(copy,origin),false);}
});
test('visible original native link required beyond catalog, max bounded',()=>{
 const link={getAttribute:k=>k==='href'?url:null,closest:()=>null,hasAttribute:()=>false};
 const doc={querySelectorAll:()=>[link]};assert(ui.visible(doc,url,()=>true));
 assert.equal(ui.visible(doc,url,()=>false),false);
 assert.equal(ui.visible({querySelectorAll:()=>[]},url,()=>true),false);
 assert.equal(ui.visible({querySelectorAll:()=>Array(101).fill(link)},url,()=>true),false);
 link.closest=()=>({});assert.equal(ui.visible(doc,url,()=>true),false);
});
