/* Registry hanya struktur native bagi konteks dokumen ini, bukan data/draf. */
(function(){
 'use strict';
 if(!window.PINDAH||typeof PINDAH.aturKerangkaLangsung!=='function')return;
 let hostLama=null,registry=null;
 PINDAH.aturKerangkaLangsung(function(pilihan){
  // Script dapat diparse sebelum host di luar bingkai. Cari saat dipakai,
  // bukan membekukan null saat dokumen awal belum selesai diparse.
  const host=document.getElementById('padi-kerangka-langsung'),frame=document.querySelector('.bingkai'),sesi=document.getElementById('formulir-sesi');
  const cap=document.documentElement.getAttribute('data-versi')||'';
  if(!host?.isConnected||!frame||!sesi?.dataset.token||!cap||host.dataset.cap!==cap||host.dataset.konteks!==frame.dataset.pindahKonteks||window.SESIFORM&&!SESIFORM.periksa())return null;
  if(host!==hostLama){try{registry=JSON.parse(host.textContent);hostLama=host;}catch(_){return null;}}
  if(registry?.versi!==1||registry.cap!==cap||registry.konteks!==frame.dataset.pindahKonteks||registry.sesi!==sesi.dataset.token||!registry.frames||!Object.prototype.hasOwnProperty.call(registry.frames,pilihan.alamat))return null;
  return {versi:1,alamat:pilihan.alamat,konteks:registry.konteks,cap:cap,html:registry.frames[pilihan.alamat]};
 });
})();
