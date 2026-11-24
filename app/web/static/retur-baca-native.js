/* Staff native return READ only; no form/stock/post/retry-write state. */
(function(global){'use strict';
 const root=document.querySelector('[data-retur-baca-native]');
 if(!root||!global.PadiKerangkaReturBacaUI?.address(root.dataset.url,location.origin))return;
 global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-retur-baca-native]',statusSelector:'[data-retur-baca-status]',retrySelector:'[data-retur-baca-retry]',shellSelector:'[data-retur-baca-native]',contentAttribute:'data-retur-baca-isi',messages:{loading:'Memuat catatan terbaru. Kerangka tetap tersedia.',response:'Catatan retur belum dapat dibaca. Periksa konteks lalu coba baca lagi; tidak ada transaksi yang dikirim.',native:'Dokumen retur belum tersedia. Tidak ada penerimaan atau pengiriman ulang.',timeout:'Pembacaan terlalu lama. Coba lagi hanya membaca data.'}});
})(typeof window==='undefined'?globalThis:window);
