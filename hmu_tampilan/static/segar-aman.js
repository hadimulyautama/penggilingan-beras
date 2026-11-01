/* Satu pagar untuk penyegaran otomatis staf dan portal. Tidak menyimpan draf
 * ke server/storage; hanya menahan penggantian DOM selama isian belum aman. */
(function () {
  'use strict';
  if (window.SEGAR_AMAN) return;
  var awal = new WeakMap(), kotor = new Set(), terkirim = new Set(), sentuh = 0;
  function nilai(el) {
    if (el.type === 'file') return Array.from(el.files || []).map(function (f) { return f.name + ':' + f.size; }).join('|');
    if (el.type === 'checkbox' || el.type === 'radio') return String(el.checked);
    if (el.multiple) return Array.from(el.selectedOptions).map(function (o) { return o.value; }).join('\n');
    return el.value;
  }
  function kontrol(el) { return el && el.matches && el.matches('input:not([type=hidden]),select,textarea,[contenteditable=true]'); }
  function baca(el) { return el.isContentEditable ? el.innerHTML : nilai(el); }
  function nilaiAwal(el) {
    if (el.isContentEditable) return el.innerHTML;
    if (el.type === 'checkbox' || el.type === 'radio') return String(el.defaultChecked);
    if (el.tagName === 'SELECT') {
      var opts = Array.from(el.options).filter(function (o) { return o.defaultSelected; });
      if (!el.multiple && !opts.length && el.options.length) opts = [el.options[0]];
      return opts.map(function (o) { return o.value; }).join('\n');
    }
    return el.defaultValue || '';
  }
  function ingat(root) {
    root.querySelectorAll('input,select,textarea,[contenteditable=true]').forEach(function (el) {
      if (!awal.has(el)) awal.set(el, nilaiAwal(el));
    });
  }
  function tutup(el) {
    var d = el.closest('dialog,.lembar');
    return d && !(d.open || d.style.display === 'flex');
  }
  function filterTersimpan(el) {
    var form = el.form;
    if (!(form && form.method.toLowerCase() === 'get') && !el.closest('[data-saring-kerja]')) return false;
    if (!el.name || el.type === 'file' || el.type === 'checkbox' || el.type === 'radio' || el.multiple) return false;
    return (new URL(location.href).searchParams.get(el.name) || '') === el.value;
  }
  function bersih() {
    // Autofill/perubahan nilai tanpa event juga merupakan isian belum aman.
    document.querySelectorAll('form input:not([name=_csrf]),form select,form textarea,[contenteditable=true]').forEach(function (el) {
      if (!awal.has(el)) awal.set(el, nilaiAwal(el));
      if (!el.disabled && !el.readOnly && baca(el) !== awal.get(el)) kotor.add(el);
    });
    kotor.forEach(function (el) {
      if (!el.isConnected || tutup(el) || baca(el) === awal.get(el) || filterTersimpan(el)) kotor.delete(el);
    });
    terkirim.forEach(function (form) { if (!form.isConnected || tutup(form)) terkirim.delete(form); });
  }
  document.addEventListener('focusin', function (e) { if (kontrol(e.target) && !awal.has(e.target)) awal.set(e.target, nilaiAwal(e.target)); }, true);
  function ubah(e) {
    if (!kontrol(e.target)) return;
    if (!awal.has(e.target)) awal.set(e.target, e.target.defaultValue || '');
    if (baca(e.target) !== awal.get(e.target)) kotor.add(e.target); else kotor.delete(e.target);
  }
  document.addEventListener('input', ubah, true);
  document.addEventListener('change', ubah, true);
  document.addEventListener('submit', function (e) { terkirim.add(e.target); }, true);
  document.addEventListener('reset', function (e) {
    setTimeout(function () {
      terkirim.delete(e.target);
      e.target.querySelectorAll('input,select,textarea').forEach(function (el) { awal.set(el, baca(el)); kotor.delete(el); });
    }, 0);
  }, true);
  document.addEventListener('pointerdown', function () { sentuh = Date.now(); }, true);
  document.addEventListener('pointerup', function () { sentuh = Date.now(); }, true);
  window.SEGAR_AMAN = {
    ingat: function () { ingat(document); },
    boleh: function () {
      bersih();
      if (document.visibilityState !== 'visible' || kotor.size || terkirim.size || Date.now() - sentuh < 600) return false;
      if (document.querySelector('dialog[open],[role=dialog][aria-modal=true],[data-editor-perintah],[data-kemas-ulang]')) return false;
      var d = document.getElementById('lembar');
      if (d && d.style.display === 'flex') return false;
      return !kontrol(document.activeElement);
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { ingat(document); }); else ingat(document);
})();
