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
  if(registry?.versi!==2||registry.penyandian!=='baris-1'||registry.cap!==cap||registry.konteks!==frame.dataset.pindahKonteks||registry.sesi!==sesi.dataset.token||!registry.frames||typeof registry.frames!=='object'||Array.isArray(registry.frames)||!Object.prototype.hasOwnProperty.call(registry.frames,pilihan.alamat))return null;
  const potongan=registry.potongan,refs=registry.frames[pilihan.alamat];
  if(!Array.isArray(potongan)||!potongan.length||potongan.length>16384||!potongan.every(s=>typeof s==='string'&&s.length)||!Array.isArray(refs)||!refs.length||refs.length>16384)return null;
  let panjang=0;const baris=[];
  // Validasi seluruh indeks dan ukuran sebelum join. Versi/rujukan rusak
  // kembali ke navigasi native, bukan HTML parsial atau alamat tebakan.
  for(const i of refs){if(!Number.isInteger(i)||i<0||i>=potongan.length)return null;panjang+=potongan[i].length;if(panjang>524288)return null;baris.push(potongan[i]);}
  return {versi:1,alamat:pilihan.alamat,konteks:registry.konteks,cap:cap,html:baris.join('')};
 });
})();
