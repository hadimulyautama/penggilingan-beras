/* Struktur kosong dua daftar. Tidak membaca saldo atau menghitung ulangnya.
 * Baris pesan tidak pernah masuk enumerasi data milik pencarian native.
 */
window.PadiDaftarKosong=function(container,config){
 'use strict';if(!container||container.dataset.daftarKosongReady)return;container.dataset.daftarKosongReady='1';
 let queued=false,lastMode=null,lastTarget=null,lastMessage=null;
 const area=container.querySelector('.stok-seragam,.laporan-isi')||container;
 function filtered(){const q=new URLSearchParams(location.search);return !!q.get('cari')?.trim()||config.scopeFiltered;}
 function message(){return filtered()?'Tidak ada hasil pada filter ini. Atur ulang filter untuk memeriksa seluruh cakupan.':config.kind==='pekerjaan'?'Belum ada proses aktif pada cakupan ini.':'Belum ada stok pada cakupan ini.';}
 function rows(){return Array.from(area.querySelectorAll('.proses-aktif-list__row,.stok-baris__tautan,.stok-mobile-list__baris,.produk-list .tabel-standar__item,.karung-tabel tbody tr:not([data-daftar-pesan])'));}
 function clear(){area.querySelectorAll('[data-daftar-pesan],[data-daftar-kosong]').forEach(n=>n.remove());}
 function table(text){
  const box=document.createElement('div');box.className='halaman-bertahap__scroll';box.dataset.daftarKosong='';box.tabIndex=0;box.setAttribute('role','region');box.setAttribute('aria-label','Daftar · tabel dapat digulir');
  const t=document.createElement('table');t.className='halaman-bertahap__tabel';const head=t.createTHead().insertRow();
  for(const label of config.columns){const th=document.createElement('th');th.scope='col';th.textContent=label;head.append(th);}
  const cell=t.createTBody().insertRow().insertCell();cell.colSpan=config.columns.length;cell.textContent=text;box.append(t);return box;
 }
 const observer=new MutationObserver(records=>{if(!container.isConnected){observer.disconnect();return;}if(records.some(r=>container.contains(r.target)))schedule();});
 function observe(){observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden']});}
 function withoutObserver(fn){observer.disconnect();fn();if(container.isConnected)observe();}
 function update(){
  queued=false;if(!container.isConnected){observer.disconnect();return;}
  const data=rows(),text=message(),normal=data.some(n=>!n.hidden&&n.getClientRects().length);
  const t=normal?null:Array.from(area.querySelectorAll('table')).find(n=>!n.closest('[data-daftar-kosong]')&&n.tHead?.getClientRects().length&&n.tBodies[0]?.querySelector('tr:not([data-daftar-pesan])'));
  const grid=normal?null:Array.from(area.querySelectorAll('.tabel-standar__kepala')).find(n=>n.getClientRects().length);
  const mode=normal?'normal':!data.length?'empty':t?'table':grid?'grid':'mobile-empty';
  const target=t||grid||area;
  if(mode===lastMode&&target===lastTarget&&text===lastMessage)return;
  lastMode=mode;lastTarget=target;lastMessage=text;
  withoutObserver(()=>{
   clear();
   if(!data.length){area.querySelectorAll('.kosong').forEach(n=>n.remove());area.append(table(text));return;}
   if(normal)return;
   if(t){const row=t.tBodies[0].insertRow();row.dataset.daftarPesan='';const cell=row.insertCell();cell.colSpan=t.tHead.rows[0].cells.length;cell.textContent=text;return;}
   if(grid){const row=document.createElement('div');row.dataset.daftarPesan='';row.setAttribute('role','row');row.className='halaman-bertahap__pesan-grid';row.textContent=text;grid.parentElement.append(row);return;}
   // Kartu mobile native menyembunyikan kepala tabel. Jika semua hasil
   // tersaring, gunakan struktur kosong yang sama dengan kerangka awal.
   area.append(table(text));
  });
 }
 function schedule(){if(!queued){queued=true;queueMicrotask(update);}}
 const clearBeforeFilter=()=>{lastMode=null;withoutObserver(clear);schedule();};
 container.addEventListener('submit',clearBeforeFilter,true);
 container.addEventListener('search',clearBeforeFilter,true);
 container.addEventListener('keydown',e=>{if(e.key==='Escape')clearBeforeFilter();},true);
 if(window.PINDAH)PINDAH.pasang(window,'resize',schedule);
 document.querySelectorAll('link[rel=stylesheet]').forEach(n=>n.addEventListener('load',schedule,{once:true}));
 update();
};
