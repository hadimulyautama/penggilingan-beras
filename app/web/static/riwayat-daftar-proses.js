/* Hanya tata letak kontrol. Tautan, kursor, cakupan baca dan isi daftar tetap
   berasal dari server; baris/kartu dan dokumen tidak disalin atau diubah. */
(function(){
 'use strict';
 const root=document.querySelector('[data-daftar-riwayat-proses]');if(!root||root.dataset.rpdReady)return;root.dataset.rpdReady='1';
 const menu=root.querySelector('.rhs-menu'),guide=root.querySelector('#rpd-panduan');
 for(const b of root.querySelectorAll('[data-rpd-guide]'))b.onclick=()=>{if(menu)menu.open=false;guide.showModal();};
 root.querySelector('[data-rpd-guide-close]').onclick=()=>guide.close();
 for(const b of root.querySelectorAll('[data-rpd-print]'))b.onclick=()=>{if(menu)menu.open=false;window.print();};
 // Tautan GET jenis proses tetap navigasi halaman biasa, termasuk klik
 // dengan tombol pengubah. PINDAH menangani siklus listener halaman.
})();
