/* Satu katalog hidup pada satu konteks; yang dibaca tidak pernah menyimpan. */
(function(){
 'use strict';
 const root=document.querySelector('[data-pekerjaan-lain]');if(!root||root.padiKatalog)return;
 const address=location.pathname+location.search,cap=document.documentElement.dataset.versi,context=root.dataset.plContext,
  token=document.getElementById('formulir-sesi')?.dataset.token,status=root.querySelector('[data-pl-status]'),retry=root.querySelector('[data-pl-retry]');
 let number=0,menuRequest=null,countRequest=null;
 function valid(){return root.isConnected&&location.pathname+location.search===address&&document.documentElement.dataset.versi===cap&&document.querySelector('.bingkai')?.dataset.pindahKonteks===context&&document.getElementById('formulir-sesi')?.dataset.token===token&&(!window.SESIFORM||SESIFORM.periksa());}
 function pesan(text){status.hidden=false;status.querySelector('p').textContent=text;retry.hidden=false;}
 function nonaktifkan(){for(const b of root.querySelectorAll('[data-pl-aksi]')){b.disabled=true;b.setAttribute('aria-describedby','pl-alasan');}}
 const observer=new MutationObserver(()=>{if(!root.isConnected){number++;menuRequest?.abort();countRequest?.abort();observer.disconnect();}});
 observer.observe(document.body,{childList:true,subtree:true});
 async function hitungan(){
  if(!root.hasAttribute('data-pl-shell'))return;
  countRequest?.abort();const ctrl=new AbortController();countRequest=ctrl;const timer=setTimeout(()=>ctrl.abort(),20000);
  try{
   const r=await fetch(address,{credentials:'same-origin',cache:'no-store',signal:ctrl.signal,headers:{'X-Pindah':'1','Accept':'text/html'}});
   if(!r.ok||r.redirected||!valid()||countRequest!==ctrl)return;
   const doc=new DOMParser().parseFromString(await r.text(),'text/html');
   if(!valid()||countRequest!==ctrl||doc.documentElement.dataset.versi!==cap||doc.querySelector('.bingkai')?.dataset.pindahKonteks!==context||doc.getElementById('formulir-sesi')?.dataset.token!==token)return;
   const changes=[];
   for(const key of ['tindakan','berjalan']){const old=document.querySelector('[data-tab-riwayat="'+key+'"] .kontrol-tab__jumlah'),fresh=doc.querySelector('[data-tab-riwayat="'+key+'"] .kontrol-tab__jumlah');if(!old||!fresh||!/^\d+$/.test(fresh.textContent.trim()))return;changes.push([old,fresh.textContent]);}
   for(const [old,text] of changes)old.textContent=text;
   root.removeAttribute('data-pl-shell');
  }catch(_){/* Hitungan opsional boleh tetap —; jangan mengunci katalog. */}
  finally{clearTimeout(timer);if(countRequest===ctrl)countRequest=null;}
 }
 async function baca(){
  if(!valid())return null;
  menuRequest?.abort();const ctrl=new AbortController();menuRequest=ctrl;const n=++number,timer=setTimeout(()=>ctrl.abort(),20000);
  nonaktifkan();status.hidden=false;status.querySelector('p').textContent='Memeriksa pilihan pekerjaan. Tombol tersedia setelah izin terbaru terbaca.';retry.hidden=true;hitungan();
  try{
   const r=await fetch('/api/actions/menu',{credentials:'same-origin',cache:'no-store',signal:ctrl.signal});
   if(!valid()||number!==n)return null;
   if(!r.ok||r.redirected)throw Error([401,403].includes(r.status)?'Sesi atau akses berubah. Buka kembali Pekerjaan dengan akun dan gudang yang benar. Tidak ada catatan yang disimpan.':'Pilihan pekerjaan belum dapat dibaca. Coba lagi hanya membaca.');
   const menu=await r.json();if(!valid()||number!==n)return null;
   const ids=new Set();
   if(!Array.isArray(menu)||menu.length>500)throw Error('Katalog belum lengkap. Coba lagi sebelum membuka formulir.');
   for(const a of menu){
    if(!a||typeof a.id!=='string'||ids.has(a.id)||typeof a.label!=='string'||typeof a.boleh!=='boolean'||a.fields!==undefined&&!Array.isArray(a.fields))throw Error('Katalog belum lengkap. Coba lagi sebelum membuka formulir.');
    ids.add(a.id);
   }
   return menu;
  }catch(e){if(valid()&&number===n)pesan(e.name==='AbortError'?'Pembacaan terlalu lama. Anda tetap dapat berpindah tab; Coba lagi hanya membaca.':e.message);return null;}
  finally{clearTimeout(timer);if(menuRequest===ctrl)menuRequest=null;}
 }
 function gambar(data,buka){
  if(!valid())return;
  const groups=new Map(),actions=data.menu.filter(a=>!a.kartu),ids=new Set(actions.map(a=>a.id)),order=[...new Set([...(data.urutGrup||[]),...actions.map(a=>a.grup||'Lain-lain')])],screen=root.querySelector('#layar');
  for(const a of actions){const g=a.grup||'Lain-lain';if(!groups.has(g))groups.set(g,[]);groups.get(g).push(a);}
  for(const b of screen.querySelectorAll('[data-pl-aksi]'))if(!ids.has(b.dataset.plAksi))b.remove();
  for(const name of order){
   if(!groups.has(name))continue;
   let group=[...screen.querySelectorAll('[data-pl-grup]')].find(n=>n.dataset.plGrup===name);
   if(!group){group=document.createElement('div');group.dataset.plGrup=name;const label=document.createElement('span');label.className='lbl';label.append(document.createTextNode(name+' · '));const count=document.createElement('span');count.dataset.plJumlah='';label.append(count);const list=document.createElement('div');list.className='grup';list.style.gap='8px';group.append(label,list);screen.append(group);}
   group.querySelector('[data-pl-jumlah]').textContent=groups.get(name).length;
   for(const a of groups.get(name)){
    let b=[...group.querySelectorAll('[data-pl-aksi]')].find(n=>n.dataset.plAksi===a.id);
    if(!b){b=document.createElement('button');b.type='button';b.className='tindakan';b.dataset.plAksi=a.id;const body=document.createElement('span');body.className='tindakan__isi';for(const cls of ['tindakan__nama','tindakan__ket']){const text=document.createElement('span');text.className=cls;body.append(text);}b.append(body);group.querySelector('.grup').append(b);}
    b.querySelector('.tindakan__nama').textContent=a.label;b.querySelector('.tindakan__ket').textContent=a.boleh?(a.hint||''):(a.alasan_akses||'Tidak diizinkan untuk peran atau gudang kerja Anda.');b.disabled=!a.boleh;b.removeAttribute('aria-describedby');b.title=a.boleh?'':(a.alasan_akses||'Tidak memiliki akses');b.onclick=()=>buka(a.id);
   }
  }
  for(const g of screen.querySelectorAll('[data-pl-grup]'))if(!groups.has(g.dataset.plGrup))g.remove();
  const empty=screen.querySelector('[data-pl-empty]');if(actions.length){empty?.remove();}else if(!empty){const p=document.createElement('p');p.className='bantu';p.dataset.plEmpty='';p.textContent='Tidak ada aksi untuk peran Anda.';screen.append(p);}
  root.dataset.plReady='1';status.hidden=true;root.querySelector('#pl-alasan').hidden=true;
 }
 const api={baca,gambar};root.padiKatalog=api;
 retry.addEventListener('click',()=>api.ulangi?.());
})();
