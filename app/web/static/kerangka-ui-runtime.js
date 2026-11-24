/* Public immutable structure; context/permission choices come from the document. */
(function(){
 'use strict';
 const data=window.PadiKerangkaUIData;
 if(data?.versi!==1||!data.variants||typeof data.sumber!=='string')return;
 for(const component of Object.values(data.variants))Object.freeze(component);
 Object.freeze(data.variants);Object.freeze(data);
 const own=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
 function value(node,text){node.value=text;node.setAttribute('value',text);}
 function dateValid(text){if(!/^\d{4}-\d{2}-\d{2}$/.test(text)||Number(text.slice(0,4))<1)return false;try{return new Date(text+'T00:00:00.000Z').toISOString().slice(0,10)===text;}catch(_){return false;}}
 function shipping(address){
  const u=new URL(address,location.href),q=u.searchParams;
  if(u.origin!==location.origin||u.pathname!=='/barang-keluar'||u.hash||u.search.length>3000||u.pathname+u.search!==address)return null;
  if(Array.from(q.keys()).some(k=>!['q','status','sejak','pelanggan_id','sebelum'].includes(k)||q.getAll(k).length!==1))return null;
  const search=(q.get('q')||'').trim(),status=q.get('status')||'',since=q.get('sejak')||'',customer=q.get('pelanggan_id')||'',cursor=q.get('sebelum')||'';
  if(search.length>200||!['','perintah','dimuat','selesai','batal'].includes(status)||since&&!dateValid(since)||customer&&(!/^[1-9]\d{0,9}$/.test(customer)||Number(customer)>2147483647)||cursor&&(!/^-?\d{1,10}$/.test(cursor)||Math.abs(Number(cursor))>2147483647))return null;
  return {u,search,status,since,customer};
 }
 function navigation(doc,path){
  doc.querySelectorAll('#laci summary.pintu').forEach(n=>{n.classList.remove('pintu--kini');n.removeAttribute('aria-current');});
  doc.querySelectorAll('#laci a[href]').forEach(n=>{
   const u=new URL(n.getAttribute('href'),location.href),active=u.origin===location.origin&&u.pathname===path;
   n.classList.toggle('pintu--kini',active&&n.classList.contains('pintu'));n.classList.toggle('pintu-sub__satu--kini',active&&n.classList.contains('pintu-sub__satu'));
   if(active){n.setAttribute('aria-current','page');const group=n.closest('details');if(group){group.open=true;group.querySelector('summary')?.classList.add('pintu--kini');}}else n.removeAttribute('aria-current');
  });
 }
 function buat(address,base,context,cap,token){
  const state=shipping(address);if(!state)return null;
  const host=document.getElementById('padi-kerangka-ui');let permission;
  if(!host?.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>4096)return null;
  try{permission=JSON.parse(host.textContent);}catch(_){return null;}
  if(permission?.versi!==1||permission.sumber!==data.sumber||permission.cap!==cap||permission.konteks!==context||permission.sesi!==token||!permission.varians||Object.keys(permission.varians).some(k=>k!=='pengiriman'))return null;
  const key=permission.varians.pengiriman;
  if(!['pengiriman-admin','pengiriman-operator'].includes(key)||!own(data.variants,key))return null;
  const component=data.variants[key];if(component.path!==state.u.pathname||component.family!=='pengiriman'||typeof base!=='string')return null;
  const doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman');
  if(!frame||!main||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const comments=Array.from(main.childNodes).filter(n=>n.nodeType===8),from=comments.find(n=>n.data.trim()==='isi-halaman:mulai'),to=comments.find(n=>n.data.trim()==='isi-halaman:akhir');
  if(!from||!to||!(from.compareDocumentPosition(to)&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=component.html;
  const root=part.content.querySelector('[data-halaman-bertahap][data-kind="pengiriman"]');if(!root)return null;
  root.dataset.stamp=context+'|'+address;root.dataset.url='/api/halaman-bertahap/pengiriman'+state.u.search;
  for(const form of root.querySelectorAll('form')){
   for(const input of form.querySelectorAll('input[type=hidden]'))input.remove();
   for(const input of form.querySelectorAll('[name=q]'))value(input,state.search);
   const select=form.querySelector('[name=status]');if(select){select.value=state.status;for(const option of select.options)option.toggleAttribute('selected',option.selected);}
   const since=form.querySelector('[name=sejak]');if(since)value(since,state.since);
   const fields=new Set(Array.from(form.elements).filter(e=>e.name&&!e.disabled).map(e=>e.name));
   const hidden=form.matches('.bk-form-filter')?[['q',state.search],['pelanggan_id',state.customer]]:Array.from(state.u.searchParams).filter(([k])=>!['q','sebelum'].includes(k));
   for(const [name,text] of hidden){if(fields.has(name)||name==='pelanggan_id'&&!text)continue;const input=doc.createElement('input');input.type='hidden';input.name=name;value(input,text);form.append(input);}
  }
  const filter=root.querySelector('[data-bk-buka="bk-filter"]'),count=Number(!!state.status)+Number(!!state.since);if(filter)filter.textContent='Filter'+(count?' · '+count:'');
  const statusChip=root.querySelector('[data-ui-status]');if(statusChip){statusChip.hidden=!state.status;statusChip.textContent=root.querySelector('select[name=status]')?.selectedOptions[0].textContent||'';}
  const dateChip=root.querySelector('[data-ui-date]');if(dateChip){dateChip.hidden=!state.since;dateChip.textContent='Sejak '+state.since;}
  const reset=root.querySelector('.bk-form-filter>a[href]');if(reset){const next=new URL('/barang-keluar',location.href);next.searchParams.set('q',state.search);if(state.customer)next.searchParams.set('pelanggan_id',state.customer);reset.setAttribute('href',next.pathname+next.search);}
  while(from.nextSibling&&from.nextSibling!==to)from.nextSibling.remove();to.before(part.content);
  frame.dataset.pindahAlamat=address;doc.title=component.title+' · PT Hadi Mulya Utama';
  const label=main.querySelector('.bar__merek');if(label){label.textContent=component.title;label.setAttribute('aria-label',component.title);}
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const html=doc.createElement('template');html.innerHTML=component.breadcrumb;crumb.replaceChildren(html.content);}
  navigation(doc,state.u.pathname);
  return {versi:1,alamat:address,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 window.PadiKerangkaUI=Object.freeze({versi:1,sumber:data.sumber,buat});
})();
