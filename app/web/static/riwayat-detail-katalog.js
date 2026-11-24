/* Root memasang ini hanya sesudah katalog privat sumber native tersedia.
 * Kode/summary lama memakai location.href. Biarkan SDK existing menangani
 * klik GET pada href yang sama, tanpa menyentuh penjaga editor atau writer. */
(function(global){
 'use strict';
 function anchorHandler(text){return String(text||'').replace(/\s+/g,'').replace(/;$/,'')==='event.preventDefault();event.stopPropagation();location.href=this.href';}
 function summaryHandler(text,href){
  const match=/^event\.preventDefault\(\);location\.href=(['"])([^'"]+)\1;?$/.exec(String(text||'').replace(/\s+/g,''));
  return !!match&&match[2]===href;
 }
 if(typeof module==='object'&&module.exports){module.exports={anchorHandler,summaryHandler};return;}
 function install(){
  if(document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return;
  const api=global.PadiKerangkaRiwayatDetailUI,frame=document.querySelector('.bingkai'),token=document.getElementById('formulir-sesi')?.dataset.token,cap=document.documentElement.dataset.versi;
  if(!api||!frame||!token||!cap)return;
  const catalog=api.currentCatalog(frame.dataset.pindahKonteks,cap,token);if(!catalog)return;
  for(const entry of catalog.entries){
   if(!entry.variant.startsWith('riwayat-'))continue;
   const link=api.visibleLink(entry);if(!link)continue;
   const inline=link.getAttribute('onclick');if(inline&&!anchorHandler(inline))continue;
   if(inline)link.removeAttribute('onclick');
   const summary=link.closest('summary');
   if(summary&&summaryHandler(summary.getAttribute('onclick'),entry.alamat)&&!summary.dataset.rdnLinkReady){
    summary.removeAttribute('onclick');summary.dataset.rdnLinkReady='1';
    summary.addEventListener('click',event=>{
     if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||event.target.closest('a,button,input,select,textarea'))return;
     event.preventDefault();link.click();
    });
   }
  }
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})(typeof window==='undefined'?globalThis:window);
