/* Pembaca Operator saja. Isi berasal dari GET native, tidak memuat writer QC. */
(function(){
 'use strict';
 function mulai(){
  const root=document.querySelector('[data-qc-beras-shell]');if(!root||root.dataset.qbReady)return;root.dataset.qbReady='1';
  const status=root.querySelector('#qc-beras-status'),retry=root.querySelector('[data-qc-beras-retry]');
  const cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token||'',context=root.dataset.qcContext,path=location.pathname;
  const tabs=[...root.querySelectorAll('[role=tab]')],panels=[...root.querySelectorAll('[data-rqd-panel]')],events=new AbortController();
  let controller=null,sequence=0,done=false;
  function valid(n){return !done&&root.isConnected&&n===sequence&&location.pathname===path&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&(document.getElementById('formulir-sesi')?.dataset.token||'')===token;}
  function stop(){sequence++;controller?.abort();observer.disconnect();events.abort();}
  const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
  function show(){
   const u=new URL(location.href),key=panels.some(p=>p.dataset.rqdPanel===u.searchParams.get('tab_qc'))?u.searchParams.get('tab_qc'):'ringkasan';
   for(const p of panels)p.hidden=p.dataset.rqdPanel!==key;
   for(const t of tabs){const on=t.id==='qc-tab-'+key,link=new URL(u);link.searchParams.set('tab_qc',t.id.slice(7));t.href=link.pathname+link.search;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;if(on)t.setAttribute('aria-current','page');else t.removeAttribute('aria-current');}
  }
  root.addEventListener('click',e=>{const a=e.target.closest('[role=tab]');if(!a||e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.altKey||e.shiftKey)return;e.preventDefault();const u=new URL(a.href);history.replaceState(history.state,'',u.pathname+u.search);show();},{signal:events.signal});
  root.querySelector('[role=tablist]').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const i=tabs.indexOf(e.target);if(i<0)return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].click();tabs[n].focus();},{signal:events.signal});
  if(window.PINDAH)PINDAH.pasang(window,'popstate',()=>{if(root.isConnected&&!done)show();});
  function install(doc){
   const next=doc.querySelector('[data-riwayat-qc][data-rqd-beras]'),rice=next?.querySelector('[data-qc-sosoh]'),frame=doc.querySelector('.bingkai');
   if(!next||rice?.dataset.kode!==root.dataset.qcRef||next.querySelector('.rhs-code')?.textContent.trim()!==root.dataset.qcRef||next.querySelector('form[method="post"],[data-qc-baru],[data-qc-lengkapi],a[href*="buka="]')||doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||doc.getElementById('formulir-sesi')?.dataset.token!==token)throw Error('Konteks detail QC berubah. Muat ulang untuk memeriksa akses.');
   const header=next.querySelector('.rhs-header'),back=next.querySelector('.rhs-back'),actions=next.querySelector('[data-rqd-proses-aksi]'),origin=next.querySelector('[data-rqd-rice-origin]'),script=root.querySelector('[data-qc-beras-native]');
   const sections=[...rice.children].filter(n=>n.matches('section')),dest={ringkasan:[],sampel:[],sesi:[],asal:[]};
   for(const section of sections){const title=section.querySelector('h2')?.textContent.trim(),id=title==='Riwayat sampel dan hasil QC'?'sampel':title==='Estimasi waktu dan hasil tiap garapan'?'sesi':'ringkasan';dest[id].push(section);}
   if(!header||!back||!actions?.querySelector('a')||!origin||!script?.textContent||!dest.sampel.length||!sections.length)throw Error('Struktur QC beras belum lengkap. Coba lagi.');
   dest.asal.push(...origin.content.children);
   // Header/tabel dan kontrol tab tetap node yang sama ketika hasil masuk.
   // Tidak menjalankan script atau memasukkan form dari respons GET.
   const tableTitles={hasil:'Total hasil timbang per jenis',sampel:'Riwayat sampel dan hasil QC',sesi:'Estimasi waktu dan hasil tiap garapan'};
   for(const [key,title] of Object.entries(tableTitles)){
    const table=root.querySelector('[data-qc-beras-table="'+key+'"]'),section=sections.find(s=>s.querySelector('h2')?.textContent.trim()===title),fresh=section?.querySelector('table');
    if(fresh){if([...fresh.querySelectorAll('thead th')].map(n=>n.textContent.trim()).join('|')!==[...table.querySelectorAll('thead th')].map(n=>n.textContent.trim()).join('|'))throw Error('Kolom QC berubah. Muat ulang halaman.');}
    else if(key==='sampel')throw Error('Sampel QC belum lengkap. Coba lagi.');
   }
   frame.dataset.pindahAlamat=location.pathname+location.search;
   if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Konteks navigasi berubah. Muat ulang halaman.');
   const focus=document.activeElement,oldHeader=root.querySelector('.rhs-header'),heading=oldHeader.querySelector('h1');header.querySelector('h1').replaceWith(heading);oldHeader.replaceChildren(...header.childNodes);
   const currentBack=root.querySelector('.rhs-back');currentBack.href=back.getAttribute('href');currentBack.textContent=back.textContent;
   root.querySelector('[data-rqd-proses-aksi]').replaceChildren(...actions.childNodes);
   for(const [key,title] of Object.entries(tableTitles)){
    const table=root.querySelector('[data-qc-beras-table="'+key+'"]'),section=sections.find(s=>s.querySelector('h2')?.textContent.trim()===title),fresh=section?.querySelector('table');
    if(fresh){table.querySelector('tbody').replaceChildren(...fresh.querySelector('tbody').childNodes);fresh.replaceWith(table);}
    else{table.querySelector('tbody td').textContent=key==='sesi'?'Belum ada sesi QC aktif yang dapat dipetakan. Sampel yang dibatalkan tetap tersedia pada Sampel & hasil.':'Belum ada hasil timbang yang dicatat.';const card=table.closest('section');dest[key==='hasil'?'ringkasan':key].push(card);}
   }
   const shortcuts=document.createElement('section');shortcuts.className='riwayat-detail__card rhs-shortcuts';
   for(const [id,label] of [['sampel','Lihat sampel & hasil QC'],['sesi','Lihat sesi & pemetaan'],['asal','Buka asal & catatan']]){const a=document.createElement('a'),u=new URL(location.href);u.searchParams.set('tab_qc',id);a.href=u.pathname+u.search;a.textContent=label+' →';shortcuts.append(a);}dest.ringkasan.push(shortcuts);
   for(const panel of panels)panel.replaceChildren(...dest[panel.dataset.rqdPanel]);
   const nav=root.closest('.laporan-riwayat')?.querySelector('[data-laporan-kontrol]'),freshNav=doc.querySelector('[data-laporan-kontrol]');
   nav?.querySelectorAll('[data-lk-cetak]').forEach((b,i)=>{const fresh=freshNav?.querySelectorAll('[data-lk-cetak]')[i];if(fresh&&!fresh.disabled){b.disabled=false;b.removeAttribute('aria-describedby');}});
   root.querySelector('[data-qc-beras-state]').remove();done=true;observer.disconnect();events.abort();root.removeAttribute('data-qc-beras-shell');root.setAttribute('data-riwayat-qc','');root.setAttribute('data-rqd-beras','');root.dataset.halamanIsi='qc-detail-beras';
   // Controller native hanya mengikat tab baca. Tanpa data-qc-sosoh,
   // bagian tidak ditata ulang dan editor tidak dipasang.
   const active=document.createElement('script');active.textContent=script.textContent;script.replaceWith(active);
   if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
  }
  async function read(){
   controller?.abort();controller=new AbortController();const active=controller,n=++sequence;retry.hidden=true;status.textContent='Membaca detail QC beras…';const timer=setTimeout(()=>active.abort(),20000);
   try{const response=await fetch(location.pathname+location.search,{credentials:'same-origin',cache:'no-store',signal:active.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n))return;
    if(response.redirected||!response.ok)throw Error([401,403].includes(response.status)?'Sesi atau akses berubah. Muat ulang halaman untuk memeriksa akses.':response.status===404?'Catatan QC beras untuk proses ini tidak ditemukan. Tidak ada perubahan yang disimpan.':'Detail QC belum dapat dibaca. Coba lagi hanya membaca.');
    const html=await response.text();if(!valid(n))return;install(new DOMParser().parseFromString(html,'text/html'));
   }catch(e){if(valid(n)){status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Detail belum tersedia.':e.message;retry.hidden=false;}}
   finally{clearTimeout(timer);if(controller===active)controller=null;}
  }
  retry.addEventListener('click',read,{signal:events.signal});
  if(window.PINDAH)PINDAH.pasang(document,'click',e=>{const a=e.target.closest?.('a[href]');if(a&&!e.button&&!a.target&&!e.defaultPrevented&&!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey&&new URL(a.href,location.href).pathname!==path)stop();});
  // Tautan lama ke komponen QC tetap membuka Sampel & hasil.
  // Hanya state navigasi baca; identitas/aksi tidak diambil dari hash.
  if(location.hash==='#qc-sosoh'){const u=new URL(location.href);u.searchParams.set('tab_qc','sampel');history.replaceState(history.state,'',u.pathname+u.search+u.hash);}
  show();read();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mulai,{once:true});else mulai();
})();
