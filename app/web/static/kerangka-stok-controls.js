/* Struktur Stok publik: pilihan pending tetap GET, tanpa opsi/entitas asal. */
(function(){
 'use strict';
 const root=document.querySelector('[data-halaman-bertahap][data-kind="stok"][data-ui-stock-public]');
 if(!root||root.dataset.uiStockReady)return;root.dataset.uiStockReady='1';
 const controls=root.querySelector('[data-stok-controls]'),filter=controls.querySelector('.sk-form-filter'),search=controls.querySelector('.kontrol-pencarian__form');
 const owner=filter.querySelector('select[name=pemilik]'),customer=filter.querySelector('input[type=hidden][name=pelanggan_id]');
 function sync(){
  const show=owner.value==='jasa';
  controls.querySelector('[data-stok-pelanggan]').hidden=!show;
  const note=controls.querySelector('#ui-stock-pelanggan_id-reason');if(note)note.hidden=!show;
  if(customer)customer.disabled=!show;
 }
 owner.addEventListener('change',sync);sync();
 filter.addEventListener('submit',()=>{filter.querySelector('input[name=cari]').value=search.querySelector('input[name=cari]').value;});
})();
