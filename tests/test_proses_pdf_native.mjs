import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const reader=require('../app/web/static/proses-pdf-native.js');
const ui=require('../app/web/static/kerangka-proses-pdf-ui-runtime.js');
const O='https://unit.invalid',target='/riwayat-giling/17/laporan';
const meta={kind:'giling',id:17,kode:'UNIT<&>',target};
const variant={html:'unit',breadcrumb:'unit',header:'unit',heading_parts:['Laporan giling · ',''],iframe_parts:['Laporan giling ','']};
const data={versi:1,sumber:'a'.repeat(64),variants:{giling:variant,sosoh:variant,pengeringan:variant},styles:{n1:'native',n2:'native'},scripts:{n:'native'},navigation:{styles:['n1','n2'],script:'n'}};
const p={versi:1,cap:'cap',konteks:'ctx',sesi:'token',sumber:data.sumber,source_address:'/riwayat-giling/17',sumber_sha256:'b'.repeat(64),entry:meta};
const identity={cap:'cap',context:'ctx',session:'token',address:target};

function deferred(){
 const writes=[];
 const frame={isConnected:true,dataset:{ppvSrc:target+'.pdf',ppvUrl:target},hasAttribute:()=>false,setAttribute(k,v){writes.push([k,v]);}};
 const content={isConnected:true,querySelectorAll:()=>[frame],contains:n=>n===frame};
 return {content,frame,writes,ops:{content,value:target,origin:O,identity,current:()=>({...identity})}};
}

test('only three exact query-free HTML viewer paths are admitted',()=>{
 for(const kind of ['giling','sosoh','pengeringan'])assert.equal(reader.address(`/riwayat-${kind}/17/laporan`,O).kind,kind);
 for(const value of ['/riwayat-transfer/17/laporan',target+'.pdf',target+'?unduh=1',target+'?buka=',target+'#frame','/riwayat-giling/0/laporan','/riwayat-giling/2147483648/laporan','//elsewhere.invalid/17'])assert.equal(reader.address(value,O),null,value);
 assert.equal(reader.address(target,O).detail,'/riwayat-giling/17');
});
test('iframe activates exactly once with original source, never another request policy',()=>{
 const f=deferred();assert.equal(reader.activateDeferred(f.ops),true);
 assert.deepEqual(f.writes,[['src',target+'.pdf']]);
 assert.equal(reader.activateDeferred(f.ops),false);
 assert.deepEqual(f.writes,[['src',target+'.pdf']]);
});
test('detached content/frame or existing source does not activate',()=>{
 for(const mutate of [f=>f.content.isConnected=false,f=>f.frame.isConnected=false,f=>f.content.contains=()=>false,f=>f.frame.hasAttribute=()=>true,f=>f.frame.dataset.ppvUrl='/riwayat-giling/18/laporan',f=>f.frame.dataset.ppvSrc='/riwayat-giling/18/laporan.pdf']){
  const f=deferred();mutate(f);assert.equal(reader.activateDeferred(f.ops),false);assert.equal(f.writes.length,0);
 }
});
test('navigation/context/session/CAP change before activation rejects stale source',()=>{
 for(const change of [{address:'/riwayat-giling/18/laporan'},{context:'other'},{session:'other'},{cap:'other'}]){
  const f=deferred();f.ops.current=()=>({...identity,...change});assert.equal(reader.activateDeferred(f.ops),false);assert.equal(f.writes.length,0);
 }
 const f=deferred();let calls=0;f.ops.current=()=>++calls===1?{...identity}:{...identity,address:'/riwayat-giling/18/laporan'};
 assert.equal(reader.activateDeferred(f.ops),false);assert.equal(f.writes.length,0);
});
test('metadata retains exact parent identity, never binary/action/other record targets',()=>{
 assert.ok(ui.meta(meta,O));assert.ok(ui.sourceState(p.source_address,O));
 for(const change of [{id:18},{kind:'sosoh'},{kode:''},{id:true},{target:target+'.pdf'},{allowed:true}])assert.equal(ui.meta({...meta,...change},O),false);
 for(const value of ['/riwayat-giling/17?buka=','/riwayat-giling/17?tab_detail=a&tab_detail=b','/riwayat-giling/17?halaman_jeda=0'])assert.equal(ui.sourceState(value,O),null);
});
test('private proof must match current source, package and identity exactly',()=>{
 assert.ok(ui.valid(data,p,'ctx','cap','token',p.sumber_sha256,O));
 for(const [ctx,cap,token,sha] of [['old','cap','token',p.sumber_sha256],['ctx','old','token',p.sumber_sha256],['ctx','cap','old',p.sumber_sha256],['ctx','cap','token','c'.repeat(64)]])assert.equal(ui.valid(data,p,ctx,cap,token,sha,O),false);
 assert.equal(ui.valid(data,{...p,source_address:'/riwayat-sosoh/17'},'ctx','cap','token',p.sumber_sha256,O),false);
 assert.equal(ui.valid(data,{...p,entry:{...meta,target:'/riwayat-giling/18/laporan'}},'ctx','cap','token',p.sumber_sha256,O),false);
});
test('actual visible native code/link and original source are required for selection',()=>{
 assert.equal(ui.select(p,target,p.source_address,{visible:true,href:target,code:meta.kode}),p.entry);
 for(const proof of [null,{visible:false,href:target,code:meta.kode},{visible:true,href:target,code:'other'},{visible:true,href:target+'.pdf',code:meta.kode}])assert.equal(ui.select(p,target,p.source_address,proof),null);
 assert.equal(ui.select(p,target,'/riwayat-giling/18',{visible:true,href:target,code:meta.kode}),null);
 assert.equal(ui.shown({isConnected:true,closest:()=>({}),getClientRects:()=>[1]},()=>({visibility:'visible'})),false);
});
test('read configuration has only explicit HTML GET mount and deferred iframe callback',()=>{
 const f=deferred(),config=reader.configuration(target,O,identity,f.ops.current);
 assert.equal(config.address,target);assert.equal(config.rootSelector,'[data-proses-pdf-kerangka]');
 config.afterInstall({content:f.content});config.afterInstall({content:f.content});
 assert.deepEqual(f.writes,[['src',target+'.pdf']]);
 assert.equal(reader.configuration(target+'.pdf',O,identity,f.ops.current),null);
});
