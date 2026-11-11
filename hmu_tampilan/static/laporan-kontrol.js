/* Dipasang pada scope halaman yang diganti PINDAH; tidak menambah listener global. */
(function(){
 const root=document.querySelector('[data-laporan-kontrol]');if(!root||root.dataset.siap)return;root.dataset.siap='1';
 const scope=root.closest('.laporan-riwayat')||root;let asal;
 // Riwayat dan laporan adalah pintu berbeda. Ingatan hanya memuat
 // daftar riwayat yang diizinkan server, termasuk ketika sedang di laporan.
 try{
  const resolved={};
  for(const t of JSON.parse(root.dataset.tujuanTab||'[]')){
   if(!t.boleh)continue;
   const key='padiflow.riwayat.'+t.kunci;
   const allowed=t.alamat||[];
   const current=allowed.find(p=>location.pathname===p||location.pathname.startsWith(p+'/'));
   const saved=sessionStorage.getItem(key);
   const url=current||(allowed.includes(saved)?saved:t.href);
   resolved[t.kunci]=url;
   if(current&&root.dataset.aktif===t.kunci){sessionStorage.setItem(key,current);sessionStorage.setItem('padiflow.riwayat.terakhir',t.kunci);}
   const link=root.querySelector('[data-tab-riwayat="'+t.kunci+'"]');if(link)link.href=url;
  }
  const last=sessionStorage.getItem('padiflow.riwayat.terakhir');
  const menu=document.querySelector('#laci a.pintu[href="/riwayat"]');
  if(menu&&resolved[last])menu.href=resolved[last];
 }catch(_){}
 const jenis=root.querySelector('[data-jenis-riwayat]');
 jenis?.addEventListener('change',()=>{
  const opsi=jenis.selectedOptions[0];
  if(opsi&&!opsi.disabled&&opsi.value.startsWith('/riwayat-'))location.assign(opsi.value);
 });
 const dialogs=()=>[...scope.querySelectorAll('dialog.lk-panel,dialog.pd-panduan')];
 scope.querySelectorAll('[data-lk-buka]').forEach(b=>b.addEventListener('click',()=>{
  const target=scope.querySelector('#'+b.dataset.lkBuka);if(!target)return;
  if(!b.closest('dialog'))asal=b;dialogs().filter(d=>d.open).forEach(d=>d.close());target.showModal();
 }));
 dialogs().forEach(d=>{
  d.querySelector('[data-lk-tutup]')?.addEventListener('click',()=>d.close());
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
