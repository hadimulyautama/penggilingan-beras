/* A fixed native link hub; only independently verified super targets admit it. */
(function(global){
 'use strict';
 const ADDRESS='/pengaturan/alat',HOST='padi-pengaturan-alat-kerangka';
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k);
 const exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k));
 const sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 function valid(data,p,ctx,cap,token){
  return exact(data,['versi','sumber','variants','styles','scripts'])&&data.versi===1&&sha(data.sumber)&&exact(data.variants,[ADDRESS])
   &&exact(data.variants[ADDRESS],['title','html'])&&typeof data.variants[ADDRESS].html==='string'&&data.variants[ADDRESS].html.length<=32768&&data.variants[ADDRESS].title==='Pengaturan alat'
   &&['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=8&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144))
   &&exact(p,['versi','cap','konteks','sesi','sumber','targets'])&&p.versi===1&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===ctx&&p.sesi===token
   &&Array.isArray(p.targets)&&p.targets.length===1&&p.targets[0]===ADDRESS&&[ctx,cap,token].every(v=>typeof v==='string'&&v.length>0&&v.length<=2048);
 }
 function frameBound(doc,ctx,cap,token,address){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!session&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1
   &&frame.contains(main)&&frame.contains(session)&&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&session.dataset.token===token&&(address===undefined||frame.dataset.pindahAlamat===address);
 }
 if(typeof module==='object'&&module.exports){module.exports={valid,frameBound};return;}
 const data=global.PadiKerangkaPengaturanAlatData;
 function construct(target,base,ctx,cap,token){
  if(target!==ADDRESS||typeof base!=='string'||base.length>8388608||!frameBound(document,ctx,cap,token,location.pathname+location.search))return null;
  if(document.body.hasAttribute('data-portal-akun')||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return null;
  const hosts=document.querySelectorAll('#'+HOST);if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>4096)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}if(!valid(data,p,ctx,cap,token))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');if(!frameBound(doc,ctx,cap,token))return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=data.variants[ADDRESS].html;
  for(const [selector,pool,attr] of [['style[data-alat-style]',data.styles,'data-alat-style'],['script[data-alat-script]',data.scripts,'data-alat-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-pengaturan-alat-kerangka]');
  if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[name],[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;
  const root=roots[0],links=[...root.querySelectorAll('a[href]')].map(a=>a.getAttribute('href'));
  if(JSON.stringify(links)!==JSON.stringify(['/pengaturan/mesin','/pengaturan/silo','/pengaturan/sebab-berhenti']))return null;
  root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();
  const title=main.querySelector('.bar__merek');if(title){title.textContent='Pengaturan alat';title.setAttribute('aria-label','Pengaturan alat');}
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const a=doc.createElement('a'),name=doc.createElement('strong');a.href='/pengaturan';a.textContent='Pengaturan';name.textContent='Pengaturan alat';crumb.replaceChildren(a,doc.createTextNode(' › '),name);}
  for(const old of doc.querySelectorAll('#'+HOST))old.remove();doc.body.append(doc.importNode(host,true));
  for(const link of doc.querySelectorAll('#laci a[href]')){const active=link.getAttribute('href')==='/pengaturan';link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title='Pengaturan alat · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 global.PadiKerangkaPengaturanAlatUI=Object.freeze({versi:1,sumber:data?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
