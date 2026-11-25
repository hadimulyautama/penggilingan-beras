/* Read-first facility parents; targets are presentation, never authorization. */
(function(global){
 'use strict';
 const TARGETS=['/pengaturan/gudang','/pengaturan/silo','/pengaturan/mesin','/pengaturan/jenis-proses'],TITLES=['Pengaturan gudang','Silo','Mesin & line produksi','Jenis proses'],HOST='padi-fasilitas-parent-kerangka';
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k);
 const exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k));
 const sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 function valid(data,p,ctx,cap,token){
  return exact(data,['versi','sumber','variants','styles','scripts'])&&data.versi===1&&sha(data.sumber)&&exact(data.variants,TARGETS)
   &&TARGETS.every((address,i)=>{const v=data.variants[address];return exact(v,['title','html','breadcrumb'])&&v.title===TITLES[i]&&typeof v.html==='string'&&v.html.length<=65536&&typeof v.breadcrumb==='string'&&v.breadcrumb.length<=65536;})
   &&['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=8&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144))
   &&exact(p,['versi','cap','konteks','sesi','sumber','targets'])&&p.versi===1&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===ctx&&p.sesi===token
   &&Array.isArray(p.targets)&&JSON.stringify(p.targets)===JSON.stringify(TARGETS)&&[ctx,cap,token].every(v=>typeof v==='string'&&v.length>0&&v.length<=2048);
 }
 function frameBound(doc,ctx,cap,token,address){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!session&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1
   &&frame.contains(main)&&frame.contains(session)&&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&session.dataset.token===token&&(address===undefined||frame.dataset.pindahAlamat===address);
 }
 // Root supplies its private native /barang-masuk registry prototype, not
 // a snapshot of the current Settings page. Its identity still must match.
 function prototypeBound(doc,ctx,cap,token){return frameBound(doc,ctx,cap,token,'/barang-masuk');}
 if(typeof module==='object'&&module.exports){module.exports={valid,frameBound,prototypeBound,TARGETS,TITLES};return;}
 const data=global.PadiKerangkaFasilitasParentData;
 function construct(target,base,ctx,cap,token){
  if(!TARGETS.includes(target)||typeof base!=='string'||base.length>8388608||!frameBound(document,ctx,cap,token,location.pathname+location.search))return null;
  if(document.body.hasAttribute('data-portal-akun')||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return null;
  const hosts=document.querySelectorAll('#'+HOST);if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>4096)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}if(!valid(data,p,ctx,cap,token))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');if(!prototypeBound(doc,ctx,cap,token))return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=data.variants[target].html;
  for(const [selector,pool,attr] of [['style[data-facility-parent-style]',data.styles,'data-facility-parent-style'],['script[data-facility-parent-script]',data.scripts,'data-facility-parent-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-fasilitas-parent-kerangka]');
  if(roots.length!==1||part.content.querySelector('form,[name],input[value],input[type=hidden],[data-post],[data-kirim],[data-pengaturan-form],[data-fasilitas],script[src],link[rel=stylesheet]'))return null;
  const root=roots[0];
  if([...root.querySelectorAll('input,select,textarea')].some(n=>!n.disabled)||[...root.querySelectorAll('input[type=checkbox]')].some(n=>n.checked||n.getAttribute('aria-checked')!=='mixed')||[...root.querySelectorAll('button:not([data-fp-retry])')].some(n=>!n.disabled||n.type!=='button'))return null;
  if([...root.querySelectorAll('a[href]')].some(a=>a.getAttribute('href')!=='/pengaturan'))return null;
  root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();
  const title=main.querySelector('.bar__merek');if(title){title.textContent=data.variants[target].title;title.setAttribute('aria-label',data.variants[target].title);}
  const top=main.querySelector('header.bar');if(!top)return null;
  const back=doc.createElement('a');back.className='bar__balik';back.setAttribute('href','/pengaturan');back.setAttribute('aria-label','Kembali');
  back.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"></path></svg>';
  const previous=top.querySelector('.bar__menu,.bar__balik');if(previous)previous.replaceWith(back);else top.prepend(back);
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const html=doc.createElement('template');html.innerHTML=data.variants[target].breadcrumb;crumb.replaceChildren(html.content);}
  for(const old of doc.querySelectorAll('#'+HOST+',#padi-fasilitas-detail-catalog'))old.remove();doc.body.append(doc.importNode(host,true));
  for(const link of doc.querySelectorAll('#laci a[href]')){const active=link.getAttribute('href')==='/pengaturan';link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title=data.variants[target].title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 global.PadiKerangkaFasilitasParentUI=Object.freeze({versi:1,sumber:data?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
