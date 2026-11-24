/* Registry hanya struktur native bagi konteks dokumen ini, bukan data/draf. */
(function(){
 'use strict';
 if(!window.PINDAH||typeof PINDAH.aturKerangkaLangsung!=='function')return;
 let hostLama=null,registry=null;
 function detailLangsung(pilihan,context,cap){
  const source=document.querySelector('[data-bm-page]'),node=source?.querySelector('script[data-bm-detail-catalog]');
  if(!node||source.dataset.bmContext!==context||source.dataset.bmCap!==cap)return null;
  let data;try{data=JSON.parse(node.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='isi-1'||data.konteks!==context||data.cap!==cap||!Array.isArray(data.targets)||!data.targets.length||data.targets.length>25||typeof data.html!=='string'||data.html.length>524288)return null;
  const target=data.targets.find(t=>t?.alamat===pilihan.alamat&&typeof t.stamp==='string'&&t.stamp.startsWith(context+'|'));
  if(!target)return null;
  const u=new URL(target.alamat,location.href);
  if(u.origin!==location.origin||!/^\/barang-masuk\/[1-9]\d*$/.test(u.pathname)||u.hash)return null;
  // Prototype hanya struktur. ID/URL berasal dari link native pada halaman
  // yang masih aktif; tidak menerima ID bebas atau mencampur data sumber.
  const base=decodeFrame(registry,'/barang-masuk');if(!base)return null;
  const doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman');
  if(!frame||!main||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap)return null;
  const nodes=Array.from(main.childNodes),start=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),end=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(start.length!==1||end.length!==1||!(start[0].compareDocumentPosition(end[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  while(start[0].nextSibling&&start[0].nextSibling!==end[0])start[0].nextSibling.remove();
  const partial=doc.createElement('template');partial.innerHTML=data.html;end[0].before(partial.content);
  const root=main.querySelector('[data-halaman-bertahap][data-kind="barang-masuk-detail"]');if(!root)return null;
  doc.title='Detail Barang Masuk';const label=main.querySelector('.bar__merek');if(label){label.textContent='Detail Barang Masuk';label.setAttribute('aria-label','Detail Barang Masuk');}
  frame.dataset.pindahAlamat=target.alamat;
  root.dataset.stamp=target.stamp;
  root.dataset.url='/api/halaman-bertahap/barang-masuk-detail/'+u.pathname.split('/').pop()+u.search;
  for(const tab of root.querySelectorAll('[data-bm-tab]')){const link=new URL(u);link.searchParams.set('tab_detail',tab.dataset.bmTab);tab.dataset.url=link.pathname+link.search;}
  const back=root.querySelector('[data-bm-back]'),link=source.querySelector('a[href="'+CSS.escape(target.alamat)+'"]');
  if(!link)return null;
  if(back){back.href=location.pathname+location.search;back.textContent='Kembali ke Barang Masuk';}
  for(const anchor of frame.querySelectorAll('a.bar__balik,a.desktop-back'))if(anchor.getAttribute('href')==='/barang-masuk')anchor.href=location.pathname+location.search;
  return {versi:1,alamat:target.alamat,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function decodeFrame(data,address){
  const potongan=data.potongan,refs=data.frames[address];
  if(!Array.isArray(potongan)||!potongan.length||potongan.length>16384||!potongan.every(s=>typeof s==='string'&&s.length)||!Array.isArray(refs)||!refs.length||refs.length>16384)return null;
  let panjang=0;const baris=[];
  for(const i of refs){if(!Number.isInteger(i)||i<0||i>=potongan.length)return null;panjang+=potongan[i].length;if(panjang>524288)return null;baris.push(potongan[i]);}
  return baris.join('');
 }
 PINDAH.aturKerangkaLangsung(function(pilihan){
  // Script dapat diparse sebelum host di luar bingkai. Cari saat dipakai,
  // bukan membekukan null saat dokumen awal belum selesai diparse.
  const host=document.getElementById('padi-kerangka-langsung'),frame=document.querySelector('.bingkai'),sesi=document.getElementById('formulir-sesi');
  const cap=document.documentElement.getAttribute('data-versi')||'';
  if(!host?.isConnected||!frame||!sesi?.dataset.token||!cap||host.dataset.cap!==cap||host.dataset.konteks!==frame.dataset.pindahKonteks||window.SESIFORM&&!SESIFORM.periksa())return null;
  if(host!==hostLama){try{registry=JSON.parse(host.textContent);hostLama=host;}catch(_){return null;}}
  if(registry?.versi!==2||registry.penyandian!=='baris-1'||registry.cap!==cap||registry.konteks!==frame.dataset.pindahKonteks||registry.sesi!==sesi.dataset.token||!registry.frames||typeof registry.frames!=='object'||Array.isArray(registry.frames))return null;
  if(!Object.prototype.hasOwnProperty.call(registry.frames,pilihan.alamat))return detailLangsung(pilihan,registry.konteks,cap);
  // Validasi seluruh indeks dan ukuran sebelum join. Versi/rujukan rusak
  // kembali ke navigasi native, bukan HTML parsial atau alamat tebakan.
  const html=decodeFrame(registry,pilihan.alamat);if(!html)return null;
  return {versi:1,alamat:pilihan.alamat,konteks:registry.konteks,cap:cap,html};
 });
})();
