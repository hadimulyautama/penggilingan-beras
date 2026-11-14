(function(){
  var box=document.querySelector('[data-pemulihan]');if(!box)return;
  var token=new URLSearchParams(location.hash.slice(1)).get('cap')||'';
  // Fragment tidak dikirim ke server/proxy. Hilangkan sebelum sumber lain dibuka.
  if(location.hash)history.replaceState(null,'',location.pathname);
  var form=box.querySelector('form'),msg=box.querySelector('[data-pesan]'),info=box.querySelector('[data-identitas]');
  var csrf=box.querySelector('[data-csrf-pemulihan]').value;
  async function post(path,data){
    var r=await fetch('/pemulihan/'+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data),cache:'no-store'});
    var j=await r.json();if(!r.ok)throw Error(typeof j.detail==='string'?j.detail:'Permintaan belum dapat diproses.');return j;
  }
  if(token.length!==64){info.textContent='Tautan tidak lengkap. Minta tautan pemulihan baru kepada Admin Sistem.';return;}
  post('periksa',{cap:token}).then(function(d){info.textContent=d.nama+' · '+d.username+' · '+d.perusahaan;form.hidden=false;}).catch(function(e){info.textContent=e.message;});
  form.addEventListener('submit',async function(e){
    e.preventDefault();var btn=form.querySelector('button');btn.disabled=true;msg.textContent='Menyimpan kata sandi…';
    try{
      var r=await post('simpan',{cap:token,sandi:form.elements.sandi.value,ulangi:form.elements.ulangi.value});
      token='';form.reset();form.hidden=true;msg.textContent='Kata sandi diperbarui. Silakan masuk kembali.';
      var link=box.querySelector('[data-masuk]');if(r.tujuan){link.href=r.tujuan;link.hidden=false;}else msg.textContent+=' Buka TeraFlow yang biasa Anda gunakan.';
    }catch(err){msg.textContent=err.message;}finally{btn.disabled=false;}
  });
})();
