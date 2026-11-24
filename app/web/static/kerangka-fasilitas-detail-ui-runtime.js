/* First-click only from a visible, already-read native parent line link. */
(function(global){'use strict';
 const PARENT='/pengaturan/mesin',HOST='padi-fasilitas-detail-catalog',VARIANTS=['line','dryer'];
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k),exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k));
 const sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 function address(value){const m=typeof value==='string'&&/^\/pengaturan\/mesin\/([1-9][0-9]{0,9})$/.exec(value);return m&&Number(m[1])<=2147483647?{id:Number(m[1]),target:value}:null;}
 function valid(data,p,ctx,cap,token){
  return exact(data,['versi','sumber','parent_sha','variants','styles','scripts'])&&data.versi===1&&sha(data.sumber)&&sha(data.parent_sha)&&exact(data.variants,VARIANTS)
   &&VARIANTS.every(v=>exact(data.variants[v],['title','html','breadcrumb'])&&data.variants[v].title==='Mesin & line produksi'&&typeof data.variants[v].html==='string'&&data.variants[v].html.length<=65536&&typeof data.variants[v].breadcrumb==='string'&&data.variants[v].breadcrumb.length<=65536)
   &&['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=8&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144))
   &&exact(p,['versi','cap','konteks','sesi','sumber','source_address','sumber_sha256','entries'])&&p.versi===1&&p.sumber===data.sumber&&p.source_address===PARENT&&p.sumber_sha256===data.parent_sha&&p.cap===cap&&p.konteks===ctx&&p.sesi===token
   &&[ctx,cap,token].every(v=>typeof v==='string'&&v.length>0&&v.length<=2048)&&Array.isArray(p.entries)&&p.entries.length>0&&p.entries.length<=32&&new Set(p.entries.map(e=>e?.id)).size===p.entries.length
   &&p.entries.every(e=>exact(e,['id','label','variant','target'])&&Number.isInteger(e.id)&&e.id>0&&e.id<=2147483647&&typeof e.label==='string'&&e.label.length>0&&e.label.length<=100&&VARIANTS.includes(e.variant)&&address(e.target)?.id===e.id);
 }
 function shown(node,style){return !!node&&node.isConnected!==false&&!node.closest('[hidden],[inert],[aria-hidden="true"]')&&node.getClientRects().length>0&&!['hidden','collapse'].includes(style(node).visibility);}
 function visibleLink(doc,target,entry,style){
  const links=[...doc.querySelectorAll('#isi-halaman [data-fasilitas] .pg-grup a.pg-pintu[href]')].filter(a=>a.getAttribute('href')===target&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true'&&shown(a,style));
  if(links.length!==1)return false;const label=links[0].querySelector('.pg-pintu__isi strong');return !!label&&label.textContent===entry.label;
 }
 function frameBound(doc,ctx,cap,token,address){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!session&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1&&frame.contains(main)&&frame.contains(session)
   &&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&session.dataset.token===token&&(address===undefined||frame.dataset.pindahAlamat===address);
 }
 if(typeof module==='object'&&module.exports){module.exports={address,valid,shown,visibleLink,frameBound};return;}
 const data=global.PadiKerangkaFasilitasDetailData;
 function construct(target,base,ctx,cap,token){
  const state=address(target);if(!state||location.pathname+location.search!==PARENT||typeof base!=='string'||base.length>8388608||!frameBound(document,ctx,cap,token,PARENT))return null;
  if(document.body.hasAttribute('data-portal-akun')||document.querySelector('[data-editor-perintah],[data-kemas-ulang],[data-pengaturan-tinggalkan]'))return null;
  const hosts=document.querySelectorAll('#'+HOST);if(hosts.length!==1)return null;
  const host=hosts[0],currentMain=document.getElementById('isi-halaman');if(!host.isConnected||!currentMain.contains(host)||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.dataset.sourceAddress!==PARENT||host.textContent.length>16384)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}if(!valid(data,p,ctx,cap,token)||host.dataset.sourceSha!==data.parent_sha)return null;
  const entry=p.entries.find(e=>e.target===target&&e.id===state.id);if(!entry||!visibleLink(document,target,entry,n=>getComputedStyle(n)))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');if(!frameBound(doc,ctx,cap,token))return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const component=data.variants[entry.variant],part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attr] of [['style[data-facility-style]',data.styles,'data-facility-style'],['script[data-facility-script]',data.scripts,'data-facility-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-fasilitas-detail-kerangka]');
  if(roots.length!==1||part.content.querySelector('form,[name],input[value],input[type=hidden],[data-post],[data-kirim],[data-simpan-alat],[data-pengaturan-form],script[src],link[rel=stylesheet]'))return null;
  if([...part.content.querySelectorAll('input,select,textarea')].some(n=>!n.disabled)||[...part.content.querySelectorAll('button:not([data-fd-retry])')].some(n=>!n.disabled||n.type!=='button'))return null;
  const root=roots[0],heading=root.querySelector('[data-fd-label]');if(!heading)return null;heading.textContent=entry.label;root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  const bar=main.querySelector('.bar__merek');if(bar){bar.textContent=component.title;bar.setAttribute('aria-label',component.title);}
  const top=main.querySelector('header.bar');if(!top)return null;
  const back=doc.createElement('a');back.className='bar__balik';back.setAttribute('href',PARENT);back.setAttribute('aria-label','Kembali');back.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"></path></svg>';
  for(const old of top.querySelectorAll('.bar__menu,.bar__balik'))old.remove();top.prepend(back);
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const html=doc.createElement('template');html.innerHTML=component.breadcrumb;crumb.replaceChildren(html.content);}
  // Parent provenance is not a new detail catalog. No pending-resource chain.
  for(const old of doc.querySelectorAll('#'+HOST))old.remove();
  for(const link of doc.querySelectorAll('#laci a[href]')){const active=link.getAttribute('href')==='/pengaturan';link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title=component.title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 global.PadiKerangkaFasilitasDetailUI=Object.freeze({versi:1,sumber:data?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
