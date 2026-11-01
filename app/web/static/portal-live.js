/* HTML selalu datang dari pembaca portal yang memeriksa seluruh sumber. */
(() => {
  'use strict';
  let alamat=location.pathname+location.search;
  if(!(alamat==='/pelanggan' || alamat.startsWith('/pelanggan/')) || !document.getElementById('isi-pelanggan'))return;
  const identity=document.querySelector('meta[name=portal-identitas]')?.content;
  const endpoint='/pelanggan/live/';
  let stream=null,pending=null,applied=null,retry=null,busy=false,stopped=false,last=0,generation=0,connected=false,reconnect=null,delay=1000;
  const safe=()=>window.SEGAR_AMAN?.boleh() && !document.body.classList.contains('sidebar-open');
  function pesan(teks){
    let bar=document.getElementById('portal-kesegaran');
    if(!bar){bar=document.createElement('p');bar.id='portal-kesegaran';bar.className='pelanggan-peringatan-stok';bar.setAttribute('role','status');document.querySelector('.portal-topbar')?.after(bar);}
    if(bar.textContent!==teks)bar.textContent=teks;
  }
  function terapkan(){
    if(!pending || stopped)return;
    if(!safe() || !connected){
      pesan(connected?'Ada pembaruan. Isian Anda tetap aman; tampilan diperbarui setelah isian selesai.':'Sambungan terputus. Isian tetap tersedia; mencoba memperbarui lagi.');
      if(!retry)retry=setTimeout(()=>{retry=null;terapkan();},1000);
      return;
    }
    if(location.pathname+location.search!==alamat){sesuaikan();return;}
    const data=pending,doc=new DOMParser().parseFromString(data.html,'text/html');
    const main=doc.getElementById('isi-pelanggan'),old=document.getElementById('isi-pelanggan');
    if(!main || !old)return;
    const target=new URL(data.url,location.href);
    if(target.origin!==location.origin || !(target.pathname==='/pelanggan' || target.pathname.startsWith('/pelanggan/')))return;
    if(target.pathname+target.search!==alamat){location.replace(target.href);return;}
    const pos=window.scrollY,inner=old.scrollTop;
    const open=[...old.querySelectorAll('details')].map((el,i)=>el.open?(el.id||i):null);
    old.replaceChildren(...main.childNodes);
    document.title=doc.title;
    ['.portal-topbar>span','.portal-account>strong'].forEach(selector=>{
      const current=document.querySelector(selector),next=doc.querySelector(selector);
      if(current && next)current.textContent=next.textContent;
    });
    old.querySelectorAll('details').forEach((el,i)=>el.open=open.includes(el.id||i));
    old.scrollTop=inner;window.scrollTo(0,pos);
    old.querySelectorAll('script[src]').forEach(el=>{
      const url=new URL(el.src,location.href);
      if(url.origin===location.origin && ['/static/saring-kerja.js','/static/pdf-penerimaan.js'].includes(url.pathname)){
        const script=document.createElement('script');script.src=url.href;el.replaceWith(script);
      }
    });
    window.SEGAR_AMAN.ingat();
    applied=data.n;pending=null;
    document.getElementById('portal-kesegaran')?.remove();
    document.dispatchEvent(new CustomEvent('portal:diperbarui'));
  }
  function terima(data){
    if(stopped)return;
    last=Date.now();connected=true;
    if(data.akses===false || (data.identity && data.identity!==identity)){stopped=true;stream?.close();pending=null;pesan('Sesi atau akses halaman telah berubah. Masuk kembali untuk melihat data terbaru.');return;}
    if(data.html){generation++;pending=data.n===applied?null:data;}
    if(pending)terapkan();else document.getElementById('portal-kesegaran')?.remove();
  }
  async function denyut(){
    if(stopped || busy || document.visibilityState!=='visible')return;
    busy=true;
    const start=generation,halaman=alamat;
    try{
      const r=await fetch(endpoint+'keadaan?halaman='+encodeURIComponent(alamat),{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
      if([401,403,404].includes(r.status)){terima({akses:false});return;}
      if(!r.ok || !(r.headers.get('content-type')||'').includes('application/json'))throw Error();
      const data=await r.json();
      if(start===generation && halaman===alamat)terima(data);
    }catch(_){connected=false;pesan('Sambungan terputus. Isian tetap tersedia; mencoba memperbarui lagi.');}
    finally{busy=false;}
  }
  function sambung(){
    if(stopped || stream || document.visibilityState!=='visible')return;
    if(!window.EventSource){denyut();return;}
    const halaman=alamat;
    const es=new EventSource(endpoint+'aliran?halaman='+encodeURIComponent(alamat));stream=es;
    es.onmessage=e=>{if(stream!==es)return;delay=1000;try{if(halaman!==location.pathname+location.search){sesuaikan();return;}terima(JSON.parse(e.data));}catch(_){}};
    es.onerror=()=>{
      es.close();if(stream!==es || stopped)return;stream=null;connected=false;last=0;
      pesan('Sambungan terputus. Isian tetap tersedia; mencoba memperbarui lagi.');denyut();
      if(!reconnect && document.visibilityState==='visible'){
        reconnect=setTimeout(()=>{reconnect=null;sambung();},delay);delay=Math.min(delay*2,30000);
      }
    };
  }
  function sesuaikan(){
    const current=location.pathname+location.search;
    if(current===alamat)return;
    stream?.close();stream=null;alamat=current;pending=null;applied=null;last=0;generation++;sambung();
  }
  ['input','change','click'].forEach(type=>document.addEventListener(type,()=>setTimeout(sesuaikan,0)));
  window.addEventListener('popstate',sesuaikan);
  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='visible'){last=0;delay=1000;sambung();denyut();terapkan();}
    else{stream?.close();stream=null;clearTimeout(reconnect);reconnect=null;}
  });
  window.addEventListener('pageshow',e=>{if(e.persisted){denyut();sambung();}});
  window.addEventListener('online',()=>{denyut();sambung();});
  const channel=window.BroadcastChannel?new BroadcastChannel('portal-sesi'):null;
  if(channel){channel.onmessage=e=>{if(e.data?.identity!==identity)terima({akses:false});};channel.postMessage({identity});}
  document.addEventListener('submit',e=>{
    if(new URL(e.target.action,location.href).pathname==='/pelanggan/keluar'){
      channel?.postMessage({identity:null});terima({akses:false});
    }
  },true);
  async function cekSesi(){
    if(stopped || document.visibilityState!=='visible')return;
    try{
      const r=await fetch(endpoint+'sesi',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});
      if([401,403].includes(r.status)){terima({akses:false});return;}
      if(r.ok){const data=await r.json();if(data.identity!==identity)terima({akses:false});}
    }catch(_){}
  }
  setInterval(()=>{cekSesi();if(Date.now()-last>25000)denyut();},10000);
  sambung();
})();
