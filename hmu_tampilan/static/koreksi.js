/* Isian koreksi tetap berada di tab saat jaringan atau server menolak simpan. */
(function () {
  if (window.KOREKSI_RIWAYAT) return;
  window.KOREKSI_RIWAYAT = true;
  document.addEventListener('submit', async function (e) {
    var form = e.target;
    if (!form.matches('.riwayat-koreksi__form')) return;
    e.preventDefault();
    if (form.dataset.menyimpan || (window.SESIFORM && !SESIFORM.periksa())) return;
    form.dataset.menyimpan = '1';
    var tombol = form.querySelector('[type="submit"]');
    var pesan = form.querySelector('[data-gagal-koreksi]');
    if (!pesan) { pesan = document.createElement('p'); pesan.dataset.gagalKoreksi='1'; pesan.setAttribute('role','alert'); form.prepend(pesan); }
    tombol.disabled = true;
    try {
      var r = await fetch(form.action, {method:'POST',credentials:'same-origin',body:new FormData(form)});
      if (window.SESIFORM && !SESIFORM.periksa()) throw new Error('Sesi berubah ketika permintaan diproses. Periksa riwayat akun pembuka sebelum mengulang; permintaan yang sudah diterima mungkin selesai.');
      if (r.status === 422) {
        var d = new DOMParser().parseFromString(await r.text(),'text/html');
        var baru = d.querySelector('.riwayat-detail');
        if (!baru) throw new Error('Jawaban server tidak lengkap. Isian masih tersedia; periksa riwayat sebelum mencoba lagi.');
        form.closest('.riwayat-detail').replaceWith(baru);
        var pertama = baru.querySelector('input[type="number"], textarea');
        if (pertama) pertama.focus();
      } else if (!r.ok) {
        throw new Error('Koreksi belum dapat disimpan. Isian dipertahankan. Periksa sesi dan riwayat sebelum mencoba lagi.');
      } else if (r.url.indexOf('/masuk') >= 0) {
        throw new Error('Sesi berakhir. Salin isian yang diperlukan, masuk kembali, lalu buka koreksi baru.');
      } else {
        window.location.assign(r.url);
      }
    } catch (err) {
      pesan.textContent = err && err.name === 'TypeError' ? 'Jaringan terganggu. Penyimpanan belum dapat dipastikan. Angka dan alasan tetap tersedia; periksa riwayat sebelum mengirim ulang.' : (err.message || 'Penyimpanan belum dapat dipastikan. Isian dipertahankan; periksa riwayat sebelum mengirim ulang.');
      pesan.tabIndex = -1; pesan.focus();
    } finally {
      delete form.dataset.menyimpan; tombol.disabled = false;
    }
  });
})();
