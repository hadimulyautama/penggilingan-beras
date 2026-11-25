/* Canonical inert Muatan layout. Actual native predicate outcome stays private. */
(function(global){'use strict';
 const HOST='padi-muatan-kerangka',ADDRESS='/muatan',obj=v=>!!v&&typeof v==='object'&&!Array.isArray(v),own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k),exact=(v,keys)=>obj(v)&&Object.keys(v).length===keys.length&&keys.every(k=>own(v,k));
 const sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v),small=v=>typeof v==='string'&&v.length<=65536;
 function permission(p){return exact(p,['can_record'])&&typeof p.can_record==='boolean';}
 function variant(v){return exact(v,['title','brand','read','record','breadcrumbs'])&&v.title==='Catat muatan'&&v.brand==='Catat muatan'&&small(v.read)&&small(v.record)&&exact(v.breadcrumbs,['/muatan','/barang-keluar'])&&Object.values(v.breadcrumbs).every(small);}
 function valid(data,p,ctx,cap,token){
  return exact(data,['versi','sumber','variants','scripts','styles'])&&data.versi===1&&sha(data.sumber)&&exact(data.variants,[ADDRESS])&&variant(data.variants[ADDRESS])
   &&obj(data.scripts)&&Object.keys(data.scripts).length<=4&&Object.values(data.scripts).every(v=>typeof v==='string'&&v.length<=262144)
   &&obj(data.styles)&&Object.keys(data.styles).length<=4&&Object.values(data.styles).every(v=>typeof v==='string'&&v.length<=65536)
   &&exact(p,['versi','sumber','cap','konteks','sesi','permission'])&&p.versi===1&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===ctx&&p.sesi===token&&permission(p.permission)
   &&[ctx,cap,token].every(v=>typeof v==='string'&&v.length>0&&v.length<=2048);
 }
 function frameBound(doc,ctx,cap,token,address){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!session&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1&&frame.contains(main)&&frame.contains(session)
   &&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&session.dataset.token===token&&(address===undefined||frame.dataset.pindahAlamat===address);
 }
 // This chooses only native presentation from the already-bound actual menu,
 // never a permission. Missing/ambiguous menu makes the factory decline.
 function navigationParent(doc){const links=doc.querySelectorAll('#laci a.pintu[href="/muatan"],#laci a.pintu[href="/barang-keluar"]');return links.length===1?links[0].getAttribute('href'):null;}
 if(typeof module==='object'&&module.exports){module.exports={permission,variant,valid,frameBound,navigationParent};return;}
 const data=global.PadiKerangkaMuatanData;
 function construct(target,base,ctx,cap,token){
  if(target!==ADDRESS||typeof base!=='string'||base.length>8388608||!frameBound(document,ctx,cap,token,location.pathname+location.search))return null;
  if(document.body.hasAttribute('data-portal-akun')||document.body.classList.contains('portal-customer')||document.querySelector('[data-editor-perintah],[data-kemas-ulang],dialog[open]'))return null;
  const hosts=document.querySelectorAll('#'+HOST);if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>4096)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}if(!valid(data,p,ctx,cap,token))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');if(!frameBound(doc,ctx,cap,token,'/barang-masuk'))return null;
  const parent=navigationParent(doc);if(!parent)return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const v=data.variants[ADDRESS],part=doc.createElement('template');part.innerHTML=p.permission.can_record?v.record:v.read;
  for(const [selector,pool,attribute] of [['script[data-muat-script]',data.scripts,'data-muat-script'],['style[data-muat-style]',data.styles,'data-muat-style']])for(const n of part.content.querySelectorAll(selector)){const key=n.getAttribute(attribute);if(!own(pool,key))return null;n.textContent=pool[key];n.removeAttribute(attribute);}
  const roots=part.content.querySelectorAll('[data-muatan-native]');
  if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[name],[data-post],[data-kirim],[data-editor-perintah],[data-lembar-muatan],[data-catat-muatan],#lembar-awal,script[src],link[rel=stylesheet],iframe'))return null;
  if([...part.content.querySelectorAll('button:not([data-muat-native-retry])')].some(b=>!b.disabled))return null;
  const root=roots[0];root.dataset.url=ADDRESS;root.dataset.stamp=ctx+'|'+ADDRESS;
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  const brand=main.querySelector('.bar__merek');if(!brand||!main.querySelector('header.bar #buka-laci.bar__menu'))return null;brand.textContent=v.brand;brand.setAttribute('aria-label',v.brand);
  for(const old of main.querySelectorAll('.desktop-back,a.bar__balik'))old.remove();
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(!crumb)return null;const t=doc.createElement('template');t.innerHTML=v.breadcrumbs[parent];crumb.replaceChildren(t.content);
  for(const old of doc.querySelectorAll('#'+HOST))old.remove();doc.body.append(doc.importNode(host,true));
  for(const a of doc.querySelectorAll('#laci a[href]')){const active=a.getAttribute('href')===ADDRESS;a.classList.toggle('pintu--kini',active&&a.classList.contains('pintu'));a.classList.toggle('pintu-sub__satu--kini',active&&a.classList.contains('pintu-sub__satu'));if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=ADDRESS;frame.dataset.pindahKerangka='1';doc.title='Catat muatan · PT Hadi Mulya Utama';
  return {versi:1,alamat:ADDRESS,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 global.PadiKerangkaMuatanUI=Object.freeze({versi:1,sumber:data?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
