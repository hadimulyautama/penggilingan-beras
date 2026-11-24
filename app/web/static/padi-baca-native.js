/* Explicit opt-in native HTML reader. URL equality is correlation, never authorization.
 * Server native guards remain authoritative; this module has no route discovery,
 * business IDs/roles, transaction policy, POST or persistence. */
(function (global) {
 'use strict';
 const HTML_LIMIT=8*1024*1024;
 function htmlWithinLimit(html){return typeof html==='string'&&html.length<=HTML_LIMIT&&new TextEncoder().encode(html).byteLength<=HTML_LIMIT;}
 function activatePrepared(items,ops){
  for(const item of items){
   if(!ops.current())return false;
   try{ops.activate(item);}catch(error){if(ops.current())ops.failed(error);return false;}
  }
  return true;
 }
 function sameOriginAddress(value,origin){
  if(typeof value!=='string'||typeof origin!=='string'||!value.startsWith('/')||value.startsWith('//'))return false;
  try{const url=new URL(value,origin);return url.origin===new URL(origin).origin&&!url.hash&&url.pathname+url.search===value;}catch(_){return false;}
 }
 function sameIdentity(a,b,address){
  return !!a&&!!b&&['cap','context','token','address'].every(k=>typeof a[k]==='string'&&a[k]&&a[k]===b[k])&&typeof address==='string'&&a.address===address;
 }
 function waitForInteraction(ops){
  if(ops.signal.aborted||!ops.current()||!ops.busy())return Promise.resolve();
  return new Promise(resolve=>{
   let settled=false,cleanup=()=>{};
   const finish=()=>{if(settled)return;settled=true;cleanup();ops.signal.removeEventListener('abort',finish);resolve();};
   const check=()=>{if(ops.signal.aborted||!ops.current()||!ops.busy())finish();};
   ops.signal.addEventListener('abort',finish,{once:true});
   cleanup=ops.subscribe(check);if(settled)cleanup();else check();
  });
 }
 function createReader(ops){
  if(!sameOriginAddress(ops.address,ops.origin))throw TypeError('Alamat GET native harus eksplisit dan satu origin.');
  let generation=0,controller=null,live=true;
  const current=n=>live&&n===generation&&ops.current();
  function stop(){live=false;++generation;if(controller)controller.abort();controller=null;}
  async function read(){
   if(!live||!ops.current())return;
   if(controller)controller.abort();const number=++generation,active=new AbortController();controller=active;
   ops.loading();const timeout=setTimeout(()=>active.abort(),20000);
   try{
    const response=await ops.fetch(active.signal);if(!current(number))return;
    const fresh=await ops.parse(response);if(!current(number))return;
    if(!sameIdentity(ops.identity,fresh.identity,ops.address))throw Error(ops.identityError||'Sesi atau cakupan halaman berubah. Muat ulang halaman untuk memeriksa akses.');
    const prepared=await ops.prepare(fresh,active.signal);if(!current(number))return;
    clearTimeout(timeout); // Optional UI interaction is not a network timeout.
    if(ops.beforeInstall)await ops.beforeInstall(active.signal);
    if(!current(number))return;
    ops.install(fresh,prepared);controller=null;live=false;++generation;
   }catch(error){if(current(number))ops.failed(error);}
   finally{clearTimeout(timeout);if(number===generation)controller=null;}
  }
  return {read,stop};
 }
 function mount(config){
 const ADDRESS=config.address;
 if(!sameOriginAddress(ADDRESS,location.origin)||!config.rootSelector||!config.statusSelector||!config.retrySelector
    ||config.contentAttribute&&!/^data-[a-z][a-z0-9-]*$/.test(config.contentAttribute))return null;
 const root=document.querySelector(config.rootSelector);
 if(!root||root.dataset.padiBacaNativeReady)return;root.dataset.padiBacaNativeReady='1';
 const main=document.getElementById('isi-halaman'),frame=document.querySelector('.bingkai');
 const session=()=>document.getElementById('formulir-sesi')?.dataset.token||'';
 const address=()=>location.pathname+location.search;
 const identity={cap:document.documentElement.dataset.versi||'',context:frame?.dataset.pindahKonteks||'',token:session(),address:frame?.dataset.pindahAlamat||''};
 const stamp=root.dataset.stamp;
 const status=root.querySelector(config.statusSelector),retry=root.querySelector(config.retrySelector);
 if(!main||!frame?.contains(main)||!main.contains(root)||!sameIdentity(identity,identity,ADDRESS)||address()!==ADDRESS||root.dataset.url!==ADDRESS||!stamp||!status||!retry)return;
 const lifecycle=new AbortController();
 function current(){return root.isConnected&&root.dataset.stamp===stamp&&address()===ADDRESS&&sameIdentity(identity,{cap:document.documentElement.dataset.versi||'',context:document.querySelector('.bingkai')?.dataset.pindahKonteks||'',token:session(),address:document.querySelector('.bingkai')?.dataset.pindahAlamat||''},ADDRESS);}
 function interaction(){
  const focus=document.activeElement;
  return !!main.querySelector('dialog[open]')||!!(focus&&main.contains(focus)&&focus.matches('select:not(:disabled),textarea:not(:disabled):not([readonly]),input:not(:disabled):not([readonly])'));
 }
 async function beforeInstall(signal){
  if(interaction()){
   root.dataset.padiBacaNativeState='waiting-interaction';
   status.textContent='Data sudah dibaca. Selesaikan pilihan atau tutup dialog untuk menampilkan data terbaru.';
  }
  await waitForInteraction({signal,current,busy:interaction,subscribe(check){
   const events=['close','cancel','focusout'];
   for(const name of events)main.addEventListener(name,check,true);
   const observer=new MutationObserver(check);observer.observe(main,{childList:true,subtree:true,attributes:true,attributeFilter:['open']});
   return ()=>{observer.disconnect();for(const name of events)main.removeEventListener(name,check,true);};
  }});
 }
 function markers(parent){
  const nodes=Array.from(parent.childNodes),starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))throw Error((config.messages?.structure||'Struktur halaman belum dapat dibaca. Coba lagi.'));
  return [starts[0],ends[0]];
 }
 async function parse(response){
  if(response.redirected||!response.ok||(response.headers.get('content-type')||'').split(';')[0].trim()!=='text/html')throw Error((config.messages?.response||'Data belum dapat dibaca. Muat ulang halaman bila sesi atau akses berubah.'));
  const html=await response.text();if(!htmlWithinLimit(html))throw Error('Dokumen terlalu besar untuk dibaca bertahap. Muat ulang halaman.');
  const doc=new DOMParser().parseFromString(html,'text/html');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelector('.halaman-memuat')||doc.querySelector(config.shellSelector||config.rootSelector))throw Error((config.messages?.native||'Halaman native belum tersedia. Coba lagi tanpa mengirim perubahan.'));
  const source=doc.getElementById('isi-halaman'),freshFrame=doc.querySelector('.bingkai'),freshSession=doc.getElementById('formulir-sesi');
  if(!freshFrame.contains(source)||!freshFrame.contains(freshSession))throw Error('Struktur sesi halaman tidak sesuai. Muat ulang halaman.');
  const [first,last]=markers(source),content=document.createElement('div');content.dataset.padiBacaNativeIsi='';if(config.contentAttribute)content.setAttribute(config.contentAttribute,'');
  for(let node=first.nextSibling;node&&node!==last;node=node.nextSibling)content.append(node.cloneNode(true));
  return {doc,content,identity:{cap:doc.documentElement.dataset.versi||'',context:freshFrame.dataset.pindahKonteks||'',token:doc.getElementById('formulir-sesi').dataset.token||'',address:freshFrame.dataset.pindahAlamat||''}};
 }
 async function prepare(fresh,signal){
  const prepared=[];
  for(const link of fresh.content.querySelectorAll('link[rel=stylesheet][href]')){
   const url=new URL(link.getAttribute('href'),location.href);
   if(url.origin!==location.origin||!url.pathname.startsWith('/static/')||url.searchParams.get('v')!==identity.cap)throw Error((config.messages?.styleVersion||'Versi gaya halaman berubah. Muat ulang halaman.'));
   const response=await fetch(url.pathname+url.search,{credentials:'same-origin',signal});
   if(!response.ok||response.redirected||!(response.headers.get('content-type')||'').startsWith('text/css'))throw Error((config.messages?.style||'Gaya halaman belum dapat dimuat. Coba lagi.'));
   prepared.push({node:link,type:'style',text:await response.text()});
  }
  for(const script of fresh.content.querySelectorAll('script')){
   const type=(script.getAttribute('type')||'').toLowerCase();if(type==='application/json')continue;
   if(type&&!['application/javascript','text/javascript'].includes(type))throw Error((config.messages?.scriptType||'Kontrol halaman belum dikenali. Muat ulang halaman.'));
   let text=script.textContent;
   if(script.hasAttribute('src')){
    const url=new URL(script.getAttribute('src'),location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/static/')||url.searchParams.get('v')!==identity.cap)throw Error((config.messages?.scriptVersion||'Versi kontrol halaman berubah. Muat ulang halaman.'));
    const response=await fetch(url.pathname+url.search,{credentials:'same-origin',signal});
    if(!response.ok||response.redirected||!['application/javascript','text/javascript'].includes((response.headers.get('content-type')||'').split(';')[0]))throw Error((config.messages?.script||'Kontrol halaman belum dapat dimuat. Coba lagi.'));
    text=await response.text();
   }
   prepared.push({node:script,type:'script',text});
  }
  return prepared;
 }
 const observer=new MutationObserver(()=>{if(!root.isConnected){reader.stop();observer.disconnect();lifecycle.abort();}});
 const reader=createReader({address:ADDRESS,origin:location.origin,identityError:config.messages?.identity,identity,current,fetch:signal=>fetch(ADDRESS,{method:'GET',credentials:'same-origin',cache:'no-store',signal,headers:{'X-Pindah':'1','X-Kerangka-Halaman':'0','Accept':'text/html'}}),parse,prepare,beforeInstall,
  loading(){retry.hidden=true;status.setAttribute('role','status');status.textContent=(config.messages?.loading||'Memuat data…');},
  failed(error){status.setAttribute('role','alert');status.textContent=error.name==='AbortError'?(config.messages?.timeout||'Pembacaan terlalu lama. Coba lagi hanya membaca data.'):error.message;retry.hidden=false;},
  install(fresh,prepared){
   if(!current())return;const [start,end]=markers(main),focus=document.activeElement,inside=main.contains(focus);
   // Seluruh GET aset sudah selesai. Tidak ada await setelah pemeriksaan akhir.
   observer.disconnect();lifecycle.abort();while(start.nextSibling&&start.nextSibling!==end)start.nextSibling.remove();end.before(fresh.content);document.title=fresh.doc.title||document.title;
   const installedCurrent=()=>fresh.content.isConnected&&address()===ADDRESS&&sameIdentity(identity,{cap:document.documentElement.dataset.versi||'',context:document.querySelector('.bingkai')?.dataset.pindahKonteks||'',token:session(),address:document.querySelector('.bingkai')?.dataset.pindahAlamat||''},ADDRESS);
   const actions=config.afterInstall?prepared.concat([{type:'after-install'}]):prepared;
   const activated=activatePrepared(actions,{current:installedCurrent,
    activate(item){
     let scriptError=false;const failedScript=()=>{scriptError=true;};
     const executable=item.type==='script'||item.type==='after-install';
     if(executable)window.addEventListener('error',failedScript);
     try{
      if(item.type==='after-install')config.afterInstall({content:fresh.content,doc:fresh.doc,previousRoot:root});
      else{
       const replacement=document.createElement(item.type==='style'?'style':'script');
       for(const attr of item.node.attributes)if(!['src','href','rel','defer','async'].includes(attr.name))replacement.setAttribute(attr.name,attr.value);
       replacement.textContent=item.text;item.node.replaceWith(replacement);
      }
      if(scriptError)throw Error('Kontrol halaman gagal disiapkan.');
     }finally{if(executable)window.removeEventListener('error',failedScript);}
    },
    failed(){
     // The old shell is already detached: report on the fresh content,
     // hold form controls, and offer one explicit native GET reload only.
     fresh.content.dataset.nativeReadState='failed';fresh.content.inert=true;
     for(const field of fresh.content.querySelectorAll('input,select,textarea,button'))field.disabled=true;
     const warning=document.createElement('section');warning.setAttribute('role','alert');
     const text=document.createElement('p');text.textContent='Kontrol halaman belum dapat disiapkan. Muat ulang halaman untuk membaca data terbaru; tidak ada pengiriman ulang otomatis.';
     const reload=document.createElement('a');reload.className='btn';reload.href=ADDRESS;reload.setAttribute('data-utuh','');reload.textContent='Muat ulang halaman';
     warning.append(text,reload);fresh.content.before(warning);
    }
   });
   if(!activated)return;
   if(installedCurrent()&&inside&&document.activeElement===document.body)config.restoreFocus?.({focus,retry,content:fresh.content});
  }
 });
 observer.observe(document.body,{childList:true,subtree:true});
 retry.addEventListener('click',()=>reader.read());
 window.addEventListener('pagehide',()=>{reader.stop();observer.disconnect();lifecycle.abort();},{once:true,signal:lifecycle.signal});
 reader.read();return reader;
 }
 const api={sameOriginAddress,sameIdentity,createReader,mount,htmlWithinLimit,activatePrepared,waitForInteraction};
 if(typeof module==='object'&&module.exports){module.exports=api;return;}
 global.PADI_BACA_NATIVE=api;
})(typeof window==='undefined'?globalThis:window);
