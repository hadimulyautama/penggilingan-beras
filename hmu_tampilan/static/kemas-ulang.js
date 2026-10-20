/* Tidak mengubah stok sampai operator menyetujui ringkasan dan mengirim. */
(function(){
  var root=document.querySelector('[data-kemas-ulang]');if(!root||root.dataset.siap)return;root.dataset.siap='1';
  var form=root.querySelector('form'),galat=root.querySelector('[data-galat]'),hasil=root.querySelector('[data-hasil]'),kirim=form.querySelector('button[type=submit]'),sibuk=false,kotor=false;
  function el(n){return form.elements.namedItem(n);}
  function angka(n){return new Intl.NumberFormat('id-ID',{maximumFractionDigits:2}).format(n);}
  function hitung(){
    var o=el('sumber_id').selectedOptions[0],k=el('kemasan').selectedOptions[0];
    var unit=Number(o.dataset.unit||0),asal=Number(el('jumlah_asal').value||0)*unit,baru=Number(el('jumlah_baru').value||0)*Number(k.dataset.ukuran||0),sisa=Math.round((asal-baru)*100)/100;
    var curah=o.dataset.curah==='1';root.querySelector('[data-satuan]').textContent=curah?'kg':'karung';el('jumlah_asal').step=curah?'0.01':'1';el('jumlah_asal').min=curah?'0.01':'1';el('jumlah_asal').max=o.dataset.jumlah||'';
    root.querySelector('[data-preview]').textContent=unit&&k.dataset.ukuran?'Asal '+angka(asal)+' kg → kemasan baru '+angka(baru)+' kg · '+(sisa<0?'Melebihi asal '+angka(-sisa)+' kg':'Sisa curah '+angka(sisa)+' kg, tetap milik pemilik yang sama.'):'Pilih asal dan kemasan baru untuk memeriksa berat.';
    return {o:o,sisa:sisa};
  }
  form.addEventListener('input',function(){kotor=true;el('setuju').checked=false;hitung();});
  // Checkbox konfirmasi harus dapat dicentang setelah pemeriksaan.
  el('setuju').addEventListener('input',function(e){e.stopPropagation();});
  form.addEventListener('change',function(e){if(e.target!==el('setuju')){el('setuju').checked=false;hitung();}});
  root.querySelector('[data-periksa-stok]').addEventListener('click',async function(){
    if(sibuk||!el('sumber_id').value)return;
    if(window.SESIFORM&&!SESIFORM.periksa())return;
    var id=el('sumber_id').value;
    try{var r=await fetch('/api/kemas-ulang/pilihan?sumber_id='+encodeURIComponent(id),{credentials:'same-origin',cache:'no-store'});
      if(!r.ok)throw Error('Stok terbaru gagal dimuat. Isian Anda tetap tersedia.');var data=await r.json();
      var sel=el('sumber_id');sel.replaceChildren(new Option('Pilih batch asal',''));
      data.forEach(function(o){var opt=new Option(o.label,String(o.id));opt.dataset.kunci=o.kunci;opt.dataset.unit=o.unit;opt.dataset.jumlah=o.jumlah;opt.dataset.curah=o.curah?'1':'0';sel.add(opt);});
      sel.value=data.some(function(o){return String(o.id)===id;})?id:'';el('setuju').checked=false;hitung();
      galat.hidden=true;hasil.textContent='Stok terbaru dimuat. Jumlah isian Anda tetap ada; periksa kembali ringkasannya.';
    }catch(x){galat.textContent=x.message;galat.hidden=false;}
  });
  window.addEventListener('beforeunload',function(e){if(kotor){e.preventDefault();e.returnValue='';}});
  form.addEventListener('submit',async function(e){e.preventDefault();if(sibuk||!form.reportValidity())return;
    galat.hidden=true;var cek=hitung();if(cek.sisa<0){galat.textContent='Berat kemasan baru melebihi berat asal.';galat.hidden=false;el('jumlah_baru').focus();return;}
    if(window.SESIFORM&&!SESIFORM.periksa())return;
    var k=el('kemasan').value.split('|'),meta=document.getElementById('formulir-sesi');
    var data={sumber_id:Number(el('sumber_id').value),kunci:cek.o.dataset.kunci,jumlah_asal:Number(el('jumlah_asal').value),material:k[0],ukuran:Number(k[1]),merk:el('merk').value,jumlah_baru:Number(el('jumlah_baru').value),setuju:el('setuju').checked};
    var kontrol=Array.from(form.elements).map(function(x){return {el:x,disabled:x.disabled};});
    sibuk=true;kontrol.forEach(function(x){x.el.disabled=true;});kirim.textContent='Menyimpan…';
    try{
      var r=await fetch('/api/kemas-ulang',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':meta?meta.dataset.token:''},body:JSON.stringify(data)});
      if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi berubah. Periksa riwayat sebelum mengulang.');
      var d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Kemas ulang ditolak. Periksa kembali isian.');
      kotor=false;hasil.textContent='Kemas ulang #'+d.id+' tercatat: '+angka(d.berat_baru_kg)+' kg, sisa curah '+angka(d.sisa_kg)+' kg. Muat ulang untuk melanjutkan dari saldo terbaru.';
      Array.from(form.elements).forEach(function(x){x.disabled=true;});kirim.textContent='Tercatat';
    }catch(x){galat.textContent=x instanceof TypeError?'Jaringan gagal. Isian tetap tersedia; coba lagi dengan isian yang sama.':(x.message||'Kemas ulang gagal. Isian tetap tersedia.');galat.hidden=false;galat.tabIndex=-1;galat.focus();kontrol.forEach(function(x){x.el.disabled=x.disabled;});kirim.disabled=false;kirim.textContent='Coba catat lagi';}
    finally{sibuk=false;}
  });hitung();
})();
