/* Draf pribadi: satu kiriman berjalan, revisi diperiksa server, terbit eksplisit. */
(function () {
  var root=document.querySelector('[data-editor-perintah]');
  if (!root || root.dataset.siap) return;
  root.dataset.siap='1';
  var form=document.getElementById('draf-form'), status=document.getElementById('draf-status');
  var galat=document.getElementById('draf-galat'), coba=document.getElementById('draf-coba');
  var awal=JSON.parse(document.getElementById('draf-awal').textContent), revisi=awal.revisi;
  var identitas=root.dataset.editorPerintah, api='/api/actions/draf-perintah/'+identitas;
  var daftarBarang=[], pelanggan=[], armada=[], timer, berjalan=null, tertunda=null, konflik=null, siap=false, menerbitkan=false;
  var tersimpan=JSON.stringify(awal.isi), perubahan=0;
  var selectP=document.getElementById('draf-pelanggan-id'), inputP=document.getElementById('draf-pelanggan'), saranP=document.getElementById('draf-pelanggan-saran'), selectA=document.getElementById('draf-armada');
  var daftar=document.getElementById('draf-barang'), terbit=document.getElementById('draf-terbitkan');
  function uuid(){return crypto.randomUUID();}
  function sesi(){if(window.SESIFORM && !SESIFORM.periksa()) throw Error('Sesi berubah. Isian tetap tersedia; masuk dengan akun pembuka dan buka kembali draf ini.');}
  function pesan(teks){galat.textContent=teks;galat.hidden=false;}
  function opsi(sel, data, nilai, kosong) {
    sel.replaceChildren(new Option(kosong,''));
    data.forEach(function(o){sel.add(new Option(o.label,o.value));});
    if(nilai && !data.some(function(o){return String(o.value)===nilai;})) sel.add(new Option('Pilihan sebelumnya tidak tersedia ('+nilai+'). Pilih ulang.',nilai));
    sel.value=nilai||'';
  }
  function isi(){return {pelanggan:selectP.value,pelanggan_teks:inputP.value,tiket_armada:selectA.value,nama_ekspedisi:document.getElementById('draf-ekspedisi').value,
    barang:Array.from(daftar.children).map(function(row){return {pilih:row.querySelector('select').value,jumlah:row.querySelector('input').value};})};}
  function baris(b) {
    var row=document.createElement('div');row.className='draf-item';
    var label=document.createElement('label');label.textContent='Barang';
    var bungkus=document.createElement('div');bungkus.className='ulang__pilihan';
    var nama=document.createElement('span');nama.className='ulang__nama';
    var sel=document.createElement('select');sel.setAttribute('aria-label','Barang');
    opsi(sel,daftarBarang,b.pilih,'Pilih barang');bungkus.append(nama,sel);label.append(bungkus);
    var jumlahLabel=document.createElement('label');jumlahLabel.textContent='Jumlah';
    var input=document.createElement('input');input.className='fld';input.type='number';input.min='0';input.inputMode='decimal';input.value=b.jumlah==null?'':b.jumlah;
    var satuan=document.createElement('span');satuan.className='draf-satuan';
    var jumlahGrup=document.createElement('div');jumlahGrup.className='draf-jumlah';jumlahGrup.append(input,satuan);jumlahLabel.append(jumlahGrup);
    var hapus=document.createElement('button');hapus.type='button';hapus.className='btn';hapus.textContent='Hapus item';
    hapus.onclick=function(){row.remove();ubah();};
    function namaUnit(){nama.textContent=sel.selectedOptions[0].textContent;var karung=/^(bj:|[0-9]+\|)/.test(sel.value);satuan.textContent=karung?'karung':'kg';input.step=karung?'1':'any';input.setAttribute('aria-label','Jumlah '+satuan.textContent);}
    sel.addEventListener('change',namaUnit);namaUnit();row.append(label,jumlahLabel,hapus);daftar.append(row);
  }
  function pasang(data){selectP.value=data.pelanggan||'';var ditemukan=pelanggan.find(function(o){return String(o.value)===selectP.value;});inputP.value=ditemukan?ditemukan.label:(data.pelanggan_teks||'');if(!ditemukan)selectP.value='';tutupSaran();opsi(selectA,armada,data.tiket_armada,'Belum ada armada');
    document.getElementById('draf-ekspedisi').value=data.nama_ekspedisi||'';daftar.replaceChildren();(data.barang&&data.barang.length?data.barang:[{}]).forEach(baris);}
  async function kirim(url,method,data){sesi();var el=document.getElementById('formulir-sesi');
    var r=await fetch(url,{method:method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':el?el.dataset.token:''},body:JSON.stringify(data)});
    var j=await r.json().catch(function(){return {};});sesi();
    if(!r.ok){var e=Error(typeof j.detail==='string'?j.detail:(j.detail&&j.detail.pesan)||'Permintaan gagal. Isian tetap ada.');e.data=j.detail;e.status=r.status;throw e;}return j;
  }
  function tampilKonflik(data){konflik=data;document.getElementById('draf-konflik').hidden=false;terbit.disabled=true;
    var pembanding=document.getElementById('draf-pembanding');pembanding.replaceChildren();
    var p=document.createElement('p');p.textContent='Pelanggan: '+((pelanggan.find(function(o){return String(o.value)===data.isi.pelanggan;})||{}).label||data.isi.pelanggan||(data.isi.pelanggan_teks?data.isi.pelanggan_teks+' (belum dipilih)':'Belum dipilih'));pembanding.append(p);
    (data.isi.barang||[]).forEach(function(b){var p=document.createElement('p');p.textContent=((daftarBarang.find(function(o){return o.value===b.pilih;})||{}).label||b.pilih||'Belum dipilih')+' · '+b.jumlah+' '+(/^(bj:|[0-9]+\|)/.test(b.pilih)?'karung':'kg');pembanding.append(p);});
    var a=document.createElement('p');a.textContent='Armada: '+((armada.find(function(o){return String(o.value)===data.isi.tiket_armada;})||{}).label||data.isi.tiket_armada||'Belum ada')+' · Ekspedisi: '+(data.isi.nama_ekspedisi||'—');pembanding.append(a);
    if(data.tujuan){var link=document.createElement('a');link.href=data.tujuan;link.textContent='Buka perintah yang sudah terbit';pembanding.append(link);document.getElementById('draf-pakai-isian').disabled=true;}
  }
  async function simpan(){clearTimeout(timer);if(berjalan){await berjalan;return simpan();}if(konflik)throw Error('Periksa konflik draf dahulu.');
    var sekarang=isi();if(!tertunda && JSON.stringify(sekarang)===tersimpan)return;
    if(!tertunda)tertunda={revisi:revisi,kiriman:uuid(),isi:sekarang};
    status.textContent='Menyimpan…';coba.hidden=true;galat.hidden=true;
    berjalan=(async function(){try{var j=await kirim(api,'PUT',tertunda);revisi=j.revisi;tersimpan=JSON.stringify(tertunda.isi);tertunda=null;
      history.replaceState(null,'','/barang-keluar/draf/'+identitas);status.textContent='Tersimpan sebagai draf';
    }catch(e){status.textContent='Belum tersimpan';pesan(e.message);if(e.status===409 && e.data && e.data.isi)tampilKonflik(e.data);else coba.hidden=false;throw e;
    }finally{berjalan=null;}})();
    await berjalan;
    if(JSON.stringify(isi())!==tersimpan)return simpan();
  }
  function ubah(){if(!siap)return;perubahan++;status.textContent='Perubahan belum tersimpan';clearTimeout(timer);if(!konflik)timer=setTimeout(function(){simpan().catch(function(){});},600);}
  form.addEventListener('input',ubah);form.addEventListener('change',ubah);
  document.getElementById('draf-tambah').onclick=function(){baris({});ubah();};
  coba.onclick=function(){simpan().catch(function(){});};
  var opsiAktif=-1;
  function tutupSaran(){saranP.hidden=true;inputP.setAttribute('aria-expanded','false');inputP.removeAttribute('aria-activedescendant');opsiAktif=-1;}
  function pilihPelanggan(p){selectP.value=String(p.value);inputP.value=p.label;tutupSaran();ubah();}
  function saringPelanggan(){
    var q=inputP.value.trim().toLocaleLowerCase('id');
    var cocok=pelanggan.filter(function(p){return p.label.toLocaleLowerCase('id').includes(q);}).slice(0,50);
    saranP.replaceChildren();opsiAktif=-1;inputP.removeAttribute('aria-activedescendant');
    cocok.forEach(function(p,i){var btn=document.createElement('button');btn.type='button';btn.className='kombo__opsi';btn.id='draf-pelanggan-opsi-'+i;btn.setAttribute('role','option');btn.setAttribute('aria-selected','false');btn.tabIndex=-1;btn.textContent=p.label;
      btn.onmousedown=function(e){e.preventDefault();};btn.onclick=function(){pilihPelanggan(p);};saranP.append(btn);});
    if(!cocok.length){var kosong=document.createElement('p');kosong.className='kombo__kosong';kosong.textContent='Pelanggan tidak ditemukan. Pilih pelanggan yang sudah terdaftar.';saranP.append(kosong);}
    saranP.hidden=false;inputP.setAttribute('aria-expanded','true');
  }
  inputP.addEventListener('input',function(){selectP.value='';saringPelanggan();});
  inputP.addEventListener('focus',function(){if(siap)saringPelanggan();});
  inputP.addEventListener('blur',function(){setTimeout(tutupSaran,100);});
  inputP.addEventListener('keydown',function(e){
    if(e.key==='Escape'){tutupSaran();e.preventDefault();return;}
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      e.preventDefault();if(saranP.hidden)saringPelanggan();var opsi=Array.from(saranP.querySelectorAll('[role=option]'));if(!opsi.length)return;
      opsiAktif=opsiAktif<0?(e.key==='ArrowDown'?0:opsi.length-1):(opsiAktif+(e.key==='ArrowDown'?1:-1)+opsi.length)%opsi.length;
      opsi.forEach(function(o,i){o.setAttribute('aria-selected',String(i===opsiAktif));});
      inputP.setAttribute('aria-activedescendant',opsi[opsiAktif].id);opsi[opsiAktif].scrollIntoView({block:'nearest'});
    }else if(e.key==='Enter'&&!saranP.hidden){e.preventDefault();var aktif=saranP.querySelector('[aria-selected=true]');if(aktif)aktif.click();}
  });
  function selesaiKonflik(){revisi=konflik.revisi;tertunda=null;konflik=null;document.getElementById('draf-konflik').hidden=true;terbit.disabled=false;galat.hidden=true;}
  document.getElementById('draf-pakai-terbaru').onclick=function(){var data=konflik;if(data.tujuan){location.assign(data.tujuan);return;}pasang(data.isi);selesaiKonflik();tersimpan=JSON.stringify(isi());status.textContent='Draf terbaru dimuat';};
  document.getElementById('draf-pakai-isian').onclick=function(){selesaiKonflik();tersimpan=null;ubah();};
  form.onsubmit=async function(e){e.preventDefault();if(!siap||menerbitkan)return;
    galat.hidden=true;var invalid=Array.from(form.querySelectorAll('input[type=number]')).find(function(el){return !el.value||!el.checkValidity()||Number(el.value)<=0;});
    if(!selectP.value)invalid=inputP;
    if(!invalid)invalid=Array.from(daftar.querySelectorAll('select')).find(function(el){return !el.value;});
    if(!daftar.children.length){pesan('Tambahkan setidaknya satu barang.');document.getElementById('draf-tambah').focus();return;}
    if(invalid){pesan('Lengkapi pelanggan, barang, dan jumlah positif. Jumlah karung harus bilangan bulat.');invalid.focus();return;}
    menerbitkan=true;terbit.disabled=true;var versi=perubahan;
    try{await simpan();if(versi!==perubahan)throw Error('Isian berubah saat diperiksa. Periksa ulang lalu terbitkan.');
      form.querySelectorAll('input,select,button').forEach(function(el){el.disabled=true;});
      var j=await kirim(api+'/terbitkan','POST',{revisi:revisi});if(!/^\/barang-keluar\/\d+$/.test(j.tujuan))throw Error('Periksa daftar perintah sebelum mengulang.');
      tersimpan=JSON.stringify(isi());location.assign(j.tujuan);
    }catch(e){pesan(e.message);if(e.status===409&&e.data&&e.data.isi)tampilKonflik(e.data);}
    finally{menerbitkan=false;form.querySelectorAll('input,select,button').forEach(function(el){el.disabled=false;});if(konflik)terbit.disabled=true;}
  };
  window.addEventListener('beforeunload',function(e){if(siap&&(tertunda||JSON.stringify(isi())!==tersimpan)){e.preventDefault();e.returnValue='';}});
  Promise.all(['/api/actions/barang-bisa-keluar','/api/actions/pelanggan-kledo','/api/actions/tiket-armada'].map(async function(url){var r=await fetch(url,{credentials:'same-origin'});if(!r.ok)throw Error('Daftar pilihan gagal dimuat. Muat ulang halaman; draf yang tersimpan tetap ada.');return r.json();})).then(function(data){daftarBarang=data[0];pelanggan=data[1];armada=data[2];pasang(awal.isi);tersimpan=JSON.stringify(isi());siap=true;status.textContent=revisi?'Tersimpan sebagai draf':'Belum ada perubahan';}).catch(function(e){pesan(e.message);terbit.disabled=true;});
})();
