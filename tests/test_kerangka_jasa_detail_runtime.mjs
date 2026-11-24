/* Pure and DOM-protocol doubles only; no browser, app runtime or requests. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import vm from 'node:vm';
const api=createRequire(import.meta.url)('../app/web/static/kerangka-jasa-detail-ui-runtime.js');
const sandbox={window:{},module:{exports:{}},URL,TextEncoder,AbortController};
vm.runInNewContext(readFileSync(new URL('../app/web/static/kerangka-jasa-detail-ui.js',import.meta.url),'utf8'),sandbox);
const data=sandbox.window.PadiKerangkaJasaDetailData;
const ORIGIN='https://fixture.invalid',CTX='fixture-context',CAP='fixture-cap',TOKEN='fixture-session';
const SOURCE='/jasa?status=&cari=&halaman=1',TARGET='/jasa/pelanggan/17?status=&cari=&halaman=1';
const SHA=createHash('sha256').update(SOURCE).digest('hex');
const tabs=['ringkasan','penerimaan','proses','stok','pengambilan'];
function catalog(){return {versi:1,sumber:data.sumber,cap:CAP,konteks:CTX,sesi:TOKEN,source_address:SOURCE,sumber_sha256:SHA,mode:'list',entries:[{id:17,label:'Fixture A',filter:true,targets:[TARGET]}]};}
const valid=p=>api.valid(data,p,CTX,CAP,TOKEN,SHA,ORIGIN);
function pendingProof(current=TARGET){return {kind:'pending',visible:true,href:api.tabURL(api.address(current,ORIGIN),'stok'),label:'Fixture A',pid:17,url:current,originSha:SHA,originTarget:TARGET,stamp:api.pendingStamp(CTX,current,17,SHA)};}
test('public five-tab package and original private source bind without business values',()=>{
 assert.equal(valid(catalog()),true);assert.equal(Object.keys(data.variants).length,5);
 const p=catalog(),proof={kind:'list',visible:true,href:TARGET,label:'Fixture A'};
 assert.equal(api.selectProvenance(p,TARGET,SOURCE,CTX,proof,ORIGIN).entry.id,17);
 assert.equal(api.selectProvenance(p,TARGET,SOURCE,CTX,{...proof,visible:false},ORIGIN),null);
 assert.equal(api.selectProvenance(p,TARGET,SOURCE,CTX,{...proof,label:'stale label'},ORIGIN),null);
 assert.equal(api.selectProvenance(p,TARGET,'/jasa?halaman=2',CTX,proof,ORIGIN),null);
});
test('pending same-PID tabs retain original catalog source and SHA',()=>{
 const p=catalog();let current=TARGET;
 for(const key of tabs){const target=api.tabURL(api.address(current,ORIGIN),key),proof={...pendingProof(current),href:target};
  const selected=api.selectProvenance(p,target,current,CTX,proof,ORIGIN);assert.equal(selected.entry.id,17);assert.equal(selected.originTarget,TARGET);current=target;
 }
 assert.equal(p.source_address,SOURCE);assert.equal(p.sumber_sha256,SHA);assert.deepEqual(p.entries[0].targets,[TARGET]);
});
test('other PID, wrong stamp/source/root URL or absent original data is closed',()=>{
 const p=catalog(),proof=pendingProof(),target=proof.href;
 for(const delta of [{pid:18},{url:'/jasa/pelanggan/18'},{stamp:'stale'},{originSha:'b'.repeat(64)},{originTarget:'/jasa/pelanggan/17?tab=proses'}])assert.equal(api.selectProvenance(p,target,TARGET,CTX,{...proof,...delta},ORIGIN),null);
 assert.equal(api.selectProvenance(p,target,TARGET,'other-context',proof,ORIGIN),null);
 assert.equal(api.selectProvenance(undefined,target,TARGET,CTX,proof,ORIGIN),null);
 p.entries.push({id:18,label:'Fixture B',filter:false,targets:['/jasa/pelanggan/18']});
 assert.equal(api.selectProvenance(p,'/jasa/pelanggan/18?tab=stok',TARGET,CTX,{...proof,pid:18,label:'Fixture B',href:'/jasa/pelanggan/18?tab=stok',originTarget:'/jasa/pelanggan/18'},ORIGIN),null);
});
test('ctx/session/CAP/program source/host SHA and unknown filter metadata reject',()=>{
 for(const [key,value] of [['konteks','old'],['cap','old'],['sesi','old'],['sumber','b'.repeat(64)],['sumber_sha256','b'.repeat(64)]])assert.equal(valid({...catalog(),[key]:value}),false,key);
 const p=catalog();p.entries[0].filter=null;assert.equal(valid(p),false);
 assert.equal(api.valid(data,catalog(),CTX,CAP,TOKEN,'b'.repeat(64),ORIGIN),false);
 assert.equal(valid(null),false);
});
test('native detail provenance contains exactly five same-customer tab links',()=>{
 const p=catalog(),source='/jasa/pelanggan/17?tab=ringkasan';p.mode='detail';p.source_address=source;p.sumber_sha256=createHash('sha256').update(source).digest('hex');p.entries[0].targets=tabs.map(k=>'/jasa/pelanggan/17?tab='+k);
 assert.equal(api.valid(data,p,CTX,CAP,TOKEN,p.sumber_sha256,ORIGIN),true);
 p.entries[0].targets.pop();assert.equal(api.valid(data,p,CTX,CAP,TOKEN,p.sumber_sha256,ORIGIN),false);
});
function node(attrs={},extra={}){return {isConnected:true,getAttribute:k=>Object.hasOwn(attrs,k)?attrs[k]:null,hasAttribute:k=>Object.hasOwn(attrs,k),closest:()=>null,getClientRects:()=>[{}],...extra};}
function domFixture(){
 const target='/jasa/pelanggan/17?tab=stok',link=node({href:target}),heading={textContent:'Fixture A'};
 const root=node({}, {dataset:{url:TARGET,jdPid:'17',jdOriginSha:SHA,jdOriginTarget:TARGET,stamp:api.pendingStamp(CTX,TARGET,17,SHA)},querySelectorAll:()=>[link],querySelector:()=>heading});
 const doc={querySelectorAll:()=>[root],getElementById:()=>({contains:n=>n===root})};return {root,link,doc,target};
}
test('DOM-protocol proof needs connected visible current pending root and link',()=>{
 const f=domFixture(),style=()=>({visibility:'visible'});
 let proof=api.proofFromDOM(catalog(),f.target,TARGET,f.doc,style,ORIGIN);
 assert.equal(api.selectProvenance(catalog(),f.target,TARGET,CTX,proof,ORIGIN).entry.id,17);
 f.root.dataset.stamp='stale';proof=api.proofFromDOM(catalog(),f.target,TARGET,f.doc,style,ORIGIN);assert.equal(api.selectProvenance(catalog(),f.target,TARGET,CTX,proof,ORIGIN),null);
 f.root.isConnected=false;assert.equal(api.proofFromDOM(catalog(),f.target,TARGET,f.doc,style,ORIGIN),null);
 f.root.isConnected=true;f.link.getClientRects=()=>[];assert.equal(api.proofFromDOM(catalog(),f.target,TARGET,f.doc,style,ORIGIN),null);
 f.link.getClientRects=()=>[{}];assert.equal(api.proofFromDOM(catalog(),f.target,TARGET,f.doc,()=>({visibility:'hidden'}),ORIGIN),null);
 f.doc.getElementById=()=>({contains:()=>false});assert.equal(api.proofFromDOM(catalog(),f.target,TARGET,f.doc,style,ORIGIN),null);
});
test('focused order, actions, other routes and malformed links cannot be new targets',()=>{
 for(const target of ['/jasa/17','/jasa/17/nota','/jasa/pelanggan/17?pesanan_id=1','/jasa/pelanggan/17?buka=tutup_jasa&nilai=1','/jasa/pelanggan/17?tab=unknown','/jasa/pelanggan/17?tab=stok&tab=proses','/jasa/pelanggan/17?company_id=2','/pelanggan/jasa/pelanggan/17','//other.invalid/jasa/pelanggan/17'])assert.equal(api.address(target,ORIGIN),null,target);
});
test('portal or open native editor sources cannot adopt the public reader frame',()=>{
 const clean={body:{hasAttribute:()=>false,classList:{contains:()=>false}},querySelector:()=>null,getElementById:()=>null};
 assert.equal(api.blockedSource(clean),false);
 assert.equal(api.blockedSource(clean,'#pesanan-17'),true);
 assert.equal(api.blockedSource({...clean,querySelector:()=>({})}),true);
 assert.equal(api.blockedSource({...clean,getElementById:()=>({open:true,style:{}})}),true);
 assert.equal(api.blockedSource({...clean,getElementById:()=>({open:false,style:{display:'flex'}})}),true);
 assert.equal(api.blockedSource({...clean,body:{hasAttribute:()=>true}}),true);
});
test('native customer block title and parent query preserve name and original URL key order',()=>{
 assert.equal(api.nativeTitle('Fixture A'),'Fixture A · Pesanan Jasa');
 assert.equal(api.backURL(api.address('/jasa/pelanggan/17?tab=stok',ORIGIN)),'/jasa?');
 assert.equal(api.backURL(api.address('/jasa/pelanggan/17?halaman=3&cari=A%26B+%22x%22+*&status=berjalan&tab=stok',ORIGIN)),'/jasa?halaman=3&cari=A%26B+%22x%22+%2A&status=berjalan');
});
test('compiled native breadcrumb private name uses textContent and both native parent links use safe href',()=>{
 const writes=[],links=[1,2].map(()=>({getAttribute:()=>'/jasa?__PADI_BACK_QUERY__',setAttribute:(key,value)=>writes.push([key,value])}));
 const leaf={textContent:'__PADI_JASA_LABEL__ · Pesanan Jasa'};
 Object.defineProperty(leaf,'innerHTML',{set(){throw Error('Private label must not become HTML');}});
 const fragment={querySelectorAll:selector=>selector==='a[href]'?links:[leaf]},label='Nama <img src=x onerror=alert(1)> & "x"',back='/jasa?cari=A%26B';
 assert.equal(api.bindBreadcrumb(fragment,label,back),true);
 assert.equal(leaf.textContent,label+' · Pesanan Jasa');assert.deepEqual(writes,[['href',back],['href',back]]);
 leaf.textContent='other-source';assert.equal(api.bindBreadcrumb(fragment,label,back),false);
});
