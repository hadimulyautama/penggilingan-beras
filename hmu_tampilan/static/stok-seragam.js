/* Pendengar terikat kepala halaman yang ikut diganti oleh PINDAH. */
(function () {
  function pasang(root) {
  if (!root || root.dataset.skTerpasang) return;
  root.dataset.skTerpasang = "1";
  var asal;
  root.querySelectorAll('[data-sk-buka]').forEach(function (tombol) {
    tombol.addEventListener('click', function () {
      var tujuan = root.querySelector('#' + tombol.dataset.skBuka);
      root.querySelectorAll('dialog[open]').forEach(function (d) { d.close(); });
      if (!tombol.closest('dialog')) asal = tombol;
      tujuan.showModal();
    });
  });
  root.querySelectorAll('dialog').forEach(function (d) {
    d.querySelector('[data-sk-tutup]').addEventListener('click', function () { d.close(); });
    d.addEventListener('click', function (e) {
      var r = d.getBoundingClientRect();
      if (e.target === d && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) d.close();
    });
    d.addEventListener('close', function () { if (asal && !root.querySelector('dialog[open]')) asal.focus(); });
  });
  root.querySelectorAll('[data-sk-cetak]').forEach(function (b) {
    b.addEventListener('click', function () {
      root.querySelectorAll('dialog[open]').forEach(function (d) { d.close(); });
      window.print();
    });
  });

  pasangDaftar(root);

  }
  
  pasang(document.querySelector('[data-stok-controls]'));
/* Saldo adalah informasi cakupan, bukan jumlah yang boleh berubah karena
 * menyaring tampilan. Semua baris sudah dirender oleh pembaca stok lama. */
function pasangDaftar(root) {
  var isi=document.querySelector('.stok-seragam');if(!isi)return;
  var input=root.querySelector('[type=search]'),form=root.querySelector('.kontrol-pencarian__form');
  function cari(tulis) {
    var q=input.value.trim().toLocaleLowerCase('id'),jumlah=0;
    isi.querySelectorAll('.stok-baris__tautan,.stok-mobile-list__baris,.produk-list .tabel-standar__item,.karung-tabel tbody tr').forEach(function(row){
      var pemilik=row.closest('[data-pemilik]');
      var cocok=!q||(row.textContent+' '+(pemilik?pemilik.dataset.pemilik:'')).toLocaleLowerCase('id').includes(q);
      var target=row.matches('.stok-baris__tautan')?row.closest('tr'):row;target.hidden=!cocok;
      if(cocok&&row.getClientRects().length)jumlah++;
    });
    var hasil=root.querySelector('[data-stok-hasil]');hasil.hidden=!q;
    hasil.textContent=q?jumlah+' baris cocok. Angka total tetap saldo seluruh cakupan.':'';
    if(tulis){var u=new URL(location.href);if(input.value.trim())u.searchParams.set('cari',input.value.trim());else u.searchParams.delete('cari');history.replaceState(history.state,'',u.pathname+u.search);}
    root.querySelector('.sk-form-filter [name=cari]').value=input.value;
    if(tulis)document.querySelectorAll('[data-stok-controls] .kontrol-tab a,.stok-seragam a[href],.sk-form-filter>a').forEach(function(a){
      var u=new URL(a.href,location.href);if(u.origin!==location.origin)return;
      if(u.pathname==='/stok'){if(input.value.trim())u.searchParams.set('cari',input.value.trim());else u.searchParams.delete('cari');}
      if(u.searchParams.has('kembali_stok')){var k=new URL(u.searchParams.get('kembali_stok'),location.href);if(k.origin===location.origin&&k.pathname==='/stok'){if(input.value.trim())k.searchParams.set('cari',input.value.trim());else k.searchParams.delete('cari');u.searchParams.set('kembali_stok',k.pathname+k.search);}}
      a.href=u.pathname+u.search+u.hash;
    });
  }
  form.addEventListener('submit',function(e){e.preventDefault();cari(true);});
  input.addEventListener('keydown',function(e){if(e.key==='Escape'){input.value='';cari(true);}});
  input.addEventListener('search',function(){if(!input.value)cari(true);});
  root.querySelector('.sk-form-filter').addEventListener('submit',function(){root.querySelector('.sk-form-filter [name=cari]').value=input.value;});
  cari(false);
  var filter=root.querySelector('.sk-form-filter'),owner=filter.querySelector('[name=pemilik]'),label=filter.querySelector('[data-stok-pelanggan]'),select=label.querySelector('select'),status=filter.querySelector('[data-stok-pelanggan-status]'),load=null;
  async function pelanggan(){
    var jasa=owner.value==='jasa';label.hidden=!jasa;select.disabled=!jasa;status.hidden=true;
    if(load)load.abort();if(!jasa)return;
    load=new AbortController();var current=load;select.disabled=true;status.hidden=false;status.textContent='Memuat pelanggan…';
    try{var url=new URL(root.dataset.pelangganUrl,location.href);url.searchParams.set('gudang',filter.querySelector('[name=gudang]').value);
      var response=await fetch(url.pathname+url.search,{credentials:'same-origin',cache:'no-store',signal:current.signal});
      if(!response.ok||response.redirected)throw new Error('gagal');var doc=new DOMParser().parseFromString(await response.text(),'text/html'),source=doc.querySelector('.sk-form-filter [name=pelanggan_id]');if(!source)throw new Error('gagal');if(load!==current)return;
      var value=select.value;select.replaceChildren.apply(select,Array.from(source.options).map(function(o){return o.cloneNode(true);}));select.value=value;if(select.selectedIndex<0)select.value='';select.disabled=false;status.hidden=true;
    }catch(e){if(load!==current||e.name==='AbortError')return;select.value='';select.disabled=true;status.textContent='Pelanggan belum dapat dimuat. Terapkan filter untuk melihat titipan jasa.';}
  }
  owner.addEventListener('change',pelanggan);
  filter.querySelector('[name=gudang]').addEventListener('change',function(){if(owner.value==='jasa')pelanggan();});
}

})();
