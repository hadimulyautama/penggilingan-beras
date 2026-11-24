/* Staff native return READ only; no form/stock/post/retry-write state. */
(function(global){'use strict';
 const object=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k),exact=(x,keys)=>object(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k));
 function receiptTabPlan(identity,tabs,origin,describe){
  if(!exact(identity,['address','cap','context','token'])||!['address','cap','context','token'].every(k=>typeof identity[k]==='string'&&identity[k]&&identity[k].length<=4096)||typeof describe!=='function'||!Array.isArray(tabs)||tabs.length!==4)return null;
  let base;try{base=new URL(identity.address,origin);}catch(_){return null;}
  if(base.origin!==origin||base.hash||base.pathname+base.search!==identity.address)return null;
  const initial=describe(identity.address,origin);if(initial?.kind!=='receipt')return null;
  const views=[];
  for(const tab of tabs){
   if(!exact(tab,['href','controls'])||typeof tab.href!=='string'||!tab.href||tab.href.length>4096||typeof tab.controls!=='string')return null;
   let u;try{u=new URL(tab.href,origin+identity.address);}catch(_){return null;}
   const view=describe(u.pathname+u.search,origin);
   if(u.origin!==origin||u.pathname!==base.pathname||view?.kind!=='receipt'||view.id!==initial.id||u.searchParams.get('tab_detail')!==view.tab||tab.controls!=='panel-'+view.tab||u.hash!=='#'+tab.controls)return null;
   views.push(Object.freeze({href:tab.href,full:u.href,address:u.pathname+u.search,controls:tab.controls}));
  }
  if(new Set(views.map(v=>v.controls)).size!==4||new Set(views.map(v=>v.full)).size!==4)return null;
  return Object.freeze({...identity,origin,views:Object.freeze(views)});
 }
 function nextReceiptAddress(plan,last,current){
  if(!plan||!exact(current,['cap','context','token','frameAddress','href','locationHref','selectedControls','panelVisible','connected','sameRoot','sessionCurrent','nativeHandled'])||typeof last!=='string')return null;
  if(!current.connected||!current.sameRoot||!current.sessionCurrent||!current.nativeHandled||!current.panelVisible||current.cap!==plan.cap||current.context!==plan.context||current.token!==plan.token||current.frameAddress!==last)return null;
  const view=plan.views.find(v=>v.href===current.href&&v.full===current.locationHref&&v.controls===current.selectedControls);
  return view?.address||null;
 }
 function adoptReceiptTabs(content,doc){
  const describe=global.PadiKerangkaReturBacaUI?.address;
  if(!content?.isConnected||!doc||typeof describe!=='function')return false;
  const frame=document.querySelector('.bingkai'),main=document.getElementById('isi-halaman'),session=document.getElementById('formulir-sesi'),freshFrame=doc.querySelector('.bingkai'),freshSession=doc.getElementById('formulir-sesi');
  if(document.querySelectorAll('.bingkai').length!==1||document.querySelectorAll('#isi-halaman').length!==1||document.querySelectorAll('#formulir-sesi').length!==1||!frame||!main||!session||!freshFrame||!freshSession||!frame.contains(main)||!frame.contains(session)||!main.contains(content)||!content.hasAttribute('data-retur-baca-isi')||doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1)return false;
  const roots=content.querySelectorAll('[data-detail-tab]'),freshRoots=doc.getElementById('isi-halaman')?.querySelectorAll('[data-detail-tab]');
  if(roots.length!==1||freshRoots?.length!==1)return false;
  const root=roots[0],freshRoot=freshRoots[0],unsafe='form,[name],[data-post],[data-kirim],[data-retur-form],[data-editor-perintah],[data-kemas-ulang]';
  if(root.querySelector(unsafe)||freshRoot.querySelector(unsafe)||root.matches(unsafe)||freshRoot.matches(unsafe)||root.dataset.returReadTabs)return false;
  const nativeTabs=[...root.querySelectorAll('[role=tablist] [role=tab]')],sourceTabs=[...freshRoot.querySelectorAll('[role=tablist] [role=tab]')];
  if(nativeTabs.length!==4||sourceTabs.length!==4||nativeTabs.some((t,i)=>t.tagName!=='A'||t.getAttribute('href')!==sourceTabs[i].getAttribute('href')||t.getAttribute('aria-controls')!==sourceTabs[i].getAttribute('aria-controls')))return false;
  const identity={address:freshFrame.dataset.pindahAlamat||'',cap:doc.documentElement.dataset.versi||'',context:freshFrame.dataset.pindahKonteks||'',token:freshSession.dataset.token||''},plan=receiptTabPlan(identity,sourceTabs.map(t=>({href:t.getAttribute('href'),controls:t.getAttribute('aria-controls')})),location.origin,describe);
  if(!plan||location.pathname+location.search!==plan.address||frame.dataset.pindahAlamat!==plan.address||document.documentElement.dataset.versi!==plan.cap||frame.dataset.pindahKonteks!==plan.context||session.dataset.token!==plan.token)return false;
  let last=plan.address;root.dataset.returReadTabs='1';
  // Registered AFTER the unchanged native controller. It owns the URL,
  // selected tab and panel; this listener only follows a captured native href.
  root.addEventListener('click',event=>{
   const tab=event.target.closest?.('a');if(!nativeTabs.includes(tab)||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||tab.target)return;
   try{
    const selected=root.querySelector('[role=tab][aria-selected=true]'),controls=selected?.getAttribute('aria-controls'),panel=controls?root.querySelector('#'+CSS.escape(controls)):null;
    const next=nextReceiptAddress(plan,last,{cap:document.documentElement.dataset.versi||'',context:frame.dataset.pindahKonteks||'',token:session.dataset.token||'',frameAddress:frame.dataset.pindahAlamat||'',href:tab.getAttribute('href'),locationHref:location.href,selectedControls:controls||'',panelVisible:!!panel&&!panel.hidden,connected:root.isConnected&&frame.isConnected&&session.isConnected,sameRoot:document.querySelectorAll('.bingkai').length===1&&document.querySelectorAll('#isi-halaman').length===1&&document.querySelectorAll('#formulir-sesi').length===1&&document.querySelector('.bingkai')===frame&&document.getElementById('isi-halaman')===main&&document.getElementById('formulir-sesi')===session&&frame.contains(root)&&main.contains(content)&&!root.matches(unsafe)&&!root.querySelector(unsafe),sessionCurrent:!global.SESIFORM||global.SESIFORM.periksa(),nativeHandled:event.defaultPrevented&&selected===tab});
    if(next){frame.dataset.pindahAlamat=next;last=next;}
   }catch(_){/* Optional read-view adapter declines; native URL/tabs remain. */}
  });
  return true;
 }
 if(typeof module==='object'&&module.exports){module.exports={receiptTabPlan,nextReceiptAddress};return;}
 const root=document.querySelector('[data-retur-baca-native]');
 if(!root||!global.PadiKerangkaReturBacaUI?.address(root.dataset.url,location.origin))return;
 global.PADI_BACA_NATIVE?.mount({address:root.dataset.url,rootSelector:'[data-retur-baca-native]',statusSelector:'[data-retur-baca-status]',retrySelector:'[data-retur-baca-retry]',shellSelector:'[data-retur-baca-native]',contentAttribute:'data-retur-baca-isi',afterInstall({content,doc}){adoptReceiptTabs(content,doc);},messages:{loading:'Memuat catatan terbaru. Kerangka tetap tersedia.',response:'Catatan retur belum dapat dibaca. Periksa konteks lalu coba baca lagi; tidak ada transaksi yang dikirim.',native:'Dokumen retur belum tersedia. Tidak ada penerimaan atau pengiriman ulang.',timeout:'Pembacaan terlalu lama. Coba lagi hanya membaca data.'}});
})(typeof window==='undefined'?globalThis:window);
