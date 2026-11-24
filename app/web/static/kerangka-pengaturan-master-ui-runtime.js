/* Fixed master layouts. Metadata is presentation, never authorization. */
(function(global){
 'use strict';
 const PATHS=['/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping'];
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
 const exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>Object.prototype.hasOwnProperty.call(x,k));
 const sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 function nativeAddress(value){return PATHS.includes(value)?value:null;}
 function valid(data,p,ctx,cap,token){
  return exact(data,['versi','sumber','variants','styles','scripts'])&&data.versi===1&&sha(data.sumber)
   &&exact(data.variants,PATHS)&&PATHS.every(path=>exact(data.variants[path],['title','html'])&&typeof data.variants[path].title==='string'&&typeof data.variants[path].html==='string'&&data.variants[path].html.length<=65536)
   &&['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=8&&Object.values(data[k]).every(s=>typeof s==='string'&&s.length<=262144))
   &&exact(p,['versi','cap','konteks','sesi','sumber','allowed'])&&p.versi===1&&p.allowed===true&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===ctx&&p.sesi===token
   &&[ctx,cap,token].every(v=>typeof v==='string'&&v.length>0&&v.length<=2048);
 }
 function frameBound(doc,ctx,cap,token,address){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!session&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1
   &&frame.contains(main)&&frame.contains(session)&&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&session.dataset.token===token
   &&(address===undefined||frame.dataset.pindahAlamat===address);
 }
 if(typeof module==='object'&&module.exports){module.exports={valid,nativeAddress,frameBound};return;}
 const data=global.PadiKerangkaPengaturanMasterData;
 function construct(target,base,ctx,cap,token){
  if(!nativeAddress(target)||typeof base!=='string'||base.length>8388608||!frameBound(document,ctx,cap,token,location.pathname+location.search))return null;
  // Do not transplant a loaded transaction/editor or a portal into a reader.
  if(document.body.hasAttribute('data-portal-akun')||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return null;
  const hosts=document.querySelectorAll('#padi-pengaturan-master-kerangka');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>4096)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}
  if(!valid(data,p,ctx,cap,token))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');if(!frameBound(doc,ctx,cap,token))return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=data.variants[target].html;
  for(const [selector,pool,attr] of [['style[data-master-style]',data.styles,'data-master-style'],['script[data-master-script]',data.scripts,'data-master-script']])for(const node of part.content.querySelectorAll(selector)){
   const key=node.getAttribute(attr);if(!Object.prototype.hasOwnProperty.call(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);
  }
  const roots=part.content.querySelectorAll('[data-pengaturan-master-kerangka]');
  if(roots.length!==1||part.content.querySelector('form,[name],input[type=hidden],[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;
  if([...part.content.querySelectorAll('input,select,textarea')].some(n=>!n.disabled)||[...part.content.querySelectorAll('button:not([data-master-native-retry])')].some(n=>!n.disabled||n.type!=='button'))return null;
  const root=roots[0];root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();
  const title=main.querySelector('.bar__merek');if(title){title.textContent=data.variants[target].title;title.setAttribute('aria-label',data.variants[target].title);}
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const a=doc.createElement('a'),name=doc.createElement('strong');a.href='/pengaturan';a.textContent='Pengaturan';name.textContent=data.variants[target].title;crumb.replaceChildren(a,doc.createTextNode(' › '),name);}
  for(const old of doc.querySelectorAll('#padi-pengaturan-master-kerangka'))old.remove();doc.body.append(doc.importNode(host,true));
  for(const link of doc.querySelectorAll('#laci a[href]')){const active=link.getAttribute('href')==='/pengaturan';link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title=data.variants[target].title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 global.PadiKerangkaPengaturanMasterUI=Object.freeze({versi:1,sumber:data?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
