/* Daftar dibaca sekali lewat GET native; tidak ada penyimpanan transaksi. */
(function(){
 'use strict';
 function mulai(){
  const root=document.querySelector('[data-daftar-retur-supplier]');if(!root)return;
  const getForm=root.querySelector('#rrs-form');
  // Form GET memakai navigator/penjaga yang sama dengan tautan, termasuk
  // field di dialog yang tetap dimiliki form. Tidak ada submit transaksi.
  if(window.PINDAH&&getForm&&!getForm.dataset.rrsGetReady){
   getForm.dataset.rrsGetReady='1';PINDAH.pasang(getForm,'submit',e=>{
    if(e.defaultPrevented||getForm.method.toLowerCase()!=='get'||getForm.target)return;
    const u=new URL(getForm.action,location.href);if(u.origin!==location.origin||u.pathname!=='/riwayat-retur-supplier')return;
    u.search=new URLSearchParams(new FormData(getForm)).toString();u.hash='';e.preventDefault();
    const link=document.createElement('a');link.href=u.pathname+u.search;link.hidden=true;root.append(link);link.click();link.remove();
   });
  }
  if(!root.hasAttribute('data-rrs-shell')||root.dataset.rrsReadReady)return;root.dataset.rrsReadReady='1';
  const address=location.pathname+location.search,context=root.dataset.rrsContext,cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token||'',status=root.querySelector('#rrs-baca-status'),retry=root.querySelector('[data-rrs-retry]'),content=root.querySelector('[data-rrs-content]');
  let request=null,sequence=0,done=false;
  function valid(n){return !done&&root.isConnected&&n===sequence&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
  function stop(){sequence++;request?.abort();observer.disconnect();}
  const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
  function install(doc){
   const fresh=doc.querySelector('[data-rrs-native]'),frame=doc.querySelector('.bingkai'),next=fresh?.querySelector('[data-rrs-content]'),form=root.querySelector('#rrs-form'),nextForm=fresh?.querySelector('#rrs-form');
   if(!fresh||!next||!nextForm||fresh.querySelector('script,form[method="post"]')||doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==address||doc.getElementById('formulir-sesi')?.dataset.token!==token)throw Error('Konteks riwayat berubah. Muat ulang untuk memeriksa akses.');
   const problem=next.querySelector('[role="alert"]');if(problem)throw Error(problem.textContent.trim());
   const table=content.querySelector('.rsh-tabel'),newTable=next.querySelector('.rsh-tabel'),cards=content.querySelector('.rsh-kartu-daftar'),newCards=next.querySelector('.rsh-kartu-daftar'),metrics=content.querySelector('.rrs-metrik'),newMetrics=next.querySelector('.rrs-metrik');
   const columns=n=>[...n?.querySelectorAll('thead th')||[]].map(x=>x.textContent.trim()).join('|');
   if(!table||!newTable||!cards||!newCards||!newMetrics||columns(table)!==columns(newTable)||newMetrics.querySelectorAll('strong').length!==3)throw Error('Struktur daftar belum lengkap. Coba lagi hanya membaca.');
   const changes=[];
   for(const name of ['supplier','gudang']){const old=root.querySelector('select[name="'+name+'"]'),actual=fresh.querySelector('select[name="'+name+'"]');if(!old||!actual)throw Error('Pilihan filter belum lengkap. Coba lagi.');changes.push({old,actual});}
   const focus=document.activeElement;
   if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Konteks navigasi berubah. Muat ulang halaman.');
   if(focus?.matches('a.desktop-back')&&!focus.isConnected){const back=document.querySelector('a.desktop-back');if(back&&!back.hidden&&back.href===focus.href)back.replaceWith(focus);}
   // Form dan input yang sedang diketik tetap; hanya opsi yang tadinya belum
   // dibaca diisi dari cakupan native. Tidak pernah menerapkan filter otomatis.
   for(const {old,actual} of changes){const value=actual.value;old.replaceChildren(...actual.childNodes);old.value=value;for(const option of old.options)option.toggleAttribute('selected',option.selected);old.disabled=actual.disabled;old.removeAttribute('title');form.querySelectorAll('input[data-rrs-filter-pending][name="'+old.name+'"]').forEach(n=>n.remove());}
   for(const name of ['scope','filter-tags']){const old=root.querySelector('[data-rrs-'+name+']'),actual=fresh.querySelector('[data-rrs-'+name+']');if(old&&actual)old.replaceChildren(...actual.childNodes);}
   const actualTable=newTable.querySelector('table'),oldTable=table.querySelector('table'),head=oldTable.querySelector('thead');actualTable.querySelector('thead').replaceWith(head);oldTable.replaceChildren(...actualTable.childNodes);newTable.querySelector('table').replaceWith(oldTable);table.replaceChildren(...newTable.childNodes);newTable.replaceWith(table);
   cards.replaceChildren(...newCards.childNodes);newCards.replaceWith(cards);
   metrics.replaceChildren(...newMetrics.childNodes);newMetrics.replaceWith(metrics);
   content.replaceChildren(...next.childNodes);root.querySelector('[data-rrs-read-state]').remove();root.removeAttribute('data-rrs-shell');root.setAttribute('data-rrs-native','');root.dataset.halamanIsi='rrs-daftar';done=true;observer.disconnect();
   for(const print of document.querySelectorAll('[data-lk-cetak][aria-describedby="rrs-baca-status"]')){const native=doc.querySelector('[data-lk-cetak]');print.disabled=!native||native.disabled;print.removeAttribute('aria-describedby');}
   if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
  }
  async function read(){
   request?.abort();request=new AbortController();const active=request,n=++sequence;retry.hidden=true;status.textContent='Membaca riwayat retur…';const timer=setTimeout(()=>active.abort(),20000);
   try{const response=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n))return;
    if(response.redirected||!response.ok)throw Error([401,403].includes(response.status)?'Sesi atau cakupan riwayat berubah. Muat ulang atau periksa pilihan gudang/supplier. Tidak ada perubahan transaksi.':'Riwayat belum dapat dibaca. Filter tetap tersedia; Coba lagi hanya membaca.');
    const body=await response.text();if(valid(n))install(new DOMParser().parseFromString(body,'text/html'));
   }catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Filter tetap tersedia; coba baca ulang.':e.message;retry.hidden=false;}}
   finally{clearTimeout(timer);if(request===active)request=null;}
  }
  retry.addEventListener('click',read);
  if(window.PINDAH)PINDAH.pasang(document,'click',e=>{const a=e.target.closest?.('a[href]');if(a&&!e.button&&!a.target&&!e.defaultPrevented&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey&&new URL(a.href,location.href).pathname+new URL(a.href,location.href).search!==address)stop();});
  read();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mulai,{once:true});else mulai();
})();
