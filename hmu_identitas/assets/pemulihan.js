(function(){'use strict';
  var box=document.querySelector('[data-pemulihan]');if(!box)return;
  var fragment=new URLSearchParams(location.hash.slice(1)),token=fragment.get('cap')||'',product=fragment.get('produk')||'';
  if(location.hash)history.replaceState(null,'',location.pathname);
  var form=box.querySelector('form'),msg=box.querySelector('[data-pesan]'),info=box.querySelector('[data-identitas]'),retry=box.querySelector('[data-retry-pemulihan]');
  var csrf=box.querySelector('[data-csrf-pemulihan]').value,checking=false,saving=false,verified=false,uncertainSave=false;
  function failure(message,transient){var e=new Error(message);e.transient=transient;return e;}
  async function post(path,data){
    var controller=new AbortController(),timer=setTimeout(function(){controller.abort();},15000);
    try{
    var response;
    try{response=await fetch('/pemulihan/'+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data),cache:'no-store',signal:controller.signal});}
    catch(e){throw failure('Sambungan terputus. Isian tetap tersedia; coba lagi saat koneksi kembali.',true);}
    var result;try{result=await response.json();}catch(e){throw failure('Layanan belum memberi jawaban yang dapat dibaca. Isian tetap tersedia; coba lagi sebentar lagi.',true);}
    if(!response.ok){if(response.status>=500||response.status===429)throw failure('Layanan pemulihan sedang terganggu. Isian tetap tersedia; coba lagi sebentar lagi.',true);throw failure(result&&typeof result.detail==='string'?result.detail:'Permintaan belum dapat diproses. Periksa tautan pemulihan.',false);}
    if(!result||typeof result!=='object'||Array.isArray(result))throw failure('Jawaban layanan belum dapat diperiksa. Coba lagi sebentar lagi.',true);
    return result;
    }finally{clearTimeout(timer);}
  }
  async function check(){
    if(checking||saving||verified||token.length!==64)return;
    checking=true;retry.hidden=true;info.textContent='Memeriksa tautan pemulihan…';
    try{var data=await post('periksa',{cap:token,produk:product});
      if(typeof data.nama!=='string'||typeof data.username!=='string'||typeof data.perusahaan!=='string')throw failure('Identitas belum dapat diperiksa. Coba lagi sebentar lagi.',true);
      info.textContent=data.nama+' · '+data.username+' · '+data.perusahaan+(product?' · '+(product==='teraflow'?'TeraFlow':'PadiFlow'):'');
      verified=true;form.hidden=false;var impact=box.querySelector('[data-dampak-bersama]');if(impact)impact.hidden=data.jenis!=='staf';
    }catch(e){info.textContent=e.message;retry.hidden=!e.transient;}finally{checking=false;}
  }
  if(token.length!==64||['','padiflow','teraflow'].indexOf(product)<0){info.textContent='Tautan tidak lengkap. Minta tautan pemulihan baru kepada Admin Sistem.';return;}
  retry.addEventListener('click',check);window.addEventListener('online',check);check();
  form.addEventListener('submit',async function(e){
    e.preventDefault();if(saving||!verified||token.length!==64)return;
    saving=true;var btn=form.querySelector('button');btn.disabled=true;msg.textContent='Menyimpan kata sandi…';
    try{var result=await post('simpan',{cap:token,produk:product,sandi:form.elements.sandi.value,ulangi:form.elements.ulangi.value});
      if(result.berhasil!==true)throw failure('Hasil penyimpanan belum dapat dipastikan. Isian tetap tersedia; periksa kembali sebelum mencoba lagi.',true);
      token='';verified=false;form.reset();form.hidden=true;retry.hidden=true;msg.textContent='Kata sandi diperbarui. Silakan masuk kembali.';
      var link=box.querySelector('[data-masuk]');if(result.tujuan){link.href=result.tujuan;link.hidden=false;}else msg.textContent+=' Hubungi Admin Sistem jika akses produk pilihan belum tersedia.';
    }catch(err){if(err.transient)uncertainSave=true;msg.textContent=err.message+(uncertainSave?' Jawaban penyimpanan sebelumnya mungkin terputus. Coba masuk dengan sandi yang Anda kirim sebelumnya, atau minta tautan baru jika sudah dipakai.':'');}finally{saving=false;btn.disabled=false;}
  });
})();
