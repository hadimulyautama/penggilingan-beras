/* Satu tab baca; saldo/kemasan/lot dan otorisasi tetap dari handler native. */
(function(){
 'use strict';
 const root=document.querySelector('[data-jst-shell]');if(!root||root.dataset.jstReady)return;root.dataset.jstReady='1';
 const panel=root.querySelector('[data-jst-panel]'),grid=panel.querySelector('.jasa-stok'),links=[...root.querySelectorAll('[data-jst-target]')],controls=document.querySelector('[data-jst-controls]'),status=document.getElementById('jst-baca-status'),retry=document.querySelector('[data-jst-retry]'),main=document.getElementById('isi-halaman');
 const path=location.pathname,cap=document.documentElement.dataset.versi,context=root.dataset.jstContext,token=document.getElementById('formulir-sesi')?.dataset.token,keys=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status'],life=new AbortController();
 const marks=[...grid.childNodes].filter(n=>n.nodeType===8),start=marks.find(n=>n.data.trim()==='stok:mulai'),end=marks.find(n=>n.data.trim()==='stok:akhir');if(!start||!end)return;
 let number=0,request=null,target=null,stopped=false;
 function allowed(raw){try{const u=new URL(raw,location.href);return u.origin===location.origin&&u.pathname===path&&!u.hash&&u.href.length<4096&&u.searchParams.get('tab')==='stok'&&[...u.searchParams.keys()].every(k=>keys.includes(k)&&u.searchParams.getAll(k).length===1&&u.searchParams.get(k).length<=200)?u:null;}catch(_){return null;}}
 function current(n,u){return !stopped&&root.isConnected&&n===number&&location.pathname+location.search===u.pathname+u.search&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function clearRows(){while(start.nextSibling!==end)start.nextSibling.remove();}
 function cancel(){number++;request?.abort();request=null;}
 function stop(){cancel();stopped=true;observer.disconnect();life.abort();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
 function position(){return main?.scrollTop||0;}
 function savePosition(){history.replaceState({...history.state,jst:{path,context,cap,scroll:position()}},'',location.href);}
 savePosition();
 function loading(){
  root.dataset.jstLoaded='0';panel.setAttribute('aria-busy','true');clearRows();const row=document.createElement('article');row.className='jasa-stok__baris';for(const [tag,text] of [['div','Barang / sumber belum dibaca'],['span','Lokasi belum dibaca'],['div','Saldo belum dibaca']]){const cell=document.createElement(tag);cell.textContent=text;row.append(cell);}grid.insertBefore(row,end);
  links.forEach(a=>{a.removeAttribute('href');a.setAttribute('aria-disabled','true');a.setAttribute('aria-describedby','jst-baca-status');});root.querySelectorAll('[data-js-cetak]').forEach(b=>b.disabled=true);controls.hidden=false;retry.hidden=true;retry.disabled=true;status.textContent='Memeriksa akses dan membaca Stok pelanggan. Anda tetap dapat berpindah; tidak ada perubahan yang disimpan.';
 }
 function install(doc,u,restore,hadRetry){
  const frame=doc.querySelector('.bingkai'),fresh=doc.querySelector('.jasa-detail'),freshPanel=fresh?.querySelector(':scope > section.kartu'),freshGrid=freshPanel?.querySelector('.jasa-stok'),freshHead=[...freshGrid?.querySelectorAll('.jasa-stok__kepala > span')||[]],head=[...grid.querySelectorAll('.jasa-stok__kepala > span')],freshLinks=[...freshPanel?.querySelectorAll(':scope > .jasa-operasi > a[href]')||[]],freshTabs=[...fresh?.querySelectorAll('.jasa-detail-tab a')||[]],tabs=[...root.querySelectorAll('.jasa-detail-tab a')];
  const freshBack=fresh?.querySelector('.jasa-kembali[href]'),freshTitle=fresh?.querySelector('h1'),freshIdentity=fresh?.querySelector('.jasa-identitas'),nativeControls=fresh?.querySelector('[data-jasa-kontrol]');
  if(doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==u.pathname+u.search||doc.getElementById('formulir-sesi')?.dataset.token!==token||freshTabs.length!==5||fresh.querySelector('.jasa-detail-tab [aria-current=page]')?.textContent!=='Stok'||freshPanel?.querySelector('h2')?.textContent!=='Stok pelanggan'||freshHead.length!==3||freshLinks.length!==3||freshPanel.querySelector('script,form')||!freshBack||!freshTitle||!freshIdentity||!nativeControls||!window.PINDAH?.selaraskanChrome(doc))throw Error('Konteks sesi atau pelanggan berubah. Buka kembali Stok sebelum melanjutkan.');
  const focus=document.activeElement,top=root.contains(focus)?focus.getBoundingClientRect().top:null,scroll=typeof restore==='number'?restore:position();
  const back=root.querySelector('.jasa-kembali');back.href=freshBack.getAttribute('href');back.textContent=freshBack.textContent;root.querySelector('h1').textContent=freshTitle.textContent;root.querySelector('.jasa-identitas').replaceChildren(...freshIdentity.childNodes);
  tabs.forEach((a,i)=>{a.href=freshTabs[i].getAttribute('href');if(freshTabs[i].hasAttribute('aria-current'))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  links.forEach((a,i)=>{a.href=freshLinks[i].getAttribute('href');a.textContent=freshLinks[i].textContent;a.removeAttribute('aria-disabled');a.removeAttribute('aria-describedby');});head.forEach((a,i)=>a.textContent=freshHead[i].textContent);clearRows();for(const row of [...freshGrid.children].filter(n=>!n.matches('.jasa-stok__kepala')))grid.insertBefore(row.cloneNode(true),end);
  root.querySelectorAll('[data-js-cetak]').forEach(b=>{b.disabled=!nativeControls?.querySelector('[data-js-cetak]')||nativeControls.querySelector('[data-js-cetak]').disabled;b.removeAttribute('aria-describedby');});panel.removeAttribute('aria-busy');root.dataset.jstLoaded='1';controls.hidden=true;retry.hidden=true;if(main)main.scrollTop=scroll;
  if(focus?.isConnected&&focus.getClientRects().length){if(document.activeElement!==focus)focus.focus({preventScroll:true});if(main&&top!==null&&typeof restore!=='number')main.scrollTop+=focus.getBoundingClientRect().top-top;}
  if(hadRetry&&(focus===retry||focus===document.body)){const h=panel.querySelector('h2');h.tabIndex=-1;h.focus({preventScroll:true});}
 }
 async function read(u,restore){
  if(stopped||!u)return;if(request&&target?.href===u.href)return;cancel();const ctrl=new AbortController();request=ctrl;target=u;const n=++number,hadRetry=document.activeElement===retry;loading();const timer=setTimeout(()=>ctrl.abort(),20000);
  try{const r=await fetch(u.pathname+u.search,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','X-Jasa-Stok-Data':'1','Accept':'text/html'}});if(!current(n,u))return;if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)||r.redirected?'Sesi atau akses Stok belum tersedia. Kembali ke halaman yang diizinkan.':r.status===404?'Stok pelanggan tidak ditemukan pada konteks ini. Tidak ada perubahan yang disimpan.':'Stok belum dapat dibaca. Coba lagi hanya membaca tab yang sedang dibuka.');const html=await r.text();if(current(n,u))install(new DOMParser().parseFromString(html,'text/html'),u,restore,hadRetry);}
  catch(e){if(current(n,u)){panel.removeAttribute('aria-busy');status.textContent=e.name==='AbortError'?'Pembacaan Stok terlalu lama. Anda tetap dapat berpindah; Coba lagi hanya membaca.':e.message;retry.hidden=false;retry.disabled=false;}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 retry.addEventListener('click',()=>read(target||allowed(location.href)),{signal:life.signal});
 window.PINDAH.aturPembacaRiwayat((address,state)=>{if(stopped||!root.isConnected)return false;const u=allowed(location.href);if(!u||u.pathname+u.search!==address){cancel();return false;}read(u,state?.jst?.scroll);return true;});
 document.addEventListener('click',e=>{if(e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(a&&!a.target&&!a.hasAttribute('download')&&!a.getAttribute('href').startsWith('#')&&!allowed(a.href)){cancel();status.textContent='Pembacaan dihentikan. Coba lagi hanya membaca tab ini.';controls.hidden=false;retry.hidden=false;retry.disabled=false;}},{capture:true,signal:life.signal});
 window.addEventListener('beforeunload',stop,{signal:life.signal});read(allowed(location.href));
})();
