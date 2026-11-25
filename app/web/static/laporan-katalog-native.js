/* Katalog metadata native saja; laporan/data/PDF tetap reader aslinya. */
(function(){
 'use strict';
 window.PADI_BACA_NATIVE?.mount({address:'/laporan',rootSelector:'[data-laporan-katalog-kerangka]',
  statusSelector:'[data-katalog-native-status]',retrySelector:'[data-katalog-native-retry]',
  messages:{loading:'Membaca navigasi dan akses terbaru…',response:'Katalog belum dapat dibaca ulang. Muat ulang bila sesi atau akses berubah.',
   native:'Katalog native belum tersedia. Coba lagi hanya membaca data.',timeout:'Pembacaan katalog terlalu lama. Coba lagi hanya membaca data.'},
  restoreFocus({focus,retry,content}){const selector=focus===retry?'[data-lk-buka="lk-panduan"]':focus.closest('[data-lk-buka]')?'[data-lk-buka="'+CSS.escape(focus.closest('[data-lk-buka]').dataset.lkBuka)+'"]':null;if(selector)content.querySelector(selector)?.focus({preventScroll:true});}
 });
})();
