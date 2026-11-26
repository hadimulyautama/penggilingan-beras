/* Pulau kontrol Kabar saja. Isi dan semua POST tetap HTML native. */
(function(){
 'use strict';
 function alamat(raw){
  const u=new URL(raw,location.href);
  return u.origin===location.origin&&u.pathname==='/kabar'&&!u.hash
   &&Array.from(u.searchParams.keys()).every(k=>['tab','jenis','batas','sampai','sebelum'].includes(k));
 }
 function siapkan(root,content){
  const fresh=content.querySelector('section.kb');
  const oldControl=root.querySelector('.kontrol-halaman'),nextControl=fresh?.querySelector('.kontrol-halaman');
  const guide=root.querySelector('#kb-panduan'),nextGuide=fresh?.querySelector('#kb-panduan');
  const oldTabs=Array.from(oldControl?.querySelectorAll('.kontrol-tab a')||[]),nextTabs=Array.from(nextControl?.querySelectorAll('.kontrol-tab a')||[]);
  const form=oldControl?.querySelector('form.kb-kind'),nextForm=nextControl?.querySelector('form.kb-kind');
  const select=form?.querySelector('select[name="jenis"]'),nextSelect=nextForm?.querySelector('select[name="jenis"]');
  const summary=root.querySelector('.kb-summary'),nextSummary=fresh?.querySelector('.kb-summary');
  const button=summary?.querySelector('[data-kabar-semua]'),nextButton=nextSummary?.querySelector('[data-kabar-semua]');
  if(!fresh||!oldControl||!nextControl||oldTabs.length!==2||nextTabs.length!==2
    ||nextTabs.some(a=>!alamat(a.getAttribute('href')))||!form||!nextForm||form.method!=='get'||nextForm.method!=='get'
    ||form.getAttribute('action')!=='/kabar'||nextForm.getAttribute('action')!=='/kabar'
    ||!select||!nextSelect||!button||!nextButton||!guide?.querySelector('.pd-panduan__isi')||!nextGuide?.querySelector('.pd-panduan__isi')
    ||!/^(0|[1-9]\d*)$/.test(fresh.dataset.sampai||''))throw Error('Struktur Kabar belum sesuai. Coba lagi.');
  const scripts=Array.from(content.querySelectorAll('script'));
  const expected=['kabar-kontrol.js','menu-layar.js','kerangka-langsung.js','navigasi-daftar-bertahap.js'].map(n=>'/static/'+n+'?v='+document.documentElement.dataset.versi).sort();
  if(JSON.stringify(scripts.map(n=>n.getAttribute('src')).sort())!==JSON.stringify(expected))throw Error('Kontrol Kabar berubah. Muat ulang halaman.');
  const rows=Array.from(fresh.children).filter(n=>n.matches('.kb-day,.kb-feed,.kb-empty,.kb-more'));
  if(!rows.length||rows.some(n=>n.matches('a')&&!alamat(n.getAttribute('href'))))throw Error('Isi Kabar belum lengkap. Coba lagi.');
  const getNames=n=>Array.from(n.querySelectorAll('[name]'),e=>e.name).sort().join('|');
  if(getNames(form)!==getNames(nextForm)||nextSelect.options.length<1)throw Error('Filter Kabar berubah. Muat ulang halaman.');
  // Jangan membentuk/mengirim status baca di browser. Form native harus
  // tetap punya satu CSRF dan satu endpoint yang sudah tersedia.
  const post=nextButton.closest('form');
  if(!post||post.method!=='post'||post.getAttribute('action')!=='/kabar/status'
    ||post.querySelectorAll('input[name="_csrf"]').length!==1)throw Error('Kontrol status Kabar belum sesuai. Muat ulang halaman.');
  return {root,fresh,oldControl,nextControl,oldTabs,nextTabs,form,nextForm,select,nextSelect,summary,nextSummary,button,nextButton,guide,nextGuide,rows,
   styles:Array.from(root.parentElement.querySelectorAll('style[data-kabar-aset-native]'),s=>s.cloneNode(true))};
 }
 function attrs(old,native){for(const a of Array.from(old.attributes))old.removeAttribute(a.name);for(const a of native.attributes)old.setAttribute(a.name,a.value);}
 function isi(p){
  const {root,fresh,oldControl,oldTabs,nextTabs,form,nextForm,select,nextSelect,summary,nextSummary,button,nextButton,guide,nextGuide}=p;
  oldTabs.forEach((old,i)=>{attrs(old,nextTabs[i]);old.replaceChildren(...Array.from(nextTabs[i].childNodes));});
  select.replaceChildren(...Array.from(nextSelect.options,o=>o.cloneNode(true)));select.value=nextSelect.value;attrs(select,nextSelect);
  const hidden=form.querySelector('input[name="tab"]'),nextHidden=nextForm.querySelector('input[name="tab"]');attrs(hidden,nextHidden);
  const apply=form.querySelector('button[type="submit"]'),nextApply=nextForm.querySelector('button[type="submit"]');attrs(apply,nextApply);
  attrs(button,nextButton);nextButton.replaceWith(button);summary.replaceChildren(...Array.from(nextSummary.childNodes));
  guide.querySelector('.pd-panduan__isi').replaceChildren(...Array.from(nextGuide.querySelector('.pd-panduan__isi').childNodes));
  const data=root.querySelector('[data-shell-table-wrap]');data.replaceChildren(...p.rows);data.setAttribute('aria-busy','false');
  root.querySelector('.halaman-bertahap__status')?.remove();root.querySelector('[data-shell-message]')?.remove();
  // Badge native baru melihat .kb setelah seluruh data selesai dipasang.
  root.className=fresh.className;root.dataset.sampai=fresh.dataset.sampai;
  delete root.dataset.halamanBertahap;delete root.dataset.ready;root.dataset.halamanIsi='kabar';
  for(const style of p.styles)if(!root.querySelector('style[data-kabar-aset-native="'+style.dataset.kabarAsetNative+'"]'))root.prepend(style);
  return root;
 }
 window.PadiKabarFrame={versi:1,siapkan,isi};
})();
