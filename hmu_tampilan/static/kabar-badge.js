/* Satu pewaktu per bingkai; berhenti ketika navigasi mengganti bingkai. */
(function () {
  var bingkai = document.querySelector('.bingkai');
  if (!bingkai || !bingkai.querySelector('a[href="/kabar"]')) return;
  var patokan = bingkai.querySelector('.bar__kabar,.desktop-chrome__notice');
  if (!patokan) return;
  var awal = Number((patokan.getAttribute('aria-label') || '').match(/(\d+) belum/)?.[1] || 0);
  async function periksa() {
    if (!patokan.isConnected) return;
    if (!document.hidden) {
      try {
        var r = await fetch('/api/kabar/jumlah', {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (!r.ok || r.redirected) throw new Error('Jumlah tidak tersedia');
        var data = await r.json(), n = data.belum;
        if (!Number.isInteger(n) || n < 0) throw new Error('Jumlah tidak valid');
        if (!patokan.isConnected) return;
        bingkai.querySelectorAll('.bar__kabar,.desktop-chrome__notice').forEach(function (a) {
          a.setAttribute('aria-label', 'Kabar, ' + n + ' belum dibaca');
          var badge = a.querySelector('span');
          if (!n) { if (badge) badge.remove(); return; }
          if (!badge) { badge = document.createElement('span'); if (a.classList.contains('bar__kabar')) badge.className = 'bar__kabar-jml'; a.appendChild(badge); }
          badge.textContent = n < 100 ? n : '99+';
          if (a.classList.contains('bar__kabar')) badge.classList.toggle('bar__kabar-jml--merah', !!data.merah);
        });
        var kb = bingkai.querySelector('.kb');
        if (kb) {
          kb.querySelector('[data-kabar-semua]').disabled = !n;
          kb.querySelector('[data-kabar-belum]').textContent = 'Belum dibaca (' + n + ')';
          kb.querySelector('[data-kabar-total]').textContent = n + ' kabar belum dibaca dalam cakupan Anda';
        }
        if (kb && (awal !== n || data.terakhir > Number(kb.dataset.sampai)) && !kb.querySelector('[data-kabar-segar]')) {
          var segar = document.createElement('a'); segar.href = '/kabar' + location.search.replace(/([?&])(sampai|batas)=[^&]*/g, '$1').replace(/[?&]+$/, '');
          segar.dataset.kabarSegar = ''; segar.className = 'kb-more'; segar.textContent = 'Kabar berubah — muat daftar terbaru'; kb.prepend(segar);
        }
        awal = n;
      } catch (_) {
        // Pertahankan hitungan server terakhir; kegagalan tidak digambar nol.
      }
    }
    if (patokan.isConnected) setTimeout(periksa, 20000);
  }
  periksa();
})();
