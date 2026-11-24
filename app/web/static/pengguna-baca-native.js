/* Bentuk baca pengguna, tanpa editor/otorisasi atau pengiriman baru. */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 function emptyPeopleCase(variant,heading,message,hasForm){return ['staf','staf-super'].includes(variant)&&heading==='Buatkan akun'&&message==='Semua orang yang aktif sudah punya akun.'&&!hasForm;}
 function keepEmptyPeople(content,previousRoot){
  const variant=previousRoot?.dataset.penggunaVariant;
  const cards=Array.from(content.querySelectorAll('.kartu'));
  const card=cards.find(n=>n.querySelector('h2')?.textContent.trim()==='Buatkan akun');
  const message=card?.querySelector('p.bantu');
  if(!card||!message||!emptyPeopleCase(variant,card.querySelector('h2').textContent.trim(),message.textContent.trim(),!!card.querySelector('form')))return;
  const source=previousRoot.querySelector('[data-pengguna-pilihan-orang] .grup');
  if(!source||source.querySelector('form,[name],input[type=hidden],script,[data-post],[data-kirim]'))return;
  const group=source.cloneNode(true);message.id='pengguna-baca-orang-kosong';
  group.setAttribute('aria-describedby',message.id);
  for(const field of group.querySelectorAll('input,select,textarea,button')){
   field.disabled=true;field.removeAttribute('value');field.setAttribute('aria-describedby',message.id);
   if(field.matches('input,textarea'))field.value='';
  }
  const select=group.querySelector('select');if(select){select.replaceChildren();const option=document.createElement('option');option.textContent=message.textContent.trim();select.append(option);}
  card.append(group);
 }
 function validAddress(address,origin){
  if(!core?.sameOriginAddress(address,origin)||address.length>4096)return false;
  let u;try{u=new URL(address,origin);decodeURIComponent(u.search);}catch(_){return false;}
  if(u.search.length>2048)return false;
  const staff=/^\/pengguna(?:\/([1-9][0-9]{0,9}))?$/.exec(u.pathname),customer=/^\/pengguna\/pelanggan(?:\/([1-9][0-9]{0,9}))?$/.exec(u.pathname);
  if(staff)return !u.search&&(!staff[1]||Number(staff[1])<=2147483647);
  if(!customer||customer[1]&&Number(customer[1])>2147483647)return false;
  const q=[...u.searchParams];return new Set(q.map(x=>x[0])).size===q.length&&q.every(([k,v])=>['cari_akun','halaman_akun'].includes(k)&&(k!=='halaman_akun'||/^[0-9]{1,9}$/.test(v)));
 }
 function updateBreadcrumb(source,target,doc){
  if(!source||!target||source.querySelector('script,form,input'))return;
  const focus=doc.activeElement,anchor=target.contains(focus)&&focus.matches('a[href]')?focus:null;
  const href=anchor?.getAttribute('href'),back=anchor?.matches('.desktop-back');
  target.replaceChildren(...Array.from(source.childNodes,n=>doc.importNode(n,true)));
  // Replacing fresh native names must not drop a user's current keyboard
  // position. Restore only its unique equivalent inside this same breadcrumb.
  if(anchor&&doc.activeElement===doc.body){
   const matches=Array.from(target.querySelectorAll('a[href]')).filter(a=>a.getAttribute('href')===href&&a.matches('.desktop-back')===back);
   if(matches.length===1)matches[0].focus({preventScroll:true});
  }
 }
 function refreshChrome(doc){
  // Only the fresh, identity-checked native document knows whether the name
  // changed or its missing-resource fallback rendered the list instead.
  const fresh=doc.querySelector('.bar__merek'),live=document.querySelector('.bar__merek');
  if(fresh&&live){live.textContent=fresh.textContent;live.setAttribute('aria-label',fresh.getAttribute('aria-label')||fresh.textContent);}
  const back=doc.querySelector('header.bar a.bar__balik'),current=document.querySelector('header.bar a.bar__balik');
  if(back&&current&&['/pengaturan','/pengguna'].includes(back.getAttribute('href')))current.setAttribute('href',back.getAttribute('href'));
  const source=doc.querySelector('.desktop-chrome__crumbrow'),target=document.querySelector('.desktop-chrome__crumbrow');
  updateBreadcrumb(source,target,document);
 }
 function configuration(address,origin){
  if(!validAddress(address,origin))return null;
  return {address,rootSelector:'[data-pengguna-baca-native]',statusSelector:'[data-pengguna-baca-status]',retrySelector:'[data-pengguna-baca-retry]',shellSelector:'[data-pengguna-baca-native]',contentAttribute:'data-pengguna-baca-native-isi',messages:{loading:'Memuat data pengguna terbaru…'},
   afterInstall({content,previousRoot,doc}){keepEmptyPeople(content,previousRoot);refreshChrome(doc);global.PadiKerangkaPenggunaUI?.adoptNative(doc);},
   restoreFocus({focus,retry,content}){if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});}else{const href=focus.closest('a[href]')?.getAttribute('href');if(href)Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===href)?.focus({preventScroll:true});}}
  };
 }
 if(typeof module==='object'&&module.exports){module.exports={configuration,emptyPeopleCase,validAddress,updateBreadcrumb};return;}
 const root=document.querySelector('[data-pengguna-baca-native]');
 const config=root?configuration(root.dataset.url,location.origin):null;
 if(core&&config)core.mount(config);
})(typeof window==='undefined'?globalThis:window);
