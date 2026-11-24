/* Public immutable structure; context/permission choices come from the document. */
(function(){
 'use strict';
 const data=window.PadiKerangkaUIData;
 if(data?.versi!==1||!data.variants||!data.styles||!data.scripts||typeof data.sumber!=='string')return;
 for(const component of Object.values(data.variants)){if(Array.isArray(component.statuses))Object.freeze(component.statuses);Object.freeze(component);}
 Object.freeze(data.variants);Object.freeze(data.styles);Object.freeze(data.scripts);Object.freeze(data);
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
 function jasa(address){
  const u=new URL(address,location.href),q=u.searchParams;
  if(u.origin!==location.origin||u.pathname!=='/jasa'||u.hash||u.search.length>3000||u.pathname+u.search!==address)return null;
  if(Array.from(q.keys()).some(k=>!['cari','status','halaman'].includes(k)||q.getAll(k).length!==1))return null;
  const search=(q.get('cari')||'').trim(),status=q.get('status')||'',page=q.get('halaman');
  if(search.length>200||!data.variants['jasa-admin']?.statuses.includes(status)||page&&(!/^[1-9]\d{0,9}$/.test(page)||Number(page)>2147483647))return null;
  return {u,search,status};
 }
 function stock(address){
  const u=new URL(address,location.href),q=u.searchParams;
  if(u.origin!==location.origin||u.pathname!=='/stok'||u.hash||u.search.length>3000||u.pathname+u.search!==address)return null;
  if(Array.from(q.keys()).some(k=>!['tab','pemilik','gudang','pelanggan_id','cari'].includes(k)||q.getAll(k).length!==1))return null;
  const tab=q.get('tab')??'bahan',owner=q.get('pemilik')??'semua',warehouse=q.get('gudang')||'',customer=q.get('pelanggan_id')||'',search=q.get('cari')||'';
  if(!['bahan','produk','karung'].includes(tab)||!['semua','pabrik','jasa'].includes(owner)||search.length>200||warehouse&&!['g1','g2'].includes(warehouse)&&!/^wh:[1-9]\d{0,9}$/.test(warehouse)||warehouse.startsWith('wh:')&&Number(warehouse.slice(3))>2147483647||customer&&(!/^[1-9]\d{0,9}$/.test(customer)||Number(customer)>2147483647||owner!=='jasa'))return null;
  return {u,tab,owner,warehouse,customer,search};
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
  const account=['/pengaturan/akun','/laporan'].includes(address)?{u:new URL(address,location.href)}:null;
  const state=shipping(address)||jasa(address)||account||stock(address);if(!state)return null;
  const family=state.u.pathname==='/laporan'?'laporan':state.u.pathname==='/stok'?'stok':state.u.pathname==='/jasa'?'jasa':state.u.pathname==='/pengaturan/akun'?'akun':'pengiriman';
  const host=document.getElementById('padi-kerangka-ui');let permission;
  if(!host?.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>4096)return null;
  try{permission=JSON.parse(host.textContent);}catch(_){return null;}
  if(permission?.versi!==1||permission.sumber!==data.sumber||permission.cap!==cap||permission.konteks!==context||permission.sesi!==token||!permission.varians||Object.keys(permission.varians).some(k=>!['pengiriman','jasa','akun','stok','laporan'].includes(k)))return null;
  const allowedStock=permission.varians.stok;
  if(family==='stok'&&(!allowedStock||typeof allowedStock!=='object'||Array.isArray(allowedStock)||Object.keys(allowedStock).some(k=>!['bahan','produk','karung'].includes(k))))return null;
  const key=family==='stok'?allowedStock[state.tab]:permission.varians[family];
  if(typeof key!=='string'||!own(data.variants,key))return null;
  const component=data.variants[key];if(component.path!==state.u.pathname||component.family!==family||typeof base!=='string')return null;
  const doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman');
  if(!frame||!main||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||doc.getElementById('formulir-sesi')?.dataset.token!==token)return null;
  const comments=Array.from(main.childNodes).filter(n=>n.nodeType===8),from=comments.find(n=>n.data.trim()==='isi-halaman:mulai'),to=comments.find(n=>n.data.trim()==='isi-halaman:akhir');
  if(!from||!to||!(from.compareDocumentPosition(to)&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attribute] of [['style[data-ui-style-ref]',data.styles,'data-ui-style-ref'],['script[data-ui-script-ref]',data.scripts,'data-ui-script-ref']]){
   for(const node of part.content.querySelectorAll(selector)){
    const key=node.getAttribute(attribute);if(!own(pool,key)||typeof pool[key]!=='string'||pool[key].length>524288)return null;
    node.textContent=pool[key];node.removeAttribute(attribute);
   }
  }

  const root=part.content.querySelector(family==='laporan'?'[data-laporan-katalog-kerangka]':family==='akun'?'[data-pengaturan-akun-kerangka]':family==='jasa'?'[data-jasa-bertahap]':'[data-halaman-bertahap][data-kind="'+family+'"]');if(!root)return null;
  root.dataset.stamp=context+'|'+address;root.dataset.url=['akun','laporan'].includes(family)?state.u.pathname:'/api/halaman-bertahap/'+family+state.u.search;
  if(family==='pengiriman'){

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
  }else if(family==='jasa'){
   root.dataset.filtered=state.search||state.status?'1':'0';
   for(const input of root.querySelectorAll('[name=cari]'))value(input,state.search);
   for(const input of root.querySelectorAll('input[name=status]'))value(input,state.status);
   const select=root.querySelector('select[name=status]');select.value=state.status;
   for(const option of select.options)option.toggleAttribute('selected',option.selected);
   const scope=root.querySelector('[data-ui-jasa-status]');scope.hidden=!state.status;
   scope.querySelector('strong').textContent=select.selectedOptions[0].textContent;
   const filter=root.querySelector('[data-js-buka="js-filter"]');filter.textContent='Filter'+(state.status?' · 1':'');
   root.querySelector('.js-form-filter>a[href]').setAttribute('href','/jasa?'+new URLSearchParams({cari:state.search}));
  }
  if(family==='stok'){
   if(component.tab!==state.tab)return null;
   const tabs=Object.keys(allowedStock);
   for(const tab of root.querySelectorAll('[data-ui-stock-tab]')){
    const kind=tab.dataset.uiStockTab;
    if(!tabs.includes(kind)){const span=doc.createElement('span');span.className='kontrol-tab__item akses-terkunci';span.textContent=tab.textContent;span.setAttribute('aria-disabled','true');span.title='Tidak tersedia pada gudang kerja ini';tab.replaceWith(span);continue;}
    const next=new URL(state.u);next.searchParams.set('tab',kind);tab.setAttribute('href',next.pathname+next.search);tab.removeAttribute('aria-disabled');tab.removeAttribute('tabindex');
   }
   for(const input of root.querySelectorAll('[name=cari]'))value(input,state.search);
   const ownerSelect=root.querySelector('select[name=pemilik]');ownerSelect.value=state.owner;
   for(const option of ownerSelect.options)option.toggleAttribute('selected',option.selected);
   for(const form of root.querySelectorAll('form')){
    for(const input of form.querySelectorAll('input[type=hidden]'))input.remove();
    const fields=new Set(Array.from(form.elements).filter(e=>e.name&&!e.disabled).map(e=>e.name));
    for(const [name,text] of [['tab',state.tab],['pemilik',state.owner],['gudang',state.warehouse],['pelanggan_id',state.customer],['cari',state.search]]){
     if(fields.has(name)||name==='pelanggan_id'&&!text)continue;
     const input=doc.createElement('input');input.type='hidden';input.name=name;value(input,text);form.append(input);
    }
   }
   root.querySelector('[data-stok-pelanggan]').hidden=state.owner!=='jasa';root.querySelector('#ui-stock-pelanggan_id-reason').hidden=state.owner!=='jasa';
   root.querySelector('.kontrol-pencarian>[data-sk-buka="sk-filter"]').textContent='Filter'+(state.owner!=='semua'||state.warehouse||state.customer?' · '+(Number(state.owner!=='semua')+Number(!!state.warehouse)+Number(!!state.customer)):'');
   const scope=root.querySelector('.sk-cakupan');scope.querySelector('strong').textContent=ownerSelect.selectedOptions[0].textContent;scope.lastChild.textContent=' · '+(state.warehouse?'Gudang terpilih · nama menunggu data':'Pilihan gudang belum dibaca');
   const history=root.querySelector('[data-ui-stock-ownership-href]');if(history){history.setAttribute('href','/kepemilikan?'+new URLSearchParams({kind:state.tab==='bahan'?'pk':state.tab,kembali_stok:address}));history.removeAttribute('aria-disabled');history.removeAttribute('tabindex');}
   const reset=new URL('/stok',location.href);reset.searchParams.set('tab',state.tab);reset.searchParams.set('pemilik','semua');if(state.search)reset.searchParams.set('cari',state.search);root.querySelector('.sk-form-filter>a[href]').setAttribute('href',reset.pathname+reset.search);
   root.dataset.filtered=state.owner!=='semua'||state.warehouse||state.customer||state.search?'1':'0';
  }
  while(from.nextSibling&&from.nextSibling!==to)from.nextSibling.remove();to.before(part.content);
  frame.dataset.pindahAlamat=address;doc.title=component.title+' · PT Hadi Mulya Utama';
  const label=main.querySelector('.bar__merek');if(label){label.textContent=component.title;label.setAttribute('aria-label',component.title);}
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const html=doc.createElement('template');html.innerHTML=component.breadcrumb;crumb.replaceChildren(html.content);}
  navigation(doc,state.u.pathname);
  return {versi:1,alamat:address,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 window.PadiKerangkaUI=Object.freeze({versi:1,sumber:data.sumber,buat});
})();
