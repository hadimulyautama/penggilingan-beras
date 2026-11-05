/* Dipasang pada scope halaman yang diganti PINDAH; tidak menambah listener global. */
(function(){
 const root=document.querySelector('[data-laporan-kontrol]');if(!root||root.dataset.siap)return;root.dataset.siap='1';
 const scope=root.closest('.laporan-riwayat')||root;let asal;
 const dialogs=()=>[...scope.querySelectorAll('dialog.lk-panel,dialog.pd-panduan')];
 scope.querySelectorAll('[data-lk-buka]').forEach(b=>b.addEventListener('click',()=>{
  const target=scope.querySelector('#'+b.dataset.lkBuka);if(!target)return;
  if(!b.closest('dialog'))asal=b;dialogs().filter(d=>d.open).forEach(d=>d.close());target.showModal();
 }));
 dialogs().forEach(d=>{
  d.querySelector('[data-lk-tutup]').addEventListener('click',()=>d.close());
  d.addEventListener('close',()=>{if(asal?.isConnected&&!dialogs().some(x=>x.open))asal.focus()});
  d.addEventListener('click',e=>{const r=d.getBoundingClientRect();if(e.target===d&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))d.close()});
 });
 scope.querySelectorAll('[data-lk-cetak]').forEach(b=>b.addEventListener('click',()=>{
  dialogs().filter(d=>d.open).forEach(d=>d.close());
  const report=scope.querySelector('#lembar');const isi=!!report?.open;
  document.body.classList.toggle('laporan-print-dialog',isi);
  const selesai=()=>document.body.classList.remove('laporan-print-dialog');
  window.addEventListener('afterprint',selesai,{once:true});
  try{window.print()}catch(e){window.removeEventListener('afterprint',selesai);selesai();throw e}
 }));
 const filter=scope.querySelector('.lk-form-filter'),search=scope.querySelector('.lk-pencarian [name=cari]');
 if(filter&&search){
  filter.addEventListener('submit',()=>{filter.elements.cari.value=search.value});
  filter.querySelector('[data-lk-reset]').addEventListener('click',e=>{const a=e.currentTarget;const u=new URL(a.href);u.searchParams.set('cari',search.value);a.href=u.href});
 }
})();
