/* Public final journey structure, never a grant or a dynamic customer DTO. */
(function(global){'use strict';
 const native=typeof module==='object'&&module.exports?require('./riwayat-pengiriman-native.js'):null;
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k),exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k)),sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 function address(value,origin){
  if(native)return native.address(value,origin);
  const core={sameOriginAddress(v,o){try{const u=new URL(v,o);return typeof v==='string'&&v.startsWith('/')&&!v.startsWith('//')&&u.origin===o&&!u.hash&&u.pathname+u.search===v;}catch(_){return false;}}};
  /*__PADI_NATIVE_READ_ADDRESS__*/
 }
 function meta(m){return exact(m,['id','kode','status','title','bersama','tiket','review'])&&Number.isInteger(m.id)&&m.id>0&&m.id<=2147483647&&['selesai','batal'].includes(m.status)&&['kode','title'].every(k=>typeof m[k]==='string'&&m[k]&&m[k].length<=200)&&['bersama','tiket','review'].every(k=>typeof m[k]==='boolean');}
 function navigation(n,origin){
  if(!exact(n,['body_back','header_back','chrome_back']))return false;
  const safe=value=>{if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.length>4096||/[\\\r\n]/.test(value))return null;try{const u=new URL(value,origin);return u.origin===origin&&u.pathname+u.search+u.hash===value?u:null;}catch(_){return null;}};
  const body=safe(n.body_back),chrome=safe(n.chrome_back),header=n.header_back===null?null:safe(n.header_back);
  return body?.pathname==='/barang-keluar'&&body.hash==='#judul-riwayat-keluar'&&chrome?.pathname==='/barang-keluar'&&!chrome.hash&&(n.header_back===null||!!header&&!header.hash&&['/barang-masuk','/pekerjaan','/kabar'].includes(header.pathname));
 }
 function valid(data,p,ctx,cap,token,sourceSha,origin){
  if(!exact(data,['versi','sumber','variants','styles','scripts'])||data.versi!==1||!sha(data.sumber)||!exact(data.variants,['read','review'])||!['read','review'].every(k=>exact(data.variants[k],['html','breadcrumb','header_menu','header_back'])&&typeof data.variants[k].html==='string'&&data.variants[k].html.length<=131072&&['breadcrumb','header_menu','header_back'].every(f=>typeof data.variants[k][f]==='string'&&data.variants[k][f].length<=65536))||!['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=16&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144)))return false;
  if(!exact(p,['versi','cap','konteks','sesi','sumber','source_address','sumber_sha256','entries'])||p.versi!==1||p.sumber!==data.sumber||p.cap!==cap||p.konteks!==ctx||p.sesi!==token||![ctx,cap,token].every(v=>typeof v==='string'&&v&&v.length<=2048)||!sha(sourceSha)||p.sumber_sha256!==sourceSha||typeof p.source_address!=='string'||p.source_address.length>4096||!Array.isArray(p.entries)||!p.entries.length||p.entries.length>50)return false;
  let source;try{source=new URL(p.source_address,origin);}catch(_){return false;}
  if(source.origin!==origin||source.hash||source.pathname!=='/barang-keluar'||source.pathname+source.search!==p.source_address)return false;
  return new Set(p.entries.map(e=>e?.meta?.id)).size===p.entries.length&&p.entries.every(e=>exact(e,['meta','target','nav'])&&meta(e.meta)&&navigation(e.nav,origin)&&address(e.target,origin)?.id===e.meta.id&&e.nav.header_back===null);
 }
 function shown(node,style){return !!node&&node.isConnected!==false&&!node.closest('[hidden],[inert],[aria-hidden="true"]')&&node.getClientRects().length>0&&!['hidden','collapse'].includes(style(node).visibility);}
 function normalize(link,source,origin){try{const u=new URL(link.getAttribute('href'),origin+source);return u.origin===origin&&!u.hash?u.pathname+u.search:null;}catch(_){return null;}}
 function proof(p,target,source,doc,style,origin){
  if(source!==p.source_address)return null;
  const eligible=a=>normalize(a,source,origin)===target&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true'&&shown(a,style);
  const rows=[...doc.querySelectorAll('#isi-halaman section[aria-labelledby="judul-riwayat-keluar"] tr[data-detail-keluar]')].filter(r=>shown(r,style)&&r.getAttribute('data-detail-keluar')===target);
  if(rows.length!==1)return null;const links=[...rows[0].querySelectorAll('td:first-child>a[href]')].filter(eligible);
  return links.length===1?{href:target,code:links[0].textContent,visible:true}:null;
 }
 function select(p,target,source,proof){return source===p.source_address&&proof?.visible&&proof.href===target?p.entries.find(e=>e.target===target&&e.meta.kode===proof.code)||null:null;}
 function nativeChrome(main,doc,component,nav,code){
  const crumb=main.querySelector('.desktop-chrome__crumbrow'),bar=main.querySelector('header.bar');if(!crumb||!bar)return false;
  const fragment=doc.createElement('template');fragment.innerHTML=component.breadcrumb;
  const leaves=fragment.content.querySelectorAll('[aria-current="page"]'),parents=fragment.content.querySelectorAll('a[href="__PADI_CHROME_BACK__"]');
  if(leaves.length!==1||leaves[0].textContent!=='__PADI_CODE__'||parents.length!==2||fragment.content.querySelector('script,form,input,button'))return false;
  leaves[0].textContent=code;for(const a of parents)a.setAttribute('href',nav.chrome_back);
  const control=doc.createElement('template');control.innerHTML=component[nav.header_back===null?'header_menu':'header_back'];
  const controls=control.content.querySelectorAll('.bar__menu,.bar__balik'),old=bar.querySelectorAll('.bar__menu,.bar__balik');
  if(controls.length!==1||old.length!==1||control.content.querySelector('script,form,input'))return false;
  if(nav.header_back===null){if(!old[0].matches('button.bar__menu#buka-laci')||!controls[0].matches('button.bar__menu#buka-laci'))return false;}
  else{if(!controls[0].matches('a.bar__balik[href="__PADI_HEADER_BACK__"]'))return false;controls[0].setAttribute('href',nav.header_back);old[0].replaceWith(control.content);}
  crumb.replaceChildren(fragment.content);const title=bar.querySelector('.bar__merek');if(!title)return false;title.textContent='Riwayat pengiriman · '+code;title.setAttribute('aria-label','Riwayat pengiriman · '+code);return true;
 }
 function buat(target,base,ctx,cap,token){try{
  const source=location.pathname+location.search,current=document.querySelector('.bingkai'),mainNow=document.getElementById('isi-halaman'),sessionNow=document.getElementById('formulir-sesi');
  if(typeof base!=='string'||base.length>8388608||!address(target,location.origin)||location.hash||document.querySelector('[data-editor-perintah],[data-kemas-ulang]')||document.getElementById('lembar')?.open||document.body.hasAttribute('data-portal-akun')||document.body.classList.contains('portal-customer'))return null;
  if(document.querySelectorAll('.bingkai').length!==1||document.querySelectorAll('#isi-halaman').length!==1||document.querySelectorAll('#formulir-sesi').length!==1||!current.contains(mainNow)||!current.contains(sessionNow)||current.dataset.pindahAlamat!==source||current.dataset.pindahKonteks!==ctx||document.documentElement.dataset.versi!==cap||sessionNow.dataset.token!==token)return null;
  const hosts=document.querySelectorAll('#padi-riwayat-pengiriman-catalog');if(hosts.length!==1)return null;const host=hosts[0];if(!host.isConnected||!mainNow.contains(host)||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>262144)return null;
  const p=JSON.parse(host.textContent),data=global.PadiKerangkaRiwayatPengirimanData;
  if(!valid(data,p,ctx,cap,token,host.dataset.sourceSha,location.origin)||host.dataset.sourceAddress!==p.source_address)return null;
  const entry=select(p,target,source,proof(p,target,source,document,n=>getComputedStyle(n),location.origin));if(!entry)return null;
  const m=entry.meta,doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==ctx||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const component=data.variants[m.review?'review':'read'],part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attr]of[['style[data-rp-style]',data.styles,'data-rp-style'],['script[data-rp-script]',data.scripts,'data-rp-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-riwayat-pengiriman-kerangka]');if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;const root=roots[0];
  root.dataset.url=target;root.dataset.stamp=ctx+'|'+target;root.querySelector('[data-rp-title]').textContent=m.title;root.querySelector('[data-rp-state]').textContent=m.bersama?'Keadaan perjalanan belum dibaca':m.status==='selesai'?'Terverifikasi':'Dibatalkan';root.querySelector('[data-rp-handover]').hidden=m.status!=='selesai';root.querySelector('[data-rp-back]').setAttribute('href',entry.nav.body_back);
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  for(const old of doc.querySelectorAll('#padi-riwayat-pengiriman-catalog'))old.remove();
  if(!nativeChrome(main,doc,component,entry.nav,m.kode))return null;
  for(const a of doc.querySelectorAll('#laci a[href]')){const active=new URL(a.getAttribute('href'),location.href).pathname==='/barang-keluar';a.classList.toggle('pintu--kini',active&&a.classList.contains('pintu'));a.classList.toggle('pintu-sub__satu--kini',active&&a.classList.contains('pintu-sub__satu'));if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title='Riwayat pengiriman · '+m.kode+' · PT Hadi Mulya Utama';return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }catch(_){return null;}}
 if(typeof module==='object'&&module.exports){module.exports={address,meta,navigation,valid,shown,normalize,proof,select,nativeChrome};return;}
 global.PadiKerangkaRiwayatPengirimanUI=Object.freeze({versi:1,sumber:global.PadiKerangkaRiwayatPengirimanData?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
