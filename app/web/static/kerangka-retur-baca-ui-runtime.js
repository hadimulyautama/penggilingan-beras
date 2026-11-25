/* Staff return READ frames; actual GET remains the authority for all records. */
(function(global){'use strict';
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k),exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k));
 const sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x),TABS=['ringkasan','barang','tiket','riwayat'];
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.length>4096||/[\\\x00-\x1f]/.test(value))return null;
  let u;try{u=new URL(value,origin);}catch(_){return null;}const pairs=[...u.searchParams],q=u.searchParams,positive=v=>typeof v==='string'&&/^[1-9][0-9]{0,9}$/.test(v)&&Number(v)<=2147483647;
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||pairs.length>3||new Set(pairs.map(p=>p[0])).size!==pairs.length)return null;
  if(u.pathname==='/retur')return pairs.every(([k,v])=>['sebelum','sebelum_pengajuan'].includes(k)&&positive(v))?{kind:'list',id:null,tab:null}:null;
  let m=u.pathname.match(/^\/retur\/([1-9][0-9]{0,9})$/);
  if(m)return positive(m[1])&&pairs.every(([k,v])=>k==='tab_detail'&&TABS.includes(v))?{kind:'receipt',id:Number(m[1]),tab:q.get('tab_detail')||'ringkasan'}:null;
  m=u.pathname.match(/^\/retur\/tiket\/([1-9][0-9]{0,9})$/);
  return m&&positive(m[1])&&!pairs.length?{kind:'ticket',id:Number(m[1]),tab:null}:null;
 }
 function bound(doc,ctx,cap,token,source){
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),form=doc.getElementById('formulir-sesi');
  return !!frame&&!!main&&!!form&&doc.querySelectorAll('.bingkai').length===1&&doc.querySelectorAll('#isi-halaman').length===1&&doc.querySelectorAll('#formulir-sesi').length===1&&frame.contains(main)&&frame.contains(form)&&frame.dataset.pindahKonteks===ctx&&doc.documentElement.dataset.versi===cap&&form.dataset.token===token&&(source===undefined||frame.dataset.pindahAlamat===source);
 }
 function packageValid(data){
  return exact(data,['versi','sumber','variants','styles','scripts'])&&data.versi===1&&sha(data.sumber)&&exact(data.variants,['list','receipt','ticket'])&&Object.values(data.variants).every(c=>exact(c,['html','title','breadcrumb','header_menu'])&&['html','title','breadcrumb','header_menu'].every(k=>typeof c[k]==='string'&&c[k].length<=131072))&&['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=16&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144));
 }
 function validFlags(data,p,ctx,cap,token){
  return packageValid(data)&&exact(p,['versi','sumber','cap','konteks','sesi','targets'])&&p.versi===1&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===ctx&&p.sesi===token&&[ctx,cap,token].every(v=>typeof v==='string'&&v&&v.length<=2048)&&Array.isArray(p.targets)&&p.targets.length===1&&p.targets[0]==='/retur';
 }
 function validCatalog(data,p,source,ctx,cap,token,digest,origin){
  if(!packageValid(data)||!exact(p,['versi','sumber','cap','konteks','sesi','source_address','sumber_sha256','entries'])||p.versi!==1||p.sumber!==data.sumber||p.cap!==cap||p.konteks!==ctx||p.sesi!==token||p.source_address!==source||!sha(digest)||p.sumber_sha256!==digest||!Array.isArray(p.entries)||!p.entries.length||p.entries.length>50)return false;
  return new Set(p.entries.map(e=>e?.kind+':'+e?.id)).size===p.entries.length&&p.entries.every(e=>{const a=address(e?.target,origin);return exact(e,['kind','id','code','target'])&&['receipt','ticket'].includes(e.kind)&&Number.isInteger(e.id)&&a?.id===e.id&&a.kind===e.kind&&typeof e.code==='string'&&e.code&&e.code.length<=200;});
 }
 function shown(a,style){return !!a&&a.isConnected!==false&&!a.closest('[hidden],[inert],[aria-hidden="true"]')&&a.getClientRects().length>0&&!['hidden','collapse'].includes(style(a).visibility)&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true';}
 function href(a,source,origin){try{const u=new URL(a.getAttribute('href'),origin+source);return u.origin===origin&&!u.hash?u.pathname+u.search:null;}catch(_){return null;}}
 function visibleLink(doc,target,source,origin,style,selector='#isi-halaman a[href],#laci a[href]'){
  const links=[...doc.querySelectorAll(selector)];if(links.length>1000)return null;
  return links.find(a=>href(a,source,origin)===target&&shown(a,style))||null;
 }
 function select(p,target,source,doc,style,origin){
  if(p.source_address!==source)return null;const e=p.entries.find(v=>v.target===target);if(!e)return null;
  const selector=e.kind==='receipt'?'#isi-halaman [data-retur-receipts] td[data-sel="utama"] > a.tabel-standar__kode[href]':'#isi-halaman #panel-tiket a[href]';
  const a=visibleLink(doc,target,source,origin,style,selector);
  return a&&(e.kind==='receipt'?a.textContent===e.code:a.textContent==='Lihat tiket RTP terkait'&&a.closest('section')?.querySelector('h3')?.textContent===e.code)?e:null;
 }
 const api={address,bound,packageValid,validFlags,validCatalog,shown,href,visibleLink,select};
 if(typeof module==='object'&&module.exports){module.exports=api;return;}
 const data=global.PadiKerangkaReturBacaData;
 function buat(target,base,ctx,cap,token){try{
  const source=location.pathname+location.search,spec=address(target,location.origin);
  if(!spec||typeof base!=='string'||base.length>8388608||!bound(document,ctx,cap,token,source)||document.body.hasAttribute('data-portal-akun')||document.body.classList.contains('portal-customer')||document.querySelector('[data-editor-perintah],[data-kemas-ulang]')||global.SESIFORM&&!global.SESIFORM.periksa())return null;
  const flags=document.querySelectorAll('#padi-retur-baca-kerangka');if(flags.length!==1)return null;const flag=flags[0];
  if(!flag.isConnected||flag.dataset.cap!==cap||flag.dataset.konteks!==ctx||flag.textContent.length>4096)return null;
  if(!validFlags(data,JSON.parse(flag.textContent),ctx,cap,token))return null;
  let entry=null;
  if(spec.kind==='list'){
   if(!visibleLink(document,target,source,location.origin,n=>getComputedStyle(n)))return null;
  }else{
   const hosts=document.querySelectorAll('#padi-retur-baca-catalog');if(hosts.length!==1)return null;const host=hosts[0];
   if(!host.isConnected||!document.getElementById('isi-halaman').contains(host)||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.dataset.sourceAddress!==source||host.textContent.length>32768)return null;
   const catalog=JSON.parse(host.textContent);
   if(!validCatalog(data,catalog,source,ctx,cap,token,host.dataset.sourceSha,location.origin))return null;
   entry=select(catalog,target,source,document,n=>getComputedStyle(n),location.origin);if(!entry)return null;
  }
  const doc=new DOMParser().parseFromString(base,'text/html');if(!bound(doc,ctx,cap,token))return null;
  const main=doc.getElementById('isi-halaman'),frame=doc.querySelector('.bingkai'),nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const component=data.variants[spec.kind],part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attr] of [['style[data-retur-style]',data.styles,'data-retur-style'],['script[data-retur-script]',data.scripts,'data-retur-script']])for(const n of part.content.querySelectorAll(selector)){const key=n.getAttribute(attr);if(!own(pool,key))return null;n.textContent=pool[key];n.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-retur-baca-native]');if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[name],[data-post],[data-kirim],[data-detail-tab],[data-retur-form],script[src],link[rel=stylesheet],script[type="application/json"]'))return null;
  const root=roots[0];root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;
  if(entry)for(const code of root.querySelectorAll('[data-retur-code]'))code.textContent=entry.code;
  if(spec.kind==='receipt'){
   for(const tab of root.querySelectorAll('[data-retur-tab]'))tab.setAttribute('aria-selected',String(tab.dataset.returTab===spec.tab));
   for(const panel of root.querySelectorAll('[data-retur-panel]'))panel.hidden=panel.dataset.returPanel!==spec.tab;
  }
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  const crumb=main.querySelector('.desktop-chrome__crumbrow'),bar=main.querySelector('header.bar');if(!crumb||!bar)return null;
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();
  const chrome=doc.createElement('template');chrome.innerHTML=component.breadcrumb;
  if(entry)for(const n of chrome.content.querySelectorAll('[aria-current="page"]'))n.textContent=n.textContent.replace('__PADI_CODE__',entry.code);
  crumb.replaceChildren(chrome.content);
  const control=doc.createElement('template');control.innerHTML=component.header_menu;
  if(control.content.querySelectorAll('.bar__menu').length!==1||control.content.querySelector('.bar__balik,form,script,input'))return null;
  for(const old of bar.querySelectorAll('.bar__menu,.bar__balik'))old.remove();bar.prepend(control.content);
  const title=component.title.replace('__PADI_CODE__',entry?.code||''),brand=bar.querySelector('.bar__merek');if(!brand)return null;brand.textContent=title;brand.setAttribute('aria-label',title);
  for(const old of doc.querySelectorAll('#padi-retur-baca-catalog'))old.remove();
  for(const old of doc.querySelectorAll('#padi-retur-baca-kerangka'))old.remove();doc.body.append(doc.importNode(flag,true));
  for(const a of doc.querySelectorAll('#laci a[href]')){const active=new URL(a.getAttribute('href'),location.href).pathname==='/barang-keluar';a.classList.toggle('pintu--kini',active&&a.classList.contains('pintu'));a.classList.toggle('pintu-sub__satu--kini',active&&a.classList.contains('pintu-sub__satu'));if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title=title+' · PT Hadi Mulya Utama';return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }catch(_){return null;}}
 global.PadiKerangkaReturBacaUI=Object.freeze({versi:1,sumber:data?.sumber,address,buat});
})(typeof window==='undefined'?globalThis:window);
