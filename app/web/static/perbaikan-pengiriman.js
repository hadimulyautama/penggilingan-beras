(function () {
  'use strict';
  var f = document.querySelector('[data-perbaikan-pengiriman]');
  if (!f || f.dataset.siap) return;
  f.dataset.siap = '1';
  var sibuk = false, terkunci = false;
  f.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (sibuk || terkunci || !f.reportValidity()) return;
    var alasan = f.elements.alasan.value.trim(), pesan = f.querySelector('[data-pesan]');
    if (!alasan) { pesan.textContent = 'Alasan tidak boleh hanya spasi.'; return; }
    if (window.SESIFORM && !window.SESIFORM.periksa()) { pesan.textContent = 'Sesi berubah. Alasan tetap tersedia; masuk kembali dan periksa status terbaru.'; return; }
    sibuk = true;
    var tombol = f.querySelector('button'), tag = document.getElementById('formulir-sesi');
    tombol.disabled = true;
    var ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 20000);
    try {
      var r = await fetch(f.dataset.url, {method:'POST', credentials:'same-origin', signal:ctrl.signal,
        headers:{'Content-Type':'application/json','X-CSRF-Token':tag ? tag.dataset.token : ''},
        body:JSON.stringify({log_id:Number(f.dataset.log),alasan:alasan,konfirmasi:f.elements.konfirmasi.checked})});
      if (r.status >= 500) throw Error('Status penyimpanan belum dapat dipastikan. Periksa status dan audit sebelum mengulang.');
      var j = await r.json();
      if (!r.ok) {
        pesan.textContent = (typeof j.detail === 'string' ? j.detail : 'Pemeriksaan ditolak.') + ' Isian tetap tersedia. Baca ulang status dan dampak sebelum konfirmasi baru.';
        terkunci = true; return;
      }
      terkunci = true;
      pesan.textContent = j.pesan + ' Baca ulang status untuk melanjutkan perbaikan.';
    } catch (err) {
      terkunci = true;
      pesan.textContent = 'Status penyimpanan belum dapat dipastikan. Isian tetap tersedia. Periksa status pengiriman atau audit sebelum mengulang.';
    } finally {
      clearTimeout(timer); sibuk = false; tombol.disabled = terkunci;
    }
  });
})();
