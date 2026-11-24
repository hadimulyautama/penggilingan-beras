/* Dua fase dryer saja. GET, identitas, pembatalan dan respons usang milik
 * PADI_BACA_NATIVE; tidak ada writer, penyimpanan lokal, atau draf baru. */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const tabs=['ringkasan','bahan','pengukuran','riwayat'];
 function descriptor(address,origin){
  if(!core?.sameOriginAddress(address,origin))return null;
  const u=new URL(address,origin),q=u.searchParams,match=/^\/proses-aktif\/(pengeringan|pendinginan)\/([A-Za-z0-9][A-Za-z0-9._-]{0,79})$/.exec(u.pathname);
  try{decodeURIComponent(u.search);}catch(_){return null;}
  if(!match||u.search.length>3000||Array.from(q.keys()).some(k=>!['tab_detail','kembali_kerja','halaman_ukur','halaman_dingin','halaman_jeda'].includes(k)||q.getAll(k).length!==1))return null;
  if(['halaman_ukur','halaman_dingin','halaman_jeda'].some(k=>q.has(k)&&!(/^[1-9][0-9]{0,8}$/).test(q.get(k))))return null;
  let tab=q.get('tab_detail');if(!tabs.includes(tab))tab=q.get('halaman_ukur')?'pengukuran':q.get('halaman_dingin')||q.get('halaman_jeda')?'riwayat':'ringkasan';
  return {address:u.pathname+u.search,phase:match[1],code:match[2],tab};
 }
 function restoreTab(content,key,phase){
  const native=content.querySelector('.pengeringan-detail');
  // Peralihan fase/riwayat native tidak dipaksa kembali menjadi halaman aktif.
  if(!native||phase==='pengeringan'&&native.classList.contains('pendinginan-detail')||phase==='pendinginan'&&!native.hasAttribute('data-pendinginan-aktif'))return null;
  const all=Array.from(native.querySelectorAll('.pengeringan-tabs [role=tab]'));
  const chosen=all.find(t=>t.getAttribute('aria-controls')==='panel-'+key);
  if(!chosen)return null;
  for(const tab of all){const active=tab===chosen;tab.setAttribute('aria-selected',String(active));const panel=native.querySelector('#'+tab.getAttribute('aria-controls'));if(panel)panel.hidden=!active;}
  return chosen;
 }
 if(typeof module==='object'&&module.exports){module.exports={descriptor,restoreTab};return;}
 const root=document.querySelector('[data-dryer-native-html]');
 if(!root||root.dataset.dryerNativeReady||!core)return;
 const state=descriptor(root.dataset.url,location.origin);
 if(!state||state.address!==location.pathname+location.search||state.phase!==root.dataset.fase)return;
 root.dataset.dryerNativeReady='1';
 const buttons=Array.from(root.querySelectorAll('[data-dryer-tab]'));
 function show(key){
  if(!tabs.includes(key))return;root.dataset.tab=key;
  for(const b of buttons){const active=b.dataset.dryerTab===key;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;}
  for(const p of root.querySelectorAll('[data-dryer-panel]'))p.hidden=p.dataset.dryerPanel!==key;
 }
 for(const b of buttons)b.addEventListener('click',e=>{e.preventDefault();show(b.dataset.dryerTab);});
 root.querySelector('[role=tablist]')?.addEventListener('keydown',e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  const index=buttons.indexOf(document.activeElement);if(index<0)return;
  const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
  e.preventDefault();show(buttons[next].dataset.dryerTab);buttons[next].focus();
 });
 const guide=root.querySelector('#dryer-panduan');let guideSource=null;
 for(const b of root.querySelectorAll('[data-dryer-guide]'))b.addEventListener('click',()=>{guideSource=b;b.closest('details')?.removeAttribute('open');guide?.showModal();});
 root.querySelector('[data-dryer-guide-close]')?.addEventListener('click',()=>guide?.close());
 guide?.addEventListener('close',()=>{if(guideSource?.isConnected)(guideSource.getClientRects().length?guideSource:root.querySelector('[data-dryer-menu]'))?.focus({preventScroll:true});});
 show(state.tab);let nativeTab=null;
 core.mount({address:state.address,rootSelector:'[data-dryer-native-html]',statusSelector:'[data-dryer-status]',retrySelector:'[data-dryer-retry]',shellSelector:'[data-dryer-native-html],.halaman-memuat',contentAttribute:'data-dryer-native-isi',messages:{loading:'Memuat data proses terbaru…'},
  afterInstall({content}){nativeTab=restoreTab(content,root.dataset.tab,state.phase);},
  restoreFocus({focus,retry,content}){
   if(focus===retry||focus.hasAttribute('data-dryer-tab'))nativeTab?.focus({preventScroll:true});
   else if(focus.hasAttribute('data-dryer-menu'))content.querySelector('summary[aria-label="Tindakan proses"],summary[aria-label="Tindakan riwayat"]')?.focus({preventScroll:true});
   else if(focus.hasAttribute('data-dryer-guide'))content.querySelector('[data-dr-guide],[data-rhp-guide]')?.focus({preventScroll:true});
  }});
})(typeof window==='undefined'?globalThis:window);
