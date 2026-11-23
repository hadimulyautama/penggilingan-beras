/* Tab lokal tidak mengganti DOM isian atau menjalankan pembaca/penulis.
 * Pemulihan draf, kunci pending dan pemeriksaan izin tetap controller native. */
(function(){
 'use strict';
 const root=document.querySelector('[data-bm-detail-shell]');
 if(!root||root.dataset.bmDetailReady)return;root.dataset.bmDetailReady='1';
 const tabs=Array.from(root.querySelectorAll('[data-bm-tab]'));
 const panels=Array.from(root.querySelectorAll('[data-bm-detail-panel]'));
 function pilih(key,updateURL=false,hash){
  const selected=tabs.find(t=>t.dataset.bmTab===key);if(!selected)return;
  for(const tab of tabs){const active=tab===selected;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
  const rincian=root.querySelector('[data-bm-detail-rincian]');if(rincian)rincian.hidden=key==='ringkasan';
  for(const panel of panels){const active=panel.dataset.bmDetailPanel===key;panel.hidden=!active;if(active&&key!=='ringkasan')panel.querySelector('details')?.setAttribute('open','');}
  if(updateURL){const u=new URL(selected.dataset.url,location.href);if(hash!==undefined)u.hash=hash;if(u.origin===location.origin&&u.pathname===location.pathname)history.replaceState(history.state,'',u.pathname+u.search+u.hash);}
 }
 root.querySelector('[role="tablist"]').addEventListener('click',e=>{
  const tab=e.target.closest('[data-bm-tab]');if(tab)pilih(tab.dataset.bmTab,true);
 });
 root.querySelector('[role="tablist"]').addEventListener('keydown',e=>{
  const i=tabs.indexOf(e.target);if(i<0||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  pilih(tabs[next].dataset.bmTab,true);tabs[next].focus();
 });
 function fragmen(){
  let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(_){return;}
  const target=document.getElementById(id);if(!target||!root.contains(target))return;
  const panel=target.closest('[data-bm-detail-panel]');if(panel)pilih(panel.dataset.bmDetailPanel,true,location.hash);
 }
 // Pergantian tab memakai button, bukan navigasi dokumen. Penjaga navigasi
 // native untuk draf/pending tetap tidak diubah dan selalu menjaga menu lain.
 if(window.PINDAH)PINDAH.pasang(window,'hashchange',fragmen);else window.addEventListener('hashchange',fragmen);
 root.addEventListener('invalid',e=>{const panel=e.target.closest('[data-bm-detail-panel]');if(panel)pilih(panel.dataset.bmDetailPanel,true);},true);
 function gagalIsian(){
  if(!root.isConnected)return;const shell=root.querySelector('[data-bm-form-shell]');if(!shell)return;
  shell.setAttribute('aria-busy','false');const status=shell.querySelector('[data-bm-form-shell-status]');
  status.textContent='Isian belum dapat disiapkan. Muat ulang halaman untuk memulihkan isian dan memeriksa status. Tidak ada pengiriman ulang otomatis.';status.setAttribute('role','alert');
  shell.querySelector('[data-bm-form-retry]').hidden=false;
 }
 const native=document.getElementById('bm-native-form-script');native?.addEventListener('error',gagalIsian);
 // Error runtime juga tidak boleh meninggalkan kerangka seolah masih siap
 // mengirim. Tidak ada timeout atau simpan ulang otomatis.
 if(window.PINDAH)PINDAH.pasang(window,'load',gagalIsian);else window.addEventListener('load',gagalIsian,{once:true});
 root.querySelector('[data-bm-form-retry]')?.addEventListener('click',()=>location.reload());
 pilih(tabs.find(t=>t.getAttribute('aria-selected')==='true')?.dataset.bmTab||'ringkasan');fragmen();
})();
