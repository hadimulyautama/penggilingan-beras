/* Struktur detail publik. Host privat hanya korelasi; data/auth tetap native. */
(function(global){
 'use strict';
 const kinds=['giling','sosoh','pengeringan'],qc=['gabah-basah','gabah-kering','pk-luar','pk-hasil-giling','beras-hasil-sosoh'];
 const variants=[...kinds.map(x=>'riwayat-'+x),...qc.map(x=>'qc-'+x),'qc-beras-daftar'];
 const menuPaths={proses:['/riwayat-sosoh','/riwayat-giling','/riwayat-pengeringan'],qc:qc.map(x=>'/riwayat-qc/'+x),laporan:['/laporan'],audit:['/audit']};
 const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k),obj=o=>!!o&&typeof o==='object'&&!Array.isArray(o);
 const exact=(o,keys)=>obj(o)&&Object.keys(o).length===keys.length&&keys.every(k=>own(o,k));
 function state(address,origin){
  if(typeof address!=='string'||address.length>4096||!address.startsWith('/')||address.startsWith('//'))return null;
  let u;try{u=new URL(address,origin);decodeURIComponent(u.search);}catch(_){return null;}
  if(u.origin!==origin||u.hash||u.pathname+u.search!==address||u.search.length>3000)return null;
  const q=u.searchParams,pairs=[...q],names=pairs.map(x=>x[0]);if(new Set(names).size!==names.length)return null;
  const h=/^\/riwayat-(giling|sosoh|pengeringan)\/([1-9][0-9]{0,9})$/.exec(u.pathname),c=/^\/riwayat-qc\/([a-z-]+)(?:\/([A-Za-z0-9][A-Za-z0-9._-]{0,79}))?$/.exec(u.pathname);
  let variant,kind,tab,parent,family;
  if(h){
   kind=h[1];if(Number(h[2])>2147483647)return null;
   const allowed=['tab_detail','halaman_jeda',...(kind==='giling'?['sebelum']:[]),...(kind==='pengeringan'?['halaman_ukur','halaman_dingin','kembali_kerja']:[])];
   if(names.some(k=>!allowed.includes(k))||q.get('sebelum')&&!/^-?[0-9]{1,10}$/.test(q.get('sebelum')))return null;
   variant='riwayat-'+kind;parent='/'+variant;family='proses';
   const tabs=kind==='pengeringan'?['ringkasan','bahan','pengukuran','riwayat']:['ringkasan','bahan','hasil','qc','riwayat'];
   tab=q.get('tab_detail');if(!tabs.includes(tab))tab=kind==='pengeringan'&&q.get('halaman_ukur')?'pengukuran':kind==='pengeringan'&&(q.get('halaman_dingin')||q.get('halaman_jeda'))?'riwayat':'ringkasan';
  }else if(c&&qc.includes(c[1])){
   kind=c[1];parent='/riwayat-qc/'+kind;family='qc';
   if(!c[2]){if(kind!=='beras-hasil-sosoh'||u.search)return null;variant='qc-beras-daftar';tab='';}
   else{
    const allowed=['tab_qc',...(kind==='beras-hasil-sosoh'?[]:['putaran','kembali_qc','kembali_jasa','kembali_stok','kembali_kerja'])];
    if(names.some(k=>!allowed.includes(k))||q.get('putaran')&&!/^[1-9][0-9]{0,8}$/.test(q.get('putaran')))return null;
    variant='qc-'+kind;const tabs=kind==='beras-hasil-sosoh'?['ringkasan','sampel','sesi','asal']:['ringkasan','putaran','perhitungan','asal'];tab=q.get('tab_qc');if(!tabs.includes(tab))tab='ringkasan';
   }
  }else return null;
  if(pairs.some(([k,v])=>k.startsWith('halaman_')&&!/^[1-9][0-9]{0,8}$/.test(v)))return null;
  return {u,variant,kind,tab,parent,family,ref:c?.[2]||null};
 }
 function nativeTitle(parts,code){return Array.isArray(parts)&&parts.length>0&&parts.length<=16&&parts.every(p=>p===null||typeof p==='string'&&p.length<=256)&&typeof code==='string'&&code.length<=80?parts.map(p=>p===null?code:p).join(''):null;}
 function validData(data){
  return exact(data,['versi','sumber','variants','styles','scripts'])&&data.versi===1&&/^[a-f0-9]{64}$/.test(data.sumber)&&exact(data.variants,variants)&&variants.every(v=>exact(data.variants[v],['html','title_parts','bar_control','breadcrumb'])&&nativeTitle(data.variants[v].title_parts,'PADI-KODE')!==null&&typeof data.variants[v].bar_control==='string'&&data.variants[v].bar_control.length<=8192&&typeof data.variants[v].html==='string'&&data.variants[v].html.length<=262144&&typeof data.variants[v].breadcrumb==='string'&&data.variants[v].breadcrumb.length<=65536)&&['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=32&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=524288));
 }
 function backContext(selected,origin){
  if(selected.variant==='riwayat-giling'){
   const raw=selected.u.searchParams.get('sebelum'),cursor=raw&&/^-?[0-9]{1,10}$/.test(raw)?Number(raw):0;
   return selected.parent+(cursor?'?sebelum='+cursor:'')+'#giling-'+selected.u.pathname.split('/').pop();
  }
  if(selected.variant==='riwayat-pengeringan'){
   const value=selected.u.searchParams.get('kembali_kerja');
   if(typeof value==='string'&&value.startsWith('/')&&!value.startsWith('//')&&!value.includes('\\')&&!/[\x00-\x1f]/.test(value)){
    try{const u=new URL(value,origin);if(u.origin===origin&&['/barang-masuk','/pekerjaan','/kabar'].includes(u.pathname))return value;}catch(_){}
   }
  }
  if(selected.family==='qc'&&selected.kind!=='beras-hasil-sosoh'){
   const paths=/^\/(?:riwayat-qc\/[\w-]+|pekerjaan|stok(?:\/pk\/detail)?|stok-pk-jasa|barang-masuk(?:\/\d+)?|jasa(?:\/pelanggan\/\d+)?|riwayat-(?:giling|pengeringan|sosoh|transfer)(?:\/\d+)?|proses-aktif\/(?:giling|pengeringan|pendinginan|sosoh)\/[\w-]+)$/;
   for(const key of ['kembali_qc','kembali_jasa','kembali_stok','kembali_kerja']){
    const value=selected.u.searchParams.get(key);
    if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.includes('\\'))continue;
    try{const u=new URL(value,origin);if(u.origin===origin&&paths.test(u.pathname))return value;}catch(_){}
   }
  }
  return selected.parent;
 }
 function contextualBack(selected,back){return selected.variant==='riwayat-pengeringan'?!!selected.u.searchParams.get('kembali_kerja'):selected.family==='qc'&&selected.kind!=='beras-hasil-sosoh'&&back!==selected.parent;}
 function validCatalog(p,{context,cap,token,source,digest}){
  return exact(p,['versi','sumber','cap','konteks','sesi','sumber_sha256','batas','boleh_catat_qc','entries'])&&p.versi===1&&p.sumber===source&&p.konteks===context&&p.cap===cap&&p.sesi===token&&p.sumber_sha256===digest&&/^[a-f0-9]{64}$/.test(digest)&&[30,200].includes(p.batas)&&typeof p.boleh_catat_qc==='boolean'&&Array.isArray(p.entries)&&p.entries.length<=p.batas&&new Set(p.entries.map(e=>e?.alamat)).size===p.entries.length&&p.entries.every(e=>{if(!exact(e,['alamat','kode','variant','boleh_koreksi'])||typeof e.kode!=='string'||!e.kode.length||e.kode.length>80||typeof e.boleh_koreksi!=='boolean')return false;const r=state(e.alamat,'https://catalog.invalid');return !!r&&r.variant===e.variant&&e.variant!=='qc-beras-daftar'&&(!r.ref||r.ref===e.kode)&&(!e.boleh_koreksi||['riwayat-giling','riwayat-sosoh'].includes(e.variant));});
 }
 function menuValid(p,{context,cap,token,digest}){
  if(!exact(p,['versi','cap','konteks','sesi','sumber','targets','menu'])||p.versi!==1||p.konteks!==context||p.cap!==cap||p.sesi!==token||typeof digest!=='string'||!/^[a-f0-9]{64}$/.test(digest)||p.sumber!==digest||!Array.isArray(p.targets)||!p.targets.length||p.targets.length>8||new Set(p.targets).size!==p.targets.length||p.targets.some(x=>!Object.values(menuPaths).flat().includes(x))||!exact(p.menu,['default','tabs'])||!obj(p.menu.tabs)||!Object.keys(p.menu.tabs).length||Object.keys(p.menu.tabs).some(k=>!own(menuPaths,k)))return false;
  for(const [key,t]of Object.entries(p.menu.tabs))if(!exact(t,['first','allowed'])||!Array.isArray(t.allowed)||!t.allowed.length||t.allowed.length>menuPaths[key].length||new Set(t.allowed).size!==t.allowed.length||t.allowed.some(v=>!menuPaths[key].includes(v))||t.first!==t.allowed[0])return false;
  return p.menu.default===p.menu.tabs[Object.keys(menuPaths).find(k=>own(p.menu.tabs,k))].first;
 }
 function currentCatalog(data,context,cap,token){
  const source=location.pathname+location.search,frame=document.querySelector('.bingkai');
  if(!frame||frame.dataset.pindahAlamat!==source||frame.dataset.pindahKonteks!==context||document.documentElement.dataset.versi!==cap||document.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const hosts=document.querySelectorAll('[data-riwayat-detail-catalog]');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.sourceAddress!==source||host.textContent.length>262144)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}
  if(!validCatalog(p,{context,cap,token,source:data.sumber,digest:host.dataset.sourceSha}))return null;
  const url=new URL(source,location.href),history=kinds.some(k=>url.pathname==='/riwayat-'+k),check=qc.some(k=>url.pathname==='/riwayat-qc/'+k);
  if(!history&&!check||p.batas!==(history?30:200)||p.entries.some(e=>!e.alamat.startsWith(url.pathname+'/')))return null;
  const params=Array.from(url.searchParams);if(url.search.length>2049||url.search&&(!history||params.length!==1||params[0][0]!=='sebelum'))return null;
  return p;
 }
 function visible(node){return !!node?.getClientRects().length&&!['hidden','collapse'].includes(getComputedStyle(node).visibility)&&!node.closest('[hidden],[inert],[aria-hidden="true"]');}
 function visibleLink(entry){
  const root=document.querySelector(entry.variant.startsWith('riwayat-')?'[data-daftar-riwayat-proses]':'[data-riwayat-qc]');if(!root)return null;
  return Array.from(root.querySelectorAll('a[href]')).find(a=>{
   if(a.getAttribute('href')!==entry.alamat||!visible(a)||a.hasAttribute('target')||a.hasAttribute('download')||a.getAttribute('aria-disabled')==='true')return false;
   if(entry.variant.startsWith('riwayat-')){
    const row=a.closest('article[data-rg-proses],tr[data-rg-proses],details.padat,details.riwayat-desktop-row');
    return !!row&&visible(row)&&!!(a.closest('.padat__nama--kode,.riwayat-desktop-lot')||a.classList.contains('rg-kode'))&&a.textContent.trim()===entry.kode;
   }
   if(entry.variant==='qc-beras-hasil-sosoh')return !!a.closest('[data-rqd-beras]')&&!!a.closest('h2')&&a.textContent.trim()===entry.kode;
   return a.matches('a.tabel-standar__baris')&&a.querySelector('.tabel-standar__kode')?.textContent.trim()===entry.kode;
  })||null;
 }
 function pruneNavigation(root,selection,menu){
  const nav=root.querySelector('[data-laporan-kontrol]');if(!nav)throw Error('Kontrol native tidak ada');nav.dataset.aktif=selection.family;
  const source=JSON.parse(nav.dataset.tujuanTab||'[]');nav.dataset.tujuanTab=JSON.stringify(source.map(t=>({...t,href:menu.tabs[t.kunci]?.first||'',boleh:!!menu.tabs[t.kunci],alamat:menu.tabs[t.kunci]?.allowed||[]})));
  for(const a of nav.querySelectorAll('[data-tab-riwayat]')){const scope=menu.tabs[a.dataset.tabRiwayat];if(!scope){const span=a.ownerDocument.createElement('span');span.className=a.className+' akses-terkunci';span.setAttribute('aria-disabled','true');span.textContent=a.textContent;a.replaceWith(span);}else{a.href=scope.first;a.dataset.tujuan=JSON.stringify(scope.allowed);a.toggleAttribute('aria-current',a.dataset.tabRiwayat===selection.family);if(a.hasAttribute('aria-current'))a.setAttribute('aria-current','page');}}
  const allowed=menu.tabs[selection.family]?.allowed||[];
  for(const option of nav.querySelectorAll('select[data-jenis-riwayat] option')){option.disabled=!allowed.includes(option.value);option.toggleAttribute('selected',option.value===selection.parent);}
  for(const a of nav.querySelectorAll('.laporan-nav__jenis a[href]'))if(!allowed.includes(a.getAttribute('href'))){const span=a.ownerDocument.createElement('span');span.className='akses-terkunci';span.setAttribute('aria-disabled','true');span.textContent=a.textContent;a.replaceWith(span);}else{a.toggleAttribute('aria-current',a.getAttribute('href')===selection.parent);if(a.hasAttribute('aria-current'))a.setAttribute('aria-current','page');}
 }
 const data=global.PadiKerangkaRiwayatDetailData;
 function buat(address,base,context,cap,token){
  const selected=state(address,location.origin);if(!selected||!validData(data)||typeof base!=='string'||base.length>8388608)return null;
  const hosts=document.querySelectorAll('#padi-riwayat-kerangka');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>8192)return null;
  let permission;try{permission=JSON.parse(host.textContent);}catch(_){return null;}
  if(!menuValid(permission,{context,cap,token,digest:global.PadiKerangkaRiwayatUI?.sumber})||!permission.menu.tabs[selected.family]?.allowed.includes(selected.parent))return null;
  const catalog=currentCatalog(data,context,cap,token),entry=catalog?.entries.find(e=>e.alamat===address&&e.variant===selected.variant);
  if(selected.variant!=='qc-beras-daftar'&&(!entry||!visibleLink(entry)||!address.startsWith(location.pathname+'/')))return null;
  const doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=Array.from(main.childNodes),start=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),end=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(start.length!==1||end.length!==1||!(start[0].compareDocumentPosition(end[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=data.variants[selected.variant].html;
  for(const [selector,pool,key]of [['style[data-detail-style]',data.styles,'data-detail-style'],['script[data-detail-script]',data.scripts,'data-detail-script']])for(const node of part.content.querySelectorAll(selector)){const ref=node.getAttribute(key);if(!own(pool,ref))return null;node.textContent=pool[ref];node.removeAttribute(key);}
  const roots=part.content.querySelectorAll('[data-riwayat-detail-native]');if(roots.length!==1||part.content.querySelector('form,[name],[data-post],[data-kirim],script[src],link[rel=stylesheet]')||Array.from(part.content.querySelectorAll('input,select,textarea')).some(f=>!f.disabled||f.hasAttribute('value')))return null;
  const root=roots[0];root.dataset.url=address;root.dataset.stamp=context+'|'+address;root.dataset.rdnTab=selected.tab;
  for(const n of root.querySelectorAll('[data-rdn-privilege]'))if(n.dataset.rdnPrivilege==='koreksi'?!entry?.boleh_koreksi:!(selected.variant==='qc-beras-daftar'&&catalog?.boleh_catat_qc))n.remove();
  const code=root.querySelector('[data-rdn-code]');if(code)code.textContent=entry.kode;
  const back=backContext(selected,location.origin);let backLink=root.querySelector('.rhs-back,.riwayat-detail__back');
  const contextual=root.querySelector('template[data-rdn-back-context]');
  if(contextualBack(selected,back)){
   const anchor=contextual?.content.querySelector('a.rhs-back,a.riwayat-detail__back');
   if(!backLink||!anchor||contextual.content.querySelectorAll('a').length!==1||contextual.content.querySelector('script,form,input,button'))return null;
   backLink.replaceWith(anchor.cloneNode(true));backLink=root.querySelector('.rhs-back,.riwayat-detail__back');
  }
  if(backLink)backLink.setAttribute('href',back);contextual?.remove();
  for(const t of root.querySelectorAll('[data-rdn-tab]')){const active=t.dataset.rdnTab===selected.tab;t.setAttribute('aria-selected',String(active));t.tabIndex=active?0:-1;}
  for(const p of root.querySelectorAll('[data-rdn-panel]'))p.hidden=p.dataset.rdnPanel!==selected.tab;
  try{pruneNavigation(part.content,selected,permission.menu);}catch(_){return null;}
  while(start[0].nextSibling&&start[0].nextSibling!==end[0])start[0].nextSibling.remove();end[0].before(part.content);
  main.querySelectorAll('.desktop-back').forEach(n=>n.remove());const title=nativeTitle(data.variants[selected.variant].title_parts,entry?.kode||'');
  const bar=main.querySelector('.bar__merek');if(bar){bar.textContent=title;bar.setAttribute('aria-label',bar.textContent);}
  const control=doc.createElement('template');control.innerHTML=data.variants[selected.variant].bar_control;
  if(control.content.querySelectorAll('button.bar__menu').length!==1||control.content.querySelector('a,script,form,input'))return null;
  main.querySelectorAll('.bar__menu,.bar__balik').forEach(n=>n.remove());main.querySelector('header.bar')?.prepend(control.content);
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){
   const template=doc.createElement('template');template.innerHTML=data.variants[selected.variant].breadcrumb;
   const nav=template.content.querySelector('nav.desktop-breadcrumb'),leaf=nav?.querySelector('[aria-current="page"]');
   if(template.content.querySelectorAll('nav.desktop-breadcrumb').length!==1||!leaf)return null;
   if(entry)leaf.textContent=entry.kode;
   for(const a of template.content.querySelectorAll('a[href]')){
    const u=new URL(a.getAttribute('href'),location.href);
    if(u.pathname===selected.parent&&(selected.variant==='riwayat-giling'||selected.variant==='riwayat-pengeringan'&&new URL(back,location.href).pathname===selected.parent))a.setAttribute('href',back);
   }
   crumb.replaceChildren(template.content);
  }
  for(const old of doc.querySelectorAll('#padi-riwayat-kerangka'))old.remove();doc.body.append(doc.importNode(host,true));
  frame.dataset.pindahAlamat=address;doc.title=title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:address,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 if(typeof module==='object'&&module.exports){module.exports={nativeTitle,state,validData,validCatalog,menuValid,backContext,contextualBack,visibleLink};return;}
 global.PadiKerangkaRiwayatDetailUI=Object.freeze({versi:1,sumber:data?.sumber,buat,currentCatalog:(context,cap,token)=>validData(data)?currentCatalog(data,context,cap,token):null,visibleLink});
})(typeof window==='undefined'?globalThis:window);
