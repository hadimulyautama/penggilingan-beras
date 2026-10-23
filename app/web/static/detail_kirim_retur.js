/* Panel memakai data yang telah diotorisasi server; transaksi tetap formulir lama. */
(function () {
  'use strict';
  var root=document.querySelector('[data-detail-tab]'); if(!root)return;
  var tabs=Array.from(root.querySelectorAll('[role=tab]'));
  function tampil(id){tabs.forEach(function(t){var a=t.getAttribute('aria-controls')===id;t.setAttribute('aria-selected',String(a));root.querySelector('#'+t.getAttribute('aria-controls')).hidden=!a;});}
  function fragmen(){var id;try{id=decodeURIComponent(location.hash.slice(1));}catch(_){return;}
    var peta={'judul-isi-muatan':'panel-barang','judul-timbang-pengiriman':'panel-tiket','judul-jejak-pengiriman':'panel-riwayat','tiket-retur':'panel-barang','alasan-batal':'panel-ringkasan'};
    if(!id)return;var target=document.getElementById(peta[id]||id);if(!target||!root.contains(target))return;var p=target.closest('[role=tabpanel]');if(p)tampil(p.id);
    for(var e=target;e&&e!==root;e=e.parentElement)if(e.tagName==='DETAILS')e.open=true;
  }
  root.addEventListener('click',function(e){var a=e.target.closest('a');if(!a||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||a.target)return;
    var u=new URL(a.href),n=new URL(location.href),tab=u.searchParams.get('tab_detail');
    if(u.origin!==n.origin||u.pathname!==n.pathname||u.searchParams.has('buka')||!tabs.some(function(t){return t.getAttribute('aria-controls')==='panel-'+tab;}))return;
    e.preventDefault();e.stopPropagation();tampil('panel-'+tab);history.replaceState(history.state,'',u.pathname+u.search+u.hash);fragmen();
  });
  root.querySelector('[role=tablist]').addEventListener('keydown',function(e){var i=tabs.indexOf(e.target);if(i<0||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();i=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[i].focus();tabs[i].click();});
  // Validasi browser juga harus dapat memfokuskan isian wajib di tab lain.
  root.addEventListener('invalid',function(e){var p=e.target.closest('[role=tabpanel]');if(p)tampil(p.id);},true);
  // Penjaga pengiriman ulang lokal melengkapi lock/idempotensi server lama.
  root.querySelectorAll('form').forEach(function(f){f.addEventListener('submit',function(e){if(f.dataset.mengirim){e.preventDefault();return;}f.dataset.mengirim='1';f.querySelectorAll('button[type=submit]').forEach(function(b){b.disabled=true;});});});
  if(window.PINDAH)PINDAH.pasang(window,'hashchange',fragmen);else window.addEventListener('hashchange',fragmen);
  fragmen();
})();
