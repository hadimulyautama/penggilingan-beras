/* Baca rincian perintah eksplisit. Editor dan transaksi tetap engine native. */
(function(){
 'use strict';
 function mulai(){
 const root=document.querySelector('[data-pengiriman-detail-shell]');if(!root||root.dataset.pkdReady)return;root.dataset.pkdReady='1';
 const frame=document.querySelector('.bingkai'),cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token,context=root.dataset.pkdContext,actor=root.dataset.pkdActor,id=root.dataset.pkdTarget;
 const tabs=[...root.querySelectorAll('.detail-kirim-tabs [role=tab]')],panels=tabs.map(a=>root.querySelector('#'+a.getAttribute('aria-controls'))),status=root.querySelector('#pkd-status'),retry=root.querySelector('[data-pkd-retry]'),startTabs=root.pkdTabs,startVerification=root.pkdVerification;
 const key=raw=>{const u=new URL(raw,location.href);u.hash='';u.searchParams.delete('tab_detail');return u.pathname+u.search;},address=location.pathname+location.search,readKey=key(location.href);
 let sequence=0,request=null,done=false,abandoned=false,started=false;const events=new AbortController();
 function current(n){return !done&&!abandoned&&root.isConnected&&n===sequence&&key(location.href)===readKey&&document.documentElement.dataset.versi===cap&&frame?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function stop(){if(done)return;abandoned=true;++sequence;request?.abort();retry.hidden=true;observer.disconnect();events.abort();}
 const observer=new MutationObserver(()=>{if(!root.isConnected)stop();});observer.observe(document.body,{childList:true,subtree:true});
 function selected(){const u=new URL(location.href),hash=u.hash.slice(1);return tabs.some(a=>a.getAttribute('aria-controls')===hash)?hash:'panel-'+(['ringkasan','barang','tiket','riwayat'].includes(u.searchParams.get('tab_detail'))?u.searchParams.get('tab_detail'):'ringkasan');}
 function show(){const active=selected();tabs.forEach((a,i)=>{a.setAttribute('aria-selected',String(panels[i].id===active));panels[i].hidden=panels[i].id!==active;});}
 root.addEventListener('click',e=>{const a=e.target.closest('.detail-kirim-tabs a');if(!a||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();e.stopPropagation();const u=new URL(a.href);history.replaceState(history.state,'',u.pathname+u.search+u.hash);show();},{signal:events.signal});
 root.querySelector('.detail-kirim-tabs').addEventListener('keydown',e=>{const i=tabs.indexOf(e.target);if(i<0||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].click();tabs[n].focus();},{signal:events.signal});
 document.addEventListener('click',e=>{if(e.defaultPrevented||e.button||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const a=e.target.closest('a[href]');if(a&&!a.target&&!a.hasAttribute('download')&&key(a.href)!==readKey)stop();},{capture:true,signal:events.signal});
 window.addEventListener('popstate',()=>{if(key(location.href)!==readKey)stop();else show();},{signal:events.signal});
 function attributes(old,fresh){for(const a of [...old.attributes])old.removeAttribute(a.name);for(const a of fresh.attributes)old.setAttribute(a.name,a.value);}
 function install(doc,retryFocus){
  const next=doc.querySelector('[data-pengiriman-native]'),nextFrame=doc.querySelector('.bingkai'),freshTabs=[...next?.querySelectorAll('.detail-kirim-tabs [role=tab]')||[]];
  if(!next||next.dataset.pkdRecord!==id||next.dataset.pkdActor!==actor||doc.documentElement.dataset.versi!==cap||nextFrame?.dataset.pindahKonteks!==context||key(nextFrame.dataset.pindahAlamat)!==readKey||doc.getElementById('formulir-sesi')?.dataset.token!==token||freshTabs.length!==4||freshTabs.some((a,i)=>a.id!==tabs[i].id)||typeof startTabs!=='function'||typeof startVerification!=='function')throw Error('Konteks rincian atau struktur berubah. Buka ulang rincian perintah.');
  const freshPanels=panels.map(p=>next.querySelector('#'+p.id)),header=root.querySelector('header.kirim-detail__kepala'),freshHeader=next.querySelector('header.kirim-detail__kepala'),freshNav=next.querySelector('.kontrol-tab'),nav=root.querySelector('.kontrol-tab'),freshBack=next.querySelector('.detail-kirim-kembali');
  if(freshPanels.some(p=>!p)||!freshHeader||!freshNav||!freshBack||next.querySelectorAll('[data-verifikasi-pengiriman]').length>1)throw Error('Rincian belum lengkap. Coba lagi hanya membaca.');
  const verification=next.querySelector('[data-verifikasi-pengiriman]'),json=next.querySelector('#verifikasi-awal');
  for(const script of next.querySelectorAll('script')){
   if(script===json&&script.type==='application/json')continue;
   const src=script.getAttribute('src');if(!src||new URL(src,location.href).origin!==location.origin||new URL(src,location.href).pathname!=='/static/verifikasi-pengiriman.js'||!script.hasAttribute('defer'))throw Error('Controller rincian berubah. Gunakan halaman native.');script.remove();
  }
  if(verification&&(!verification.hasAttribute('data-inline')||!json||!Array.isArray(JSON.parse(json.textContent))||document.getElementById('verifikasi-awal')))throw Error('Pemeriksaan verifikasi belum lengkap.');
  const action=doc.querySelector('script[data-perintah-detail]');if(action&&(action.dataset.perintahDetail!==id||action.dataset.buka||action.dataset.nilai||action.dataset.tiket))throw Error('Tujuan memerlukan formulir native tersendiri.');
  const table=root.querySelector('#panel-barang table'),newTable=next.querySelector('#panel-barang table'),heads=[...table.querySelectorAll('thead th')],newHeads=[...newTable?.querySelectorAll('thead th')||[]];if(newHeads.length!==4||heads.length!==4)throw Error('Kolom rincian berubah. Buka ulang halaman native.');
  const focus=document.activeElement,active=selected(),title=header.querySelector('h1');nextFrame.dataset.pindahAlamat=location.pathname+location.search;if(window.PINDAH&&!PINDAH.selaraskanChrome(doc))throw Error('Sesi atau cakupan navigasi berubah.');
  title.textContent=freshHeader.querySelector('h1').textContent;freshHeader.querySelector('h1').replaceWith(title);header.replaceChildren(...freshHeader.childNodes);
  const top=root.querySelector('[data-pkd-top]');for(let node=freshHeader.nextSibling;node&&node!==next.querySelector('.detail-kirim-tabs');){const after=node.nextSibling;top.before(node);node=after;}top.remove();
  const oldMain=nav.querySelector('a[href="/barang-keluar"]'),newMain=freshNav.querySelector('a[href="/barang-keluar"]');if(oldMain&&newMain){attributes(oldMain,newMain);oldMain.replaceChildren(...newMain.childNodes);newMain.replaceWith(oldMain);}nav.replaceChildren(...freshNav.childNodes);
  const back=root.querySelector('[data-pkd-back]');back.href=freshBack.getAttribute('href');back.textContent=freshBack.textContent;
  heads.forEach((h,i)=>{attributes(h,newHeads[i]);h.replaceChildren(...newHeads[i].childNodes);newHeads[i].replaceWith(h);});table.replaceChildren(...newTable.childNodes);newTable.replaceWith(table);
  tabs.forEach((a,i)=>{attributes(a,freshTabs[i]);a.replaceChildren(...freshTabs[i].childNodes);const u=new URL(location.href);u.searchParams.set('tab_detail',a.id.slice(4));u.hash=a.getAttribute('aria-controls');a.href=u.pathname+u.search+u.hash;a.setAttribute('aria-selected',String(panels[i].id===active));});
  panels.forEach((p,i)=>{p.replaceChildren(...freshPanels[i].childNodes);p.hidden=p.id!==active;});
  const tail=document.querySelector('[data-pkd-tail]');const edit=doc.querySelector('[data-pengiriman-perbaikan]');if(edit)tail.append(edit);
  for(const selector of ['dialog#lembar','div#kabar']){const actual=doc.querySelector(selector);if(actual&&!document.querySelector(selector)){if(actual.children.length||actual.textContent.trim())throw Error('Formulir native belum netral. Buka ulang halaman asli.');tail.append(actual);}}
  started=true;startTabs();if(verification){startVerification();if(root.querySelector('[data-verifikasi-pengiriman]')?.dataset.siap!=='1')throw Error('Verifikasi native belum siap.');}
  root.querySelector('[data-pkd-state]').remove();root.removeAttribute('data-pengiriman-detail-shell');root.setAttribute('data-pengiriman-native','');root.dataset.pkdRecord=id;root.dataset.pkdLoaded='1';done=true;observer.disconnect();events.abort();
  if(retryFocus&&focus===document.body){title.tabIndex=-1;title.focus({preventScroll:true});}else if(focus?.isConnected&&document.activeElement!==focus)focus.focus({preventScroll:true});
 }
 async function read(){if(done||abandoned||started)return;request?.abort();const ctrl=new AbortController();request=ctrl;const n=++sequence,retryFocus=document.activeElement===retry,timer=setTimeout(()=>ctrl.abort(),20000);retry.disabled=true;retry.textContent='Membaca…';status.textContent='Membaca rincian perintah. Belum ada tindakan yang dapat disimpan.';
  try{const response=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});if(!current(n))return;if(response.redirected||!response.ok)throw Error([401,403].includes(response.status)?'Akses atau sesi berubah. Kembali ke halaman yang diizinkan. Tidak ada catatan yang disimpan.':response.status===404?'Perintah tidak ditemukan pada cakupan ini. Tidak ada perubahan yang disimpan.':'Rincian belum dapat dibaca. Coba lagi hanya membaca.');const html=await response.text();if(current(n))install(new DOMParser().parseFromString(html,'text/html'),retryFocus);
  }catch(e){if(current(n)){status.textContent=e.name==='AbortError'?'Pembacaan terlalu lama. Anda dapat kembali atau mencoba membaca lagi.':e.message;retry.hidden=started;retry.disabled=false;retry.textContent='Coba lagi';if(started){for(const field of root.querySelectorAll('input,textarea,select,button'))field.disabled=true;root.querySelector('[data-pkd-native]').hidden=false;}}}
  finally{clearTimeout(timer);if(request===ctrl)request=null;}}
 retry.addEventListener('click',read,{signal:events.signal});show();read();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mulai,{once:true});else mulai();
})();
