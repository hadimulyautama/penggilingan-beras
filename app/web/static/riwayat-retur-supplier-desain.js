/* GET/tab serta tautan tindakan tetap milik server. Tidak ada pemeriksaan,
   perhitungan stok atau POST yang dijalankan dari halaman baca ini. */
(function(){
 'use strict';
 const root=document.querySelector('[data-riwayat-retur-supplier]');
 if(!root||root.dataset.rsdReady)return;root.dataset.rsdReady='1';
 const menu=root.querySelector('.rhs-menu'),guide=root.querySelector('#rsd-panduan');
 for(const b of root.querySelectorAll('[data-rsd-guide]'))b.onclick=()=>{if(menu)menu.open=false;guide.showModal();};
 root.querySelector('[data-rsd-guide-close]').onclick=()=>guide.close();
 const tabs=[...root.querySelectorAll('.rsh-tabs [role=tab]')];
 root.querySelector('.rsh-tabs').addEventListener('keydown',e=>{let i=tabs.indexOf(e.target);if(i<0||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();i=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[i].click();});
 function hash(){let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(_){return;}if(!id)return;const target=document.getElementById(id);if(target&&root.contains(target))target.scrollIntoView({block:'nearest'});}
 hash();if(window.PINDAH)PINDAH.pasang(window,'hashchange',hash);else window.addEventListener('hashchange',hash);
})();
