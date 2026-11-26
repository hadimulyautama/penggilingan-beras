/* Registry hanya struktur native bagi konteks dokumen ini, bukan data/draf. */
(function(){
 'use strict';
 if(!window.PINDAH||typeof PINDAH.aturKerangkaLangsung!=='function')return;
 let hostLama=null,registry=null;
 // Sama dengan stok_navigasi.alamat: urutan/default dan encoding adalah
 // bagian tautan native; jangan menormalkan scope dengan URL permintaan mentah.
 function kutipStok(value,scalar=false){
  let text=encodeURIComponent(String(value)).replace(/[!'()*]/g,char=>'%'+char.charCodeAt(0).toString(16).toUpperCase());
  return scalar?text.replace(/%2F/g,'/'):text.replace(/%20/g,'+');
 }
 function alamatStok(tab,owner,customer,warehouse,search){
  const params=[['tab',tab],['pemilik',owner||'semua']];
  if(owner==='jasa'&&customer)params.push(['pelanggan_id',customer]);
  if(warehouse)params.push(['gudang',warehouse]);
  if(search)params.push(['cari',search]);
  return '/stok?'+params.map(([key,value])=>key+'='+kutipStok(value)).join('&');
 }
 function stokLangsung(pilihan,context,cap,token){
  if(!pilihan.alamat.startsWith('/stok'))return null;
  const u=new URL(pilihan.alamat,location.href),q=u.searchParams;
  if(u.origin!==location.origin||u.pathname!=='/stok'||u.hash||u.search.length>3000)return null;
  const names=['tab','pemilik','gudang','pelanggan_id','cari'];
  if(Array.from(q.keys()).some(k=>!names.includes(k)||q.getAll(k).length!==1))return null;
  const tab=q.has('tab')?q.get('tab'):'bahan',owner=q.has('pemilik')?q.get('pemilik'):'semua',warehouse=q.get('gudang')||'',customer=q.get('pelanggan_id')||'',search=q.get('cari')||'';
  if(!['bahan','produk','karung'].includes(tab)||!['semua','pabrik','jasa'].includes(owner)||search.length>200||customer&&(!/^[1-9]\d{0,9}$/.test(customer)||Number(customer)>2147483647)||customer&&owner!=='jasa')return null;
  const host=document.getElementById('padi-stok-kerangka');let data;
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap)return null;
  const encoded=host.textContent;if(!encoded||encoded.length>1572864)return null;
  try{data=JSON.parse(encoded);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.konteks!==context||data.cap!==cap||data.sesi!==token||!data.frames||typeof data.frames!=='object'||Array.isArray(data.frames)||Object.keys(data.frames).some(k=>!['bahan','produk','karung'].includes(k)))return null;
  // Jenis yang tidak disediakan otoritas tidak dibuat di browser. Penjaga
  // native tetap berjalan ketika GET isi tiba atau hak telah berubah.
  const html=decodeFrame(data,tab);if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),root=main?.querySelector('[data-halaman-bertahap][data-kind="stok"]');
  const prototype='/stok?tab='+tab+'&pemilik=semua';
  if(!frame||!root||frame.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==prototype||root.dataset.stamp!==context+'|'+prototype||root.dataset.url!=='/api/halaman-bertahap/stok?tab='+tab+'&pemilik=semua'||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const locationSelect=root.querySelector('select[name="gudang"]'),ownerSelect=root.querySelector('select[name="pemilik"]'),customerSelect=root.querySelector('select[name="pelanggan_id"]');
  if(!locationSelect||!ownerSelect||!customerSelect||!Array.from(locationSelect.options).some(o=>o.value===warehouse))return null;
  locationSelect.value=warehouse;ownerSelect.value=owner;
  if(customer){const option=doc.createElement('option');option.value=customer;option.textContent='Pelanggan terpilih · ID '+customer+' (nama menunggu data)';customerSelect.append(option);customerSelect.value=customer;}
  // Data pelanggan belum dibaca. ID dipertahankan tanpa menebak nama atau
  // menampilkan pilihan transaksi lama dari konteks lain.
  customerSelect.disabled=true;
  const customerLabel=customerSelect.closest('[data-stok-pelanggan]');if(customerLabel)customerLabel.hidden=owner!=='jasa';
  const filterButton=root.querySelector('.kontrol-pencarian>[data-sk-buka="sk-filter"]'),filterCount=Number(owner!=='semua')+Number(!!warehouse)+Number(!!customer);
  if(filterButton)filterButton.textContent='Filter'+(filterCount?' · '+filterCount:'');
  const controls=root.querySelector('[data-stok-controls]');if(controls)controls.dataset.pelangganUrl='/stok?tab='+tab+'&pemilik=jasa&gudang='+encodeURIComponent(warehouse);
  for(const form of root.querySelectorAll('form')){
   for(const input of form.querySelectorAll('input[type="hidden"]'))input.remove();
   for(const input of form.querySelectorAll('input[name="cari"]'))input.setAttribute('value',search);
   const fields=new Set(Array.from(form.elements).filter(e=>e.name&&!e.disabled).map(e=>e.name));
   for(const [key,value] of [['tab',tab],['pemilik',owner],['gudang',warehouse],['pelanggan_id',customer],['cari',search]]){
    if(fields.has(key)||key==='pelanggan_id'&&!customer)continue;
    const input=doc.createElement('input');input.type='hidden';input.name=key;input.setAttribute('value',value);form.append(input);
   }
  }
  // PINDAH mem-parse outerHTML lagi. Current value property tidak cukup:
  // atribut terpilih harus mengikuti filter sebelum serialisasi dokumen.
  for(const select of root.querySelectorAll('select'))for(const option of select.options)option.toggleAttribute('selected',option.selected);
  for(const link of main.querySelectorAll('.laporan-nav a[href],.kontrol-tab a[href]')){
   const target=new URL(link.getAttribute('href'),location.href);
   if(target.origin!==location.origin||target.pathname!=='/stok')continue;
   const kind=target.searchParams.get('tab')||'bahan';
   if(!['bahan','produk','karung'].includes(kind))return null;
   link.setAttribute('href',alamatStok(kind,owner,customer,warehouse,search));
  }
  root.querySelector('[data-shell-reset],.sk-form-filter>a[href]')?.setAttribute('href','/stok?tab='+tab+'&pemilik=semua&cari='+kutipStok(search,true));
  const historyLink=root.querySelector('.sk-riwayat-link');
  if(historyLink){
   const back=new URL(historyLink.getAttribute('href'),location.href),kind=tab==='bahan'?'pk':tab;
   if(back.origin!==location.origin||back.pathname!=='/kepemilikan'||back.searchParams.get('kind')!==kind||Array.from(back.searchParams.keys()).some(key=>!['kind','kembali_stok'].includes(key)||back.searchParams.getAll(key).length!==1))return null;
   historyLink.setAttribute('href','/kepemilikan?kind='+kind+'&kembali_stok='+kutipStok(alamatStok(tab,owner,customer,warehouse,search),true));
  }
  const scope=root.querySelector('[data-shell-scope],.sk-cakupan');
  if(scope){const ownerLabel=({semua:'Semua kepemilikan',pabrik:'Pabrik',jasa:'Titipan jasa'})[owner]+(customer?' · Pelanggan ID '+customer+' (nama menunggu data)':'');const strong=doc.createElement('strong');strong.textContent=ownerLabel;scope.replaceChildren(strong,doc.createTextNode(' · '+locationSelect.selectedOptions[0].textContent));}
  root.dataset.filtered=owner!=='semua'||!!(warehouse||customer||search)?'1':'0';
  root.dataset.stamp=context+'|'+u.pathname+u.search;
  root.dataset.url='/api/halaman-bertahap/stok'+u.search;
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function kabarLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),q=u.searchParams;
  if(u.origin!==location.origin||u.pathname!=='/kabar'||u.hash||u.search.length>2000
    ||Array.from(q.keys()).some(k=>!['tab','jenis','batas','sampai','sebelum'].includes(k)||q.getAll(k).length!==1)
    ||!['','belum'].includes(q.get('tab')||'')||(q.get('jenis')||'').length>200)return null;
  for(const key of ['batas','sampai','sebelum'])if(q.has(key)&&(!/^\d{1,18}$/.test(q.get(key))||Number(q.get(key))<(key==='sampai'?0:1)||key==='batas'&&Number(q.get(key))>100))return null;
  const host=document.getElementById('padi-kabar-kerangka');let data;
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>1048576)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.konteks!==context||data.cap!==cap||data.sesi!==token||!data.frames||Array.isArray(data.frames)||Object.keys(data.frames).length!==1||!Object.hasOwn(data.frames,'/kabar'))return null;
  const html=decodeFrame(data,'/kabar');if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-halaman-bertahap][data-kind="kabar"]');
  if(!frame||!root||frame.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!=='/kabar'||root.dataset.stamp!==context+'|/kabar'||root.dataset.url!=='/api/halaman-bertahap/kabar'||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const tab=q.get('tab')||'';root.querySelector('input[name="tab"]').setAttribute('value',tab);
  const tabs=root.querySelectorAll('.kontrol-tab a');if(tabs.length!==2)return null;
  tabs.forEach((a,i)=>{const params=new URLSearchParams();params.set('tab',i?'belum':'');params.set('jenis',q.get('jenis')||'');params.set('batas','30');if(q.has('sampai'))params.set('sampai',q.get('sampai'));a.setAttribute('href','/kabar?'+params);a.toggleAttribute('aria-current',(i===1)===(tab==='belum'));if(a.hasAttribute('aria-current'))a.setAttribute('aria-current','page');});
  root.dataset.stamp=context+'|'+u.pathname+u.search;root.dataset.url='/api/halaman-bertahap/kabar'+u.search;frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function kembaliDetailMasuk(target){
  if(target.searchParams.getAll('kembali_kerja').length>1)return null;
  const raw=target.searchParams.get('kembali_kerja')||'/barang-masuk';
  const back=new URL(raw,location.href);
  if(!raw.startsWith('/')||raw.startsWith('//')||back.origin!==location.origin||back.pathname!=='/barang-masuk'||back.hash)return null;
  // Nilai ini datang dari href katalog native. Pertahankan kueri persis,
  // bukan URL list yang kebetulan sedang dibuka atau bentuk normalisasi baru.
  return raw;
 }
 function detailLangsung(pilihan,context,cap){
  const source=document.querySelector('[data-bm-page]'),node=source?.querySelector('script[data-bm-detail-catalog]');
  if(!node||source.dataset.bmContext!==context||source.dataset.bmCap!==cap)return null;
  let data;try{data=JSON.parse(node.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='isi-1'||data.konteks!==context||data.cap!==cap||!Array.isArray(data.targets)||!data.targets.length||data.targets.length>25||typeof data.html!=='string'||data.html.length>524288)return null;
  const target=data.targets.find(t=>t?.alamat===pilihan.alamat&&typeof t.stamp==='string'&&t.stamp.startsWith(context+'|'));
  if(!target)return null;
  const u=new URL(target.alamat,location.href);
  if(u.origin!==location.origin||!/^\/barang-masuk\/[1-9]\d*$/.test(u.pathname)||u.hash)return null;
  const kembali=kembaliDetailMasuk(u);if(kembali===null)return null;
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
  if(back){back.setAttribute('href',kembali);back.textContent='Kembali ke Barang Masuk';}
  for(const anchor of frame.querySelectorAll('a.bar__balik,a.desktop-back'))anchor.setAttribute('href',kembali);
  return {versi:1,alamat:target.alamat,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function berandaLangsung(pilihan,context,cap,token){
  if(pilihan.alamat!=='/')return null;
  const host=document.getElementById('padi-beranda-kerangka');
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>1048576)return null;
  let data;try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.cap!==cap||data.konteks!==context||data.sesi!==token||!data.frames||Array.isArray(data.frames)||Object.keys(data.frames).length!==1||!Object.hasOwn(data.frames,'/'))return null;
  const html=decodeFrame(data,'/');if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-halaman-bertahap][data-kind="beranda"]');
  if(!frame||!root||frame.dataset.pindahAlamat!=='/'||frame.dataset.pindahKonteks!==context||root.dataset.stamp!==context+'|/'||root.dataset.url!=='/api/halaman-bertahap/beranda'||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  return {versi:1,alamat:'/',konteks:context,cap,html};
 }
 const qcPaths=['gabah-basah','gabah-kering','pk-hasil-giling','pk-luar','beras-hasil-sosoh'].map(k=>'/riwayat-qc/'+k);
 function qcLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href);if(u.origin!==location.origin||u.search||u.hash||!qcPaths.includes(u.pathname))return null;
  const host=document.getElementById('padi-qc-kerangka');
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>1572864)return null;
  let data;try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.cap!==cap||data.konteks!==context||data.sesi!==token||!data.frames||Array.isArray(data.frames)||!Object.keys(data.frames).length||Object.keys(data.frames).some(p=>!qcPaths.includes(p)))return null;
  const html=decodeFrame(data,u.pathname);if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-halaman-bertahap]'),kind='qc-'+u.pathname.split('/')[2];
  if(!frame||!root||root.dataset.kind!==kind||frame.dataset.pindahAlamat!==u.pathname||frame.dataset.pindahKonteks!==context||root.dataset.stamp!==context+'|'+u.pathname||root.dataset.url!=='/api/halaman-bertahap/'+kind||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  return {versi:1,alamat:u.pathname,konteks:context,cap,html};
 }
 const riwayatPaths=['/riwayat-sosoh','/riwayat-giling','/riwayat-pengeringan'];
 function descriptorRiwayat(context,cap,token){
  const node=document.getElementById('padi-riwayat-kerangka');
  if(!node?.isConnected||node.dataset.konteks!==context||node.dataset.cap!==cap||node.textContent.length>1572864)return null;
  let data;try{data=JSON.parse(node.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.cap!==cap||data.konteks!==context||data.sesi!==token||!data.frames||typeof data.frames!=='object'||Array.isArray(data.frames)||!Object.keys(data.frames).length||Object.keys(data.frames).some(p=>!riwayatPaths.includes(p))||typeof data.default!=='string'||data.default&&!Object.hasOwn(data.frames,data.default))return null;
  return data;
 }
 function riwayatLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href);
  if(u.origin!==location.origin||!riwayatPaths.includes(u.pathname)||u.hash||u.search)return null;
  const data=descriptorRiwayat(context,cap,token),html=data&&decodeFrame(data,u.pathname);if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-halaman-bertahap]');
  const kind=u.pathname.slice(1),prototype=u.pathname;
  if(!frame||!root||root.dataset.kind!==kind||frame.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==prototype||root.dataset.stamp!==context+'|'+prototype||root.dataset.url!=='/api/halaman-bertahap/'+kind||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const address=u.pathname+u.search;
  frame.dataset.pindahAlamat=address;root.dataset.stamp=context+'|'+address;root.dataset.url='/api/halaman-bertahap/'+kind+u.search;
  return {versi:1,alamat:address,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function pasangAliasRiwayat(){
  const frame=document.querySelector('.bingkai'),token=document.getElementById('formulir-sesi')?.dataset.token,cap=document.documentElement.dataset.versi;
  if(!frame||!token||!cap||window.SESIFORM&&!SESIFORM.periksa())return;
  const data=descriptorRiwayat(frame.dataset.pindahKonteks,cap,token);
  if(!data?.default)return;
  // Hanya alias polos yang sama dengan keputusan server; bookmark kanonik
  // QC/Giling serta alias berparameter tetap milik navigasi native.
  for(const a of document.querySelectorAll('#laci a.pintu[data-pindah-menu="laporan_riwayat"],.desktop-chrome__crumbrow a[href],a.desktop-back[href],a.bar__balik[href]')){
   if(['/riwayat','/laporan-riwayat'].includes(a.getAttribute('href')))a.setAttribute('href',data.default);
  }
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',pasangAliasRiwayat,{once:true});
 else pasangAliasRiwayat();
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
  if(!Object.prototype.hasOwnProperty.call(registry.frames,pilihan.alamat))return stokLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||riwayatLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||berandaLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||qcLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||kabarLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||detailLangsung(pilihan,registry.konteks,cap);
  // Validasi seluruh indeks dan ukuran sebelum join. Versi/rujukan rusak
  // kembali ke navigasi native, bukan HTML parsial atau alamat tebakan.
  const html=decodeFrame(registry,pilihan.alamat);if(!html)return null;
  return {versi:1,alamat:pilihan.alamat,konteks:registry.konteks,cap:cap,html};
 });
})();
