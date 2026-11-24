/* Final journey READ only; all action/deeper-workflow URLs stay native. */
(function(global){'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 function address(value,origin){
  if(!core?.sameOriginAddress(value,origin))return null;
  const u=new URL(value,origin),q=u.searchParams,m=/^\/barang-keluar\/([1-9][0-9]{0,9})$/.exec(u.pathname);
  if(!m||Number(m[1])>2147483647||u.search.length>3001||/%(?![0-9a-fA-F]{2})/.test(u.search))return null;
  if([...q.keys()].some(k=>!['q','status','sejak','sebelum','pelanggan_id','kembali','kembali_kerja'].includes(k)||q.getAll(k).length!==1)||![...q].every(([k,v])=>!k.includes('\uFFFD')&&!v.includes('\uFFFD'))||(q.get('q')||'').length>200||!['','perintah','dimuat','selesai','batal'].includes(q.get('status')||''))return null;
  for(const key of ['sebelum','pelanggan_id']){const v=q.get(key);if(v&&(!/^[1-9][0-9]{0,9}$/.test(v)||Number(v)>2147483647))return null;}
  if(q.get('sejak')){const d=q.get('sejak');try{if(!/^\d{4}-\d{2}-\d{2}$/.test(d)||d.startsWith('0000')||new Date(d+'T00:00:00Z').toISOString().slice(0,10)!==d)return null;}catch(_){return null;}}
  for(const key of ['kembali','kembali_kerja']){const v=q.get(key);if(v&&(!v.startsWith('/')||v.startsWith('//')||/[\\#\r\n]/.test(v)||!['/pekerjaan','/barang-keluar','/retur','/stok','/riwayat','/laporan','/jasa'].includes(v.split('?')[0])))return null;}
  return {u,id:Number(m[1])};
 }
 function holdActions(content,origin){
  for(const a of content.querySelectorAll('a[href]')){let u;try{u=new URL(a.getAttribute('href'),origin);}catch(_){continue;}
   if(u.origin===origin&&(u.pathname!='/barang-keluar'||u.searchParams.has('buka')||u.searchParams.has('nilai')||u.searchParams.has('tiket')||u.searchParams.has('rincian_perintah')))a.setAttribute('data-utuh','');
  }
 }
 function configuration(value,origin){
  if(!address(value,origin))return null;
  return {address:value,rootSelector:'[data-riwayat-pengiriman-kerangka]',statusSelector:'[data-rp-status]',retrySelector:'[data-rp-retry]',
   messages:{loading:'Memuat riwayat pengiriman…',response:'Riwayat belum dapat dibaca. Sesi, status dan akses tetap diperiksa oleh halaman native.'},
   afterInstall({content}){holdActions(content,origin);},
   restoreFocus({focus,retry,content}){if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});}}};
 }
 if(typeof module==='object'&&module.exports){module.exports={address,configuration,holdActions};return;}
 const root=document.querySelector('[data-riwayat-pengiriman-kerangka]'),config=root?configuration(root.dataset.url,location.origin):null;
 if(!config||!core)return;const reader=core.mount(config);
 root.addEventListener('click',event=>{const a=event.target.closest('a[href]');if(a&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey&&event.button===0)reader?.stop();},true);
})(typeof window==='undefined'?globalThis:window);
