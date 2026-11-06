/* Hanya tata letak kontrol. Tautan, kursor, cakupan baca dan isi daftar tetap
   berasal dari server; baris/kartu dan dokumen tidak disalin atau diubah. */
(function(){
 'use strict';
 const root=document.querySelector('[data-daftar-riwayat-proses]');if(!root||root.dataset.rpdReady)return;root.dataset.rpdReady='1';
 const menu=root.querySelector('.rhs-menu'),guide=root.querySelector('#rpd-panduan'),navigation=root.querySelector('#rpd-navigation');
 const nav=document.querySelector('.laporan-riwayat>.laporan-nav'),slot=root.querySelector('[data-rpd-parent-nav-slot]'),category=root.querySelector('[data-rpd-category-slot]');
 if(nav&&slot&&navigation){
  // Node asli mempertahankan tautan, penanda aktif dan pilihan terkunci.
  // Dialog bawaan berada di luar dialog navigasi supaya tidak bertumpuk.
  for(const d of [...nav.querySelectorAll('dialog')])nav.before(d);
  const types=nav.querySelector('.laporan-nav__jenis');if(types&&category)category.append(types);
  slot.append(nav);
  root.querySelector('[data-rpd-nav-open]').onclick=()=>{menu.open=false;navigation.showModal();};
  root.querySelector('[data-rpd-nav-close]').onclick=()=>navigation.close();
 }
 for(const b of root.querySelectorAll('[data-rpd-guide]'))b.onclick=()=>{menu.open=false;guide.showModal();};
 root.querySelector('[data-rpd-guide-close]').onclick=()=>guide.close();
 for(const b of root.querySelectorAll('[data-rpd-print]'))b.onclick=()=>{menu.open=false;window.print();};
 // Tautan GET jenis proses tetap navigasi halaman biasa, termasuk klik
 // dengan tombol pengubah. PINDAH menangani siklus listener halaman.
})();
