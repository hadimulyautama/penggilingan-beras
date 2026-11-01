/* Simpan hanya posisi daftar; filter/pencarian tetap milik navigasi lama. */
(function(){'use strict';const tag=document.querySelector('[data-posisi-penerimaan]');if(!tag||tag.dataset.ready)return;tag.dataset.ready='1';const actor=tag.dataset.posisiPenerimaan;
 const key=()=> 'barang-masuk-posisi:'+actor+':'+location.pathname+location.search;
 const holder=document.querySelector('.isi')||document.querySelector('main');if(!holder)return;
 holder.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(!a)return;const u=new URL(a.href,location.href);if(u.origin!==location.origin||!/^\/barang-masuk\/\d+$/.test(u.pathname))return;try{sessionStorage.setItem(key(),String(holder.scrollTop));}catch(_){}});
 try{const back='barang-masuk-kembali:'+actor;if(sessionStorage.getItem(back)===location.pathname+location.search){const y=Number(sessionStorage.getItem(key()));sessionStorage.removeItem(back);if(Number.isFinite(y))requestAnimationFrame(()=>holder.scrollTo({top:y}));}}catch(_){}
})();
