/* Satu pemilik pembacaan: shell awal dan pencarian memakai renderer native.
 * GET lama boleh dibatalkan/diabaikan; tidak ada cache HTML transaksi atau POST. */
(function(){'use strict';
 function pasang(root){
  if(!root||root.dataset.siap)return;
  // HTML rilis lama boleh bertemu asset baru saat upgrade/rollback. Tanpa
  // penanda otoritatif, pertahankan GET form/link native; jangan membuat stamp.
  let schemas;try{schemas=JSON.parse(root.dataset.bmSchemas);}catch(_){return;}
  if(!root.dataset.bmContext||!root.dataset.bmCap||!schemas?.belum||!schemas?.diterima)return;
  root.dataset.siap='1';
  root.querySelector('[data-bm-bootstrap]')?.setAttribute('hidden','');
  const search=root.querySelector('[data-bm-search]'),input=search.querySelector('[name=cari]'),name=search.querySelector('[name=pemasok]');
  const result=root.querySelector('[data-bm-results]'),status=root.querySelector('[data-bm-read-status]'),error=root.querySelector('[data-bm-error]');
  const tokenSesi=()=>document.getElementById('formulir-sesi')?.dataset.token||'';
  const originalToken=tokenSesi(),context=root.dataset.bmContext,cap=root.dataset.bmCap,version=document.documentElement.getAttribute('data-versi')||'';
  const forms=Array.from(root.querySelectorAll('form'));
  let outer=null;
  let generation=0,controller=null,pending=null,lastURL=location.pathname+location.search,lastDraft='';
  const nilaiIsian=()=>forms.map(f=>new URLSearchParams(new FormData(f)).toString()).join('|');
  let baseline=nilaiIsian();
  const alamatDaftar=u=>{const v=new URL(u,location.href);if(v.origin!==location.origin||v.pathname!=='/barang-masuk')throw Error('Tujuan daftar tidak sesuai.');return v.pathname+v.search;};
  function masihBerlaku(n,url){return root.isConnected&&document.querySelector('[data-bm-page]')===root&&n===generation&&location.pathname+location.search===url&&tokenSesi()===originalToken;}
  function hentikanBaca(){++generation;controller?.abort();controller=null;pending=null;observer.disconnect();document.removeEventListener('click',tinggalkanHalaman);if(outer?.bmReadHandler===navigasiDaftar){outer.removeEventListener('click',navigasiDaftar);delete outer.bmReadHandler;}}
  const observer=new MutationObserver(()=>{if(!root.isConnected)hentikanBaca();});observer.observe(document.body,{childList:true,subtree:true});
  function tandaiPilihan(){root.querySelector('#bm-belum-cari').hidden=input.value.trim()===root.dataset.cariTertampil&&name.value===root.dataset.pemasokTertampil;}
  function aturCetak(ready){
   for(const b of document.querySelectorAll('[data-lk-cetak], [data-bm-cetak]')){b.disabled=!ready;if(!ready)b.setAttribute('aria-describedby','bm-cetak-alasan');else if(b.getAttribute('aria-describedby')==='bm-cetak-alasan')b.removeAttribute('aria-describedby');}
   root.querySelector('#bm-cetak-alasan').hidden=ready;
  }
  function tampilkanTabel(state,url){
   const focus=ambilFokus();
   const q=new URL(url,location.href).searchParams,kind=q.get('status')==='diterima'?'diterima':'belum';
   const box=document.createElement('div');box.className='bm-state-scroll';box.tabIndex=0;box.setAttribute('role','region');box.setAttribute('aria-label','Daftar penerimaan · tabel dapat digulir');
   const t=document.createElement('table');t.className='bm-state-table';const head=t.createTHead().insertRow();
   for(const label of schemas[kind]){const th=document.createElement('th');th.scope='col';th.textContent=label;head.append(th);}
   const cell=t.createTBody().insertRow().insertCell();cell.colSpan=schemas[kind].length;cell.dataset.bmStateMessage='';
   cell.textContent=state==='loading'?'Memuat daftar penerimaan. Judul kolom dan pilihan tetap tersedia.':'Daftar penerimaan gagal dimuat. Coba lagi hanya membaca data; ini bukan daftar kosong.';
   box.append(t);result.replaceChildren(box);result.setAttribute('aria-busy',String(state==='loading'));
   if(focus?.region)pulihkanFokus(root,focus);
  }
  function sedangMengisi(){return nilaiIsian()!==baseline||!!root.querySelector('dialog[open]')||root.contains(document.activeElement)&&/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);}
  function ambilFokus(){const n=document.activeElement;if(!root.contains(n))return null;return {region:n.matches('.bm-state-scroll')||n===result,name:n.name,type:n.type,open:n.dataset?.bmBuka,retry:n.hasAttribute('data-bm-retry'),search:n.closest('[data-bm-search]')&&n.type==='submit',start:n.selectionStart,end:n.selectionEnd};}
  function pulihkanFokus(next,old){if(!old)return;let n;if(old.region){n=next.querySelector('[data-bm-results] .bm-state-scroll')||next.querySelector('[data-bm-results]');if(n&&!n.hasAttribute('tabindex'))n.tabIndex=-1;}else if(old.name)n=Array.from(next.querySelectorAll('input,select,textarea')).find(x=>x.name===old.name&&x.type===old.type);else if(old.open)n=Array.from(next.querySelectorAll('[data-bm-buka]')).find(x=>x.dataset.bmBuka===old.open);else if(old.retry)n=next.querySelector('.bm-jumlah');else if(old.search)n=next.querySelector('[data-bm-search] button[type=submit]');if(n){if(old.retry)n.tabIndex=-1;n.focus({preventScroll:true});if(old.start!=null&&n.setSelectionRange)try{n.setSelectionRange(old.start,old.end);}catch(_){}}}
  function pasangHasil(doc,n,url){
   if(!masihBerlaku(n,url))return;const next=doc.querySelector('[data-bm-page]');
   if(!context||!cap||!next||next.dataset.bmContext!==context||next.dataset.bmCap!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==originalToken||version&&doc.documentElement.getAttribute('data-versi')!==version)throw Error('Sesi, gudang atau versi berubah. Muat ulang halaman sebelum membaca cakupan terbaru.');
   if(next.hasAttribute('data-bm-shell')||next.querySelector('[data-bm-error]:not([hidden])'))throw Error('Daftar belum berhasil dibaca. Coba lagi tanpa mencatat transaksi.');
   if(sedangMengisi()){pending={doc,n,url};status.textContent='Data siap. Isian pilihan tetap dipertahankan; terapkan atau tutup pilihan untuk melanjutkan.';return;}
   const focus=ambilFokus(),holder=document.querySelector('.isi'),scroll=holder?.scrollTop;
   const tabs=document.querySelector('nav[aria-label="Bagian Barang Masuk"]'),fresh=doc.querySelector('nav[aria-label="Bagian Barang Masuk"]');
   if(tabs&&fresh)tabs.replaceChildren(...Array.from(fresh.childNodes,x=>x.cloneNode(true)));
   const link=document.querySelector('#laci a[href="/barang-masuk"]'),freshLink=doc.querySelector('#laci a[href="/barang-masuk"]');
   if(link&&freshLink){link.querySelectorAll('.pintu__jml').forEach(x=>x.remove());for(const badge of freshLink.querySelectorAll('.pintu__jml'))link.append(badge.cloneNode(true));}
   hentikanBaca();root.replaceWith(next);if(window.PINDAH){PINDAH.lupakan();PINDAH.lupakanSentuhan();}pasang(next);pulihkanFokus(next,focus);if(holder&&scroll!=null)holder.scrollTop=scroll;
  }
  function tampilkanGagal(e,n,url){if(!masihBerlaku(n,url))return;pending=null;error.hidden=false;status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Coba lagi tanpa mengirim pencatatan.':e.message;tampilkanTabel('error',url);aturCetak(false);tandaiPilihan();}
  async function baca(url,json=false,push=true){
   const target=json?location.pathname+location.search:alamatDaftar(url);
   controller?.abort();const n=++generation,active=new AbortController();controller=active;pending=null;lastURL=target;
   if(push&&location.pathname+location.search!==target)history.pushState({pindah:1},'',target);
   const q=new URL(target,location.href).searchParams;
   root.querySelectorAll('input[name=status]').forEach(x=>x.value=q.get('status')==='diterima'?'diterima':'belum');
   const targetStatus=q.get('status')==='diterima'?'diterima':'belum';root.dataset.bmStatus=targetStatus;
   for(const a of document.querySelectorAll('nav[aria-label="Bagian Barang Masuk"] a,[data-bm-page] [data-bm-nav] a')){const u=new URL(a.href,location.href);if(u.pathname!=='/barang-masuk')continue;const current=(u.searchParams.get('status')||'belum')===targetStatus;if(current)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
   root.querySelectorAll('.kontrol-tab__jumlah').forEach(x=>x.textContent='…');
   for(const badge of document.querySelectorAll('#laci a[href="/barang-masuk"] .pintu__jml')){badge.textContent='…';badge.setAttribute('aria-label','Jumlah penerimaan belum dibaca');}
   const count=root.querySelector('.bm-jumlah');count.replaceChildren();const unknown=document.createElement('strong');unknown.textContent='Jumlah hasil belum tersedia';count.append(unknown);if(q.get('cari'))count.append(document.createTextNode(' untuk “'+q.get('cari')+'”'));
   baseline=nilaiIsian();lastDraft=baseline;error.hidden=true;tampilkanTabel('loading',target);aturCetak(false);status.textContent='Memuat daftar penerimaan…';
   const timer=setTimeout(()=>active.abort(),25000);
   try{
    const r=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:json?{'Accept':'application/json'}:{'X-Barang-Masuk-Cari':'1'}});
    if(!masihBerlaku(n,target))return;
    if(r.redirected||!r.ok)throw Error(r.status===401||r.status===403?'Sesi atau akses berubah. Muat ulang halaman untuk memeriksa akses.':'Daftar penerimaan belum dapat dibaca. Coba lagi tanpa mengirim pencatatan.');
    let html;if(json){const payload=await r.json();if(payload.stamp!==root.dataset.bmStamp)throw Error('Konteks daftar berubah. Muat ulang halaman untuk membaca cakupan yang benar.');html=payload.html;}else html=await r.text();
    if(masihBerlaku(n,target))pasangHasil(new DOMParser().parseFromString(html,'text/html'),n,target);
   }catch(e){tampilkanGagal(e,n,target);}
   finally{clearTimeout(timer);if(masihBerlaku(n,target)){controller=null;result.setAttribute('aria-busy','false');}}
  }
  function lanjutkanHasil(){if(!pending||sedangMengisi())return;const p=pending;pending=null;try{pasangHasil(p.doc,p.n,p.url);}catch(e){tampilkanGagal(e,p.n,p.url);}}
  search.addEventListener('input',tandaiPilihan);search.addEventListener('change',tandaiPilihan);search.addEventListener('pf:read-state-restored',tandaiPilihan);
  for(const f of forms)f.addEventListener('submit',e=>{e.preventDefault();if(f.matches('.bm-form-filter')){let field=f.querySelector('[name=cari]');if(!field){field=document.createElement('input');field.type='hidden';field.name='cari';f.append(field);}field.value=input.value;f.closest('dialog')?.close();}const u=new URL(f.action,location.href);u.search=new URLSearchParams(new FormData(f)).toString();baca(u.pathname+u.search);});
  function navigasiDaftar(e){const a=e.target.closest('a[href]');if(!a||e.defaultPrevented||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0||a.target||a.hasAttribute('download'))return;const u=new URL(a.href);if(u.origin!==location.origin||u.pathname!=='/barang-masuk')return;e.preventDefault();e.stopPropagation();baca(u.pathname+u.search);}
  root.addEventListener('click',e=>{if(e.target.closest('[data-bm-nav]'))navigasiDaftar(e);});
  outer=document.querySelector('nav[aria-label="Bagian Barang Masuk"]');if(outer){if(outer.bmReadHandler)outer.removeEventListener('click',outer.bmReadHandler);outer.bmReadHandler=navigasiDaftar;outer.addEventListener('click',navigasiDaftar);}
  function tinggalkanHalaman(e){if(e.defaultPrevented||!root.isConnected||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0)return;const a=e.target.closest('a[href]');if(a&&!a.target&&!a.hash&&!a.hasAttribute('download'))hentikanBaca();}
  document.addEventListener('click',tinggalkanHalaman);
  root.addEventListener('close',lanjutkanHasil,true);// Tunggu default perpindahan fokus keyboard selesai sebelum mengganti DOM.
  root.addEventListener('focusout',()=>requestAnimationFrame(lanjutkanHasil));
  root.querySelector('[data-bm-retry]').addEventListener('click',()=>{if(nilaiIsian()!==lastDraft&&lastDraft){status.textContent='Isian pilihan berubah. Tekan Cari atau Terapkan filter agar pilihan terbaru digunakan.';return;}baca(lastURL);});
  if(window.PADIFLOW_MASUK)PADIFLOW_MASUK(root.querySelector('.bm-kepala'));tandaiPilihan();
  if(root.hasAttribute('data-bm-shell'))baca(root.dataset.bmUrl,true,false);else aturCetak(!root.querySelector('[data-bm-error]:not([hidden])'));
 }
 pasang(document.querySelector('[data-bm-page]'));
})();
