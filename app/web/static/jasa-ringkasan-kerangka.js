/* Identitas dan saldo hanya dari respons native yang cocok dengan sesi/tujuan. */
(function(){
 'use strict';
 const root=document.querySelector('[data-jd-shell]');if(!root||root.dataset.jdRead)return;root.dataset.jdRead='1';
 const address=location.pathname+location.search,context=root.dataset.jdContext,cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token,
  controls=document.querySelector('[data-jd-controls]'),status=document.getElementById('jd-baca-status'),retry=document.querySelector('[data-jd-retry]'),original=document.querySelector('[data-jd-original]');
 let sequence=0,request=null,done=false,abandoned=false,started=false;
 const life=new AbortController();
 function valid(n){return !done&&!abandoned&&root.isConnected&&n===sequence&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function stop(){if(done)return;abandoned=true;sequence++;request?.abort();retry.hidden=true;status.textContent='Pembacaan dihentikan. Tidak ada perubahan yang disimpan.';}
 const observer=new MutationObserver(()=>{if(!root.isConnected){stop();observer.disconnect();life.abort();}});observer.observe(document.body,{childList:true,subtree:true});
 document.addEventListener('click',e=>{if(done||e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.altKey||e.shiftKey)return;const a=e.target.closest('a[href]');if(!a||a.target||a.hasAttribute('download')||a.getAttribute('href').startsWith('#'))return;const u=new URL(a.href,location.href);if(u.pathname+u.search!==address)stop();},{capture:true,signal:life.signal});
 window.addEventListener('popstate',stop,{signal:life.signal});window.addEventListener('beforeunload',stop,{signal:life.signal});
 async function read(){
  if(done||abandoned)return;request?.abort();const ctrl=new AbortController();request=ctrl;const n=++sequence,hadFocus=document.activeElement===retry,timer=setTimeout(()=>ctrl.abort(),20000);retry.disabled=true;status.textContent='Memeriksa akses dan membaca Ringkasan pelanggan. Tidak ada perubahan yang disimpan.';
  try{
   const r=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','X-Jasa-Ringkasan-Data':'1','Accept':'text/html'}});if(!valid(n))return;
   if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)?'Akses Ringkasan pelanggan belum tersedia untuk sesi ini. Kembali ke halaman yang diizinkan.':r.status===404?'Ringkasan pelanggan tidak ditemukan pada konteks ini. Anda dapat kembali; Coba lagi hanya membaca.':'Ringkasan pelanggan belum dapat dibaca. Coba lagi hanya membaca tujuan yang sedang dibuka.');
   const text=await r.text();if(!valid(n))return;const doc=new DOMParser().parseFromString(text,'text/html'),frame=doc.querySelector('.bingkai');
   if(doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==address||doc.getElementById('formulir-sesi')?.dataset.token!==token||!doc.querySelector('.jasa-detail #pesanan-pelanggan'))throw Error('Konteks sesi atau pelanggan berubah. Buka kembali Ringkasan sebelum melanjutkan.');
   if(!started){root.padiMulaiRingkasan();started=true;}
   if(typeof root.padiIsiRingkasan!=='function')throw Error('Pembaca Ringkasan belum siap. Buka halaman asli sebelum melanjutkan.');
   const focus=document.activeElement,main=document.getElementById('isi-halaman'),focusTop=root.contains(focus)?focus.getBoundingClientRect().top:null;
   root.padiIsiRingkasan(doc,address);root.dataset.jdLoaded='1';done=true;observer.disconnect();life.abort();controls.hidden=true;
   // Isi yang baru datang boleh menambah tinggi di atas kontrol yang dibaca.
   // Jaga posisi kontrol fokus, bukan menyimpan angka gulir halaman lama.
   if(main&&focusTop!==null&&focus.isConnected&&document.activeElement===focus)main.scrollTop+=focus.getBoundingClientRect().top-focusTop;
   if(hadFocus){const h=root.querySelector('h1');h.tabIndex=-1;h.focus({preventScroll:true});}
  }catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan Ringkasan terlalu lama. Anda tetap dapat berpindah; Coba lagi hanya membaca.':e.message;retry.hidden=false;retry.disabled=false;if(started){original.href=address;original.hidden=false;}}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 retry.addEventListener('click',read);read();
})();
