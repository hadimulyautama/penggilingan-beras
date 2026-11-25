/* First-click customer layout: private native provenance is not a grant. */
(function(global){
 'use strict';
 const TABS=['ringkasan','penerimaan','proses','stok','pengambilan'];
 const KEYS=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status','rincian_halaman','rincian_cari'];
 const STATUS=['','berjalan','selesai','dibatalkan','digabung'];
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k);
 const exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k));
 const sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//'))return null;
  let u;try{u=new URL(value,origin);}catch(_){return null;}
  const q=u.searchParams,m=u.pathname.match(/^\/jasa\/pelanggan\/([1-9][0-9]{0,9})$/);
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||!m||Number(m[1])>2147483647||u.search.length>3001||/%(?![0-9a-fA-F]{2})/.test(u.search))return null;
  if([...q.keys()].some(k=>!KEYS.includes(k)||q.getAll(k).length!==1)||!TABS.includes(q.has('tab')?q.get('tab'):'ringkasan'))return null;
  if(['status','pesanan_status'].some(k=>!STATUS.includes(q.get(k)||''))||['cari','pesanan_cari','rincian_cari'].some(k=>(q.get(k)||'').length>200))return null;
  if(['halaman','pesanan_halaman','rincian_halaman'].some(k=>{const v=q.get(k)||'';return v&&(!/^[1-9][0-9]{0,9}$/.test(v)||Number(v)>2147483647);})||[...q].some(([k,v])=>k.includes('\uFFFD')||v.includes('\uFFFD')))return null;
  return {u,pid:Number(m[1]),tab:q.get('tab')||'ringkasan'};
 }
 function valid(data,p,ctx,cap,token,sourceSha,origin){
  if(!exact(data,['versi','sumber','variants','styles','scripts'])||data.versi!==1||!sha(data.sumber)||!exact(data.variants,TABS)
   ||!TABS.every(k=>exact(data.variants[k],['title','html','breadcrumb'])&&data.variants[k].title==='__PADI_JASA_LABEL__ · Pesanan Jasa'&&typeof data.variants[k].html==='string'&&data.variants[k].html.length<=131072&&typeof data.variants[k].breadcrumb==='string'&&data.variants[k].breadcrumb.length<=65536)
   ||!['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=16&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144))
   ||!exact(p,['versi','cap','konteks','sesi','sumber','source_address','sumber_sha256','mode','entries'])||p.versi!==1||p.sumber!==data.sumber||p.cap!==cap||p.konteks!==ctx||p.sesi!==token
   ||![ctx,cap,token].every(v=>typeof v==='string'&&v&&v.length<=2048)||!sha(sourceSha)||p.sumber_sha256!==sourceSha||typeof p.source_address!=='string'||p.source_address.length>4096
   ||!['list','detail'].includes(p.mode)||!Array.isArray(p.entries)||!p.entries.length||p.entries.length>(p.mode==='list'?25:1))return false;
  let source;try{source=new URL(p.source_address,origin);}catch(_){return false;}
  if(source.origin!==origin||source.hash||source.pathname+source.search!==p.source_address||p.mode==='list'&&source.pathname!=='/jasa'||p.mode==='detail'&&!address(p.source_address,origin))return false;
  if(new Set(p.entries.map(e=>e?.id)).size!==p.entries.length)return false;
  return p.entries.every(e=>exact(e,['id','label','filter','targets'])&&Number.isInteger(e.id)&&e.id>0&&e.id<=2147483647&&typeof e.label==='string'&&e.label.length>0&&e.label.length<=200&&typeof e.filter==='boolean'
   &&Array.isArray(e.targets)&&e.targets.length===(p.mode==='list'?1:5)&&new Set(e.targets).size===e.targets.length&&e.targets.every(t=>address(t,origin)?.pid===e.id)
   &&(p.mode!=='detail'||new Set(e.targets.map(t=>address(t,origin).tab)).size===5)
   &&(p.mode!=='detail'||address(p.source_address,origin).pid===e.id));
 }
 function pendingStamp(ctx,target,pid,originSha){return ctx+'|'+target+'|'+pid+'|'+originSha;}
 function selectProvenance(p,target,source,ctx,proof,origin){
  const state=address(target,origin);if(!state||!obj(proof)||proof.visible!==true||proof.href!==target)return null;
  const entry=p?.entries?.find(e=>e.id===state.pid);if(!entry||proof.label!==entry.label)return null;
  if(proof.kind==='pending'){
   const current=address(source,origin);
   if(!current||current.pid!==entry.id||proof.pid!==entry.id||proof.url!==source||proof.originSha!==p.sumber_sha256
    ||!entry.targets.includes(proof.originTarget)||proof.stamp!==pendingStamp(ctx,source,entry.id,p.sumber_sha256))return null;
   return {state,entry,originTarget:proof.originTarget};
  }
  if(source!==p.source_address||!entry.targets.includes(target)||proof.kind!==p.mode)return null;
  if(p.mode==='detail'&&address(source,origin)?.pid!==entry.id)return null;
  return {state,entry,originTarget:target};
 }
 function shown(node,style){return !!node&&node.isConnected!==false&&!node.closest('[hidden],[inert],[aria-hidden="true"]')&&node.getClientRects().length>0&&!['hidden','collapse'].includes(style(node).visibility);}
 function proofFromDOM(p,target,source,doc,style,origin){
  const normalized=link=>{try{const u=new URL(link.getAttribute('href'),origin+source);return u.origin===origin&&!u.hash?u.pathname+u.search:null;}catch(_){return null;}};
  const eligible=link=>normalized(link)===target&&!link.hasAttribute('target')&&!link.hasAttribute('download')&&link.getAttribute('aria-disabled')!=='true'&&shown(link,style);
  const pending=doc.querySelectorAll('[data-jasa-detail-kerangka]');
  if(pending.length){
   if(pending.length!==1)return null;const root=pending[0],links=[...root.querySelectorAll('.jasa-detail-tab>a[href]')].filter(eligible),heading=root.querySelector('.jasa-kontrol h1');
   const main=doc.getElementById('isi-halaman');
   if(!main||!main.contains(root)||!shown(root,style)||links.length!==1||!heading)return null;
   return {kind:'pending',visible:true,href:target,label:heading.textContent,pid:Number(root.dataset.jdPid),url:root.dataset.url,originSha:root.dataset.jdOriginSha,originTarget:root.dataset.jdOriginTarget,stamp:root.dataset.stamp};
  }
  if(p.mode==='list'){
   const rows=[...doc.querySelectorAll('#isi-halaman .jasa-daftar>a.jasa-pelanggan[href]')].filter(eligible);if(rows.length!==1)return null;
   const heading=rows[0].querySelector('.baris h2');return heading?{kind:'list',visible:true,href:target,label:heading.textContent}:null;
  }
  const links=[...doc.querySelectorAll('#isi-halaman .jasa-detail-tab>a[href]')].filter(eligible),heading=doc.querySelector('#isi-halaman .jasa-kontrol h1');
  return links.length===1&&heading?{kind:'detail',visible:true,href:target,label:heading.textContent}:null;
 }
 function tabURL(state,key){
  const q=state.u.searchParams,next=new URL(state.u.pathname,state.u.origin);
  for(const [k,v] of [['tab',key],['status',q.get('status')||''],['cari',q.get('cari')||''],['halaman',q.get('halaman')||'']])next.searchParams.set(k,v);
  for(const [k,v] of q)if(k.startsWith('pesanan_'))next.searchParams.set(k,v);
  return next.pathname+next.search;
 }
 function nativeTitle(label){return (label+' · Pesanan Jasa').trim();}
 function backURL(state){
  const q=new URLSearchParams();for(const [key,value] of state.u.searchParams)if(['status','cari','halaman'].includes(key))q.append(key,value);
  // Python native urlencode preserves input order and encodes '*' as well.
  return '/jasa?'+q.toString().replace(/\*/g,'%2A');
 }
 function bindBreadcrumb(fragment,label,back){
  const links=[...fragment.querySelectorAll('a[href]')].filter(a=>a.getAttribute('href')==='/jasa?__PADI_BACK_QUERY__'),leaves=fragment.querySelectorAll('[aria-current="page"]');
  if(links.length!==2||leaves.length!==1||leaves[0].textContent!=='__PADI_JASA_LABEL__ · Pesanan Jasa')return false;
  // Native breadcrumb.susun collapses whitespace. Set text/href via DOM only,
  // never interpolate a private name or a filter into HTML program strings.
  leaves[0].textContent=nativeTitle(label).replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g,' ').trim();
  for(const link of links)link.setAttribute('href',back);return true;
 }
 function blockedSource(doc,hash=''){
  if(hash)return true;
  if(doc.body?.hasAttribute('data-portal-akun')||doc.body?.classList.contains('portal-customer')||doc.querySelector('[data-editor-perintah],[data-kemas-ulang]'))return true;
  const dialog=doc.getElementById('lembar');return !!dialog&&(dialog.open||dialog.style?.display==='flex');
 }
 function catalogFromRead(data,doc,live,source,origin){
  const frame=live.querySelector('.bingkai'),main=live.getElementById('isi-halaman'),session=live.getElementById('formulir-sesi');
  const freshFrame=doc.querySelector('.bingkai'),freshMain=doc.getElementById('isi-halaman'),freshSession=doc.getElementById('formulir-sesi');
  if(![live,doc].every(d=>['.bingkai','#isi-halaman','#formulir-sesi'].every(s=>d.querySelectorAll(s).length===1))
   ||!frame?.contains(main)||!frame.contains(session)||!freshFrame?.contains(freshMain)||!freshFrame.contains(freshSession)
   ||frame.dataset.pindahAlamat!==source||freshFrame.dataset.pindahAlamat!==source)return null;
  const cap=live.documentElement.dataset.versi,ctx=frame.dataset.pindahKonteks,token=session.dataset.token;
  if(doc.documentElement.dataset.versi!==cap||freshFrame.dataset.pindahKonteks!==ctx||freshSession.dataset.token!==token)return null;
  const hosts=doc.querySelectorAll('#padi-jasa-detail-catalog');if(hosts.length!==1)return null;
  const host=hosts[0],attributes=['type','id','data-cap','data-konteks','data-source-address','data-source-sha'];
  if(host.tagName!=='SCRIPT'||host.getAttribute('type')!=='application/json'||host.attributes.length!==attributes.length
   ||!attributes.every(k=>host.hasAttribute(k))||!freshMain.contains(host)||host.textContent.length>262144)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}
  if(!valid(data,p,ctx,cap,token,host.dataset.sourceSha,origin)||p.mode!=='list'||p.source_address!==source
   ||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.dataset.sourceAddress!==source)return null;
  // Inert current-read metadata only. Visible-link proof and server authority
  // are still checked by the existing factory and the native detail request.
  return host.cloneNode(true);
 }
 if(typeof module==='object'&&module.exports){module.exports={address,valid,pendingStamp,selectProvenance,shown,proofFromDOM,tabURL,blockedSource,nativeTitle,backURL,bindBreadcrumb,catalogFromRead};return;}
 const data=global.PadiKerangkaJasaDetailData;
 function construct(target,base,ctx,cap,token){
  if(typeof base!=='string'||base.length>8388608||!address(target,location.origin)||blockedSource(document,location.hash))return null;
  const source=location.pathname+location.search,currentFrame=document.querySelector('.bingkai'),currentMain=document.getElementById('isi-halaman'),currentSession=document.getElementById('formulir-sesi');
  if(document.querySelectorAll('.bingkai').length!==1||document.querySelectorAll('#isi-halaman').length!==1||document.querySelectorAll('#formulir-sesi').length!==1||!currentFrame.contains(currentMain)||!currentFrame.contains(currentSession)||currentFrame.dataset.pindahAlamat!==source||currentFrame.dataset.pindahKonteks!==ctx||document.documentElement.dataset.versi!==cap||currentSession.dataset.token!==token)return null;
  const hosts=document.querySelectorAll('#padi-jasa-detail-catalog');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||!currentMain.contains(host)||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>262144)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}
  if(!valid(data,p,ctx,cap,token,host.dataset.sourceSha,location.origin)||host.dataset.sourceAddress!==p.source_address)return null;
  const proof=proofFromDOM(p,target,source,document,n=>getComputedStyle(n),location.origin),selection=selectProvenance(p,target,source,ctx,proof,location.origin);if(!selection)return null;
  const {state,entry,originTarget}=selection,doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==ctx||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=data.variants[state.tab].html;
  for(const [selector,pool,attr] of [['style[data-jd-style]',data.styles,'data-jd-style'],['script[data-jd-script]',data.scripts,'data-jd-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-jasa-detail-kerangka]');if(roots.length!==1||part.content.querySelector('form,input[name],input[type=hidden],[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;
  const root=roots[0],q=state.u.searchParams,heading=root.querySelector('.jasa-kontrol h1');
  if(!heading||root.querySelectorAll('[data-jd-tab]').length!==5||!root.querySelector('.jasa-kembali'))return null;
  root.dataset.url=target;root.dataset.stamp=pendingStamp(ctx,target,entry.id,p.sumber_sha256);root.dataset.jdPid=String(entry.id);root.dataset.jdOriginSha=p.sumber_sha256;root.dataset.jdOriginTarget=originTarget;
  heading.textContent=entry.label;
  for(const tab of root.querySelectorAll('[data-jd-tab]'))tab.setAttribute('href',tabURL(state,tab.dataset.jdTab));
  const back=backURL(state);root.querySelector('.jasa-kembali').setAttribute('href',back);
  if(!entry.filter&&!(q.get('pesanan_cari')||q.get('pesanan_status')))root.querySelector('[data-jd-order-filter]')?.remove();
  for(const [selector,key] of [['[data-jd-order-search]','pesanan_cari'],['[data-jd-detail-search]','rincian_cari']])for(const node of root.querySelectorAll(selector))node.setAttribute('value',(q.get(key)||'').trim());
  for(const option of root.querySelectorAll('[data-jd-order-status] option'))option.toggleAttribute('selected',option.value===(q.get('pesanan_status')||''));
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  for(const old of doc.querySelectorAll('#padi-jasa-detail-catalog'))old.remove();ends[0].before(doc.importNode(host,true));
  const title=nativeTitle(entry.label),bar=main.querySelector('.bar__merek');if(bar){bar.textContent=title;bar.setAttribute('aria-label',title);}
  const top=main.querySelector('header.bar');if(!top)return null;
  const backLink=doc.createElement('a');backLink.className='bar__balik';backLink.setAttribute('href',back);backLink.setAttribute('aria-label','Kembali');
  backLink.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"></path></svg>';
  const oldBack=top.querySelector('.bar__menu,.bar__balik');if(oldBack)oldBack.replaceWith(backLink);else top.prepend(backLink);
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const html=doc.createElement('template');html.innerHTML=data.variants[state.tab].breadcrumb;if(!bindBreadcrumb(html.content,entry.label,back))return null;crumb.replaceChildren(html.content);}
  for(const link of doc.querySelectorAll('#laci a[href]')){const active=new URL(link.getAttribute('href'),location.href).pathname==='/jasa';link.classList.toggle('pintu--kini',active&&link.classList.contains('pintu'));link.classList.toggle('pintu-sub__satu--kini',active&&link.classList.contains('pintu-sub__satu'));if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title=title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 function buat(...args){try{return construct(...args);}catch(_){return null;}}
 global.PadiKerangkaJasaDetailUI=Object.freeze({versi:1,sumber:data?.sumber,buat,
  readCatalog:doc=>catalogFromRead(data,doc,document,location.pathname+location.search,location.origin)});
})(typeof window==='undefined'?globalThis:window);
