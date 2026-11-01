/* Pencatatan pengukuran saja; tidak mengirim tindakan stok. */
(() => {
 'use strict';
 const root=document.querySelector('[data-bobot-pengeringan]');if(!root)return;
 let data=JSON.parse(document.getElementById('bobot-pengeringan-awal').textContent);
 const form=root.querySelector('form'),preview=root.querySelector('[data-preview]'),message=root.querySelector('[data-pesan]'),save=root.querySelector('[data-simpan]'),read=root.querySelector('[data-baca]');
 let key=crypto.randomUUID(),checked=null,busy=false,dirty=false,uncertain=false;
 const values=()=>({lot_id:data.lot_id,kg:Number(form.elements.kg.value),referensi:form.elements.referensi.value.trim(),alasan:form.elements.alasan.value.trim(),konfirmasi:form.elements.konfirmasi.checked,dasar:data.dasar,kunci:key});
 const freeze=()=>{for(const e of form.elements)e.disabled=busy||uncertain;save.disabled=busy||uncertain;read.disabled=busy;};
 function paint(){
  const area=root.querySelector('.bobot-pengeringan'),labels=area.querySelectorAll('dt'),numbers=area.querySelectorAll('dd');
  numbers[0].textContent=data.bobot.basah||'Belum diketahui';
  labels[1].textContent=data.bobot.terukur?'Bobot gabah kering terukur':'Estimasi bobot gabah kering';
  numbers[1].textContent=data.bobot.terukur||(data.bobot.kering?'≈ '+data.bobot.kering:'Belum tersedia');
  area.querySelector('small').textContent=data.bobot.terukur?'Hasil timbang flowing scale':'Estimasi · belum ditimbang';
 }
 function changed(){if(!dirty)key=crypto.randomUUID();dirty=true;checked=null;preview.hidden=true;}
 form.addEventListener('input',changed);
 async function call(body){
  if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi atau peran berubah. Buka kembali formulir pada peran yang benar.');
  const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),25000);
  try {
  const response=await fetch('/api/actions/bobot-pengeringan'+(body?'':'?lot_id='+data.lot_id),{signal:abort.signal,method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':document.getElementById('formulir-sesi')?.dataset.token||''},body:body?JSON.stringify(body):undefined});
  let result;try{result=await response.json();}catch(_){throw Error('Balasan belum lengkap.');}
  if(!response.ok){const e=Error(typeof result.detail==='string'?result.detail:'Periksa kembali isian dan izin Anda.');e.known=response.status>=400&&response.status<500;throw e;}
  return result;
  } finally {clearTimeout(timer);}
 }
 form.addEventListener('submit',e=>{e.preventDefault();if(busy||uncertain||!form.reportValidity())return;checked=values();root.querySelector('[data-ringkasan]').textContent=data.kode+': '+(data.terukur?.kg||'Belum tercatat')+' → '+form.elements.kg.value+' kg. Referensi: '+checked.referensi+(checked.alasan?'. Catatan: '+checked.alasan:'');preview.hidden=false;message.textContent='Baca ringkasan sebelum menyimpan.';});
 save.addEventListener('click',async()=>{
  if(busy||uncertain||!checked||JSON.stringify(checked)!==JSON.stringify(values()))return;
  busy=true;freeze();message.textContent='Menyimpan catatan timbang…';
  try{const result=await call(checked);data=result.data;paint();dirty=false;checked=null;preview.hidden=true;form.elements.alasan.required=true;message.textContent=result.pesan;}
  catch(e){uncertain=!e.known;message.textContent=uncertain?'Status simpan belum dapat dipastikan. Isian dipertahankan. Periksa status terbaru sebelum mengulang.':e.message;checked=null;preview.hidden=true;read.hidden=false;}
  finally{busy=false;freeze();}
 });
 read.addEventListener('click',async()=>{
  if(busy)return;busy=true;freeze();
  try{const latest=await call();const found=latest.terukur?.kunci===key;data=latest;paint();checked=null;preview.hidden=true;
   if(found){dirty=false;message.textContent='Catatan timbang sudah tersimpan. Tidak dikirim ulang.';}
   else message.textContent='Data terbaru telah dimuat; isian Anda tetap tersedia. Baca kembali bobot terakhir '+(data.terukur?.kg||'belum tercatat')+' kg, lalu periksa dan konfirmasi ulang.';
   uncertain=false;form.elements.alasan.required=!!data.terukur;read.hidden=true;
  }catch(e){message.textContent='Status terbaru belum dapat dibaca. Isian tetap tersedia; jangan mengirim ulang sebelum status dipastikan.';}
  finally{busy=false;freeze();}
 });
 window.addEventListener('beforeunload',e=>{if(root.isConnected&&(dirty||busy||uncertain)){e.preventDefault();e.returnValue='';}});
 document.addEventListener('click',e=>{if(root.isConnected&&(dirty||busy||uncertain)&&e.target.closest('a[href]')&&!confirm('Isian belum selesai. Tinggalkan halaman ini?')){e.preventDefault();e.stopImmediatePropagation();}},true);
})();
