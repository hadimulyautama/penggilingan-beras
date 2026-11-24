/* Paket dryer publik tidak mempunyai izin, akun, angka atau tindakan tulis. */
(function(global){
 'use strict';
 const phases=['pengeringan','pendinginan'];
 const data=global.PadiKerangkaPengeringanData;
 const own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k);
 const object=v=>!!v&&typeof v==='object'&&!Array.isArray(v);
 const exact=(v,keys)=>object(v)&&Object.keys(v).length===keys.length&&keys.every(k=>own(v,k));
 function validPackage(p){
  return exact(p,['versi','sumber','variants'])&&p.versi===1&&/^[a-f0-9]{64}$/.test(p.sumber)&&exact(p.variants,phases)&&phases.every(k=>exact(p.variants[k],['html','breadcrumb'])&&typeof p.variants[k].html==='string'&&p.variants[k].html.length<=262144&&typeof p.variants[k].breadcrumb==='string'&&p.variants[k].breadcrumb.length<=65536);
 }
 function backContext(value,origin){
  const fallback='/pekerjaan?tab=berjalan';
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\')||/[\x00-\x1f]/.test(value))return {body:fallback,crumb:fallback};
  let u;try{u=new URL(value,origin);}catch(_){return {body:fallback,crumb:fallback};}
  if(u.origin!==origin||!['/barang-masuk','/pekerjaan','/kabar'].includes(u.pathname))return {body:fallback,crumb:fallback};
  return {body:value,crumb:u.pathname==='/pekerjaan'&&u.search?value:fallback};
 }
 function validCatalog(p,{cap,context,token,source,digest}){
  return exact(p,['versi','cap','konteks','sesi','sumber','sumber_sha256','entries'])&&p.versi===1&&p.cap===cap&&p.konteks===context&&p.sesi===token&&p.sumber===source&&p.sumber_sha256===digest&&/^[a-f0-9]{64}$/.test(digest)&&Array.isArray(p.entries)&&p.entries.length<=50&&p.entries.every(e=>exact(e,['alamat','kode','fase','label'])&&typeof e.alamat==='string'&&e.alamat.length<=4096&&typeof e.kode==='string'&&phases.includes(e.fase)&&e.label===e.fase[0].toUpperCase()+e.fase.slice(1)+' aktif');
 }
 function state(address,origin){
  if(typeof address!=='string'||address.length>4096||!address.startsWith('/')||address.startsWith('//'))return null;
  let u;try{u=new URL(address,origin);}catch(_){return null;}
  try{decodeURIComponent(u.search);}catch(_){return null;}
  const m=/^\/proses-aktif\/(pengeringan|pendinginan)\/([A-Za-z0-9][A-Za-z0-9._-]{0,79})$/.exec(u.pathname),q=u.searchParams;
  if(u.origin!==origin||u.hash||u.pathname+u.search!==address||!m||u.search.length>3000||Array.from(q.keys()).some(k=>!['tab_detail','kembali_kerja','halaman_ukur','halaman_dingin','halaman_jeda'].includes(k)||q.getAll(k).length!==1))return null;
  if(['halaman_ukur','halaman_dingin','halaman_jeda'].some(k=>q.has(k)&&!(/^[1-9][0-9]{0,8}$/).test(q.get(k))))return null;
  let tab=q.get('tab_detail');if(!['ringkasan','bahan','pengukuran','riwayat'].includes(tab))tab=q.get('halaman_ukur')?'pengukuran':q.get('halaman_dingin')||q.get('halaman_jeda')?'riwayat':'ringkasan';
  return {u,phase:m[1],code:m[2],tab};
 }
 function buat(address,base,context,cap,token){
  const selected=state(address,location.origin);
  if(!selected||!validPackage(data)||typeof base!=='string'||base.length>8388608||![context,cap,token].every(x=>typeof x==='string'&&x&&x.length<=512))return null;
  const source=location.pathname+location.search,current=document.querySelector('.bingkai');
  if(!['/pekerjaan','/berjalan'].includes(location.pathname)||current?.dataset.pindahAlamat!==source||current.dataset.pindahKonteks!==context||document.documentElement.dataset.versi!==cap||document.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const hosts=document.querySelectorAll('[data-pengeringan-native-catalog]');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.sourceAddress!==source||host.textContent.length>262144)return null;
  let catalog;try{catalog=JSON.parse(host.textContent);}catch(_){return null;}
  if(!validCatalog(catalog,{cap,context,token,source:data.sumber,digest:host.dataset.sourceSha})||!catalog.entries.some(e=>e.alamat===address&&e.kode===selected.code&&e.fase===selected.phase))return null;
  const visible=node=>!!node.getClientRects().length&&!['hidden','collapse'].includes(getComputedStyle(node).visibility)&&!node.closest('[hidden],[inert],[aria-hidden="true"]');
  const rows=Array.from(document.querySelectorAll('section[data-blok][aria-label="Proses aktif"] .proses-aktif-list > .proses-aktif-list__row'));
  if(rows.length>50||!rows.some(row=>row.dataset.proses===selected.phase&&visible(row)&&row.querySelector('strong')?.textContent.trim()===selected.code&&(row.matches('a[href]')?[row]:Array.from(row.querySelectorAll('a.proses-aktif-list__detail[href]'))).some(a=>a.getAttribute('href')===address&&visible(a)&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true')))return null;
  const doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=Array.from(main.childNodes),starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=data.variants[selected.phase].html;
  const roots=part.content.querySelectorAll('[data-dryer-native-html]');if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[name],[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;
  const root=roots[0];root.dataset.fase=selected.phase;root.dataset.url=address;root.dataset.stamp=context+'|'+address;root.dataset.tab=selected.tab;
  root.querySelector('.dr-code,.rhs-code').textContent=selected.code;
  const back=backContext(selected.u.searchParams.get('kembali_kerja'),location.origin);
  root.querySelector('.riwayat-detail__back').href=back.body;
  for(const tab of root.querySelectorAll('[data-dryer-tab]')){const active=tab.dataset.dryerTab===selected.tab;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
  for(const panel of root.querySelectorAll('[data-dryer-panel]'))panel.hidden=panel.dataset.dryerPanel!==selected.tab;
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  main.querySelectorAll('.desktop-back').forEach(n=>n.remove());
  const title=selected.phase[0].toUpperCase()+selected.phase.slice(1)+' aktif';
  const bar=main.querySelector('.bar__merek');if(bar){bar.textContent=title;bar.setAttribute('aria-label',title);}
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){
   const template=doc.createElement('template');template.innerHTML=data.variants[selected.phase].breadcrumb;
   const nav=template.content.querySelector('nav.desktop-breadcrumb'),leaf=nav?.querySelector('[aria-current="page"]');
   if(template.content.querySelectorAll('nav.desktop-breadcrumb').length!==1||!leaf||template.content.querySelectorAll('a.desktop-back').length!==1)return null;
   leaf.textContent=selected.code;
   for(const a of template.content.querySelectorAll('a[href="/pekerjaan?tab=berjalan"]'))a.setAttribute('href',back.crumb);
   crumb.replaceChildren(template.content);
  }
  for(const link of doc.querySelectorAll('#laci a[href]')){const active=link.getAttribute('href')==='/pekerjaan';link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=address;doc.title=title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:address,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 if(typeof module==='object'&&module.exports){module.exports={validPackage,validCatalog,state,backContext};return;}
 global.PadiKerangkaPengeringanUI=Object.freeze({versi:1,buat});
})(typeof window==='undefined'?globalThis:window);
