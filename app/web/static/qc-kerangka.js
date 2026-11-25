/* Hidrasi lima daftar QC. Hanya memindahkan HTML native yang tervalidasi;
 * tidak menghitung mutu, mengubah field/editor, atau mengirim transaksi. */
(function(){
 'use strict';
 const header=':scope>.tabel-standar__scroll>.tabel-standar__kepala';
 const text=n=>n?.textContent.trim();
 function navSchema(n){return JSON.stringify({active:n?.dataset.aktif,allowed:n?.dataset.bolehAlamat,tabs:n?.dataset.tujuanTab,
  options:Array.from(n?.querySelectorAll('[data-jenis-riwayat] option')||[],o=>[o.value,o.textContent,o.disabled]),
  category:Array.from(n?.querySelectorAll('.laporan-nav__jenis a')||[],a=>[a.getAttribute('href'),a.textContent,a.getAttribute('aria-current')])});}
 function siapkan(root,content){
  const old=root.closest('.laporan-riwayat'),fresh=content.querySelector('.laporan-riwayat');
  const nav=old?.querySelector('[data-laporan-kontrol]'),nextNav=fresh?.querySelector('[data-laporan-kontrol]');
  if(!old||!fresh||!nav||!nextNav||nav.dataset.aktif!=='qc'||navSchema(nav)!==navSchema(nextNav))throw Error('Akses atau jenis Riwayat QC berubah. Muat ulang halaman.');
  const tabs=JSON.parse(nav.dataset.tujuanTab||'[]');
  for(const a of nav.querySelectorAll('[data-tab-riwayat]')){
   const t=tabs.find(x=>x.kunci===a.dataset.tabRiwayat),u=new URL(a.href,location.href);
   if(!t?.boleh||u.origin!==location.origin||u.search||u.hash||!t.alamat.includes(u.pathname))throw Error('Tujuan Riwayat QC berubah. Muat ulang halaman.');
  }
  const body=old.querySelector('.laporan-isi'),nextBody=fresh.querySelector('.laporan-isi'),nextRoot=nextBody?.querySelector('[data-riwayat-qc]');
  const guide=old.querySelector('#rqd-panduan'),nextGuide=fresh.querySelector('#rqd-panduan');
  if(!body||!nextBody||!nextRoot||!guide?.querySelector('.pd-panduan__isi')||!nextGuide?.querySelector('.pd-panduan__isi'))throw Error('Struktur daftar QC belum lengkap. Coba lagi.');
  const rice=root.dataset.kind==='qc-beras-hasil-sosoh';
  if(rice!==nextRoot.hasAttribute('data-rqd-beras')||nextRoot.querySelector('[data-qc-sosoh]')||!rice&&!nextRoot.classList.contains('rqd-list'))throw Error('Tujuan QC bukan daftar yang sedang dibaca. Muat ulang halaman.');
  const beforePrint=nav.querySelectorAll('[data-lk-cetak]'),afterPrint=nextNav.querySelectorAll('[data-lk-cetak]');
  if(beforePrint.length!==afterPrint.length)throw Error('Kontrol Cetak QC berubah. Muat ulang halaman.');
  const frame={kind:root.dataset.kind,old,fresh,nav,nextNav,body,nextBody,nextRoot,guide,nextGuide,rice,beforePrint,afterPrint,
   styles:Array.from(body.querySelectorAll('style[data-qc-aset-native]'),s=>s.cloneNode(true))};
  if(rice){
   frame.riceFrame=root.querySelector('[data-qc-rice-frame]');frame.rows=Array.from(nextRoot.children).filter(n=>n.matches('section.riwayat-detail__card')||n.tagName==='P'&&!n.hasAttribute('data-qc-rice-actions'));
   frame.actions=root.querySelector('[data-qc-rice-actions]');frame.nextActions=nextRoot.querySelector('[data-qc-rice-actions]');
   if(!frame.riceFrame?.querySelector('[data-qc-rice-body]')||!frame.rows.length||(frame.actions?.outerHTML||'')!==(frame.nextActions?.outerHTML||''))throw Error('Tindakan atau daftar QC beras berubah. Muat ulang halaman.');
  }else{
   frame.stats=root.querySelector('[data-qc-summary]');frame.nextStats=nextRoot.querySelector('.riwayat-detail__card');
   const labels=n=>Array.from(n?.querySelectorAll('.rhs-mass>div>span')||[],s=>s.textContent);
   if(!frame.stats||!frame.nextStats||frame.stats.querySelectorAll('strong').length!==2||frame.nextStats.querySelectorAll('strong').length!==2||JSON.stringify(labels(frame.stats))!==JSON.stringify(labels(frame.nextStats)))throw Error('Ringkasan QC berubah. Coba lagi.');
   frame.grid=root.querySelector('[data-qc-read-grid]');frame.nextGrid=nextRoot.querySelector('.tabel-standar--grid');frame.empty=nextRoot.querySelector('.riwayat-empty');
   const cols=n=>Array.from(n?.querySelectorAll(header+'>span')||[],s=>text(s));
   if(!frame.grid||!frame.nextGrid&&!frame.empty||frame.nextGrid&&JSON.stringify(cols(frame.grid))!==JSON.stringify(cols(frame.nextGrid)))throw Error('Kolom QC belum sesuai. Muat ulang halaman.');
  }
  return frame;
 }
 function isi(frame,content){
  const {old,fresh,nav,nextNav,body,nextBody,nextRoot,guide,nextGuide}=frame;
  guide.querySelector('.pd-panduan__isi').replaceChildren(...Array.from(nextGuide.querySelector('.pd-panduan__isi').childNodes));nextGuide.replaceWith(guide);
  frame.beforePrint.forEach((b,i)=>{for(const a of ['disabled','aria-describedby']){if(frame.afterPrint[i].hasAttribute(a))b.setAttribute(a,frame.afterPrint[i].getAttribute(a));else b.removeAttribute(a);}});
  if(frame.rice){
   const marker=document.createComment('qc-rows');frame.rows[0].before(marker);
   frame.riceFrame.querySelector('[data-qc-rice-body]').replaceChildren(...frame.rows);marker.replaceWith(frame.riceFrame);
   if(frame.actions)frame.nextActions.replaceWith(frame.actions);
  }else{
   const values=frame.nextStats.querySelectorAll('strong');frame.stats.querySelectorAll('strong').forEach((n,i)=>{n.textContent=values[i].textContent;});frame.nextStats.replaceWith(frame.stats);
   const head=frame.grid.querySelector(header),scroll=frame.grid.querySelector('.tabel-standar__scroll');
   if(frame.nextGrid){
    frame.nextGrid.querySelector(header).replaceWith(head);scroll.replaceChildren(...Array.from(frame.nextGrid.querySelector('.tabel-standar__scroll').childNodes));frame.nextGrid.replaceWith(frame.grid);
   }else{
    const marker=document.createComment('qc-empty');frame.empty.before(marker);const row=document.createElement('div');row.className='tabel-standar__item';row.append(frame.empty);scroll.replaceChildren(head,row);marker.replaceWith(frame.grid);
   }
  }
  for(const style of frame.styles)nextRoot.prepend(style);
  // Wrapper/nav tetap tersambung. Popup select dan fokus jenis QC tidak
  // dilepas hanya karena GET isi selesai; hanya badan daftar yang diganti.
  body.replaceChildren(...Array.from(nextBody.childNodes));
  let passed=false,tail=old;
  for(const n of Array.from(content.childNodes)){
   if(n===fresh){passed=true;continue;}
   if(!passed)old.before(n);else{tail.after(n);tail=n;}
  }
  for(const n of body.querySelectorAll('[data-shell-table-wrap]'))n.setAttribute('aria-busy','false');
  old.dataset.halamanIsi=frame.kind;
  return old;
 }
 window.PadiQCFrame={versi:1,siapkan,isi};
})();
