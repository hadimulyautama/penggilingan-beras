/* Hapus hanya draf pribadi; revisi dan identitas diperiksa kembali di server. */
(function(){
  var daftar=document.querySelector('[data-daftar-draf]');
  if(!daftar||daftar.dataset.siap)return;daftar.dataset.siap='1';
  var dialog=daftar.querySelector('[data-dialog-hapus-draf]');
  dialog.querySelector('[data-batal-hapus-draf]').onclick=function(){dialog.close('batal');};
  dialog.querySelector('[data-setuju-hapus-draf]').onclick=function(){dialog.close('hapus');};
  dialog.addEventListener('click',function(e){
    var r=dialog.getBoundingClientRect();
    if(e.target===dialog&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))dialog.close('batal');
  });
  function konfirmasi(tombol){
    if(dialog.open)return Promise.resolve(false);
    dialog.querySelector('[data-nama-hapus-draf]').textContent=tombol.dataset.nama;
    dialog.querySelector('[data-item-hapus-draf]').textContent=tombol.dataset.item+' item';
    // Escape harus selalu berarti Batal, termasuk sesudah dialog sebelumnya disetujui.
    dialog.returnValue='batal';
    return new Promise(function(resolve){
      dialog.addEventListener('close',function(){resolve(dialog.returnValue==='hapus');},{once:true});
      dialog.showModal();
    });
  }
  daftar.addEventListener('click',async function(e){
    var tombol=e.target.closest('[data-hapus-draf]');if(!tombol||tombol.disabled)return;
    if(window.SESIFORM&&!SESIFORM.periksa())return;
    if(!await konfirmasi(tombol))return;
    if(window.SESIFORM&&!SESIFORM.periksa())return;
    var galat=daftar.querySelector('[data-galat-draf]');galat.hidden=true;tombol.disabled=true;
    try{
      var konteks=document.getElementById('formulir-sesi');
      var r=await fetch('/api/actions/draf-perintah/'+encodeURIComponent(tombol.dataset.hapusDraf)+'/hapus',{
        method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':konteks?konteks.dataset.token:''},body:JSON.stringify({revisi:Number(tombol.dataset.revisi)})});
      var j=await r.json().catch(function(){return {};});
      if(window.SESIFORM&&!SESIFORM.periksa())throw Error('Sesi berubah. Periksa daftar dengan akun pembuka sebelum mengulang.');
      if(!r.ok)throw Error(typeof j.detail==='string'?j.detail:'Gagal menghapus draf. Coba lagi.');
      tombol.closest('[data-baris-draf]').remove();
      var n=daftar.querySelectorAll('[data-baris-draf]').length;
      daftar.querySelector('[data-jumlah-draf]').textContent=n;daftar.querySelector('[data-draf-kosong]').hidden=n>0;
      if(window.PINDAH)PINDAH.lupakan();
    }catch(err){galat.textContent=(err instanceof TypeError?'Jaringan gagal. Draf tetap di daftar; coba lagi.':err.message)||'Gagal menghapus draf. Coba lagi.';galat.hidden=false;tombol.disabled=false;}
  });
})();
