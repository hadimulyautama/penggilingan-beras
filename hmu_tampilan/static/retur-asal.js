/* Formulir lama tetap penulis tunggal. Jangan mengulang POST yang jawabannya
   hilang: operator harus memeriksa pengajuan/riwayat sebelum mencoba lagi. */
(function(){
 'use strict';
 document.querySelectorAll('form[data-retur-form]').forEach(function(f){
  if(f.dataset.returSiap)return;f.dataset.returSiap='1';
  var busy=false,uncertain=false;
  var msg=document.createElement('div');msg.className='retur-form-message';msg.setAttribute('role','status');msg.hidden=true;f.appendChild(msg);
  function buttons(disabled){f.querySelectorAll('button').forEach(function(b){if(!b.dataset.awalDisabled)b.dataset.awalDisabled=b.disabled?'1':'0';b.disabled=disabled||b.dataset.awalDisabled==='1';});}
  function inform(text,unknown){msg.hidden=false;msg.textContent=text;if(unknown){var a=document.createElement('a');a.href=location.pathname;a.target='_blank';a.rel='noopener';a.textContent=' Periksa status di tab baru';msg.appendChild(a);var list=document.createElement('a');list.href='/retur';list.target='_blank';list.rel='noopener';list.textContent=' · Daftar pengajuan dan riwayat retur';msg.appendChild(list);}}
  f.addEventListener('submit',async function(e){
   e.preventDefault();if(busy||uncertain)return;
   if(!f.reportValidity())return;
   var reason=f.querySelector('[name=alasan]');if(reason&&reason.required&&!reason.value.trim()){inform('Isi alasan yang sah, bukan spasi kosong.');reason.focus();return;}
   var payload=new FormData(f);busy=true;buttons(true);f.setAttribute('aria-busy','true');inform('Menyimpan pengajuan dan memeriksa data terbaru…');
   try{
    var response=await fetch(f.action,{method:'POST',body:payload,headers:{Accept:'application/json'},credentials:'same-origin'});
    if(response.status>=500||response.redirected)throw new Error('unknown');
    var data=await response.json();
    if(!response.ok){inform(data.detail||'Data belum dapat disimpan. Periksa isian dan batas terbaru.');buttons(false);return;}
    if(!data.ok||!data.alamat)throw new Error('unknown');
    inform('Server mengonfirmasi penyimpanan. Membuka status pengajuan…');location.assign(data.alamat);
   }catch(_){uncertain=true;inform('Status penyimpanan belum dapat dipastikan. Isian tetap tersedia. Periksa pengajuan dan riwayat terbaru sebelum mengulang; jangan membuat pengajuan yang sama lagi jika sudah tercatat.',true);}
   finally{busy=false;f.removeAttribute('aria-busy');}
  });
 });
})();
