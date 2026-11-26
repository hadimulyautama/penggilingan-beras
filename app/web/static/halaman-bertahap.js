/* Hanya dua halaman daftar. Angka/tindakan tetap hasil renderer native.
 * Adapter tidak menulis transaksi dan tidak menyimpan HTML/data di cache.
 */
(function () {
 'use strict';
 const root=document.querySelector('[data-halaman-bertahap]');
 if(!root||root.dataset.ready)return;root.dataset.ready='1';
 const main=document.getElementById('isi-halaman'),status=root.querySelector('[data-shell-status]'),retry=root.querySelector('[data-shell-retry]'),table=root.querySelector('[data-shell-table-wrap]'),message=root.querySelector('[data-shell-message]');
 const detail=root.dataset.kind==='barang-masuk-detail';
 const beranda=root.dataset.kind==='beranda';
 const kabar=root.dataset.kind==='kabar';
 const qc=['qc-gabah-basah','qc-gabah-kering','qc-pk-hasil-giling','qc-pk-luar','qc-beras-hasil-sosoh'].includes(root.dataset.kind);
 const riwayat=['riwayat-sosoh','riwayat-giling','riwayat-pengeringan'].includes(root.dataset.kind);
 function berandaIslands(content){
  if(!beranda)return null;
  // Pembacaan awal diterapkan utuh. Native tetap mengirim bagian parsial,
  // tetapi shell menandainya gagal dan menyediakan satu retry GET; tidak
  // menampilkan angka nol atau campuran data lama sebagai hasil lengkap.
  if(content.querySelector('.pesan--hati[role="alert"]'))throw Error('Sebagian keadaan pabrik belum dapat dibaca. Coba lagi hanya membaca, tanpa mencatat transaksi.');
  const selectors=['.beranda-sambut','.beranda-kolom','.beranda-tindaklanjut','.beranda-aktivitas','.beranda-ringkasan'];
  const parts=selectors.map(selector=>({old:root.querySelector(selector),fresh:content.querySelector(selector)}));
  if(parts.some(p=>!p.old||!p.fresh))throw Error('Struktur Beranda berubah. Muat ulang halaman.');
  const oldTitle=root.querySelector('#judul-beranda'),nextTitle=content.querySelector('#judul-beranda');
  const oldNeeds=root.querySelector('.beranda-tindaklanjut>h2.lbl'),nextNeeds=content.querySelector('.beranda-tindaklanjut>h2.lbl');
  if(!oldTitle||!nextTitle||!oldNeeds||!nextNeeds||oldNeeds.textContent!==nextNeeds.textContent)throw Error('Judul Beranda belum sesuai. Coba lagi.');
  const oldSites=Array.from(root.querySelectorAll('[data-alur-gudang]')),nextSites=Array.from(content.querySelectorAll('[data-alur-gudang]'));
  const headerShape=n=>({key:n.dataset.alurGudang,code:n.querySelector('.alur-gudang__kode')?.textContent.trim(),name:n.querySelector('.alur-gudang__kepala p')?.textContent.trim(),title:n.querySelector('.alur-gudang__kepala h2')?.textContent.trim(),links:Array.from(n.querySelectorAll('.alur-gudang__kepala a'),a=>a.getAttribute('href'))});
  if(JSON.stringify(oldSites.map(headerShape))!==JSON.stringify(nextSites.map(headerShape)))throw Error('Cakupan ringkasan gudang berubah. Muat ulang halaman.');
  return {parts,oldTitle,nextTitle,oldNeeds,nextNeeds,oldSites,nextSites};
 }
 function retainBeranda(island){
  if(!island)return;
  const {parts,oldTitle,nextTitle,oldNeeds,nextNeeds,oldSites,nextSites}=island;
  oldTitle.textContent=nextTitle.textContent;nextTitle.replaceWith(oldTitle);nextNeeds.replaceWith(oldNeeds);
  // Nilai dan baris berasal dari renderer native. Hanya node struktur dan
  // tautan gudang yang sudah tervalidasi dipertahankan, bukan hasil lama.
  oldSites.forEach((old,i)=>{
   const fresh=nextSites[i],head=old.querySelector('.alur-gudang__kepala');
   fresh.querySelector('.alur-gudang__kepala').replaceWith(head);
   old.replaceChildren(...Array.from(fresh.childNodes));fresh.replaceWith(old);
  });
  // Aktivitas kosong tetap memiliki judul bagian; angka belum dibaca tidak
  // pernah dipakai memutuskan apakah ada proses atau tindakan.
  const activity=parts[3],heading=activity.old.querySelector('[data-beranda-judul-aktivitas]');
  if(heading){
   const native=Array.from(activity.fresh.querySelectorAll('[data-blok]>.lbl')).find(n=>n.textContent.trim().startsWith('Sedang berjalan ·'));
   if(native){heading.replaceChildren(...Array.from(native.childNodes));native.replaceWith(heading);}
   else activity.fresh.prepend(heading);
  }
  // Anak dahulu supaya wrapper kolom memegang kembali bagian yang sama.
  for(const i of [2,3,1,4,0]){const {old,fresh}=parts[i];old.className=fresh.className;old.replaceChildren(...Array.from(fresh.childNodes));fresh.replaceWith(old);}
 }
 function riwayatIslands(content){
  if(!riwayat)return null;
  const old=root.closest('.laporan-riwayat'),fresh=content.querySelector('.laporan-riwayat');
  if(!old||!fresh)throw Error('Struktur Riwayat berubah. Muat ulang halaman.');
  const nav=old.querySelector('[data-laporan-kontrol]'),nextNav=fresh.querySelector('[data-laporan-kontrol]');
  const schema=node=>JSON.stringify({
   active:node?.dataset.aktif,allowed:node?.dataset.bolehAlamat,tabs:node?.dataset.tujuanTab,
   options:Array.from(node?.querySelectorAll('[data-jenis-riwayat] option')||[],o=>[o.value,o.textContent,o.disabled]),
   category:Array.from(node?.querySelectorAll('.laporan-nav__jenis a')||[],a=>[a.getAttribute('href'),a.textContent,a.getAttribute('aria-current')])
  });
  if(!nav||!nextNav||schema(nav)!==schema(nextNav))throw Error('Akses atau jenis Riwayat berubah. Muat ulang halaman.');
  // Bookmark tab yang berizin boleh berbeda dari href default native.
  const tabs=JSON.parse(nav.dataset.tujuanTab||'[]');
  for(const link of nav.querySelectorAll('[data-tab-riwayat]')){
   const tab=tabs.find(t=>t.kunci===link.dataset.tabRiwayat),u=new URL(link.href,location.href);
   if(!tab?.boleh||u.origin!==location.origin||u.search||u.hash||!tab.alamat.includes(u.pathname))throw Error('Tujuan Riwayat berubah. Muat ulang halaman.');
  }
  const stats=old.querySelector('.rpd-intro'),nextStats=fresh.querySelector('.rpd-intro');
  const labels=n=>Array.from(n?.querySelectorAll('.rpd-stats>div>span')||[],s=>s.textContent);
  if(!stats||!nextStats||labels(stats).length!==3||stats.querySelectorAll('strong').length!==3||nextStats.querySelectorAll('strong').length!==3||JSON.stringify(labels(stats))!==JSON.stringify(labels(nextStats)))throw Error('Ringkasan Riwayat berubah. Coba lagi.');
  const headerSelector='.riwayat-desktop-list>.riwayat-desktop-head,.riwayat-desktop-list>table>thead';
  const head=old.querySelector(headerSelector),nextHead=fresh.querySelector(headerSelector);
  const columns=n=>Array.from(n?.querySelectorAll('span,th')||[],c=>c.textContent.trim());
  if(!head||!nextHead||head.tagName!==nextHead.tagName||JSON.stringify(columns(head))!==JSON.stringify(columns(nextHead)))throw Error('Kolom Riwayat berubah. Muat ulang halaman.');
  const guide=old.querySelector('#rpd-panduan'),nextGuide=fresh.querySelector('#rpd-panduan'),body=old.querySelector('.laporan-isi'),nextBody=fresh.querySelector('.laporan-isi');
  if(!guide?.querySelector('.pd-panduan__isi')||!nextGuide?.querySelector('.pd-panduan__isi')||!body||!nextBody||nav.querySelectorAll('[data-lk-cetak]').length!==nextNav.querySelectorAll('[data-lk-cetak]').length)throw Error('Kontrol Riwayat belum lengkap. Coba lagi.');
  return {old,fresh,nav,nextNav,stats,nextStats,head,nextHead,guide,nextGuide,body,nextBody,styles:Array.from(old.querySelectorAll('style[data-riwayat-aset-native]'),s=>s.cloneNode(true))};
 }
 function retainRiwayat(island){
  if(!island)return;
  const {old,fresh,nav,nextNav,stats,nextStats,head,nextHead,guide,nextGuide,body,nextBody,styles}=island;
  const values=nextStats.querySelectorAll('strong');
  stats.querySelectorAll('strong').forEach((s,i)=>{s.textContent=values[i].textContent;});
  nextStats.replaceWith(stats);nextHead.replaceWith(head);
  const guideBody=guide.querySelector('.pd-panduan__isi'),nextGuideBody=nextGuide.querySelector('.pd-panduan__isi');
  guideBody.replaceChildren(...Array.from(nextGuideBody.childNodes));nextGuide.replaceWith(guide);
  const before=nav.querySelectorAll('[data-lk-cetak]'),after=nextNav.querySelectorAll('[data-lk-cetak]');
  before.forEach((b,i)=>{for(const attr of ['disabled','aria-describedby']){if(after[i].hasAttribute(attr))b.setAttribute(attr,after[i].getAttribute(attr));else b.removeAttribute(attr);}});
  // Controller navigasi native memegang scope wrapper. Pertahankan wrapper,
  // nav dan panduan yang sama; hanya data/statistik dan baris yang berubah.
  body.replaceChildren(...Array.from(nextBody.childNodes));
  for(const style of styles)if(!Array.from(old.querySelectorAll('style[data-riwayat-aset-native]')).some(s=>s.dataset.riwayatAsetNative===style.dataset.riwayatAsetNative))old.prepend(style);
  fresh.replaceWith(old);
 }
 function addressNow(){const u=new URL(location.href);if(detail)u.searchParams.delete('tab_detail');return u.pathname+u.search;}
 const address=addressNow(),token=document.getElementById('formulir-sesi')?.dataset.token||'',stamp=root.dataset.stamp;
 function formState(form){const values=new URLSearchParams(new FormData(form));if(root.dataset.kind==='stok')values.sort();return values.toString();}
 const forms=Array.from(root.querySelectorAll('form')),initialForms=forms.map(formState);
 let sequence=0,controller=null,pending=null,finished=false,readFromRetry=false;
 function current(number){return root.isConnected&&number===sequence&&addressNow()===address&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
 function stop(){++sequence;pending=null;if(controller)controller.abort();controller=null;observer.disconnect();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});
 observer.observe(document.body,{childList:true,subtree:true});
 function controlsChanged(){return forms.some((f,i)=>formState(f)!==initialForms[i]);}
 function interacting(){return controlsChanged()||!!root.querySelector('details[open],dialog[open]')||root.contains(document.activeElement)&&/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);}
 function markers(element){const nodes=Array.from(element.childNodes);return [nodes.find(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),nodes.find(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir')];}
 async function prepareScripts(container,doc,signal){
  const release=doc.documentElement.getAttribute('data-versi');
  if(release!==document.documentElement.getAttribute('data-versi'))throw Error('Versi aplikasi berubah. Muat ulang halaman sebelum melanjutkan.');
  const result=[];
  for(const old of container.querySelectorAll('script')){
   const type=(old.getAttribute('type')||'').toLowerCase();
   if(type==='application/json')continue;
   if(type&&!['text/javascript','application/javascript'].includes(type))throw Error('Jenis kontrol halaman belum didukung. Muat ulang halaman.');
   let text=old.textContent;
   if(old.hasAttribute('src')){
    const url=new URL(old.getAttribute('src'),location.href);
    if(url.origin!==location.origin||!url.pathname.startsWith('/static/')||url.searchParams.has('v')&&url.searchParams.get('v')!==release)throw Error('Versi kontrol halaman tidak sesuai. Muat ulang halaman.');
    const response=await fetch(url.pathname+url.search,{credentials:'same-origin',signal});
    const mime=(response.headers.get('content-type')||'').split(';')[0];
    if(!response.ok||response.redirected||!['text/javascript','application/javascript'].includes(mime))throw Error('Kontrol halaman belum dapat dimuat. Coba lagi tanpa mengirim transaksi.');
    text=await response.text();
   }
   result.push({old,text});
  }
  return result;
 }
 function activateScripts(prepared){
  // Semua asset sudah dibaca sebelum swap. Tidak ada jeda async yang dapat
  // menjalankan kontrol halaman lama setelah pengguna pindah menu.
  for(const item of prepared){
   if((riwayat||qc||kabar)&&!item.old.isConnected)continue;
   const script=document.createElement('script');
   for(const a of item.old.attributes)if(!['src','defer','async'].includes(a.name))script.setAttribute(a.name,a.value);
   script.textContent=item.text;item.old.replaceWith(script);
  }
 }
 function restoreSemanticFocus(previous,content){
  if(document.activeElement!==document.body)return;
  // Pulau kontrol tetap memakai node semula, tetapi memindahkannya melalui
  // dokumen detached melepas fokus browser. Pulihkan node yang benar-benar
  // dipertahankan dahulu; jangan menebak kontrol lain dari nama kelasnya.
  if(previous?.isConnected&&content.contains(previous)&&!previous.matches(':disabled')&&!previous.closest('[hidden]')){
   previous.focus({preventScroll:true});return;
  }
  let target=null;
  if(detail&&previous?.hasAttribute('data-bm-tab'))target=content.querySelector('[data-bm-tab="'+CSS.escape(previous.dataset.bmTab)+'"]');
  else if(detail&&previous?.matches('.bm-table-scroll'))target=content.querySelector('.bm-table-scroll')||content.querySelector('[data-bm-tab][aria-selected="true"]');
  else if(previous?.hasAttribute('data-pk-buka'))target=content.querySelector('[data-pk-buka="'+CSS.escape(previous.dataset.pkBuka)+'"]');
  else if(previous?.hasAttribute('data-lk-buka'))target=content.querySelector('[data-lk-buka="'+CSS.escape(previous.dataset.lkBuka)+'"]');
  else if(previous?.hasAttribute('data-shell-guide'))target=content.querySelector('[data-sk-buka="sk-panduan"]');
  else if(root.dataset.kind==='stok'&&previous?.matches('.kontrol-pencarian__submit'))target=content.querySelector('[data-stok-controls] .kontrol-pencarian__submit');
  else if(root.dataset.kind==='stok'&&previous?.hasAttribute('data-sk-buka'))target=content.querySelector('[data-sk-buka="'+CSS.escape(previous.dataset.skBuka)+'"]');
  else if(root.dataset.kind==='stok'&&previous===table){target=content.querySelector('[data-daftar-kosong]');if(!target){content.tabIndex=-1;content.setAttribute('aria-label','Daftar Stok');target=content;}}
  else if(previous?.matches('.halaman-bertahap__filter>summary'))target=content.querySelector('[data-pk-buka="pk-filter"],[data-sk-buka="sk-filter"]');
  else if(previous===retry||previous===document.body&&readFromRetry){content.tabIndex=-1;content.setAttribute('aria-label',detail?'Detail penerimaan':riwayat?root.dataset.riwayatLabel:qc?root.dataset.qcLabel:kabar?'Kabar':beranda?'Beranda':'Daftar '+(root.dataset.kind==='pekerjaan'?'Pekerjaan':'Stok'));target=content;}
  target?.focus({preventScroll:true});
 }
 // Satu pulau kontrol native, bukan morph umum formulir transaksi.
 // Ketidakcocokan struktur berhenti sebelum menyentuh kontrol yang terlihat.
 function controlIsland(content){
  const selector=root.dataset.kind==='pekerjaan'?'.pk-kepala':root.dataset.kind==='stok'?'[data-stok-controls]':null;
  if(!selector)return null;
  const old=root.querySelector(selector),fresh=content.querySelector(selector);
  if(!old||!fresh)throw Error('Struktur kontrol berubah. Muat ulang halaman.');
  const schema=node=>JSON.stringify({
   forms:Array.from(node.querySelectorAll('form')).map(f=>[(f.getAttribute('method')||'get').toLowerCase(),f.getAttribute('action'),Array.from(new Set(Array.from(f.querySelectorAll('[name]')).map(n=>n.name))).sort()]),
   links:Array.from(node.querySelectorAll('a[href]')).map(a=>a.getAttribute('href')),
   dialogs:Array.from(node.querySelectorAll('dialog')).map(d=>d.id),
   scopeLabels:node.querySelectorAll('.sk-cakupan').length,
  });
  if(schema(old)!==schema(fresh))throw Error('Cakupan kontrol berubah. Muat ulang halaman.');
  let tabs=null;
  if(root.dataset.kind==='pekerjaan'){
   const selector='nav[aria-label="Tab pekerjaan"]',before=[],after=content.querySelectorAll(selector);
   const [start,end]=markers(main);
   if(!start||!end)throw Error('Batas tab pekerjaan berubah. Muat ulang halaman.');
   // LAPORAN_NAV menaruh tab di luar root daftar, tetapi tetap di dalam
   // batas isi native aktif. Header/sidebar di luar batas tidak dijaring.
   let node=start.nextSibling;
   for(;node&&node!==end;node=node.nextSibling){
    if(node.nodeType!==1)continue;
    if(node.matches(selector))before.push(node);
    before.push(...node.querySelectorAll(selector));
   }
   if(node!==end)throw Error('Batas tab pekerjaan berubah. Muat ulang halaman.');
   if(before.length!==1||after.length!==1||schema(before[0])!==schema(after[0])||old.contains(before[0])!==fresh.contains(after[0]))throw Error('Struktur tab pekerjaan berubah. Muat ulang halaman.');
   // Native browser dapat menempatkan tab sebagai saudara kepala kontrol.
   // Pertahankan pulau itu sendiri; jangan mencari atau membuat tab lain.
   if(!old.contains(before[0]))tabs={old:before[0],fresh:after[0]};
  }
  return {old,fresh,tabs};
 }
 function retainControls(island){
  if(!island)return;
  const {old,fresh,tabs}=island;
  // GET native yang sama menentukan angka/opsi. Ketikan dan panel terbuka
  // sudah ditahan oleh interacting(), juga sesudah seluruh aset selesai.
  for(const select of old.querySelectorAll('select[name]')){
   const native=fresh.querySelector('select[name="'+CSS.escape(select.name)+'"]');
   if(!native)continue;
   select.replaceChildren(...Array.from(native.options,o=>o.cloneNode(true)));select.value=native.value;
  }
  for(const selector of ['[data-pk-cetak]','[data-sk-cetak]','select[name]']){
   const controls=old.querySelectorAll(selector),native=fresh.querySelectorAll(selector);
   controls.forEach((control,i)=>{if(!native[i])return;for(const attr of ['disabled','aria-describedby']){if(native[i].hasAttribute(attr))control.setAttribute(attr,native[i].getAttribute(attr));else control.removeAttribute(attr);}});
  }
  const counts=old.querySelectorAll('.kontrol-tab__jumlah'),nativeCounts=fresh.querySelectorAll('.kontrol-tab__jumlah');
  counts.forEach((count,i)=>{if(nativeCounts[i])count.textContent=nativeCounts[i].textContent;});
  // Nama pemilik/lokasi mengikuti hasil baca tervalidasi, bukan placeholder
  // kerangka. Labelnya tetap node yang sama, tanpa memasang ulang kontrol.
  const scope=old.querySelector('.sk-cakupan'),nativeScope=fresh.querySelector('.sk-cakupan');
  if(scope&&nativeScope)scope.replaceChildren(...Array.from(nativeScope.childNodes));
  // Placeholder nama memiliki hidden fallback hanya selama select disabled.
  for(const input of old.querySelectorAll('input[type="hidden"][name]')){
   if(old.querySelector('select[name="'+CSS.escape(input.name)+'"]')&&!fresh.querySelector('input[type="hidden"][name="'+CSS.escape(input.name)+'"]'))input.remove();
  }
  for(const reason of old.querySelectorAll('[id^="shell-"]'))if(!fresh.querySelector('#'+CSS.escape(reason.id)))reason.remove();
  if(fresh.dataset.pelangganUrl)old.dataset.pelangganUrl=fresh.dataset.pelangganUrl;
  old.pfStockShellStop?.();
  if(tabs){
   const links=tabs.old.querySelectorAll('a[href]'),nativeLinks=tabs.fresh.querySelectorAll('a[href]');
   links.forEach((link,i)=>{
    for(const attr of ['class','aria-current']){if(nativeLinks[i].hasAttribute(attr))link.setAttribute(attr,nativeLinks[i].getAttribute(attr));else link.removeAttribute(attr);}
    const counts=link.querySelectorAll('.kontrol-tab__jumlah'),nativeCounts=nativeLinks[i].querySelectorAll('.kontrol-tab__jumlah');
    counts.forEach((count,j)=>{if(nativeCounts[j])count.textContent=nativeCounts[j].textContent;});
   });
   tabs.fresh.replaceWith(tabs.old);
  }
  fresh.replaceWith(old);
 }
 function stockTable(content){
  if(root.dataset.kind!=='stok')return null;
  const old=table.querySelector('table'),head=old?.querySelector('thead');if(!head)return null;
  const columns=n=>Array.from(n.querySelectorAll('th'),th=>th.textContent.trim().replace(/\s+/g,' '));
  const oldColumns=columns(head),native=Array.from(content.querySelectorAll('.stok-seragam table')).filter(candidate=>{
   const fresh=columns(candidate.querySelector('thead')||candidate);
   return fresh.length===oldColumns.length&&fresh.every((label,i)=>label===oldColumns[i]||i===fresh.length-1&&label===''&&oldColumns[i]==='Tindakan'&&candidate.classList.contains('stok-tabel'));
  });
  // Beberapa tabel pemilik tidak disatukan: hasil tetap markup native.
  return native.length===1?{old,head,fresh:native[0]}:null;
 }
 function retainTable(plan){
  if(!plan)return;
  const {old,head,fresh}=plan;
  // Identitas table/thead/kolom tetap; badan dan gaya persis renderer native.
  const nativeColumns=fresh.querySelectorAll('thead th');
  head.querySelectorAll('th').forEach((th,i)=>{
   th.textContent=nativeColumns[i].textContent;
   for(const attr of Array.from(th.attributes))th.removeAttribute(attr.name);
   for(const attr of nativeColumns[i].attributes)th.setAttribute(attr.name,attr.value);
  });
  for(const attr of Array.from(old.attributes))old.removeAttribute(attr.name);
  for(const attr of fresh.attributes)old.setAttribute(attr.name,attr.value);
  for(const child of Array.from(old.children))if(child!==head)child.remove();
  for(const child of Array.from(fresh.children))if(child.tagName!=='THEAD')old.append(child);
  fresh.replaceWith(old);
 }
 function detailIslands(content){
  if(!detail)return null;
  const fresh=content.querySelector('[data-bm-detail-shell][data-penerimaan-ringkas]');
  if(!fresh||content.querySelectorAll('[data-bm-detail-shell]').length!==1||root.hasAttribute('data-penerimaan-ringkas')||fresh.dataset.tiket!==location.pathname.split('/').pop()||!fresh.dataset.actor)throw Error('Profil detail berubah. Muat ulang halaman.');
  const keys=['ringkasan','tiket','qc','riwayat'];
  const tabs=node=>Array.from(node.querySelectorAll('[data-bm-tab]'));
  const before=tabs(root),after=tabs(fresh);
  if(before.length!==4||after.length!==4||keys.some((key,i)=>{
   const a=before[i],b=after[i];return a.dataset.bmTab!==key||b.dataset.bmTab!==key||a.id!==b.id||a.getAttribute('aria-controls')!==b.getAttribute('aria-controls')||a.dataset.url!==b.dataset.url||a.textContent.trim()!==b.textContent.trim();
  }))throw Error('Struktur tab detail berubah. Muat ulang halaman.');
  const selectors=['.bm-kepala','.bm-kepala h1','[role="tablist"]','[data-bm-detail-rincian]',...keys.map(key=>'#bm-panel-'+key)];
  for(const selector of selectors)if(root.querySelectorAll(selector).length!==1||fresh.querySelectorAll(selector).length!==1)throw Error('Struktur panel detail belum lengkap. Coba lagi.');
  if(root.querySelector('.bm-kepala h1').textContent.trim()!=='Detail penerimaan'||fresh.querySelector('.bm-kepala h1').textContent.trim()!=='Detail penerimaan')throw Error('Judul detail berubah. Muat ulang halaman.');
  const back=root.querySelector('[data-bm-back]');
  if(!back||back.getAttribute('href')!==fresh.dataset.kembali)throw Error('Tujuan kembali detail berubah. Muat ulang halaman.');
  return {fresh,keys,before,after,back};
 }
 function retainDetail(plan){
  if(!plan)return;
  const {fresh,keys,before,after,back}=plan;
  const attrs=(old,native)=>{for(const a of Array.from(old.attributes))old.removeAttribute(a.name);for(const a of native.attributes)old.setAttribute(a.name,a.value);};
  const heading=root.querySelector('.bm-kepala'),nativeHeading=fresh.querySelector('.bm-kepala'),h1=heading.querySelector('h1');
  nativeHeading.querySelector('h1').replaceWith(h1);attrs(heading,nativeHeading);heading.replaceChildren(...Array.from(nativeHeading.childNodes));nativeHeading.replaceWith(heading);
  for(const key of keys){
   const panel=root.querySelector('#bm-panel-'+key),native=fresh.querySelector('#bm-panel-'+key);
   attrs(panel,native);panel.replaceChildren(...Array.from(native.childNodes));native.replaceWith(panel);
  }
  before.forEach((tab,i)=>{for(const name of ['aria-selected','tabindex','data-url']){if(after[i].hasAttribute(name))tab.setAttribute(name,after[i].getAttribute(name));else tab.removeAttribute(name);}});
  fresh.querySelector('[role="tablist"]').replaceWith(root.querySelector('[role="tablist"]'));
  const rincian=root.querySelector('[data-bm-detail-rincian]'),nativeRincian=fresh.querySelector('[data-bm-detail-rincian]');
  attrs(rincian,nativeRincian);rincian.replaceChildren(...Array.from(nativeRincian.childNodes));nativeRincian.replaceWith(rincian);
  // Hanya tautan GET yang sudah ada pada shell dan cocok dengan induk native.
  fresh.append(back.parentElement);
  // Peningkatan sekali dari shell baca; profil native yang sudah terpasang
  // ditolak di detailIslands, jadi formulir/draf hidup tidak pernah di-morph.
  const tabsReady=root.dataset.bmDetailReady;
  attrs(root,fresh);if(tabsReady)root.dataset.bmDetailReady=tabsReady;
  root.replaceChildren(...Array.from(fresh.childNodes));fresh.replaceWith(root);
 }
 async function install(payload,number){
  if(!current(number)||payload.stamp!==stamp)throw Error('Konteks sesi atau gudang berubah. Muat ulang halaman untuk membaca cakupan yang benar.');
  const doc=new DOMParser().parseFromString(payload.html,'text/html'),source=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(!source||session?.dataset.token!==token)throw Error('Sesi pembacaan berubah. Muat ulang halaman.');
  const [start,end]=markers(source),[from,to]=markers(main);if(!start||!end||!from||!to)throw Error('Struktur daftar belum dapat dibaca. Coba lagi.');
  if(interacting()){
   pending={payload,number};status.textContent=kabar?'Data siap. Tutup panduan untuk menampilkan kabar.':qc?'Data siap. Tutup panduan untuk menampilkan catatan QC.':'Data siap. Terapkan filter yang sedang Anda isi; pilihan tetap dipertahankan.';return;
  }
  const content=document.createElement('div');content.dataset.halamanIsi=root.dataset.kind;
  for(let node=start.nextSibling;node&&node!==end;node=node.nextSibling)content.append(node.cloneNode(true));
  const css=main.querySelector('link[href*="/static/halaman-bertahap.css"]');if(css)content.prepend(css.cloneNode(true));
  // Consumer pilihan pelanggan lama membaca HTML. Tetap memakai route native
  // melalui endpoint baca khusus, bukan merender shell kembali sebagai opsi.
  const stock=content.querySelector('[data-stok-controls]');
  if(stock){const url=new URL(stock.dataset.pelangganUrl,location.href);url.pathname='/api/halaman-bertahap/stok/html';stock.dataset.pelangganUrl=url.pathname+url.search;}
  if(qc&&window.PadiQCFrame?.versi!==1)throw Error('Kontrol daftar QC belum tersedia. Muat ulang halaman.');
  if(kabar&&window.PadiKabarFrame?.versi!==1)throw Error('Kontrol Kabar belum tersedia. Muat ulang halaman.');
  const kabarFrame=kabar?PadiKabarFrame.siapkan(root,content):null;
  const island=controlIsland(content),stockFrame=stockTable(content),detailFrame=detailIslands(content),historyFrame=riwayatIslands(content),homeFrame=berandaIslands(content),qcFrame=qc?PadiQCFrame.siapkan(root,content):null;
  const prepared=kabar?[]:await prepareScripts(content,doc,controller?.signal);
  if(!current(number)||payload.stamp!==stamp)return;
  // Pengguna dapat membuka filter ketika asset masih dibaca.
  if(interacting()){
   pending={payload,number};status.textContent=kabar?'Data siap. Tutup panduan untuk menampilkan kabar.':qc?'Data siap. Tutup panduan untuk menampilkan catatan QC.':'Data siap. Terapkan filter yang sedang Anda isi; pilihan tetap dipertahankan.';return;
  }
  if(detail){
   // Tab boleh berubah selama pembacaan tanpa mengubah draf/controller.
   // Aset sudah selesai dibaca. Pilih tab TERKINI tepat sebelum swap;
   // tidak ada await lagi yang dapat membekukan pilihan selama GET aset.
   const key=new URL(location.href).searchParams.get('tab_detail')||'ringkasan';
   for(const tab of content.querySelectorAll('[data-bm-tab]')){const active=tab.dataset.bmTab===key;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
   for(const panel of content.querySelectorAll('[data-bm-detail-panel]')){panel.hidden=panel.dataset.bmDetailPanel!==key;if(!panel.hidden&&key!=='ringkasan')panel.querySelector('details')?.setAttribute('open','');}
   const rincian=content.querySelector('[data-bm-detail-rincian]');if(rincian)rincian.hidden=key==='ringkasan';
  }
  if(!window.PINDAH?.selaraskanChrome||!PINDAH.selaraskanChrome(doc))throw Error('Konteks navigasi berubah. Muat ulang halaman.');
  const previousFocus=document.activeElement;
  if(kabarFrame){
   // CSS dan controller panduan sudah siap bersama kerangka. Tidak perlu
   // menunggu aset opsional atau melepas tab/filter untuk menerapkan GET.
   observer.disconnect();finished=true;controller=null;
   for(let node=from.nextSibling;node&&node!==to;){const next=node.nextSibling;if(node!==root)node.remove();node=next;}
   const installed=PadiKabarFrame.isi(kabarFrame);restoreSemanticFocus(previousFocus,installed);return;
  }
  if(qcFrame){
   // Nav QC tidak dilepas dari dokumen. Perubahan isi tidak menutup select
   // jenis yang sedang dipakai, dan tetap mempertahankan kontrol native.
   observer.disconnect();finished=true;controller=null;
   for(let node=from.nextSibling;node&&node!==to;){const next=node.nextSibling;if(node!==qcFrame.old)node.remove();node=next;}
   const installed=PadiQCFrame.isi(qcFrame,content);
   const valid=()=>installed.isConnected&&addressNow()===address&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;
   try{activateScripts(prepared);if(valid())restoreSemanticFocus(previousFocus,installed);}
   catch(error){if(valid()){const warning=document.createElement('p');warning.setAttribute('role','alert');warning.textContent=error.message;installed.prepend(warning);}}
   return;
  }
  retainControls(island);retainTable(stockFrame);retainDetail(detailFrame);retainRiwayat(historyFrame);retainBeranda(homeFrame);
  observer.disconnect();finished=true;controller=null;
  while(from.nextSibling&&from.nextSibling!==to)from.nextSibling.remove();to.before(content);
  const valid=()=>content.isConnected&&addressNow()===address&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;
  try{
   activateScripts(prepared);if(!valid())return;
   restoreSemanticFocus(previousFocus,content);

  }catch(error){if(valid()){const warning=document.createElement('p');warning.setAttribute('role','alert');warning.textContent=error.message;content.prepend(warning);}}
 }
 async function read(){
  readFromRetry=document.activeElement===retry;
  if(controller)controller.abort();const number=++sequence;controller=new AbortController();const active=controller;pending=null;
  retry.hidden=true;table.setAttribute('aria-busy','true');status.textContent=kabar?'Membaca kabar…':detail?'Memuat detail penerimaan…':riwayat?'Memuat catatan…':qc?'Membaca catatan QC…':beranda?'Membaca keadaan pabrik…':'Memuat data…';message.textContent=kabar?'Jumlah dan jenis kabar menunggu pembacaan dalam cakupan akun Anda.':detail?'Nilai, sumber dan tindakan menunggu pembacaan terbaru.':riwayat?'Catatan sedang dibaca. Jenis proses dan panduan tetap tersedia.':qc?'Nilai belum dibaca ditandai —, bukan nol atau hasil penilaian.':beranda?'Angka bertanda — belum dibaca; bukan nol atau keadaan kosong.':'Memuat data. Judul kolom dan filter tetap tersedia.';
  const timeout=setTimeout(()=>active.abort(),20000);
  try{
   const response=await fetch(root.dataset.url,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:{'Accept':'application/json'}});
   if(!current(number))return;
   if(response.redirected||!response.ok){
    let detail='';if(!response.redirected&&[400,404,409,422].includes(response.status)){try{const body=await response.json();if(typeof body.detail==='string')detail=body.detail;}catch(_){}}
    throw Error(response.status===401||response.status===403?'Sesi atau akses berubah. Muat ulang halaman untuk memeriksa akses.':detail||'Data belum dapat dimuat. Coba lagi hanya membaca, tanpa mencatat transaksi.');
   }
   const payload=await response.json();if(current(number))await install(payload,number);
  }catch(error){
   failed(error,number);
  }finally{clearTimeout(timeout);if(current(number)){controller=null;table.setAttribute('aria-busy','false');}}
 }
 function failed(error,number){if(!current(number))return;if(beranda){root.querySelector('.beranda-sambut')?.after(status.parentElement);status.parentElement.after(message);}status.textContent=error.name==='AbortError'?'Pembacaan terlalu lama. Data belum tersedia.':error.message;message.textContent=kabar?'Kabar belum dapat dibaca; ini bukan berarti tidak ada kabar.':detail?'Gagal memuat detail; ini bukan penerimaan kosong.':riwayat?'Catatan belum dapat dibaca; ini bukan riwayat kosong.':qc?'Catatan belum dapat dibaca; ini bukan QC kosong atau belum dinilai.':beranda?'Keadaan pabrik belum dapat dibaca; ini bukan berarti tidak ada pekerjaan atau stok.':'Gagal memuat data; ini bukan daftar kosong.';retry.hidden=false;}
 async function resume(){
  if(!pending||interacting())return;
  const next=pending;pending=null;if(!current(next.number))return;
  const active=new AbortController();controller=active;const timer=setTimeout(()=>active.abort(),20000);
  try{await install(next.payload,next.number);}catch(error){failed(error,next.number);}
  finally{clearTimeout(timer);if(controller===active)controller=null;}
 }
 retry.addEventListener('click',read);
 root.addEventListener('toggle',resume,true);
 root.addEventListener('close',resume,true);
 root.addEventListener('focusout',()=>queueMicrotask(resume));
 const guide=root.querySelector('[data-shell-guide-panel]');
 root.querySelector('[data-shell-guide]')?.addEventListener('click',()=>guide.showModal());
 root.querySelector('[data-shell-guide-close]')?.addEventListener('click',()=>guide.close());
 if(root.dataset.kind==='stok'){
  // Kerangka memakai markup header native yang sama. Controller daftar
  // native baru aktif setelah data; di sini hanya panel baca yang dibuka.
  let opener=null;
  const shellDialogs=new AbortController(),stockControls=root.querySelector('[data-stok-controls]');
  if(stockControls)stockControls.pfStockShellStop=()=>shellDialogs.abort();
  root.addEventListener('click',event=>{
   const open=event.target.closest('[data-sk-buka]'),close=event.target.closest('[data-sk-tutup]');
   if(open){const panel=root.querySelector('#'+CSS.escape(open.dataset.skBuka));if(panel?.tagName==='DIALOG'){opener=open;panel.showModal();}}
   if(close)close.closest('dialog')?.close();
  },{signal:shellDialogs.signal});
  for(const panel of root.querySelectorAll('dialog'))panel.addEventListener('close',()=>{if(opener?.isConnected)opener.focus({preventScroll:true});},{signal:shellDialogs.signal});
 }
 const leave=e=>{const a=e.target.closest?.('a[href]');if(!finished&&root.isConnected&&a&&!a.target&&!a.hasAttribute('download')&&!a.hash&&!e.defaultPrevented&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey){stop();}};
 if(window.PINDAH)PINDAH.pasang(document,'click',leave);else document.addEventListener('click',leave,{once:true});
 read();
})();
