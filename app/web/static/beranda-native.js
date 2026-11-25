/* Explicit Home read. Figures and native action controllers arrive fresh. */
(function(global){'use strict';
 const root=document.querySelector('[data-beranda-native]');
 if(!root||root.dataset.url!=='/'||location.pathname+location.search!=='/')return;
 global.PADI_BACA_NATIVE?.mount({address:'/',rootSelector:'[data-beranda-native]',
  statusSelector:'[data-home-native-status]',retrySelector:'[data-home-native-retry]',
  shellSelector:'[data-beranda-native]',contentAttribute:'data-home-native-isi',
  messages:{loading:'Memuat data Beranda…',response:'Data Beranda belum dapat dibaca. Sesi dan akses tetap diperiksa pada halaman native.'},
  onFailure(){for(const p of root.querySelectorAll('[data-home-unread]'))p.textContent='Data bagian ini belum berhasil dibaca; ini bukan keadaan kosong atau saldo nol. Coba lagi hanya membaca data.';},
  restoreFocus({focus,retry,content}){if(focus===retry){const heading=content.querySelector('#judul-beranda');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}}}
 });
})(typeof window==='undefined'?globalThis:window);
