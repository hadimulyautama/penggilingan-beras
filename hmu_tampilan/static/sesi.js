/* Formulir tetap milik sesi pembukanya, termasuk saat tab dipulihkan dari Back. */
(function () {
  if (window.SESIFORM) { window.SESIFORM.halamanBaru(); return; }
  function nonce() {
    var bagian = ('; ' + document.cookie).split('; produksi_csrf=');
    return bagian.length === 2 ? bagian.pop().split(';').shift() : '';
  }
  var berubah = false;
  function periksa() {
    var konteks = document.getElementById('formulir-sesi');
    var cocok = !konteks || (!berubah && konteks.dataset.nonce === nonce());
    if (!cocok && !document.getElementById('sesi-berubah')) {
      var pesan = document.createElement('div');
      pesan.id = 'sesi-berubah'; pesan.setAttribute('role', 'alert');
      pesan.style.cssText = 'position:fixed;z-index:99999;left:12px;right:12px;top:12px;padding:16px;background:#fff0c2;color:#312300;border:2px solid #956400;border-radius:12px;font-size:16px;';
      pesan.textContent = 'Sesi berubah di tab lain atau telah berakhir. Jangan simpan dari formulir lama. Salin isian yang diperlukan, masuk dengan akun yang benar, lalu buka formulir baru. Isian di tab ini tetap tersedia. Permintaan yang sudah dikirim mungkin selesai atas nama pembukanya; periksa riwayat sebelum mengulang.';
      document.body.appendChild(pesan);
    }
    if (cocok) { var lama = document.getElementById("sesi-berubah"); if (lama) lama.remove(); }
    return cocok;
  }
  async function cekServer() {
    var konteks = document.getElementById('formulir-sesi');
    if (!konteks || konteks.dataset.aktif !== '1') return;
    var token = konteks.dataset.token;
    try {
      var r = await fetch('/api/sesi-formulir', {credentials:'same-origin', cache:'no-store'});
      if (!r.ok) return;
      var data = await r.json();
      if (!data || typeof data.aktif !== 'boolean' || typeof data.token !== 'string') return;
      if (document.getElementById('formulir-sesi') !== konteks) return;
      berubah = !data.aktif || data.token !== token;
      periksa();
    } catch (_) { /* Jaringan gagal bukan bukti pergantian akun; server tetap menjaga simpan. */ }
  }
  window.SESIFORM = { periksa: periksa, halamanBaru: function () { berubah = false; periksa(); cekServer(); } };
  document.addEventListener('submit', function (e) {
    if (!periksa()) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  window.addEventListener('focus', function () { periksa(); cekServer(); });
  window.addEventListener('pageshow', function () { periksa(); cekServer(); });
  document.addEventListener('visibilitychange', function () { periksa(); if (!document.hidden) cekServer(); });
  window.addEventListener('storage', periksa);
  setInterval(periksa, 2000);
  setInterval(cekServer, 15000);
  cekServer();
  periksa();
})();
