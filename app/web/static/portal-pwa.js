/* Pemasangan tidak mengubah sesi: server tetap memeriksa akun pelanggan. */
(() => {
  const warna = document.querySelector('meta[name=theme-color]');
  const selaraskanTema = () => warna?.setAttribute('content', document.body.classList.contains('terik') ? '#f5f5ef' : '#111914');
  new MutationObserver(selaraskanTema).observe(document.body, {attributes: true, attributeFilter: ['class']});
  selaraskanTema();
  const area = document.querySelector('[data-pasang-area]');
  const button = document.querySelector('[data-pasang-app]');
  const petunjuk = document.querySelector('[data-pasang-petunjuk]');
  const mandiri = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  let tawaran = null;
  if (area) area.hidden = mandiri();

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    tawaran = event;
    if (area) area.hidden = mandiri();
  });
  window.addEventListener('appinstalled', () => {
    tawaran = null;
    if (area) area.hidden = true;
  });
  button?.addEventListener('click', async () => {
    if (tawaran) {
      const prompt = tawaran;
      tawaran = null;
      button.disabled = true;
      try {
        await prompt.prompt();
        const pilihan = await prompt.userChoice;
        if (pilihan.outcome === 'accepted' && area) area.hidden = true;
      } finally { button.disabled = false; }
      return;
    }
    if (!petunjuk) return;
    const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    petunjuk.textContent = ios
      ? 'Buka di Safari, ketuk Bagikan, lalu Tambahkan ke Layar Utama. Nama aplikasi: PadiFlow Pelanggan.'
      : 'Buka menu peramban, pilih Pasang aplikasi atau Tambahkan ke layar utama. Di Safari Mac, pilih File → Tambahkan ke Dock.';
    petunjuk.hidden = false;
  });

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/pelanggan/sw.js', {
      scope: '/pelanggan/', updateViaCache: 'none'
    }).catch(() => { /* Portal tetap dapat dibaca bila pemasangan dibatasi peramban. */ });
  }
})();
