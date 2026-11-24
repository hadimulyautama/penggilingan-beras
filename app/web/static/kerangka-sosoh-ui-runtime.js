/* Public data-free Sosoh structure; native private schema and fresh GET own data. */
(function(global){
 'use strict';
 const keys=['ringkasan','bahan','hasil','qc','riwayat'];
 const object=v=>!!v&&typeof v==='object'&&!Array.isArray(v),own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k);
 const exact=(v,fields)=>object(v)&&Object.keys(v).length===fields.length&&fields.every(k=>own(v,k));
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//'))return null;
  let u;try{u=new URL(value,origin);}catch(_){return null;}
  const q=u.searchParams,pairs=[...q];
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||!/^\/proses-aktif\/sosoh\/[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(u.pathname)||u.search.length>3001||pairs.length>12
   ||new Set(pairs.map(p=>p[0])).size!==pairs.length||pairs.some(p=>!['tab_detail','kembali_kerja','halaman_hasil','halaman_qc','halaman_jeda','buka','nilai'].includes(p[0]))||q.get('buka')||q.get('nilai'))return null;
  const tab=q.get('tab_detail')||'ringkasan';
  return {u,code:u.pathname.split('/').pop(),tab:keys.includes(tab)?tab:'ringkasan'};
 }
 function validData(data){
  return exact(data,['versi','sumber','variants','styles','scripts'])&&data.versi===1&&typeof data.sumber==='string'&&/^[a-f0-9]{64}$/.test(data.sumber)
   &&exact(data.variants,['admin','operator'])&&['admin','operator'].every(k=>exact(data.variants[k],['html'])&&typeof data.variants[k].html==='string'&&data.variants[k].html.length<=131072)
   &&['styles','scripts'].every(k=>object(data[k])&&Object.keys(data[k]).length<=32&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=524288));
 }
 function validPermission(p,data,context,cap,token){
  return validData(data)&&exact(p,['versi','sumber','cap','konteks','sesi','layout','hasil'])&&p.versi===1&&p.sumber===data.sumber&&p.cap===cap&&p.konteks===context&&p.sesi===token
   &&[context,cap,token].every(v=>typeof v==='string'&&v&&v.length<=512)&&['operator','admin'].includes(p.layout)
   &&Array.isArray(p.hasil)&&p.hasil.length>0&&p.hasil.length<=64&&new Set(p.hasil.map(h=>h?.jenis)).size===p.hasil.length
   &&p.hasil.every(h=>exact(h,['jenis','nama','beras'])&&typeof h.jenis==='string'&&h.jenis.length>0&&h.jenis.length<=128&&typeof h.nama==='string'&&h.nama.length>0&&h.nama.length<=256&&typeof h.beras==='boolean');
 }
 function validCatalog(c,address,code,context,cap,token,sourceSha){
  return exact(c,['versi','cap','konteks','sesi','sumber_sha256','entries'])&&c.versi===1&&c.cap===cap&&c.konteks===context&&c.sesi===token&&typeof sourceSha==='string'&&/^[a-f0-9]{64}$/.test(sourceSha)&&c.sumber_sha256===sourceSha
   &&Array.isArray(c.entries)&&c.entries.length>0&&c.entries.length<=50
   &&c.entries.every(e=>exact(e,['alamat','kode','label'])&&typeof e.alamat==='string'&&typeof e.kode==='string'&&e.label==='Penyosohan aktif')
   &&c.entries.some(e=>e.alamat===address&&e.kode===code);
 }
 function visibleRow(doc,address,code,shown){
  const rows=[...doc.querySelectorAll('section[data-blok][aria-label="Proses aktif"] .proses-aktif-list > .proses-aktif-list__row[data-proses="sosoh"]')];
  if(rows.length>50)return false;
  return rows.some(row=>{
   const strong=row.querySelector('strong');
   if(row.closest('[hidden],[inert],[aria-hidden="true"]')||!shown(row)||!strong||strong.closest('[hidden],[inert],[aria-hidden="true"]')||!shown(strong)||strong.textContent.trim()!==code)return false;
   const links=row.matches('a[href]')?[row]:[...row.querySelectorAll('a.proses-aktif-list__detail[href]')];
   return links.some(link=>link.getAttribute('href')===address&&!link.closest('[hidden],[inert],[aria-hidden="true"]')&&!link.hasAttribute('target')&&!link.hasAttribute('download')&&link.getAttribute('aria-disabled')!=='true'&&shown(link));
  });
 }
 function fieldGroups(schema,layout){
  const main=layout==='operator'?schema.filter(h=>h.beras):schema.slice(0,6);
  return {main,more:schema.filter(h=>!main.includes(h))};
 }
 const api={address,validData,validPermission,validCatalog,visibleRow,fieldGroups};
 if(typeof module==='object'&&module.exports){module.exports=api;return;}
 const data=global.PadiKerangkaSosohData;if(!validData(data))return;
 for(const variant of Object.values(data.variants))Object.freeze(variant);
 Object.freeze(data.variants);Object.freeze(data.styles);Object.freeze(data.scripts);Object.freeze(data);
 function buat(target,base,context,cap,token){
  const state=address(target,location.origin),source=location.pathname+location.search,currentFrame=document.querySelector('.bingkai');
  if(!state||!['/pekerjaan','/berjalan'].includes(location.pathname)||currentFrame?.dataset.pindahAlamat!==source||currentFrame.dataset.pindahKonteks!==context
   ||document.documentElement.dataset.versi!==cap||document.getElementById('formulir-sesi')?.dataset.token!==token||typeof base!=='string'||base.length>8388608)return null;
  const hosts=document.querySelectorAll('#padi-sosoh-kerangka'),catalogs=document.querySelectorAll('script[data-sosoh-native-catalog]');
  if(hosts.length!==1||catalogs.length!==1)return null;
  const host=hosts[0],catalogHost=catalogs[0];
  if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>32768||!catalogHost.isConnected||catalogHost.dataset.sourceAddress!==source||catalogHost.textContent.length>262144)return null;
  let p,catalog;try{p=JSON.parse(host.textContent);catalog=JSON.parse(catalogHost.textContent);}catch(_){return null;}
  if(!validPermission(p,data,context,cap,token)||!validCatalog(catalog,target,state.code,context,cap,token,catalogHost.dataset.sourceSha))return null;
  const shown=node=>!!node.getClientRects().length&&!['hidden','collapse'].includes(global.getComputedStyle(node).visibility);
  if(!visibleRow(document,target,state.code,shown))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1)return null;
  const frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=data.variants[p.layout].html;
  for(const [selector,pool,attr]of[['style[data-sosoh-style]',data.styles,'data-sosoh-style'],['script[data-sosoh-script]',data.scripts,'data-sosoh-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-sosoh-native-html]'),templates=part.content.querySelectorAll('template[data-sn-output-template]');
  if(roots.length!==1||templates.length!==1||part.content.querySelector('form,input:not([disabled]),#sosoh-awal,[data-sosoh-ringkas],[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;
  const root=roots[0],prototype=templates[0],more=root.querySelector('[data-sn-fold="hasil-lain"]');
  if(root.dataset.layout!==p.layout||!more||prototype.content.querySelectorAll('[data-sn-output-kind]').length!==1||root.querySelector('[data-sn-output-kind]'))return null;
  const groups=fieldGroups(p.hasil,p.layout);
  for(const [kind,rows]of Object.entries(groups))for(const field of rows){
   const fragment=prototype.content.cloneNode(true),row=fragment.querySelector('[data-sn-output-kind]'),label=row.querySelector('[data-sn-output-label]'),inputs=row.querySelectorAll('input');
   if(!label||inputs.length!==1||!inputs[0].disabled||inputs[0].hasAttribute('value')||inputs[0].hasAttribute('name'))return null;
   row.dataset.snOutputKind=field.jenis;label.textContent=field.nama;inputs[0].setAttribute('aria-label','Total kumulatif '+field.nama);
   if(kind==='main')more.before(fragment);else more.append(fragment);
  }
  prototype.remove();root.dataset.url=target;root.dataset.stamp=context+'|'+target;root.dataset.snTab=state.tab;
  root.querySelector('.sr-design-code').textContent=state.code;
  const back=root.querySelector('.sr-design-back');if(back)back.setAttribute('href',source);
  for(const tab of root.querySelectorAll('[data-sn-tab-pilih]')){const selected=tab.dataset.snTabPilih===state.tab;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;}
  for(const panel of root.querySelectorAll('[data-sn-panel]'))panel.hidden=panel.dataset.snPanel!==state.tab;
  const qc=root.querySelector('[data-sn-fold="qc"]');if(qc)qc.open=state.tab==='qc';
  const [first,last]=[starts[0],ends[0]];while(first.nextSibling&&first.nextSibling!==last)first.nextSibling.remove();last.before(part.content);
  const title='Penyosohan '+state.code;doc.title=title+' · PT Hadi Mulya Utama';
  const heading=main.querySelector('.bar__merek');if(heading){heading.textContent=title;heading.setAttribute('aria-label',title);}
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const a=doc.createElement('a'),strong=doc.createElement('strong');a.href='/pekerjaan';a.textContent='Pekerjaan';strong.textContent=state.code;crumb.replaceChildren(a,doc.createTextNode(' › '),strong);}
  for(const a of main.querySelectorAll('a.bar__balik,a.desktop-back'))a.setAttribute('href',source);
  for(const summary of doc.querySelectorAll('#laci summary.pintu')){summary.classList.remove('pintu--kini');summary.removeAttribute('aria-current');}
  for(const a of doc.querySelectorAll('#laci a[href]')){const u=new URL(a.getAttribute('href'),location.href),active=u.origin===location.origin&&u.pathname==='/pekerjaan';a.classList.toggle('pintu--kini',active&&a.classList.contains('pintu'));a.classList.toggle('pintu-sub__satu--kini',active&&a.classList.contains('pintu-sub__satu'));if(active){a.setAttribute('aria-current','page');const group=a.closest('details');if(group){group.open=true;group.querySelector('summary')?.classList.add('pintu--kini');}}else a.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;
  return {versi:1,alamat:target,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 global.PadiKerangkaSosohUI=Object.freeze({versi:1,sumber:data.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
