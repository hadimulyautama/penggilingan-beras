/* Native structures register before data. Read filters, current context and
 * action/draft guards keep their native owners; this adapter never posts. */
(function(){
 'use strict';
 const binding=document.currentScript?.dataset.konteks||'';
 const schema=document.currentScript?.dataset.daftar;
 if(schema&&!document.querySelector('[data-halaman-bertahap]')){
  const container=document.querySelector('[data-halaman-isi]')||document.getElementById('isi-halaman');
  if(window.PadiDaftarKosong)PadiDaftarKosong(container,JSON.parse(schema));
 }
 // Pendaftaran hanya tersedia pada paket baru. Paket hangat lama tetap
 // memakai kerangka generik dan HTML native; jangan memaksa navigasi utuh.
 function memakaiKerangka(alamat){
  const u=new URL(alamat,location.href);
  const histories=['/riwayat-giling','/riwayat-sosoh','/riwayat-pengeringan','/riwayat-qc/gabah-basah','/riwayat-qc/gabah-kering','/riwayat-qc/pk-luar','/riwayat-qc/pk-hasil-giling'];
  if(u.origin===location.origin&&histories.includes(u.pathname))return true;
  return u.origin===location.origin&&(['/audit','/kabar','/pengaturan','/pengaturan/sesi','/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping'].includes(u.pathname)||u.pathname.startsWith('/laporan/')||/^\/jasa\/pelanggan\/[1-9]\d*$/.test(u.pathname)||u.pathname==='/barang-masuk'||/^\/barang-masuk\/[1-9]\d*$/.test(u.pathname)||/^\/proses-aktif\/(?:giling|sosoh|pengeringan|pendinginan)\/[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(u.pathname)||u.pathname==='/jasa'||u.pathname==='/stok'||u.pathname==='/pekerjaan'||u.pathname==='/barang-keluar');
 }
 if(window.PINDAH&&typeof PINDAH.aturKerangkaHalaman==='function'){
  PINDAH.aturKerangkaHalaman(memakaiKerangka);
  // Hanya tab halaman native yang sudah direview. Penjaga editor, unduhan,
  // hash dan kontrol riwayat lain tetap milik PINDAH native.
  if(!document.querySelector('[data-editor-perintah],[data-kemas-ulang]')){
   document.querySelectorAll('.laporan-nav a[data-tab-riwayat][data-utuh]').forEach(function(link){
    if(memakaiKerangka(link.href))link.removeAttribute('data-utuh');
   });
  }
 }
 // Jika paket UI tidak tersedia/cocok, pertahankan GET dokumen native.
 // data-utuh dibaca penjaga PINDAH existing; tidak melewati penjaga editor.
 function nativeIfUIUnavailable(){
  const uiHost=document.getElementById('padi-kerangka-ui');let uiReady=false;
  try{const ui=JSON.parse(uiHost?.textContent||'null');uiReady=!!(ui&&ui.versi===1&&ui.sumber===window.PadiKerangkaUI?.sumber&&ui.cap===document.documentElement.dataset.versi&&ui.konteks===document.querySelector('.bingkai')?.dataset.pindahKonteks&&ui.sesi===document.getElementById('formulir-sesi')?.dataset.token);}catch(_){}
  let historyReady=false;
  try{const host=document.getElementById('padi-riwayat-kerangka'),data=JSON.parse(host?.textContent||'null');historyReady=!!(host?.isConnected&&data?.versi===1&&data.sumber===window.PadiKerangkaRiwayatUI?.sumber&&data.cap===document.documentElement.dataset.versi&&data.konteks===document.querySelector('.bingkai')?.dataset.pindahKonteks&&data.sesi===document.getElementById('formulir-sesi')?.dataset.token);}catch(_){}
  if(!historyReady)document.querySelectorAll('.laporan-nav a[href]').forEach(link=>{const u=new URL(link.href,location.href);if(u.origin===location.origin&&/^\/riwayat-(giling|sosoh|pengeringan|qc\/)/.test(u.pathname))link.setAttribute('data-utuh','');});
  if(!uiReady)document.querySelectorAll('a[href]').forEach(link=>{const u=new URL(link.href,location.href);if(u.origin===location.origin&&(['/barang-keluar','/jasa','/pengaturan/akun','/laporan'].includes(u.pathname)||u.pathname.startsWith('/proses-aktif/giling/')||u.pathname==='/stok'&&!document.getElementById('padi-stok-kerangka')))link.setAttribute('data-utuh','');});
 }
 // Parser awal belum mencapai laci/manifest di luar bingkai. Partial swap
 // sudah memiliki DOM lengkap; keduanya memeriksa dokumen yang benar.
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',nativeIfUIUnavailable,{once:true});else nativeIfUIUnavailable();
 const controls=document.querySelector('[data-stok-controls]');
 if(controls&&location.pathname==='/stok'){
  const u=new URL(controls.dataset.pelangganUrl,location.href);u.pathname='/api/halaman-bertahap/stok/html';controls.dataset.pelangganUrl=u.pathname+u.search;
  protectCustomerOptions(controls,binding);
 }
 function protectCustomerOptions(root,context){
  if(root.dataset.pelangganTerjaga)return;root.dataset.pelangganTerjaga='1';
  const form=root.querySelector('.sk-form-filter');if(!form)return;
  const owner=form.querySelector('[name=pemilik]'),warehouse=form.querySelector('[name=gudang]'),label=form.querySelector('[data-stok-pelanggan]'),select=label?.querySelector('select'),status=form.querySelector('[data-stok-pelanggan-status]');
  if(!owner||!warehouse||!select||!status)return;
  const token=document.getElementById('formulir-sesi')?.dataset.token||'';let sequence=0,load=null;
  function syncHidden(){const hidden=form.querySelector('input[type="hidden"][name="pelanggan_id"]');if(hidden){hidden.disabled=owner.value!=='jasa'||!select.disabled;if(!hidden.disabled)hidden.value=select.value;}}
  syncHidden();
  function valid(n){return root.isConnected&&n===sequence&&location.pathname==='/stok'&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
  async function read(){
   if(load)load.abort();const n=++sequence;label.hidden=owner.value!=='jasa';select.disabled=owner.value!=='jasa';status.hidden=true;
   syncHidden();if(owner.value!=='jasa')return;
   load=new AbortController();const current=load;select.disabled=true;syncHidden();status.hidden=false;status.textContent='Memuat pelanggan…';
   const timer=setTimeout(()=>current.abort(),20000);
   try{
    const url=new URL(root.dataset.pelangganUrl,location.href);url.searchParams.set('gudang',warehouse.value);
    const response=await fetch(url.pathname+url.search,{credentials:'same-origin',cache:'no-store',signal:current.signal});
    if(!valid(n))return;
    if(!response.ok||response.redirected||response.headers.get('X-Halaman-Konteks')!==context)throw Error('Konteks sesi atau gudang berubah. Muat ulang halaman untuk membaca pelanggan.');
    const doc=new DOMParser().parseFromString(await response.text(),'text/html'),source=doc.querySelector('.sk-form-filter [name=pelanggan_id]');
    if(!valid(n))return;
    if(!source||doc.getElementById('formulir-sesi')?.dataset.token!==token)throw Error('Pilihan pelanggan belum dapat dibaca untuk sesi ini. Muat ulang halaman.');
    const value=select.value;select.replaceChildren(...Array.from(source.options).map(o=>o.cloneNode(true)));select.value=value;if(select.selectedIndex<0)select.value='';select.disabled=false;syncHidden();status.hidden=true;
   }catch(e){if(valid(n)){select.disabled=true;syncHidden();status.textContent=e.name==='AbortError'?'Pembacaan pelanggan terlalu lama. Pilihan pelanggan tetap dipertahankan; periksa kembali sebelum menerapkan filter.':e.message;}}
   finally{clearTimeout(timer);if(load===current)load=null;}
  }
  // Listener capture menggantikan consumer pilihan pada dua route saja;
  // pilihan/izin dan POST tetap milik kode native.
  form.addEventListener('change',e=>{if(e.target!==owner&&e.target!==warehouse)return;e.stopImmediatePropagation();read();},true);
  const observer=new MutationObserver(()=>{if(!root.isConnected){++sequence;if(load)load.abort();observer.disconnect();}});observer.observe(document.body,{childList:true,subtree:true});
 }
})();
