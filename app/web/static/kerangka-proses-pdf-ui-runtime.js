/* Three native HTML PDF viewers. Public structure is never authority. */
(function(global){'use strict';
 const native=typeof module==='object'&&module.exports?require('./proses-pdf-native.js'):null;
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k),exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k)),sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 function address(value,origin){
  if(native)return native.address(value,origin);
  /*__PADI_NATIVE_VIEWER_ADDRESS__*/
 }
 function sourceState(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.length>4096)return null;
  let u;try{u=new URL(value,origin);decodeURIComponent(u.search);}catch(_){return null;}
  const m=/^\/riwayat-(giling|sosoh|pengeringan)\/([1-9][0-9]{0,9})$/.exec(u.pathname);
  if(u.origin!==origin||u.hash||u.pathname+u.search!==value||!m||Number(m[2])>2147483647||u.search.length>3001)return null;
  const q=[...u.searchParams],allowed=['tab_detail','halaman_jeda',...(m[1]==='giling'?['sebelum']:[]),...(m[1]==='pengeringan'?['halaman_ukur','halaman_dingin','kembali_kerja']:[])];
  if(new Set(q.map(([k])=>k)).size!==q.length||q.some(([k,v])=>!allowed.includes(k)||(k.startsWith('halaman_')&&!/^[1-9][0-9]{0,8}$/.test(v))||(k==='sebelum'&&v&&!/^-?[0-9]{1,10}$/.test(v))))return null;
  return {u,kind:m[1],id:Number(m[2]),parent:'/riwayat-'+m[1]};
 }
 function meta(m,origin){const s=m&&address(m.target,origin);return exact(m,['kind','id','kode','target'])&&Number.isInteger(m.id)&&m.id>0&&m.id<=2147483647&&typeof m.kode==='string'&&m.kode.length>0&&m.kode.length<=200&&s?.kind===m.kind&&s?.id===m.id;}
 function valid(data,p,ctx,cap,token,sourceSha,origin){
  if(!exact(data,['versi','sumber','variants','styles','scripts','navigation'])||data.versi!==1||!sha(data.sumber)||!exact(data.variants,['giling','sosoh','pengeringan'])||!['giling','sosoh','pengeringan'].every(k=>exact(data.variants[k],['html','breadcrumb','header','heading_parts','iframe_parts'])&&['html','breadcrumb','header'].every(f=>typeof data.variants[k][f]==='string'&&data.variants[k][f].length<=131072)&&['heading_parts','iframe_parts'].every(f=>Array.isArray(data.variants[k][f])&&data.variants[k][f].length===2&&data.variants[k][f].every(s=>typeof s==='string'&&s.length<=200)))||!['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=16&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144)))return false;
  if(!exact(data.navigation,['styles','script'])||!Array.isArray(data.navigation.styles)||data.navigation.styles.length!==2||data.navigation.styles.some(k=>typeof k!=='string'||!own(data.styles,k))||typeof data.navigation.script!=='string'||!own(data.scripts,data.navigation.script))return false;
  if(!exact(p,['versi','cap','konteks','sesi','sumber','source_address','sumber_sha256','entry'])||p.versi!==1||p.sumber!==data.sumber||p.cap!==cap||p.konteks!==ctx||p.sesi!==token||![ctx,cap,token].every(v=>typeof v==='string'&&v&&v.length<=2048)||!sha(sourceSha)||p.sumber_sha256!==sourceSha||!meta(p.entry,origin))return false;
  const source=sourceState(p.source_address,origin);return !!source&&source.kind===p.entry.kind&&source.id===p.entry.id&&p.entry.target===source.u.pathname+'/laporan';
 }
 function shown(n,style){return !!n&&n.isConnected!==false&&!n.closest('[hidden],[inert],[aria-hidden="true"]')&&n.getClientRects().length>0&&!['hidden','collapse'].includes(style(n).visibility);}
 function normalize(a,source,origin){try{const u=new URL(a.getAttribute('href'),origin+source);return u.origin===origin&&!u.hash?u.pathname+u.search:null;}catch(_){return null;}}
 function proof(p,target,source,doc,style,origin){
  if(source!==p.source_address||target!==p.entry.target)return null;
  const roots=doc.querySelectorAll('#isi-halaman [data-riwayat-'+p.entry.kind+']');if(roots.length!==1||!shown(roots[0],style))return null;
  const code=roots[0].querySelector('header .rhs-code');if(!code||code.textContent!==p.entry.kode)return null;
  const links=[...roots[0].querySelectorAll('.rhs-actions>a[href]')].filter(a=>normalize(a,source,origin)===target&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true'&&shown(a,style));
  return links.length===1?{visible:true,href:target,code:code.textContent}:null;
 }
 function select(p,target,source,proof){return source===p.source_address&&proof?.visible&&proof.href===target&&proof.code===p.entry.kode&&target===p.entry.target?p.entry:null;}
 function navigationClone(mainNow,doc,part,data,parent){
  const wrappers=mainNow.querySelectorAll('.laporan-riwayat');if(wrappers.length!==1)return null;
  const wrapper=doc.importNode(wrappers[0],true),inner=wrapper.querySelectorAll(':scope>.laporan-isi'),nav=wrapper.querySelectorAll('[data-laporan-kontrol]');
  if(inner.length!==1||nav.length!==1||nav[0].dataset.aktif!=='proses')return null;
  const select=nav[0].querySelector('select[data-jenis-riwayat]');if(!select||select.value!==parent)return null;
  inner[0].replaceChildren();
  if(wrapper.querySelector('form,input,textarea,[name],[data-post],[data-kirim],iframe'))return null;
  // The controls/allowed paths come from current native DOM, not role guesses.
  for(const node of wrapper.querySelectorAll('style,link[rel=stylesheet],script'))node.remove();
  delete nav[0].dataset.siap;
  for(const button of nav[0].querySelectorAll('[data-lk-cetak],[data-lk-buka]')){button.disabled=true;button.setAttribute('aria-describedby','status-bagikan');}
  for(const key of data.navigation.styles){const style=doc.createElement('style');style.textContent=data.styles[key];wrapper.prepend(style);}
  const script=doc.createElement('script');script.textContent=data.scripts[data.navigation.script];wrapper.append(script);
  inner[0].append(part);return wrapper;
 }
 function chrome(main,doc,component,detail,code){
  const row=main.querySelector('.desktop-chrome__crumbrow'),bar=main.querySelector('header.bar');if(!row||!bar)return false;
  const fragment=doc.createElement('template');fragment.innerHTML=component.breadcrumb;
  const current=fragment.content.querySelectorAll('[aria-current=page]'),links=fragment.content.querySelectorAll('a[href="__PADI_DETAIL__"]');
  if(current.length!==1||links.length!==2||current[0].textContent!=='Laporan __PADI_CODE__'||fragment.content.querySelector('script,form,input,button'))return false;
  current[0].textContent='Laporan '+code;for(const a of links)a.setAttribute('href',detail);row.replaceChildren(fragment.content);
  const control=doc.createElement('template');control.innerHTML=component.header;
  if(control.content.querySelectorAll('button.bar__menu#buka-laci').length!==1||control.content.querySelector('a,script,form,input'))return false;
  main.querySelectorAll('.bar__menu,.bar__balik').forEach(n=>n.remove());bar.prepend(control.content);
  const title=bar.querySelector('.bar__merek');if(!title)return false;title.textContent='Laporan '+code;title.setAttribute('aria-label','Laporan '+code);return true;
 }
 function buat(target,base,ctx,cap,token){try{
  const source=location.pathname+location.search,current=document.querySelector('.bingkai'),mainNow=document.getElementById('isi-halaman'),sessionNow=document.getElementById('formulir-sesi');
  if(typeof base!=='string'||base.length>8388608||/<iframe[\s>]/i.test(base)||!address(target,location.origin)||document.querySelector('dialog[open],.riwayat-koreksi[open]')||document.body.hasAttribute('data-portal-akun')||document.body.classList.contains('portal-customer'))return null;
  if(document.querySelectorAll('.bingkai').length!==1||document.querySelectorAll('#isi-halaman').length!==1||document.querySelectorAll('#formulir-sesi').length!==1||!current.contains(mainNow)||!current.contains(sessionNow)||current.dataset.pindahAlamat!==source||current.dataset.pindahKonteks!==ctx||document.documentElement.dataset.versi!==cap||sessionNow.dataset.token!==token)return null;
  const hosts=document.querySelectorAll('#padi-proses-pdf-catalog');if(hosts.length!==1)return null;const host=hosts[0];if(!host.isConnected||!mainNow.contains(host)||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.dataset.sourceAddress!==source||host.textContent.length>8192)return null;
  const p=JSON.parse(host.textContent),data=global.PadiKerangkaProsesPDFData;
  if(!valid(data,p,ctx,cap,token,host.dataset.sourceSha,location.origin))return null;
  const entry=select(p,target,source,proof(p,target,source,document,n=>getComputedStyle(n),location.origin));if(!entry)return null;
  const state=address(target,location.origin),doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==ctx||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const component=data.variants[entry.kind],part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attr]of[['style[data-ppv-style]',data.styles,'data-ppv-style'],['script[data-ppv-script]',data.scripts,'data-ppv-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-proses-pdf-kerangka]');if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[data-post],[data-kirim],iframe[src],iframe[srcdoc],script[src],link[rel=stylesheet]'))return null;
  const root=roots[0];root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;
  root.querySelector('[data-ppv-heading]').textContent=component.heading_parts.join(entry.kode);root.querySelector('[data-ppv-title]').setAttribute('title',component.iframe_parts.join(entry.kode));
  const wrapper=navigationClone(mainNow,doc,part.content,data,state.parent);if(!wrapper)return null;
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(wrapper);
  if(!chrome(main,doc,component,state.detail,entry.kode))return null;
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title='Laporan '+entry.kode+' · PT Hadi Mulya Utama';return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }catch(_){return null;}}
 if(typeof module==='object'&&module.exports){module.exports={address,sourceState,meta,valid,shown,normalize,proof,select,navigationClone,chrome};return;}
 global.PadiKerangkaProsesPDFUI=Object.freeze({versi:1,sumber:global.PadiKerangkaProsesPDFData?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
