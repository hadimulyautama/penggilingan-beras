/* Panduan hanya mengganti penjelasan; tindakan tetap melalui jalur aplikasi. */
(function () {
  'use strict';
  var root = document.querySelector('[data-bantuan-kirim]');
  if (!root || root.dataset.siap) return;
  root.dataset.siap = '1';
  var tabs = Array.from(root.querySelectorAll('[role="tab"]'));
  function pilih(tab) {
    tabs.forEach(function (t) {
      var aktif = t === tab;
      t.setAttribute('aria-selected', String(aktif));
      t.tabIndex = aktif ? 0 : -1;
      root.querySelector('#' + t.getAttribute('aria-controls')).hidden = !aktif;
    });
  }
  root.addEventListener('click', function (e) {
    var tab = e.target.closest('[role="tab"]');
    if (tabs.includes(tab)) pilih(tab);
  });
  root.addEventListener('keydown', function (e) {
    var i = tabs.indexOf(e.target);
    if (i < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    i = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    pilih(tabs[i]); tabs[i].focus();
  });
})();
