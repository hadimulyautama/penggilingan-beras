/* Explicit seven-list GET adapter; no actor/role inference or transaction path. */
(function(global){
 'use strict';
 const PROCESS=['/riwayat-giling','/riwayat-sosoh','/riwayat-pengeringan'];
 const QC=['gabah-basah','gabah-kering','pk-luar','pk-hasil-giling'].map(k=>'/riwayat-qc/'+k);
 function allowed(address,origin){
  if(typeof address!=='string'||!address.startsWith('/')||address.startsWith('//'))return false;
  let u;try{u=new URL(address,origin);}catch(_){return false;}
  if(u.origin!==origin||u.hash||u.pathname+u.search!==address||u.search.length>2049)return false;
  if(QC.includes(u.pathname))return !u.search;
  const pairs=[...u.searchParams];return PROCESS.includes(u.pathname)&&(!u.search||pairs.length===1&&pairs[0][0]==='sebelum');
 }
 if(typeof module==='object'&&module.exports){module.exports={allowed};return;}
 const root=document.querySelector('[data-riwayat-daftar-native]');if(!root||!allowed(root.dataset.url,location.origin))return;
 global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-riwayat-daftar-native]',
  statusSelector:'[data-riwayat-native-status]',retrySelector:'[data-riwayat-native-retry]',
  messages:{loading:'Memuat catatan. Ringkasan dan jumlah belum dibaca.',
   response:'Catatan belum dapat dibaca. Muat ulang bila sesi atau akses berubah.',
   native:'Daftar native belum tersedia. Coba lagi hanya membaca data.',
   timeout:'Pembacaan daftar terlalu lama. Coba lagi hanya membaca data.'},
  restoreFocus({focus,retry,content}){if(focus===retry)content.querySelector('[data-lk-buka]')?.focus({preventScroll:true});}
 });
})(typeof window==='undefined'?globalThis:window);
