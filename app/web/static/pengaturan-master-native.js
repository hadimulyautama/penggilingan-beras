/* Two declared master reads only. Addresses never confer permission. */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const PATHS=['/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping'];
 function nativeAddress(address,origin){return core?.sameOriginAddress(address,origin)&&PATHS.includes(address)?address:null;}
 function configuration(address,origin){
  if(!nativeAddress(address,origin))return null;
  return {address,rootSelector:'[data-pengaturan-master-kerangka]',statusSelector:'[data-master-native-status]',retrySelector:'[data-master-native-retry]',
   shellSelector:'[data-pengaturan-master-kerangka]',contentAttribute:'data-master-native-isi',
   messages:{loading:'Memuat data master…',response:'Data master belum dapat dibaca. Sesi dan akses tetap diperiksa oleh halaman native.'},
   restoreFocus({focus,retry,content}){
    if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});return;}
    const source=focus.closest('a[href]'),target=source?Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===source.getAttribute('href')):null;
    target?.focus({preventScroll:true});
   }};
 }
 if(typeof module==='object'&&module.exports){module.exports={nativeAddress,configuration};return;}
 const root=document.querySelector('[data-pengaturan-master-kerangka]'),config=root?configuration(root.dataset.url,location.origin):null;
 if(core&&config)core.mount(config);
})(typeof window==='undefined'?globalThis:window);
