/* Struktur kosong dua daftar. Tidak membaca saldo atau menghitung ulangnya.
 * Baris pesan dibersihkan sebelum enumerasi pencarian native.
 */
window.PadiDaftarKosong=function(container,config){
 'use strict';if(!container||container.dataset.daftarKosongReady)return;container.dataset.daftarKosongReady='1';
 let queued=false,last=[],lastMessage=null;
 const loads=[];
 const area=container.querySelector('.stok-seragam,.laporan-isi')||container;
 const rowSelector=(config.kind==='pekerjaan'?'.benda[data-cari],':'')+'.proses-aktif-list__row,.stok-baris__tautan,.stok-mobile-list__baris,.produk-list .tabel-standar__item,.karung-tabel tbody tr:not([data-daftar-pesan])';
 function rows(node){return Array.from(node.querySelectorAll(rowSelector));}
 function visible(node){return !node.hidden&&!!node.getClientRects().length;}
 function message(){const q=new URLSearchParams(location.search);return q.get('cari')?.trim()||config.scopeFiltered?'Tidak ada hasil pada filter ini. Atur ulang filter untuk memeriksa seluruh cakupan.':config.kind==='pekerjaan'?(config.tab==='tindakan'?'Tidak ada pekerjaan perlu tindakan pada cakupan ini.':'Belum ada proses aktif pada cakupan ini.'):'Belum ada stok pada cakupan ini.';}
 function clear(){area.querySelectorAll('[data-daftar-pesan],[data-daftar-kosong]').forEach(n=>n.remove());}
 function table(text){
  const box=document.createElement('div');box.className='halaman-bertahap__scroll';box.dataset.daftarKosong='';box.tabIndex=0;box.setAttribute('role','region');box.setAttribute('aria-label','Daftar · tabel dapat digulir');
  const t=document.createElement('table');t.className='halaman-bertahap__tabel';const head=t.createTHead().insertRow();
  for(const label of config.columns){const th=document.createElement('th');th.scope='col';th.textContent=label;head.append(th);}
  const cell=t.createTBody().insertRow().insertCell();cell.colSpan=config.columns.length;cell.textContent=text;box.append(t);return box;
 }
 function dispose(){observer.disconnect();for(const [node,fn] of loads){node.removeEventListener('load',fn);node.removeEventListener('error',fn);}loads.length=0;}
 const observer=new MutationObserver(records=>{if(!container.isConnected){dispose();return;}if(records.some(r=>container.contains(r.target)))schedule();});
 function observe(){observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden']});}
 function withoutObserver(fn){observer.disconnect();fn();if(container.isConnected)observe();}
 function groups(){
  const found=[];
  for(const t of area.querySelectorAll('table:not(.halaman-bertahap__tabel)')){
   if(!visible(t)||!rows(t).length)continue;
   found.push({node:t,target:visible(t.tHead||t)?t:t.closest('.karung-bagian')||t.parentElement,mode:t.tHead&&visible(t.tHead)?'table':'mobile'});
  }
  for(const g of area.querySelectorAll('.produk-list')){
   if(!visible(g)||!rows(g).length)continue;
   const head=g.querySelector('.tabel-standar__kepala');
   found.push({node:g,target:head&&visible(head)?head.parentElement:g.closest('.produk-grup')||g,mode:head&&visible(head)?'grid':'mobile'});
  }
  for(const g of area.querySelectorAll('.stok-mobile-list__bagian'))if(visible(g)&&rows(g).length)found.push({node:g,target:g,mode:'mobile'});
  return found;
 }
 function update(){
  queued=false;if(!container.isConnected){dispose();return;}
  const data=rows(area),text=message(),found=groups();
  const state=!data.length?[{node:area,target:area,mode:'empty',empty:true}]:found.length?found.map(g=>({...g,empty:!rows(g.node).some(visible)})):[{node:area,target:area,mode:'mobile',empty:!data.some(visible)}];
  if(text===lastMessage&&state.length===last.length&&state.every((s,i)=>s.node===last[i].node&&s.target===last[i].target&&s.mode===last[i].mode&&s.empty===last[i].empty))return;
  last=state;lastMessage=text;
  withoutObserver(()=>{
   clear();
   for(const s of state){
    if(!s.empty)continue;
    if(s.mode==='empty')area.querySelectorAll('.kosong').forEach(n=>n.remove());
    if(s.mode==='table'){const row=s.node.tBodies[0].insertRow();row.dataset.daftarPesan='';const cell=row.insertCell();cell.colSpan=s.node.tHead.rows[0].cells.length;cell.textContent=text;}
    else if(s.mode==='grid'){const row=document.createElement('div');row.dataset.daftarPesan='';row.setAttribute('role','row');row.className='halaman-bertahap__pesan-grid';row.textContent=text;s.target.append(row);}
    else s.target.append(table(text));
   }
  });
 }
 function schedule(){if(!queued){queued=true;queueMicrotask(update);}}
 const clearBeforeFilter=()=>{last=[];withoutObserver(clear);schedule();};
 container.addEventListener('submit',clearBeforeFilter,true);
 container.addEventListener('search',clearBeforeFilter,true);
 container.addEventListener('keydown',e=>{if(e.key==='Escape')clearBeforeFilter();},true);
 if(window.PINDAH)PINDAH.pasang(window,'resize',schedule);
 // Only pending styles can change layout; persistent loaded HEAD links must
 // not retain closures for detached transaction documents.
 for(const node of document.querySelectorAll('link[rel=stylesheet]'))if(!node.sheet){
  const done=()=>{node.removeEventListener('load',done);node.removeEventListener('error',done);const i=loads.findIndex(x=>x[0]===node);if(i>=0)loads.splice(i,1);schedule();};
  loads.push([node,done]);node.addEventListener('load',done);node.addEventListener('error',done);
 }
 update();
};
