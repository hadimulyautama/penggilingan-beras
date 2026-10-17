(() => {
  const root = document.getElementById('retur-ui');
  if (!root) return;
  const katalog = JSON.parse(root.querySelector('#retur-katalog').textContent);
  const list = root.querySelector('#ticket-list');
  const rows = root.querySelector('#return-items');
  const tmpl = document.getElementById('item-template');
  const fmt = n => Number(n || 0).toLocaleString('id-ID', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  let target = 0, selesai = false;
  const check = () => {
    rows.querySelectorAll('.rt-item').forEach(row => {
      const size = Number(row.querySelector('[name="kemasan"]').selectedOptions[0]?.dataset.ukuran || 0);
      const bags = Number(row.querySelector('[name="jumlah_karung"]').value);
      row.querySelector('[name="berat_kg"]').value = size > 0 && Number.isInteger(bags) && bags > 0 ? size * bags : '';
    });
    const total = [...rows.querySelectorAll('[name="berat_kg"]')].reduce((s, e) => s + (parseFloat(e.value) || 0), 0);
    const diff = target - total;
    const melewati = selesai && Math.abs(diff) > Math.max(2, target * .002);
    root.querySelector('#sum-weight').textContent = fmt(total);
    root.querySelector('#ticket-weight').textContent = selesai ? fmt(target) : 'menunggu timbang kedua';
    const box = root.querySelector('#weight-check');
    box.classList.toggle('ok', selesai && !melewati);
    box.classList.toggle('warn', melewati);
    root.querySelector('#weight-difference').textContent = selesai ? 'Selisih ' + (diff > 0 ? '+' : '') + fmt(diff) + ' kg' : 'Belum masuk stok';
    const reason = root.querySelector('#reason-field');
    reason.classList.toggle('show', melewati);
    reason.querySelector('input').required = melewati;
  };
  const bindRow = row => {
    row.querySelector('.jenis-select').addEventListener('change', e => {
      const category = e.target.value;
      row.dataset.category = category;
      const kemasan = row.querySelector('[name="kemasan"]');
      kemasan.replaceChildren(new Option('Pilih kemasan', ''));
      (katalog.kemasan[category] || []).forEach(k => {
        const option = new Option(k.nama, k.nilai);
        option.dataset.ukuran = k.ukuran_kg;
        kemasan.add(option);
      });
      kemasan.disabled = !category;
      const beras = category === 'beras_putih';
      ['quality_id', 'brand_id'].forEach(name => {
        const el = row.querySelector(`[name="${name}"]`);
        el.required = beras;
        el.value = '';
      });
      check();
    });
    row.querySelectorAll('input,select').forEach(e => e.addEventListener('input', check));
    row.querySelector('[name="kemasan"]').addEventListener('change', check);
    row.querySelector('.rt-remove').addEventListener('click', () => {
      if (rows.children.length > 1) { row.remove(); check(); }
    });
  };
  const updateTicket = () => {
    const sel = list?.querySelector('input:checked');
    if (!sel) return;
    const d = sel.dataset;
    target = parseFloat(d.net) || 0;
    selesai = d.state === 'SELESAI';
    root.querySelector('#picked-code').textContent = d.code;
    root.querySelector('#picked-customer').textContent = d.customer;
    root.querySelector('#picked-plate').textContent = d.plate;
    root.querySelector('#picked-gross').textContent = fmt(d.gross) + ' kg';
    root.querySelector('#picked-empty').textContent = selesai ? fmt(d.empty) + ' kg' : 'Menunggu';
    root.querySelector('#picked-net').textContent = selesai ? fmt(target) + ' kg' : 'Menunggu';
    root.querySelector('#save-details').disabled = selesai;
    root.querySelector('#submit-return').disabled = !selesai;
    const items = JSON.parse(d.items || '[]');
    rows.replaceChildren();
    (items.length ? items : [{}]).forEach(item => {
      const row = tmpl.content.firstElementChild.cloneNode(true);
      rows.appendChild(row);
      bindRow(row);
      const pilihan = item.jenis_barang ? item : (katalog.sku[String(item.sku_id)] || {});
      row.querySelector('.jenis-select').value = pilihan.jenis_barang || '';
      row.querySelector('.jenis-select').dispatchEvent(new Event('change'));
      ['kemasan', 'brand_id'].forEach(name => {
        if (pilihan[name] !== undefined && pilihan[name] !== null) row.querySelector(`[name="${name}"]`).value = pilihan[name];
      });
      ['quality_id', 'jumlah_karung', 'catatan_item'].forEach(name => {
        if (item[name] !== undefined && item[name] !== null) row.querySelector(`[name="${name}"]`).value = item[name];
      });
    });
    check();
  };
  list?.addEventListener('change', updateTicket);
  root.querySelector('#add-item').addEventListener('click', () => {
    const row = tmpl.content.firstElementChild.cloneNode(true);
    rows.appendChild(row); bindRow(row); row.querySelector('select').focus();
  });
  rows.querySelectorAll('.rt-item').forEach(bindRow);
  updateTicket();
})();
