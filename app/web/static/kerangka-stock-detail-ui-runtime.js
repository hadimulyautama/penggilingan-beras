/* Bounded DTO-backed private link catalog; never stock math or authorization. */
(function(global){'use strict';
 const variants=['pk-g1','pk-g2-curah','pk-g2-karung','product-auto','product-curah','product-packed','warehouse-g1','warehouse-g2'];
 const selector='a.stok-baris__tautan[href],a.stok-mobile-list__baris[href],.produk-list a.tabel-standar__baris[href],a.alur-gudang__buka[href]';
 const obj=v=>!!v&&typeof v==='object'&&!Array.isArray(v),own=(v,k)=>Object.prototype.hasOwnProperty.call(v,k),exact=(v,keys)=>obj(v)&&Object.keys(v).length===keys.length&&keys.every(k=>own(v,k));
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.length>4096)return null;
  let u;try{u=new URL(value,origin);}catch(_){return null;}
  const p=[...u.searchParams],q=u.searchParams;
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||p.length>12||new Set(p.map(x=>x[0])).size!==p.length)return null;
  const positive=x=>typeof x==='string'&&/^[0-9]+$/.test(x)&&/[1-9]/.test(x);
  if(u.pathname==='/stok/pk/detail'){
   if(p.some(x=>!['gudang','kode','id','jasa','pemilik_id','gudang_filter','kembali_stok'].includes(x[0]))||!['g1','g2'].includes(q.get('gudang'))||!['0','1'].includes(q.get('jasa')||'0'))return null;
   const key=q.get(q.get('gudang')==='g1'?'kode':'id'),owner=q.get('pemilik_id');
   if(!key||key.length>128||q.get('gudang')==='g2'&&!positive(key)||owner&&owner!=='pabrik'&&!positive(owner))return null;
   return {u,family:'pk'};
  }
  if(['/stok-produk/detail','/stok-produk-jasa/detail'].includes(u.pathname)){
   if(p.some(x=>!['jenis','pelanggan_id','sumber_page','kembali_stok'].includes(x[0]))||!q.get('jenis')||q.get('jenis').length>128||q.has('sumber_page')&&!positive(q.get('sumber_page')))return null;
   if(u.pathname==='/stok-produk-jasa/detail'?!positive(q.get('pelanggan_id')):!!q.get('pelanggan_id'))return null;
   return {u,family:'product'};
  }
  return ['/gudang/g1','/gudang/g2'].includes(u.pathname)&&!p.length?{u,family:'warehouse'}:null;
 }
 function validReferences(r){
  const text=v=>typeof v==='string'&&v.length>0&&v.length<=256;
  return exact(r,['name','function','steps','dryers','silos'])&&text(r.name)&&text(r.function)&&Array.isArray(r.steps)&&r.steps.length>0&&r.steps.length<=8&&r.steps.every(text)&&Array.isArray(r.dryers)&&r.dryers.length<=16&&r.dryers.every(g=>exact(g,['name','units'])&&typeof g.name==='string'&&g.name.length<=256&&Array.isArray(g.units)&&g.units.every(text))&&r.dryers.reduce((n,g)=>n+g.units.length,0)<=50&&Array.isArray(r.silos)&&r.silos.length<=50&&r.silos.every(text);
 }
 function fillWarehouse(doc,root,m){
  const r=m.warehouse_refs;if(!validReferences(r))throw Error('Warehouse reference structure unavailable');
  const set=(selector,value)=>{const n=root.querySelector(selector);if(!n)throw Error('Native warehouse reference host missing');n.textContent=value;};
  set('[data-stock-function]',r.function);set('[data-stock-warehouse-name]',r.name);
  root.querySelector('[data-stock-warehouse-label]').setAttribute('aria-label','Ringkasan '+r.name);
  root.querySelector('[data-stock-warehouse]').setAttribute('aria-label',r.name+' — '+r.function);
  const stages=root.querySelector('[data-stock-stages]');stages.setAttribute('aria-label','Alur produksi '+r.name);stages.style.setProperty('--tahap',String(r.steps.length));
  const clone=selector=>{const node=root.querySelector(selector)?.content.firstElementChild;if(!node)throw Error('Native reference prototype missing');return node.cloneNode(true);};
  r.steps.forEach((label,i)=>{const n=clone('[data-stock-step-reference]');n.querySelector('strong').textContent=label;n.querySelector('.alur-tahap__nomor').textContent=String(i+1);stages.append(n);});
  const dryers=root.querySelector('[data-stock-dryers]');
  if(dryers){dryers.setAttribute('aria-label','Mesin pengering '+r.name);const groups=root.querySelector('[data-stock-dryer-groups]');for(const group of r.dryers){const n=clone('[data-stock-dryer-group-reference]'),furnace=n.querySelector('[data-stock-furnace]');if(group.name){n.classList.add('alur-kelompok--bersama');furnace.querySelector('strong').textContent=group.name;}else furnace.remove();for(const label of group.units){const unit=clone('[data-stock-dryer-reference]');unit.querySelector('[data-stock-reference-name]').textContent=label;n.querySelector('.alur-dryers').append(unit);}groups.before(n);}}
  const silos=root.querySelector('[data-stock-silos]');silos.style.setProperty('--jumlah-silo',String(r.silos.length||1));
  root.querySelector('[data-stock-silo-area]').setAttribute('aria-label','Silo '+r.name);
  root.querySelector('.alur-penyimpanan').classList.toggle('alur-penyimpanan--banyak',r.silos.length>2);
  root.querySelector('.alur-mesin').classList.toggle('alur-mesin--ringkas',m.variant==='warehouse-g1'&&r.dryers.reduce((n,g)=>n+g.units.length,0)===1&&r.silos.length<=2);
  for(const label of r.silos){const unit=clone('[data-stock-silo-reference]');unit.querySelector('[data-stock-reference-name]').textContent=label;silos.append(unit);}
  for(const n of root.querySelectorAll('template'))n.remove();
 }
 function validMeta(m){
  return exact(m,['variant','mutu','jasa','beras','qc_latest','stages','incoming','stock','warehouse_refs'])&&variants.includes(m.variant)&&['mutu','jasa','beras'].every(k=>typeof m[k]==='boolean')&&(m.qc_latest===null||typeof m.qc_latest==='boolean')&&Array.isArray(m.stages)&&m.stages.length<=8&&m.stages.every(v=>typeof v==='string'&&v.length>0&&v.length<=128)&&['incoming','stock'].every(k=>typeof m[k]==='string'&&m[k].length<=256)&&(m.variant.startsWith('warehouse-')?validReferences(m.warehouse_refs):m.warehouse_refs===null);
 }
 function validChrome(c,origin){
  const local=v=>{if(typeof v!=='string'||!v.startsWith('/')||v.startsWith('//')||v.length>4096||/[\\\u0000-\u001f]/.test(v))return false;try{return new URL(v,origin).origin===origin;}catch(_){return false;}};
  return exact(c,['title','back','chain'])&&typeof c.title==='string'&&c.title&&c.title.length<=512&&local(c.back)&&exact(c.chain,['items','kembali'])&&Array.isArray(c.chain.items)&&c.chain.items.length>=2&&c.chain.items.length<=6&&c.chain.items.every((n,i)=>exact(n,['nama','alamat'])&&typeof n.nama==='string'&&n.nama&&n.nama.length<=512&&(i===c.chain.items.length-1?n.alamat===null:local(n.alamat)))&&c.chain.kembali===c.chain.items[c.chain.items.length-2].alamat;
 }
 function installChrome(doc,main,component,chrome,origin){
  if(!validChrome(chrome,origin))throw Error('Native breadcrumb metadata changed');
  const part=doc.createElement('template');part.innerHTML=component.breadcrumb;
  const rows=[...part.content.querySelectorAll('.nav-rantai>li')];if(rows.length!==chrome.chain.items.length)throw Error('Native breadcrumb shape changed');
  for(let i=0;i<rows.length;i++){const item=chrome.chain.items[i],node=rows[i].querySelector('a,[aria-current="page"]');if(!node||!!item.alamat!==(node.tagName==='A'))throw Error('Native breadcrumb node changed');node.textContent=item.nama;if(item.alamat)node.setAttribute('href',item.alamat);}
  const desktop=part.content.querySelector('.desktop-back');if(!desktop)throw Error('Native Back missing');desktop.setAttribute('href',chrome.chain.kembali);
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(!crumb)throw Error('Native breadcrumb host missing');crumb.replaceChildren(part.content);
  const mobile=doc.createElement('template');mobile.innerHTML=component.back_markup;
  const back=mobile.content.querySelector('a.bar__balik'),bar=main.querySelector('.bar');if(!back||!bar)throw Error('Native mobile Back missing');back.setAttribute('href',chrome.back);
  const old=bar.querySelector('.bar__menu,.bar__balik');if(old)old.replaceWith(mobile.content);else bar.prepend(mobile.content);
 }
 function validCatalog(c,data,source,ctx,cap,token,expectedDigest){
  return exact(c,['versi','sumber','cap','konteks','sesi','asal','asal_sha256','entries'])&&c.versi===1&&c.sumber===data.sumber&&c.cap===cap&&c.konteks===ctx&&c.sesi===token&&c.asal===source&&typeof expectedDigest==='string'&&/^[a-f0-9]{64}$/.test(expectedDigest)&&c.asal_sha256===expectedDigest&&[ctx,cap,token].every(v=>typeof v==='string'&&v&&v.length<=512)&&Array.isArray(c.entries)&&c.entries.length>0&&c.entries.length<=50&&new Set(c.entries.map(e=>e?.alamat)).size===c.entries.length&&c.entries.every(e=>exact(e,['alamat','metadata','chrome','body_title'])&&typeof e.alamat==='string'&&(e.body_title===null?e.metadata?.variant?.startsWith('warehouse-'):typeof e.body_title==='string'&&e.body_title.length>0&&e.body_title.length<=512&&!e.metadata?.variant?.startsWith('warehouse-'))&&validMeta(e.metadata)&&validChrome(e.chrome,'https://native-relative.invalid'));
 }
 function visible(doc,target,shown){
  const links=[...doc.querySelectorAll('#isi-halaman '+selector.split(',').join(',#isi-halaman '))];
  if(links.length>100)return false;
  return links.some(a=>a.getAttribute('href')===target&&!a.closest('[hidden],[inert],[aria-hidden="true"]')&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true'&&shown(a));
 }
 const api={address,validMeta,validCatalog,validChrome,validReferences,fillWarehouse,installChrome,visible};
 if(typeof module==='object'&&module.exports){module.exports=api;return;}
 const data=global.PadiKerangkaStockDetailData;
 if(!exact(data,['versi','sumber','variants','scripts','styles'])||data.versi!==1||typeof data.sumber!=='string'||!/^[a-f0-9]{64}$/.test(data.sumber)||!exact(data.variants,variants)||(!obj(data.scripts)||!obj(data.styles)))return;
 function buat(target,base,ctx,cap,token){
  const state=address(target,location.origin),source=location.pathname+location.search,frame=document.querySelector('.bingkai');
  if(!state||frame?.dataset.pindahAlamat!==source||frame.dataset.pindahKonteks!==ctx||document.documentElement.dataset.versi!==cap||document.getElementById('formulir-sesi')?.dataset.token!==token||typeof base!=='string'||base.length>8388608)return null;
  const hosts=document.querySelectorAll('#padi-stock-detail-catalog');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.dataset.sourceAddress!==source||host.textContent.length>32768)return null;
  let c;try{c=JSON.parse(host.textContent);}catch(_){return null;}
  if(!validCatalog(c,data,source,ctx,cap,token,host.dataset.sourceSha))return null;
  const entry=c.entries.find(e=>e.alamat===target);if(!entry)return null;
  const m=entry.metadata;
  if(state.family==='pk'&&(!m.variant.startsWith('pk-')||(state.u.searchParams.get('gudang')==='g1')!==(m.variant==='pk-g1')||m.jasa!==(state.u.searchParams.get('jasa')==='1'))
   ||state.family==='product'&&(!m.variant.startsWith('product-')||m.jasa!==(state.u.pathname==='/stok-produk-jasa/detail'))
   ||state.family==='warehouse'&&m.variant!=='warehouse-'+state.u.pathname.split('/').pop())return null;
  const shown=n=>!!n.getClientRects().length&&!['hidden','collapse'].includes(global.getComputedStyle(n).visibility);
  if(!visible(document,target,shown))return null;
  const doc=new DOMParser().parseFromString(base,'text/html');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1)return null;
  const f=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(!f.contains(main)||!f.contains(session)||f.dataset.pindahKonteks!==ctx||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const v=data.variants[m.variant];if(!exact(v,['html','title','breadcrumb','back_markup'])||typeof v.html!=='string'||v.html.length>131072||typeof v.title!=='string'||typeof v.breadcrumb!=='string'||v.breadcrumb.length>65536||typeof v.back_markup!=='string'||v.back_markup.length>65536)return null;
  const part=doc.createElement('template');part.innerHTML=v.html;
  for(const style of part.content.querySelectorAll('style[data-stock-detail-style-ref]')){const key=style.getAttribute('data-stock-detail-style-ref');if(!own(data.styles,key)||typeof data.styles[key]!=='string'||data.styles[key].length>524288)return null;style.textContent=data.styles[key];style.removeAttribute('data-stock-detail-style-ref');}
  for(const script of part.content.querySelectorAll('script[data-stock-detail-script]')){const key=script.getAttribute('data-stock-detail-script');if(!own(data.scripts,key)||typeof data.scripts[key]!=='string'||data.scripts[key].length>524288)return null;script.textContent=data.scripts[key];script.removeAttribute('data-stock-detail-script');}
  const roots=part.content.querySelectorAll('[data-stock-detail-native]');if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[data-post],[data-kirim],script[src],link[rel=stylesheet],script[type="application/json"]'))return null;
  const root=roots[0];if(root.dataset.variant!==m.variant)return null;
  if(!m.mutu)root.querySelector('[data-stock-detail-qc]')?.remove();
  const owner=root.querySelector('[data-stock-owner]');if(owner)owner.hidden=!m.jasa;
  const note=root.querySelector('[data-stock-qc-note]');if(note)note.textContent=m.qc_latest===null?'Catatan · menunggu data':m.qc_latest?'Catatan lab':'Pencatat & catatan';
  const title=entry.chrome.title;
  if(entry.body_title!==null){const h=root.querySelector('[data-stock-body-title]');if(!h)return null;h.textContent=entry.body_title;const n=root.querySelector('[data-stock-product-name]');if(n)n.textContent=entry.body_title;}else if(root.querySelector('h1'))return null;
  const contentBack=root.querySelector('[data-stock-content-back]');if(contentBack){contentBack.setAttribute('href',entry.chrome.back);if(m.variant.startsWith('product-'))contentBack.textContent='← Kembali ke '+(m.jasa?'Stok Produk Jasa':'Stok Produk');}
  const chip=root.querySelector('[data-stock-owner-chip]');if(chip){chip.textContent=m.jasa?'Jasa':'Pabrik';chip.classList.toggle('pk-detail__chip--jasa',m.jasa);chip.classList.toggle('pk-detail__chip--pabrik',!m.jasa);}
  const product=root.querySelector('details.padat');if(product){product.classList.toggle('padat--giling',m.beras);product.classList.toggle('padat--samping',!m.beras);}
  if(m.variant.startsWith('warehouse-')){try{fillWarehouse(doc,root,m);}catch(_){return null;}}
  for(const [sel,value]of [['[data-stock-incoming]',m.incoming],['[data-stock-label]',m.stock]]){const n=root.querySelector(sel);if(n)n.textContent=value;}
  root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;
  const[first,last]=[starts[0],ends[0]];while(first.nextSibling&&first.nextSibling!==last)first.nextSibling.remove();last.before(part.content);
  const heading=main.querySelector('.bar__merek');if(heading){heading.textContent=title;heading.setAttribute('aria-label',title);}
  try{installChrome(doc,main,v,entry.chrome,location.origin);}catch(_){return null;}
  f.dataset.pindahAlamat=target;doc.title=title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 global.PadiKerangkaStockDetailUI=Object.freeze({versi:1,sumber:data.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
