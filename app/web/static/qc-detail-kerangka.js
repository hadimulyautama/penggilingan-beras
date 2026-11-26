/* Detail baca gabah/PK saja. Angka, izin dan lot tetap dibaca handler native. */
(function(){
 'use strict';
 const root=document.querySelector('[data-qc-detail-shell]');if(!root||root.dataset.qdReady)return;root.dataset.qdReady='1';
 const status=root.querySelector('#qc-detail-status'),retry=root.querySelector('[data-qc-detail-retry]');
 const cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token||'',context=root.dataset.qcContext;
 const path=location.pathname,tabs=[...root.querySelectorAll('.qc-tabs a')],panels=[...root.querySelectorAll('[data-rqd-panel]')];
 let controller=null,number=0,done=false;
 const events=new AbortController();
 function current(n){return !done&&root.isConnected&&n===number&&location.pathname===path&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
 function stop(){number++;controller?.abort();observer.disconnect();events.abort();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
 function show(){
  const u=new URL(location.href),key=panels.some(p=>p.dataset.rqdPanel===u.searchParams.get('tab_qc'))?u.searchParams.get('tab_qc'):'ringkasan';
  for(const panel of panels)panel.hidden=panel.dataset.rqdPanel!==key;
  for(const tab of tabs){const on=tab.id==='qc-tab-'+key,link=new URL(u);link.searchParams.set('tab_qc',tab.id.slice(7));tab.href=link.pathname+link.search;tab.setAttribute('aria-selected',String(on));tab.tabIndex=on?0:-1;if(on)tab.setAttribute('aria-current','page');else tab.removeAttribute('aria-current');}
 }
 root.addEventListener('click',event=>{const a=event.target.closest('.qc-tabs a');if(!a||event.button||event.metaKey||event.ctrlKey||event.altKey||event.shiftKey)return;event.preventDefault();const u=new URL(a.href,location.href);history.replaceState(history.state,'',u.pathname+u.search);show();},{signal:events.signal});
 root.querySelector('.qc-tabs').addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const i=tabs.indexOf(event.target);if(i<0)return;event.preventDefault();const n=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].click();tabs[n].focus();},{signal:events.signal});
 const restore=()=>{if(root.isConnected)show();};if(window.PINDAH)PINDAH.pasang(window,'popstate',restore);
 function install(doc){
  const next=doc.querySelector('[data-riwayat-qc][data-qc-kind][data-qc-ref]'),frame=doc.querySelector('.bingkai');
  if(!next||next.dataset.qcKind!==root.dataset.qcKind||next.dataset.qcRef!==root.dataset.qcRef||next.querySelector('form[method="post"],[data-qc-sosoh]')||doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||doc.getElementById('formulir-sesi')?.dataset.token!==token)throw Error('Konteks detail QC berubah. Muat ulang halaman.');
  const freshPanels=panels.map(p=>next.querySelector('#'+p.id)),nextTabs=[...next.querySelectorAll('.qc-tabs a')],guide=root.querySelector('#rqd-panduan');
  const header=root.querySelector('header.rhs-header'),freshHeader=next.querySelector('header.rhs-header'),back=root.querySelector('[data-qc-detail-back]'),freshBack=next.querySelector('.riwayat-detail__back');
  const nav=root.closest('.laporan-riwayat')?.querySelector('[data-laporan-kontrol]'),freshNav=doc.querySelector('[data-laporan-kontrol]');
  const schema=n=>JSON.stringify({active:n?.dataset.aktif,allowed:n?.dataset.bolehAlamat,tabs:n?.dataset.tujuanTab});
  if(freshPanels.some(p=>!p)||nextTabs.length!==4||nextTabs.some((t,i)=>t.id!==tabs[i].id)||!guide||!next.querySelector('#rqd-panduan')||!freshHeader||!freshBack||schema(nav)!==schema(freshNav))throw Error('Struktur detail QC belum lengkap. Coba lagi.');
  const script=root.querySelector('[data-qc-detail-native]');if(!script?.textContent)throw Error('Kontrol detail QC belum tersedia. Muat ulang halaman.');
  const picker=root.querySelector('.qc-picker'),nextPicker=next.querySelector('.qc-picker');
  if(!picker||!nextPicker?.querySelector('select')||!nextPicker.querySelector('button'))throw Error('Pilihan putaran belum lengkap. Coba lagi.');
  frame.dataset.pindahAlamat=location.pathname+location.search;
  if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Konteks navigasi berubah. Muat ulang halaman.');
  const focus=document.activeElement,title=header.querySelector('h1');freshHeader.querySelector('h1').replaceWith(title);header.replaceChildren(...freshHeader.childNodes);
  back.href=freshBack.getAttribute('href');back.textContent=freshBack.textContent;
  const select=picker.querySelector('select'),button=picker.querySelector('button');
  select.replaceChildren(...nextPicker.querySelector('select').childNodes);select.disabled=false;select.removeAttribute('aria-describedby');nextPicker.querySelector('select').replaceWith(select);
  button.disabled=false;button.removeAttribute('aria-describedby');nextPicker.querySelector('button').replaceWith(button);
  for(const a of [...picker.attributes])picker.removeAttribute(a.name);for(const a of nextPicker.attributes)picker.setAttribute(a.name,a.value);picker.replaceChildren(...nextPicker.childNodes);nextPicker.replaceWith(picker);
  panels.forEach((panel,i)=>panel.replaceChildren(...freshPanels[i].childNodes));
  nav?.querySelectorAll('[data-lk-cetak]').forEach((b,i)=>{const nextButton=freshNav.querySelectorAll('[data-lk-cetak]')[i];if(nextButton&&!nextButton.disabled){b.disabled=false;b.removeAttribute('aria-describedby');}});
  root.querySelector('[data-qc-detail-state]').remove();done=true;observer.disconnect();events.abort();root.removeAttribute('data-qc-detail-shell');root.setAttribute('data-riwayat-qc','');root.dataset.halamanIsi='qc-detail-'+root.dataset.qcKind;
  // Jalankan hanya controller native yang sudah dipin bersama kerangka,
  // bukan script dari respons GET. Tidak ada writer/rumus di adapter ini.
  const active=document.createElement('script');active.textContent=script.textContent;script.replaceWith(active);
  if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
 }
 async function read(){
  controller?.abort();controller=new AbortController();const active=controller,n=++number;retry.hidden=true;status.textContent='Membaca detail QC…';
  const timer=setTimeout(()=>active.abort(),20000);
  try{
   const url=new URL(location.href);url.searchParams.set('kembali_qc',root.querySelector('[data-qc-detail-back]').getAttribute('href'));
   const response=await fetch(url.pathname+url.search,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});
   if(!current(n))return;
   if(response.redirected||!response.ok)throw Error([401,403].includes(response.status)?'Sesi atau akses berubah. Muat ulang halaman untuk memeriksa akses.':response.status===404?'Catatan QC untuk batch atau proses ini tidak ditemukan. Tidak ada perubahan yang disimpan.':'Detail QC belum dapat dibaca. Coba lagi hanya membaca.');
   const html=await response.text();if(!current(n))return;
   const doc=new DOMParser().parseFromString(html,'text/html');install(doc);
  }catch(error){if(current(n)){status.textContent=error.name==='AbortError'?'Pembacaan terlalu lama. Detail belum tersedia.':error.message;retry.hidden=false;}}
  finally{clearTimeout(timer);if(controller===active)controller=null;}
 }
 retry.addEventListener('click',read,{signal:events.signal});
 const leave=event=>{const a=event.target.closest?.('a[href]');if(a&&!event.defaultPrevented&&!event.metaKey&&!event.ctrlKey&&!event.shiftKey&&!event.altKey&&new URL(a.href,location.href).pathname!==path)stop();};if(window.PINDAH)PINDAH.pasang(document,'click',leave);
 show();read();
})();
