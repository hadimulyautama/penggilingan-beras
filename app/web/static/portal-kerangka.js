/* Public portal menu structure. Identity and all rows stay in private GETs. */
(function(global){
 'use strict';
 const paths=['/ringkasan','/barang-masuk','/barang-saya','/jasa-saya','/riwayat-proses','/barang-keluar','/laporan'];
 const obj=v=>v&&typeof v==='object'&&!Array.isArray(v);
 const exact=(v,names)=>obj(v)&&Object.keys(v).length===names.length&&names.every(k=>Object.prototype.hasOwnProperty.call(v,k));
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/pelanggan')||value.startsWith('//')||value.length>2300)return null;
  let u;try{u=new URL(value,origin);decodeURIComponent(u.search);}catch(_){return null;}
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value)return null;
  const path=['/pelanggan','/pelanggan/'].includes(u.pathname)?'/ringkasan':u.pathname.startsWith('/pelanggan/')?u.pathname.slice('/pelanggan'.length):'';
  if(!paths.includes(path)||u.search.length>2049)return null;
  const filters=path==='/barang-masuk'?['jenis','cari','halaman']:['/riwayat-proses','/laporan'].includes(path)?['jenis','q','halaman']:path==='/barang-keluar'?['q','status','sejak','sebelum']:[];
  const pairs=[...u.searchParams];if(pairs.length>6||new Set(pairs.map(x=>x[0])).size!==pairs.length||pairs.some(([k])=>!filters.includes(k)))return null;
  const q=Object.fromEntries(pairs);
  for(const [key,limit]of[['cari',200],['q',120],['jenis',80],['status',40]])if((q[key]||'').length>limit)return null;
  for(const key of ['halaman','sebelum'])if(key in q&&(!/^[0-9]+$/.test(q[key])||Number(q[key])<1||Number(q[key])>2147483647))return null;
  if(q.sejak){const d=new Date(q.sejak+'T00:00:00Z');if(!/^\d{4}-\d{2}-\d{2}$/.test(q.sejak)||q.sejak.startsWith('0000')||!Number.isFinite(d.getTime())||d.toISOString().slice(0,10)!==q.sejak)return null;}
  return {path,address:value,q};
 }
 function valid(data,binding,cap,account,session){
  return exact(data,['versi','sumber','schemas','variants'])&&data.versi===1&&/^[a-f0-9]{64}$/.test(data.sumber)&&exact(data.schemas,paths)&&exact(data.variants,paths)
   &&paths.every(p=>typeof data.variants[p]==='string'&&data.variants[p].length>0&&data.variants[p].length<65536&&obj(data.schemas[p]))
   &&exact(binding,['versi','sumber','cap','akun','sesi','menus'])&&binding.versi===1&&binding.sumber===data.sumber&&binding.cap===cap&&binding.akun===account&&binding.sesi===session
   &&[cap,account,session].every(v=>typeof v==='string'&&v.length>0&&v.length<2048)&&/^[1-9][0-9]*$/.test(account)
   &&Array.isArray(binding.menus)&&binding.menus.length===paths.length&&new Set(binding.menus).size===paths.length&&binding.menus.every(p=>typeof p==='string'&&paths.includes(p.slice('/pelanggan'.length))&&p.startsWith('/pelanggan/'));
 }
 function filterDirty(root){return !!root&&Array.from(root.querySelectorAll('[data-portal-filter-initial]')).some(n=>n.value!==n.getAttribute('data-portal-filter-initial'));}
 if(typeof module==='object'&&module.exports){module.exports={address,valid,filterDirty};return;}
 const data=global.PadiKerangkaPortalData;if(!obj(data))return;
 function state(value){
  const s=address(value,location.origin),hosts=document.querySelectorAll('#padi-portal-kerangka'),cap=document.documentElement.dataset.portalCap,account=document.body.dataset.portalAkun,session=document.querySelector('meta[name="formulir-sesi"]')?.content;
  if(!s||hosts.length!==1||!hosts[0].isConnected||hosts[0].textContent.length>8192)return null;
  let binding;try{binding=JSON.parse(hosts[0].textContent);}catch(_){return null;}
  if(!valid(data,binding,cap,account,session))return null;
  // These seven menu doors are always native CustomerReader navigation.
  // Sidebar closes before delegated click on HP; DOM presence is required,
  // not computed visibility after that close. No resource ID is granted.
  const links=[...document.querySelectorAll('.portal-sidebar nav a[href]')].map(a=>a.getAttribute('href'));
  if(!binding.menus.every(p=>links.includes(p)))return null;
  return s;
 }
 function buat(value){
  const s=state(value);if(!s)return null;
  const part=document.createElement('template');part.innerHTML=data.variants[s.path];
  const roots=part.content.querySelectorAll('[data-portal-native-frame]');if(roots.length!==1||part.content.querySelector('script,iframe,[data-post],[data-kirim],form[method=post],[name=_csrf]'))return null;
  const root=roots[0];root.dataset.portalAddress=s.address;
  for(const field of root.querySelectorAll('[data-portal-filter-initial]')){
   let value=s.q[field.name]||'';
   if(field.tagName==='SELECT'&&!Array.from(field.options).some(o=>o.value===value))value='';
   field.value=value;field.setAttribute('data-portal-filter-initial',value);
   if(field.tagName==='SELECT')for(const option of field.options)option.toggleAttribute('selected',option.selected);else field.setAttribute('value',value);
  }
  return {html:root.outerHTML,title:root.querySelector('h1').textContent,address:s.address};
 }
 function freshDocument(doc){
  const old=document.querySelector('#padi-portal-kerangka'),next=doc.querySelector('#padi-portal-kerangka');
  if(!old||!next||doc.documentElement.dataset.portalCap!==document.documentElement.dataset.portalCap||doc.body.dataset.portalAkun!==document.body.dataset.portalAkun||doc.querySelector('meta[name="formulir-sesi"]')?.content!==document.querySelector('meta[name="formulir-sesi"]')?.content)return false;
  let before,after;try{before=JSON.parse(old.textContent);after=JSON.parse(next.textContent);}catch(_){return false;}
  return valid(data,after,doc.documentElement.dataset.portalCap,doc.body.dataset.portalAkun,doc.querySelector('meta[name="formulir-sesi"]')?.content)&&before.cap===after.cap&&before.sesi===after.sesi&&before.akun===after.akun;
 }
 global.PadiKerangkaPortalUI=Object.freeze({buat,siap:value=>!!state(value),freshDocument,filterDirty});
})(typeof window==='undefined'?globalThis:window);
