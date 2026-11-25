import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const require=createRequire(import.meta.url);
const {references,valid,frameBound}=require('../app/web/static/kerangka-beranda-ui-runtime.js');
const data={versi:1,sumber:'a'.repeat(64),variants:{'/':{title:'Beranda',brand:'PT Hadi Mulya Utama',html:'<section></section>',breadcrumb:''}},scripts:{}};
const refs={sapaan:'Selamat pagi, Contoh',tanggal:'24 November 2026',scope:'Semua gudang',semua_gudang:true};
const privateData={versi:1,sumber:data.sumber,cap:'cap',konteks:'ctx',sesi:'session',references:refs};
let cases=0;function test(name,run){run();console.log('PASS '+name);cases++;}
test('known scope presentation and no inferred IDs',()=>{assert(references(refs));assert(!references({...refs,warehouse_id:1}));assert(!references({...refs,semua_gudang:false}));assert(!references({...refs,scope:'Other'}));});
test('specific warehouse labels must carry non-all scope',()=>{for(const scope of ['Gudang 1 · Selepan','Gudang 2 · Penyosohan','Belum punya gudang'])assert(references({...refs,scope,semua_gudang:false}));});
test('current private source cap context and session all required',()=>{assert(valid(data,privateData,'ctx','cap','session'));for(const key of ['sumber','cap','konteks','sesi'])assert(!valid(data,{...privateData,[key]:'other'},'ctx','cap','session'));});
test('no client-made role row or identity fields',()=>{assert(!valid(data,{...privateData,role:'admin'},'ctx','cap','session'));assert(!valid(data,{...privateData,references:{...refs,device_cards:[]}},'ctx','cap','session'));});
test('public package only exact Home with native brand',()=>{assert(!valid({...data,variants:{...data.variants,'/beranda':data.variants['/']}},privateData,'ctx','cap','session'));assert(!valid({...data,variants:{'/':{...data.variants['/'],brand:'Beranda'}}},privateData,'ctx','cap','session'));});
function doc(){const main={},session={dataset:{token:'session'}},frame={dataset:{pindahKonteks:'ctx',pindahAlamat:'/barang-masuk'},contains:n=>n===main||n===session};return {frame,main,session,documentElement:{dataset:{versi:'cap'}},querySelector:s=>s==='.bingkai'?frame:null,getElementById:s=>s==='isi-halaman'?main:s==='formulir-sesi'?session:null,querySelectorAll:s=>s==='.bingkai'?[frame]:s==='#isi-halaman'?[main]:s==='#formulir-sesi'?[session]:[]};}
test('prototype tied to Root identity and exact address',()=>{const d=doc();assert(frameBound(d,'ctx','cap','session','/barang-masuk'));assert(!frameBound(d,'other','cap','session','/barang-masuk'));assert(!frameBound(d,'ctx','cap','session','/stok'));d.frame.contains=()=>false;assert(!frameBound(d,'ctx','cap','session','/barang-masuk'));});
test('duplicate native frame is rejected',()=>{const d=doc(),old=d.querySelectorAll;d.querySelectorAll=s=>s==='.bingkai'?[d.frame,d.frame]:old(s);assert(!frameBound(d,'ctx','cap','session'));});
test('aliases and action queries decline before parsing any document',()=>{const code=readFileSync(new URL('../app/web/static/kerangka-beranda-ui-runtime.js',import.meta.url),'utf8');const context={window:{PadiKerangkaBerandaData:data},document:new Proxy({},{get(){throw Error('Must decline before document access');}})};vm.runInNewContext(code,context);for(const target of ['/beranda','/dashboard','/?buka=packing','/?pesan=ok'])assert.equal(context.window.PadiKerangkaBerandaUI.buat(target,'base','ctx','cap','session'),null);});
console.log(`${cases} pure Node contracts passed; no browser or runtime claim.`);
