/* Pendengar terikat kepala halaman yang ikut diganti oleh PINDAH. */
(function () {
  function pasang(root) {
  if (!root || root.dataset.pkTerpasang) return;
  root.dataset.pkTerpasang = "1";
  var asal;
  root.querySelectorAll('[data-pk-buka]').forEach(function (tombol) {
    tombol.addEventListener('click', function () {
      var tujuan = root.querySelector('#' + tombol.dataset.pkBuka);
      root.querySelectorAll('dialog[open]').forEach(function (d) { d.close(); });
      if (!tombol.closest('dialog')) asal = tombol;
      tujuan.showModal();
    });
  });
  root.querySelectorAll('dialog').forEach(function (d) {
    d.querySelector('[data-pk-tutup]').addEventListener('click', function () { d.close(); });
    d.addEventListener('click', function (e) {
      var r = d.getBoundingClientRect();
      if (e.target === d && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) d.close();
    });
    d.addEventListener('close', function () { if (asal && !root.querySelector('dialog[open]')) asal.focus(); });
  });
  root.querySelectorAll('[data-pk-cetak]').forEach(function (b) {
    b.addEventListener('click', function () {
      root.querySelectorAll('dialog[open]').forEach(function (d) { d.close(); });
      window.print();
    });
  });
  var filter = root.querySelector('.pk-form-filter');
  if (filter) filter.addEventListener('submit', function () {
    var input = filter.querySelector('[name=cari]');
    if (!input) { input = document.createElement('input'); input.type='hidden'; input.name='cari'; filter.appendChild(input); }
    input.value = root.querySelector('[name=cari][type=search]').value;
  });
  }
  
  pasang(document.querySelector('.pk-kepala'));
})();
