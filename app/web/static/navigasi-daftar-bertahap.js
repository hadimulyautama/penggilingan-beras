/* Bukan pengganti PINDAH: hanya dua daftar memakai dokumen kerangka cepat.
 * Pembacaan ulang X-Pindah tetap renderer native, termasuk filter pelanggan.
 */
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
  if(u.origin===location.origin&&/^\/jasa\/pelanggan\/[1-9]\d{0,9}$/.test(u.pathname)&&!u.hash&&u.searchParams.get('tab')==='penerimaan'&&[...u.searchParams.keys()].every(k=>['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status','rincian_halaman','rincian_cari'].includes(k)&&u.searchParams.getAll(k).length===1))return true;
  if(u.origin===location.origin&&/^\/jasa\/pelanggan\/[1-9]\d{0,9}$/.test(u.pathname)&&!u.hash&&u.searchParams.get('tab')==='proses'&&[...u.searchParams.keys()].every(k=>['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status','rincian_halaman','rincian_cari'].includes(k)&&u.searchParams.getAll(k).length===1))return true;
  if(u.origin===location.origin&&/^\/jasa\/pelanggan\/[1-9]\d{0,9}$/.test(u.pathname)&&!u.hash&&u.searchParams.get('tab')==='stok'&&[...u.searchParams.keys()].every(k=>['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status'].includes(k)&&u.searchParams.getAll(k).length===1))return true;
  if(u.origin===location.origin&&/^\/jasa\/pelanggan\/[1-9]\d{0,9}$/.test(u.pathname)&&!u.hash&&u.searchParams.get('tab')==='pengambilan'&&[...u.searchParams.keys()].every(k=>['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status'].includes(k)&&u.searchParams.getAll(k).length===1))return true;
  if(u.origin===location.origin&&/^\/jasa\/pelanggan\/[1-9]\d{0,9}$/.test(u.pathname)&&!u.hash&&(u.searchParams.get('tab')||'ringkasan')==='ringkasan'&&[...u.searchParams.keys()].every(k=>['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status'].includes(k)&&u.searchParams.getAll(k).length===1))return true;
  if(u.origin===location.origin&&u.pathname==='/stok-produk/kemas-ulang'&&!u.hash&&u.searchParams.has('sku_id')&&[...u.searchParams.keys()].every(k=>['sku_id','std_id','jasa_id','kembali_stok'].includes(k)&&u.searchParams.getAll(k).length===1))return true;
  if(u.origin===location.origin&&/^\/barang-keluar\/[1-9]\d*\/perbaikan$/.test(u.pathname)&&!u.hash&&[...u.searchParams.keys()].every(k=>['q','status','sejak','sebelum'].includes(k)&&u.searchParams.getAll(k).length===1))return true;
  if(u.origin===location.origin&&u.pathname==='/barang-keluar/pengambilan-jasa'&&!u.hash&&[...u.searchParams.keys()].every(k=>k==='pelanggan_id'&&u.searchParams.getAll(k).length===1))return true;
  if(u.origin===location.origin&&!u.hash&&/^\/barang-keluar\/[1-9]\d*$/.test(u.pathname)&&u.searchParams.get('rincian_perintah')==='1'&&!u.searchParams.has('buka')&&!u.searchParams.has('nilai'))return true;
   if(u.origin===location.origin&&!u.hash&&(['/muatan','/selesai-muat'].includes(u.pathname)||/^\/barang-keluar\/[1-9]\d*\/(muatan|selesai-muat)$/.test(u.pathname)))return true;
   if(u.origin===location.origin&&u.pathname==='/pekerjaan/catat-lain'&&!u.searchParams.has('buka')&&!u.searchParams.has('nilai')&&!u.hash)return true;
  if(u.origin===location.origin&&/^\/riwayat-qc\/(gabah-basah|gabah-kering|pk-hasil-giling|pk-luar|beras-hasil-sosoh)\/[\w-]+$/.test(u.pathname))return true;
  return u.origin===location.origin&&(u.pathname==='/stok/karung/detail'||u.pathname==='/riwayat-retur-supplier'||/^\/riwayat-retur-supplier\/[1-9]\d*$/.test(u.pathname)||u.pathname==='/barang-masuk'||/^\/barang-masuk\/[1-9]\d*$/.test(u.pathname)||u.pathname==='/jasa'||u.pathname==='/kabar'||u.pathname==='/laporan'||/^\/laporan\/[a-z_]+$/.test(u.pathname)||u.pathname==='/stok'||u.pathname==='/pekerjaan'||!u.search&&(['/','/riwayat-sosoh','/riwayat-giling','/riwayat-pengeringan'].includes(u.pathname)||/^\/riwayat-qc\/(gabah-basah|gabah-kering|pk-hasil-giling|pk-luar|beras-hasil-sosoh)$/.test(u.pathname)));
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
 // Badan baris mengikuti tautan detail yang sudah dirender native. Tidak
 // membentuk tujuan/izin sendiri atau membuka aksi verifikasi secara langsung.
 if(window.PINDAH)document.querySelectorAll('.keluar-daftar').forEach(scope=>{
  if(scope.dataset.keluarNavRead)return;scope.dataset.keluarNavRead='1';
  scope.addEventListener('click',e=>{
   if(e.defaultPrevented||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.target.closest('a,button,input,select,textarea,summary')||window.getSelection()?.toString()||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return;
   const row=e.target.closest('[data-detail-keluar]');if(!row||!scope.contains(row))return;
   const target=new URL(row.dataset.detailKeluar,location.href);
   if(target.origin!==location.origin||target.hash||!/^\/barang-keluar\/[1-9]\d*$/.test(target.pathname))return;
   const link=[...row.querySelectorAll('a[href]')].find(a=>a.href===target.href&&!a.target&&!a.hasAttribute('download'));
   if(!link)return;
   e.preventDefault();link.click();
  },true);
 });
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
