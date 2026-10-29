/* Berkas disiapkan sebelum ketukan share, agar aktivasi Safari tetap sah.
   Hanya GET endpoint yang sama dengan Unduh PDF; tidak menyimpan berkas
   dalam cache aplikasi atau mengirimkannya tanpa pilihan pengguna. */
(function () {
  'use strict';
  var button = document.querySelector('[data-penerimaan-share]');
  if (!button || button.dataset.shareSiap) return;
  button.dataset.shareSiap = '1';
  var status = document.getElementById('status-bagikan');
  var file = null, loading = false, sharing = false;
  var url = new URL(button.dataset.penerimaanShare, location.href);
  function pesan(teks) { if (status) status.textContent = teks; }
  function dukung() {
    try {
      return typeof navigator.share === 'function' && typeof navigator.canShare === 'function' &&
        navigator.canShare({ files: [new File(['%PDF-'], 'laporan.pdf', {type:'application/pdf'})] });
    } catch (_) { return false; }
  }
  async function siapkan() {
    if (loading || sharing) return;
    loading = true; button.disabled = true;
    pesan('Menyiapkan PDF untuk dibagikan…');
    try {
      if (url.origin !== location.origin) throw Error('Asal PDF tidak sah.');
      var response = await fetch(url.href, {credentials:'same-origin',cache:'no-store'});
      if (!response.ok || response.redirected ||
          (response.headers.get('content-type') || '').split(';')[0].trim() !== 'application/pdf') {
        throw Error('PDF tidak tersedia.');
      }
      var blob = await response.blob();
      if (!blob.size) throw Error('PDF kosong.');
      var name = (response.headers.get('content-disposition') || '').match(/filename="([^"/\\]+\.pdf)"/);
      file = new File([blob], name ? name[1] : 'laporan-penerimaan.pdf', {type:'application/pdf'});
      pesan('PDF siap. Ketuk Bagikan PDF untuk memilih aplikasi atau Simpan ke File.');
    } catch (_) {
      file = null;
      pesan('PDF belum berhasil dimuat. Ketuk Bagikan PDF untuk mencoba lagi, atau gunakan Unduh PDF / Lihat PDF.');
    } finally { loading = false; button.disabled = false; }
  }
  button.addEventListener('click', async function () {
    if (loading || sharing) return;
    if (!dukung()) {
      pesan('Perangkat ini belum mendukung berbagi berkas dari halaman. Gunakan Lihat PDF, lalu Bagikan atau Simpan ke File pada pembaca PDF.');
      return;
    }
    if (!file) { await siapkan(); return; }
    sharing = true; button.disabled = true;
    pesan('Pilih aplikasi atau Simpan ke File pada menu berbagi perangkat.');
    try {
      // Tidak ada fetch/await sebelum share: panggil dalam ketukan ini.
      await navigator.share({files:[file],title:'Laporan Penerimaan Barang'});
      pesan('Berkas PDF diteruskan ke pilihan berbagi perangkat.');
    } catch (error) {
      pesan(error.name === 'AbortError' ? 'Berbagi dibatalkan. PDF tetap dapat dibagikan atau diunduh.' :
        'PDF belum berhasil dibagikan. Ketuk lagi, atau gunakan Lihat PDF lalu Bagikan / Simpan ke File.');
    } finally { sharing = false; button.disabled = false; }
  });
  if (dukung()) siapkan();
  else {
    button.disabled = false;
    pesan('Gunakan Unduh PDF atau Lihat PDF. Berbagi berkas langsung tersedia pada perangkat yang mendukung.');
  }
})();
