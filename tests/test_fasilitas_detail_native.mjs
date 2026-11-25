/* Pure protocol negatives, not browser or real authorization evidence. */
import test from 'node:test';import assert from 'node:assert/strict';import {createRequire} from 'node:module';import {readFileSync} from 'node:fs';import {createHash} from 'node:crypto';import vm from 'node:vm';
const require=createRequire(import.meta.url),api=require('../app/web/static/kerangka-fasilitas-detail-ui-runtime.js'),adapter=require('../app/web/static/fasilitas-detail-native.js');
const sandbox={window:{},module:{exports:{}},URL};vm.runInNewContext(readFileSync(new URL('../app/web/static/kerangka-fasilitas-detail-ui.js',import.meta.url),'utf8'),sandbox);
const data=sandbox.window.PadiKerangkaFasilitasDetailData,PARENT='/pengaturan/mesin',TARGET=PARENT+'/17',p={versi:1,cap:'cap',konteks:'ctx',sesi:'fixture-token',sumber:data.sumber,source_address:PARENT,sumber_sha256:createHash('sha256').update(PARENT).digest('hex'),entries:[{id:17,label:'Native <name>',variant:'dryer',target:TARGET}]};
test('bare line descriptor is correlation only, other IDs still need a catalog entry',()=>{
 assert.equal(api.address(TARGET).id,17);assert.equal(adapter.configuration(TARGET,'https://fixture.invalid').address,TARGET);
 for(const value of ['/pengaturan/mesin/017',PARENT+'/0',PARENT+'/2147483648','/pengaturan/dryer/17',TARGET+'?tersimpan=1',TARGET+'#edit','https://other.invalid'+TARGET]){assert.equal(api.address(value),null);assert.equal(adapter.configuration(value,'https://fixture.invalid'),null);}
});
test('private catalog exact source/program/context/CAP/session/variant and bounded native rows',()=>{
 const valid=x=>api.valid(data,x,p.konteks,p.cap,p.sesi);assert.equal(valid(p),true);assert.equal(data.parent_sha,p.sumber_sha256);
 for(const key of ['cap','konteks','sesi','sumber','source_address','sumber_sha256'])assert.equal(valid({...p,[key]:'old'}),false);
 assert.equal(valid({...p,entries:[]}),false);assert.equal(valid({...p,entries:[p.entries[0],p.entries[0]]}),false);
 for(const delta of [{id:18},{variant:'guess'},{target:'/pengaturan/dryer/17'},{id:true},{label:null}])assert.equal(valid({...p,entries:[{...p.entries[0],...delta}]}),false);
 assert.equal(valid({...p,company_id:1}),false);assert.equal(valid(null),false);
});
test('currently visible exact native link and actual caption are mandatory',()=>{
 const link={isConnected:true,getAttribute:k=>k==='href'?TARGET:null,hasAttribute:()=>false,closest:()=>null,getClientRects:()=>[{}],querySelector:()=>({textContent:p.entries[0].label})};
 const doc={querySelectorAll:()=>[link]},style=()=>({visibility:'visible'});
 assert.equal(api.visibleLink(doc,TARGET,p.entries[0],style),true);
 assert.equal(api.visibleLink(doc,TARGET,{...p.entries[0],label:'guessed'},style),false);
 link.getClientRects=()=>[];assert.equal(api.visibleLink(doc,TARGET,p.entries[0],style),false);link.getClientRects=()=>[{}];
 link.isConnected=false;assert.equal(api.visibleLink(doc,TARGET,p.entries[0],style),false);link.isConnected=true;
 assert.equal(api.visibleLink(doc,TARGET,p.entries[0],()=>({visibility:'hidden'})),false);
 doc.querySelectorAll=()=>[link,link];assert.equal(api.visibleLink(doc,TARGET,p.entries[0],style),false);
});
test('current parent frame and contained session must match before any parse/swap',()=>{
 const main={},session={dataset:{token:p.sesi}},frame={dataset:{pindahAlamat:PARENT,pindahKonteks:p.konteks},contains:n=>[main,session].includes(n)};
 const doc={documentElement:{dataset:{versi:p.cap}},querySelector:()=>frame,querySelectorAll:()=>[{}],getElementById:id=>id==='isi-halaman'?main:session};
 const valid=()=>api.frameBound(doc,p.konteks,p.cap,p.sesi,PARENT);assert.equal(valid(),true);frame.contains=()=>false;assert.equal(valid(),false);frame.contains=n=>[main,session].includes(n);frame.dataset.pindahAlamat=TARGET;assert.equal(valid(),false);
});
test('retry restores read focus and does not choose a configuration action',()=>{
 const config=adapter.configuration(TARGET,'https://fixture.invalid'),retry={},calls=[],content={focus:o=>calls.push(o),querySelectorAll:()=>[]};
 config.restoreFocus({focus:retry,retry,content});assert.equal(content.tabIndex,-1);assert.equal(calls.length,1);
 config.restoreFocus({focus:{closest:()=>null},retry,content});assert.equal(calls.length,1);
});
