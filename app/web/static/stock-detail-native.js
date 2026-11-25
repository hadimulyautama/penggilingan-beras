/* Stock/warehouse read-only shell; native GET supplies the real controllers. */
(function(global){'use strict';
 function allowed(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.length>4096)return false;
  let u;try{u=new URL(value,origin);}catch(_){return false;}
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value)return false;
  const allowed=u.pathname==='/stok/pk/detail'?['gudang','kode','id','jasa','pemilik_id','gudang_filter','kembali_stok']:['/stok-produk/detail','/stok-produk-jasa/detail'].includes(u.pathname)?['jenis','pelanggan_id','sumber_page','kembali_stok']:['/gudang/g1','/gudang/g2'].includes(u.pathname)?[]:null;
  if(!allowed)return false;const pairs=[...u.searchParams];return pairs.length<=12&&new Set(pairs.map(p=>p[0])).size===pairs.length&&pairs.every(p=>allowed.includes(p[0]));
 }
 if(typeof module==='object'&&module.exports){module.exports={allowed};return;}
 const root=document.querySelector('[data-stock-detail-native]');if(!root||!allowed(root.dataset.url,location.origin))return;
 global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-stock-detail-native]',statusSelector:'[data-stock-detail-status]',retrySelector:'[data-stock-detail-retry]',shellSelector:'[data-stock-detail-native]',contentAttribute:'data-stock-detail-isi',messages:{loading:'Memuat stok terbaru. Status simpan sebelumnya belum diperiksa.',response:'Stok belum dapat dibaca. Muat ulang bila sumber, gudang atau akses berubah. Status simpan belum dapat dipastikan.',native:'Halaman stok native belum tersedia. Tidak ada pengiriman ulang otomatis.',timeout:'Pembacaan stok terlalu lama. Coba lagi hanya membaca; jangan mengirim ulang transaksi.'}});
})(typeof window==='undefined'?globalThis:window);
