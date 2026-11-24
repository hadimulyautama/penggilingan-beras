/* Public native History structure; permission metadata comes from this document.
 * No read requests, storage, actor inference, transaction or route discovery. */
(function(global){
 'use strict';
 const PROCESS=['/riwayat-giling','/riwayat-sosoh','/riwayat-pengeringan'];
 const QC=['gabah-basah','gabah-kering','pk-luar','pk-hasil-giling'].map(k=>'/riwayat-qc/'+k);
 const PATHS=[...PROCESS,...QC];
 const MENU={proses:['/riwayat-sosoh','/riwayat-giling','/riwayat-pengeringan'],
  qc:['/riwayat-qc/gabah-basah','/riwayat-qc/gabah-kering','/riwayat-qc/pk-hasil-giling','/riwayat-qc/pk-luar','/riwayat-qc/beras-hasil-sosoh'],
  laporan:['/laporan'],audit:['/audit']};
 const own=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
 const object=value=>!!value&&typeof value==='object'&&!Array.isArray(value);
 const exact=(value,keys)=>object(value)&&Object.keys(value).length===keys.length&&keys.every(k=>own(value,k));
 function address(value,origin){
  if(typeof value!=='string'||typeof origin!=='string'||!value.startsWith('/')||value.startsWith('//'))return null;
  let u;try{u=new URL(value,origin);}catch(_){return null;}
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||!PATHS.includes(u.pathname)||u.search.length>2049)return null;
  const pairs=[...u.searchParams];
  if(QC.includes(u.pathname)&&u.search||PROCESS.includes(u.pathname)&&u.search&&(pairs.length!==1||pairs[0][0]!=='sebelum'))return null;
  return {path:u.pathname,family:PROCESS.includes(u.pathname)?'proses':'qc',kind:PROCESS.includes(u.pathname)?({'/riwayat-giling':'giling','/riwayat-sosoh':'sosoh','/riwayat-pengeringan':'pengeringan'}[u.pathname]):u.pathname.split('/').pop()};
 }
 function validData(data){
  return exact(data,['versi','sumber','variants','styles','scripts'])&&data.versi===1&&typeof data.sumber==='string'&&/^[a-f0-9]{64}$/.test(data.sumber)
   &&object(data.variants)&&Object.keys(data.variants).length===7&&PATHS.every(path=>exact(data.variants[path],['title','html','breadcrumb'])
    &&['title','html','breadcrumb'].every(k=>typeof data.variants[path][k]==='string')&&data.variants[path].html.length<=524288&&data.variants[path].breadcrumb.length<=65536)
   &&['styles','scripts'].every(k=>object(data[k])&&Object.keys(data[k]).length<=64&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=524288));
 }
 function validPermission(permission,data,context,cap,token){
  if(!validData(data)||!exact(permission,['versi','cap','konteks','sesi','sumber','targets','menu'])||permission.versi!==1
    ||permission.cap!==cap||permission.konteks!==context||permission.sesi!==token||permission.sumber!==data.sumber
    ||![context,cap,token].every(v=>typeof v==='string'&&v)
    ||!Array.isArray(permission.targets)||!permission.targets.length||permission.targets.length>7
    ||new Set(permission.targets).size!==permission.targets.length||permission.targets.some(p=>typeof p!=='string'||!PATHS.includes(p))
    ||!exact(permission.menu,['default','tabs'])||!object(permission.menu.tabs)||!Object.keys(permission.menu.tabs).length
    ||Object.keys(permission.menu.tabs).some(k=>!own(MENU,k)))return false;
  for(const [key,tab] of Object.entries(permission.menu.tabs)){
   if(!exact(tab,['first','allowed'])||!Array.isArray(tab.allowed)||!tab.allowed.length||tab.allowed.length>MENU[key].length
    ||new Set(tab.allowed).size!==tab.allowed.length||tab.allowed.some(p=>typeof p!=='string'||!MENU[key].includes(p))
    ||tab.first!==tab.allowed[0])return false;
  }
  const first=Object.keys(MENU).find(k=>own(permission.menu.tabs,k));
  if(permission.menu.default!==permission.menu.tabs[first].first)return false;
  return permission.targets.every(path=>permission.menu.tabs[PROCESS.includes(path)?'proses':'qc']?.allowed.includes(path));
 }
 function pruneNavigation(doc,root,state,menu){
  const nav=root.querySelector('[data-laporan-kontrol]');if(!nav)throw Error('Native navigation missing');
  nav.dataset.aktif=state.family;
  const source=JSON.parse(nav.dataset.tujuanTab||'[]'),tabs=[];
  for(const tab of source){
   const scope=menu.tabs[tab.kunci];
   tabs.push({...tab,href:scope?.first||'',boleh:!!scope,alamat:scope?.allowed||[]});
  }
  nav.dataset.tujuanTab=JSON.stringify(tabs);
  for(const link of nav.querySelectorAll('[data-tab-riwayat]')){
   const key=link.dataset.tabRiwayat,scope=menu.tabs[key];
   if(!scope){const span=doc.createElement('span');span.className='kontrol-tab__item akses-terkunci';span.setAttribute('aria-disabled','true');span.title='Tidak memiliki akses';span.textContent=link.querySelector('.kontrol-tab__label')?.textContent||link.textContent;link.replaceWith(span);continue;}
   link.setAttribute('href',scope.first);link.dataset.tujuan=JSON.stringify(scope.allowed);
   if(key===state.family)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  }
  const allowed=menu.tabs[state.family].allowed;
  for(const select of nav.querySelectorAll('[data-jenis-riwayat]')){
   for(const option of select.options){
    const path=option.getAttribute('value'),enabled=allowed.includes(path);
    option.disabled=!enabled;option.selected=enabled&&path===state.path;
    option.toggleAttribute('selected',option.selected);
    if(!enabled){option.removeAttribute('value');option.textContent=option.textContent+' — tidak memiliki akses';}
   }
  }
  for(const link of nav.querySelectorAll('.laporan-nav__jenis a[href]')){
   const path=link.getAttribute('href');
   if(!allowed.includes(path)){const span=doc.createElement('span');span.className='akses-terkunci';span.setAttribute('aria-disabled','true');span.title='Tidak memiliki akses gudang ini';span.textContent=link.textContent;link.replaceWith(span);continue;}
   if(path===state.path)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  }
 }
 function markNavigation(doc,path){
  for(const summary of doc.querySelectorAll('#laci summary.pintu')){summary.classList.remove('pintu--kini');summary.removeAttribute('aria-current');}
  for(const link of doc.querySelectorAll('#laci a[href]')){
   const url=new URL(link.getAttribute('href'),location.href);
   const active=url.origin===location.origin&&(url.pathname===path||['/riwayat','/laporan-riwayat'].includes(url.pathname));
   link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));
   link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));
   if(active){link.setAttribute('aria-current','page');const group=link.closest('details');if(group){group.open=true;group.querySelector('summary')?.classList.add('pintu--kini');}}
   else link.removeAttribute('aria-current');
  }
 }
 if(typeof module==='object'&&module.exports){module.exports={address,validData,validPermission,pruneNavigation};return;}
 const data=global.PadiKerangkaRiwayatData;if(!validData(data))return;
 for(const variant of Object.values(data.variants))Object.freeze(variant);
 Object.freeze(data.variants);Object.freeze(data.styles);Object.freeze(data.scripts);Object.freeze(data);
 function buat(target,base,context,cap,token){
  const state=address(target,location.origin);if(!state||typeof base!=='string'||base.length>8388608)return null;
  const hosts=document.querySelectorAll('#padi-riwayat-kerangka');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>8192)return null;
  let permission;try{permission=JSON.parse(host.textContent);}catch(_){return null;}
  if(!validPermission(permission,data,context,cap,token)||!permission.targets.includes(state.path)||!permission.menu.tabs[state.family]?.allowed.includes(state.path))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1)return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const component=data.variants[state.path],part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attribute] of [['style[data-history-style-ref]',data.styles,'data-history-style-ref'],['script[data-history-script-ref]',data.scripts,'data-history-script-ref']]){
   for(const node of part.content.querySelectorAll(selector)){
    const key=node.getAttribute(attribute);if(!own(pool,key))return null;
    node.textContent=pool[key];node.removeAttribute(attribute);
   }
  }
  const root=part.content.querySelector('.laporan-riwayat'),reader=part.content.querySelector('[data-riwayat-daftar-native]');
  if(!root||!reader||!root.contains(reader)||part.content.querySelectorAll('.laporan-riwayat').length!==1||part.content.querySelectorAll('[data-riwayat-daftar-native]').length!==1||part.content.querySelector('form,input,[data-post],[data-kirim],script[src],link[rel="stylesheet"]'))return null;
  try{pruneNavigation(doc,root,state,permission.menu);}catch(_){return null;}
  reader.dataset.url=target;reader.dataset.stamp=context+'|'+target;
  for(const button of root.querySelectorAll('[data-lk-cetak],[data-rpd-print]')){button.disabled=true;button.setAttribute('disabled','');button.setAttribute('aria-describedby','riwayat-native-cetak-alasan');}
  const [from,to]=[starts[0],ends[0]];
  while(from.nextSibling&&from.nextSibling!==to)from.nextSibling.remove();to.before(part.content);
  for(const node of main.querySelectorAll('.desktop-back'))node.remove();
  const title=main.querySelector('.bar__merek');if(title){title.textContent=component.title;title.setAttribute('aria-label',component.title);}
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const html=doc.createElement('template');html.innerHTML=component.breadcrumb;crumb.replaceChildren(html.content);}
  // Never carry an older full-frame History registry from a BM base. Keep
  // only the already validated metadata host from this current document.
  for(const old of doc.querySelectorAll('#padi-riwayat-kerangka'))old.remove();
  if(!doc.body)return null;doc.body.append(doc.importNode(host,true));
  markNavigation(doc,state.path);
  frame.dataset.pindahAlamat=target;doc.title=component.title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 global.PadiKerangkaRiwayatUI=Object.freeze({versi:1,sumber:data.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
