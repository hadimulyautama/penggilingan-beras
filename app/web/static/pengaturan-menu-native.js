/* Explicit two-route settings adopter. Native server guards own authority. */
(function(global){
 'use strict';
 const ADDRESSES=['/pengaturan','/pengaturan/sesi'];
 function configuration(address){
  if(!ADDRESSES.includes(address))return null;
  return {address,rootSelector:'[data-pengaturan-menu-kerangka]',statusSelector:'[data-pengaturan-menu-status]',retrySelector:'[data-pengaturan-menu-retry]',shellSelector:'[data-pengaturan-menu-kerangka]',contentAttribute:'data-pengaturan-menu-isi',messages:{loading:'Memuat pengaturan…'},
   restoreFocus({focus,retry,content}){
    let next;
    if(focus===retry){content.tabIndex=-1;next=content;}
    else {const link=focus.closest('a[href]');if(link)next=Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===link.getAttribute('href'));}
    next?.focus({preventScroll:true});
   }};
 }
 if(typeof module==='object'&&module.exports){module.exports={configuration};return;}
 const root=document.querySelector('[data-pengaturan-menu-kerangka]');
 const config=root?configuration(root.dataset.url):null;
 if(config&&global.PADI_BACA_NATIVE)global.PADI_BACA_NATIVE.mount(config);
})(typeof window==='undefined'?globalThis:window);
