/* Report-only GET adapter. Native server owns authorization, dates and values. */
(function(global){
 'use strict';
 const CODES=['gabah_masuk','pk_masuk','penyosohan','penggilingan','pengeringan','pemasukan_pk','pindah_pk','pengemasan','kemas_ulang','barang_keluar','retur_pelanggan','retur_pk'];
 function allowed(address,origin){
  if(typeof address!=='string'||!address.startsWith('/')||address.startsWith('//'))return false;
  let u;try{u=new URL(address,origin);}catch(_){return false;}
  if(u.origin!==origin||u.hash||u.pathname+u.search!==address||u.search.length>2049)return false;
  if(!CODES.some(code=>u.pathname==='/laporan/'+code))return false;
  const keys=[...u.searchParams.keys()];return new Set(keys).size===keys.length&&keys.every(k=>['periode','dari','sampai'].includes(k));
 }
 function emptySpec(data,code){
  if(!CODES.includes(code)||!data||data.kode!==code||!Array.isArray(data.rincian))throw Error('Struktur laporan tidak sesuai tujuan.');
  if(data.rincian.length)return null;
  if(!Array.isArray(data.kolom)||!data.kolom.length||!Array.isArray(data.kepala_tabel)||!data.kepala_tabel.length)throw Error('Kolom laporan belum tersedia.');
  const count=data.kolom.length;
  if(data.kolom.some(c=>!c||typeof c.nama!=='string'||typeof c.kunci!=='string')||
     data.kepala_tabel.some(row=>!Array.isArray(row)||row.some(c=>!c||typeof c.nama!=='string'||!Number.isInteger(c.kolom)||c.kolom<1||c.kolom>count||!Number.isInteger(c.baris)||c.baris<1||c.baris>data.kepala_tabel.length)))throw Error('Kepala laporan tidak sesuai kolom.');
  if(data.kepala_tabel[0].reduce((total,c)=>total+c.kolom,0)!==count)throw Error('Jumlah kolom laporan berubah.');
  // These are the actual fresh report schema objects, never computed output types.
  return {columns:data.kolom,headers:data.kepala_tabel};
 }
 function preserveEmptyTable(content,code){
  const source=content.querySelector('#laporan-data'),target=content.querySelector('#lap-isi');
  if(!source||!target)throw Error('Data laporan native belum tersedia.');
  const spec=emptySpec(JSON.parse(source.textContent),code);if(!spec)return false;
  if(target.querySelector('table'))return false;
  const message=[...target.children].find(el=>el.tagName==='P'&&el.textContent==='Tidak ada transaksi pada periode ini.');
  if(!message)throw Error('Keadaan kosong laporan native berubah.');
  const doc=content.ownerDocument,wrap=doc.createElement('div'),table=doc.createElement('table');wrap.className='lp-tabel';
  const caption=doc.createElement('caption');caption.className='lbl';caption.textContent='Rincian transaksi';table.append(caption);
  const head=doc.createElement('thead');
  for(const row of spec.headers){const tr=doc.createElement('tr');for(const cell of row){const th=doc.createElement('th');th.scope=cell.kolom>1?'colgroup':'col';th.colSpan=cell.kolom;th.rowSpan=cell.baris;th.textContent=cell.nama;tr.append(th);}head.append(tr);}
  const body=doc.createElement('tbody'),tr=doc.createElement('tr'),td=doc.createElement('td');td.colSpan=spec.columns.length;td.textContent=message.textContent;tr.append(td);body.append(tr);table.append(head,body);wrap.append(table);message.replaceWith(wrap);return true;
 }
 function controls(root,changed){
  const form=root.querySelector('form'),period=form.elements.periode,range=form.querySelector('.lp-rentang'),show=form.querySelector('.lp-tampilkan');
  root.querySelector('[data-lp-proses]').addEventListener('change',event=>{form.action=event.target.value;form.requestSubmit();});
  period.addEventListener('change',()=>{const custom=period.value==='khusus';range.hidden=!custom;show.hidden=!custom;range.querySelectorAll('input').forEach(el=>{el.disabled=!custom;el.required=custom;});if(custom)changed();else form.requestSubmit();});
  form.addEventListener('submit',event=>{changed();const start=form.elements.dari,end=form.elements.sampai;end.setCustomValidity('');if(period.value==='khusus'&&start.value>end.value){event.preventDefault();end.setCustomValidity('Tanggal akhir harus sama atau setelah tanggal awal.');end.reportValidity();}});
  range.querySelectorAll('input').forEach(el=>el.addEventListener('input',()=>{form.elements.sampai.setCustomValidity('');changed();}));
  const guide=root.querySelector('#lp-panduan');root.querySelector('[data-lp-panduan]').addEventListener('click',()=>guide.showModal());root.querySelector('[data-lp-tutup]').addEventListener('click',()=>guide.close());
 }
 const api={allowed,emptySpec,preserveEmptyTable,controls};
 if(typeof module==='object'&&module.exports){module.exports=api;return;}
 const root=document.querySelector('[data-laporan-detail-native]');if(!root||!allowed(root.dataset.url,location.origin))return;
 const code=new URL(root.dataset.url,location.origin).pathname.slice('/laporan/'.length);
 const reader=global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-laporan-detail-native]',
  statusSelector:'[data-detail-native-status]',retrySelector:'[data-detail-native-retry]',
  messages:{loading:'Memuat laporan. Ringkasan dan rincian belum dibaca.',response:'Laporan belum dapat dibaca. Muat ulang bila sesi atau akses berubah.',native:'Laporan native belum tersedia. Coba lagi hanya membaca data.',timeout:'Pembacaan laporan terlalu lama. Coba lagi hanya membaca data.'},
  afterInstall({content}){preserveEmptyTable(content,code);},
  restoreFocus({focus,retry,content}){if(focus===retry)content.querySelector('[data-lp-panduan]')?.focus({preventScroll:true});}
 });
 controls(root,()=>{
  // Custom dates are a GET-filter draft. Do not let the old range replace it
  // after focus leaves the input; only Tampilkan/navigating reads that range.
  reader?.stop();root.querySelector('[data-detail-native-retry]').hidden=true;
  root.querySelector('[data-detail-native-status]').textContent='Pilihan periode berubah. Pilih Tampilkan untuk membaca rentang tanggal, atau pilih periode lainnya.';
 });
})(typeof window==='undefined'?globalThis:window);
