/* Pilihan yang belum dipratinjau tidak boleh terlihat siap diterapkan. */
(function () {
  'use strict';
  var pilihan = document.querySelector('[data-pilihan-penetapan]');
  var terapkan = document.querySelector('[data-terapkan-penetapan]');
  if (!pilihan || !terapkan || terapkan.dataset.siap) return;
  terapkan.dataset.siap = '1';
  var tombol = terapkan.querySelector('button[type="submit"]');
  var pesan = document.querySelector('[data-pilihan-berubah]');
  var lokasi = terapkan.dataset.rencanaLokasi;
  var gudang = JSON.parse(terapkan.dataset.rencanaGudang).map(String).sort();
  function periksa() {
    var ids = Array.from(pilihan.querySelectorAll('input[name="warehouse_id"]:checked'))
      .map(function (el) { return el.value; }).sort();
    var sama = pilihan.elements.lokasi_pabrik_id.value === lokasi && JSON.stringify(ids) === JSON.stringify(gudang);
    tombol.disabled = !sama;
    pesan.hidden = sama;
  }
  pilihan.addEventListener('change', periksa);
  pilihan.addEventListener('input', periksa);
  periksa();
})();
