/* Five customer-detail tabs only; URL correlation never grants customer access. */
(function(global){
 'use strict';
 const core=typeof module==='object'&&module.exports?require('./padi-baca-native.js'):global.PADI_BACA_NATIVE;
 const TABS=['ringkasan','penerimaan','proses','stok','pengambilan'];
 const STATUS=['','berjalan','selesai','dibatalkan','digabung'];
 const KEYS=['tab','status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status','rincian_halaman','rincian_cari'];
 function nativeAddress(address,origin){
  if(!core?.sameOriginAddress(address,origin))return null;
  const url=new URL(address,origin),q=url.searchParams,match=url.pathname.match(/^\/jasa\/pelanggan\/([1-9][0-9]{0,9})$/);
  if(!match||Number(match[1])>2147483647||url.search.length>3001||/%(?![0-9a-fA-F]{2})/.test(url.search))return null;
  if(Array.from(q.keys()).some(k=>!KEYS.includes(k)||q.getAll(k).length!==1)||!TABS.includes(q.has('tab')?q.get('tab'):'ringkasan'))return null;
  if(['status','pesanan_status'].some(k=>!STATUS.includes(q.get(k)||'')))return null;
  if(['halaman','pesanan_halaman','rincian_halaman'].some(k=>{const v=q.get(k)||'';return v&&(!/^[1-9][0-9]{0,9}$/.test(v)||Number(v)>2147483647);}))return null;
  if(['cari','pesanan_cari','rincian_cari'].some(k=>(q.get(k)||'').length>200))return null;
  if(Array.from(q.entries()).some(([k,v])=>k.includes('\uFFFD')||v.includes('\uFFFD')))return null;
  return url.pathname+url.search;
 }
 function configuration(address,origin){
  address=nativeAddress(address,origin);if(!address)return null;
  return {address,rootSelector:'[data-jasa-detail-kerangka]',statusSelector:'[data-jasa-detail-status]',retrySelector:'[data-jasa-detail-retry]',
   shellSelector:'[data-jasa-detail-kerangka]',contentAttribute:'data-jasa-detail-native-isi',
   messages:{loading:'Memuat detail pelanggan…',response:'Detail pelanggan belum dapat dibaca. Sesi dan akses tetap mengikuti pemeriksaan native.'},
   restoreFocus({focus,retry,content}){
    let target=null;
    if(focus===retry){content.tabIndex=-1;target=content;}
    else {
     const link=focus.closest('a[href]');
     if(link?.closest('.jasa-detail-tab')){
      const tab=new URL(link.href,location.href).searchParams.get('tab')||'ringkasan';
      target=Array.from(content.querySelectorAll('.jasa-detail-tab a[href]')).find(a=>(new URL(a.getAttribute('href'),location.href).searchParams.get('tab')||'ringkasan')===tab);
     }else if(link)target=Array.from(content.querySelectorAll('a[href]')).find(a=>a.getAttribute('href')===link.getAttribute('href'));
    }
    target?.focus({preventScroll:true});
   }};
 }
 if(typeof module==='object'&&module.exports){module.exports={nativeAddress,configuration};return;}
 const root=document.querySelector('[data-jasa-detail-kerangka]');
 const config=root?configuration(root.dataset.url,location.origin):null;
 if(config&&core)core.mount(config);
})(typeof window==='undefined'?globalThis:window);
