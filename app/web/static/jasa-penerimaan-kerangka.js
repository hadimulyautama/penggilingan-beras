/* Satu tab baca; aturan penerimaan dan hak tetap milik handler native. */
(function(){
 'use strict';
 const root=document.querySelector('[data-jpr-shell]');if(!root||root.dataset.jprReady)return;root.dataset.jprReady='1';
 const form=root.querySelector(':scope > form.saring'),field=form.elements.rincian_cari,panel=root.querySelector('[data-jpr-panel]'),pager=document.querySelector('[data-jpr-pager]'),controls=document.querySelector('[data-jpr-controls]'),status=document.getElementById('jpr-baca-status'),retry=document.querySelector('[data-jpr-retry]'),main=document.getElementById('isi-halaman');
 const path=location.pathname,cap=document.documentElement.dataset.versi,context=root.dataset.jprContext,token=document.getElementById('formulir-sesi')?.dataset.token;
 const keys=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status','rincian_halaman','rincian_cari'],life=new AbortController();
 const marks=[...panel.childNodes].filter(n=>n.nodeType===8),start=marks.find(n=>n.data.trim()==='penerimaan:mulai'),end=marks.find(n=>n.data.trim()==='penerimaan:akhir');if(!start||!end)return;
 let number=0,request=null,target=null,stopped=false;
 function allowed(raw){try{const u=new URL(raw,location.href);return u.origin===location.origin&&u.pathname===path&&!u.hash&&u.href.length<4096&&u.searchParams.get('tab')==='penerimaan'&&[...u.searchParams.keys()].every(k=>keys.includes(k)&&u.searchParams.getAll(k).length===1&&u.searchParams.get(k).length<=200)?u:null;}catch(_){return null;}}
 function current(n,u){return !stopped&&root.isConnected&&n===number&&location.pathname+location.search===u.pathname+u.search&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function clearRows(){while(start.nextSibling!==end)start.nextSibling.remove();}
 function cancel(){number++;request?.abort();request=null;}
 function stop(){cancel();stopped=true;observer.disconnect();life.abort();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
 function position(){return main?.scrollTop||0;}
 function savePosition(){history.replaceState({...history.state,jpr:{path,context,cap,scroll:position()}},'',location.href);}
 savePosition();
 function loading(){
  root.dataset.jprLoaded='0';panel.setAttribute('aria-busy','true');clearRows();const row=document.createElement('article');row.className='jasa-catatan';const title=document.createElement('strong');title.textContent='Penerimaan';const text=document.createElement('p');text.className='bantu';text.textContent='Nomor, status, jenis, pesanan dan bobot belum dibaca.';row.append(title,text);panel.insertBefore(row,end);
  const open=root.querySelector('[data-jpr-open]');open.removeAttribute('href');open.setAttribute('aria-disabled','true');open.setAttribute('aria-describedby','jpr-baca-status');root.querySelectorAll('[data-js-cetak]').forEach(b=>b.disabled=true);
  pager.hidden=false;pager.querySelector('span').textContent='Halaman catatan belum dibaca.';pager.querySelectorAll('a').forEach(a=>{a.hidden=false;a.removeAttribute('href');a.setAttribute('aria-disabled','true');});controls.hidden=false;retry.hidden=true;retry.disabled=true;status.textContent='Memeriksa akses dan membaca Penerimaan pelanggan. Anda tetap dapat berpindah; tidak ada perubahan yang disimpan.';
 }
 function install(doc,u,restore,hadRetry){
  const frame=doc.querySelector('.bingkai'),fresh=doc.querySelector('.jasa-detail'),freshForm=fresh?.querySelector(':scope > form.saring'),freshPanel=fresh?.querySelector(':scope > section.kartu'),freshTabs=[...fresh?.querySelectorAll('.jasa-detail-tab a')||[]],tabs=[...root.querySelectorAll('.jasa-detail-tab a')];
  const freshBack=fresh?.querySelector('.jasa-kembali[href]'),freshTitle=fresh?.querySelector('h1'),freshIdentity=fresh?.querySelector('.jasa-identitas'),nativeControls=fresh?.querySelector('[data-jasa-kontrol]');
  if(doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==u.pathname+u.search||doc.getElementById('formulir-sesi')?.dataset.token!==token||freshTabs.length!==5||fresh.querySelector('.jasa-detail-tab [aria-current=page]')?.textContent!=='Penerimaan'||!freshForm?.elements.rincian_cari||!freshPanel?.querySelector('h2')||!freshPanel.querySelector(':scope > a[href]')||freshPanel.querySelector('script,form[method=post]')||!freshBack||!freshTitle||!freshIdentity||!nativeControls||!window.PINDAH?.selaraskanChrome(doc))throw Error('Konteks sesi atau pelanggan berubah. Buka kembali Penerimaan sebelum melanjutkan.');
  const focus=document.activeElement,top=root.contains(focus)?focus.getBoundingClientRect().top:null,scroll=typeof restore==='number'?restore:position();
  const back=root.querySelector('.jasa-kembali');back.href=freshBack.getAttribute('href');back.textContent=freshBack.textContent;
  root.querySelector('h1').textContent=freshTitle.textContent;root.querySelector('.jasa-identitas').replaceChildren(...freshIdentity.childNodes);
  tabs.forEach((a,i)=>{a.href=freshTabs[i].getAttribute('href');if(freshTabs[i].hasAttribute('aria-current'))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  if(field.value===(u.searchParams.get('rincian_cari')||''))field.value=freshForm.elements.rincian_cari.value;
  if(freshForm.hasAttribute('action'))form.setAttribute('action',freshForm.getAttribute('action'));else form.removeAttribute('action');
  panel.querySelector('h2').textContent=freshPanel.querySelector('h2').textContent;const open=root.querySelector('[data-jpr-open]'),nextOpen=freshPanel.querySelector(':scope > a[href]');open.href=nextOpen.getAttribute('href');open.textContent=nextOpen.textContent;open.removeAttribute('aria-disabled');open.removeAttribute('aria-describedby');clearRows();
  const rows=[...freshPanel.children].slice(2),filteredEmpty=!!freshForm.elements.rincian_cari.value&&!freshPanel.querySelector('article.jasa-catatan');
  for(const row of rows){const copy=row.cloneNode(true);if(filteredEmpty&&copy.matches('p.bantu'))copy.textContent='Tidak ada penerimaan yang cocok dengan pencarian ini. Ubah atau kosongkan pencarian untuk membaca catatan lain.';panel.insertBefore(copy,end);}
  const nextPager=doc.querySelector('nav[aria-label="Halaman catatan pelanggan"]');pager.hidden=!nextPager;pager.querySelector('span').textContent=nextPager?.querySelector('span')?.textContent||'';
  for(const [node,label] of [[pager.querySelector('[data-jpr-prev]'),'Sebelumnya'],[pager.querySelector('[data-jpr-next]'),'Berikutnya']]){const next=nextPager&&[...nextPager.querySelectorAll('a')].find(a=>a.textContent.includes(label));node.hidden=!next;if(next){node.href=next.getAttribute('href');node.removeAttribute('aria-disabled');}else{node.removeAttribute('href');node.setAttribute('aria-disabled','true');}}
  root.querySelectorAll('[data-js-cetak]').forEach(b=>{b.disabled=!nativeControls?.querySelector('[data-js-cetak]')||nativeControls.querySelector('[data-js-cetak]').disabled;b.removeAttribute('aria-describedby');});
  panel.removeAttribute('aria-busy');root.dataset.jprLoaded='1';controls.hidden=true;retry.hidden=true;if(main)main.scrollTop=scroll;
  if(focus?.isConnected&&focus.getClientRects().length){if(document.activeElement!==focus)focus.focus({preventScroll:true});if(main&&top!==null&&typeof restore!=='number')main.scrollTop+=focus.getBoundingClientRect().top-top;}
  if(hadRetry&&focus===retry){const h=panel.querySelector('h2');h.tabIndex=-1;h.focus({preventScroll:true});}
 }
 async function read(u,push=false,restore){
  if(stopped||!u)return;if(request&&target?.href===u.href)return;
  if(push){savePosition();if(location.pathname+location.search!==u.pathname+u.search)history.pushState({pindah:1,jpr:{path,context,cap,scroll:null}},'',u.href);}
  if(!push&&target&&target.pathname+target.search!==u.pathname+u.search)field.value=u.searchParams.get('rincian_cari')||'';
  cancel();const ctrl=new AbortController();request=ctrl;target=u;const n=++number,hadRetry=document.activeElement===retry;loading();const timer=setTimeout(()=>ctrl.abort(),20000);
  try{const r=await fetch(u.pathname+u.search,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','X-Jasa-Penerimaan-Data':'1','Accept':'text/html'}});if(!current(n,u))return;if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)||r.redirected?'Sesi atau akses Penerimaan belum tersedia. Kembali ke halaman yang diizinkan.':r.status===404?'Penerimaan pelanggan tidak ditemukan pada konteks ini. Tidak ada perubahan yang disimpan.':'Penerimaan belum dapat dibaca. Coba lagi hanya membaca tab yang sedang dibuka.');const html=await r.text();if(current(n,u))install(new DOMParser().parseFromString(html,'text/html'),u,restore,hadRetry);}
  catch(e){if(current(n,u)){panel.removeAttribute('aria-busy');status.textContent=e.name==='AbortError'?'Pembacaan Penerimaan terlalu lama. Anda tetap dapat berpindah; Coba lagi hanya membaca.':e.message;retry.hidden=false;retry.disabled=false;}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 form.addEventListener('submit',e=>{const u=new URL(form.action,location.href);u.search=new URLSearchParams(new FormData(form));const safe=allowed(u.href);if(!safe)return;e.preventDefault();e.stopPropagation();read(safe,true);},{signal:life.signal});
 pager.addEventListener('click',e=>{if(e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]'),u=a&&allowed(a.href);if(!u||a.target||a.hasAttribute('download'))return;e.preventDefault();e.stopPropagation();read(u,true);},{signal:life.signal});
 retry.addEventListener('click',()=>read(target||allowed(location.href)),{signal:life.signal});
 window.PINDAH.aturPembacaRiwayat((address,state)=>{if(stopped||!root.isConnected)return false;const u=allowed(location.href);if(!u||u.pathname+u.search!==address){cancel();return false;}read(u,false,state?.jpr?.scroll);return true;});
 document.addEventListener('click',e=>{if(e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(a&&!a.target&&!a.hasAttribute('download')&&!a.getAttribute('href').startsWith('#')&&!allowed(a.href)){cancel();status.textContent='Pembacaan dihentikan. Coba lagi hanya membaca tab ini.';controls.hidden=false;retry.hidden=false;retry.disabled=false;}},{capture:true,signal:life.signal});
 window.addEventListener('beforeunload',stop,{signal:life.signal});read(allowed(location.href));
})();
