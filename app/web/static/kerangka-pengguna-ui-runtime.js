/* Native user layouts. Metadata/correlated hrefs select shape, never authority. */
(function(global){
 'use strict';
 const VARIANTS=['staf','staf-super','staf-detail','pelanggan','pelanggan-detail'],HOST='padi-pengguna-kerangka';
 const object=v=>!!v&&typeof v==='object'&&!Array.isArray(v),own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k),exact=(v,keys)=>object(v)&&Object.keys(v).length===keys.length&&keys.every(k=>own(v,k));
 function stripNative(value){return value.replace(/^[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,'');}
 function state(address,origin){
  if(typeof address!=='string'||address.length>4096||!address.startsWith('/')||address.startsWith('//'))return null;
  let u;try{u=new URL(address,origin);decodeURIComponent(u.search);}catch(_){return null;}
  if(u.origin!==origin||u.hash||u.pathname+u.search!==address||u.search.length>2048)return null;
  const staff=/^\/pengguna(?:\/([1-9][0-9]{0,9}))?$/.exec(u.pathname),customer=/^\/pengguna\/pelanggan(?:\/([1-9][0-9]{0,9}))?$/.exec(u.pathname);
  let id,kind,search='';
  if(staff){if(u.search)return null;id=staff[1];kind=id?'staf-detail':'staf';}
  else if(customer){id=customer[1];kind=id?'pelanggan-detail':'pelanggan';const q=[...u.searchParams];if(new Set(q.map(x=>x[0])).size!==q.length||q.some(([k,v])=>!['cari_akun','halaman_akun'].includes(k)||k==='halaman_akun'&&!/^[0-9]{1,9}$/.test(v)))return null;search=Array.from(stripNative(u.searchParams.get('cari_akun')||'')).slice(0,100).join('');}
  else return null;
  if(id&&Number(id)>2147483647)return null;
  return {u,kind,search,parent:kind.startsWith('staf')?'/pengguna':'/pengguna/pelanggan'};
 }
 function validData(d){
  return exact(d,['versi','sumber','variants','styles','scripts'])&&d.versi===1&&/^[a-f0-9]{64}$/.test(d.sumber)&&exact(d.variants,VARIANTS)&&VARIANTS.every(v=>exact(d.variants[v],['title','html','breadcrumb','bar','kembali'])&&typeof d.variants[v].title==='string'&&d.variants[v].title.length<=200&&typeof d.variants[v].html==='string'&&d.variants[v].html.length<=65536&&typeof d.variants[v].breadcrumb==='string'&&d.variants[v].breadcrumb.length<=65536&&typeof d.variants[v].bar==='string'&&d.variants[v].bar.length<=8192&&['/pengaturan','/pengguna'].includes(d.variants[v].kembali))&&['styles','scripts'].every(k=>object(d[k])&&Object.keys(d[k]).length<=8&&Object.values(d[k]).every(v=>typeof v==='string'&&v.length<=262144));
 }
 function validPermission(p,data,ctx,cap,token){
  return exact(p,['versi','cap','konteks','sesi','sumber','targets'])&&p.versi===1&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===ctx&&p.sesi===token&&[ctx,cap,token].every(x=>typeof x==='string'&&x&&x.length<=2048)&&object(p.targets)&&Object.keys(p.targets).length>0&&Object.keys(p.targets).length<=2&&Object.entries(p.targets).every(([path,variant])=>path==='/pengguna'&&['staf','staf-super'].includes(variant)||path==='/pengguna/pelanggan'&&variant==='pelanggan')&&(!own(p.targets,'/pengguna/pelanggan')||p.targets['/pengguna']==='staf-super');
 }
 function validCatalog(p,data,ctx,cap,token,source){
  const selection=state(source,'https://catalog.invalid');if(!selection||!['staf','pelanggan'].includes(selection.kind))return false;
  return exact(p,['versi','sumber','source_address','source_sha256','cap','konteks','sesi','entries'])&&p.versi===1&&p.sumber===data.sumber&&p.source_address===source&&typeof p.source_sha256==='string'&&/^[a-f0-9]{64}$/.test(p.source_sha256)&&p.cap===cap&&p.konteks===ctx&&p.sesi===token&&Array.isArray(p.entries)&&p.entries.length<=(source.split('?')[0]==='/pengguna'?200:20)&&new Set(p.entries.map(e=>e?.alamat)).size===p.entries.length&&p.entries.every(e=>{const s=typeof e?.alamat==='string'?state(e.alamat,'https://catalog.invalid'):null;return exact(e,['alamat','variant','title'])&&!!s&&s.kind===e.variant&&['staf-detail','pelanggan-detail'].includes(s.kind)&&s.parent===source.split('?')[0]&&typeof e.title==='string'&&e.title.length>0&&e.title.length<=200;});
 }
 function frameBound(doc,ctx,cap,token,address){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!session&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1&&frame.contains(main)&&frame.contains(session)&&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&session.dataset.token===token&&(address===undefined||frame.dataset.pindahAlamat===address);
 }
 function visible(n){return !!n?.getClientRects().length&&!['hidden','collapse'].includes(getComputedStyle(n).visibility)&&!n.closest('[hidden],[inert],[aria-hidden="true"]');}
 function visibleLink(entry){
  const staff=entry.variant==='staf-detail',rows=document.querySelectorAll(staff?'.daftar-standar > .daftar-standar__baris':'.kelola-portal table tbody tr');
  return Array.from(rows).filter(visible).some(row=>Array.from(row.querySelectorAll('a[href]')).some(a=>a.getAttribute('href')===entry.alamat&&visible(a)&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true'&&(!staff||row.querySelector('.baris__nama')?.textContent.trim()===entry.title)));
 }
 const data=global.PadiKerangkaPenggunaData;
 function construct(address,base,ctx,cap,token){
  const selected=state(address,location.origin),source=location.pathname+location.search;
  if(!selected||!validData(data)||typeof base!=='string'||base.length>8388608||!frameBound(document,ctx,cap,token,source)||document.querySelector('[data-editor-perintah],[data-kemas-ulang]')||document.body.hasAttribute('data-portal-akun'))return null;
  const hosts=document.querySelectorAll('#'+HOST);if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>8192)return null;
  let permission;try{permission=JSON.parse(host.textContent);}catch(_){return null;}
  if(!validPermission(permission,data,ctx,cap,token)||!own(permission.targets,selected.parent))return null;
  let variant=selected.kind==='staf'?permission.targets['/pengguna']:selected.kind,title;
  if(selected.kind.endsWith('-detail')){
   const nodes=document.querySelectorAll('[data-pengguna-native-catalog]');if(nodes.length!==1)return null;
   const node=nodes[0];if(!node.isConnected||node.dataset.sourceAddress!==source||node.textContent.length>131072)return null;
   let c;try{c=JSON.parse(node.textContent);}catch(_){return null;}
   if(!validCatalog(c,data,ctx,cap,token,source)||c.source_sha256!==node.dataset.sourceSha)return null;
   const entry=c.entries.find(e=>e.alamat===address&&e.variant===selected.kind);
   if(!entry||!visibleLink(entry)||!address.startsWith(location.pathname+'/'))return null;
   title=entry.title;
  }
  const component=data.variants[variant];title=title||component.title;
  const doc=new DOMParser().parseFromString(base,'text/html');if(!frameBound(doc,ctx,cap,token))return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),nodes=Array.from(main.childNodes),start=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),end=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(start.length!==1||end.length!==1||!(start[0].compareDocumentPosition(end[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attr]of [['style[data-users-style]',data.styles,'data-users-style'],['script[data-users-script]',data.scripts,'data-users-script']])for(const n of part.content.querySelectorAll(selector)){const key=n.getAttribute(attr);if(!own(pool,key))return null;n.textContent=pool[key];n.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-pengguna-baca-native]');if(roots.length!==1||part.content.querySelector('form,[name],input[type=hidden],[data-post],[data-kirim],script[src],link[rel=stylesheet]')||Array.from(part.content.querySelectorAll('input,select,textarea')).some(n=>!n.disabled)||Array.from(part.content.querySelectorAll('button:not([data-pengguna-baca-retry])')).some(n=>!n.disabled||n.type!=='button'))return null;
  const root=roots[0];root.dataset.url=address;root.dataset.stamp=ctx+'|'+address;
  if(variant==='staf-detail')root.querySelector('[data-pengguna-nama]').textContent=title;
  const filter=root.querySelector('[data-pengguna-cari]');if(filter)filter.setAttribute('value',selected.search);
  // The source prototype has no Reset when query is empty; add only that
  // native read link beside its own filter, never a target/resource/action.
  if(selected.search&&filter){const a=doc.createElement('a');a.className='btn';a.href='/pengguna/pelanggan';a.textContent='Reset';filter.parentElement.append(a);}
  while(start[0].nextSibling&&start[0].nextSibling!==end[0])start[0].nextSibling.remove();end[0].before(part.content);
  const brand=main.querySelector('.bar__merek');if(!brand)return null;brand.textContent=title;brand.setAttribute('aria-label',title);
  const top=main.querySelector('header.bar'),control=doc.createElement('template');control.innerHTML=component.bar;
  if(!top||control.content.querySelectorAll('a.bar__balik').length!==1||control.content.querySelector('script,button,form,input'))return null;
  control.content.querySelector('a.bar__balik').setAttribute('href',component.kembali);top.querySelectorAll('.bar__menu,.bar__balik').forEach(n=>n.remove());top.prepend(control.content);
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const t=doc.createElement('template');t.innerHTML=component.breadcrumb;if(variant==='staf-detail'){const leaf=t.content.querySelector('[aria-current=page]');if(!leaf)return null;leaf.textContent=title;}crumb.replaceChildren(t.content);}
  for(const old of doc.querySelectorAll('#'+HOST))old.remove();doc.body.append(doc.importNode(host,true));
  for(const link of doc.querySelectorAll('#laci a[href]')){const active=selected.kind.startsWith('pelanggan')&&link.getAttribute('href')==='/pengaturan';link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=address;frame.dataset.pindahKerangka='1';doc.title=title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:address,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function adoptNative(doc){
  const current=document.querySelector('.bingkai'),ctx=current?.dataset.pindahKonteks,cap=document.documentElement.dataset.versi,token=document.getElementById('formulir-sesi')?.dataset.token,address=location.pathname+location.search;
  const remove=()=>{for(const old of document.querySelectorAll('#'+HOST+',[data-pengguna-native-catalog]'))old.remove();};
  if(!validData(data)||!frameBound(document,ctx,cap,token,address)||!frameBound(doc,ctx,cap,token,address))return false;
  const list=doc.querySelectorAll('#'+HOST),host=list[0];
  if(list.length!==1||host.tagName!=='SCRIPT'||host.type!=='application/json'||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>8192){remove();return false;}
  let permission;try{permission=JSON.parse(host.textContent);}catch(_){remove();return false;}
  if(!validPermission(permission,data,ctx,cap,token)){remove();return false;}
  const cats=doc.querySelectorAll('[data-pengguna-native-catalog]');let catalog=null;
  if(cats.length===1){
   const node=cats[0];let value;
   if(node.tagName==='SCRIPT'&&node.type==='application/json'&&node.textContent.length<=131072&&node.dataset.sourceAddress===address){try{value=JSON.parse(node.textContent);}catch(_){} }
   if(value&&validCatalog(value,data,ctx,cap,token,address)&&value.source_sha256===node.dataset.sourceSha)catalog=node;
  }
  remove();document.body.append(document.importNode(host,true));if(catalog)document.body.append(document.importNode(catalog,true));return true;
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 if(typeof module==='object'&&module.exports){module.exports={state,validData,validPermission,validCatalog,frameBound,visibleLink,stripNative};return;}
 global.PadiKerangkaPenggunaUI=Object.freeze({versi:1,sumber:data?.sumber,buat,adoptNative});
})(typeof window==='undefined'?globalThis:window);
