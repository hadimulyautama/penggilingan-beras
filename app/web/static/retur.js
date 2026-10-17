(() => {
  const root = document.getElementById('retur-ui');
  if (!root) return;
  const list = root.querySelector('#ticket-list');
  const rows = root.querySelector('#return-items');
  const tmpl = document.getElementById('item-template');
  const fmt = n => Number(n || 0).toLocaleString('id-ID', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  let target = 0, selesai = false;
  const check = () => {
    const total = [...rows.querySelectorAll('[name="berat_kg"]')].reduce((s, e) => s + (parseFloat(e.value) || 0), 0);
    const diff = total - target;
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
    row.querySelector('.sku-select').addEventListener('change', e => {
      const category = e.target.selectedOptions[0]?.dataset.category || '';
      row.dataset.category = category;
      row.querySelector('[name="tara_per_karung_kg"]').value = e.target.selectedOptions[0]?.dataset.tara || '';
      const quality = row.querySelector('[name="quality_id"]');
      quality.required = category === 'beras_putih';
      if (!quality.required) quality.value = '';
      check();
    });
    row.querySelectorAll('input,select').forEach(e => e.addEventListener('input', check));
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
      row.querySelector('.sku-select').value = item.sku_id || '';
      row.querySelector('.sku-select').dispatchEvent(new Event('change'));
      ['sku_id', 'quality_id', 'jumlah_karung', 'tara_per_karung_kg', 'berat_kg', 'catatan_item'].forEach(name => {
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
  updateTicket();
})();
