/* Hanya alat bantu tampilan. Formulir, draf, aturan dan mutasi milik aksi.js. */
(function(){
 'use strict';
 const root=document.querySelector('.pengeringan-detail.dr-redesign');if(!root||root.dataset.desainSiap)return;root.dataset.desainSiap='1';
 const guide=root.querySelector('#dr-panduan');
 for(const b of root.querySelectorAll('[data-dr-guide]'))b.onclick=()=>{const menu=b.closest('details');if(menu)menu.open=false;guide.showModal();};
 root.querySelector('[data-dr-guide-close]').onclick=()=>guide.close();
 guide.addEventListener('click',e=>{if(e.target===guide){const r=guide.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)guide.close();}});
 root.querySelector('[data-dr-refresh]').onclick=()=>location.reload();
 root.querySelector('[data-dr-print]').onclick=()=>window.print();
})();
