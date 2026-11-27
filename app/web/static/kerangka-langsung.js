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
 function returDaftarLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),q=u.searchParams,path='/riwayat-retur-supplier',params=['q','awal','akhir','status','supplier','gudang','penerimaan','halaman'];
  if(u.origin!==location.origin||u.pathname!==path||u.hash||u.search.length>3000||[...q.keys()].some(k=>!params.includes(k)||q.getAll(k).length!==1)||[...q.values()].some(v=>v.length>200))return null;
  for(const k of ['supplier','gudang','penerimaan','halaman'])if(q.get(k)&&(!/^[1-9]\d{0,9}$/.test(q.get(k))||Number(q.get(k))>2147483647))return null;
  for(const k of ['awal','akhir'])if(q.get(k)&&!/^\d{4}-\d{2}-\d{2}$/.test(q.get(k)))return null;
  const host=document.getElementById('padi-rrs-kerangka');let data;
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>786432)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.cap!==cap||data.konteks!==context||data.sesi!==token||Object.keys(data.frames||{}).length!==1||!Array.isArray(data.status)||q.get('status')&&!data.status.includes(q.get('status')))return null;
  const html=decodeFrame(data,path);if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),root=doc.querySelector('[data-rrs-shell]'),frame=doc.querySelector('.bingkai'),form=root?.querySelector('#rrs-form');
  if(!root||!form||root.dataset.rrsContext!==context||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==path||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  for(const key of ['q','awal','akhir','status','supplier','gudang']){
   const control=root.querySelector('[name="'+key+'"]'),value=q.get(key)||'';if(!control)return null;
   if(['supplier','gudang'].includes(key)&&value){const option=doc.createElement('option');option.value=value;option.textContent='Pilihan sebelumnya · ID '+value+' (nama menunggu data)';control.append(option);const hidden=doc.createElement('input');hidden.type='hidden';hidden.name=key;hidden.value=value;hidden.setAttribute('value',value);hidden.setAttribute('data-rrs-filter-pending','');form.append(hidden);}
   control.value=value;
   if(control.tagName==='SELECT')for(const option of control.options)option.toggleAttribute('selected',option.selected);else control.setAttribute('value',value);
  }
  const receipt=q.get('penerimaan');if(receipt){const hidden=doc.createElement('input');hidden.type='hidden';hidden.name='penerimaan';hidden.setAttribute('value',receipt);form.append(hidden);root.querySelector('[data-rrs-scope]').textContent='Riwayat dibatasi pada penerimaan yang dipilih. Rincian sumber menunggu data.';}
  const count=['awal','akhir','status','supplier','gudang'].filter(k=>q.get(k)).length,b=root.querySelector('[data-rrs-filter-open]');if(b){const text=[...b.childNodes].find(n=>n.nodeType===3);if(text)text.textContent=' Filter'+(count?' · '+count:'');}
  const reset=root.querySelector('.rsh-filter>a[href]');if(reset)reset.setAttribute('href',path+'?'+(receipt?'penerimaan='+kutipStok(receipt)+'&':'')+'halaman=1');
  const applied=root.querySelector('[data-rrs-filter-tags]');if([...q.keys()].some(k=>k!=='halaman'&&q.get(k)))applied.textContent='Membaca hasil untuk filter pada alamat ini. Perubahan isian belum diterapkan sampai Cari/Terapkan filter dipilih.';
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function returDetailLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),q=u.searchParams,match=u.pathname.match(/^\/riwayat-retur-supplier\/([1-9]\d{0,9})$/),tabs=['ringkasan','timbang','stok','jejak'];
  if(u.origin!==location.origin||!match||Number(match[1])>2147483647||u.hash||u.search.length>3000)return null;
  const params=['q','awal','akhir','status','supplier','gudang','penerimaan','halaman'];
  if([...q.keys()].some(k=>!params.concat('tab').includes(k)||q.getAll(k).length!==1)||[...q.values()].some(v=>v.length>200))return null;
  const tab=q.get('tab')||'ringkasan';if(!tabs.includes(tab))return null;
  const host=document.getElementById('padi-rsd-kerangka');let data;
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>1572864)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.cap!==cap||data.konteks!==context||data.sesi!==token||Object.keys(data.frames||{}).length!==4||tabs.some(t=>!Object.hasOwn(data.frames,t)))return null;
  const html=decodeFrame(data,tab);if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),root=doc.querySelector('[data-rsd-shell]'),frame=doc.querySelector('.bingkai'),prototype='/riwayat-retur-supplier/__RSD_ID__';
  if(!root||root.dataset.rsdContext!==context||root.dataset.rsdId!=='__RSD_ID__'||root.dataset.rsdTab!==tab||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==prototype+'?tab='+tab||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const query=params.filter(k=>q.get(k)).map(k=>k+'='+kutipStok(q.get(k))).join('&'),back='/riwayat-retur-supplier?'+query;
  root.dataset.rsdId=match[1];frame.dataset.pindahAlamat=u.pathname+u.search;
  const links=[...root.querySelectorAll('.rsh-tabs [role="tab"]')];if(links.length!==4)return null;
  links.forEach((a,i)=>a.setAttribute('href',u.pathname+'?'+query+'&tab='+tabs[i]));
  root.querySelector('.rsp-kembali').setAttribute('href',back);
  for(const a of doc.querySelectorAll('.bar__balik,.desktop-back'))a.setAttribute('href',back);
  if(location.pathname===u.pathname&&document.activeElement?.matches('.rsh-tabs [role="tab"]'))root.dataset.rsdFocusTab='1';
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function karungDetailLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),q=u.searchParams,path='/stok/karung/detail';
  if(u.origin!==location.origin||u.pathname!==path||u.hash||u.search.length>2000||[...q.keys()].some(k=>!['material','ukuran','merk','pemilik','sumber_page'].includes(k)||q.getAll(k).length!==1)||!q.get('material')||q.get('material').length>100||(q.get('merk')||'').length>200||!/^\d{1,10}$/.test(q.get('ukuran')||'')||Number(q.get('ukuran'))<1||Number(q.get('ukuran'))>2147483647)return null;
  const owner=q.get('pemilik')||'pabrik',page=q.get('sumber_page')||'1';
  if(owner!=='pabrik'&&(!/^[1-9]\d{0,9}$/.test(owner)||Number(owner)>2147483647)||!/^[1-9]\d{0,9}$/.test(page)||Number(page)>2147483647)return null;
  const host=document.getElementById('padi-karung-detail-kerangka');let data;
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>524288)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.cap!==cap||data.konteks!==context||data.sesi!==token||Object.keys(data.frames||{}).length!==1)return null;
  const html=decodeFrame(data,path);if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),root=doc.querySelector('[data-karung-detail-shell]'),frame=doc.querySelector('.bingkai');
  if(!root||root.dataset.karungContext!==context||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==path||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function laporanLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),q=u.searchParams;
  if(u.origin!==location.origin||u.hash||u.search.length>2000||!(u.pathname==='/laporan'||/^\/laporan\/[a-z_]+$/.test(u.pathname))||Array.from(q.keys()).some(k=>!['periode','dari','sampai'].includes(k)||q.getAll(k).length!==1))return null;
  if(u.pathname==='/laporan'&&u.search)return null;
  const host=document.getElementById('padi-laporan-kerangka');let data;
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>1572864)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.konteks!==context||data.cap!==cap||data.sesi!==token||!data.frames||Array.isArray(data.frames)||Object.keys(data.frames).length>14||!Object.hasOwn(data.frames,u.pathname))return null;
  const html=decodeFrame(data,u.pathname);if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai');
  if(!frame||frame.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==u.pathname||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  if(u.pathname==='/laporan')return doc.querySelector('[data-laporan-catalogue]')?{versi:1,alamat:u.pathname,konteks:context,cap,html}:null;
  const root=doc.querySelector('[data-halaman-bertahap][data-laporan-shell]'),kind='laporan-'+u.pathname.split('/')[2];
  if(!root||root.dataset.kind!==kind||root.dataset.stamp!==context+'|'+u.pathname||root.dataset.url!=='/api/halaman-bertahap/'+kind)return null;
  const form=root.querySelector('form'),period=form.elements.periode,value=q.get('periode')??'bulan_ini';
  if(!Array.from(period.options).some(o=>o.value===value))return null;
  period.value=value;
  for(const key of ['dari','sampai']){
   const v=q.get(key)||'';
   if(v&&(!/^\d{4}-\d{2}-\d{2}$/.test(v)||!Number.isFinite(Date.parse(v+'T00:00:00Z'))||new Date(v+'T00:00:00Z').toISOString().slice(0,10)!==v))return null;
   form.elements[key].setAttribute('value',v);form.elements[key].disabled=value!=='khusus';form.elements[key].required=value==='khusus';
  }
  if(value==='khusus'&&(!q.get('dari')||!q.get('sampai')||q.get('dari')>q.get('sampai')||q.get('sampai')==='9999-12-31'))return null;
  form.querySelector('.lp-rentang').hidden=value!=='khusus';form.querySelector('.lp-tampilkan').hidden=value!=='khusus';
  for(const option of period.options)option.toggleAttribute('selected',option.selected);
  root.querySelector('[data-lp-periode]').textContent='Periode dipilih: '+period.selectedOptions[0].textContent+' · tanggal menunggu data';
  const address=u.pathname+u.search;frame.dataset.pindahAlamat=address;root.dataset.stamp=context+'|'+address;root.dataset.url='/api/halaman-bertahap/'+kind+u.search;
  return {versi:1,alamat:address,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
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
  function pekerjaanLainLangsung(pilihan,context,cap,token){
   const u=new URL(pilihan.alamat,location.href);
   if(u.origin!==location.origin||u.pathname!=='/pekerjaan/catat-lain'||u.hash||u.search.length>4096||Array.from(u.searchParams.keys()).some(k=>k!=='kembali'||u.searchParams.getAll(k).length!==1))return null;
   const raw=u.searchParams.get('kembali')||'/pekerjaan',back=new URL(raw,location.href);
   if(!raw.startsWith('/')||raw.startsWith('//')||back.origin!==location.origin||back.pathname!=='/pekerjaan'||back.hash)return null;
   const host=document.getElementById('padi-pl-kerangka');let data;
   if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>786432)return null;
   try{data=JSON.parse(host.textContent);}catch(_){return null;}
   if(data?.versi!==1||data.penyandian!=='baris-1'||data.konteks!==context||data.cap!==cap||data.sesi!==token||!data.frames||Object.keys(data.frames).length!==1)return null;
   const html=decodeFrame(data,'/pekerjaan/catat-lain');if(!html)return null;
   const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-pekerjaan-lain]');
   if(!frame||!root||root.dataset.plContext!==context||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
   for(const key of ['buka','nilai','halaman','asal','kategori','grup','informasi'])back.searchParams.delete(key);
   for(const tab of ['tindakan','berjalan']){const link=doc.querySelector('[data-tab-riwayat="'+tab+'"]');if(!link)return null;const target=new URL(back);target.searchParams.set('tab',tab);link.href=target.pathname+target.search;}
   const active=doc.querySelector('[data-tab-riwayat="lain"]');if(!active)return null;active.href=u.pathname+u.search;
   const nav=doc.querySelector('[data-laporan-kontrol]');if(!nav)return null;
   let tabs;try{tabs=JSON.parse(nav.dataset.tujuanTab);}catch(_){return null;}
   if(!Array.isArray(tabs)||tabs.length!==3)return null;
   for(const tab of tabs){const a=doc.querySelector('[data-tab-riwayat="'+tab.kunci+'"]');if(!a)return null;tab.href=a.getAttribute('href');a.removeAttribute('data-utuh');}
   nav.dataset.tujuanTab=JSON.stringify(tabs);
   frame.dataset.pindahAlamat=u.pathname+u.search;
   return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
  }
  function perbaikanLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),m=/^\/barang-keluar\/([1-9]\d{0,9})\/perbaikan$/.exec(u.pathname),q=u.searchParams;
  if(u.origin!==location.origin||!m||Number(m[1])>2147483647||u.hash||u.search.length>4096||[...q.keys()].some(k=>!['q','status','sejak','sebelum'].includes(k)||q.getAll(k).length!==1)||[...q.values()].some(v=>v.length>200))return null;
  const host=document.getElementById('padi-perbaikan-kerangka');let data;if(!host||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>524288)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}if(data?.versi!==1||data.cap!==cap||data.konteks!==context||data.sesi!==token||typeof data.html!=='string'||data.html.length>393216)return null;
  const doc=new DOMParser().parseFromString(data.html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-pp-shell]');
  if(!root||root.dataset.ppContext!==context||!root.dataset.ppActor||frame?.dataset.pindahAlamat!=='/barang-keluar/2147483647/perbaikan'||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  root.dataset.ppTarget=m[1];root.querySelector('[data-pp-back]').href='/barang-keluar/'+m[1]+u.search;root.querySelector('[data-pp-original]').href=u.pathname+u.search;frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function jasaStokLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),m=/^\/jasa\/pelanggan\/([1-9]\d{0,9})$/.exec(u.pathname),q=u.searchParams,keys=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status'];
  if(u.origin!==location.origin||!m||Number(m[1])>2147483647||u.hash||u.href.length>4096||q.get('tab')!=='stok'||[...q.keys()].some(k=>!keys.includes(k)||q.getAll(k).length!==1||q.get(k).length>200))return null;
  const host=document.getElementById('padi-jst-kerangka');let data;if(!host||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>524288)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}if(data?.versi!==1||data.cap!==cap||data.konteks!==context||data.sesi!==token||typeof data.html!=='string'||data.html.length>393216)return null;
  const doc=new DOMParser().parseFromString(data.html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-jst-shell]');
  if(!root||root.dataset.jstContext!==context||frame?.dataset.pindahAlamat!=='/jasa/pelanggan/2147483647?tab=stok'||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const parent=new URLSearchParams();for(const name of ['status','cari','halaman'])if(q.has(name))parent.set(name,q.get(name));root.querySelector('.jasa-kembali').href='/jasa'+(parent.toString()?'?'+parent:'');
  root.querySelectorAll('[data-jst-tab]').forEach(a=>{const next=new URLSearchParams({tab:a.dataset.jstTab,status:q.get('status')||'',cari:q.get('cari')||'',halaman:q.get('halaman')||''});for(const name of ['pesanan_halaman','pesanan_cari','pesanan_status'])if(q.has(name))next.set(name,q.get(name));a.href=u.pathname+'?'+next;});
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function jasaProsesLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),m=/^\/jasa\/pelanggan\/([1-9]\d{0,9})$/.exec(u.pathname),q=u.searchParams,keys=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status','rincian_halaman','rincian_cari'];
  if(u.origin!==location.origin||!m||Number(m[1])>2147483647||u.hash||u.href.length>4096||q.get('tab')!=='proses'||[...q.keys()].some(k=>!keys.includes(k)||q.getAll(k).length!==1||q.get(k).length>200))return null;
  const host=document.getElementById('padi-jpc-kerangka');let data;if(!host||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>524288)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}if(data?.versi!==1||data.cap!==cap||data.konteks!==context||data.sesi!==token||typeof data.html!=='string'||data.html.length>393216)return null;
  const doc=new DOMParser().parseFromString(data.html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-jpc-shell]');
  if(!root||root.dataset.jpcContext!==context||frame?.dataset.pindahAlamat!=='/jasa/pelanggan/2147483647?tab=proses'||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const form=root.querySelector(':scope > form.saring');if(!form?.elements.rincian_cari)return null;form.action=u.pathname;form.elements.rincian_cari.value=q.get('rincian_cari')||'';
  const parent=new URLSearchParams();for(const name of ['status','cari','halaman'])if(q.has(name))parent.set(name,q.get(name));root.querySelector('.jasa-kembali').href='/jasa'+(parent.toString()?'?'+parent:'');
  root.querySelectorAll('[data-jpc-tab]').forEach(a=>{const next=new URLSearchParams({tab:a.dataset.jpcTab,status:q.get('status')||'',cari:q.get('cari')||'',halaman:q.get('halaman')||''});for(const name of ['pesanan_halaman','pesanan_cari','pesanan_status'])if(q.has(name))next.set(name,q.get(name));a.href=u.pathname+'?'+next;});
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function jasaPenerimaanLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),m=/^\/jasa\/pelanggan\/([1-9]\d{0,9})$/.exec(u.pathname),q=u.searchParams,keys=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status','rincian_halaman','rincian_cari'];
  if(u.origin!==location.origin||!m||Number(m[1])>2147483647||u.hash||u.href.length>4096||q.get('tab')!=='penerimaan'||[...q.keys()].some(k=>!keys.includes(k)||q.getAll(k).length!==1||q.get(k).length>200))return null;
  const host=document.getElementById('padi-jpr-kerangka');let data;if(!host||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>524288)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}if(data?.versi!==1||data.cap!==cap||data.konteks!==context||data.sesi!==token||typeof data.html!=='string'||data.html.length>393216)return null;
  const doc=new DOMParser().parseFromString(data.html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-jpr-shell]');
  if(!root||root.dataset.jprContext!==context||frame?.dataset.pindahAlamat!=='/jasa/pelanggan/2147483647?tab=penerimaan'||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const form=root.querySelector(':scope > form.saring');if(!form?.elements.rincian_cari)return null;form.action=u.pathname;form.elements.rincian_cari.value=q.get('rincian_cari')||'';
  const parent=new URLSearchParams();for(const name of ['status','cari','halaman'])if(q.has(name))parent.set(name,q.get(name));root.querySelector('.jasa-kembali').href='/jasa'+(parent.toString()?'?'+parent:'');
  root.querySelectorAll('[data-jpr-tab]').forEach(a=>{const next=new URLSearchParams({tab:a.dataset.jprTab,status:q.get('status')||'',cari:q.get('cari')||'',halaman:q.get('halaman')||''});for(const name of ['pesanan_halaman','pesanan_cari','pesanan_status'])if(q.has(name))next.set(name,q.get(name));a.href=u.pathname+'?'+next;});
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function jasaRingkasanLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),m=/^\/jasa\/pelanggan\/([1-9]\d{0,9})$/.exec(u.pathname),q=u.searchParams,keys=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status'];
  if(u.origin!==location.origin||!m||Number(m[1])>2147483647||u.hash||u.search.length>4096||(q.get('tab')||'ringkasan')!=='ringkasan'||[...q.keys()].some(k=>!keys.includes(k)||q.getAll(k).length!==1||q.get(k).length>200))return null;
  const host=document.getElementById('padi-jd-kerangka');let data;if(!host||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>524288)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}if(data?.versi!==1||data.cap!==cap||data.konteks!==context||data.sesi!==token||typeof data.html!=='string'||data.html.length>393216)return null;
  const doc=new DOMParser().parseFromString(data.html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-jd-shell]');
  if(!root||root.dataset.jdContext!==context||frame?.dataset.pindahAlamat!=='/jasa/pelanggan/2147483647'||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const form=root.querySelector('.jasa-pesanan-filter');if(!form)return null;form.action=u.pathname+'#pesanan-pelanggan';
  for(const name of ['pesanan_cari','pesanan_status'])form.elements.namedItem(name).value=q.get(name)||'';
  const parent=new URLSearchParams();for(const name of ['status','cari','halaman'])if(q.has(name))parent.set(name,q.get(name));root.querySelector('.jasa-kembali').href='/jasa'+(parent.toString()?'?'+parent:'');
  const receipt=root.querySelector('[data-jd-tab="penerimaan"]');if(receipt){const next=new URLSearchParams({tab:'penerimaan',status:q.get('status')||'',cari:q.get('cari')||'',halaman:q.get('halaman')||''});for(const name of ['pesanan_halaman','pesanan_cari','pesanan_status'])if(q.has(name))next.set(name,q.get(name));receipt.href=u.pathname+'?'+next;receipt.removeAttribute('aria-disabled');}
  const processTab=root.querySelector('[data-jd-tab="proses"]');if(processTab){const next=new URLSearchParams({tab:'proses',status:q.get('status')||'',cari:q.get('cari')||'',halaman:q.get('halaman')||''});for(const name of ['pesanan_halaman','pesanan_cari','pesanan_status'])if(q.has(name))next.set(name,q.get(name));processTab.href=u.pathname+'?'+next;processTab.removeAttribute('aria-disabled');}
  const stockTab=root.querySelector('[data-jd-tab="stok"]');if(stockTab){const next=new URLSearchParams({tab:'stok',status:q.get('status')||'',cari:q.get('cari')||'',halaman:q.get('halaman')||''});for(const name of ['pesanan_halaman','pesanan_cari','pesanan_status'])if(q.has(name))next.set(name,q.get(name));stockTab.href=u.pathname+'?'+next;stockTab.removeAttribute('aria-disabled');}
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function kemasUlangLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),q=u.searchParams,path='/stok-produk/kemas-ulang',ids=['sku_id','std_id','jasa_id'];
  if(u.origin!==location.origin||u.pathname!==path||u.hash||u.search.length>4096||!q.has('sku_id')||[...q.keys()].some(k=>![...ids,'kembali_stok'].includes(k)||q.getAll(k).length!==1)||ids.some(k=>q.has(k)&&(!/^[1-9]\d{0,9}$/.test(q.get(k))||Number(q.get(k))>2147483647))||(q.get('kembali_stok')||'').length>2000)return null;
  const host=document.getElementById('padi-ku-kerangka');let data;if(!host||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>524288)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}if(data?.versi!==1||data.cap!==cap||data.konteks!==context||data.sesi!==token||typeof data.html!=='string'||data.html.length>393216)return null;
  const doc=new DOMParser().parseFromString(data.html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-ku-shell]');
  if(!root||root.dataset.kuContext!==context||root.hasAttribute('data-kemas-ulang')||frame?.dataset.pindahAlamat!==path||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  if(q.has('jasa_id')){const link=doc.querySelector('#laci a.pintu[href="/stok-produk-jasa"]');if(link){for(const a of doc.querySelectorAll('#laci a.pintu')){a.classList.toggle('pintu--kini',a===link);if(a===link)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}}root.querySelector('[data-ku-back]').href='/stok-produk-jasa';root.querySelector('[data-ku-back]').textContent='← Produk jasa';}
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function pengambilanLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),q=u.searchParams,path='/barang-keluar/pengambilan-jasa',pid=q.get('pelanggan_id')||'';
  if(u.origin!==location.origin||u.pathname!==path||u.hash||u.search.length>3000||[...q.keys()].some(k=>k!=='pelanggan_id'||q.getAll(k).length!==1)||pid&&(!/^[1-9]\d{0,9}$/.test(pid)||Number(pid)>2147483647))return null;
  const host=document.getElementById('padi-pengambilan-kerangka');let data;if(!host||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>524288)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}if(data?.versi!==1||data.cap!==cap||data.konteks!==context||data.sesi!==token||typeof data.html!=='string'||data.html.length>393216)return null;
  const doc=new DOMParser().parseFromString(data.html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-editor-perintah="__PJ_ID__"][data-jenis="jasa"]');
  if(!root||frame?.dataset.pindahAlamat!==path||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  frame.dataset.pindahAlamat=u.pathname+u.search;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function pengirimanDetailLangsung(pilihan,context,cap,token){
   const u=new URL(pilihan.alamat,location.href),m=/^\/barang-keluar\/([1-9]\d{0,9})$/.exec(u.pathname),q=u.searchParams,keys=['rincian_perintah','q','status','sejak','sebelum','tab_detail','kembali','kembali_kerja'];
   if(u.origin!==location.origin||u.hash||!m||Number(m[1])>2147483647||u.search.length>4096||q.get('rincian_perintah')!=='1'||[...q.keys()].some(k=>!keys.includes(k)||q.getAll(k).length!==1)||!['ringkasan','barang','tiket','riwayat'].includes(q.get('tab_detail')||'ringkasan'))return null;
   const host=document.getElementById('padi-pengiriman-detail-kerangka');let data;if(!host||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>524288)return null;
   try{data=JSON.parse(host.textContent);}catch(_){return null;}if(data?.versi!==1||data.cap!==cap||data.konteks!==context||data.sesi!==token||typeof data.html!=='string')return null;
   const doc=new DOMParser().parseFromString(data.html,'text/html'),root=doc.querySelector('[data-pengiriman-detail-shell]'),frame=doc.querySelector('.bingkai');if(!root||root.dataset.pkdContext!==context||!root.dataset.pkdActor||frame?.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
   root.dataset.pkdTarget=m[1];root.querySelector('[data-pkd-native]').href=u.pathname+u.search;const back=q.get('kembali_kerja')||q.get('kembali')||'',allowed=['/pekerjaan','/barang-keluar','/retur','/stok','/riwayat','/laporan','/jasa'];const b=new URL(back||'/barang-keluar',location.href);root.querySelector('[data-pkd-back]').href=back&&b.origin===location.origin&&allowed.includes(b.pathname)?back:'/barang-keluar?'+new URLSearchParams({q:q.get('q')||'',status:q.get('status')||'',sejak:q.get('sejak')||''});
   for(const a of root.querySelectorAll('.detail-kirim-tabs a')){const t=new URL(u);t.searchParams.set('tab_detail',a.id.slice(4));t.hash=a.getAttribute('aria-controls');a.href=t.pathname+t.search+t.hash;}frame.dataset.pindahAlamat=u.pathname+u.search;
   return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
  }
  function muatanLangsung(pilihan,context,cap,token){
   const u=new URL(pilihan.alamat,location.href),match=/^\/barang-keluar\/([1-9]\d{0,9})\/(muatan|selesai-muat)$/.exec(u.pathname),q=u.searchParams;
   const path=match?'/'+match[2]:u.pathname,finish=path==='/selesai-muat',keys=['perintah','kembali_kerja',...(finish?['buka']:['item','semua'])];
   if(u.origin!==location.origin||u.hash||u.search.length>4096||!['/muatan','/selesai-muat'].includes(path)||Array.from(q.keys()).some(k=>!keys.includes(k)||q.getAll(k).length!==1)||match&&q.has('perintah'))return null;
   for(const key of ['perintah','item'])if(q.get(key)&&(!/^[1-9]\d{0,9}$/.test(q.get(key))||Number(q.get(key))>2147483647))return null;
   if(match&&Number(match[1])>2147483647||['semua','buka'].some(k=>!['','0','1'].includes(q.get(k)||'')))return null;
   const work=q.get('kembali_kerja')||'';if(work&&(!(work==='/pekerjaan'||work.startsWith('/pekerjaan?'))||new URL(work,location.href).hash))return null;
   const id=match?.[1]||q.get('perintah')||'',host=document.getElementById('padi-muatan-kerangka');let data;
   if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>393216)return null;
   try{data=JSON.parse(host.textContent);}catch(_){return null;}
   if(data?.versi!==1||data.penyandian!=='baris-1'||data.konteks!==context||data.cap!==cap||data.sesi!==token||!data.frames||Object.keys(data.frames).length!==4)return null;
   const prototype=path+(id?'?perintah=2147483647':''),html=decodeFrame(data,prototype);if(!html)return null;
   const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector('[data-muatan-shell]');
   if(!frame||!root||root.dataset.muatanContext!==context||!root.dataset.actor||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
   const parent='/barang-keluar/'+id;
   for(const a of doc.querySelectorAll('a[href]')){const href=a.getAttribute('href');if(href==='/barang-keluar/2147483647')a.setAttribute('href',parent);}
   const old=document.querySelector('.bingkai')?.dataset.pindahAlamat||'/',back=new URL(old,location.href),cancel=root.querySelector('[data-muatan-cancel]');
   if(cancel&&back.origin===location.origin&&old.startsWith('/')&&!old.startsWith('//'))cancel.href=back.pathname+back.search;
   if(work)for(const a of doc.querySelectorAll('a.desktop-back,a.bar__balik'))a.href=work;
   root.dataset.buka=q.get('buka')||'';root.dataset.muatanTarget=id;frame.dataset.pindahAlamat=u.pathname+u.search;
   return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
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
 function qcDetailLangsung(pilihan,context,cap,token){
  const u=new URL(pilihan.alamat,location.href),match=/^\/riwayat-qc\/(gabah-basah|gabah-kering|pk-hasil-giling|pk-luar|beras-hasil-sosoh)\/([\w-]+)$/.exec(u.pathname);
  if(u.origin!==location.origin||!match||u.hash||u.search.length>3000)return null;
  const rice=match[1]==='beras-hasil-sosoh';
  const allowed=rice?['tab_qc']:['tab_qc','putaran','kembali_qc','kembali_jasa','kembali_stok','kembali_kerja'];
  if([...u.searchParams.keys()].some(k=>!allowed.includes(k)||u.searchParams.getAll(k).length!==1))return null;
  const host=document.getElementById('padi-qc-kerangka');let data;
  if(!host?.isConnected||host.dataset.konteks!==context||host.dataset.cap!==cap||host.textContent.length>1572864)return null;
  try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.konteks!==context||data.cap!==cap||data.sesi!==token||(rice?data.beras:data.detail)?.penyandian!=='baris-1')return null;
  const html=decodeFrame(rice?data.beras:data.detail,match[1]);if(!html)return null;
  const doc=new DOMParser().parseFromString(html,'text/html'),frame=doc.querySelector('.bingkai'),root=doc.querySelector(rice?'[data-qc-beras-shell]':'[data-qc-detail-shell]'),prototype=rice?'__QC_BERAS_REF__':'__QC_REF__';
  if(!frame||!root||(!rice&&root.dataset.qcKind!==match[1])||root.dataset.qcRef!==prototype||root.dataset.qcContext!==context||frame.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!=='/riwayat-qc/'+match[1]+'/'+prototype||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  frame.dataset.pindahAlamat=u.pathname+u.search;root.dataset.qcRef=match[2];root.querySelector(rice?'[data-qc-beras-reference]':'[data-qc-detail-reference]').textContent=match[2];
  const source=/^\/(?:riwayat-qc\/[\w-]+|pekerjaan|stok(?:\/pk\/detail)?|stok-pk-jasa|barang-masuk(?:\/\d+)?|jasa(?:\/pelanggan\/\d+)?|riwayat-(?:giling|pengeringan|sosoh|transfer)(?:\/\d+)?|proses-aktif\/(?:giling|pengeringan|pendinginan|sosoh)\/[\w-]+)$/;
  let back=source.test(location.pathname)?location.pathname+location.search:'/riwayat-qc/'+match[1];
  for(const key of ['kembali_qc','kembali_jasa','kembali_stok','kembali_kerja']){const raw=u.searchParams.get(key);if(!raw)continue;const candidate=new URL(raw,location.href);if(raw.startsWith('/')&&!raw.startsWith('//')&&candidate.origin===location.origin&&source.test(candidate.pathname)){back=raw;break;}}
  if(!rice)root.querySelector('[data-qc-detail-back]').href=back;
  for(const a of root.querySelectorAll('.rhs-tabs a')){const link=new URL(u);link.searchParams.set('tab_qc',a.id.slice(7));a.href=link.pathname+link.search;}
  const title=rice?'QC beras hasil sosoh':'Detail QC '+match[2];doc.title=title;const brand=doc.querySelector('.bar__merek');if(brand){brand.textContent=title;brand.setAttribute('aria-label',title);}
  const crumb=doc.querySelector('.desktop-chrome__crumbrow .desktop-breadcrumb [aria-current="page"]');if(crumb)crumb.textContent=title;
  return {versi:1,alamat:u.pathname+u.search,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
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
  if(!Object.prototype.hasOwnProperty.call(registry.frames,pilihan.alamat))return jasaStokLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||jasaProsesLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||jasaPenerimaanLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||jasaRingkasanLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||kemasUlangLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||perbaikanLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||pengambilanLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||pengirimanDetailLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||muatanLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||pekerjaanLainLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||returDaftarLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||returDetailLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||stokLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||karungDetailLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||riwayatLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||berandaLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||qcLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||qcDetailLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||kabarLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||laporanLangsung(pilihan,registry.konteks,cap,sesi.dataset.token)||detailLangsung(pilihan,registry.konteks,cap);
  // Validasi seluruh indeks dan ukuran sebelum join. Versi/rujukan rusak
  // kembali ke navigasi native, bukan HTML parsial atau alamat tebakan.
  const html=decodeFrame(registry,pilihan.alamat);if(!html)return null;
  return {versi:1,alamat:pilihan.alamat,konteks:registry.konteks,cap:cap,html};
 });
})();
