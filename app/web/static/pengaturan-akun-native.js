/* Khusus kerangka Akun: GET native, tanpa cache data, POST, atau policy draf. */
(function (global) {
 'use strict';
 const ADDRESS='/pengaturan/akun';
 function sameIdentity(a,b){
  return !!a&&!!b&&['cap','context','token','address'].every(k=>typeof a[k]==='string'&&a[k]&&a[k]===b[k])&&a.address===ADDRESS;
 }
 function createReader(ops){
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
    if(!sameIdentity(ops.identity,fresh.identity))throw Error('Sesi atau cakupan akun berubah. Muat ulang halaman untuk memeriksa akses.');
    const prepared=await ops.prepare(fresh,active.signal);if(!current(number))return;
    ops.install(fresh,prepared);controller=null;live=false;++generation;
   }catch(error){if(current(number))ops.failed(error);}
   finally{clearTimeout(timeout);if(number===generation)controller=null;}
  }
  return {read,stop};
 }
 if(typeof module==='object'&&module.exports){module.exports={sameIdentity,createReader};return;}
 global.PF_AKUN_NATIVE={sameIdentity,createReader};
 const root=document.querySelector('[data-pengaturan-akun-kerangka]');
 if(!root||root.dataset.akunNativeReady)return;root.dataset.akunNativeReady='1';
 const main=document.getElementById('isi-halaman'),frame=document.querySelector('.bingkai');
 const session=()=>document.getElementById('formulir-sesi')?.dataset.token||'';
 const address=()=>location.pathname+location.search;
 const identity={cap:document.documentElement.dataset.versi||'',context:frame?.dataset.pindahKonteks||'',token:session(),address:frame?.dataset.pindahAlamat||''};
 const stamp=root.dataset.stamp;
 const status=root.querySelector('[data-akun-native-status]'),retry=root.querySelector('[data-akun-native-retry]');
 if(!main||!sameIdentity(identity,identity)||address()!==ADDRESS||root.dataset.url!==ADDRESS||!stamp||!status||!retry)return;
 const lifecycle=new AbortController();
 function current(){return root.isConnected&&root.dataset.stamp===stamp&&address()===ADDRESS&&sameIdentity(identity,{cap:document.documentElement.dataset.versi||'',context:document.querySelector('.bingkai')?.dataset.pindahKonteks||'',token:session(),address:document.querySelector('.bingkai')?.dataset.pindahAlamat||''});}
 function markers(parent){
  const nodes=Array.from(parent.childNodes),starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))throw Error('Struktur akun belum dapat dibaca. Coba lagi.');
  return [starts[0],ends[0]];
 }
 async function parse(response){
  if(response.redirected||!response.ok||(response.headers.get('content-type')||'').split(';')[0].trim()!=='text/html')throw Error('Akun belum dapat dibaca. Muat ulang halaman bila sesi atau akses berubah.');
  const doc=new DOMParser().parseFromString(await response.text(),'text/html');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelector('[data-pengaturan-akun-kerangka]'))throw Error('Halaman akun native belum tersedia. Coba lagi tanpa mengirim perubahan.');
  const source=doc.getElementById('isi-halaman'),freshFrame=doc.querySelector('.bingkai');
  const [first,last]=markers(source),content=document.createElement('div');content.dataset.akunNativeIsi='';
  for(let node=first.nextSibling;node&&node!==last;node=node.nextSibling)content.append(node.cloneNode(true));
  return {doc,content,identity:{cap:doc.documentElement.dataset.versi||'',context:freshFrame.dataset.pindahKonteks||'',token:doc.getElementById('formulir-sesi').dataset.token||'',address:freshFrame.dataset.pindahAlamat||''}};
 }
 async function prepare(fresh,signal){
  const prepared=[];
  for(const link of fresh.content.querySelectorAll('link[rel=stylesheet][href]')){
   const url=new URL(link.getAttribute('href'),location.href);
   if(url.origin!==location.origin||!url.pathname.startsWith('/static/')||url.searchParams.get('v')!==identity.cap)throw Error('Versi gaya akun berubah. Muat ulang halaman.');
   const response=await fetch(url.pathname+url.search,{credentials:'same-origin',signal});
   if(!response.ok||response.redirected||!(response.headers.get('content-type')||'').startsWith('text/css'))throw Error('Gaya akun belum dapat dimuat. Coba lagi.');
   prepared.push({node:link,type:'style',text:await response.text()});
  }
  for(const script of fresh.content.querySelectorAll('script')){
   const type=(script.getAttribute('type')||'').toLowerCase();if(type==='application/json')continue;
   if(type&&!['application/javascript','text/javascript'].includes(type))throw Error('Kontrol akun belum dikenali. Muat ulang halaman.');
   let text=script.textContent;
   if(script.hasAttribute('src')){
    const url=new URL(script.getAttribute('src'),location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/static/')||url.searchParams.get('v')!==identity.cap)throw Error('Versi kontrol akun berubah. Muat ulang halaman.');
    const response=await fetch(url.pathname+url.search,{credentials:'same-origin',signal});
    if(!response.ok||response.redirected||!['application/javascript','text/javascript'].includes((response.headers.get('content-type')||'').split(';')[0]))throw Error('Kontrol akun belum dapat dimuat. Coba lagi.');
    text=await response.text();
   }
   prepared.push({node:script,type:'script',text});
  }
  return prepared;
 }
 const observer=new MutationObserver(()=>{if(!root.isConnected){reader.stop();observer.disconnect();lifecycle.abort();}});
 const reader=createReader({identity,current,fetch:signal=>fetch(ADDRESS,{method:'GET',credentials:'same-origin',cache:'no-store',signal,headers:{'X-Pindah':'1','Accept':'text/html'}}),parse,prepare,
  loading(){retry.hidden=true;status.setAttribute('role','status');status.textContent='Memuat data akun…';},
  failed(error){status.setAttribute('role','alert');status.textContent=error.name==='AbortError'?'Pembacaan akun terlalu lama. Isian belum dibuka; coba lagi hanya membaca data.':error.message;retry.hidden=false;},
  install(fresh,prepared){
   if(!current())return;const [start,end]=markers(main),focus=document.activeElement,inside=root.contains(focus);
   // Seluruh GET aset sudah selesai. Tidak ada await setelah pemeriksaan akhir.
   observer.disconnect();lifecycle.abort();while(start.nextSibling&&start.nextSibling!==end)start.nextSibling.remove();end.before(fresh.content);document.title=fresh.doc.title||document.title;
   for(const item of prepared){
    const replacement=document.createElement(item.type==='style'?'style':'script');
    for(const attr of item.node.attributes)if(!['src','href','rel','defer','async'].includes(attr.name))replacement.setAttribute(attr.name,attr.value);
    replacement.textContent=item.text;item.node.replaceWith(replacement);
   }
   if(inside&&document.activeElement===document.body){
    const next=focus===retry?fresh.content.querySelector('input[name=nama]'):focus.closest('a[href]')?Array.from(fresh.content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===focus.closest('a[href]').getAttribute('href')):null;
    next?.focus({preventScroll:true});
   }
  }
 });
 observer.observe(document.body,{childList:true,subtree:true});
 retry.addEventListener('click',()=>reader.read());
 window.addEventListener('pagehide',()=>{reader.stop();observer.disconnect();lifecycle.abort();},{once:true,signal:lifecycle.signal});
 reader.read();
})(typeof window==='undefined'?globalThis:window);
