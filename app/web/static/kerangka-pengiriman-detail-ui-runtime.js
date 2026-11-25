/* Public layout is not a grant. Only current native DTO+visible link provenance. */
(function(global){'use strict';
 const native=typeof module==='object'&&module.exports?require('./pengiriman-detail-native.js'):null;
 const TABS=['ringkasan','barang','tiket','riwayat'],KEYS=['id','kode','status','keadaan','jasa','cepat','bersama','tiket','boleh_perintah','boleh_muat','actions'];
 const obj=x=>!!x&&typeof x==='object'&&!Array.isArray(x),own=(x,k)=>Object.prototype.hasOwnProperty.call(x,k),exact=(x,keys)=>obj(x)&&Object.keys(x).length===keys.length&&keys.every(k=>own(x,k)),sha=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
 function address(value,origin){
  if(native)return native.address(value,origin);
  const core={sameOriginAddress(v,o){try{const u=new URL(v,o);return typeof v==='string'&&v.startsWith('/')&&!v.startsWith('//')&&u.origin===o&&!u.hash&&u.pathname+u.search===v;}catch(_){return false;}}};
  /*__PADI_NATIVE_READ_ADDRESS__*/
 }
 function meta(m){return exact(m,KEYS)&&Number.isInteger(m.id)&&m.id>0&&m.id<=2147483647&&['perintah','dimuat'].includes(m.status)&&['kode','keadaan'].every(k=>typeof m[k]==='string'&&m[k]&&m[k].length<=200)&&['jasa','cepat','bersama','tiket','boleh_perintah','boleh_muat'].every(k=>typeof m[k]==='boolean')&&Array.isArray(m.actions)&&m.actions.length<=10&&m.actions.every(a=>exact(a,['label','bagian'])&&typeof a.label==='string'&&a.label&&a.label.length<=200&&['ringkasan','barang'].includes(a.bagian));}
 function navigation(n,origin){
  if(!exact(n,['body_back','header_back','chrome_back']))return false;
  const safe=value=>{if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||value.length>4096)return null;try{const u=new URL(value,origin);return u.origin===origin&&!u.hash&&u.pathname+u.search===value?u:null;}catch(_){return null;}};
  const body=safe(n.body_back),chrome=safe(n.chrome_back),header=n.header_back===null?null:safe(n.header_back);
  return !!body&&['/pekerjaan','/barang-keluar','/retur','/stok','/riwayat','/laporan','/jasa'].includes(body.pathname)&&chrome?.pathname==='/barang-keluar'&&(n.header_back===null||!!header&&['/barang-masuk','/pekerjaan','/kabar'].includes(header.pathname));
 }
 function valid(data,p,ctx,cap,token,sourceSha,origin){
  if(!exact(data,['versi','sumber','variants','styles','scripts'])||data.versi!==1||!sha(data.sumber)||!exact(data.variants,['read','command'])||!['read','command'].every(k=>exact(data.variants[k],['html','breadcrumb','header_menu','header_back'])&&typeof data.variants[k].html==='string'&&data.variants[k].html.length<=131072&&['breadcrumb','header_menu','header_back'].every(f=>typeof data.variants[k][f]==='string'&&data.variants[k][f].length<=65536))||!['styles','scripts'].every(k=>obj(data[k])&&Object.keys(data[k]).length<=16&&Object.values(data[k]).every(v=>typeof v==='string'&&v.length<=262144)))return false;
  if(!exact(p,['versi','cap','konteks','sesi','sumber','source_address','sumber_sha256','mode','entries'])||p.versi!==1||p.sumber!==data.sumber||p.cap!==cap||p.konteks!==ctx||p.sesi!==token||![ctx,cap,token].every(v=>typeof v==='string'&&v&&v.length<=2048)||!sha(sourceSha)||p.sumber_sha256!==sourceSha||!['list','detail'].includes(p.mode)||typeof p.source_address!=='string'||p.source_address.length>4096||!Array.isArray(p.entries)||!p.entries.length||p.entries.length>(p.mode==='list'?50:1))return false;
  let source;try{source=new URL(p.source_address,origin);}catch(_){return false;}
  if(source.origin!==origin||source.hash||source.pathname+source.search!==p.source_address||(p.mode==='list'?source.pathname!=='/barang-keluar':!address(p.source_address,origin)))return false;
  return new Set(p.entries.map(e=>e?.meta?.id)).size===p.entries.length&&p.entries.every(e=>exact(e,['meta','targets','nav'])&&meta(e.meta)&&navigation(e.nav,origin)&&Array.isArray(e.targets)&&e.targets.length===(p.mode==='list'?1:4)&&new Set(e.targets).size===e.targets.length&&e.targets.every(t=>address(t,origin)?.id===e.meta.id)&&(p.mode!=='detail'||new Set(e.targets.map(t=>address(t,origin).tab)).size===4&&address(p.source_address,origin).id===e.meta.id));
 }
 const stamp=(ctx,target,id,digest)=>ctx+'|'+target+'|'+id+'|'+digest;
 function sameReadScope(originTarget,target,origin){const a=address(originTarget,origin),b=address(target,origin);if(!a||!b||a.id!==b.id)return false;a.u.searchParams.delete('tab_detail');b.u.searchParams.delete('tab_detail');return a.u.pathname+a.u.search===b.u.pathname+b.u.search;}
 function select(p,target,source,ctx,proof,origin){
  const state=address(target,origin);if(!state||!proof?.visible||proof.href!==target)return null;
  const entry=p.entries.find(e=>e.meta.id===state.id);if(!entry||proof.code!==entry.meta.kode)return null;
  if(proof.kind==='pending')return address(source,origin)?.id===state.id&&proof.id===state.id&&proof.url===source&&proof.digest===p.sumber_sha256&&entry.targets.includes(proof.originTarget)&&sameReadScope(proof.originTarget,target,origin)&&proof.stamp===stamp(ctx,source,state.id,p.sumber_sha256)?{state,entry,originTarget:proof.originTarget}:null;
  return source===p.source_address&&proof.kind===p.mode&&entry.targets.includes(target)?{state,entry,originTarget:target}:null;
 }
 function shown(node,style){return !!node&&node.isConnected!==false&&!node.closest('[hidden],[inert],[aria-hidden="true"]')&&node.getClientRects().length>0&&!['hidden','collapse'].includes(style(node).visibility);}
 function normalize(link,source,origin){try{const u=new URL(link.getAttribute('href'),origin+source);if(u.origin!==origin||u.hash&&!/^#panel-(ringkasan|barang|tiket|riwayat)$/.test(u.hash))return null;return u.pathname+u.search;}catch(_){return null;}}
 function proof(p,target,source,doc,style,origin){
  const eligible=a=>normalize(a,source,origin)===target&&!a.hasAttribute('target')&&!a.hasAttribute('download')&&a.getAttribute('aria-disabled')!=='true'&&shown(a,style);
  const pending=doc.querySelectorAll('[data-pengiriman-detail-kerangka]');
  if(pending.length){if(pending.length!==1)return null;const root=pending[0],links=[...root.querySelectorAll('[data-pd-tab]')].filter(eligible),code=root.querySelector('[data-pd-code]');if(!doc.getElementById('isi-halaman')?.contains(root)||!shown(root,style)||links.length!==1||!code)return null;return {kind:'pending',visible:true,href:target,code:code.textContent,id:Number(root.dataset.pdId),url:root.dataset.url,digest:root.dataset.pdOriginSha,originTarget:root.dataset.pdOriginTarget,stamp:root.dataset.stamp};}
  if(p.mode==='list'){const rows=[...doc.querySelectorAll('#isi-halaman .keluar-daftar tr.keluar-baris[data-detail-keluar]')].filter(r=>shown(r,style)&&r.getAttribute('data-detail-keluar')===target);if(rows.length!==1)return null;const links=[...rows[0].querySelectorAll('td:first-child>a[href]')].filter(eligible);if(links.length!==1)return null;const code=links[0].querySelector('small')?.textContent,entry=p.entries.find(e=>e.targets.includes(target));return code&&entry&&code.startsWith(entry.meta.kode+' · ')?{kind:'list',visible:true,href:target,code:entry.meta.kode}:null;}
  const root=doc.querySelector('#isi-halaman [data-detail-tab]'),code=root?.querySelector('#judul-perintah'),links=root?[...root.querySelectorAll('.detail-kirim-tabs>a[href]')].filter(eligible):[];return root&&shown(root,style)&&code&&links.length===1?{kind:'detail',visible:true,href:target,code:code.textContent}:null;
 }
 function tabURL(state,tab){const u=new URL(state.u);u.searchParams.set('tab_detail',tab);return u.pathname+u.search;}
 function nativeChrome(main,doc,component,nav,code){
  const crumb=main.querySelector('.desktop-chrome__crumbrow'),bar=main.querySelector('header.bar');if(!crumb||!bar)return false;
  const fragment=doc.createElement('template');fragment.innerHTML=component.breadcrumb;
  const leaves=fragment.content.querySelectorAll('[aria-current="page"]'),parents=fragment.content.querySelectorAll('a[href="__PADI_CHROME_BACK__"]');
  if(leaves.length!==1||leaves[0].textContent!=='__PADI_CODE__'||parents.length!==2||fragment.content.querySelector('script,form,input,button'))return false;
  leaves[0].textContent=code;for(const a of parents)a.setAttribute('href',nav.chrome_back);
  const control=doc.createElement('template');control.innerHTML=component[nav.header_back===null?'header_menu':'header_back'];
  const controls=control.content.querySelectorAll('.bar__menu,.bar__balik'),old=bar.querySelectorAll('.bar__menu,.bar__balik');
  if(controls.length!==1||old.length!==1||control.content.querySelector('script,form,input'))return false;
  if(nav.header_back===null){
   // Keep the native base menu node/attributes, never invent a Back control.
   if(!old[0].matches('button.bar__menu#buka-laci')||!controls[0].matches('button.bar__menu#buka-laci'))return false;
  }else{
   if(!controls[0].matches('a.bar__balik[href="__PADI_HEADER_BACK__"]'))return false;
   controls[0].setAttribute('href',nav.header_back);old[0].replaceWith(control.content);
  }
  crumb.replaceChildren(fragment.content);
  const title=bar.querySelector('.bar__merek');if(!title)return false;title.textContent=code;title.setAttribute('aria-label',code);
  return true;
 }
 function buat(target,base,ctx,cap,token){try{
  const source=location.pathname+location.search,current=document.querySelector('.bingkai'),mainNow=document.getElementById('isi-halaman'),sessionNow=document.getElementById('formulir-sesi');
  if(typeof base!=='string'||base.length>8388608||!address(target,location.origin)||location.hash||document.querySelector('[data-editor-perintah],[data-kemas-ulang]')||document.getElementById('lembar')?.open||document.body.hasAttribute('data-portal-akun')||document.body.classList.contains('portal-customer'))return null;
  if(document.querySelectorAll('.bingkai').length!==1||document.querySelectorAll('#isi-halaman').length!==1||document.querySelectorAll('#formulir-sesi').length!==1||!current.contains(mainNow)||!current.contains(sessionNow)||current.dataset.pindahAlamat!==source||current.dataset.pindahKonteks!==ctx||document.documentElement.dataset.versi!==cap||sessionNow.dataset.token!==token)return null;
  const hosts=document.querySelectorAll('#padi-pengiriman-detail-catalog');if(hosts.length!==1)return null;const host=hosts[0];if(!host.isConnected||!mainNow.contains(host)||host.dataset.cap!==cap||host.dataset.konteks!==ctx||host.textContent.length>262144)return null;
  const p=JSON.parse(host.textContent),data=global.PadiKerangkaPengirimanDetailData;
  if(!valid(data,p,ctx,cap,token,host.dataset.sourceSha,location.origin)||host.dataset.sourceAddress!==p.source_address)return null;
  const selected=select(p,target,source,ctx,proof(p,target,source,document,n=>getComputedStyle(n),location.origin),location.origin);if(!selected)return null;
  const {state,entry,originTarget}=selected,m=entry.meta,doc=new DOMParser().parseFromString(base,'text/html'),frame=doc.querySelector('.bingkai'),main=doc.getElementById('isi-halaman'),session=doc.getElementById('formulir-sesi');
  if(doc.querySelectorAll('.bingkai').length!==1||doc.querySelectorAll('#isi-halaman').length!==1||doc.querySelectorAll('#formulir-sesi').length!==1||!frame.contains(main)||!frame.contains(session)||frame.dataset.pindahKonteks!==ctx||doc.documentElement.dataset.versi!==cap||session.dataset.token!==token)return null;
  const nodes=[...main.childNodes],starts=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:mulai'),ends=nodes.filter(n=>n.nodeType===8&&n.data.trim()==='isi-halaman:akhir');if(starts.length!==1||ends.length!==1||!(starts[0].compareDocumentPosition(ends[0])&Node.DOCUMENT_POSITION_FOLLOWING))return null;
  const component=data.variants[m.boleh_perintah?'command':'read'],part=doc.createElement('template');part.innerHTML=component.html;
  for(const [selector,pool,attr]of[['style[data-pd-style]',data.styles,'data-pd-style'],['script[data-pd-script]',data.scripts,'data-pd-script']])for(const node of part.content.querySelectorAll(selector)){const key=node.getAttribute(attr);if(!own(pool,key))return null;node.textContent=pool[key];node.removeAttribute(attr);}
  const roots=part.content.querySelectorAll('[data-pengiriman-detail-kerangka]');if(roots.length!==1||part.content.querySelector('form,input,select,textarea,[data-post],[data-kirim],script[src],link[rel=stylesheet]'))return null;const root=roots[0];
  root.dataset.url=target;root.dataset.stamp=stamp(ctx,target,m.id,p.sumber_sha256);root.dataset.pdId=String(m.id);root.dataset.pdOriginSha=p.sumber_sha256;root.dataset.pdOriginTarget=originTarget;
  root.querySelector('[data-pd-code]').textContent=m.kode;root.querySelector('[data-pd-state]').textContent=m.keadaan;root.querySelector('[data-pd-owner]').textContent=m.jasa?'Jasa':'Milik pabrik';root.querySelector('[data-pd-party-label]').textContent=m.jasa?'Pemilik':'Pelanggan';root.querySelector('[data-pd-group]').hidden=!m.bersama;
  for(const node of root.querySelectorAll('[data-pd-actual-label]'))node.textContent=m.cepat?'Jumlah aktual':'Dimuat aktual';
  for(const a of root.querySelectorAll('[data-pd-tab]')){a.href=tabURL(state,a.dataset.pdTab);a.setAttribute('aria-selected',String(a.dataset.pdTab===state.tab));}
  for(const panel of root.querySelectorAll('[role=tabpanel]'))panel.hidden=panel.id!=='panel-'+state.tab;
  for(const holder of root.querySelectorAll('[data-pd-actions]')){holder.replaceChildren();for(const action of m.actions.filter(a=>a.bagian===holder.dataset.pdActions)){const button=doc.createElement('button');button.className='btn';button.type='button';button.disabled=true;button.setAttribute('aria-describedby','pd-pending');button.textContent=action.bagian==='barang'?'+ Tambah item':action.label;holder.append(button);}}
  root.querySelector('[data-pd-back]').setAttribute('href',entry.nav.body_back);
  while(starts[0].nextSibling&&starts[0].nextSibling!==ends[0])starts[0].nextSibling.remove();ends[0].before(part.content);
  for(const old of doc.querySelectorAll('#padi-pengiriman-detail-catalog'))old.remove();ends[0].before(doc.importNode(host,true));
  if(!nativeChrome(main,doc,component,entry.nav,m.kode))return null;
  for(const a of doc.querySelectorAll('#laci a[href]')){const active=new URL(a.getAttribute('href'),location.href).pathname==='/barang-keluar';a.classList.toggle('pintu--kini',active&&a.classList.contains('pintu'));a.classList.toggle('pintu-sub__satu--kini',active&&a.classList.contains('pintu-sub__satu'));if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  frame.dataset.pindahAlamat=target;frame.dataset.pindahKerangka='1';doc.title=m.kode+' · PT Hadi Mulya Utama';return {versi:1,alamat:target,konteks:ctx,cap,html:'<!doctype html>'+doc.documentElement.outerHTML};
 }catch(_){return null;}}
 if(typeof module==='object'&&module.exports){module.exports={address,meta,navigation,valid,stamp,sameReadScope,select,shown,normalize,proof,tabURL,nativeChrome};return;}
 global.PadiKerangkaPengirimanDetailUI=Object.freeze({versi:1,sumber:global.PadiKerangkaPengirimanDetailData?.sumber,buat});
})(typeof window==='undefined'?globalThis:window);
