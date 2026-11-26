/* Hanya pembacaan awal. Setelah siap, editor/penjaga keluar native mengambil alih. */
(function(){
 'use strict';
 const root=document.querySelector('[data-ku-shell]');if(!root||root.dataset.kuRead)return;root.dataset.kuRead='1';
 const address=location.pathname+location.search,context=root.dataset.kuContext,cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token,
  status=root.querySelector('[data-ku-status]'),retry=root.querySelector('[data-ku-retry]'),original=root.querySelector('[data-ku-original]'),form=root.querySelector('form'),start=root.padiMulaiKemasUlang;
 let sequence=0,request=null,done=false,abandoned=false,started=false;
 const lifetime=new AbortController();form.addEventListener('submit',e=>e.preventDefault(),{signal:lifetime.signal});
 function valid(n){return !done&&!abandoned&&root.isConnected&&sequence===n&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function stop(){if(done)return;abandoned=true;sequence++;request?.abort();retry.hidden=true;status.textContent='Pembacaan dihentikan. Tidak ada perubahan yang disimpan.';}
 const observer=new MutationObserver(()=>{if(!root.isConnected){stop();observer.disconnect();lifetime.abort();}});observer.observe(document.body,{childList:true,subtree:true});
 document.addEventListener('click',e=>{if(done||e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(!a||a.target||a.hasAttribute('download')||a.getAttribute('href').startsWith('#'))return;const u=new URL(a.href,location.href);if(u.pathname+u.search!==address)stop();},{capture:true,signal:lifetime.signal});
 window.addEventListener('popstate',stop,{signal:lifetime.signal});window.addEventListener('beforeunload',stop,{signal:lifetime.signal});
 function pasang(doc,hadFocus){
  const fresh=doc.querySelector('[data-kemas-ulang]'),frame=doc.querySelector('.bingkai'),names=['sumber_id','jumlah_asal','kemasan','merk','jumlah_baru','setuju'];
  if(!fresh||fresh.querySelector('script')||typeof start!=='function'||doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==address||doc.getElementById('formulir-sesi')?.dataset.token!==token||fresh.querySelector('h1')?.textContent!=='Kemas ulang')throw Error('Konteks formulir berubah. Buka kembali Kemas ulang sebelum mengisi.');
  const sourceForm=fresh.querySelector('form');
  for(const name of names){const a=form.elements.namedItem(name),b=sourceForm?.elements.namedItem(name);if(!a||!b||a.tagName!==b.tagName||a.type!==b.type)throw Error('Struktur formulir berubah. Buka formulir asli sebelum mengisi.');}
  for(const selector of ['[data-kemasan-kosong]','[data-saldo-kemasan]','[data-preview]','[data-hasil]','[data-selesai]','[data-periksa-stok]','button[type=submit]','details>ul'])if(!fresh.querySelector(selector)||!root.querySelector(selector))throw Error('Struktur formulir belum lengkap.');
  const back=fresh.querySelector(':scope>a'),identity=fresh.querySelector(':scope>p'),focus=document.activeElement;
  if(!back||!identity||!window.PINDAH?.selaraskanChrome(doc))throw Error('Navigasi atau akses berubah. Buka kembali formulir.');
  root.dataset.kembaliStok=fresh.dataset.kembaliStok||'';
  const anchor=root.querySelector('[data-ku-back]');anchor.href=back.href;anchor.textContent=back.textContent;anchor.setAttribute('data-utuh','');root.querySelector('[data-ku-identitas]').replaceChildren(...Array.from(identity.childNodes).map(n=>n.cloneNode(true)));
  for(const name of names){const a=form.elements.namedItem(name),b=sourceForm.elements.namedItem(name);if(a.tagName==='SELECT')a.replaceChildren(...Array.from(b.options).map(o=>o.cloneNode(true)));a.value=b.value;a.checked=b.checked;a.disabled=b.disabled;}
  for(const selector of ['[data-kemasan-kosong]','[data-saldo-kemasan]','[data-preview]','[data-hasil]','[data-selesai]','[data-periksa-stok]','button[type=submit]']){const a=root.querySelector(selector),b=fresh.querySelector(selector);a.textContent=b.textContent;a.hidden=b.hidden;if('disabled' in a)a.disabled=b.disabled;if(a.tagName==='A')a.href=b.href;}
  root.querySelector('details>ul').replaceChildren(...Array.from(fresh.querySelector('details>ul').childNodes).map(n=>n.cloneNode(true)));
  const empty=[...fresh.querySelectorAll(':scope>p')].find(p=>p.textContent==='Tidak ada stok bebas yang dapat dikemas ulang. Periksa reservasi pengiriman.'),target=root.querySelector('[data-ku-empty]');target.hidden=!empty;target.textContent=empty?.textContent||'';
  started=true;root.setAttribute('data-kemas-ulang','');lifetime.abort();start();if(root.dataset.siap!=='1')throw Error('Editor belum siap. Buka formulir asli sebelum mengisi.');
  done=true;root.dataset.kuLoaded='1';observer.disconnect();status.hidden=true;retry.hidden=true;original.hidden=true;
  if(focus===retry||hadFocus&&focus===document.body){const h=root.querySelector('h1');h.tabIndex=-1;h.focus({preventScroll:true});}else if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
 }
 async function baca(){
  if(started||abandoned||done)return;request?.abort();const ctrl=new AbortController();request=ctrl;const n=++sequence,hadFocus=document.activeElement===retry,timer=setTimeout(()=>ctrl.abort(),20000);retry.disabled=true;status.textContent='Memeriksa akses dan pilihan stok. Belum ada perubahan yang disimpan.';
  try{const r=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n))return;if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)?'Akses Kemas ulang belum tersedia untuk sesi ini. Kembali ke halaman yang diizinkan.':'Formulir belum dapat dibaca. Coba lagi hanya membaca data.');const html=await r.text();if(valid(n))pasang(new DOMParser().parseFromString(html,'text/html'),hadFocus);}
  catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Anda tetap dapat kembali; coba lagi hanya membaca.':e.message;retry.hidden=started;retry.disabled=false;if(started){form.querySelectorAll('input,select,button').forEach(x=>x.disabled=true);original.href=address;original.hidden=false;}}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 retry.addEventListener('click',baca);baca();
})();
