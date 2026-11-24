/* Read-only history navigation adapter. Actual native links and server metadata
 * remain authoritative; this module has no writer, request, token or save state.
 */
(function(global){
 'use strict';
 const paths=['/riwayat-giling','/riwayat-sosoh','/riwayat-pengeringan','/riwayat-qc/gabah-basah','/riwayat-qc/gabah-kering','/riwayat-qc/pk-luar','/riwayat-qc/pk-hasil-giling'];
 function resolve(menu,targets,current,last,saved){
  if(!menu||!menu.tabs||typeof menu.default!=='string'||!Array.isArray(targets))return null;
  let target=menu.default;
  const active=Object.entries(menu.tabs).find(([key,tab])=>key!=='laporan'&&Array.isArray(tab?.allowed)&&tab.allowed.includes(current));
  if(active)target=current;
  else if(Object.hasOwn(menu.tabs,last)){
   const tab=menu.tabs[last];
   if(!Array.isArray(tab?.allowed)||typeof tab.first!=='string'||!tab.allowed.includes(tab.first))return null;
   target=tab.allowed.includes(saved)?saved:tab.first;
  }
  return paths.includes(target)&&targets.includes(target)?target:null;
 }
 if(typeof module==='object'&&module.exports){module.exports={resolve,paths};return;}
 function descriptor(){
  const host=document.getElementById('padi-riwayat-kerangka'),frame=document.querySelector('.bingkai');
  if(!host?.isConnected||!frame||frame.dataset.pindahAlamat!==location.pathname+location.search||host.textContent.length>8192||global.SESIFORM&&!global.SESIFORM.periksa())return null;
  let data;try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.sumber!==global.PadiKerangkaRiwayatUI?.sumber||data.cap!==document.documentElement.dataset.versi||host.dataset.cap!==data.cap||data.konteks!==frame.dataset.pindahKonteks||host.dataset.konteks!==data.konteks||data.sesi!==document.getElementById('formulir-sesi')?.dataset.token||!Array.isArray(data.targets)||data.targets.length>7||data.targets.some(path=>!paths.includes(path)))return null;
  return data;
 }
 function prepare(){
  if(!global.PINDAH||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return;
  const data=descriptor();if(!data)return;
  let last=null,saved=null;
  try{last=sessionStorage.getItem('padiflow.riwayat.terakhir');if(['proses','qc','audit','laporan'].includes(last))saved=sessionStorage.getItem('padiflow.riwayat.'+last);}catch(_){}
  const target=resolve(data.menu,data.targets,location.pathname,last,saved);
  if(target)for(const link of document.querySelectorAll('#laci a[href="/riwayat"],#laci a[href="/laporan-riwayat"]')){
   link.setAttribute('href',target);link.dataset.riwayatAliasNative='1';link.removeAttribute('data-utuh');
   const active=data.targets.includes(location.pathname);link.classList.toggle('pintu--kini',active);
   if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  }
  const controls=document.querySelector('[data-laporan-kontrol]');if(!controls)return;
  for(const link of controls.querySelectorAll('a[href][data-utuh]')){
   const u=new URL(link.href,location.href);
   if(u.origin===location.origin&&!u.hash&&data.targets.includes(u.pathname)&&!u.search)link.removeAttribute('data-utuh');
  }
  const select=controls.querySelector('[data-jenis-riwayat]');
  if(!select||select.dataset.riwayatNavigasiReady)return;
  select.dataset.riwayatNavigasiReady='1';
  select.addEventListener('change',event=>{
   const current=descriptor(),option=select.selectedOptions[0];
   if(!select.isConnected||!current||!option||option.disabled||!current.targets.includes(option.value)||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return;
   const link=Array.from(controls.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===option.value&&!a.hasAttribute('data-utuh')&&!a.target&&!a.hasAttribute('download'));
   if(!link)return; // Native location.assign remains the fallback.
   event.stopImmediatePropagation();link.click();
  },true);
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',prepare,{once:true});else prepare();
})(typeof window==='undefined'?globalThis:window);
