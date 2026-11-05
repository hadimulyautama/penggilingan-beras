/* Penyajian saja. Panel data, link paginasi dan tindakan operasional memakai
   komponen/server asli; tidak ada penulisan maupun penghitungan bobot di sini. */
(function(){
 'use strict';
 const root=document.querySelector('[data-riwayat-pengeringan]');if(!root||root.dataset.rhpReady)return;root.dataset.rhpReady='1';
 const tabs=[...root.querySelectorAll('.pengeringan-tabs [role=tab]')],panels=tabs.map(t=>root.querySelector('#'+t.getAttribute('aria-controls')));
 function show(id,update=false){const panel=root.querySelector('#panel-'+id);if(!panel||!panels.includes(panel))return;panels.forEach(p=>p.hidden=p!==panel);tabs.forEach(t=>t.setAttribute('aria-selected',String(t.getAttribute('aria-controls')===panel.id)));if(update){const url=new URL(location.href);url.searchParams.set('tab_detail',id);url.searchParams.delete('buka');url.searchParams.delete('nilai');url.hash=panel.id;history.replaceState(history.state,'',url);}}
 function fromHash(){let id;try{id=decodeURIComponent(location.hash.slice(1))}catch(_){return}const target=document.getElementById(id);if(!target||!root.contains(target))return;const panel=target.closest('[role=tabpanel]');if(!panel||!panels.includes(panel))return;show(panel.id.slice(6));for(let p=target.parentElement;p&&p!==root;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;target.scrollIntoView({block:'nearest'});}
 for(const a of root.querySelectorAll('.pengeringan-tabs a,[data-rhp-go],a[href*="#panel-"]'))a.addEventListener('click',e=>{if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0)return;const url=new URL(a.href,location.href);const id=a.dataset.rhpGo||url.hash.replace('#panel-','');if(!panels.some(p=>p.id==='panel-'+id))return;e.preventDefault();e.stopPropagation();show(id,true);});
 // Paginasi dibentuk server dari URL awal. Tab lokal dapat berubah sesudahnya;
 // ikat setiap link ke panel asalnya agar query tab lama tidak membuka panel lain.
 for(const p of panels)for(const a of p.querySelectorAll('nav a[href]')){const url=new URL(a.href,location.href);if(url.origin===location.origin&&url.pathname===location.pathname){url.searchParams.set('tab_detail',p.id.slice(6));a.href=url.href;}}
 // Formulir tindakan tetap milik katalog lama. Jaga tab asal ketika GET
 // tindakan memuat ulang bingkai, termasuk setelah tab dipilih secara lokal.
 for(const a of root.querySelectorAll('a[href*="buka="]')){const url=new URL(a.href,location.href),panel=a.closest('[role=tabpanel]');if(panel&&url.origin===location.origin&&url.pathname===location.pathname){url.searchParams.set('tab_detail',panel.id.slice(6));a.href=url.href;}}
 root.querySelector('.pengeringan-tabs').addEventListener('keydown',e=>{const i=tabs.indexOf(e.target);if(i<0||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;show(tabs[n].getAttribute('aria-controls').slice(6),true);tabs[n].focus();});
 const guide=root.querySelector('#rhp-panduan');for(const b of root.querySelectorAll('[data-rhp-guide]'))b.onclick=()=>{root.querySelector('.rhs-menu').open=false;guide.showModal();};root.querySelector('[data-rhp-guide-close]').onclick=()=>guide.close();root.querySelector('[data-rhp-print]').onclick=()=>window.print();
 const slot=root.querySelector('[data-rhp-parent-nav-slot]'),navDialog=root.querySelector('#rhp-navigation'),nav=document.querySelector('.laporan-riwayat>.laporan-nav');
 if(slot&&navDialog&&nav){for(const d of [...nav.querySelectorAll('dialog')])nav.before(d);slot.append(nav);root.querySelector('[data-rhp-nav-open]').onclick=()=>{root.querySelector('.rhs-menu').open=false;navDialog.showModal();};root.querySelector('[data-rhp-nav-close]').onclick=()=>navDialog.close();}
 fromHash();if(window.PINDAH)PINDAH.pasang(window,'hashchange',fromHash);else window.addEventListener('hashchange',fromHash);
})();
