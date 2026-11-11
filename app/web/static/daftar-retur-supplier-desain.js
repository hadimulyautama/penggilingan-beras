/* Satu GET form asli. Kepemilikan HTML form mempertahankan seluruh filter
   ketika kolom cari tetap di halaman dan rincian filter berada di dialog. */
(function(){
 'use strict';
 const root=document.querySelector('[data-daftar-retur-supplier]');if(!root||root.dataset.rrsReady)return;
 const form=root.querySelector('#rrs-form'),fields=form?.querySelector('.rsh-filter'),dialog=root.querySelector('#rrs-filter'),slot=root.querySelector('[data-rrs-filter-slot]');
 if(!form||!fields||!dialog||!slot)return;
 const scope=root.closest('[data-daftar-riwayat-proses]')||root;
 // Tidak menyalin field atau membentuk query baru. Browser mengirim lima
 // filter, q dan batas penerimaan bersama, termasuk saat menekan Enter/Cari.
 for(const control of fields.querySelectorAll('input,select,textarea,button'))control.setAttribute('form',form.id);
 slot.append(fields);fields.open=true;fields.querySelector('summary').hidden=true;
 for(const button of scope.querySelectorAll('[data-rrs-filter-open]')){
  button.hidden=false;button.onclick=()=>{const menu=scope.querySelector('.rhs-menu');if(menu)menu.open=false;dialog.showModal();};
 }
 root.querySelector('[data-rrs-filter-close]').onclick=()=>dialog.close();
 root.dataset.rrsReady='1';
})();
