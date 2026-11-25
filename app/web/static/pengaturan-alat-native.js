/* The Alat link hub only. Native target GETs retain their own guards. */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const ADDRESS='/pengaturan/alat';
 function configuration(address,origin){
  if(address!==ADDRESS||!core?.sameOriginAddress(address,origin))return null;
  return {address,rootSelector:'[data-pengaturan-alat-kerangka]',statusSelector:'[data-alat-native-status]',retrySelector:'[data-alat-native-retry]',shellSelector:'[data-pengaturan-alat-kerangka]',contentAttribute:'data-alat-native-isi',
   messages:{loading:'Memeriksa akses halaman terbaru…',response:'Halaman alat belum dapat dibaca. Sesi dan akses tetap diperiksa oleh halaman native.'},
   restoreFocus({focus,retry,content}){const link=focus===retry?null:focus.closest('a[href]'),target=link?Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===link.getAttribute('href')):null;if(target)target.focus({preventScroll:true});else if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});}}
  };
 }
 if(typeof module==='object'&&module.exports){module.exports={configuration};return;}
 const root=document.querySelector('[data-pengaturan-alat-kerangka]'),config=root?configuration(root.dataset.url,location.origin):null;
 if(core&&config)core.mount(config);
})(typeof window==='undefined'?globalThis:window);
