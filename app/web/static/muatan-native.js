/* Pending Muatan only reads native HTML; the original editor owns drafts and writes. */
(function(global){'use strict';
 const root=document.querySelector('[data-muatan-native]');
 if(!root||root.dataset.url!=='/muatan'||location.pathname+location.search!=='/muatan')return;
 global.PADI_BACA_NATIVE?.mount({address:'/muatan',rootSelector:'[data-muatan-native]',
  statusSelector:'[data-muat-native-status]',retrySelector:'[data-muat-native-retry]',
  shellSelector:'[data-muatan-native]',contentAttribute:'data-muat-native-isi',
  messages:{loading:'Memuat kiriman…',response:'Kiriman belum dapat dibaca. Sesi dan akses tetap diperiksa pada halaman native.'},
  onFailure(){for(const p of root.querySelectorAll('[data-muat-unread]'))p.textContent='Kiriman belum berhasil dibaca; ini bukan keadaan kosong atau saldo nol. Coba lagi hanya membaca data.';},
  restoreFocus({focus,retry,content}){if(focus===retry){const heading=content.querySelector('[data-lembar-muatan] h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}}}
 });
})(typeof window==='undefined'?globalThis:window);
