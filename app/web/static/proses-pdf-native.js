/* Three HTML viewers only. Never fetch/cache/compose a PDF or submit data. */
(function(global){'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 function address(value,origin){
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//'))return null;
  let u;try{u=new URL(value,origin);}catch(_){return null;}
  const m=/^\/riwayat-(giling|sosoh|pengeringan)\/([1-9][0-9]{0,9})\/laporan$/.exec(u.pathname);
  return u.origin===origin&&!u.search&&!u.hash&&u.pathname===value&&m&&Number(m[2])<=2147483647?{u,kind:m[1],id:Number(m[2]),pdf:value+'.pdf',detail:value.slice(0,-8),parent:'/riwayat-'+m[1]}:null;
 }
 function same(a,b){return !!a&&!!b&&['cap','context','session','address'].every(k=>typeof a[k]==='string'&&a[k]&&a[k]===b[k]);}
 function activateDeferred({content,value,origin,identity,current}){
  const spec=address(value,origin);
  if(!spec||!content?.isConnected||!same(identity,current())||identity.address!==value)return false;
  const frames=[...content.querySelectorAll('iframe[data-ppv-src]')];if(frames.length!==1)return false;const frame=frames[0];
  if(!frame.isConnected||!content.contains(frame)||frame.dataset.ppvUrl!==value||frame.dataset.ppvSrc!==spec.pdf||frame.hasAttribute('src')||frame.dataset.ppvActivated||!same(identity,current()))return false;
  frame.dataset.ppvActivated='1';frame.setAttribute('src',frame.dataset.ppvSrc);return true;
 }
 function snapshot(){const frame=document.querySelector('.bingkai');return {cap:document.documentElement.dataset.versi||'',context:frame?.dataset.pindahKonteks||'',session:document.getElementById('formulir-sesi')?.dataset.token||'',address:frame?.dataset.pindahAlamat||''};}
 function configuration(value,origin,identity,current){
  if(!address(value,origin))return null;
  return {address:value,rootSelector:'[data-proses-pdf-kerangka]',statusSelector:'#status-bagikan',retrySelector:'[data-ppv-retry]',
   messages:{loading:'Menyiapkan halaman laporan…',response:'Halaman laporan belum dapat dibaca. Hak akses dan kesiapan proses tetap diperiksa oleh halaman native.'},
   afterInstall({content}){activateDeferred({content,value,origin,identity,current});},
   restoreFocus({focus,retry,content}){if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});}}};
 }
 if(typeof module==='object'&&module.exports){module.exports={address,same,activateDeferred,configuration};return;}
 const value=location.pathname+location.search,identity=snapshot(),root=document.querySelector('[data-proses-pdf-kerangka]');
 if(!root){const content=document.getElementById('isi-halaman');if(content)activateDeferred({content,value,origin:location.origin,identity,current:snapshot});return;}
 const config=configuration(value,location.origin,identity,snapshot);if(!config||!core)return;const reader=core.mount(config);
 root.addEventListener('click',event=>{const link=event.target.closest('a[href]');if(link&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey&&event.button===0)reader?.stop();},true);
})(typeof window==='undefined'?globalThis:window);
