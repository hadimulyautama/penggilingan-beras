/* Read-only customer detail structure. Every data GET retains native guards. */
(function(global){
 'use strict';
 const obj=v=>v&&typeof v==='object'&&!Array.isArray(v);
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/pelanggan/')||value.length>4096)return null;
  let u;try{u=new URL(value,origin);decodeURIComponent(u.search);}catch(_){return null;}
  if(u.origin!==origin||u.pathname+u.search+u.hash!==value)return null;
  let kind,resource,m;
  if((m=u.pathname.match(/^\/pelanggan\/proses-aktif\/giling\/([A-Za-z0-9_-]{1,100})$/))){kind='giling';resource=m[1];}
  else if((m=u.pathname.match(/^\/pelanggan\/riwayat-giling\/([1-9][0-9]{0,9})$/))){kind='giling-riwayat';resource=m[1];if(Number(resource)>2147483647)return null;}
  else if((m=u.pathname.match(/^\/pelanggan\/barang-masuk\/([1-9][0-9]{0,9})$/))){kind='penerimaan';resource=m[1];}
  else return null;
  const pairs=[...u.searchParams],q=Object.fromEntries(pairs),tabs=kind==='giling'?['ringkasan','bahan','hasil','riwayat']:kind==='giling-riwayat'?['ringkasan','bahan','hasil','qc','riwayat']:['ringkasan','tiket','qc','riwayat'];
  const keys=['tab_detail','pelanggan_id','pemilik','kepemilikan',...(kind==='giling'?['halaman_hasil','halaman_qc','halaman_jeda']:kind==='giling-riwayat'?['halaman_jeda','sebelum']:[])];
  if(pairs.length>9||Object.keys(q).length!==pairs.length||pairs.some(([k])=>!keys.includes(k)))return null;
  for(const[k,v]of pairs){if((k==='pelanggan_id'||k.startsWith('halaman_'))&&(!/^[1-9][0-9]{0,9}$/.test(v)||Number(v)>2147483647))return null;if(['pemilik','kepemilikan'].includes(k)&&v!=='jasa')return null;}
  if('sebelum'in q&&!/^-?[0-9]{1,10}$/.test(q.sebelum))return null;
  const tab=q.tab_detail||'ringkasan',prefix=kind==='giling'?'#panel-':kind==='giling-riwayat'?'#rhs-panel-':null;
  if(!tabs.includes(tab)||u.hash&&(!prefix||u.hash!==prefix+tab))return null;
  return{kind,resource,address:u.pathname+u.search,hash:u.hash,tab};
 }
 function valid(c,p,cap,account,session){
  if(!obj(c)||Object.keys(c).sort().join(',')!=='address,akun,cap,entries,sesi,sumber,versi'||c.versi!==1||c.sumber!==p.sumber||c.cap!==cap||c.akun!==account||c.sesi!==session||!cap||!session||!/^[1-9][0-9]*$/.test(account)||typeof c.address!=='string'||!c.address.startsWith('/pelanggan')||!Array.isArray(c.entries)||c.entries.length>50)return false;
  return c.entries.every(e=>obj(e)&&Object.keys(e).sort().join(',')==='code,heading,kind,resource,targets,title'&&['giling','giling-riwayat','penerimaan'].includes(e.kind)&&[e.code,e.heading,e.title,e.resource].every(v=>typeof v==='string'&&v.length>0&&v.length<=180)&&Array.isArray(e.targets)&&e.targets.length>0&&e.targets.length<=12&&new Set(e.targets).size===e.targets.length&&e.targets.every(v=>{const a=address(v,'https://portal.invalid');return a&&a.kind===e.kind&&a.resource===e.resource;}));
 }
 if(typeof module==='object'&&module.exports){module.exports={address,valid};return;}
 const data=global.PadiKerangkaPortalDetailData;if(!obj(data)||data.versi!==1||!/^[a-f0-9]{64}$/.test(data.sumber))return;
 function state(value){
  const a=address(value,location.origin),hosts=document.querySelectorAll('#padi-portal-detail-catalog');
  if(!a||hosts.length!==1||hosts[0].textContent.length>65536)return null;
  const cap=document.documentElement.dataset.portalCap,account=document.body.dataset.portalAkun,session=document.querySelector('meta[name="formulir-sesi"]')?.content;
  let c;try{c=JSON.parse(hosts[0].textContent);}catch(_){return null;}
  if(!valid(c,data,cap,account,session))return null;
  const current=location.pathname+location.search,frame=hosts[0].closest('[data-portal-detail-frame]');
  if(c.address!==current&&(!frame||frame.dataset.portalDetailAddress!==current||frame.dataset.portalDetailSource!==c.address))return null;
  const e=c.entries.find(e=>e.kind===a.kind&&e.resource===a.resource&&e.targets.includes(value));if(!e)return null;
  // Exact projected native link, or this same resource's program-built frame.
  const link=[...document.querySelectorAll('a[href]')].find(n=>n.getAttribute('href')===value&&!n.closest('[hidden]'));
  if(!link||!link.isConnected||(!frame&&(!link.getClientRects().length||getComputedStyle(link).visibility==='hidden')))return null;
  return{a,c,e};
 }
 function buat(value){
  const s=state(value);if(!s)return null;
  const t=document.createElement('template');t.innerHTML=data.variants[s.a.kind];
  const root=t.content.querySelector('[data-portal-detail-frame]');if(!root||t.content.querySelector('script,iframe,form,input,[data-post],[data-kirim]'))return null;
  root.dataset.portalAddress=s.a.address;root.dataset.portalDetailAddress=s.a.address;root.dataset.portalDetailSource=s.c.address;
  root.querySelector('[data-portal-detail-heading]').textContent=s.e.heading;root.querySelector('[data-portal-detail-code]').textContent=s.e.code;
  for(const n of root.querySelectorAll('[data-portal-detail-panel]'))n.hidden=n.dataset.portalDetailPanel!==s.a.tab;
  for(const n of root.querySelectorAll('[data-portal-detail-tab]')){
   const key=n.dataset.portalDetailTab;n.setAttribute('aria-selected',String(key===s.a.tab));
   const target=s.e.targets.find(v=>address(v,location.origin).tab===key);
   if(target){const link=document.createElement('a');for(const attr of n.attributes)if(!['disabled','type','aria-describedby'].includes(attr.name))link.setAttribute(attr.name,attr.value);link.setAttribute('href',target);link.textContent=n.textContent;n.replaceWith(link);}
  }
  const inert=document.createElement('script');inert.type='application/json';inert.id='padi-portal-detail-catalog';inert.textContent=JSON.stringify({...s.c,entries:[s.e]});root.append(inert);
  return{html:root.outerHTML,title:s.e.title,address:s.a.address,hash:s.a.hash};
 }
 // Cache policy only: recognizing a read URL never grants its framework or
 // resource. Exact catalog + visible-link proof remains mandatory in state.
 global.PadiKerangkaPortalDetailUI=Object.freeze({buat,siap:value=>!!state(value),freshOnly:value=>!!address(value,location.origin)});
})(typeof window==='undefined'?globalThis:window);
