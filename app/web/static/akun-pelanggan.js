/* Server searches every synced Kledo contact; the selected ID is never inferred from a name. */
(() => {
  const root = document.querySelector('[data-kontak-pilih]');
  if (!root) return;
  const input = root.querySelector('[role=combobox]');
  const value = root.querySelector('[name=kontak]');
  const list = root.querySelector('[role=listbox]');
  const status = root.querySelector('[role=status]');
  let timer, controller, sequence = 0, active = -1;
  const options = () => [...list.querySelectorAll('[role=option]')];
  function close() {
    clearTimeout(timer);
    sequence++;
    if (controller) controller.abort();
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  }
  function validity() {
    input.setCustomValidity(value.value ? '' : 'Pilih pelanggan dari hasil pencarian kontak Kledo.');
  }
  function highlight(index) {
    const rows = options();
    active = index;
    rows.forEach((row, i) => row.setAttribute('aria-selected', String(i === active)));
    if (rows[active]) {
      input.setAttribute('aria-activedescendant', rows[active].id);
      rows[active].scrollIntoView({block: 'nearest'});
    }
  }
  async function search() {
    const current = ++sequence;
    if (controller) controller.abort();
    controller = new AbortController();
    status.textContent = 'Mencari kontak Kledo…';
    try {
      const response = await fetch('/pengguna/pelanggan/kontak?q=' + encodeURIComponent(input.value.trim()),
        {signal: controller.signal, headers: {Accept: 'application/json'}, redirect: 'error', cache: 'no-store'});
      if (!response.ok) throw new Error('Pencarian gagal');
      const data = await response.json();
      if (current !== sequence) return;
      list.replaceChildren();
      active = -1;
      input.removeAttribute('aria-activedescendant');
      data.items.forEach((item, index) => {
        const option = document.createElement('button');
        option.type = 'button';
        option.tabIndex = -1;
        option.id = 'kontak-opsi-' + index;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        const name = document.createElement('strong');
        name.textContent = item.name;
        const detail = document.createElement('small');
        detail.textContent = item.label.slice(item.name.length + 3) + (item.phone ? ' · ' + item.phone : '');
        option.append(name, detail);
        option.addEventListener('mousedown', event => event.preventDefault());
        option.addEventListener('click', () => {
          value.value = item.value;
          input.value = item.label;
          validity();
          close();
          status.textContent = 'Pelanggan terpilih: ' + item.label;
          input.focus();
        });
        list.append(option);
      });
      list.hidden = !data.items.length;
      input.setAttribute('aria-expanded', String(!list.hidden));
      status.textContent = data.items.length
        ? data.items.length + ' kontak ditemukan.' + (data.more ? ' Ketik nama lebih lengkap untuk mempersempit hasil.' : '')
        : 'Tidak ada kontak yang cocok. Coba nama lain atau perbarui kontak Kledo.';
    } catch (error) {
      if (error.name === 'AbortError' || current !== sequence) return;
      close();
      status.textContent = 'Kontak gagal dimuat. Ketik ulang untuk mencoba lagi; masuk kembali jika sesi telah berakhir.';
    }
  }
  input.addEventListener('input', () => {
    close();
    value.value = '';
    validity();
    status.textContent = 'Mencari kontak Kledo…';
    timer = setTimeout(search, 200);
  });
  input.addEventListener('focus', () => { if (!value.value) search(); });
  input.addEventListener('keydown', event => {
    const rows = options();
    if (event.key === 'Escape') { close(); return; }
    if (event.key === 'Tab') { close(); return; }
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !list.hidden && rows.length) {
      event.preventDefault();
      highlight((active + (event.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length);
    }
    if (event.key === 'Enter' && !list.hidden && rows.length) {
      event.preventDefault();
      rows[active < 0 ? 0 : active].click();
    }
  });
  document.addEventListener('pointerdown', event => { if (!root.contains(event.target)) close(); });
  input.addEventListener('blur', () => { setTimeout(() => { if (!root.contains(document.activeElement)) close(); }, 150); });
  validity();
})();
