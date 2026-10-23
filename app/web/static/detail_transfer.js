/* Hash lama tetap membuka rincian yang tepat, termasuk sesudah navigasi instan. */
(function () {
  'use strict';
  var root = document.querySelector('.transfer-detail');
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
    if (!id && new URL(location.href).searchParams.get('buka_koreksi') === '1') id = 'koreksi-transfer';
    var peta = {'ringkasan-proses':'panel-ringkasan','tindakan-proses':'tindakan-proses','bahan-proses':'panel-bahan','permintaan':'panel-permintaan','riwayat-proses':'panel-riwayat','catatan-hasil':'koreksi-transfer'};
    var target = document.getElementById(peta[id] || id);
    if (!target || !root.contains(target)) return;
    var panel = target.closest('[role=tabpanel]');
    if (!panel) return;
    tampil(panel.id);
    if (target.id === 'koreksi-transfer') { var formulir = target.querySelector('details'); if (formulir) formulir.open = true; }
    for (var el = target.parentElement; el && el !== root; el = el.parentElement) {
      if (el.tagName === 'DETAILS') el.open = true;
    }
    target.scrollIntoView({block: 'start'});
  }
  // Seluruh panel sudah diotorisasi dan dirender server. Pergantian lokal
  // menjaga isian/bobot dasar koreksi tetap utuh, termasuk setelah POST gagal.
  root.addEventListener('click', function (e) {
    var a = e.target.closest('a');
    if (!a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || a.target) return;
    var u = new URL(a.href), sekarang = new URL(location.href), dasar = new URL(tabs[0].href);
    var tab = u.searchParams.get('tab_detail');
    if (u.origin !== sekarang.origin || u.pathname !== dasar.pathname || u.searchParams.has('buka') ||
        u.searchParams.get('halaman_transfer') !== sekarang.searchParams.get('halaman_transfer') ||
        !tabs.some(function (t) { return t.getAttribute('aria-controls') === 'panel-' + tab; })) return;
    e.preventDefault(); e.stopPropagation();
    tampil('panel-' + tab);
    history.replaceState(history.state, '', u.pathname + u.search + u.hash);
    dariHash();
  });
  root.querySelector('.transfer-tabs').addEventListener('keydown', function (e) {
    var i = tabs.indexOf(e.target);
    if (i < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    i = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[i].focus(); tabs[i].click();
  });
  // Tanpa JavaScript, tautan tab tetap GET biasa. Pagination dan tindakan
  // selalu membaca server; fragmen lama dibuka ke panel yang sesuai.
  if (window.PINDAH) PINDAH.pasang(window, 'hashchange', dariHash);
  else window.addEventListener('hashchange', dariHash);
  dariHash();
})();
