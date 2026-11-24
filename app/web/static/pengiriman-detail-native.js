/* Active four-tab shipping READ only; action/editor URLs remain native. */
(function(global){'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const TABS=['ringkasan','barang','tiket','riwayat'];
 function address(value,origin){
  if(!core?.sameOriginAddress(value,origin))return null;
  const u=new URL(value,origin),q=u.searchParams,m=/^\/barang-keluar\/([1-9][0-9]{0,9})$/.exec(u.pathname);
  if(!m||Number(m[1])>2147483647||u.search.length>3001||/%(?![0-9a-fA-F]{2})/.test(u.search))return null;
  if([...q.keys()].some(k=>!['tab_detail','q','status','sejak','sebelum','pelanggan_id','kembali','kembali_kerja'].includes(k)||q.getAll(k).length!==1)||!TABS.includes(q.has('tab_detail')?q.get('tab_detail'):'ringkasan')||(q.get('q')||'').length>200||!['','perintah','dimuat','selesai','batal'].includes(q.get('status')||'')||[...q].some(([k,v])=>k.includes('\uFFFD')||v.includes('\uFFFD')))return null;
  for(const key of ['sebelum','pelanggan_id']){const v=q.get(key);if(v&&(!/^[1-9][0-9]{0,9}$/.test(v)||Number(v)>2147483647))return null;}
  if(q.get('sejak')){const d=q.get('sejak');try{if(!/^\d{4}-\d{2}-\d{2}$/.test(d)||d.startsWith('0000')||new Date(d+'T00:00:00Z').toISOString().slice(0,10)!==d)return null;}catch(_){return null;}}
  for(const key of ['kembali','kembali_kerja']){const v=q.get(key);if(v&&(!v.startsWith('/')||v.startsWith('//')||/[\\#\r\n]/.test(v)||!['/pekerjaan','/barang-keluar','/retur','/stok','/riwayat','/laporan','/jasa'].includes(v.split('?')[0])))return null;}
  return {u,id:Number(m[1]),tab:q.get('tab_detail')||'ringkasan'};
 }
 function holdActions(content,origin){
  for(const link of content.querySelectorAll('a[href]')){let u;try{u=new URL(link.getAttribute('href'),origin);}catch(_){continue;}
   if(u.origin===origin&&(u.searchParams.has('buka')||u.searchParams.has('nilai')||u.searchParams.has('tiket')||['/muatan','/selesai-muat','/verifikasi-pengiriman'].includes(u.pathname)||/^\/barang-keluar\/\d+\/(?:muatan|selesai-muat|verifikasi|perbaikan|retur|koreksi-selesai)$/.test(u.pathname)))link.setAttribute('data-utuh','');
  }
 }
 function configuration(value,origin){
  if(!address(value,origin))return null;
  return {address:value,rootSelector:'[data-pengiriman-detail-kerangka]',statusSelector:'[data-pd-status]',retrySelector:'[data-pd-retry]',
   messages:{loading:'Memuat detail pengiriman…',response:'Detail belum dapat dibaca. Sesi, status dan akses tetap diperiksa oleh halaman native.'},
   afterInstall({content}){holdActions(content,origin);},
   restoreFocus({focus,retry,content}){if(focus===retry){content.tabIndex=-1;content.focus({preventScroll:true});}}};
 }
 if(typeof module==='object'&&module.exports){module.exports={address,configuration,holdActions};return;}
 const root=document.querySelector('[data-pengiriman-detail-kerangka]'),config=root?configuration(root.dataset.url,location.origin):null;
 if(!config||!core)return;const reader=core.mount(config);
 root.addEventListener('click',event=>{const link=event.target.closest('a[href]');if(link&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey&&event.button===0)reader?.stop();},true);
 const tabs=[...root.querySelectorAll('[data-pd-tab]')];
 root.querySelector('[role=tablist]')?.addEventListener('keydown',event=>{let i=tabs.indexOf(event.target);if(i<0||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();i=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[i].focus();tabs[i].click();});
})(typeof window==='undefined'?globalThis:window);
