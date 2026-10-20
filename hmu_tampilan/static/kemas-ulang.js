/* Tidak mengubah stok sampai operator menyetujui ringkasan dan mengirim. */
(function(){
  var root=document.querySelector('[data-kemas-ulang]');if(!root||root.dataset.siap)return;root.dataset.siap='1';
  var form=root.querySelector('form'),galat=root.querySelector('[data-galat]'),hasil=root.querySelector('[data-hasil]'),kirim=form.querySelector('button[type=submit]'),sibuk=false,kotor=false,saldo=null,urutan=0;
  var infoSaldo=root.querySelector('[data-saldo-kemasan]');
  function namaMerek(){return el('merk').value==='__tanpa__'?'':el('merk').value;}
  function daftarMerek(){var o=el('kemasan').selectedOptions[0];try{return JSON.parse(o.dataset.merek||'[]');}catch(_){return [];}}
  function isiMerek(lama,otomatis){
    var list=daftarMerek(),sel=el('merk');sel.replaceChildren(new Option(list.length?'Pilih merek':'Pilih kemasan dahulu',''));
    list.forEach(function(m){sel.add(new Option(m.label+' · '+angka(m.tersedia)+' lembar',m.value||'__tanpa__'));});
    sel.disabled=!list.length;
    if(list.some(function(m){return (m.value||'__tanpa__')===lama;}))sel.value=lama;
    else if(otomatis&&list.length===1)sel.value=list[0].value||'__tanpa__';
    var kosong=el('kemasan').options.length<=1;
    root.querySelector('[data-kemasan-kosong]').hidden=!kosong;kirim.disabled=kosong;
  }
  async function periksaDaftar(){
    var id=el('sumber_id').value,lama=el('kemasan').value,merk=el('merk').value;
    var r=await fetch('/api/kemas-ulang/kemasan-tersedia?sumber_id='+encodeURIComponent(id),{credentials:'same-origin',cache:'no-store'});
    if(!r.ok)throw Error('Daftar kemasan tersedia gagal dimuat. Isian tetap tersedia.');var list=await r.json();
    if(el('sumber_id').value!==id||el('kemasan').value!==lama||el('merk').value!==merk)return;
    var sel=el('kemasan');sel.replaceChildren(new Option('Pilih kemasan baru',''));
    list.forEach(function(p){var opt=new Option(p.label,p.value);opt.dataset.ukuran=p.ukuran;opt.dataset.merek=JSON.stringify(p.merek);sel.add(opt);});
    sel.value=list.some(function(p){return p.value===lama;})?lama:'';
    isiMerek(merk,false);saldo=null;el('setuju').checked=false;hitung();
  }
  function tampilSaldo(){
    if(!infoSaldo||saldo===null)return;
    var perlu=Number(el('jumlah_baru').value||0);
    infoSaldo.textContent='Stok kemasan baru milik '+saldo.pemilik+': '+angka(saldo.tersedia)+' lembar'+(perlu?' · diperlukan '+angka(perlu)+' lembar.':'.');
    if(saldo.tersedia<perlu||saldo.tersedia===0)infoSaldo.textContent+=' Belum cukup. Pilih kemasan yang tersedia atau minta admin mencatat penerimaan/pemindahan kepemilikan kemasan yang benar.';
  }
  async function periksaKemasan(){
    var n=++urutan;saldo=null;
    if(!el('sumber_id').value||!el('kemasan').value||!el('merk').value){if(infoSaldo)infoSaldo.textContent='Pilih batch dan kemasan baru untuk melihat ketersediaan.';return;}
    var k=el('kemasan').value.split('|');if(infoSaldo)infoSaldo.textContent='Memeriksa stok kemasan baru…';
    try{var r=await fetch('/api/kemas-ulang/kemasan?'+new URLSearchParams({sumber_id:el('sumber_id').value,material:k[0],ukuran:k[1],merk:namaMerek()}),{credentials:'same-origin',cache:'no-store'});
      var d=await r.json();if(n!==urutan)return;if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Stok kemasan belum dapat diperiksa.');
      if(typeof d.tersedia!=='number')throw Error('Stok kemasan belum dapat diperiksa.');saldo=d;tampilSaldo();if(d.tersedia<=0){await periksaDaftar();if(infoSaldo)infoSaldo.textContent='Pilihan kemasan tadi sudah habis. Daftar diperbarui; pilih kembali kemasan dan merek yang tersedia.';}
    }catch(x){if(n===urutan&&infoSaldo)infoSaldo.textContent='Stok kemasan belum dapat diperiksa. Server akan memeriksa kembali saat dicatat.';}
  }
  function gagal(pesan,isian,belumPasti){galat.textContent=(belumPasti?'Status simpan belum dapat dipastikan. ':'Belum tersimpan. ')+pesan;galat.hidden=false;galat.tabIndex=-1;galat.focus();galat.scrollIntoView({block:'center'});if(isian)isian.setAttribute('aria-invalid','true');}

  function el(n){return form.elements.namedItem(n);}
  function angka(n){return new Intl.NumberFormat('id-ID',{maximumFractionDigits:2}).format(n);}
  function hitung(){
    var o=el('sumber_id').selectedOptions[0],k=el('kemasan').selectedOptions[0];
    var unit=Number(o.dataset.unit||0),asal=Number(el('jumlah_asal').value||0)*unit,baru=Number(el('jumlah_baru').value||0)*Number(k.dataset.ukuran||0),sisa=Math.round((asal-baru)*100)/100;
    var curah=o.dataset.curah==='1';root.querySelector('[data-satuan]').textContent=curah?'kg':'karung';el('jumlah_asal').step=curah?'0.01':'1';el('jumlah_asal').min=curah?'0.01':'1';el('jumlah_asal').max=o.dataset.jumlah||'';
    root.querySelector('[data-preview]').textContent=unit&&k.dataset.ukuran?'Asal '+angka(asal)+' kg → kemasan baru '+angka(baru)+' kg · '+(sisa<0?'Melebihi asal '+angka(-sisa)+' kg':'Sisa curah '+angka(sisa)+' kg, tetap milik pemilik yang sama.'):'Pilih asal dan kemasan baru untuk memeriksa berat.';
    tampilSaldo();return {o:o,sisa:sisa};
  }
  form.addEventListener('input',function(e){e.target.removeAttribute('aria-invalid');kotor=true;el('setuju').checked=false;hitung();});
  // Checkbox konfirmasi harus dapat dicentang setelah pemeriksaan.
  el('setuju').addEventListener('input',function(e){e.stopPropagation();});
  form.addEventListener('change',function(e){if(e.target!==el('setuju')){kotor=true;el('setuju').checked=false;if(e.target===el('kemasan'))isiMerek('',true);hitung();if(['sumber_id','kemasan','merk'].indexOf(e.target.name)>=0)periksaKemasan();}});
  root.querySelector('[data-periksa-stok]').addEventListener('click',async function(){
    if(sibuk||!el('sumber_id').value)return;
    if(window.SESIFORM&&!SESIFORM.periksa())return;
    var id=el('sumber_id').value;
    try{var r=await fetch('/api/kemas-ulang/pilihan?sumber_id='+encodeURIComponent(id),{credentials:'same-origin',cache:'no-store'});
      if(!r.ok)throw Error('Stok terbaru gagal dimuat. Isian Anda tetap tersedia.');var data=await r.json();
      var sel=el('sumber_id');sel.replaceChildren(new Option('Pilih batch asal',''));
      data.forEach(function(o){var opt=new Option(o.label,String(o.id));opt.dataset.kunci=o.kunci;opt.dataset.unit=o.unit;opt.dataset.jumlah=o.jumlah;opt.dataset.curah=o.curah?'1':'0';sel.add(opt);});
      sel.value=data.some(function(o){return String(o.id)===id;})?id:'';el('setuju').checked=false;hitung();await periksaDaftar();await periksaKemasan();
      galat.hidden=true;hasil.textContent='Stok terbaru dimuat. Jumlah isian Anda tetap ada; periksa kembali ringkasannya.';
    }catch(x){gagal(x.message);}
  });
  window.addEventListener('beforeunload',function(e){if(kotor){e.preventDefault();e.returnValue='';}});
  form.addEventListener('submit',async function(e){e.preventDefault();if(sibuk||!form.reportValidity())return;
    galat.hidden=true;var cek=hitung();if(cek.sisa<0){gagal('Berat kemasan baru melebihi berat asal.',el('jumlah_baru'));return;}
    if(saldo&&Number(el('jumlah_baru').value)>saldo.tersedia){gagal('Kemasan baru tidak cukup: tersedia '+angka(saldo.tersedia)+' lembar, diperlukan '+angka(Number(el('jumlah_baru').value))+' lembar. Pilih kemasan yang tersedia atau periksa stok bersama admin.',el('kemasan'));return;}
    if(window.SESIFORM&&!SESIFORM.periksa())return;
    var k=el('kemasan').value.split('|'),meta=document.getElementById('formulir-sesi');
    var data={sumber_id:Number(el('sumber_id').value),kunci:cek.o.dataset.kunci,jumlah_asal:Number(el('jumlah_asal').value),material:k[0],ukuran:Number(k[1]),merk:namaMerek(),jumlah_baru:Number(el('jumlah_baru').value),setuju:el('setuju').checked};
    var kontrol=Array.from(form.elements).map(function(x){return {el:x,disabled:x.disabled};});
    sibuk=true;kontrol.forEach(function(x){x.el.disabled=true;});kirim.textContent='Menyimpan…';
    try{
      var r=await fetch('/api/kemas-ulang',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':meta?meta.dataset.token:''},body:JSON.stringify(data)});
      if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi berubah. Periksa riwayat sebelum mengulang.');
      var d;try{d=await r.json();}catch(_){throw Error(r.status===403||r.status===401?'Sesi berakhir atau berubah. Salin isian, masuk kembali, lalu buka formulir baru.':'Jawaban server tidak lengkap. Periksa riwayat sebelum mencoba kembali; isian tetap tersedia.');}if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:(r.status===401||r.status===403?'Sesi berakhir atau berubah. Salin isian, masuk kembali, lalu buka formulir baru.':r.status===422?'Isian tidak valid. Periksa jumlah asal, jumlah karung baru, kemasan, dan konfirmasi.':'Kemas ulang ditolak oleh server (kode '+r.status+'). Isian tetap tersedia; periksa stok dan coba kembali.'));
      kotor=false;if(window.PINDAH&&PINDAH.lupakan)PINDAH.lupakan();hasil.textContent='Kemas ulang #'+d.id+' tercatat: '+angka(d.berat_baru_kg)+' kg, sisa curah '+angka(d.sisa_kg)+' kg. Buka stok untuk melanjutkan dari saldo terbaru.';
      Array.from(form.elements).forEach(function(x){x.disabled=true;});kirim.textContent='Tercatat';var selesai=root.querySelector('[data-selesai]');if(selesai){selesai.hidden=false;selesai.textContent='Kembali ke detail produk';if(d.kembali)selesai.href=d.kembali;}if(d.kembali&&/^\/stok-produk(?:-jasa)?\/detail\?/.test(d.kembali)){window.location.assign(d.kembali+'#kemas-ulang-berhasil');return;}hasil.tabIndex=-1;hasil.focus();hasil.scrollIntoView({block:'center'});
    }catch(x){gagal(x instanceof TypeError?'Jaringan gagal. Isian tetap tersedia; periksa riwayat sebelum mengulang dengan isian yang sama.':(x.message||'Kemas ulang gagal. Isian tetap tersedia.'),null,!(r&&r.status>=400&&r.status<500));kontrol.forEach(function(x){x.el.disabled=x.disabled;});kirim.disabled=false;kirim.textContent='Coba catat lagi';}
    finally{sibuk=false;}
  });isiMerek('',false);hitung();
})();
