/* Hapus hanya draf pribadi; revisi dan identitas diperiksa kembali di server. */
(function(){
  var daftar=document.querySelector('[data-daftar-draf]');
  if(!daftar||daftar.dataset.siap)return;daftar.dataset.siap='1';
  daftar.addEventListener('click',async function(e){
    var tombol=e.target.closest('[data-hapus-draf]');if(!tombol||tombol.disabled)return;
    if(window.SESIFORM&&!SESIFORM.periksa())return;
    if(!confirm('Hapus draf '+tombol.dataset.nama+' · '+tombol.dataset.item+' item? Draf tidak dapat dilanjutkan setelah dihapus.'))return;
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
