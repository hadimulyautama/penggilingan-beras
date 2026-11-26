/* Hanya fase baca sebelum editor native hidup; tidak menyimpan atau retry POST. */
(function(){
 'use strict';
 const root=document.querySelector('[data-muatan-shell]');if(!root||root.dataset.mrReadReady)return;root.dataset.mrReadReady='1';
 const address=location.pathname+location.search,context=root.dataset.muatanContext,actor=root.dataset.actor,cap=document.documentElement.dataset.versi,
  token=document.getElementById('formulir-sesi')?.dataset.token,status=root.querySelector('#muatan-baca-status'),retry=root.querySelector('[data-muatan-retry]'),start=root.padiMulaiMuatan;
 let sequence=0,request=null,done=false,abandoned=false,started=false;
 const lifetime=new AbortController();
 function valid(n){return !done&&!abandoned&&root.isConnected&&n===sequence&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function stop(){if(done)return;abandoned=true;sequence++;request?.abort();retry.hidden=true;if(root.isConnected)status.textContent='Pembacaan Muatan dihentikan karena berpindah halaman. Tidak ada catatan yang disimpan.';}
 const observer=new MutationObserver(()=>{if(!root.isConnected){stop();observer.disconnect();lifetime.abort();}});observer.observe(document.body,{childList:true,subtree:true});
 // URL belum tentu berubah ketika HTML tujuan lain masih tertahan. Hentikan
 // baca sejak niat meninggalkan kerangka; jangan membuka editor dari balasan lama.
 document.addEventListener('click',e=>{if(done||e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(!a||a.target||a.hasAttribute('download')||a.getAttribute('href').startsWith('#'))return;const u=new URL(a.href,location.href);if(u.pathname+u.search!==address)stop();},{capture:true,signal:lifetime.signal});
 window.addEventListener('popstate',stop,{signal:lifetime.signal});window.addEventListener('beforeunload',stop,{signal:lifetime.signal});
 function pasang(doc){
  const fresh=doc.querySelector('[data-lembar-muatan][data-tahap="catat"]'),frame=doc.querySelector('.bingkai'),json=doc.getElementById('lembar-awal'),area=root.querySelector('[data-lembar-isi]');
  if(!fresh||!json||!area||typeof start!=='function'||fresh.querySelector('script,form')||doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==address||doc.getElementById('formulir-sesi')?.dataset.token!==token||fresh.dataset.actor!==actor||!['0','1'].includes(fresh.dataset.boleh)||fresh.dataset.perintah!==(root.dataset.muatanTarget||''))throw Error('Konteks sesi, perintah, gudang, atau versi aplikasi berubah. Buka kembali Muatan sebelum mengisi.');
  const data=JSON.parse(json.textContent);if(!data||!Array.isArray(data.kiriman)||data.kiriman.length>500||document.getElementById('lembar-awal'))throw Error('Data muatan belum lengkap. Coba baca lagi sebelum mengisi.');
  if(root.querySelector('h1').textContent!==fresh.querySelector('h1')?.textContent)throw Error('Struktur formulir berubah. Buka kembali halaman Muatan.');
  if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Navigasi atau akses berubah. Buka kembali Muatan.');
  const focus=document.activeElement;
  // Hanya atribut/data hasil GET native dipasang. H1, petunjuk dan slot pesan
  // tetap; editor asli sendiri yang merakit baris/item setelah otoritas selesai.
  for(const attr of fresh.attributes)root.setAttribute(attr.name,attr.value);
  root.removeAttribute('data-muatan-shell');area.replaceChildren();
  const initial=document.createElement('script');initial.type='application/json';initial.id='lembar-awal';initial.textContent=json.textContent;root.after(initial);
  started=true;start();
  if(root.dataset.ready!=='1'||typeof root.pfCanNavigateRead!=='function')throw Error('Editor belum siap. Muat ulang halaman asli sebelum mengisi.');
  status.hidden=true;retry.hidden=true;root.querySelector('[data-muatan-read-state]').setAttribute('data-muatan-navigation','');root.dataset.muatanLoaded='1';done=true;observer.disconnect();lifetime.abort();
  if(focus===retry){const title=root.querySelector('h1');title.tabIndex=-1;title.focus({preventScroll:true});}
  else if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
 }
 async function baca(){
  if(started||abandoned||done)return;
  request?.abort();const ctrl=new AbortController();request=ctrl;const n=++sequence,timer=setTimeout(()=>ctrl.abort(),20000);retry.disabled=true;retry.textContent='Membaca…';status.textContent='Memeriksa akses dan membaca muatan. Belum ada tindakan yang dapat disimpan.';
  try{const r=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n))return;
   if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)?'Akses Muatan belum tersedia untuk sesi ini. Kembali ke halaman yang diizinkan. Tidak ada catatan yang disimpan.':[404,409,422].includes(r.status)?'Perintah tidak tersedia pada pilihan ini. Buka kembali pengiriman yang benar. Tidak ada catatan yang disimpan.':'Muatan belum dapat dibaca. Coba lagi hanya membaca data.');
   const html=await r.text();if(valid(n))pasang(new DOMParser().parseFromString(html,'text/html'));
  }catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan muatan terlalu lama. Coba lagi hanya membaca; Anda tetap dapat kembali.':e.message;retry.hidden=started;retry.disabled=false;retry.textContent='Coba lagi';if(started)for(const field of root.querySelectorAll('input,button,select,textarea'))field.disabled=true;}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 retry.addEventListener('click',baca);baca();
})();
