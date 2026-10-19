/* Delegasi tetap bekerja ketika PINDAH mengganti isi halaman tanpa muat ulang. */
(function () {
  'use strict';
  if (window.daftarKeluarTerpasang) return;
  window.daftarKeluarTerpasang = true;
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    var baris = e.target.closest('[data-detail-keluar]');
    if (!baris || e.target.closest('a,button,input,select,textarea,summary') || window.getSelection().toString()) return;
    window.location.href = baris.dataset.detailKeluar;
  });
})();
