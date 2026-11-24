/* Akun is the sole declared adopter here. URL is correlation, not permission. */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 if(!core)return;
 const ADDRESS='/pengaturan/akun';
 const messages={
  identity:'Sesi atau cakupan akun berubah. Muat ulang halaman untuk memeriksa akses.',
  structure:'Struktur akun belum dapat dibaca. Coba lagi.',
  response:'Akun belum dapat dibaca. Muat ulang halaman bila sesi atau akses berubah.',
  native:'Halaman akun native belum tersedia. Coba lagi tanpa mengirim perubahan.',
  styleVersion:'Versi gaya akun berubah. Muat ulang halaman.',style:'Gaya akun belum dapat dimuat. Coba lagi.',
  scriptType:'Kontrol akun belum dikenali. Muat ulang halaman.',scriptVersion:'Versi kontrol akun berubah. Muat ulang halaman.',
  script:'Kontrol akun belum dapat dimuat. Coba lagi.',loading:'Memuat data akun…',
  timeout:'Pembacaan akun terlalu lama. Isian belum dibuka; coba lagi hanya membaca data.'
 };
 // Preserve account's exported test contract; generic callers must declare
 // their own address/origin on the core rather than reusing this adapter.
 function sameIdentity(a,b){return core.sameIdentity(a,b,ADDRESS);}
 function createReader(ops){return core.createReader({...ops,address:ADDRESS,
  origin:typeof location==='object'?location.origin:'https://fixture.invalid',identityError:messages.identity});}
 const api={sameIdentity,createReader};
 if(typeof module==='object'&&module.exports){module.exports=api;return;}
 global.PF_AKUN_NATIVE=api;
 core.mount({address:ADDRESS,rootSelector:'[data-pengaturan-akun-kerangka]',
  statusSelector:'[data-akun-native-status]',retrySelector:'[data-akun-native-retry]',
  shellSelector:'[data-pengaturan-akun-kerangka],.halaman-memuat',
  contentAttribute:'data-akun-native-isi',messages,
  restoreFocus({focus,retry,content}){
   const next=focus===retry?content.querySelector('input[name=nama]'):focus.closest('a[href]')?Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===focus.closest('a[href]').getAttribute('href')):null;
   next?.focus({preventScroll:true});
  }
 });
})(typeof window==='undefined'?globalThis:window);
