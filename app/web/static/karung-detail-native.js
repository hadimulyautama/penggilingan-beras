/* A source-list READ only; never initializes the ownership transaction editor. */
(function(global){'use strict';
 const root=document.querySelector('[data-karung-detail-native]');
 if(!root||!global.PadiKerangkaKarungDetailUI?.address(root.dataset.url,location.origin))return;
 global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-karung-detail-native]',statusSelector:'[data-karung-detail-status]',retrySelector:'[data-karung-detail-retry]',shellSelector:'[data-karung-detail-native]',contentAttribute:'data-karung-detail-isi',messages:{loading:'Memuat sumber terbaru. Status simpan sebelumnya belum diperiksa.',response:'Detail karung belum dapat dibaca. Periksa konteks atau baca lagi; tidak ada pengiriman ulang otomatis.',native:'Detail karung native belum tersedia. Status simpan belum dipastikan.',timeout:'Pembacaan terlalu lama. Coba lagi hanya membaca data.'}});
})(typeof window==='undefined'?globalThis:window);
