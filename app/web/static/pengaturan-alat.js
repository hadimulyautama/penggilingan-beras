/* Hanya empat formulir tambah/edit dryer/silo. Tidak mengirim ulang POST otomatis. */
(function () {
  const root = document.querySelector('[data-pengaturan-form]');
  if (!root) return;
  root.querySelectorAll('form[data-simpan-alat]').forEach(form => {
    let busy = false, checking = false, panel, original = [];
    const operation = form.elements.namedItem('_operasi_alat');
    if (!operation || !operation.value) return;
    // Navigasi instan dapat memasang ulang HTML GET dari cache. Setiap
    // pembukaan formulir adalah niat baru; retry pada formulir ini tetap
    // memakai token yang sama sampai hasilnya dipastikan.
    if (window.crypto?.randomUUID) operation.value = crypto.randomUUID();
    function message(text, state) {
      if (!panel) {
        panel = document.createElement('div');
        panel.className = 'nota'; panel.setAttribute('role', 'alert');
        form.prepend(panel);
      }
      panel.replaceChildren();
      const p = document.createElement('p'); p.textContent = text; panel.append(p);
      form.dataset.pengaturanSimpanState = state;
    }
    function lock() {
      original = Array.from(form.elements).map(el => [el, el.disabled]);
      original.forEach(([el]) => { el.disabled = true; });
      busy = true;
    }
    function unlock() {
      original.forEach(([el, disabled]) => { el.disabled = disabled; });
      busy = false;
    }
    function button(text, action) {
      const b = document.createElement('button'); b.type = 'button';
      b.className = 'btn'; b.textContent = text; b.onclick = action; panel.append(b);
    }
    function result(url) {
      const u = new URL(url, location.origin);
      if (u.origin !== location.origin || !u.pathname.startsWith('/pengaturan/')) {
        throw new Error('Tujuan hasil tidak valid');
      }
      window.pfPengaturanGuard?.abort();
      location.assign(u.href);
    }
    async function request(url, options) {
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(), 15000);
      try {
        const response = await fetch(url, {...options, credentials: 'same-origin',
          cache: 'no-store', redirect: 'error', signal: abort.signal});
        const data = await response.json();
        return {response, data};
      } finally { clearTimeout(timer); }
    }
    async function check() {
      if (checking) return;
      checking = true;
      message('Memeriksa hasil penyimpanan. Isian tetap terjaga…', 'memeriksa');
      try {
        const {response, data} = await request('/pengaturan/alat/status-simpan/' + encodeURIComponent(operation.value));
        if (!response.ok) throw new Error();
        if (data.status === 'tersimpan') {
          message(data.pesan, 'tersimpan');
          button('Buka hasil tersimpan', () => result(data.url));
        } else if (data.status === 'belum_tersimpan') {
          message(data.pesan, 'belum_tersimpan'); unlock();
        } else {
          message(data.pesan || 'Status belum pasti. Jangan kirim ulang.', data.status || 'belum_pasti');
          button('Periksa status simpan', check);
        }
      } catch (_) {
        message('Status belum dapat dibaca. Isian tetap terjaga. Jangan kirim ulang sebelum status diperiksa.', 'belum_pasti');
        button('Periksa status simpan', check);
      } finally { checking = false; }
    }
    form.addEventListener('submit', async event => {
      event.preventDefault(); event.stopImmediatePropagation();
      if (busy) return;
      // Snapshot diambil sebelum input dinonaktifkan; termasuk token dan CSRF.
      const body = new FormData(form);
      root.querySelectorAll('.pesan--ok').forEach(el => el.remove());
      lock(); message('Menyimpan. Jangan tutup halaman sebelum hasil diperiksa.', 'menyimpan');
      try {
        const {response, data} = await request(form.action, {
          method: 'POST', headers: {'X-Pengaturan-Alat': '1'}, body
        });
        if (response.ok && data.status === 'tersimpan') {
          result(data.url);
        } else if (data.status === 'ditolak') {
          message(data.pesan, 'ditolak'); unlock();
        } else if (data.status === 'konflik') {
          message(data.pesan, 'konflik'); button('Periksa status simpan', check);
        } else if (response.status === 403 || response.status === 422) {
          message(typeof data.detail === 'string' ? data.detail : 'Penyimpanan ditolak. Periksa sesi dan izin Anda.', 'ditolak'); unlock();
        } else {
          await check();
        }
      } catch (_) {
        await check();
      }
    }, {capture: true});
  });
})();
