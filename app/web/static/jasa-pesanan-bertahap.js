/* Pembaca panel Ringkasan: GET native, tidak membuat/mengubah pesanan. */
(function(){
 'use strict';
 const root=document.querySelector('.jasa-detail'),panel=root?.querySelector('#pesanan-pelanggan'),form=panel?.querySelector('.jasa-pesanan-filter');
 if(!root||!panel||!form||panel.dataset.jpReady||!window.PINDAH)return;panel.dataset.jpReady='1';
 const path=location.pathname,cap=document.documentElement.dataset.versi,context=document.querySelector('.bingkai')?.dataset.pindahKonteks,token=document.getElementById('formulir-sesi')?.dataset.token;
 const keys=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status'],life=new AbortController(),main=document.querySelector('[data-isi-halaman]')||document.querySelector('main.isi')||panel.closest('main');
 let sequence=0,request=null,target=null,stopped=false;
 function allowed(raw){try{const u=new URL(raw,location.href);return u.origin===location.origin&&u.pathname===path&&/^\/jasa\/pelanggan\/[1-9]\d{0,9}$/.test(u.pathname)&&Number(u.pathname.split('/').pop())<=2147483647&&u.href.length<4096&&['','#pesanan-pelanggan'].includes(u.hash)&&(u.searchParams.get('tab')||'ringkasan')==='ringkasan'&&[...u.searchParams.keys()].every(k=>keys.includes(k)&&u.searchParams.getAll(k).length===1&&u.searchParams.get(k).length<=200)?u:null;}catch(_){return null;}}
 if(!allowed(location.href))return;
 const results=document.createElement('div');results.dataset.jpResults='1';
 const pager=panel.querySelector('.jasa-pesanan-paginasi')||document.createElement('nav');pager.className='jasa-pesanan-paginasi';pager.setAttribute('aria-label','Halaman pesanan');pager.dataset.jpHidden='1';
 const previous=pager.querySelector('a:first-child')?.textContent.includes('Sebelumnya')?pager.querySelector('a:first-child'):document.createElement('a'),next=[...pager.querySelectorAll('a')].find(a=>a.textContent.includes('Berikutnya'))||document.createElement('a'),pageLabel=pager.querySelector('span')||document.createElement('span');
 previous.className=next.className='btn btn--kecil';previous.textContent='← Sebelumnya';next.textContent='Berikutnya →';previous.dataset.jpHidden=next.dataset.jpHidden='1';
 const status=document.createElement('p');status.className='bantu';status.role='status';status.dataset.jpStatus='1';status.dataset.jpHidden='1';status.hidden=true;
 const retry=document.createElement('button');retry.type='button';retry.className='btn btn--kecil';retry.textContent='Coba lagi';retry.dataset.jpRetry='1';retry.dataset.jpHidden='1';retry.hidden=true;
 const initialPager=pager.cloneNode(true);
 function pagerFrom(source){for(const [node,label] of [[previous,'Sebelumnya'],[next,'Berikutnya']]){const fresh=source&&[...source.querySelectorAll('a')].find(a=>a.textContent.includes(label));node.hidden=!fresh;if(fresh){node.href=fresh.getAttribute('href');node.setAttribute('data-utuh','');node.removeAttribute('aria-disabled');}else{node.removeAttribute('href');node.setAttribute('aria-disabled','true');}}pageLabel.textContent=source?.querySelector('span')?.textContent||'';pager.hidden=!source;pager.replaceChildren(previous,pageLabel,next);}
 function dataChildren(source){const children=[...source.children],f=source.querySelector('.jasa-pesanan-filter'),start=f?children.indexOf(f)+1:2;return children.slice(start).filter(n=>!n.matches('.jasa-pesanan-paginasi,[data-jp-status],[data-jp-retry],[data-jp-results]'));}
 const initial=dataChildren(panel);results.append(...initial);panel.append(results,pager,status,retry);pagerFrom(initialPager.isConnected||initialPager.querySelector('span')?initialPager:null);
 function cancel(){sequence++;request?.abort();request=null;}
 function stop(){cancel();stopped=true;}
 function valid(n,u){return !stopped&&root.isConnected&&n===sequence&&location.pathname===path&&location.pathname+location.search===u.pathname+u.search&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function scrollState(){return main?.scrollTop||0;}
 function savePosition(){history.replaceState({...history.state,jp:{path,context,cap,scroll:scrollState()}},'',location.href);}
 savePosition();
 function shell(u){panel.setAttribute('aria-busy','true');retry.hidden=true;status.hidden=false;status.textContent='Memuat pesanan untuk halaman dan filter ini. Anda tetap dapat berpindah halaman.';results.replaceChildren();for(let i=0;i<3;i++){const card=document.createElement('div');card.className='jasa-catatan';const label=document.createElement('strong');label.textContent='Pesanan';const text=document.createElement('p');text.className='bantu';text.textContent='Nomor, status, dan rekap barang belum dibaca.';card.append(label,text);results.append(card);}pageLabel.textContent='Halaman '+(u.searchParams.get('pesanan_halaman')||'1')+' · Memuat pesanan…';}
 function apply(doc,values,hadFocus,restore){
  const freshRoot=doc.querySelector('.jasa-detail'),fresh=freshRoot?.querySelector('#pesanan-pelanggan'),frame=doc.querySelector('.bingkai'),freshForm=fresh?.querySelector('.jasa-pesanan-filter');
  if(!freshRoot||!fresh||!freshForm||doc.documentElement.dataset.versi!==cap||frame?.dataset.pindahKonteks!==context||frame.dataset.pindahAlamat!==target.pathname+target.search||doc.getElementById('formulir-sesi')?.dataset.token!==token||freshRoot.querySelector('.jasa-detail-tab [aria-current=page]')?.textContent!=='Ringkasan'||!window.PINDAH.selaraskanChrome(doc))throw Error('Konteks sesi atau pelanggan berubah. Buka kembali Ringkasan sebelum melanjutkan.');
  const focus=document.activeElement,scroll=typeof restore==='number'?restore:scrollState();
  panel.querySelector('h2').textContent=fresh.querySelector('h2').textContent;panel.dataset.pesananBanyak=fresh.dataset.pesananBanyak;
  for(const field of form.elements){const f=freshForm.elements.namedItem(field.name);if(f&&field.value===values.get(field))field.value=f.value;}
  results.replaceChildren(...dataChildren(fresh).map(n=>n.cloneNode(true)));pagerFrom(fresh.querySelector('.jasa-pesanan-paginasi'));
  // Baca ulang juga angka/tautan ringkasan native; kontrol dialog, tab,
  // filter, pager dan panel yang sedang dipegang tetap berupa node yang sama.
  const stable=['.jasa-kembali','[data-jasa-kontrol]','.jasa-detail-tab','#pesanan-pelanggan','.jasa-terkait'];
  const existing=new Map(stable.map(s=>[s,root.querySelector(s)]));
  const freshChildren=[...freshRoot.childNodes];for(const child of [...root.childNodes])if(![...existing.values()].includes(child))child.remove();
  for(const child of freshChildren){const selector=child.nodeType===1?stable.find(s=>child.matches(s)):null,old=selector&&existing.get(selector);if(!old){root.append(child.cloneNode(true));continue;}
   if(selector==='.jasa-kembali'){old.href=child.getAttribute('href');old.textContent=child.textContent;}
   if(selector==='.jasa-detail-tab')for(const [i,a] of [...old.querySelectorAll('a')].entries()){const b=child.querySelectorAll('a')[i];if(b)a.href=b.getAttribute('href');}
   if(selector==='[data-jasa-kontrol]'){const a=old.querySelector('h1'),b=child.querySelector('h1');if(a&&b)a.textContent=b.textContent;}
   if(selector==='.jasa-terkait'){const summary=old.querySelector('summary'),open=old.open,links=new Map([...old.querySelectorAll('a[href]')].map(a=>[a.textContent,a]));for(const freshLink of child.querySelectorAll('a[href]')){const oldLink=links.get(freshLink.textContent);if(oldLink){oldLink.href=freshLink.getAttribute('href');freshLink.replaceWith(oldLink);}}for(const x of [...old.childNodes])if(x!==summary)x.remove();old.append(...[...child.childNodes].filter(n=>n.nodeType!==1||n.tagName!=='SUMMARY'));old.open=open;}
   root.append(old);
  }
  panel.removeAttribute('aria-busy');status.hidden=true;retry.hidden=true;
  if(main)main.scrollTop=scroll;
  if(focus?.isConnected){if(document.activeElement!==focus)focus.focus({preventScroll:true});}
  else if(hadFocus){const h=panel.querySelector('h2');h.tabIndex=-1;h.focus({preventScroll:true});}
 }
 async function read(u,push,restore){
  if(stopped||!allowed(u.href))return;if(target?.href===u.href&&request)return;
  if(push){savePosition();history.pushState({pindah:1,jp:{path,context,cap,scroll:null}},'',u.href);}
  request?.abort();const ctrl=new AbortController();request=ctrl;target=u;const n=++sequence,values=new Map([...form.elements].map(x=>[x,x.value])),hadFocus=panel.contains(document.activeElement);shell(u);
  if(typeof restore==='number'&&main)main.scrollTop=restore;else if(push)panel.scrollIntoView({block:'start'});
  const timer=setTimeout(()=>ctrl.abort(),20000);
  try{const r=await fetch(u.pathname+u.search,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!valid(n,u))return;if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)?'Akses Ringkasan belum tersedia untuk sesi ini. Kembali ke halaman yang diizinkan.':'Pesanan belum dapat dibaca. Coba lagi hanya membaca halaman yang sedang dipilih.');const html=await r.text();if(!valid(n,u))return;if(document.querySelector('dialog[open]'))throw Error('Tutup dialog terlebih dahulu, lalu Coba lagi untuk membaca pesanan.');apply(new DOMParser().parseFromString(html,'text/html'),values,hadFocus,restore);}
  catch(e){if(valid(n,u)){panel.removeAttribute('aria-busy');status.hidden=false;status.textContent=e.name==='AbortError'?'Pembacaan pesanan terlalu lama. Coba lagi hanya membaca; Anda tetap dapat berpindah.':e.message;retry.hidden=false;}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}
 }
 panel.addEventListener('click',e=>{if(e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||document.querySelector('dialog[open]'))return;const a=e.target.closest('a[href]');if(!a||a.target||a.hasAttribute('download'))return;const u=allowed(a.href);if(!u||!(a.closest('.jasa-pesanan-paginasi')||a.classList.contains('jasa-tautan')))return;e.preventDefault();e.stopPropagation();read(u,true);},{signal:life.signal});
 form.addEventListener('submit',e=>{if(document.querySelector('dialog[open]'))return;const u=new URL(form.action,location.href);u.search=new URLSearchParams(new FormData(form));const safe=allowed(u.href);if(!safe)return;e.preventDefault();e.stopPropagation();read(safe,true);},{signal:life.signal});
 retry.addEventListener('click',()=>{if(target)read(target,false);},{signal:life.signal});
 window.addEventListener('popstate',e=>{if(stopped||!root.isConnected||document.querySelector('dialog[open]'))return;const u=allowed(location.href);if(!u){cancel();return;}e.stopImmediatePropagation();read(u,false,history.state?.jp?.scroll);},{capture:true,signal:life.signal});
 document.addEventListener('click',e=>{if(e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||document.querySelector('dialog[open]'))return;const a=e.target.closest('a[href]');if(a&&!a.target&&!a.hasAttribute('download')&&!a.getAttribute('href').startsWith('#')&&!allowed(a.href))cancel();},{capture:true,signal:life.signal});
 window.addEventListener('beforeunload',stop,{signal:life.signal});const observer=new MutationObserver(()=>{if(!root.isConnected){stop();observer.disconnect();life.abort();}});observer.observe(document.body,{childList:true,subtree:true});
})();
