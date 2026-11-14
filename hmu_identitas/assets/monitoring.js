/* Interaksi manusia saja. Tidak membaca nilai input, isi formulir, atau query URL. */
(function(){
  if(window.HMU_PEMAKAIAN)return;window.HMU_PEMAKAIAN=true;
  var portal=location.pathname.indexOf('/pelanggan')===0;
  var base=portal?'/pelanggan/monitoring':location.pathname.indexOf('/timbangan')===0?'/timbangan/monitoring':'/monitoring';
  var pending=[],ctx=null,last=0,busy=false;
  function id(){return crypto.randomUUID?crypto.randomUUID():([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g,function(c){return(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16);});}
  function layar(){var p=location.pathname.split('/'),keys=['stok','pekerjaan','barang-masuk','pengiriman','pengaturan','laporan','timbang','tiket','daftar','giling','sosoh','retur'];return keys.find(function(k){return p.some(function(v){return v===k||v.indexOf(k+'-')===0;});})||'lainnya';}
  async function flush(){
    if(busy||!pending.length||document.visibilityState!=='visible')return;
    busy=true;var batch=pending.splice(0,8);
    try{
      if(!ctx){var c=await fetch(base+'/konteks',{credentials:'same-origin',cache:'no-store'});if(!c.ok)throw Error('context');ctx=await c.json();}
      var r=await fetch(base+'/aktivitas',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':ctx.csrf},body:JSON.stringify({cap:ctx.cap,kejadian:batch}),keepalive:true});
      if(!r.ok){ctx=null;}
    }catch(e){ctx=null;}finally{busy=false;}
  }
  function aktif(e){
    if(!e.isTrusted||document.visibilityState!=='visible'||Date.now()-last<30000)return;
    last=Date.now();pending.push({event_id:id(),jenis:'interaksi',layar:layar()});if(pending.length>8)pending.shift();void flush();
  }
  ['pointerdown','keydown','touchstart','scroll'].forEach(function(t){document.addEventListener(t,aktif,{passive:true,capture:true});});
  var errorLast=0;
  function galat(code){if(!ctx||Date.now()-last>300000||Date.now()-errorLast<30000)return;errorLast=Date.now();pending.push({event_id:id(),jenis:'galat_browser',layar:layar(),kode:code});if(pending.length>8)pending.shift();void flush();}
  window.addEventListener('error',function(e){var n=e.error&&e.error.name;galat(['TypeError','ReferenceError','RangeError','Error'].indexOf(n)>=0?n:'Error');});
  window.addEventListener('unhandledrejection',function(){galat('promise');});
  document.addEventListener('visibilitychange',function(){if(document.visibilityState==='hidden'){pending=[];ctx=null;}});
})();
