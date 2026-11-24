/* Filtered native list structures from the current private registry only.
 * No JSON stamp, data cache, row grants, alias dispatcher or transaction. */
(function(global){
 'use strict';
 const COMMON=['jenis','kepemilikan','gudang','pemasok','cari','pelanggan_id','kembali_jasa','halaman'];
 const FIELDS={'/barang-masuk':['status',...COMMON],'/pekerjaan':['tab',...COMMON,'asal','kategori','grup','informasi']};
 const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
 function address(value,origin){
  if(typeof value!=='string'||typeof origin!=='string'||!value.startsWith('/')||value.startsWith('//')||value.length>4096||/%(?![0-9a-f]{2})/i.test(value))return null;
  let u;try{u=new URL(value,origin);decodeURIComponent(u.search.replace(/\+/g,' '));}catch(_){return null;}
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||!own(FIELDS,u.pathname)||u.search.length>3001)return null;
  const q=u.searchParams,pairs=[...q];if(pairs.length>FIELDS[u.pathname].length||new Set(pairs.map(p=>p[0])).size!==pairs.length||pairs.some(p=>!FIELDS[u.pathname].includes(p[0])))return null;
  if(['cari','pemasok'].some(k=>(q.get(k)||'').length>200)||!['','g1','g2'].includes(q.get('gudang')||'')||!['','jasa','pabrik'].includes(q.get('kepemilikan')||''))return null;
  if(['jenis','asal','kategori','grup'].some(k=>q.get(k)&&!/^[A-Za-z0-9_-]{1,80}$/.test(q.get(k)))||!['','1'].includes(q.get('informasi')||''))return null;
  if(['pelanggan_id','halaman'].some(k=>q.get(k)&&(!/^[0-9]+$/.test(q.get(k))||Number(q.get(k))<1||Number(q.get(k))>2147483647)))return null;
  const back=q.get('kembali_jasa');if(back){let b;try{b=new URL(back,origin);}catch(_){return null;}if(back.length>1500||!back.startsWith('/')||back.startsWith('//')||b.origin!==origin||b.hash||!/^\/jasa(?:\/pelanggan\/[1-9][0-9]*)?$/.test(b.pathname))return null;}
  const masuk=u.pathname==='/barang-masuk',selection=q.get(masuk?'status':'tab')??(masuk?'belum':'tindakan');
  if(!(masuk?['belum','diterima']:['tindakan','berjalan']).includes(selection))return null;
  return {u,path:u.pathname,address:value,family:masuk?'masuk':'pekerjaan',selection,prototype:masuk?'/barang-masuk?status='+selection:'/pekerjaan?tab='+selection,pairs};
 }
 function baseAddress(value,origin){return address(value,origin)?.prototype||null;}
 const encode=value=>encodeURIComponent(String(value)).replace(/[!'()*]/g,c=>'%'+c.charCodeAt(0).toString(16).toUpperCase()).replace(/%20/g,'+');
 function nativeLink(state,changes={}){
  const q=new Map(state.pairs);for(const k of ['buka','nilai','halaman'])q.delete(k);
  for(const [k,v]of Object.entries(changes))q.set(k,v);
  return state.path+'?'+[...q].filter(p=>p[1]).map(p=>encode(p[0])+'='+encode(p[1])).join('&');
 }
 function choose(select,value){
  if(!select)return false;
  const option=[...select.options].find(o=>o.value===value&&!o.disabled);if(!option)return false;
  for(const o of select.options){o.selected=o===option;o.toggleAttribute('selected',o===option);}select.value=value;return true;
 }
 function hidden(doc,form,name,value){const n=doc.createElement('input');n.type='hidden';n.name=name;n.setAttribute('value',value);form.append(n);}
 function nativeTabs(doc,main,state){
  const masuk=state.family==='masuk',key=masuk?'status':'tab',choices=masuk?['belum','diterima']:['tindakan','berjalan'];
  const target=k=>nativeLink(state,masuk?{status:k,halaman:''}:{tab:k,asal:'',kategori:'',grup:'',informasi:''});
  for(const a of main.querySelectorAll('nav[aria-label="Tab pekerjaan"] a[href],nav[aria-label="Status penerimaan"] a[href],nav[aria-label="Bagian Barang Masuk"] a[href]')){
   const u=new URL(a.getAttribute('href'),location.origin);if(u.origin!==location.origin||u.pathname!==state.path)continue;
   const selected=u.searchParams.get(key)||(masuk?'belum':'tindakan');if(!choices.includes(selected))return false;
   a.setAttribute('href',target(selected));a.removeAttribute('data-utuh');a.toggleAttribute('aria-current',selected===state.selection);if(selected===state.selection)a.setAttribute('aria-current','page');
  }
  const nav=main.querySelector('[data-laporan-kontrol]');if(nav){
   let tabs;try{tabs=JSON.parse(nav.dataset.tujuanTab||'null');}catch(_){return false;}
   if(!Array.isArray(tabs)||tabs.length!==3)return false;
   for(const tab of tabs){if(!tab||typeof tab.kunci!=='string')return false;if(choices.includes(tab.kunci))tab.href=target(tab.kunci);else if(!masuk&&tab.kunci==='lain')tab.href='/pekerjaan/catat-lain?kembali='+encode(nativeLink(state));}
   nav.dataset.aktif=state.selection;nav.dataset.tujuanTab=JSON.stringify(tabs);
   for(const a of nav.querySelectorAll('a[data-tab-riwayat="lain"]'))if(!masuk)a.setAttribute('href','/pekerjaan/catat-lain?kembali='+encode(nativeLink(state)));
  }
  return true;
 }
 function buat(target,base,context,cap,token){
  const state=address(target,location.origin);if(!global.PADI_BACA_NATIVE?.mount||!state||typeof base!=='string'||base.length>8388608||![context,cap,token].every(v=>typeof v==='string'&&v&&v.length<=512)||!/^[A-Za-z0-9._-]+$/.test(cap))return null;
  const liveFrame=document.querySelector('.bingkai');
  if(document.documentElement.dataset.versi!==cap||liveFrame?.dataset.pindahKonteks!==context||document.getElementById('formulir-sesi')?.dataset.token!==token||document.querySelector('[data-editor-perintah],[data-kemas-ulang]')||window.SESIFORM&&!SESIFORM.periksa())return null;
  const doc=new DOMParser().parseFromString(base,'text/html');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1)return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const prototypes=state.family==='masuk'?['/barang-masuk?status='+state.selection,...(state.selection==='belum'?['/barang-masuk']:[])]:['/pekerjaan?tab='+state.selection,...(state.selection==='tindakan'?['/pekerjaan']:[])];
  if(!prototypes.includes(frame.dataset.pindahAlamat))return null;
  const roots=main.querySelectorAll(state.family==='masuk'?'[data-bm-page][data-bm-shell]':'[data-halaman-bertahap][data-kind="pekerjaan"]');if(roots.length!==1)return null;
  const root=roots[0];
  if(state.family==='masuk'&&root.dataset.bmStatus!==state.selection)return null;
  const nodes=[...main.childNodes],from=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),to=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(from.length!==1||to.length!==1||!(from[0].compareDocumentPosition(to[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const q=state.u.searchParams,searchText=state.family==='masuk'?(q.get('cari')||'').trim():(q.get('cari')||''),formSelector=state.family==='masuk'?'.bm-form-filter':'.pk-form-filter',filter=root.querySelector(formSelector),search=root.querySelector('form[role="search"]');
  if(!filter||!search)return null;
  for(const k of ['jenis','kepemilikan'])if(!choose(filter.querySelector('select[name="'+k+'"]'),q.get(k)||''))return null;
  const warehouse=filter.querySelector('select[name=gudang]');if(warehouse&&!choose(warehouse,q.get('gudang')||''))return null;
  // Remote names are not inferred from a query ID or a prior list. Preserve
  // their read-filter value as hidden data and label it explicitly unread.
  const supplier=q.get('pemasok')||'';
  for(const form of [filter,search]){
   for(const n of form.querySelectorAll('input[type=hidden]'))n.remove();
   for(const n of form.querySelectorAll('input[name=cari]'))n.setAttribute('value',searchText);
   for(const select of form.querySelectorAll('select[name=pemasok]')){
    while(select.options.length)select.remove(0);const option=doc.createElement('option');option.value=supplier;option.textContent=supplier?'Nama terpilih belum dibaca':'Semua nama';option.selected=true;option.setAttribute('selected','');select.append(option);select.disabled=true;
   }
   const allowed=form===search?(state.family==='masuk'?['status','jenis','kepemilikan','gudang','pelanggan_id','kembali_jasa']:FIELDS[state.path].filter(k=>!['cari','halaman'].includes(k))):(state.family==='masuk'?['status','cari','pelanggan_id','kembali_jasa']:['tab','cari','pelanggan_id','kembali_jasa','informasi','asal','kategori','grup']);
   for(const k of allowed){const v=k===(state.family==='masuk'?'status':'tab')?state.selection:q.get(k);if(v)hidden(doc,form,k,v);}
   if(supplier)hidden(doc,form,'pemasok',supplier);
   if(form===filter&&!warehouse&&q.get('gudang'))hidden(doc,form,'gudang',q.get('gudang'));
  }
  if(!nativeTabs(doc,main,state))return null;
  const reset=filter.querySelector('a[href]');if(reset)reset.setAttribute('href',nativeLink(state,{jenis:'',kepemilikan:'',gudang:'',pemasok:''}));
  const count=['jenis','kepemilikan','gudang','pemasok'].reduce((n,k)=>n+Number(!!q.get(k)),0);
  const filterButton=root.querySelector('.kontrol-pencarian>button');if(filterButton)filterButton.textContent='Filter'+(count?' · '+count:'');
  for(const b of root.querySelectorAll('[data-pk-buka="pk-filter"][aria-label],[data-bm-buka="bm-filter"][aria-label]'))b.setAttribute('aria-label','Buka filter'+(count?' · '+count+' aktif':''));
  for(const n of root.querySelectorAll('[data-bm-bootstrap]'))n.remove();
  if(state.family==='masuk'){
   root.dataset.cariTertampil=searchText;root.dataset.pemasokTertampil=supplier;root.dataset.siap='1';
   root.removeAttribute('data-bm-stamp');root.removeAttribute('data-bm-url');
   const result=root.querySelector('.bm-jumlah');if(!result)return null;result.replaceChildren();const strong=doc.createElement('strong');strong.textContent='Jumlah hasil belum tersedia';result.append(strong);if(searchText){result.append(doc.createTextNode(' untuk “'+searchText+'” · '));const span=doc.createElement('span');span.setAttribute('data-bm-nav','');const link=doc.createElement('a');link.href=nativeLink(state,{cari:''});link.textContent='Hapus pencarian';span.append(link);result.append(span);}
  }else root.dataset.ready='1';
  root.setAttribute('data-filter-daftar-native',state.family);root.dataset.url=target;root.dataset.stamp=context+'|'+target;
  const detail=doc.createElement('p');detail.className='bantu';detail.setAttribute('data-filter-daftar-pending','');detail.textContent='Data, jumlah dan batas halaman menunggu pembacaan terbaru.'+(q.get('pelanggan_id')?' Filter pelanggan ID '+q.get('pelanggan_id')+' belum dibaca.':'');root.append(detail);
  // Retire only the old JSON shell reader in this isolated derived frame.
  // Native fresh HTML always receives its original unmodified controllers.
  for(const script of doc.querySelectorAll('script[src]')){
   const u=new URL(script.getAttribute('src'),location.origin);
   if(['/static/halaman-bertahap.js','/static/barang-masuk-pencarian.js'].includes(u.pathname))script.remove();
  }
  frame.dataset.pindahAlamat=target;
  const init=doc.createElement('script');init.textContent='window.PadiFilterDaftarNative?.mount();';to[0].before(init);
  return {versi:1,alamat:target,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function mount(){
  const root=document.querySelector('[data-filter-daftar-native]');if(!root||!address(root.dataset.url,location.origin)||root.dataset.filterDaftarReady)return;
  root.dataset.filterDaftarReady='1';const masuk=root.dataset.filterDaftarNative==='masuk',status=masuk?'[data-bm-read-status]':'[data-shell-status]',retry=masuk?'[data-bm-retry]':'[data-shell-retry]';
  const currentStatus=root.querySelector(status),currentRetry=root.querySelector(retry);if(!currentStatus||!currentRetry)return;
  const reader=global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-filter-daftar-native]',statusSelector:status,retrySelector:retry,shellSelector:'[data-filter-daftar-native]',contentAttribute:'data-filter-daftar-isi',
   onFailure(){const box=root.querySelector('[data-bm-error]');if(box)box.hidden=false;for(const node of root.querySelectorAll('[data-bm-state-message],[data-shell-message]'))node.textContent='Daftar gagal dibaca; ini bukan hasil kosong. Coba lagi hanya membaca data.';}});
  if(!reader)return;
  function changed(){reader.stop();currentRetry.hidden=true;currentStatus.textContent='Pilihan berubah. Tekan Cari atau Terapkan filter untuk membaca pilihan terbaru; isian tetap dipertahankan.';}
  for(const form of root.querySelectorAll('form[method=get]')){form.addEventListener('input',changed);form.addEventListener('change',changed);}
  currentRetry.addEventListener('click',()=>{const box=root.querySelector('[data-bm-error]');if(box)box.hidden=true;},true);
 }
 if(typeof module==='object'&&module.exports){module.exports={address,nativeLink,choose,baseAddress};return;}
 global.PadiFilterDaftarNative=Object.freeze({versi:1,buat,mount,baseAddress});
})(typeof window==='undefined'?globalThis:window);
