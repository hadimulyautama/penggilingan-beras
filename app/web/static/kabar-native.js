/* Kabar GET reader. Mark/open notification actions remain native POST only. */
(function(global){'use strict';
 function allowed(value,origin){if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//'))return false;let u;try{u=new URL(value,origin);}catch(_){return false;}
 const q=u.searchParams,pairs=[...q];if(u.origin!==origin||u.hash||u.pathname!=='/kabar'||u.pathname+u.search!==value||u.search.length>2049||pairs.length>5||new Set(pairs.map(x=>x[0])).size!==pairs.length||pairs.some(x=>!['tab','jenis','batas','sampai','sebelum'].includes(x[0])))return false;
 for(const [key,min,max]of[['batas',1,100],['sampai',0,2147483647],['sebelum',1,2147483647]])if(q.has(key)&&(!/^[0-9]+$/.test(q.get(key))||Number(q.get(key))<min||Number(q.get(key))>max))return false;return true;}
 if(typeof module==='object'&&module.exports){module.exports={allowed};return;}
 const root=document.querySelector('[data-kabar-native]');if(!root||!allowed(root.dataset.url,location.origin))return;
 global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-kabar-native]',statusSelector:'[data-kabar-native-status]',retrySelector:'[data-kabar-native-retry]',shellSelector:'[data-kabar-native]',contentAttribute:'data-kabar-native-isi',messages:{loading:'Memuat kabar…'},
 restoreFocus({focus,retry,content}){if(focus===retry||focus.hasAttribute('data-kb-panduan'))content.querySelector('[data-kb-panduan]')?.focus({preventScroll:true});}});
})(typeof window==='undefined'?globalThis:window);
