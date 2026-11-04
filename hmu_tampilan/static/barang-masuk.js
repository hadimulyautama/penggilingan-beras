/* Pendengar terikat kepala halaman yang ikut diganti oleh PINDAH. */
(function () {
  var root = document.querySelector('.bm-kepala');
  if (!root || root.dataset.bmTerpasang) return;
  root.dataset.bmTerpasang = "1";
  var asal;
  root.querySelectorAll('[data-bm-buka]').forEach(function (tombol) {
    tombol.addEventListener('click', function () {
      var tujuan = root.querySelector('#' + tombol.dataset.bmBuka);
      root.querySelectorAll('dialog[open]').forEach(function (d) { d.close(); });
      if (!tombol.closest('dialog')) asal = tombol;
      tujuan.showModal();
    });
  });
  root.querySelectorAll('dialog').forEach(function (d) {
    d.querySelector('[data-bm-tutup]').addEventListener('click', function () { d.close(); });
    d.addEventListener('click', function (e) {
      var r = d.getBoundingClientRect();
      if (e.target === d && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) d.close();
    });
    d.addEventListener('close', function () { if (asal && !root.querySelector('dialog[open]')) asal.focus(); });
  });
  root.querySelectorAll('[data-bm-cetak]').forEach(function (b) {
    b.addEventListener('click', function () {
      root.querySelectorAll('dialog[open]').forEach(function (d) { d.close(); });
      window.print();
    });
  });
})();
