/* Hanya dua halaman daftar. Angka/tindakan tetap hasil renderer native.
 * Adapter tidak menulis transaksi dan tidak menyimpan HTML/data di cache.
 */
(function () {
 'use strict';
 const root=document.querySelector('[data-halaman-bertahap]');
 if(!root||root.dataset.ready)return;root.dataset.ready='1';
 const main=document.getElementById('isi-halaman'),status=root.querySelector('[data-shell-status]'),retry=root.querySelector('[data-shell-retry]'),table=root.querySelector('[data-shell-table-wrap]'),message=root.querySelector('[data-shell-message]');
 const address=location.pathname+location.search,token=document.getElementById('formulir-sesi')?.dataset.token||'',stamp=root.dataset.stamp;
 const emptyTable=table.cloneNode(true),filtered=root.dataset.filtered==='1';
 const forms=Array.from(root.querySelectorAll('form')),initialForms=forms.map(f=>new URLSearchParams(new FormData(f)).toString());
 let sequence=0,controller=null,pending=null,finished=false;
 function current(number){return root.isConnected&&number===sequence&&location.pathname+location.search===address&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
 function stop(){++sequence;pending=null;if(controller)controller.abort();controller=null;observer.disconnect();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});
 observer.observe(document.body,{childList:true,subtree:true});
 function controlsChanged(){return forms.some((f,i)=>new URLSearchParams(new FormData(f)).toString()!==initialForms[i]);}
 function markers(element){const nodes=Array.from(element.childNodes);return [nodes.find(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),nodes.find(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir')];}
 function emptyText(){return filtered?'Tidak ada hasil pada filter ini. Atur ulang filter untuk memeriksa seluruh cakupan.':root.dataset.kind==='pekerjaan'?'Belum ada proses aktif pada cakupan ini.':'Belum ada stok pada cakupan ini.';}
 function keepEmptyStructure(container){
  const rows=container.querySelectorAll('.proses-aktif-list__row,.stok-baris__tautan,.stok-mobile-list__baris,.produk-list .tabel-standar__item,.karung-tabel tbody tr');
  if(rows.length)return;
  // Pesan native lama tidak menggantikan struktur daftar kosong dua route ini.
  container.querySelectorAll('.kosong').forEach(n=>n.remove());
  const blank=emptyTable.cloneNode(true);blank.removeAttribute('data-shell-table-wrap');blank.setAttribute('aria-busy','false');blank.querySelector('[data-shell-message]').textContent=emptyText();
  const target=container.querySelector('.stok-seragam,.laporan-isi')||container;target.append(blank);
 }
 function filterEmptyRows(container){
  container.querySelectorAll('table').forEach(t=>{
   if(!t.getClientRects().length)return;
   const body=t.tBodies[0];if(!body||!body.querySelector('tr:not([data-shell-empty-row])'))return;
   const rows=Array.from(body.rows).filter(r=>!r.hasAttribute('data-shell-empty-row'));
   const empty=rows.length&&!rows.some(r=>!r.hidden);
   let row=body.querySelector('[data-shell-empty-row]');
   if(empty&&!row){row=document.createElement('tr');row.dataset.shellEmptyRow='';const cell=row.insertCell();cell.colSpan=Math.max(1,t.tHead?.rows[0]?.cells.length||1);cell.textContent='Tidak ada hasil yang cocok dengan filter ini. Ubah atau atur ulang filter.';body.append(row);}
   if(row)row.hidden=!empty;
  });
 }
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
 async function install(payload,number){
  if(!current(number)||payload.stamp!==stamp)throw Error('Konteks sesi atau gudang berubah. Muat ulang halaman untuk membaca cakupan yang benar.');
  const doc=new DOMParser().parseFromString(payload.html,'text/html'),source=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(!source||session?.dataset.token!==token)throw Error('Sesi pembacaan berubah. Muat ulang halaman.');
  const [start,end]=markers(source),[from,to]=markers(main);if(!start||!end||!from||!to)throw Error('Struktur daftar belum dapat dibaca. Coba lagi.');
  if(controlsChanged()||root.querySelector('details[open]')||root.contains(document.activeElement)&&/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)){
   pending={payload,number};status.textContent='Data siap. Terapkan filter yang sedang Anda isi; pilihan tetap dipertahankan.';return;
  }
  const content=document.createElement('div');content.dataset.halamanIsi=root.dataset.kind;
  for(let node=start.nextSibling;node&&node!==end;node=node.nextSibling)content.append(node.cloneNode(true));
  keepEmptyStructure(content);
  const css=main.querySelector('link[href*="/static/halaman-bertahap.css"]');if(css)content.prepend(css.cloneNode(true));
  // Consumer pilihan pelanggan lama membaca HTML. Tetap memakai route native
  // melalui endpoint baca khusus, bukan merender shell kembali sebagai opsi.
  const stock=content.querySelector('[data-stok-controls]');
  if(stock){const url=new URL(stock.dataset.pelangganUrl,location.href);url.pathname='/api/halaman-bertahap/stok/html';stock.dataset.pelangganUrl=url.pathname+url.search;}
  const prepared=await prepareScripts(content,doc,controller?.signal);
  if(!current(number)||payload.stamp!==stamp)return;
  // Pengguna dapat membuka filter ketika asset masih dibaca.
  if(controlsChanged()||root.querySelector('details[open]')||root.contains(document.activeElement)&&/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)){
   pending={payload,number};status.textContent='Data siap. Terapkan filter yang sedang Anda isi; pilihan tetap dipertahankan.';return;
  }
  observer.disconnect();finished=true;controller=null;
  while(from.nextSibling&&from.nextSibling!==to)from.nextSibling.remove();to.before(content);
  const valid=()=>content.isConnected&&location.pathname+location.search===address&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;
  try{
   activateScripts(prepared);if(!valid())return;
   filterEmptyRows(content);
   const removeMessages=()=>content.querySelectorAll('[data-shell-empty-row]').forEach(n=>n.remove());
   content.addEventListener('submit',removeMessages,true);
   content.addEventListener('search',removeMessages,true);
   content.addEventListener('keydown',e=>{if(e.key==='Escape')removeMessages();},true);
   content.addEventListener('submit',()=>queueMicrotask(()=>filterEmptyRows(content)));
   content.addEventListener('search',()=>queueMicrotask(()=>filterEmptyRows(content)));
   content.addEventListener('keydown',e=>{if(e.key==='Escape')queueMicrotask(()=>filterEmptyRows(content));});
   if(window.PINDAH)PINDAH.pasang(window,'resize',()=>filterEmptyRows(content));
  }catch(error){if(valid()){const warning=document.createElement('p');warning.setAttribute('role','alert');warning.textContent=error.message;content.prepend(warning);}}
 }
 async function read(){
  if(controller)controller.abort();const number=++sequence;controller=new AbortController();const active=controller;pending=null;
  retry.hidden=true;table.setAttribute('aria-busy','true');status.textContent='Memuat data…';message.textContent='Memuat data. Judul kolom dan filter tetap tersedia.';
  const timeout=setTimeout(()=>active.abort(),20000);
  try{
   const response=await fetch(root.dataset.url,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:{'Accept':'application/json'}});
   if(!current(number))return;
   if(response.redirected||!response.ok)throw Error(response.status===401||response.status===403?'Sesi atau akses berubah. Muat ulang halaman untuk memeriksa akses.':'Data belum dapat dimuat. Coba lagi hanya membaca, tanpa mencatat transaksi.');
   const payload=await response.json();if(current(number))await install(payload,number);
  }catch(error){
   if(!current(number))return;status.textContent=error.name==='AbortError'?'Pembacaan terlalu lama. Data belum tersedia.':error.message;message.textContent='Gagal memuat data; ini bukan daftar kosong.';retry.hidden=false;
  }finally{clearTimeout(timeout);if(current(number)){controller=null;table.setAttribute('aria-busy','false');}}
 }
 retry.addEventListener('click',read);
 root.addEventListener('toggle',()=>{if(pending&&!root.querySelector('details[open]')){const next=pending;pending=null;install(next.payload,next.number).catch(e=>{if(current(next.number)){status.textContent=e.message;retry.hidden=false;}});}},true);
 root.addEventListener('focusout',()=>{if(pending)queueMicrotask(()=>{if(pending){const next=pending;pending=null;install(next.payload,next.number).catch(()=>{});}});});
 const leave=e=>{const a=e.target.closest?.('a[href]');if(!finished&&root.isConnected&&a&&!a.target&&!a.hasAttribute('download')&&!a.hash&&!e.defaultPrevented&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey){stop();}};
 if(window.PINDAH)PINDAH.pasang(document,'click',leave);else document.addEventListener('click',leave,{once:true});
 read();
})();
