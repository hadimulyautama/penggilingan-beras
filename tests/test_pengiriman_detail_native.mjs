import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),reader=require('../app/web/static/pengiriman-detail-native.js'),ui=require('../app/web/static/kerangka-pengiriman-detail-ui-runtime.js');
const ORIGIN='https://fixture.invalid',digest='a'.repeat(64);
const metadata=()=>({id:17,kode:'SYNTHETIC-OUT',status:'perintah',keadaan:'Menunggu dimuat',jasa:false,cepat:false,bersama:false,tiket:false,boleh_perintah:false,boleh_muat:true,actions:[{label:'Catat muatan',bagian:'ringkasan'}]});
const packageData=()=>({versi:1,sumber:digest,variants:{read:{html:'structure'},command:{html:'structure'}},styles:{},scripts:{}});
const catalog=()=>({versi:1,cap:'cap',konteks:'context',sesi:'session',sumber:digest,source_address:'/barang-keluar?status=perintah',sumber_sha256:digest,mode:'list',entries:[{meta:metadata(),targets:['/barang-keluar/17?q=synthetic']} ]});

test('four known tabs and bounded native filters only',()=>{
 for(const tab of ['ringkasan','barang','tiket','riwayat']){
  const target='/barang-keluar/17?tab_detail='+tab+'&q=a%20b&sejak=2026-11-24';
  assert.equal(reader.address(target,ORIGIN).tab,tab);assert.equal(reader.configuration(target,ORIGIN).address,target);
 }
 for(const target of ['/barang-keluar/0','/barang-keluar/017','/barang-keluar/2147483648','/barang-keluar/17?buka=',
 '/barang-keluar/17?nilai=17','/barang-keluar/17?tiket=2','/barang-keluar/17?rincian_perintah=1','/barang-keluar/17?tab_detail=',
 '/barang-keluar/17?tab_detail=barang&tab_detail=tiket','/barang-keluar/17?company_id=2','/barang-keluar/17?sejak=20261124',
 '/barang-keluar/17?sejak=2026-02-30','/barang-keluar/17?q=%FF','/barang-keluar/17?q=%GG','/barang-keluar/17?kembali=https://other.invalid',
 '/muatan?perintah=17','/barang-keluar/17/verifikasi','//other.invalid/barang-keluar/17'])assert.equal(reader.address(target,ORIGIN),null,target);
});

test('private native source CAP, session, context and strict variant metadata are mandatory',()=>{
 const p=catalog();assert(ui.valid(packageData(),p,'context','cap','session',digest,ORIGIN));
 for(const [key,value] of [['sesi','other'],['konteks','tenant-B'],['cap','old'],['sumber','b'.repeat(64)],['source_address','https://other.invalid/barang-keluar']])assert(!ui.valid(packageData(),{...p,[key]:value},'context','cap','session',digest,ORIGIN));
 assert(!ui.meta({...metadata(),status:'selesai'}));assert(!ui.meta({...metadata(),status:'batal'}));
 assert(!ui.meta({...metadata(),weight:50}));assert(!ui.meta({...metadata(),boleh_muat:1}));
 assert(!ui.valid(packageData(),{...p,entries:[...p.entries,...p.entries]},'context','cap','session',digest,ORIGIN));
});

test('pending tab reuse is bound to the original exact authorized resource/read scope',()=>{
 const p=catalog(),target='/barang-keluar/17?q=synthetic&tab_detail=barang',source='/barang-keluar/17?q=synthetic';
 const proof={kind:'pending',visible:true,href:target,code:'SYNTHETIC-OUT',id:17,url:source,digest,originTarget:p.entries[0].targets[0],stamp:ui.stamp('context',source,17,digest)};
 assert(ui.select(p,target,source,'context',proof,ORIGIN));
 for(const bad of [{...proof,visible:false},{...proof,id:18},{...proof,code:'other'},{...proof,stamp:'old'},{...proof,digest:'b'.repeat(64)},{...proof,originTarget:'/barang-keluar/18'}])assert.equal(ui.select(p,target,source,'context',bad,ORIGIN),null);
 const different='/barang-keluar/17?q=changed&tab_detail=barang';
 assert.equal(ui.select(p,different,source,'context',{...proof,href:different},ORIGIN),null);
 assert(!ui.sameReadScope(p.entries[0].targets[0],'/barang-keluar/18?q=synthetic',ORIGIN));
});

test('computed visibility and native exact href remain required',()=>{
 const node={isConnected:true,closest(){return null;},getClientRects(){return [1];}};
 assert(ui.shown(node,()=>({visibility:'visible'})));
 assert(!ui.shown({...node,isConnected:false},()=>({visibility:'visible'})));
 assert(!ui.shown({...node,closest(){return {}; }},()=>({visibility:'visible'})));
 assert(!ui.shown({...node,getClientRects(){return []; }},()=>({visibility:'visible'})));
 assert(!ui.shown(node,()=>({visibility:'hidden'})));
 const link={getAttribute(){return 'https://fixture.invalid/barang-keluar/17?tab_detail=barang#panel-barang';}};
 assert.equal(ui.normalize(link,'/barang-keluar/17',ORIGIN),'/barang-keluar/17?tab_detail=barang');
 assert.equal(ui.normalize({getAttribute(){return '//other.invalid/barang-keluar/17';}},'/barang-keluar/17',ORIGIN),null);
});

test('action and editor links explicitly keep the full native path after read installation',()=>{
 const links=['/barang-keluar/17?buka=ubah_item_perintah&nilai=17','/muatan?perintah=17','/selesai-muat?perintah=17',
 '/barang-keluar/17/verifikasi','/barang-keluar/17/perbaikan','/barang-keluar/17?tab_detail=barang'].map(href=>({attributes:{href},getAttribute(k){return this.attributes[k];},setAttribute(k,v){this.attributes[k]=v;}}));
 reader.holdActions({querySelectorAll(){return links;}},ORIGIN);
 assert(links.slice(0,5).every(link=>Object.hasOwn(link.attributes,'data-utuh')));
 assert(!Object.hasOwn(links[5].attributes,'data-utuh'));
});

test('public compiled browser allowlist is the same native read function, not a regex grant',()=>{
 let payload=fs.readFileSync(new URL('../app/web/static/kerangka-pengiriman-detail-ui.js',import.meta.url),'utf8');
 const hook='\n global.PadiKerangkaPengirimanDetailUI=Object.freeze';
 assert.equal(payload.split(hook).length,2);payload=payload.replace(hook,'\n global.__readForTest=address;'+hook);
 const sandbox={URL,URLSearchParams};sandbox.window=sandbox;vm.runInNewContext(payload,sandbox);
 for(const target of ['/barang-keluar/17','/barang-keluar/17?tab_detail=barang&q=a%20b','/barang-keluar/17?buka=x','/barang-keluar/17?tab_detail=','/barang-keluar/17?sejak=2026-02-30','/barang-keluar/18?company_id=2'])assert.equal(!!sandbox.__readForTest(target,ORIGIN),!!reader.address(target,ORIGIN));
});
