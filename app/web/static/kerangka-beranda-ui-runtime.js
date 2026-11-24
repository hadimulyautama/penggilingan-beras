/* Home program layout only; greeting/scope comes from one private document. */
(function(global){'use strict';
 const HOST='padi-beranda-kerangka',ADDRESS='/',obj=v=>!!v&&typeof v==='object'&&!Array.isArray(v),own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k),exact=(v,keys)=>obj(v)&&Object.keys(v).length===keys.length&&keys.every(k=>own(v,k));
 const text=v=>typeof v==='string'&&v.length>0&&v.length<=256,sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
 function references(r){return exact(r,['sapaan','tanggal','scope','semua_gudang'])&&['sapaan','tanggal','scope'].every(k=>text(r[k]))&&typeof r.semua_gudang==='boolean'&&(r.semua_gudang?r.scope==='Semua gudang':['Gudang 1 · Selepan','Gudang 2 · Penyosohan','Belum punya gudang'].includes(r.scope));}
 function valid(data,p,ctx,cap,token){
  return exact(data,['versi','sumber','variants','scripts'])&&data.versi===1&&sha(data.sumber)&&exact(data.variants,[ADDRESS])
   &&exact(data.variants[ADDRESS],['title','brand','html','breadcrumb'])&&data.variants[ADDRESS].title==='Beranda'&&data.variants[ADDRESS].brand==='PT Hadi Mulya Utama'&&typeof data.variants[ADDRESS].html==='string'&&data.variants[ADDRESS].html.length<=65536&&typeof data.variants[ADDRESS].breadcrumb==='string'&&data.variants[ADDRESS].breadcrumb.length<=65536
   &&obj(data.scripts)&&Object.keys(data.scripts).length<=4&&Object.values(data.scripts).every(v=>typeof v==='string'&&v.length<=262144)
   &&exact(p,['versi','sumber','cap','konteks','sesi','references'])&&p.versi===1&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===ctx&&p.sesi===token&&references(p.references)
   &&[ctx,cap,token].every(v=>typeof v==='string'&&v.length>0&&v.length<=2048);
 }
 function frameBound(doc,ctx,cap,token,address){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!session&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1&&frame.contains(main)&&frame.contains(session)
   &&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&session.dataset.token===token&&(address===undefined||frame.dataset.pindahAlamat===address);
 }
 if(typeof module==='object'&&module.exports){module.exports={references,valid,frameBound};return;}
 const data=global.PadiKerangkaBerandaData;
 function construct(target,base,ctx,cap,token){
  if(target!==ADDRESS||typeof base!=='string'||base.length>8388608||!frameBound(document,ctx,cap,token,location.pathname+location.search))return null;
  if(document.body.hasAttribute('data-portal-akun')||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return null;
  const hosts=document.querySelectorAll('#'+HOST);if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>4096)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}if(!valid(data,p,ctx,cap,token))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');if(!frameBound(doc,ctx,cap,token,'/barang-masuk'))return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const v=data.variants[ADDRESS],part=doc.createElement('template');part.innerHTML=v.html;
  for(const n of part.content.querySelectorAll('script[data-home-script]')){const key=n.getAttribute('data-home-script');if(!own(data.scripts,key))return null;n.textContent=data.scripts[key];n.removeAttribute('data-home-script');}
  const roots=part.content.querySelectorAll('[data-beranda-native]');
  if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[name],[data-post],[data-kirim],script[src],link[rel=stylesheet],iframe'))return null;
  const root=roots[0];root.dataset.url=ADDRESS;root.dataset.stamp=ctx+'|'+ADDRESS;
  for(const [selector,key]of[['[data-home-greeting]','sapaan'],['[data-home-date]','tanggal'],['[data-home-scope]','scope']]){const n=root.querySelector(selector);if(!n)return null;n.textContent=p.references[key];}
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  const brand=main.querySelector('.bar__merek');if(!brand)return null;brand.textContent=v.brand;brand.setAttribute('aria-label',v.brand);
  // The bound top-level BM prototype has the native menu button. Do not
  // invent an alternative back path or retain another family's back link.
  if(!main.querySelector('header.bar #buka-laci.bar__menu'))return null;
  for(const old of main.querySelectorAll('.desktop-back,a.bar__balik'))old.remove();
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const t=doc.createElement('template');t.innerHTML=v.breadcrumb;crumb.replaceChildren(t.content);}
  for(const old of doc.querySelectorAll('#'+HOST))old.remove();doc.body.append(doc.importNode(host,true));
  for(const a of doc.querySelectorAll('#laci a[href]')){const active=a.getAttribute('href')===ADDRESS;a.classList.toggle('pintu--kini',active&&a.classList.contains('pintu'));a.classList.toggle('pintu-sub__satu--kini',active&&a.classList.contains('pintu-sub__satu'));if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=ADDRESS;frame.dataset.pindahKerangka='1';doc.title='Beranda · PT Hadi Mulya Utama';
  return {versi:1,alamat:ADDRESS,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 global.PadiKerangkaBerandaUI=Object.freeze({versi:1,sumber:data?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
