/* Explicit Giling-only native HTML adoption proposal; never a route discoverer.
 * Reader GET/identity/stale handling belongs to PADI_BACA_NATIVE. Native writer,
 * draft, pending keys, recovery, beforeunload and transaction rules are untouched.
 */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const keys=['ringkasan','bahan','hasil','qc','riwayat'];
 function nativeAddress(address,origin){
  if(!core?.sameOriginAddress(address,origin))return null;
  const url=new URL(address,origin),q=url.searchParams;
  if(!/^\/proses-aktif\/giling\/[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(url.pathname)||url.search.length>3000)return null;
  const allowed=['tab_detail','kembali_kerja','halaman_hasil','halaman_qc','halaman_jeda','buka','nilai'];
  if(Array.from(q.keys()).some(k=>!allowed.includes(k)||q.getAll(k).length!==1)||q.get('buka')||q.get('nilai'))return null;
  return url.pathname+url.search;
 }
 function tabFromAddress(address,origin){
  const valid=nativeAddress(address,origin);if(!valid)return null;
  const tab=new URL(valid,origin).searchParams.get('tab_detail')||'ringkasan';
  return keys.includes(tab)?tab:'ringkasan';
 }
 function latestNativeTab(content,key){
  // Called only after native controls exist. Clicking a native tab is UI-only.
  if(!keys.includes(key))return null;
  const button=content.querySelector('[data-giling-ringkas] button[role="tab"][data-sr-tab="'+key+'"]');
  if(!button||button.disabled)return null;
  button.click();return button;
 }
 function restoreNativeTab(content,key){
  const native=content.querySelector('[data-giling-ringkas]');
  // State may finish between Work read and this fresh native GET. Preserve
  // the real finished renderer; it has no active-process tab controller.
  if(native?.pfGilingData?.aktif===false)return null;
  // Existing native editor/recovery may deliberately lock its own tabs.
  // Respect that UI guard; do not move a pending save/draft to another view.
  const ui=native?.pfGilingPresentationState;
  if(ui&&(ui.busy||ui.uncertain||ui.action||ui.review))return null;
  const button=latestNativeTab(content,key);
  if(!button)throw Error('Tab proses belum dapat dipulihkan. Baca ulang halaman native sebelum mengubah isian.');
  return button;
 }
 const api={nativeAddress,tabFromAddress,latestNativeTab,restoreNativeTab};
 if(typeof module==='object'&&module.exports){module.exports=api;return;}
 if(!core)return;
 const root=document.querySelector('[data-giling-native-html]');
 if(!root||root.dataset.gilingNativeReady)return;root.dataset.gilingNativeReady='1';
 const address=nativeAddress(root.dataset.url,location.origin);
 if(!address||address!==location.pathname+location.search)return;
 const tabs=Array.from(root.querySelectorAll('[data-gk-tab-pilih]'));
 const panels=Array.from(root.querySelectorAll('[data-gk-panel]'));
 const output=root.querySelector('[data-gk-output]'),slot=root.querySelector('[data-gk-output-slot]');
 function show(key){
  if(!keys.includes(key))return;
  root.dataset.gkTab=key;
  if(output&&slot&&['ringkasan','hasil'].includes(key)){
   if(key==='ringkasan')slot.append(output);else root.querySelector('[data-gk-panel="hasil"]').prepend(output);
  }
  for(const tab of tabs){const active=tab.dataset.gkTabPilih===key;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
  for(const panel of panels)panel.hidden=panel.dataset.gkPanel!==key;
 }
 for(const tab of tabs)tab.addEventListener('click',()=>show(tab.dataset.gkTabPilih));
 root.querySelector('[role=tablist]')?.addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const current=tabs.indexOf(document.activeElement);if(current<0)return;
  const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(current+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  event.preventDefault();show(tabs[next].dataset.gkTabPilih);tabs[next].focus();
 });
 const guide=root.querySelector('#gk-panduan'),open=root.querySelector('[data-gk-panduan]');
 open?.addEventListener('click',()=>guide?.showModal());
 root.querySelector('[data-gk-panduan-tutup]')?.addEventListener('click',()=>guide?.close());
 guide?.addEventListener('close',()=>{if(open?.isConnected)open.focus({preventScroll:true});});
 show(tabFromAddress(address,location.origin));
 let restoredTab=null;
 core.mount({address,rootSelector:'[data-giling-native-html]',
  statusSelector:'[data-gk-status]',retrySelector:'[data-gk-retry]',
  shellSelector:'[data-giling-native-html],.halaman-memuat',contentAttribute:'data-giling-native-isi',
  messages:{loading:'Memuat data proses terbaru… Status simpan sebelumnya belum diperiksa.',
   response:'Data proses belum dapat dibaca. Status simpan belum dapat dipastikan; jangan kirim ulang.',
   native:'Halaman proses native belum tersedia. Status simpan belum dapat dipastikan.',
   timeout:'Pembacaan proses terlalu lama. Status simpan belum dapat dipastikan; coba baca lagi, jangan kirim ulang.'},
  // Requires root's unconditional, still-current AFTER scripts hook. The
  // baseline core has no such hook: this proposal remains blocked until it
  // is adopted and proved. Never mutate the URL while a GET is in flight.
  afterInstall({content}){
   restoredTab=restoreNativeTab(content,root.dataset.gkTab);
  },
  restoreFocus({focus,retry,content}){
   if(focus===retry||focus.hasAttribute('data-gk-tab-pilih'))restoredTab?.focus({preventScroll:true});
  }
 });
})(typeof window==='undefined'?globalThis:window);
