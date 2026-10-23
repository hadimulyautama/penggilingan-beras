/* Hash lama tetap membuka rincian yang tepat, termasuk sesudah navigasi instan. */
(function () {
  'use strict';
  var root = document.querySelector('.pendinginan-detail');
  if (!root) return;
  var tabs = Array.from(root.querySelectorAll('[role=tab]'));
  function tampil(id) {
    tabs.forEach(function (tab) {
      var aktif = tab.getAttribute('aria-controls') === id;
      tab.setAttribute('aria-selected', String(aktif));
      root.querySelector('#' + tab.getAttribute('aria-controls')).hidden = !aktif;
    });
  }
  function dariHash() {
    var id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    var target = document.getElementById(id);
    if (!target || !root.contains(target)) return;
    var panel = target.closest('[role=tabpanel]');
    if (!panel) return;
    tampil(panel.id);
    for (var el = target.parentElement; el && el !== root; el = el.parentElement) {
      if (el.tagName === 'DETAILS') el.open = true;
    }
    target.scrollIntoView({block: 'start'});
  }
  root.querySelector('.pengeringan-tabs').addEventListener('keydown', function (e) {
    var i = tabs.indexOf(e.target);
    if (i < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    i = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[i].focus(); tabs[i].click();
  });
  // Tautan tab tetap navigasi GET biasa: query, pagination dan konteks aksi
  // dipertahankan oleh server. Skrip ini hanya menjembatani fragmen URL lama.
  if (window.PINDAH) PINDAH.pasang(window, 'hashchange', dariHash);
  else window.addEventListener('hashchange', dariHash);
  dariHash();
})();
