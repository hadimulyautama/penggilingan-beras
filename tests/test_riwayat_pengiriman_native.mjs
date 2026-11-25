import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const reader=require('../app/web/static/riwayat-pengiriman-native.js');
const ui=require('../app/web/static/kerangka-riwayat-pengiriman-ui-runtime.js');
const O='https://unit.invalid',target='/barang-keluar/17?status=selesai';
const m={id:17,kode:'UNIT',status:'selesai',title:'UNIT PLATE',bersama:false,tiket:false,review:false};
const nav={body_back:'/barang-keluar?status=selesai#judul-riwayat-keluar',header_back:null,chrome_back:'/barang-keluar?status=selesai'};
const data={versi:1,sumber:'a'.repeat(64),variants:Object.fromEntries(['read','review'].map(k=>[k,{html:'unit',breadcrumb:'unit',header_menu:'unit',header_back:'unit'}])),styles:{},scripts:{}};
const p={versi:1,cap:'cap',konteks:'ctx',sesi:'token',sumber:data.sumber,source_address:'/barang-keluar',sumber_sha256:'b'.repeat(64),entries:[{meta:m,target,nav}]};

test('only exact final-journey read addresses; action/rincian/document queries decline',()=>{
 assert.equal(reader.address(target,O).id,17);
 for(const value of ['/barang-keluar/0','/barang-keluar/17?tab_detail=barang','/barang-keluar/17?rincian_perintah=1','/barang-keluar/17?buka=','/barang-keluar/17/retur','/barang-keluar/17/serah-terima','/barang-keluar/17?q=a&q=b','/barang-keluar/17?sejak=2026-02-30','/barang-keluar/17?sejak=0000-01-01','/barang-keluar/17?pelanggan_id=0','//elsewhere.invalid/17'])assert.equal(reader.address(value,O),null,value);
 assert.ok(reader.configuration(target,O));
});
test('final metadata and native back contract do not admit active/action or broad navigation',()=>{
 assert.ok(ui.meta(m));assert.ok(ui.navigation(nav,O));
 for(const change of [{status:'dimuat'},{id:true},{title:''},{review:1},{permission:true}])assert.equal(ui.meta({...m,...change}),false);
 for(const change of [{body_back:'/retur'},{chrome_back:'/retur'},{header_back:'/barang-keluar'},{body_back:'//elsewhere.invalid/'}])assert.equal(ui.navigation({...nav,...change},O),false);
});
test('package matches exact current CAP/context/session/source and bounded native entries',()=>{
 assert.ok(ui.valid(data,p,'ctx','cap','token',p.sumber_sha256,O));
 for(const [ctx,cap,token,sha]of[['old','cap','token',p.sumber_sha256],['ctx','old','token',p.sumber_sha256],['ctx','cap','old',p.sumber_sha256],['ctx','cap','token','c'.repeat(64)]])assert.equal(ui.valid(data,p,ctx,cap,token,sha,O),false);
 assert.equal(ui.valid(data,{...p,entries:[...p.entries,...p.entries]},'ctx','cap','token',p.sumber_sha256,O),false);
 assert.equal(ui.valid(data,{...p,entries:[{...p.entries[0],target:'/barang-keluar/18'}]},'ctx','cap','token',p.sumber_sha256,O),false);
});
test('selection needs exact current parent source and visible original code/link',()=>{
 assert.equal(ui.select(p,target,p.source_address,{visible:true,href:target,code:'UNIT'}),p.entries[0]);
 for(const proof of [null,{visible:false,href:target,code:'UNIT'},{visible:true,href:target,code:'OTHER'},{visible:true,href:'/barang-keluar/18',code:'UNIT'}])assert.equal(ui.select(p,target,p.source_address,proof),null);
 assert.equal(ui.select(p,target,'/barang-keluar?status=batal',{visible:true,href:target,code:'UNIT'}),null);
});
test('computed-hidden/inert rows and cross-origin hrefs cannot prove a target',()=>{
 assert.equal(ui.shown({isConnected:true,closest:()=>({}),getClientRects:()=>[1]},()=>({visibility:'visible'})),false);
 assert.equal(ui.normalize({getAttribute:()=>target},p.source_address,O),target);
 assert.equal(ui.normalize({getAttribute:()=>O+target+'#other'},p.source_address,O),null);
 assert.equal(ui.normalize({getAttribute:()=>`https://elsewhere.invalid${target}`},p.source_address,O),null);
});
test('held deeper workflows get full native read, never a synthetic submit',()=>{
 const urls=['/barang-keluar/17?rincian_perintah=1','/barang-keluar/17/serah-terima','/barang-keluar/17/retur','/barang-keluar/17/koreksi-selesai','/audit?cari=UNIT','/barang-keluar?status=selesai#judul-riwayat-keluar'];
 const links=urls.map(href=>({getAttribute:()=>href,setAttribute(key,value){this[key]=value;}}));
 reader.holdActions({querySelectorAll:()=>links},O);
 for(const a of links.slice(0,-1))assert.equal(a['data-utuh'],'');
 assert.equal(links.at(-1)['data-utuh'],undefined);
});
