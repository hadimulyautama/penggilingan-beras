/* Khusus formulir konfigurasi. Navigasi instan juga harus menghormati isian
   yang belum disimpan; listener lama dicabut ketika halaman berganti. */
(function () {
  window.pfPengaturanGuard?.abort();
  const root = document.querySelector('[data-pengaturan-form]');
  if (!root) return;
  const controller = new AbortController();
  window.pfPengaturanGuard = controller;
  const options = {signal: controller.signal};
  let changed = false, submitting = false;
  root.addEventListener('input', () => { changed = true; }, options);
  root.addEventListener('change', () => { changed = true; }, options);
  root.addEventListener('submit', e => {
    if (e.defaultPrevented) return;
    if (submitting) { e.preventDefault(); return; }
    submitting = true;
  }, options);
  window.addEventListener('pageshow', () => { submitting = false; }, options);
  window.addEventListener('beforeunload', e => {
    if (root.isConnected && changed && !submitting) { e.preventDefault(); e.returnValue = ''; }
  }, options);
  document.addEventListener('click', e => {
    if (!root.isConnected || !changed || submitting || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
    const link = e.target.closest('a[href]');
    if (!link || link.target || link.hasAttribute('download') || link.getAttribute('href').startsWith('#')) return;
    e.preventDefault(); e.stopImmediatePropagation();
    root.querySelector('[data-pengaturan-tinggalkan]')?.remove();
    const box = document.createElement('section');
    box.className = 'kartu'; box.dataset.pengaturanTinggalkan = '';
    box.setAttribute('role', 'alert');
    const title = document.createElement('h2'); title.textContent = 'Isian belum disimpan';
    const text = document.createElement('p'); text.textContent = 'Tetap di halaman ini untuk menjaga isian, atau tinggalkan tanpa menyimpan.';
    const stay = document.createElement('button'); stay.type = 'button'; stay.className = 'btn btn--utama'; stay.textContent = 'Tetap di halaman ini';
    const leave = document.createElement('button'); leave.type = 'button'; leave.className = 'btn'; leave.textContent = 'Tinggalkan tanpa menyimpan';
    stay.onclick = () => box.remove();
    leave.onclick = () => { changed = false; location.assign(link.href); };
    box.append(title, text, stay, leave); root.prepend(box); stay.focus();

  }, {...options, capture:true});
})();
