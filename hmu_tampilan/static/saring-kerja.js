/* Kontrol milik halaman; tidak memasang listener document tiap perpindahan. */
(function () {
  var root=document.querySelector('[data-saring-kerja]'); if(!root)return;
  var input=root.querySelector('[name=cari]'),nama=root.querySelector('[name=pemasok]');
  function saring(tulis) {
    document.querySelectorAll('[data-blok]').forEach(function(b){b.hidden=false;});
    var q=input.value.trim().toLowerCase(),n=nama.value,jumlah=0;
    document.querySelectorAll('[data-cari]').forEach(function(k){
      var cocok=(!q||k.dataset.cari.includes(q))&&(!n||k.dataset.sup===n);
      k.hidden=!cocok;if(cocok&&k.getClientRects().length)jumlah++;
    });
    document.querySelectorAll('[data-blok]').forEach(function(b){
      var isi=Array.from(b.querySelectorAll('[data-cari]')).filter(function(k){return !k.hidden&&k.getClientRects().length;});
      var cap=b.querySelector('[data-jumlah]');if(cap)cap.textContent=isi.length;b.hidden=!isi.length;
    });
    root.querySelector('[data-hasil-cari]').textContent=q||n?jumlah+' cocok pada halaman ini':'';
    function konteks(u) {
      [['cari',input.value],['pemasok',n]].forEach(function(p){
        if(p[1])u.searchParams.set(p[0],p[1]);else u.searchParams.delete(p[0]);
      });
      return u;
    }
    if(tulis){
      history.replaceState(history.state,'',konteks(new URL(location.href)));
      var daftar=['/pekerjaan','/barang-masuk','/aksi','/berjalan','/mutu','/keputusan'];
      document.querySelectorAll('.isi a[href]').forEach(function(a){
        var u=new URL(a.href,location.href);
        if(u.origin!==location.origin)return;
        if(daftar.includes(u.pathname))konteks(u);
        var kembali=u.searchParams.get('kembali_kerja');
        if(kembali){
          var asal=new URL(kembali,location.href);
          if(asal.origin===location.origin&&daftar.includes(asal.pathname)){
            konteks(asal);u.searchParams.set('kembali_kerja',asal.pathname+asal.search);
          }
        }
        a.href=u.pathname+u.search+u.hash;
      });
      document.querySelectorAll('.kerja-kepala form').forEach(function(f){
        [['cari',input.value],['pemasok',n]].forEach(function(p){
          var el=f.querySelector('[name="'+p[0]+'"]');
          if(!el){el=document.createElement('input');el.type='hidden';el.name=p[0];f.appendChild(el);}
          el.value=p[1];
        });
      });
    }
  }
  input.addEventListener('input',function(){saring(true);});nama.addEventListener('change',function(){saring(true);});
  input.addEventListener('keydown',function(e){if(e.key==='Escape'){input.value='';saring(true);}});saring(false);
})();
