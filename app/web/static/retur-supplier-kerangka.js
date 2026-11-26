/* Empat tab baca; data, tindakan dan izin selalu dari handler native. */
(function(){
 'use strict';
 function mulai(){
  const root=document.querySelector('[data-rsd-shell]');if(!root||root.dataset.rsdPending)return;root.dataset.rsdPending='1';
  const status=root.querySelector('#rsd-baca-status'),retry=root.querySelector('[data-rsd-retry]'),context=root.dataset.rsdContext,cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token||'',address=location.pathname+location.search;
  const nativeCode=root.querySelector('[data-rsd-native]').textContent;
  let request=null,sequence=0,done=false;
  function valid(n){return !done&&root.isConnected&&n===sequence&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
  function stop(){sequence++;request?.abort();observer.disconnect();}
  const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
  // Keyboard memilih tab melalui navigator dan guard draf yang sama.
  function keyboard(e){const a=e.target.closest('[role="tab"]');if(!a||!['ArrowRight','ArrowLeft','Home','End'].includes(e.key))return;const tabs=[...root.querySelectorAll('.rsh-tabs [role="tab"]')],i=tabs.indexOf(a);if(i<0)return;e.preventDefault();const target=tabs[e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length];target.focus();target.click();}
  const nav=root.querySelector('.rsh-tabs');nav.addEventListener('keydown',keyboard);
  if(root.dataset.rsdFocusTab==='1')nav.querySelector('[aria-selected="true"]')?.focus({preventScroll:true});
  function install(doc){
   const next=doc.querySelector('[data-riwayat-retur-supplier]'),frame=doc.querySelector('.bingkai'),freshPanel=next?.querySelector('#rsd-panel'),panel=root.querySelector('#rsd-panel'),freshNav=next?.querySelector('.rsh-tabs');
   if(!next||next.querySelector('form,script')||!freshPanel||!freshNav||next.dataset.rsdId!==root.dataset.rsdId||next.dataset.rsdTab!==root.dataset.rsdTab||doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==address||doc.getElementById('formulir-sesi')?.dataset.token!==token)throw Error('Konteks retur berubah. Muat ulang untuk memeriksa akses.');
   const header=root.querySelector('.rhs-header'),freshHeader=next.querySelector('.rhs-header'),title=header.querySelector('h1'),freshTitle=freshHeader?.querySelector('h1'),back=root.querySelector('.rsp-kembali'),freshBack=next.querySelector('.rsp-kembali'),guide=root.querySelector('#rsd-panduan');
   const tabs=[...nav.querySelectorAll('[role="tab"]')],freshTabs=[...freshNav.querySelectorAll('[role="tab"]')];
   if(!freshTitle||freshTitle.textContent!==title.textContent||!freshBack||freshTabs.length!==4||tabs.some((a,i)=>a.id!==freshTabs[i].id||a.getAttribute('aria-selected')!==freshTabs[i].getAttribute('aria-selected'))||freshPanel.getAttribute('aria-labelledby')!==panel.getAttribute('aria-labelledby'))throw Error('Struktur rincian belum lengkap. Coba lagi hanya membaca.');
   const focus=document.activeElement;
   if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Konteks navigasi berubah. Muat ulang halaman.');
   if(focus?.matches('a.desktop-back')&&!focus.isConnected){const b=document.querySelector('a.desktop-back');if(b&&!b.hidden&&b.href===focus.href)b.replaceWith(focus);}
   // Pertahankan h1, kontrol tab, panel dan dialog panduan yang sedang terbuka.
   freshTitle.replaceWith(title);header.replaceChildren(...freshHeader.childNodes);freshHeader.replaceWith(header);
   tabs.forEach((a,i)=>{a.setAttribute('href',freshTabs[i].getAttribute('href'));});freshNav.replaceWith(nav);nav.removeEventListener('keydown',keyboard);
   back.setAttribute('href',freshBack.getAttribute('href'));freshBack.replaceWith(back);
   panel.replaceChildren(...freshPanel.childNodes);freshPanel.replaceWith(panel);const content=root.querySelector('.rsd-content'),freshContent=next.querySelector('.rsd-content');content.replaceChildren(...freshContent.childNodes);freshContent.replaceWith(content);
   next.querySelector('#rsd-panduan')?.remove();
   // Dialog terbuka tetap terhubung; node kontrol dipindahkan, bukan disalin.
   for(const child of [...root.childNodes])if(child!==guide&&!(child.nodeType===1&&child.matches('style[data-rsd-style]')))child.remove();
   for(const child of [...next.childNodes])root.insertBefore(child,guide);
   for(const print of document.querySelectorAll('[data-lk-cetak][aria-describedby="rsd-baca-status"]')){const original=doc.querySelector('[data-lk-cetak]');print.disabled=!original||original.disabled;print.removeAttribute('aria-describedby');}
   root.removeAttribute('data-rsd-shell');root.setAttribute('data-riwayat-retur-supplier','');root.dataset.halamanIsi='rsd-detail';done=true;observer.disconnect();
   const script=document.createElement('script');script.textContent=nativeCode;root.append(script);
   if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
  }
  async function read(){
   request?.abort();request=new AbortController();const active=request,n=++sequence;status.textContent='Membaca rincian retur…';retry.hidden=true;const timer=setTimeout(()=>active.abort(),20000);
   try{const response=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n))return;
    if(response.redirected||!response.ok)throw Error([401,403].includes(response.status)?'Sesi atau hak baca retur berubah. Muat ulang untuk memeriksa akses.':response.status===404?'Rincian retur belum tersedia untuk pilihan ini. Buka kembali daftar riwayat. Tidak ada perubahan yang disimpan.':'Rincian retur belum dapat dibaca. Coba lagi hanya membaca.');
    const body=await response.text();if(valid(n))install(new DOMParser().parseFromString(body,'text/html'));
   }catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Rincian retur belum tersedia.':e.message;retry.hidden=false;}}
   finally{clearTimeout(timer);if(request===active)request=null;}
  }
  retry.addEventListener('click',read);
  if(window.PINDAH)PINDAH.pasang(document,'click',e=>{const a=e.target.closest?.('a[href]');if(a&&!e.button&&!a.target&&!e.defaultPrevented&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey&&new URL(a.href,location.href).pathname+new URL(a.href,location.href).search!==address)stop();});
  read();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mulai,{once:true});else mulai();
})();
