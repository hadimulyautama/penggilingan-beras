/* Satu tab baca; pengambilan/retur dan otorisasi tetap dari handler native. */
(function(){
 'use strict';
 const root=document.querySelector('[data-jgr-shell]');if(!root||root.dataset.jgrReady)return;root.dataset.jgrReady='1';
 const panel=root.querySelector('[data-jgr-panel]'),links=[...root.querySelectorAll('[data-jgr-target]')],controls=document.querySelector('[data-jgr-controls]'),status=document.getElementById('jgr-baca-status'),retry=document.querySelector('[data-jgr-retry]'),main=document.getElementById('isi-halaman');
 const path=location.pathname,cap=document.documentElement.dataset.versi,context=root.dataset.jgrContext,token=document.getElementById('formulir-sesi')?.dataset.token,keys=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status'],life=new AbortController();
 const marks=[...panel.childNodes].filter(n=>n.nodeType===8),ranges=['pengiriman','retur'].map(k=>({start:marks.find(n=>n.data.trim()===k+':mulai'),end:marks.find(n=>n.data.trim()===k+':akhir')}));if(ranges.some(r=>!r.start||!r.end))return;
 let number=0,request=null,target=null,stopped=false;
 function allowed(raw){try{const u=new URL(raw,location.href);return u.origin===location.origin&&u.pathname===path&&!u.hash&&u.href.length<4096&&u.searchParams.get('tab')==='pengambilan'&&[...u.searchParams.keys()].every(k=>keys.includes(k)&&u.searchParams.getAll(k).length===1&&u.searchParams.get(k).length<=200)?u:null;}catch(_){return null;}}
 function current(n,u){return !stopped&&root.isConnected&&n===number&&location.pathname+location.search===u.pathname+u.search&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function clearRows(){for(const r of ranges)while(r.start.nextSibling!==r.end)r.start.nextSibling.remove();}
 function cancel(){number++;request?.abort();request=null;}
 function stop(){cancel();stopped=true;observer.disconnect();life.abort();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
 function position(){return main?.scrollTop||0;}
 function savePosition(){history.replaceState({...history.state,jgr:{path,context,cap,scroll:position()}},'',location.href);}
 savePosition();
 function loading(){
  root.dataset.jgrLoaded='0';panel.setAttribute('aria-busy','true');clearRows();for(const [i,text] of ['Pengambilan dan pengiriman belum dibaca.','Retur terkait dan pengiriman asal belum dibaca.'].entries()){const p=document.createElement('p');p.className='bantu';p.textContent=text;panel.insertBefore(p,ranges[i].end);}
  links.forEach(a=>{a.removeAttribute('href');a.setAttribute('aria-disabled','true');a.setAttribute('aria-describedby','jgr-baca-status');});root.querySelectorAll('[data-js-cetak]').forEach(b=>b.disabled=true);controls.hidden=false;retry.hidden=true;retry.disabled=true;status.textContent='Memeriksa akses dan membaca Pengambilan & retur pelanggan. Anda tetap dapat berpindah; tidak ada perubahan yang disimpan.';
 }
 function install(doc,u,restore,hadRetry){
  const frame=doc.querySelector('.bingkai'),fresh=doc.querySelector('.jasa-detail'),freshPanel=fresh?.querySelector(':scope > section.kartu'),freshReturn=freshPanel?.querySelector(':scope > h3'),freshLinks=[...freshPanel?.querySelectorAll(':scope > .jasa-operasi > a[href]')||[]],freshTabs=[...fresh?.querySelectorAll('.jasa-detail-tab a')||[]],tabs=[...root.querySelectorAll('.jasa-detail-tab a')],children=[...freshPanel?.children||[]],split=children.indexOf(freshReturn);
  const freshBack=fresh?.querySelector('.jasa-kembali[href]'),freshTitle=fresh?.querySelector('h1'),freshIdentity=fresh?.querySelector('.jasa-identitas'),nativeControls=fresh?.querySelector('[data-jasa-kontrol]');
  if(doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==u.pathname+u.search||doc.getElementById('formulir-sesi')?.dataset.token!==token||freshTabs.length!==5||fresh.querySelector('.jasa-detail-tab [aria-current=page]')?.textContent!=='Pengambilan & retur'||!freshPanel?.querySelector('h2')?.textContent.startsWith('Pengambilan & pengiriman')||!freshReturn?.textContent.startsWith('Retur terkait')||freshLinks.length!==2||split<2||freshPanel.querySelector('script,form')||!freshBack||!freshTitle||!freshIdentity||!nativeControls||!window.PINDAH?.selaraskanChrome(doc))throw Error('Konteks sesi atau pelanggan berubah. Buka kembali Pengambilan & retur sebelum melanjutkan.');
  const focus=document.activeElement,top=root.contains(focus)?focus.getBoundingClientRect().top:null,scroll=typeof restore==='number'?restore:position();
  const back=root.querySelector('.jasa-kembali');back.href=freshBack.getAttribute('href');back.textContent=freshBack.textContent;root.querySelector('h1').textContent=freshTitle.textContent;root.querySelector('.jasa-identitas').replaceChildren(...freshIdentity.childNodes);
  tabs.forEach((a,i)=>{a.href=freshTabs[i].getAttribute('href');if(freshTabs[i].hasAttribute('aria-current'))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  links.forEach((a,i)=>{a.href=freshLinks[i].getAttribute('href');a.textContent=freshLinks[i].textContent;a.removeAttribute('aria-disabled');a.removeAttribute('aria-describedby');});panel.querySelector('h2').textContent=freshPanel.querySelector('h2').textContent;panel.querySelector('h3').textContent=freshReturn.textContent;clearRows();for(const [i,rows] of [children.slice(2,split),children.slice(split+1)].entries())for(const row of rows)panel.insertBefore(row.cloneNode(true),ranges[i].end);
  root.querySelectorAll('[data-js-cetak]').forEach(b=>{b.disabled=!nativeControls?.querySelector('[data-js-cetak]')||nativeControls.querySelector('[data-js-cetak]').disabled;b.removeAttribute('aria-describedby');});panel.removeAttribute('aria-busy');root.dataset.jgrLoaded='1';controls.hidden=true;retry.hidden=true;if(main)main.scrollTop=scroll;
  if(focus?.isConnected&&focus.getClientRects().length){if(document.activeElement!==focus)focus.focus({preventScroll:true});if(main&&top!==null&&typeof restore!=='number')main.scrollTop+=focus.getBoundingClientRect().top-top;}
  if(hadRetry&&(focus===retry||focus===document.body)){const h=panel.querySelector('h2');h.tabIndex=-1;h.focus({preventScroll:true});}
 }
 async function read(u,restore){
  if(stopped||!u)return;if(request&&target?.href===u.href)return;cancel();const ctrl=new AbortController();request=ctrl;target=u;const n=++number,hadRetry=document.activeElement===retry;loading();const timer=setTimeout(()=>ctrl.abort(),20000);
  try{const r=await fetch(u.pathname+u.search,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','X-Jasa-Pengambilan-Data':'1','Accept':'text/html'}});if(!current(n,u))return;if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)||r.redirected?'Sesi atau akses Pengambilan & retur belum tersedia. Kembali ke halaman yang diizinkan.':r.status===404?'Pengambilan & retur pelanggan tidak ditemukan pada konteks ini. Tidak ada perubahan yang disimpan.':'Pengambilan & retur belum dapat dibaca. Coba lagi hanya membaca tab yang sedang dibuka.');const html=await r.text();if(current(n,u))install(new DOMParser().parseFromString(html,'text/html'),u,restore,hadRetry);}
  catch(e){if(current(n,u)){panel.removeAttribute('aria-busy');status.textContent=e.name==='AbortError'?'Pembacaan Pengambilan & retur terlalu lama. Anda tetap dapat berpindah; Coba lagi hanya membaca.':e.message;retry.hidden=false;retry.disabled=false;}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 retry.addEventListener('click',()=>read(target||allowed(location.href)),{signal:life.signal});
 window.PINDAH.aturPembacaRiwayat((address,state)=>{if(stopped||!root.isConnected)return false;const u=allowed(location.href);if(!u||u.pathname+u.search!==address){cancel();return false;}read(u,state?.jgr?.scroll);return true;});
 document.addEventListener('click',e=>{if(e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(a&&!a.target&&!a.hasAttribute('download')&&!a.getAttribute('href').startsWith('#')&&!allowed(a.href)){cancel();status.textContent='Pembacaan dihentikan. Coba lagi hanya membaca tab ini.';controls.hidden=false;retry.hidden=false;retry.disabled=false;}},{capture:true,signal:life.signal});
 window.addEventListener('beforeunload',stop,{signal:life.signal});read(allowed(location.href));
})();
