/* Fixed native detail structures; private actual predicates choose variants. */
(function(global){
 'use strict';
 const CHOICES={'/pengaturan/peran':['peran-lihat','peran-gudang'],'/pengaturan/akses':['akses'],'/pengaturan/sebab-berhenti':['sebab-berhenti'],'/pengaturan/mutu':['mutu'],'/pengaturan/kledo':['kledo'],'/pengaturan/sistem':['sistem-admin','sistem-umum']};
 const VARIANTS=Object.values(CHOICES).flat(),HOST='padi-pengaturan-detail-kerangka';
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k),exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k));
 const text=x=>typeof x==='string'&&x.length>0&&x.length<=200;
 function valid(data,p,ctx,cap,token){
  return exact(data,['versi','sumber','variants','styles','scripts','references'])&&data.versi===1&&typeof data.sumber==='string'&&/^[a-f0-9]{64}$/.test(data.sumber)
   &&exact(data.variants,VARIANTS)&&VARIANTS.every(v=>exact(data.variants[v],['title','html','breadcrumb'])&&data.variants[v].title==='Pengaturan'&&typeof data.variants[v].html==='string'&&data.variants[v].html.length<=65536&&typeof data.variants[v].breadcrumb==='string'&&data.variants[v].breadcrumb.length<=65536)
   &&['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=8&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144))
   &&exact(data.references,['columns','processes'])&&Array.isArray(data.references.columns)&&data.references.columns.length>0&&data.references.columns.length<=16&&data.references.columns.every(text)
   &&Array.isArray(data.references.processes)&&data.references.processes.length>0&&data.references.processes.length<=16&&data.references.processes.every(row=>Array.isArray(row)&&row.length===2&&row.every(text))
   &&exact(p,['versi','cap','konteks','sesi','sumber','targets','columns','processes'])&&p.versi===1&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===ctx&&p.sesi===token
   &&[ctx,cap,token].every(v=>typeof v==='string'&&v.length>0&&v.length<=2048)&&obj(p.targets)&&Object.keys(p.targets).length>0&&Object.keys(p.targets).length<=6
   &&Object.entries(p.targets).every(([path,variant])=>own(CHOICES,path)&&CHOICES[path].includes(variant))
   &&JSON.stringify(p.columns)===JSON.stringify(data.references.columns)&&JSON.stringify(p.processes)===JSON.stringify(data.references.processes);
 }
 function frameBound(doc,ctx,cap,token,address){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!session&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1&&frame.contains(main)&&frame.contains(session)
   &&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&session.dataset.token===token&&(address===undefined||frame.dataset.pindahAlamat===address);
 }
 if(typeof module==='object'&&module.exports){module.exports={valid,frameBound,choices:CHOICES};return;}
 const data=global.PadiKerangkaPengaturanDetailData;
 function construct(target,base,ctx,cap,token){
  if(!own(CHOICES,target)||typeof base!=='string'||base.length>8388608||!frameBound(document,ctx,cap,token,location.pathname+location.search))return null;
  if(document.body.hasAttribute('data-portal-akun')||document.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return null;
  const hosts=document.querySelectorAll('#'+HOST);if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>16384)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}if(!valid(data,p,ctx,cap,token)||!own(p.targets,target))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');if(!frameBound(doc,ctx,cap,token))return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const component=data.variants[p.targets[target]],part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attr] of [['style[data-settings-detail-style]',data.styles,'data-settings-detail-style'],['script[data-settings-detail-script]',data.scripts,'data-settings-detail-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-pengaturan-detail-kerangka]');
  if(roots.length!==1||part.content.querySelector('form,[name],input[type=hidden],[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;
  if([...part.content.querySelectorAll('input,select,textarea')].some(n=>!n.disabled)||[...part.content.querySelectorAll('button:not([data-pengaturan-detail-retry])')].some(n=>!n.disabled||n.type!=='button'))return null;
  roots[0].dataset.url=target;roots[0].dataset.stamp=ctx+'|'+target;
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  const title=main.querySelector('.bar__merek');if(title){title.textContent='Pengaturan';title.setAttribute('aria-label','Pengaturan');}
  const top=main.querySelector('header.bar');if(!top)return null;
  const menu=doc.createElement('button');menu.className='bar__menu';menu.type='button';menu.id='buka-laci';menu.setAttribute('aria-label','Buka menu');menu.setAttribute('aria-controls','laci');menu.setAttribute('aria-expanded','false');
  menu.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"></path></svg>';
  for(const old of top.querySelectorAll('.bar__menu,.bar__balik'))old.remove();top.prepend(menu);
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const html=doc.createElement('template');html.innerHTML=component.breadcrumb;crumb.replaceChildren(html.content);}
  for(const old of doc.querySelectorAll('#'+HOST))old.remove();doc.body.append(doc.importNode(host,true));
  for(const link of doc.querySelectorAll('#laci a[href]')){const active=link.getAttribute('href')==='/pengaturan';link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title='Pengaturan · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 global.PadiKerangkaPengaturanDetailUI=Object.freeze({versi:1,sumber:data?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
