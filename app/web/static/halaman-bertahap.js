/* Hanya dua halaman daftar. Angka/tindakan tetap hasil renderer native.
 * Adapter tidak menulis transaksi dan tidak menyimpan HTML/data di cache.
 */
(function () {
 'use strict';
 const root=document.querySelector('[data-halaman-bertahap]');
 if(!root||root.dataset.ready)return;root.dataset.ready='1';
 const main=document.getElementById('isi-halaman'),status=root.querySelector('[data-shell-status]'),retry=root.querySelector('[data-shell-retry]'),table=root.querySelector('[data-shell-table-wrap]'),message=root.querySelector('[data-shell-message]');
 const detail=root.dataset.kind==='barang-masuk-detail';
 function addressNow(){const u=new URL(location.href);if(detail)u.searchParams.delete('tab_detail');return u.pathname+u.search;}
 const address=addressNow(),token=document.getElementById('formulir-sesi')?.dataset.token||'',stamp=root.dataset.stamp;
 function formState(form){const values=new URLSearchParams(new FormData(form));if(root.dataset.kind==='stok')values.sort();return values.toString();}
 const forms=Array.from(root.querySelectorAll('form')),initialForms=forms.map(formState);
 let sequence=0,controller=null,pending=null,finished=false,readFromRetry=false;
 function current(number){return root.isConnected&&number===sequence&&addressNow()===address&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
 function stop(){++sequence;pending=null;if(controller)controller.abort();controller=null;observer.disconnect();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});
 observer.observe(document.body,{childList:true,subtree:true});
 function controlsChanged(){return forms.some((f,i)=>formState(f)!==initialForms[i]);}
 function interacting(){return controlsChanged()||!!root.querySelector('details[open],dialog[open]')||root.contains(document.activeElement)&&/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);}
 function markers(element){const nodes=Array.from(element.childNodes);return [nodes.find(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),nodes.find(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir')];}
 async function prepareScripts(container,doc,signal){
  const release=doc.documentElement.getAttribute('data-versi');
  if(release!==document.documentElement.getAttribute('data-versi'))throw Error('Versi aplikasi berubah. Muat ulang halaman sebelum melanjutkan.');
  const result=[];
  for(const old of container.querySelectorAll('script')){
   const type=(old.getAttribute('type')||'').toLowerCase();
   if(type==='application/json')continue;
   if(type&&!['text/javascript','application/javascript'].includes(type))throw Error('Jenis kontrol halaman belum didukung. Muat ulang halaman.');
   let text=old.textContent;
   if(old.hasAttribute('src')){
    const url=new URL(old.getAttribute('src'),location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/static/')||url.searchParams.has('v')&&url.searchParams.get('v')!==release)throw Error('Versi kontrol halaman tidak sesuai. Muat ulang halaman.');
    const response=await fetch(url.pathname+url.search,{credentials:'same-origin',signal});
    const mime=(response.headers.get('content-type')||'').split(';')[0];
    if(!response.ok||response.redirected||!['text/javascript','application/javascript'].includes(mime))throw Error('Kontrol halaman belum dapat dimuat. Coba lagi tanpa mengirim transaksi.');
    text=await response.text();
   }
   result.push({old,text});
  }
  return result;
 }
 function activateScripts(prepared){
  // Semua asset sudah dibaca sebelum swap. Tidak ada jeda async yang dapat
  // menjalankan kontrol halaman lama setelah pengguna pindah menu.
  for(const item of prepared){
   const script=document.createElement('script');
   for(const a of item.old.attributes)if(!['src','defer','async'].includes(a.name))script.setAttribute(a.name,a.value);
   script.textContent=item.text;item.old.replaceWith(script);
  }
 }
 function restoreSemanticFocus(previous,content){
  if(document.activeElement!==document.body)return;
  let target=null;
  if(detail&&previous?.hasAttribute('data-bm-tab'))target=content.querySelector('[data-bm-tab="'+CSS.escape(previous.dataset.bmTab)+'"]');
  else if(detail&&previous?.matches('.bm-table-scroll'))target=content.querySelector('.bm-table-scroll')||content.querySelector('[data-bm-tab][aria-selected="true"]');
  else if(previous?.hasAttribute('data-pk-buka'))target=content.querySelector('[data-pk-buka="'+CSS.escape(previous.dataset.pkBuka)+'"]');
  else if(previous?.hasAttribute('data-lk-buka'))target=content.querySelector('[data-lk-buka="'+CSS.escape(previous.dataset.lkBuka)+'"]');
  else if(previous?.hasAttribute('data-shell-guide'))target=content.querySelector('[data-sk-buka="sk-panduan"]');
  else if(root.dataset.kind==='stok'&&previous?.matches('.kontrol-pencarian__submit'))target=content.querySelector('[data-stok-controls] .kontrol-pencarian__submit');
  else if(root.dataset.kind==='stok'&&previous?.hasAttribute('data-sk-buka'))target=content.querySelector('[data-sk-buka="'+CSS.escape(previous.dataset.skBuka)+'"]');
  else if(root.dataset.kind==='stok'&&previous===table){target=content.querySelector('[data-daftar-kosong]');if(!target){content.tabIndex=-1;content.setAttribute('aria-label','Daftar Stok');target=content;}}
  else if(previous?.matches('.halaman-bertahap__filter>summary'))target=content.querySelector('[data-pk-buka="pk-filter"],[data-sk-buka="sk-filter"]');
  else if(previous===retry||previous===document.body&&readFromRetry){content.tabIndex=-1;content.setAttribute('aria-label',detail?'Detail penerimaan':'Daftar '+(root.dataset.kind==='pekerjaan'?'Pekerjaan':'Stok'));target=content;}
  target?.focus({preventScroll:true});
 }
 // Satu pulau kontrol native, bukan morph umum formulir transaksi.
 // Ketidakcocokan struktur berhenti sebelum menyentuh kontrol yang terlihat.
 function controlIsland(content){
  const selector=root.dataset.kind==='pekerjaan'?'.pk-kepala':root.dataset.kind==='stok'?'[data-stok-controls]':null;
  if(!selector)return null;
  const old=root.querySelector(selector),fresh=content.querySelector(selector);
  if(!old||!fresh)throw Error('Struktur kontrol berubah. Muat ulang halaman.');
  const schema=node=>JSON.stringify({
   forms:Array.from(node.querySelectorAll('form')).map(f=>[(f.getAttribute('method')||'get').toLowerCase(),f.getAttribute('action'),Array.from(new Set(Array.from(f.querySelectorAll('[name]')).map(n=>n.name))).sort()]),
   links:Array.from(node.querySelectorAll('a[href]')).map(a=>a.getAttribute('href')),
   dialogs:Array.from(node.querySelectorAll('dialog')).map(d=>d.id),
  });
  if(schema(old)!==schema(fresh))throw Error('Cakupan kontrol berubah. Muat ulang halaman.');
  return {old,fresh};
 }
 function retainControls(island){
  if(!island)return;
  const {old,fresh}=island;
  // GET native yang sama menentukan angka/opsi. Ketikan dan panel terbuka
  // sudah ditahan oleh interacting(), juga sesudah seluruh aset selesai.
  for(const select of old.querySelectorAll('select[name]')){
   const native=fresh.querySelector('select[name="'+CSS.escape(select.name)+'"]');
   if(!native)continue;
   select.replaceChildren(...Array.from(native.options,o=>o.cloneNode(true)));select.value=native.value;
  }
  for(const selector of ['[data-pk-cetak]','[data-sk-cetak]','select[name]']){
   const controls=old.querySelectorAll(selector),native=fresh.querySelectorAll(selector);
   controls.forEach((control,i)=>{if(!native[i])return;for(const attr of ['disabled','aria-describedby']){if(native[i].hasAttribute(attr))control.setAttribute(attr,native[i].getAttribute(attr));else control.removeAttribute(attr);}});
  }
  const counts=old.querySelectorAll('.kontrol-tab__jumlah'),nativeCounts=fresh.querySelectorAll('.kontrol-tab__jumlah');
  counts.forEach((count,i)=>{if(nativeCounts[i])count.textContent=nativeCounts[i].textContent;});
  // Placeholder nama memiliki hidden fallback hanya selama select disabled.
  for(const input of old.querySelectorAll('input[type="hidden"][name]')){
   if(old.querySelector('select[name="'+CSS.escape(input.name)+'"]')&&!fresh.querySelector('input[type="hidden"][name="'+CSS.escape(input.name)+'"]'))input.remove();
  }
  for(const reason of old.querySelectorAll('[id^="shell-"]'))if(!fresh.querySelector('#'+CSS.escape(reason.id)))reason.remove();
  if(fresh.dataset.pelangganUrl)old.dataset.pelangganUrl=fresh.dataset.pelangganUrl;
  old.pfStockShellStop?.();
  fresh.replaceWith(old);
 }
 function stockTable(content){
  if(root.dataset.kind!=='stok')return null;
  const old=table.querySelector('table'),head=old?.querySelector('thead');if(!head)return null;
  const columns=n=>Array.from(n.querySelectorAll('th'),th=>th.textContent.trim().replace(/\s+/g,' '));
  const oldColumns=columns(head),native=Array.from(content.querySelectorAll('.stok-seragam table')).filter(candidate=>{
   const fresh=columns(candidate.querySelector('thead')||candidate);
   return fresh.length===oldColumns.length&&fresh.every((label,i)=>label===oldColumns[i]||i===fresh.length-1&&label===''&&oldColumns[i]==='Tindakan'&&candidate.classList.contains('stok-tabel'));
  });
  // Beberapa tabel pemilik tidak disatukan: hasil tetap markup native.
  return native.length===1?{old,head,fresh:native[0]}:null;
 }
 function retainTable(plan){
  if(!plan)return;
  const {old,head,fresh}=plan;
  // Identitas table/thead/kolom tetap; badan dan gaya persis renderer native.
  const nativeColumns=fresh.querySelectorAll('thead th');
  head.querySelectorAll('th').forEach((th,i)=>{
   th.textContent=nativeColumns[i].textContent;
   for(const attr of Array.from(th.attributes))th.removeAttribute(attr.name);
   for(const attr of nativeColumns[i].attributes)th.setAttribute(attr.name,attr.value);
  });
  for(const attr of Array.from(old.attributes))old.removeAttribute(attr.name);
  for(const attr of fresh.attributes)old.setAttribute(attr.name,attr.value);
  for(const child of Array.from(old.children))if(child!==head)child.remove();
  for(const child of Array.from(fresh.children))if(child.tagName!=='THEAD')old.append(child);
  fresh.replaceWith(old);
 }
 async function install(payload,number){
  if(!current(number)||payload.stamp!==stamp)throw Error('Konteks sesi atau gudang berubah. Muat ulang halaman untuk membaca cakupan yang benar.');
  const doc=new DOMParser().parseFromString(payload.html,'text/html'),source=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(!source||session?.dataset.token!==token)throw Error('Sesi pembacaan berubah. Muat ulang halaman.');
  const [start,end]=markers(source),[from,to]=markers(main);if(!start||!end||!from||!to)throw Error('Struktur daftar belum dapat dibaca. Coba lagi.');
  if(interacting()){
   pending={payload,number};status.textContent='Data siap. Terapkan filter yang sedang Anda isi; pilihan tetap dipertahankan.';return;
  }
  const content=document.createElement('div');content.dataset.halamanIsi=root.dataset.kind;
  for(let node=start.nextSibling;node&&node!==end;node=node.nextSibling)content.append(node.cloneNode(true));
  const css=main.querySelector('link[href*="/static/halaman-bertahap.css"]');if(css)content.prepend(css.cloneNode(true));
  // Consumer pilihan pelanggan lama membaca HTML. Tetap memakai route native
  // melalui endpoint baca khusus, bukan merender shell kembali sebagai opsi.
  const stock=content.querySelector('[data-stok-controls]');
  if(stock){const url=new URL(stock.dataset.pelangganUrl,location.href);url.pathname='/api/halaman-bertahap/stok/html';stock.dataset.pelangganUrl=url.pathname+url.search;}
  const island=controlIsland(content),stockFrame=stockTable(content);
  const prepared=await prepareScripts(content,doc,controller?.signal);
  if(!current(number)||payload.stamp!==stamp)return;
  // Pengguna dapat membuka filter ketika asset masih dibaca.
  if(interacting()){
   pending={payload,number};status.textContent='Data siap. Terapkan filter yang sedang Anda isi; pilihan tetap dipertahankan.';return;
  }
  if(detail){
   // Tab boleh berubah selama pembacaan tanpa mengubah draf/controller.
   // Aset sudah selesai dibaca. Pilih tab TERKINI tepat sebelum swap;
   // tidak ada await lagi yang dapat membekukan pilihan selama GET aset.
   const key=new URL(location.href).searchParams.get('tab_detail')||'ringkasan';
   for(const tab of content.querySelectorAll('[data-bm-tab]')){const active=tab.dataset.bmTab===key;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
   for(const panel of content.querySelectorAll('[data-bm-detail-panel]')){panel.hidden=panel.dataset.bmDetailPanel!==key;if(!panel.hidden&&key!=='ringkasan')panel.querySelector('details')?.setAttribute('open','');}
   const rincian=content.querySelector('[data-bm-detail-rincian]');if(rincian)rincian.hidden=key==='ringkasan';
  }
  if(!window.PINDAH?.selaraskanChrome||!PINDAH.selaraskanChrome(doc))throw Error('Konteks navigasi berubah. Muat ulang halaman.');
  const previousFocus=document.activeElement;
  retainControls(island);retainTable(stockFrame);
  observer.disconnect();finished=true;controller=null;
  while(from.nextSibling&&from.nextSibling!==to)from.nextSibling.remove();to.before(content);
  const valid=()=>content.isConnected&&addressNow()===address&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;
  try{
   activateScripts(prepared);if(!valid())return;
   restoreSemanticFocus(previousFocus,content);

  }catch(error){if(valid()){const warning=document.createElement('p');warning.setAttribute('role','alert');warning.textContent=error.message;content.prepend(warning);}}
 }
 async function read(){
  readFromRetry=document.activeElement===retry;
  if(controller)controller.abort();const number=++sequence;controller=new AbortController();const active=controller;pending=null;
  retry.hidden=true;table.setAttribute('aria-busy','true');status.textContent=detail?'Memuat detail penerimaan…':'Memuat data…';message.textContent=detail?'Nilai, sumber dan tindakan menunggu pembacaan terbaru.':'Memuat data. Judul kolom dan filter tetap tersedia.';
  const timeout=setTimeout(()=>active.abort(),20000);
  try{
   const response=await fetch(root.dataset.url,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:{'Accept':'application/json'}});
   if(!current(number))return;
   if(response.redirected||!response.ok){
    let detail='';if(!response.redirected&&[400,404,409,422].includes(response.status)){try{const body=await response.json();if(typeof body.detail==='string')detail=body.detail;}catch(_){}}
    throw Error(response.status===401||response.status===403?'Sesi atau akses berubah. Muat ulang halaman untuk memeriksa akses.':detail||'Data belum dapat dimuat. Coba lagi hanya membaca, tanpa mencatat transaksi.');
   }
   const payload=await response.json();if(current(number))await install(payload,number);
  }catch(error){
   failed(error,number);
  }finally{clearTimeout(timeout);if(current(number)){controller=null;table.setAttribute('aria-busy','false');}}
 }
 function failed(error,number){if(!current(number))return;status.textContent=error.name==='AbortError'?'Pembacaan terlalu lama. Data belum tersedia.':error.message;message.textContent=detail?'Gagal memuat detail; ini bukan penerimaan kosong.':'Gagal memuat data; ini bukan daftar kosong.';retry.hidden=false;}
 async function resume(){
  if(!pending||interacting())return;
  const next=pending;pending=null;if(!current(next.number))return;
  const active=new AbortController();controller=active;const timer=setTimeout(()=>active.abort(),20000);
  try{await install(next.payload,next.number);}catch(error){failed(error,next.number);}
  finally{clearTimeout(timer);if(controller===active)controller=null;}
 }
 retry.addEventListener('click',read);
 root.addEventListener('toggle',resume,true);
 root.addEventListener('close',resume,true);
 root.addEventListener('focusout',()=>queueMicrotask(resume));
 const guide=root.querySelector('[data-shell-guide-panel]');
 root.querySelector('[data-shell-guide]')?.addEventListener('click',()=>guide.showModal());
 root.querySelector('[data-shell-guide-close]')?.addEventListener('click',()=>guide.close());
 if(root.dataset.kind==='stok'){
  // Kerangka memakai markup header native yang sama. Controller daftar
  // native baru aktif setelah data; di sini hanya panel baca yang dibuka.
  let opener=null;
  const shellDialogs=new AbortController(),stockControls=root.querySelector('[data-stok-controls]');
  if(stockControls)stockControls.pfStockShellStop=()=>shellDialogs.abort();
  root.addEventListener('click',event=>{
   const open=event.target.closest('[data-sk-buka]'),close=event.target.closest('[data-sk-tutup]');
   if(open){const panel=root.querySelector('#'+CSS.escape(open.dataset.skBuka));if(panel?.tagName==='DIALOG'){opener=open;panel.showModal();}}
   if(close)close.closest('dialog')?.close();
  },{signal:shellDialogs.signal});
  for(const panel of root.querySelectorAll('dialog'))panel.addEventListener('close',()=>{if(opener?.isConnected)opener.focus({preventScroll:true});},{signal:shellDialogs.signal});
 }
 const leave=e=>{const a=e.target.closest?.('a[href]');if(!finished&&root.isConnected&&a&&!a.target&&!a.hasAttribute('download')&&!a.hash&&!e.defaultPrevented&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey){stop();}};
 if(window.PINDAH)PINDAH.pasang(document,'click',leave);else document.addEventListener('click',leave,{once:true});
 read();
})();
