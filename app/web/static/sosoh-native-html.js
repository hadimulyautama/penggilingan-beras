/* Unwired active Sosoh shell. Native fresh GET owns data, drafts, recovery,
 * authorization and transactions. This adapter preserves read-only views. */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const keys=['ringkasan','bahan','hasil','qc','riwayat'];
 function nativeAddress(address,origin){
  if(!core?.sameOriginAddress(address,origin))return null;
  const url=new URL(address,origin),q=url.searchParams;
  if(!/^\/proses-aktif\/sosoh\/[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(url.pathname)||url.search.length>3000||Array.from(q).length>12)return null;
  const allowed=['tab_detail','kembali_kerja','halaman_hasil','halaman_qc','halaman_jeda','buka','nilai'];
  if(Array.from(q.keys()).some(k=>!allowed.includes(k)||q.getAll(k).length!==1)||q.get('buka')||q.get('nilai'))return null;
  return url.pathname+url.search;
 }
 function tabFromAddress(address,origin){
  const valid=nativeAddress(address,origin);if(!valid)return null;
  const key=new URL(valid,origin).searchParams.get('tab_detail')||'ringkasan';
  return keys.includes(key)?key:'ringkasan';
 }
 function snapshot(root){
  const fold=key=>root.querySelector('[data-sn-fold="'+key+'"]')?.open;
  return {layout:root.dataset.layout,tab:root.dataset.snTab,qc:fold('qc'),
   more:fold('hasil-lain'),pack:fold('kemasan'),
   silo:!root.querySelector('[data-sn-silo-body]')?.hidden};
 }
 function restoreNativeView(content,state){
  const native=content.querySelector('[data-sosoh-ringkas]');
  if(!native||!['operator','admin'].includes(state.layout)||native.dataset.layout!==state.layout)
   throw Error('Susunan proses berubah. Baca ulang halaman native sebelum mengubah isian.');
  if(native.pfSosohData?.aktif===false)return null;
  const ui=native.pfSosohPresentationState;
  if(ui&&(ui.busy||ui.uncertain||ui.action||ui.review))return null;
  if(!native.pfSosohData||!ui)throw Error('Data proses native belum siap. Status simpan belum dapat dipastikan.');
  if(state.layout==='admin'){
   if(!keys.includes(state.tab))throw Error('Tab proses tidak dikenali.');
   const tab=native.querySelector('button[role="tab"][data-sr-tab="'+state.tab+'"]');
   if(!tab||tab.disabled)throw Error('Tab proses belum dapat dipulihkan. Baca ulang halaman native.');
   tab.click();return tab;
  }
  // Only UI disclosure state; never restore a cycle, result, draft or key.
  const fold=(selector,value)=>{const node=native.querySelector(selector);if(node&&typeof value==='boolean')node.open=value;};
  fold('[data-sr-fold="qcTerbuka"]',state.qc);
  fold('[data-sr-output-samping]',state.more);
  fold('[data-sr-pack]',state.pack);
  const silo=native.querySelector('#sr-work-silos'),toggle=native.querySelector('.sr-work-source-toggle');
  if(silo&&toggle&&!toggle.disabled&&silo.hidden===state.silo)toggle.click();
  return null;
 }
 const api={nativeAddress,tabFromAddress,snapshot,restoreNativeView};
 if(typeof module==='object'&&module.exports){module.exports=api;return;}
 if(!core)return;
 const root=document.querySelector('[data-sosoh-native-html]');
 if(!root||root.dataset.sosohNativeReady)return;root.dataset.sosohNativeReady='1';
 const address=nativeAddress(root.dataset.url,location.origin);
 if(!address||address!==location.pathname+location.search)return;
 const tabs=Array.from(root.querySelectorAll('[data-sn-tab-pilih]'));
 function show(key){
  if(!keys.includes(key))return;
  root.dataset.snTab=key;
  for(const tab of tabs){const active=tab.dataset.snTabPilih===key;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
  for(const panel of root.querySelectorAll('[data-sn-panel]'))panel.hidden=panel.dataset.snPanel!==key;
 }
 for(const tab of tabs)tab.addEventListener('click',()=>show(tab.dataset.snTabPilih));
 for(const link of root.querySelectorAll('[data-sn-tab-jump]'))link.addEventListener('click',()=>show(link.dataset.snTabJump));
 root.querySelector('[role=tablist]')?.addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const current=tabs.indexOf(document.activeElement);if(current<0)return;
  const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(current+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  event.preventDefault();show(tabs[next].dataset.snTabPilih);tabs[next].focus();
 });
 const silo=root.querySelector('[data-sn-silo-body]'),toggle=root.querySelector('[data-sn-silo-toggle]');
 toggle?.addEventListener('click',()=>{if(!silo)return;silo.hidden=!silo.hidden;toggle.setAttribute('aria-expanded',String(!silo.hidden));toggle.textContent=(silo.hidden?'▸ ':'▾ ')+'Bahan & silo';});
 const guide=root.querySelector('#sn-panduan');let guideSource=null;
 for(const open of root.querySelectorAll('[data-sn-guide]'))open.addEventListener('click',()=>{guideSource=open;open.closest('details')?.removeAttribute('open');guide?.showModal();});
 root.querySelector('[data-sn-guide-close]')?.addEventListener('click',()=>guide?.close());
 guide?.addEventListener('close',()=>{if(guideSource?.isConnected)(guideSource.getClientRects().length?guideSource:root.querySelector('[data-sn-menu]'))?.focus({preventScroll:true});});
 show(location.hash==='#qc-sosoh'?'qc':tabFromAddress(address,location.origin));
 if(location.hash==='#qc-sosoh'){const qc=root.querySelector('[data-sn-fold="qc"]');if(qc)qc.open=true;}
 let restoredTab=null;
 core.mount({address,rootSelector:'[data-sosoh-native-html]',statusSelector:'[data-sn-status]',retrySelector:'[data-sn-retry]',
  shellSelector:'[data-sosoh-native-html],.halaman-memuat',contentAttribute:'data-sosoh-native-isi',
  messages:{loading:'Memuat data proses terbaru… Status simpan sebelumnya belum diperiksa.',
   response:'Data proses belum dapat dibaca. Status simpan belum dapat dipastikan; jangan kirim ulang.',
   native:'Halaman proses native belum tersedia. Status simpan belum dapat dipastikan.',
   timeout:'Pembacaan proses terlalu lama. Status simpan belum dapat dipastikan; coba baca lagi, jangan kirim ulang.'},
  afterInstall({content}){restoredTab=restoreNativeView(content,snapshot(root));},
  restoreFocus({focus,retry,content}){
   const native=content.querySelector('[data-sosoh-ringkas]');
   if(focus===retry||focus.hasAttribute('data-sn-tab-pilih')||focus.hasAttribute('data-sn-tab-jump'))restoredTab?.focus({preventScroll:true});
   else if(focus.hasAttribute('data-sn-guide'))native?.querySelector('.sr-work-guide,.sr-design-tools>button')?.focus({preventScroll:true});
   else if(focus.hasAttribute('data-sn-silo-toggle'))native?.querySelector('.sr-work-source-toggle')?.focus({preventScroll:true});
   else if(focus.hasAttribute('data-sn-menu'))native?.querySelector('summary[aria-label="Tindakan proses"]')?.focus({preventScroll:true});
  }
 });
})(typeof window==='undefined'?globalThis:window);
