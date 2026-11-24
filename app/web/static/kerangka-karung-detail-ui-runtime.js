/* Finite actual visible packaging DTO links; native GET remains authoritative. */
(function(global){'use strict';
 const obj=v=>!!v&&typeof v==='object'&&!Array.isArray(v),own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k),exact=(v,keys)=>obj(v)&&Object.keys(v).length===keys.length&&keys.every(k=>own(v,k));
 const selector='table.karung-tabel .karung-tabel__status > a.btn[href]';
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.length>4096)return null;
  let u;try{u=new URL(value,origin);}catch(_){return null;}
  const p=[...u.searchParams],q=u.searchParams,positive=v=>typeof v==='string'&&/^[0-9]+$/.test(v)&&Number(v)>0&&Number(v)<=2147483647;
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||u.pathname!=='/stok/karung/detail'||p.length>6||new Set(p.map(x=>x[0])).size!==p.length||p.some(x=>!['material','ukuran','merk','pemilik','sumber_page'].includes(x[0])))return null;
  if(!q.get('material')||q.get('material').length>128||!positive(q.get('ukuran'))||(q.get('merk')||'').length>256||q.has('pemilik')&&q.get('pemilik')!=='pabrik'&&!positive(q.get('pemilik'))||q.has('sumber_page')&&!positive(q.get('sumber_page')))return null;
  return u;
 }
 function valid(c,data,source,ctx,cap,token,digest){
  return exact(c,['versi','sumber','cap','konteks','sesi','asal','asal_sha256','entries'])&&c.versi===1&&c.sumber===data.sumber&&c.cap===cap&&c.konteks===ctx&&c.sesi===token&&c.asal===source&&typeof digest==='string'&&/^[a-f0-9]{64}$/.test(digest)&&c.asal_sha256===digest&&[ctx,cap,token].every(v=>typeof v==='string'&&v&&v.length<=512)&&Array.isArray(c.entries)&&c.entries.length>0&&c.entries.length<=50&&new Set(c.entries.map(e=>e?.alamat)).size===c.entries.length&&c.entries.every(e=>exact(e,['alamat','identity_label'])&&!!address(e.alamat,'https://native-relative.invalid')&&typeof e.identity_label==='string'&&e.identity_label&&e.identity_label.length<=512);
 }
 function visible(doc,target,shown){
  const links=[...doc.querySelectorAll('#isi-halaman '+selector)];if(links.length>100)return false;
  return links.some(a=>a.getAttribute('href')===target&&!a.closest('[hidden],[inert],[aria-hidden="true"]')&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true'&&shown(a));
 }
 const api={address,valid,visible};if(typeof module==='object'&&module.exports){module.exports=api;return;}
 const data=global.PadiKerangkaKarungDetailData;
 if(!exact(data,['versi','sumber','component','styles','scripts'])||data.versi!==1||typeof data.sumber!=='string'||!/^[a-f0-9]{64}$/.test(data.sumber)||!exact(data.component,['html','title','breadcrumb','back_markup','menu_markup'])||!obj(data.styles)||!obj(data.scripts))return;
 function buat(target,base,ctx,cap,token){
  const source=location.pathname+location.search,frame=document.querySelector('.bingkai');
  if(!address(target,location.origin)||frame?.dataset.pindahAlamat!==source||frame.dataset.pindahKonteks!==ctx||document.documentElement.dataset.versi!==cap||document.getElementById('formulir-sesi')?.dataset.token!==token||typeof base!=='string'||base.length>8388608)return null;
  const hosts=document.querySelectorAll('#padi-karung-detail-catalog');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.dataset.sourceAddress!==source||host.textContent.length>32768)return null;
  let catalog;try{catalog=JSON.parse(host.textContent);}catch(_){return null;}
  if(!valid(catalog,data,source,ctx,cap,token,host.dataset.sourceSha))return null;
  const entry=catalog.entries.find(e=>e.alamat===target);if(!entry||!visible(document,target,n=>!!n.getClientRects().length&&!['hidden','collapse'].includes(global.getComputedStyle(n).visibility)))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1)return null;
  const f=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(!f.contains(main)||!f.contains(session)||f.dataset.pindahKonteks!==ctx||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const comments=[...main.childNodes],starts=comments.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=comments.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const c=data.component;if(Object.values(c).some(v=>typeof v!=='string'||v.length>262144))return null;
  const part=doc.createElement('template');part.innerHTML=c.html;
  for(const [selector,pool,attr] of [['style[data-karung-style]',data.styles,'data-karung-style'],['script[data-karung-script]',data.scripts,'data-karung-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key)||typeof pool[key]!=='string'||pool[key].length>524288)return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-karung-detail-native]');if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[data-post],[data-kirim],[data-kod-awal],[data-kepemilikan-sumber],script[src],script[type="application/json"]'))return null;
  const root=roots[0];root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;root.querySelector('[data-karung-identity]').textContent=entry.identity_label;
  const[first,last]=[starts[0],ends[0]];while(first.nextSibling&&first.nextSibling!==last)first.nextSibling.remove();last.before(part.content);
  const crumb=main.querySelector('.desktop-chrome__crumbrow'),bar=main.querySelector('header.bar');if(!crumb||!bar)return null;
  for(const n of main.querySelectorAll('.desktop-back'))n.remove();crumb.innerHTML=c.breadcrumb;
  for(const n of bar.querySelectorAll('.bar__menu,.bar__balik'))n.remove();
  const controls=doc.createElement('template');controls.innerHTML=c.menu_markup+c.back_markup;
  const back=controls.content.querySelector('a.bar__balik');if(!back||controls.content.querySelectorAll('#buka-laci').length!==1)return null;back.setAttribute('href','/stok?tab=karung');bar.prepend(controls.content);bar.classList.add('bar--rsp-menu-kembali');
  const brand=bar.querySelector('.bar__merek');if(brand){brand.textContent=c.title;brand.setAttribute('aria-label',c.title);}
  f.dataset.pindahAlamat=target;doc.title=c.title+' · PT Hadi Mulya Utama';return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 global.PadiKerangkaKarungDetailUI=Object.freeze({versi:1,sumber:data.sumber,address,buat});
})(typeof window==='undefined'?globalThis:window);
