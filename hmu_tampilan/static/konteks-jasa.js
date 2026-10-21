/* Satu tautan kembali melewati halaman operasional; tidak mengisi formulir
   transaksi, tidak mengganti pemilik, dan tidak membuat permintaan simpan. */
(function(){
  var el=document.querySelector('[data-kembali-jasa]');if(!el)return;
  var kembali=el.dataset.kembaliJasa;
  function pasang(){
    document.querySelectorAll('main a[href]').forEach(function(a){
      var raw=a.getAttribute('href');if(!raw||raw[0]==='#')return;
      var u=new URL(raw,location.href);
      if(u.origin!==location.origin||!/^\/(stok(?:[/-]|$)|barang-masuk(?:[/?]|$)|pekerjaan$|proses-aktif\/|riwayat-|barang-keluar(?:\/|$)|retur(?:\/|$)|jasa(?:\/|$)|kemas-ulang)/.test(u.pathname))return;
      if(u.pathname==='/jasa'||u.pathname.startsWith('/jasa/pelanggan/'))return;
      if(!u.searchParams.has('kembali_jasa'))u.searchParams.set('kembali_jasa',kembali);
      a.href=u.pathname+u.search+u.hash;
    });
    document.querySelectorAll('main form[method="get"]').forEach(function(f){
      if(f.querySelector('[name="kembali_jasa"]'))return;
      var i=document.createElement('input');i.type='hidden';i.name='kembali_jasa';i.value=kembali;f.appendChild(i);
    });
  }
  pasang();
  if(window.PINDAH&&PINDAH.pasang)PINDAH.pasang(document,'input',pasang);
})();
