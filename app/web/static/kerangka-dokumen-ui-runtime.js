/* Data-free report framework. Fresh native GET still owns every data decision. */
(function(global){
 'use strict';
 const CODES=['gabah_masuk','pk_masuk','penyosohan','penggilingan','pengeringan','pemasukan_pk','pindah_pk','pengemasan','kemas_ulang','barang_keluar','retur_pelanggan','retur_pk'];
 const PERIODS=['hari_ini','kemarin','minggu_ini','bulan_ini','30_hari','3_bulan','tahun_ini','tahun_lalu','semua'];
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k);
 const exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k));
 function date(value){if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)||value.startsWith('0000'))return false;try{return new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;}catch(_){return false;}}
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//'))return null;
  let u;try{u=new URL(value,origin);}catch(_){return null;}
  const code=u.pathname.slice('/laporan/'.length),pairs=[...u.searchParams],q=u.searchParams,period=q.get('periode')||'bulan_ini';
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||!u.pathname.startsWith('/laporan/')||!CODES.includes(code)||u.search.length>2049||pairs.length>3||new Set(pairs.map(x=>x[0])).size!==pairs.length||pairs.some(x=>!['periode','dari','sampai'].includes(x[0]))||![...PERIODS,'khusus'].includes(period))return null;
  if(['dari','sampai'].some(k=>q.has(k)&&!date(q.get(k))))return null;
  if(period==='khusus'&&(!date(q.get('dari'))||!date(q.get('sampai'))||q.get('dari')>q.get('sampai')||q.get('sampai')==='9999-12-31'))return null;
  return {u,code,period};
 }
 function valid(data,p,ctx,cap,token){
  if(!exact(data,['versi','sumber','variants','styles','scripts'])||data.versi!==1||typeof data.sumber!=='string'||!/^[a-f0-9]{64}$/.test(data.sumber)||!exact(data.variants,CODES.map(c=>'/laporan/'+c))
   ||!CODES.every(c=>{const v=data.variants['/laporan/'+c];return exact(v,['title','html','columns'])&&typeof v.title==='string'&&typeof v.html==='string'&&v.html.length<=131072&&Number.isInteger(v.columns)&&v.columns>0&&v.columns<=32;})
   ||!['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=32&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144))
   ||!exact(p,['versi','sumber','cap','konteks','sesi','laporan'])||p.versi!==1||p.sumber!==data.sumber||p.cap!==cap||p.konteks!==ctx||p.sesi!==token||![ctx,cap,token].every(v=>typeof v==='string'&&v)
   ||!exact(p.laporan,['targets','choices','rentang'])||!Array.isArray(p.laporan.targets)||!p.laporan.targets.length||p.laporan.targets.length>12||new Set(p.laporan.targets).size!==p.laporan.targets.length||p.laporan.targets.some(c=>!CODES.includes(c))
   ||!Array.isArray(p.laporan.choices)||!p.laporan.choices.length||p.laporan.choices.length>13||new Set(p.laporan.choices).size!==p.laporan.choices.length||p.laporan.choices.some(c=>![...CODES,'transfer_pk'].includes(c))||p.laporan.targets.some(c=>!p.laporan.choices.includes(c))
   ||!exact(p.laporan.rentang,PERIODS))return false;
  return Object.values(p.laporan.rentang).every(r=>exact(r,['dari','sampai'])&&date(r.dari)&&date(r.sampai)&&r.dari<=r.sampai);
 }
 function back(doc,href){
  const target=new URL(href,location.href);if(target.origin!==location.origin||!href.startsWith('/')||href.startsWith('//')||target.hash)return false;
  const bar=doc.querySelector('#isi-halaman>.bar');if(!bar)return false;
  const a=doc.createElement('a');a.className='bar__balik';a.href=href;a.setAttribute('aria-label','Kembali');
  // Native base back icon. No label or account information is inferred.
  a.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"></path></svg>';
  const old=bar.querySelector('.bar__menu,.bar__balik');if(old)old.replaceWith(a);else bar.prepend(a);
  return true;
 }
 if(typeof module==='object'&&module.exports){module.exports={address,valid,date};return;}
 const data=global.PadiKerangkaDokumenData;
 function buat(target,base,ctx,cap,token){
  const state=address(target,location.origin);if(!state||typeof base!=='string'||base.length>8388608)return null;
  const hosts=document.querySelectorAll('#padi-dokumen-kerangka');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>8192)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}
  if(!valid(data,p,ctx,cap,token)||!p.laporan.targets.includes(state.code))return null;
  const doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==ctx||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const component=data.variants[state.u.pathname],part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attr] of [['style[data-document-style]',data.styles,'data-document-style'],['script[data-document-script]',data.scripts,'data-document-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-laporan-detail-native]');if(roots.length!==1||part.content.querySelector('[data-post],[data-kirim],#laporan-data,script[src],link[rel=stylesheet]'))return null;
  const root=roots[0],forms=root.querySelectorAll('form');if(forms.length!==1||forms[0].getAttribute('method')!=='get'||forms[0].getAttribute('action')!==state.u.pathname)return null;
  if([...forms[0].querySelectorAll('[name]')].some(n=>!['periode','dari','sampai'].includes(n.name)))return null;
  for(const option of root.querySelectorAll('[data-lp-proses] option'))if(!p.laporan.choices.includes(option.value.slice('/laporan/'.length)))option.remove();
  const custom=state.period==='khusus',range=custom?{dari:state.u.searchParams.get('dari'),sampai:state.u.searchParams.get('sampai')}:p.laporan.rentang[state.period];
  for(const option of root.querySelectorAll('select[name=periode] option'))option.toggleAttribute('selected',option.value===state.period);
  for(const name of ['dari','sampai']){const input=root.querySelector('input[name='+name+']');input.setAttribute('value',range[name]);input.toggleAttribute('disabled',!custom);input.toggleAttribute('required',custom);}
  root.querySelector('.lp-rentang').hidden=!custom;root.querySelector('.lp-tampilkan').hidden=!custom;
  root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;
  const [from,to]=[starts[0],ends[0]];while(from.nextSibling&&from.nextSibling!==to)from.nextSibling.remove();to.before(part.content);
  if(!back(doc,'/laporan'))return null;
  for(const old of main.querySelectorAll('.desktop-back'))old.remove();
  const title=main.querySelector('.bar__merek');if(title){title.textContent=component.title;title.setAttribute('aria-label',component.title);}
  const crumb=main.querySelector('.desktop-chrome__crumbrow');if(crumb){const a=doc.createElement('a'),name=doc.createElement('strong');a.href='/laporan';a.textContent='Laporan periode';name.textContent=component.title;crumb.replaceChildren(a,doc.createTextNode(' › '),name);}
  for(const old of doc.querySelectorAll('#padi-dokumen-kerangka'))old.remove();doc.body.append(doc.importNode(host,true));
  for(const a of doc.querySelectorAll('#laci a[href]')){const active=a.getAttribute('href')==='/laporan';a.classList.toggle('pintu--kini',active&&a.classList.contains('pintu'));a.classList.toggle('pintu-sub__satu--kini',active&&a.classList.contains('pintu-sub__satu'));if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;doc.title=component.title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 global.PadiKerangkaDokumenUI=Object.freeze({versi:1,sumber:data?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
