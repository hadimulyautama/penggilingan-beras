/* Pembaca pintu perbaikan saja; POST tetap milik engine native yang dipin. */
(function(){
 'use strict';
 const root=document.querySelector('[data-pp-shell]');if(!root||root.dataset.ppRead)return;root.dataset.ppRead='1';
 const address=location.pathname+location.search,context=root.dataset.ppContext,actor=root.dataset.ppActor,cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token,
  status=root.querySelector('#pp-baca-status'),retry=root.querySelector('[data-pp-retry]'),original=root.querySelector('[data-pp-original]'),start=root.padiMulaiPerbaikan;
 let sequence=0,request=null,done=false,abandoned=false,started=false;
 const lifetime=new AbortController();
 function valid(n){return !done&&!abandoned&&root.isConnected&&sequence===n&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function stop(){if(done)return;abandoned=true;sequence++;request?.abort();retry.hidden=true;status.textContent='Pembacaan dihentikan. Tidak ada perbaikan yang disimpan.';}
 const observer=new MutationObserver(()=>{if(!root.isConnected){stop();observer.disconnect();lifetime.abort();}});observer.observe(document.body,{childList:true,subtree:true});
 document.addEventListener('click',e=>{if(done||e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(!a||a.target||a.hasAttribute('download')||a.getAttribute('href').startsWith('#'))return;const u=new URL(a.href,location.href);if(u.pathname+u.search!==address)stop();},{capture:true,signal:lifetime.signal});
 window.addEventListener('popstate',stop,{signal:lifetime.signal});window.addEventListener('beforeunload',stop,{signal:lifetime.signal});
 function pasang(doc,hadFocus){
  const fresh=doc.querySelector('[data-pp-native]'),frame=doc.querySelector('.bingkai'),parts=fresh?.querySelector('.pp-susunan'),forms=fresh?.querySelectorAll('form');
  if(!fresh||!frame||!parts||parts.children.length!==2||parts.children[0].tagName!=='DIV'||parts.children[1].tagName!=='ASIDE'||fresh.querySelector('script')||forms.length>1||typeof start!=='function'||fresh.dataset.ppRecord!==root.dataset.ppTarget||fresh.dataset.ppActor!==actor||doc.documentElement.dataset.versi!==cap||frame.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==address||doc.getElementById('formulir-sesi')?.dataset.token!==token||fresh.querySelector('h1')?.textContent!==root.querySelector('h1').textContent)throw Error('Konteks perbaikan berubah. Buka kembali pengiriman yang benar sebelum mengisi.');
  const form=forms[0];if(form&&(form.dataset.url!=='/api/actions/perbaikan-pengiriman/'+root.dataset.ppTarget+'/buka-ulang'||!Number.isSafeInteger(Number(form.dataset.log))||Number(form.dataset.log)<1||!form.matches('[data-perbaikan-pengiriman]')||!form.querySelector('[name="alasan"]')||!form.querySelector('[name="konfirmasi"]')))throw Error('Langkah perbaikan belum dapat diperiksa. Buka halaman asli sebelum mengisi.');
  const summary=[...fresh.children].find(n=>n.tagName==='P'),back=fresh.querySelector(':scope > a');if(!summary||!back)throw Error('Struktur perbaikan berubah. Buka halaman asli.');
  const menu=doc.querySelector('#laci a.pintu[href="/barang-keluar"]');if(menu)for(const a of doc.querySelectorAll('#laci a.pintu')){a.classList.toggle('pintu--kini',a===menu);if(a===menu)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Navigasi atau akses berubah. Buka kembali perbaikan.');
  const focus=document.activeElement,clients=root.querySelector('[data-pp-clients]'),step=root.querySelector('[data-pp-step]');
  root.querySelector('[data-pp-back]').href=back.getAttribute('href');root.querySelector('[data-pp-summary]').replaceChildren(...summary.childNodes);clients.replaceChildren(...parts.children[0].childNodes);step.replaceChildren(...parts.children[1].childNodes);root.dataset.ppRecord=fresh.dataset.ppRecord;root.setAttribute('data-pp-native','');
  started=true;start();if(form&&!root.querySelector('[data-perbaikan-pengiriman][data-siap="1"]'))throw Error('Formulir belum siap. Buka halaman asli sebelum melanjutkan.');
  root.dataset.ppLoaded='1';done=true;observer.disconnect();lifetime.abort();status.hidden=true;retry.hidden=true;original.hidden=true;
  if(focus===retry||hadFocus&&focus===document.body){const h=root.querySelector('h1');h.tabIndex=-1;h.focus({preventScroll:true});}else if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
 }
 async function baca(){
  if(started||abandoned||done)return;request?.abort();const ctrl=new AbortController();request=ctrl;const n=++sequence,hadFocus=document.activeElement===retry,timer=setTimeout(()=>ctrl.abort(),20000);retry.disabled=true;status.textContent='Memeriksa akses dan membaca pengiriman. Belum ada tindakan yang dapat disimpan.';
  try{const r=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n))return;if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)?'Akses Perbaikan pengiriman belum tersedia untuk sesi ini. Kembali ke halaman yang diizinkan.':r.status===404?'Pengiriman tidak ditemukan untuk pilihan ini. Tidak ada perbaikan yang disimpan.':'Perbaikan belum dapat dibaca. Coba lagi hanya membaca status.');const html=await r.text();if(valid(n))pasang(new DOMParser().parseFromString(html,'text/html'),hadFocus);}
  catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Anda tetap dapat kembali; coba lagi hanya membaca.':e.message;retry.hidden=started;retry.disabled=false;if(started){root.querySelectorAll('input,textarea,select,button').forEach(x=>x.disabled=true);original.href=address;original.hidden=false;}}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 retry.addEventListener('click',baca);baca();
})();
