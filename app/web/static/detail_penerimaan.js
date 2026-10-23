/* Memilih panel tidak merender ulang dialog/isian atau menjalankan transaksi. */
(function () {
  'use strict';
  var root = document.querySelector('[data-penerimaan-tab]');
  if (!root || root.dataset.siap) return;
  root.dataset.siap = '1';
  var tabs = Array.from(root.querySelectorAll('[role=tab]'));
  function pilih(id) {
    tabs.forEach(function (t) {
      var aktif = t.getAttribute('aria-controls') === id;
      t.setAttribute('aria-selected', String(aktif)); t.tabIndex = aktif ? 0 : -1;
      root.querySelector('#' + t.getAttribute('aria-controls')).hidden = !aktif;
    });
  }
  function fragmen() {
    var id; try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    if (!id) return;
    var target = document.getElementById(id);
    if (!target || !root.contains(target)) return;
    var panel = target.closest('[role=tabpanel]'); if (panel) pilih(panel.id);
    for (var e=target; e && e!==root; e=e.parentElement) if(e.tagName==='DETAILS') e.open=true;
  }
  root.addEventListener('click', function(e) {
    var a=e.target.closest('a');
    if (!a || e.defaultPrevented || e.button!==0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || a.target) return;
    var u=new URL(a.href), n=new URL(location.href), tab=u.searchParams.get('tab_detail');
    if (u.origin!==n.origin || u.pathname!==n.pathname || !tabs.some(function(t){return t.getAttribute('aria-controls')==='terima-panel-'+tab;})) return;
    e.preventDefault(); e.stopPropagation(); pilih('terima-panel-'+tab);
    history.replaceState(history.state,'',u.pathname+u.search+u.hash); fragmen();
  });
  root.querySelector('[role=tablist]').addEventListener('keydown',function(e){
    var i=tabs.indexOf(e.target); if(i<0 || !['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
    e.preventDefault(); i=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
    tabs[i].focus(); tabs[i].click();
  });
  root.addEventListener('invalid',function(e){var p=e.target.closest('[role=tabpanel]');if(p)pilih(p.id);},true);
  if(window.PINDAH)PINDAH.pasang(window,'hashchange',fragmen);else window.addEventListener('hashchange',fragmen);
  fragmen();
})();
