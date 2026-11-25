/* Read-first line detail only: fresh native HTML alone installs original forms. */
(function(global){'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 function address(value,origin){
  if(!core?.sameOriginAddress(value,origin))return null;
  const m=/^\/pengaturan\/mesin\/([1-9][0-9]{0,9})$/.exec(value);
  return m&&Number(m[1])<=2147483647?value:null;
 }
 function configuration(value,origin){
  if(!address(value,origin))return null;
  return {address:value,rootSelector:'[data-fasilitas-detail-kerangka]',statusSelector:'[data-fd-status]',retrySelector:'[data-fd-retry]',shellSelector:'[data-fasilitas-detail-kerangka]',contentAttribute:'data-fasilitas-detail-native-isi',
   messages:{loading:'Memuat detail mesin…',response:'Detail mesin belum dapat dibaca. Sesi, akses dan keadaan fasilitas tetap diperiksa oleh halaman native.'},
   restoreFocus({focus,retry,content}){if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});return;}const source=focus.closest('a[href]');if(source)Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===source.getAttribute('href'))?.focus({preventScroll:true});}};
 }
 if(typeof module==='object'&&module.exports){module.exports={address,configuration};return;}
 const root=document.querySelector('[data-fasilitas-detail-kerangka]'),config=root?configuration(root.dataset.url,location.origin):null;
 if(core&&config)core.mount(config);
})(typeof window==='undefined'?globalThis:window);
