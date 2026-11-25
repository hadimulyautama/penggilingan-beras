/* Execute exact native SDK functions: a read-only page cannot waive another editor. */
'use strict';
const assert=require('node:assert/strict'),test=require('node:test'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const SOURCE=fs.readFileSync(path.join(__dirname,'../hmu_tampilan/static/pindah.js'),'utf8');
const SELECTOR='[data-editor-perintah],[data-kemas-ulang]';
function functions(source=SOURCE){
 const extract=(name,next)=>source.slice(source.indexOf('  function '+name+'('),source.indexOf('  function '+next+'('));
 return extract('bolehDitangani','memakaiKerangkaHalaman')+extract('rencanaKerangkaLangsung','kunciBaca');
}
function sdk(marker,program=functions()){
 let calls=0;const queries=[];
 const context={document:{querySelector(selector){queries.push(selector);if(selector===SELECTOR)return marker;return {};},getElementById:()=>({dataset:{token:'fixture-token'}}),documentElement:{getAttribute:()=> 'fixture-cap'}},
  penyediaKerangkaLangsung:()=>{calls++;return null;},location:{origin:'https://fixture.invalid',href:'https://fixture.invalid/riwayat-giling/12'}};
 vm.runInNewContext(program,context);
 return {context,queries,providerCalls:()=>calls};
}
function link(){return {getAttribute:()=>'/barang-masuk',hasAttribute:()=>false,hash:'',pathname:'/barang-masuk',target:'',origin:'https://fixture.invalid'};}
function assertVeto(s){
 assert.equal(s.context.bolehDitangani(link()),false);
 assert.equal(s.context.rencanaKerangkaLangsung('/barang-masuk',true),null);
 assert.equal(s.providerCalls(),0);
 assert.ok(s.queries.includes(SELECTOR));
}

for(const kind of ['native Admin editor','another legacy editor outside readonly History','Kemas Ulang']){
 test(kind+' keeps global click/provider veto regardless of absent busy attributes',()=>{
  assertVeto(sdk({kind}));
 });
}

test('actual readonly page without any editor permits ordinary click and consults provider',()=>{
 const s=sdk(null);
 assert.equal(s.context.bolehDitangani(link()),true);
 assert.equal(s.context.rencanaKerangkaLangsung('/barang-masuk',true),null);
 assert.equal(s.providerCalls(),1);
});

test('negative control: removing the global selector veto is detected semantically',()=>{
 const weakened=functions().replaceAll('document.querySelector("'+SELECTOR+'")','false');
 assert.notEqual(weakened,functions());
 assert.throws(()=>assertVeto(sdk({kind:'native editor'},weakened)),{name:'AssertionError'});
});

test('native target/download/foreign/hash exclusions remain independent of editor veto',()=>{
 for(const patch of [{target:'_blank'},{hash:'#detail'},{pathname:'/laporan.pdf'},{origin:'https://other.invalid'},{hasAttribute:k=>k==='download'},{hasAttribute:k=>k==='data-utuh'}]){
  const s=sdk(null);
  assert.equal(s.context.bolehDitangani({...link(),...patch}),false);
 }
});
