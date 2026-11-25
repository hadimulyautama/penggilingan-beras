import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';import fs from 'node:fs';
for(const name of ['giling','sosoh']){
 const source=fs.readFileSync(new URL('../app/web/static/'+name+'-ringkas.js',import.meta.url),'utf8');
 const lines=source.split('\n'),initializers=lines.filter(line=>line.startsWith('let data='));
 assert.equal(initializers.length,1,name+': expected actual controller state declaration');
 const initializer=initializers[0],start=source.indexOf('let readBusy=false;'),end=source.indexOf('root.pfCorrection=');
 assert.ok(start>=0&&end>start,name+': actual refresh section must exist');
 const code=source.slice(start,end);
 // The previous VM extracted the read function but omitted Sosoh's existing
 // syncPending dependency. Evaluate its actual native declaration in the same
 // closure; accessors change real lexical state, never a constant-false stub.
 const variables=['data','drafts','forms','action','review','busy','stale','uncertain','leaving','last','options','reasons','syncPending']
  .filter(key=>new RegExp('(?:^let |,)'+key+'=').test(initializer));
 const accessors=variables.map(key=>`${key}:{get(){return ${key};},set(value){${key}=value;}}`).join(',');
 function setup({nativeCall=false,sessionCurrent=true}={}){
  let resolve,reject;
  const state={fields:[{value:'lama'}]},session={periksa:()=>sessionCurrent};
  const root={isConnected:true,dispatchEvent(event){c.events.push(event.type);}};
  const c={
   root,dirty:()=>false,
   document:{activeElement:{tagName:'BODY'},getElementById(id){
    if(id===name+'-awal')return {textContent:JSON.stringify({old:true})};
    if(id==='formulir-sesi')return {dataset:{token:'fixture-session'}};
    throw Error('Unexpected fixture DOM lookup');
   }},
   call(url,payload){c.requests.push({url,payload});return new Promise((yes,no)=>{resolve=yes;reject=no;});},
   base:'uji',render(){c.renders++;},persist(){c.persists++;},
   Event:class{constructor(type){this.type=type;}},
   window:{KEADAAN_BACA:{ambil:()=>state},SESIFORM:session},SESIFORM:session,
   KEADAAN_BACA:{pulihkan(r,s){assert.equal(r,root);c.restored=s;}},
   requests:[],events:[],renders:0,persists:0,AbortController,setTimeout,clearTimeout,
   fetch(){c.requests.push({unexpectedNativeFetch:true});throw Error('No network in this VM');},
  };
  let dependencies='';
  if(nativeCall){
   const call=lines.filter(line=>line.startsWith('async function call(')),token=lines.filter(line=>line.startsWith('function token()'));
   assert.equal(call.length,1);assert.equal(token.length,1);dependencies=token[0]+'\n'+call[0];
  }
  vm.runInNewContext(`(function(){\n${initializer}\n${dependencies}\n${code}\nObject.defineProperties(globalThis,{${accessors}});\n})();`,c);
  return {c,root,state,
   resolve(value){assert.equal(typeof resolve,'function','Native read must have requested data');resolve(value);},
   reject(error){assert.equal(typeof reject,'function','Native read must have requested data');reject(error);},
  };
 }
 test(name+': baca baru memperbarui data tanpa menyalin input transaksi lama',async()=>{const s=setup();const p=s.root.pfReadRefresh();s.resolve({sumber:[],value:2});assert.equal(await p,true);assert.equal(s.c.data.value,2);assert.equal(s.c.renders,1);assert.equal(s.c.restored.fields.length,0);});
 for(const flag of ['busy','uncertain','action','review'])test(name+': '+flag+' menahan pembaruan',async()=>{const s=setup();s.c[flag]=true;assert.equal(await s.root.pfReadRefresh(),false);assert.equal(s.c.renders,0);});
 test(name+': draf dan editor koreksi tetap terlindungi',async()=>{const s=setup();s.c.dirty=()=>true;assert.equal(await s.root.pfReadRefresh(),false);s.c.dirty=()=>false;s.root.pfCorrectionActive=()=>true;assert.equal(await s.root.pfReadRefresh(),false);});
 test(name+': mengetik saat respons berjalan membatalkan pemasangan',async()=>{const s=setup();const p=s.root.pfReadRefresh();s.c.dirty=()=>true;s.resolve({sumber:[],value:2});assert.equal(await p,false);assert.equal(s.c.renders,0);assert.equal(s.c.data.old,true);});
 test(name+': baca bersamaan tidak menggandakan permintaan',async()=>{
  const s=setup(),p=s.root.pfReadRefresh();
  assert.equal(await s.root.pfReadRefresh(),false);assert.equal(s.c.requests.length,1);
  assert.equal(s.c.requests[0].payload,undefined);s.resolve({sumber:[],value:2});
  assert.equal(await p,true);assert.equal(s.c.renders,1);assert.equal(s.c.persists,1);assert.deepEqual(s.c.events,['pf:data-refresh']);
 });
 test(name+': respons tidak lengkap atau gagal tidak mengganti data dan dapat dibaca lagi',async()=>{
  const s=setup();let p=s.root.pfReadRefresh();s.resolve({value:2});
  assert.equal(await p,false);assert.equal(s.c.data.old,true);assert.equal(s.c.renders,0);
  p=s.root.pfReadRefresh();s.reject(Error('Synthetic read unavailable'));
  assert.equal(await p,false);assert.equal(s.c.data.old,true);assert.equal(s.c.persists,0);
  p=s.root.pfReadRefresh();s.resolve({sumber:[],value:3});
  assert.equal(await p,true);assert.equal(s.c.data.value,3);assert.equal(s.c.requests.length,3);
 });
 test(name+': uncertain saat baca mempertahankan kunci dan isian',async()=>{
  const s=setup(),p=s.root.pfReadRefresh(),last={key:'fixture-pending',payload:{hasil:75}};
  s.c.last=last;s.c.drafts={premium:'75'};s.c.uncertain=true;s.resolve({sumber:[],value:2});
  assert.equal(await p,false);assert.equal(s.c.last,last);assert.equal(s.c.drafts.premium,'75');
  assert.equal(s.c.uncertain,true);assert.equal(s.c.data.old,true);assert.equal(s.state.fields[0].value,'lama');
  assert.equal(s.c.renders,0);assert.equal(s.c.persists,0);
 });
 test(name+': root terlepas saat baca tidak dipasang kembali',async()=>{
  const s=setup(),p=s.root.pfReadRefresh();s.root.isConnected=false;s.resolve({sumber:[],value:2});
  assert.equal(await p,false);assert.equal(s.c.data.old,true);assert.equal(s.c.renders,0);
  assert.equal(await s.root.pfReadRefresh(),false);assert.equal(s.c.requests.length,1);
 });
 test(name+': call native menolak sesi formulir lama sebelum fetch',async()=>{
  const s=setup({nativeCall:true,sessionCurrent:false});s.c.last={key:'fixture-pending'};
  assert.equal(await s.root.pfReadRefresh(),false);assert.equal(s.c.requests.length,0);
  assert.equal(s.c.data.old,true);assert.equal(s.c.last.key,'fixture-pending');assert.equal(s.c.renders,0);assert.equal(s.c.persists,0);
 });
 if(name==='sosoh'){
  test('sosoh: syncPending native menahan baca sampai sinkronisasi selesai',async()=>{
   const s=setup();assert.equal(s.c.syncPending,false);s.c.syncPending=true;
   assert.equal(s.c.syncPending,true);const blocked=s.root.pfReadRefresh();
   assert.equal(s.c.requests.length,0);assert.equal(await blocked,false);
   s.c.syncPending=false;const p=s.root.pfReadRefresh();s.resolve({sumber:[],value:2});
   assert.equal(await p,true);assert.equal(s.c.data.value,2);assert.equal(s.c.requests.length,1);
  });
  test('sosoh: syncPending yang dimulai saat respons berjalan menahan data lama',async()=>{
   const s=setup(),p=s.root.pfReadRefresh();s.c.syncPending=true;s.resolve({sumber:[],value:2});
   assert.equal(s.c.syncPending,true);
   assert.equal(await p,false);assert.equal(s.c.data.old,true);assert.equal(s.c.renders,0);assert.equal(s.c.persists,0);
   s.c.syncPending=false;const retry=s.root.pfReadRefresh();s.resolve({sumber:[],value:3});
   assert.equal(await retry,true);assert.equal(s.c.data.value,3);assert.equal(s.c.requests.length,2);
  });
 }
}
