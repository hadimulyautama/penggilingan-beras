/* Handler native menentukan baris, pemilik, lokasi, urutan dan halaman. */
(function(){
 'use strict';
 function mulai(){
  const root=document.querySelector('[data-karung-detail-shell]');if(!root||root.dataset.kdReady)return;root.dataset.kdReady='1';
  const status=root.querySelector('#karung-detail-status'),retry=root.querySelector('[data-karung-detail-retry]'),context=root.dataset.karungContext,cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token||'',address=location.pathname+location.search;
  let request=null,sequence=0,done=false;
  function valid(n){return !done&&root.isConnected&&n===sequence&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
  function stop(){sequence++;request?.abort();observer.disconnect();}
  const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
  function install(doc){
   const next=doc.querySelector('[data-karung-detail-native]'),frame=doc.querySelector('.bingkai'),freshPanel=next?.querySelector('section'),panel=root.querySelector('section'),freshList=freshPanel?.querySelector('.daftar-standar'),list=panel.querySelector('.daftar-standar');
   if(!next||next.querySelector('form,script,[data-kepemilikan-sumber]')||!freshPanel||!freshList||doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==address||doc.getElementById('formulir-sesi')?.dataset.token!==token)throw Error('Konteks sumber karung berubah. Muat ulang untuk memeriksa akses.');
   const title=root.querySelector('h1'),freshTitle=next.querySelector('h1'),heading=panel.querySelector('h2'),freshHeading=freshPanel.querySelector('h2'),identity=next.querySelector('h1+p'),pager=panel.querySelector('nav'),freshPager=freshPanel.querySelector('nav');
   if(freshTitle?.textContent!==title.textContent||freshHeading?.textContent!==heading.textContent||!identity)throw Error('Struktur sumber karung belum lengkap. Coba lagi.');
   const focus=document.activeElement;
   if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Konteks navigasi berubah. Muat ulang halaman.');
   // Native menyelaraskan ulang crumbrow. Bila Kembali sedang difokuskan
   // dan tujuannya sama, pertahankan node itu agar keyboard tidak jatuh ke body.
   if(focus?.matches('a.desktop-back')&&!focus.isConnected){const back=document.querySelector('a.desktop-back');if(back&&!back.hidden&&back.href===focus.href)back.replaceWith(focus);}
   root.querySelector('[data-karung-identity]').replaceChildren(...identity.childNodes);
   list.replaceChildren(...freshList.childNodes);freshList.replaceWith(list);freshHeading.replaceWith(heading);
   pager.hidden=!freshPager;if(freshPager)pager.replaceChildren(...freshPager.childNodes);else pager.replaceChildren();if(freshPager)freshPager.replaceWith(pager);else freshPanel.append(pager);
   panel.replaceChildren(...freshPanel.childNodes);root.querySelector('[data-karung-detail-state]').remove();root.removeAttribute('data-karung-detail-shell');root.setAttribute('data-karung-detail-native','');root.dataset.halamanIsi='karung-detail';done=true;observer.disconnect();
   if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
  }
  async function read(){
   request?.abort();request=new AbortController();const active=request,n=++sequence;status.textContent='Membaca sumber karung…';retry.hidden=true;const timer=setTimeout(()=>active.abort(),20000);
   try{const response=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n))return;
    if(response.redirected||!response.ok)throw Error([401,403].includes(response.status)?'Sesi atau hak baca karung berubah. Muat ulang untuk memeriksa akses.':[404,409,422].includes(response.status)?'Sumber karung belum tersedia untuk pilihan ini. Buka kembali daftar stok. Tidak ada perubahan yang disimpan.':'Sumber karung belum dapat dibaca. Coba lagi hanya membaca.');
    const body=await response.text();if(valid(n))install(new DOMParser().parseFromString(body,'text/html'));
   }catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Sumber karung belum tersedia.':e.message;retry.hidden=false;}}
   finally{clearTimeout(timer);if(request===active)request=null;}
  }
  retry.addEventListener('click',read);
  if(window.PINDAH)PINDAH.pasang(document,'click',e=>{const a=e.target.closest?.('a[href]');if(a&&!e.button&&!a.target&&!e.defaultPrevented&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey&&new URL(a.href,location.href).pathname+new URL(a.href,location.href).search!==address)stop();});
  read();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mulai,{once:true});else mulai();
})();
