/* Two native Settings structures. Metadata is presentation, never authority. */
(function(global){
 'use strict';
 const PATHS=['/pengaturan','/pengaturan/sesi'];
 const GROUPS={akun:[3],fasilitas:[5,6],operasional:[4],pengguna:[2],sistem:[3,4]};
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x);
 const exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>Object.prototype.hasOwnProperty.call(x,k));
 function validURL(value){try{const u=new URL(value);return u.protocol==='https:'&&!!u.hostname&&!u.username&&!u.password&&!u.search&&!u.hash&&value.length<=2048;}catch(_){return false;}}
 function valid(data,p,context,cap,token){
  if(!exact(data,['versi','sumber','variants','styles','scripts'])||data.versi!==1||!/^[a-f0-9]{64}$/.test(data.sumber)
   ||!exact(data.variants,PATHS)||!['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=16&&Object.values(data[k]).every(s=>typeof s==='string'&&s.length<=131072))
   ||!PATHS.every(path=>exact(data.variants[path],['title','html','breadcrumb','mobile'])&&typeof data.variants[path].title==='string'&&data.variants[path].title.length>0&&data.variants[path].title.length<=200&&['html','breadcrumb','mobile'].every(k=>typeof data.variants[path][k]==='string'&&data.variants[path][k].length<=65536))
   ||!exact(p,['versi','cap','konteks','sesi','sumber','groups','advanced','recovery','short','console'])||p.versi!==1
   ||p.cap!==cap||p.konteks!==context||p.sesi!==token||p.sumber!==data.sumber||![context,cap,token].every(x=>typeof x==='string'&&x)
   ||!['advanced','recovery','short'].every(k=>typeof p[k]==='boolean')||typeof p.console!=='string'||p.console&&!validURL(p.console)
   ||!obj(p.groups)||Object.keys(p.groups).some(k=>!Object.prototype.hasOwnProperty.call(GROUPS,k))
   ||!['akun','fasilitas','pengguna','sistem'].every(k=>Object.prototype.hasOwnProperty.call(p.groups,k)))return false;
  return Object.entries(p.groups).every(([key,flags])=>Array.isArray(flags)&&GROUPS[key].includes(flags.length)&&flags.every(f=>typeof f==='boolean'))
   &&p.groups.fasilitas.length===(p.console?6:5);
 }
 function lock(doc,node){
  const span=doc.createElement('span');span.className=node.className+' akses-terkunci';span.setAttribute('aria-disabled','true');span.title='Tidak memiliki akses untuk peran ini';
  while(node.firstChild)span.append(node.firstChild);node.replaceWith(span);
 }
 function prune(doc,root,p,path){
  if(path==='/pengaturan/sesi'){
   root.querySelector('.btn--utama').textContent=p.short?'Ganti pengguna':'Keluar';return;
  }
  for(const group of root.querySelectorAll('[data-settings-group]')){
   const flags=p.groups[group.dataset.settingsGroup];if(!flags){group.remove();continue;}
   let doors=[...group.querySelectorAll('[data-settings-door]')];
   const consoleDoor=doors.find(a=>a.getAttribute('href')==='https://console.invalid/console');
   if(consoleDoor){if(p.console)consoleDoor.setAttribute('href',p.console);else{consoleDoor.remove();doors=doors.filter(a=>a!==consoleDoor);}}
   if(group.dataset.settingsGroup==='sistem'&&flags.length===3){doors.pop().remove();}
   if(doors.length!==flags.length)throw Error('Settings native slots changed');
   if(group.dataset.settingsGroup==='sistem'&&!flags[1])group.querySelector('header p').textContent='Informasi aplikasi';
   doors.forEach((node,i)=>{if(!flags[i])lock(doc,node);});
  }
  const advanced=root.querySelector('.pg-lanjutan .pg-pintu');if(advanced&&!p.advanced)lock(doc,advanced);
  if(!p.recovery)root.querySelector('.pg-darurat')?.remove();
 }
 if(typeof module==='object'&&module.exports){module.exports={valid,validURL,prune};return;}
 const data=global.PadiKerangkaPengaturanData;
 function buat(target,base,context,cap,token){
  if(!PATHS.includes(target)||typeof base!=='string'||base.length>8388608)return null;
  const hosts=document.querySelectorAll('#padi-pengaturan-kerangka');if(hosts.length!==1)return null;
  const host=hosts[0];if(!host.isConnected||host.dataset.cap!==cap||host.dataset.konteks!==context||host.textContent.length>4096)return null;
  let p;try{p=JSON.parse(host.textContent);}catch(_){return null;}
  if(!valid(data,p,context,cap,token))return null;
  const doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||!frame.contains(main)||!frame.contains(session)
   ||frame.dataset.pindahKonteks!==context||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');
  if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const part=doc.createElement('template'),component=data.variants[target];part.innerHTML=component.html;
  for(const [selector,pool,attr] of [['style[data-settings-style]',data.styles,'data-settings-style'],['script[data-settings-script]',data.scripts,'data-settings-script']]){
   for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!Object.prototype.hasOwnProperty.call(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  }
  const roots=part.content.querySelectorAll('[data-pengaturan-menu-kerangka]');if(roots.length!==1||part.content.querySelector('form,input,[name],[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;
  const root=roots[0];try{prune(doc,root,p,target);}catch(_){return null;}
  root.dataset.url=target;root.dataset.stamp=context+'|'+target;
  const [from,to]=[starts[0],ends[0]];while(from.nextSibling&&from.nextSibling!==to)from.nextSibling.remove();to.before(part.content);
  const top=main.querySelector('header.bar'),title=top?.querySelector('.bar__merek'),crumb=main.querySelector('.desktop-chrome__crumbrow');
  if(!top||!title||!crumb)return null;
  const control=doc.createElement('template');control.innerHTML=component.mobile;
  if(control.content.querySelectorAll('#buka-laci.bar__menu[type=button]').length!==1||control.content.querySelector('a,form,input,script,[name]'))return null;
  const trail=doc.createElement('template');trail.innerHTML=component.breadcrumb;
  if(trail.content.querySelectorAll('nav.desktop-breadcrumb').length!==1||trail.content.querySelectorAll('a.desktop-back').length!==1||trail.content.querySelector('form,input,script,[name]'))return null;
  for(const old of top.querySelectorAll('.bar__menu,.bar__balik'))old.remove();top.prepend(control.content);
  title.textContent=component.title;title.setAttribute('aria-label',component.title);crumb.replaceChildren(trail.content);
  for(const old of doc.querySelectorAll('#padi-pengaturan-kerangka'))old.remove();doc.body.append(doc.importNode(host,true));
  for(const a of doc.querySelectorAll('#laci a[href]')){const active=a.getAttribute('href')==='/pengaturan';a.classList.toggle('pintu--kini',active&&a.classList.contains('pintu'));a.classList.toggle('pintu-sub__satu--kini',active&&a.classList.contains('pintu-sub__satu'));if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title=component.title+' · PT Hadi Mulya Utama';
  return {versi:1,alamat:target,konteks:context,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }
 global.PadiKerangkaPengaturanUI=Object.freeze({versi:1,buat});
})(typeof window==='undefined'?globalThis:window);
