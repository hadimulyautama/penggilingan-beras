/* Terikat kepala halaman: aman saat navigasi PINDAH mengganti isi halaman. */
(function () {
 'use strict';
 const root=document.querySelector('[data-bk-controls]');if(!root||root.dataset.bkSiap)return;root.dataset.bkSiap='1';
 let asal;
 const buat=root.querySelector('[data-bk-buat]');
 root.querySelectorAll('[data-bk-buka]').forEach(b=>b.addEventListener('click',()=>{
  if(buat)buat.open=false;
  if(!b.closest('dialog'))asal=b;
  root.querySelectorAll('dialog[open]').forEach(d=>d.close());
  root.querySelector('#'+b.dataset.bkBuka).showModal();
 }));
 root.querySelectorAll('dialog').forEach(d=>{
  d.querySelector('[data-bk-tutup]').addEventListener('click',()=>d.close());
  d.addEventListener('click',e=>{const r=d.getBoundingClientRect();if(e.target===d&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))d.close()});
  d.addEventListener('close',()=>{if(asal&&!root.querySelector('dialog[open]'))asal.focus()});
 });
 root.querySelectorAll('[data-bk-cetak]').forEach(b=>b.addEventListener('click',()=>{root.querySelectorAll('dialog[open]').forEach(d=>d.close());if(buat)buat.open=false;window.print()}));
 const filter=root.querySelector('.bk-form-filter');filter.addEventListener('submit',()=>{filter.elements.q.value=root.querySelector('.bk-pencarian [name=q]').value});
 // Disclosure berisi dua tautan asli; Escape dan klik di luar menutupnya.
 if(buat){document.addEventListener('click',e=>{if(root.isConnected&&!buat.contains(e.target))buat.open=false});buat.addEventListener('keydown',e=>{if(e.key==='Escape'){buat.open=false;buat.querySelector('summary').focus();e.preventDefault()}})}
})();
