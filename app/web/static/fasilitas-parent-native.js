/* Fixed facility parents: only fresh native HTML installs editable controls. */
(function(global){'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const targets=['/pengaturan/gudang','/pengaturan/silo','/pengaturan/mesin','/pengaturan/jenis-proses'];
 function address(value,origin){return core?.sameOriginAddress(value,origin)&&targets.includes(value)?value:null;}
 function configuration(value,origin){
  if(!address(value,origin))return null;
  return {address:value,rootSelector:'[data-fasilitas-parent-kerangka]',statusSelector:'[data-fp-status]',retrySelector:'[data-fp-retry]',shellSelector:'[data-fasilitas-parent-kerangka]',contentAttribute:'data-fasilitas-parent-native-isi',
   messages:{loading:'Memuat pengaturan…',response:'Pengaturan belum dapat dibaca. Sesi dan akses tetap diperiksa oleh halaman native.'},
   restoreFocus({focus,retry,content}){if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});return;}const source=focus.closest('a[href]');if(source)Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===source.getAttribute('href'))?.focus({preventScroll:true});}};
 }
 if(typeof module==='object'&&module.exports){module.exports={address,configuration,targets};return;}
 const root=document.querySelector('[data-fasilitas-parent-kerangka]'),config=root?configuration(root.dataset.url,location.origin):null;
 if(core&&config)core.mount(config);
})(typeof window==='undefined'?globalThis:window);
