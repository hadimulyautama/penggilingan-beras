/* Audit-only read adapter. No undo, transaction, token or save operation. */
(function(global){'use strict';
 function allowed(address,origin){
  if(typeof address!=='string'||!address.startsWith('/')||address.startsWith('//'))return false;
  let u;try{u=new URL(address,origin);}catch(_){return false;}
  const pairs=[...u.searchParams];return u.origin===origin&&!u.hash&&u.pathname==='/audit'&&u.pathname+u.search===address&&u.search.length<=2049&&pairs.length<=3&&new Set(pairs.map(x=>x[0])).size===pairs.length&&pairs.every(x=>['rentang','kelompok','cari'].includes(x[0]));
 }
 if(typeof module==='object'&&module.exports){module.exports={allowed};return;}
 const root=document.querySelector('[data-audit-native]');if(!root||!allowed(root.dataset.url,location.origin))return;
 let reader=null;
 function preserve(event){if(!event.target.matches('input[name],select[name]'))return;reader?.stop();root.querySelector('[data-audit-native-retry]').hidden=true;root.querySelector('[data-audit-native-status]').textContent='Pilihan berubah. Tekan Cari atau Terapkan filter untuk membaca catatan pilihan ini.';}
 root.addEventListener('input',preserve);root.addEventListener('change',preserve);
 reader=global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-audit-native]',statusSelector:'[data-audit-native-status]',retrySelector:'[data-audit-native-retry]',shellSelector:'[data-audit-native]',contentAttribute:'data-audit-native-isi',messages:{loading:'Memuat catatan audit…'},
 restoreFocus({focus,retry,content}){let next;if(focus===retry||focus.hasAttribute('data-lk-buka'))next=content.querySelector('[data-lk-buka]');else if(focus.name)next=content.querySelector('input[name="'+focus.name+'"],select[name="'+focus.name+'"]');next?.focus({preventScroll:true});}});
})(typeof window==='undefined'?globalThis:window);
