/* Terikat elemen yang ikut diganti PINDAH, bukan salinan listener global. */
(function(){
 const root=document.querySelector('[data-jasa-kontrol]');if(!root||root.dataset.siap)return;root.dataset.siap='1';let asal;
 root.querySelectorAll('[data-js-buka]').forEach(b=>b.addEventListener('click',()=>{if(!b.closest('dialog'))asal=b;root.querySelectorAll('dialog[open]').forEach(d=>d.close());root.querySelector('#'+b.dataset.jsBuka).showModal()}));
 root.querySelectorAll('dialog').forEach(d=>{d.querySelector('[data-js-tutup]').addEventListener('click',()=>d.close());d.addEventListener('close',()=>{if(asal&&!root.querySelector('dialog[open]'))asal.focus()});d.addEventListener('click',e=>{const r=d.getBoundingClientRect();if(e.target===d&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))d.close()})});
 root.querySelectorAll('[data-js-cetak]').forEach(b=>b.addEventListener('click',()=>{root.querySelectorAll('dialog[open]').forEach(d=>d.close());window.print()}));
 const filter=root.querySelector('.js-form-filter');if(filter)filter.addEventListener('submit',()=>{filter.elements.cari.value=root.querySelector('.kontrol-pencarian__form [name=cari]').value});
})();
