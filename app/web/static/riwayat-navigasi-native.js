/* Read-only history navigation adapter. Actual native links and server metadata
 * remain authoritative; this module has no writer, request, token or save state.
 */
(function(global){
 'use strict';
 const paths=['/riwayat-giling','/riwayat-sosoh','/riwayat-pengeringan','/riwayat-qc/gabah-basah','/riwayat-qc/gabah-kering','/riwayat-qc/pk-luar','/riwayat-qc/pk-hasil-giling'];
 function resolve(menu,frames,current,last,saved){
  if(!menu||!menu.tabs||typeof menu.default!=='string'||!frames||Array.isArray(frames))return null;
  let target=menu.default;
  const active=Object.values(menu.tabs).find(tab=>Array.isArray(tab?.allowed)&&tab.allowed.includes(current));
  if(active)target=current;
  else if(Object.hasOwn(menu.tabs,last)){
   const tab=menu.tabs[last];
   if(!Array.isArray(tab?.allowed)||typeof tab.first!=='string'||!tab.allowed.includes(tab.first))return null;
   target=tab.allowed.includes(saved)?saved:tab.first;
  }
  return paths.includes(target)&&Object.hasOwn(frames,target)?target:null;
 }
 if(typeof module==='object'&&module.exports){module.exports={resolve,paths};return;}
 function descriptor(){
  const host=document.getElementById('padi-riwayat-kerangka'),frame=document.querySelector('.bingkai');
  if(!host?.isConnected||!frame||frame.dataset.pindahAlamat!==location.pathname+location.search||host.textContent.length>1572864||global.SESIFORM&&!global.SESIFORM.periksa())return null;
  let data;try{data=JSON.parse(host.textContent);}catch(_){return null;}
  if(data?.versi!==1||data.penyandian!=='baris-1'||data.cap!==document.documentElement.dataset.versi||host.dataset.cap!==data.cap||data.konteks!==frame.dataset.pindahKonteks||host.dataset.konteks!==data.konteks||data.sesi!==document.getElementById('formulir-sesi')?.dataset.token||!data.frames||Array.isArray(data.frames)||Object.keys(data.frames).some(path=>!paths.includes(path)))return null;
  return data;
 }
 function prepare(){
  if(!global.PINDAH||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return;
  const data=descriptor();if(!data)return;
  let last=null,saved=null;
  try{last=sessionStorage.getItem('padiflow.riwayat.terakhir');if(['proses','qc','audit','laporan'].includes(last))saved=sessionStorage.getItem('padiflow.riwayat.'+last);}catch(_){}
  const target=resolve(data.menu,data.frames,location.pathname,last,saved);
  if(target)for(const link of document.querySelectorAll('#laci a[href="/riwayat"],#laci a[href="/laporan-riwayat"]')){
   link.setAttribute('href',target);link.dataset.riwayatAliasNative='1';link.removeAttribute('data-utuh');
  }
  const controls=document.querySelector('[data-laporan-kontrol]');if(!controls)return;
  for(const link of controls.querySelectorAll('a[href][data-utuh]')){
   const u=new URL(link.href,location.href);
   if(u.origin===location.origin&&!u.hash&&Object.hasOwn(data.frames,u.pathname)&&!u.search)link.removeAttribute('data-utuh');
  }
  const select=controls.querySelector('[data-jenis-riwayat]');
  if(!select||select.dataset.riwayatNavigasiReady)return;
  select.dataset.riwayatNavigasiReady='1';
  select.addEventListener('change',event=>{
   const current=descriptor(),option=select.selectedOptions[0];
   if(!select.isConnected||!current||!option||option.disabled||!Object.hasOwn(current.frames,option.value)||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return;
   const link=Array.from(controls.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===option.value&&!a.hasAttribute('data-utuh')&&!a.target&&!a.hasAttribute('download'));
   if(!link)return; // Native location.assign remains the fallback.
   event.stopImmediatePropagation();link.click();
  },true);
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',prepare,{once:true});else prepare();
})(typeof window==='undefined'?globalThis:window);
