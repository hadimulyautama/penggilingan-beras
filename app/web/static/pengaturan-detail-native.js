/* Six explicit native read paths. A path is correlation, never permission. */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const PATHS=['peran','akses','sebab-berhenti','mutu','kledo','sistem'].map(x=>'/pengaturan/'+x);
 function configuration(address,origin){
  if(!PATHS.includes(address)||!core?.sameOriginAddress(address,origin))return null;
  return {address,rootSelector:'[data-pengaturan-detail-kerangka]',statusSelector:'[data-pengaturan-detail-status]',retrySelector:'[data-pengaturan-detail-retry]',shellSelector:'[data-pengaturan-detail-kerangka]',contentAttribute:'data-pengaturan-detail-native-isi',
   messages:{loading:'Memuat rincian Pengaturan…',response:'Rincian Pengaturan belum dapat dibaca. Sesi dan akses tetap diperiksa oleh halaman native.'},
   restoreFocus({focus,retry,content}){if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});return;}const link=focus.closest('a[href]');if(link)Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===link.getAttribute('href'))?.focus({preventScroll:true});}
  };
 }
 if(typeof module==='object'&&module.exports){module.exports={configuration};return;}
 const root=document.querySelector('[data-pengaturan-detail-kerangka]'),config=root?configuration(root.dataset.url,location.origin):null;
 if(core&&config)core.mount(config);
})(typeof window==='undefined'?globalThis:window);
