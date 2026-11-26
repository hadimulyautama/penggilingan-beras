/* Pembukaan baca saja. Sesudah akses segar, editor dan penjaga draf tetap native. */
(function(){
 'use strict';
 const root=document.querySelector('[data-pj-shell]');if(!root||root.dataset.pjRead)return;root.dataset.pjRead='1';
 const address=location.pathname+location.search,context=root.dataset.pjContext,cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token,
  status=document.getElementById('pj-baca-status'),retry=document.querySelector('[data-pj-retry]'),native=document.querySelector('[data-pj-native-original]'),form=root.querySelector('form'),start=root.padiMulaiPengambilan;
 let sequence=0,request=null,done=false,abandoned=false,started=false;
 const lifetime=new AbortController();
 form.addEventListener('submit',e=>e.preventDefault(),{signal:lifetime.signal});
 root.pfCanNavigateRead=()=>!started;
 root.querySelectorAll('input,textarea,select,button').forEach(x=>x.disabled=true);
 const group=root.querySelector('#draf-kelompok');
 for(const [tag,label] of [['textarea','Pilih pemilik barang'],['select','Barang'],['input','Jumlah yang diambil']]){const wrap=document.createElement('label');wrap.textContent=label;const field=document.createElement(tag);field.className='fld';field.disabled=true;field.setAttribute('aria-label',label);if(tag==='select')field.add(new Option('Pilihan menunggu pemeriksaan akses',''));if(tag==='input')field.type='number';wrap.append(field);group.append(wrap);}
 root.querySelector('#draf-status').textContent='Pilihan belum dibaca. Tunggu pemeriksaan akses sebelum mengisi.';
 function valid(n){return !done&&!abandoned&&root.isConnected&&sequence===n&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function stop(){if(done)return;abandoned=true;sequence++;request?.abort();retry.hidden=true;status.textContent='Pembacaan dihentikan. Belum ada draf atau perintah yang disimpan.';}
 const observer=new MutationObserver(()=>{if(!root.isConnected){stop();observer.disconnect();lifetime.abort();}});observer.observe(document.body,{childList:true,subtree:true});
 document.addEventListener('click',e=>{if(done||e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(!a||a.target||a.hasAttribute('download')||a.getAttribute('href').startsWith('#'))return;const u=new URL(a.href,location.href);if(u.pathname+u.search!==address)stop();},{capture:true,signal:lifetime.signal});
 window.addEventListener('popstate',stop,{signal:lifetime.signal});window.addEventListener('beforeunload',stop,{signal:lifetime.signal});
 function pasang(doc,hadFocus){
  const fresh=doc.querySelector('[data-editor-perintah][data-jenis="jasa"]'),json=doc.getElementById('draf-awal'),frame=doc.querySelector('.bingkai'),old=document.getElementById('draf-awal');
  if(!fresh||!json||!old||!frame||typeof start!=='function'||doc.documentElement.dataset.versi!==cap||frame.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==address||doc.getElementById('formulir-sesi')?.dataset.token!==token||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(fresh.dataset.editorPerintah)||fresh.querySelector('script')||fresh.querySelector('h1')?.textContent!==root.querySelector('h1').textContent)throw Error('Konteks formulir berubah. Buka kembali Pengambilan barang jasa sebelum mengisi.');
  const data=JSON.parse(json.textContent),pid=new URL(location.href).searchParams.get('pelanggan_id')||'';
  if(data.revisi!==0||Object.keys(data).sort().join(',')!=='isi,revisi'||!data.isi||Object.keys(data.isi).sort().join(',')!=='jenis,pelanggan'||data.isi.jenis!=='jasa'||data.isi.pelanggan!==pid)throw Error('Data awal formulir belum sesuai. Tidak ada draf yang disimpan.');
  for(const id of ['draf-metode','draf-armada','draf-nopol','draf-ekspedisi','draf-catatan','draf-terbitkan'])if(!fresh.querySelector('#'+id)||!root.querySelector('#'+id))throw Error('Struktur formulir berubah. Buka formulir asli sebelum mengisi.');
  if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Navigasi atau akses berubah. Buka kembali formulir.');
  const focus=document.activeElement;root.dataset.editorPerintah=fresh.dataset.editorPerintah;old.textContent=json.textContent;
  // Izin baca sementara tidak boleh terbawa ke editor: beforeunload native
  // tetap menjaga revisi, autosave gagal, konflik, dan penerbitan tak pasti.
  started=true;delete root.pfCanNavigateRead;root.querySelectorAll('input,textarea,select,button').forEach(x=>x.disabled=false);lifetime.abort();start();
  if(root.dataset.siap!=='1')throw Error('Editor belum siap. Buka formulir asli sebelum mengisi.');
  root.dataset.pjLoaded='1';done=true;observer.disconnect();status.hidden=true;retry.hidden=true;native.hidden=true;
  if(focus===retry||hadFocus&&focus===document.body){const h=root.querySelector('h1');h.tabIndex=-1;h.focus({preventScroll:true});}else if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
 }
 async function baca(){
  if(started||abandoned||done)return;request?.abort();const ctrl=new AbortController();request=ctrl;const n=++sequence,hadFocus=document.activeElement===retry,timer=setTimeout(()=>ctrl.abort(),20000);retry.disabled=true;status.textContent='Memeriksa akses sebelum formulir dapat diisi. Belum ada draf yang disimpan.';
  try{const r=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n))return;if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)?'Akses Pengambilan barang jasa belum tersedia untuk sesi ini. Kembali ke halaman yang diizinkan.':'Formulir belum dapat dibaca. Coba lagi hanya membaca data.');const html=await r.text();if(valid(n))pasang(new DOMParser().parseFromString(html,'text/html'),hadFocus);}
  catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Anda tetap dapat kembali; coba lagi hanya membaca.':e.message;retry.hidden=started;retry.disabled=false;if(started){root.querySelectorAll('input,textarea,select,button').forEach(x=>x.disabled=true);native.href=address;native.hidden=false;}}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 retry.addEventListener('click',baca);baca();
})();
