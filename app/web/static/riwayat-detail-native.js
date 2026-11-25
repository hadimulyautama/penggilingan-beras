/* Bentuk/detail baca saja. Tidak menghitung QC atau mengubah editor native. */
(function(global){
 'use strict';
 function selectedTabs(root,key){
  const buttons=Array.from(root.querySelectorAll('[data-rdn-tab]'));
  if(!buttons.some(b=>b.dataset.rdnTab===key))return null;
  root.dataset.rdnTab=key;
  for(const b of buttons){const active=b.dataset.rdnTab===key;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;}
  for(const panel of root.querySelectorAll('[data-rdn-panel]'))panel.hidden=panel.dataset.rdnPanel!==key;
  return buttons.find(b=>b.dataset.rdnTab===key);
 }
 function nativeActions(content,origin){
  for(const link of content.querySelectorAll('a[href]')){
   let u;try{u=new URL(link.getAttribute('href'),origin);}catch(_){continue;}
   // Hanya href yang memang dirender native. Footer editor tidak diadopsi:
   // klik eksplisit memuat dokumen lengkap beserta controller asli.
   if(u.origin===origin&&(u.searchParams.has('buka')||u.searchParams.has('nilai')||/^\/riwayat-(?:giling|sosoh|pengeringan)\/[1-9][0-9]*\/(?:koreksi|bobot)$/.test(u.pathname)))link.setAttribute('data-utuh','');
  }
 }
 function restoreNative(content,key,variant){
  const root=content.querySelector(variant==='riwayat-pengeringan'?'[data-riwayat-pengeringan]':variant.startsWith('riwayat-')?'[data-riwayat-'+variant.slice(8)+']':'[data-riwayat-qc]');
  if(!root)return null; // Renderer redirect/missing tidak dipaksa jadi detail.
  const tabs=Array.from(root.querySelectorAll('[role=tab]'));
  const chosen=tabs.find(t=>(t.getAttribute('aria-controls')||'').endsWith('panel-'+key));
  if(!chosen)return null;
  for(const tab of tabs){const active=tab===chosen;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;const panel=root.querySelector('#'+tab.getAttribute('aria-controls'));if(panel)panel.hidden=!active;}
  if(variant.startsWith('qc-'))root.dataset.rqdSelected=key;
  return chosen; // Tidak klik tab native: controller QC dapat mengganti URL.
 }
 if(typeof module==='object'&&module.exports){module.exports={selectedTabs,restoreNative,nativeActions};return;}
 const root=document.querySelector('[data-riwayat-detail-native]'),core=global.PADI_BACA_NATIVE;
 if(!root||!core||root.dataset.rdnReady)return;
 const address=root.dataset.url;
 if(!core.sameOriginAddress(address,location.origin)||address!==location.pathname+location.search)return;
 root.dataset.rdnReady='1';
 const tabs=Array.from(root.querySelectorAll('[data-rdn-tab]'));
 for(const a of tabs)a.addEventListener('click',e=>{e.preventDefault();selectedTabs(root,a.dataset.rdnTab);});
 for(const a of root.querySelectorAll('[data-rdn-go]'))a.addEventListener('click',e=>{e.preventDefault();selectedTabs(root,a.dataset.rdnGo)?.focus({preventScroll:true});});
 root.querySelector('[role=tablist]')?.addEventListener('keydown',e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  const index=tabs.indexOf(document.activeElement);if(index<0)return;
  const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  e.preventDefault();selectedTabs(root,tabs[next].dataset.rdnTab)?.focus();
 });
 const guide=root.querySelector('#rdn-panduan');let guideSource=null;
 for(const a of root.querySelectorAll('[data-rdn-guide]'))a.addEventListener('click',()=>{guideSource=a;a.closest('details')?.removeAttribute('open');guide?.showModal();});
 root.querySelector('[data-rdn-guide-close]')?.addEventListener('click',()=>guide?.close());
 guide?.addEventListener('close',()=>{if(guideSource?.isConnected)(guideSource.getClientRects().length?guideSource:root.querySelector('[data-rdn-menu]'))?.focus({preventScroll:true});});
 for(const b of document.querySelectorAll('[data-lk-cetak]')){b.disabled=true;b.setAttribute('aria-describedby','rdn-menunggu');}
 let restored=null;
 core.mount({address,rootSelector:'[data-riwayat-detail-native]',statusSelector:'[data-rdn-status]',retrySelector:'[data-rdn-retry]',shellSelector:'[data-riwayat-detail-native],.halaman-memuat',contentAttribute:'data-riwayat-detail-native-isi',messages:{loading:'Memuat catatan terbaru…'},
  afterInstall({content}){nativeActions(content,location.origin);restored=restoreNative(content,root.dataset.rdnTab,root.dataset.rdnVariant);},
  restoreFocus({focus,retry,content}){
   if(focus===retry||focus.hasAttribute('data-rdn-tab')||focus.hasAttribute('data-rdn-go')){
    if(restored)restored.focus({preventScroll:true});else{content.tabIndex=-1;content.focus({preventScroll:true});}
   }else if(focus.hasAttribute('data-rdn-menu'))content.querySelector('summary[aria-label="Tindakan riwayat"]')?.focus({preventScroll:true});
   else if(focus.hasAttribute('data-rdn-guide')||focus.hasAttribute('data-lk-buka'))content.querySelector('[data-lk-buka],[data-rhs-guide],[data-rhp-guide],[data-rqd-guide]')?.focus({preventScroll:true});
  }});
})(typeof window==='undefined'?globalThis:window);
