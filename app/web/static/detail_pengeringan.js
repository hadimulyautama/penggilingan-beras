/* Hash lama tetap membuka rincian yang tepat, termasuk sesudah navigasi instan. */
(function () {
  'use strict';
  var root = document.querySelector('.pengeringan-detail');
  if (!root) return;
  var tabs = Array.from(root.querySelectorAll('[role=tab]'));
  function tampil(id) {
    tabs.forEach(function (tab) {
      var aktif = tab.getAttribute('aria-controls') === id;
      tab.setAttribute('aria-selected', String(aktif));
      root.querySelector('#' + tab.getAttribute('aria-controls')).hidden = !aktif;
    });
  }
  function dariHash() {
    var id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    var target = document.getElementById(id);
    if (!target || !root.contains(target)) return;
    var panel = target.closest('[role=tabpanel]');
    if (!panel) return;
    tampil(panel.id);
    for (var el = target.parentElement; el && el !== root; el = el.parentElement) {
      if (el.tagName === 'DETAILS') el.open = true;
    }
    target.scrollIntoView({block: 'start'});
  }
  root.querySelector('.pengeringan-tabs').addEventListener('keydown', function (e) {
    var i = tabs.indexOf(e.target);
    if (i < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    i = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[i].focus(); tabs[i].click();
  });
  // Tautan tab tetap navigasi GET biasa: query, pagination dan konteks aksi
  // dipertahankan oleh server. Skrip ini hanya menjembatani fragmen URL lama.
  if (window.PINDAH) PINDAH.pasang(window, 'hashchange', dariHash);
  else window.addEventListener('hashchange', dariHash);
  dariHash();
})();

/* Perpindahan ke target tetap memakai formulir lama; draft ukur tidak dibuang. */
(function () {
  'use strict';
  var root = document.querySelector('.pengeringan-detail');
  if (!root) return;
  var lembar = document.getElementById('lembar');
  var sesi = document.querySelector('meta[name="formulir-sesi"]');
  var kunci = root.querySelector('h1').textContent + '|' + (sesi ? sesi.content : '');
  var arsip = window.PENGERINGAN_DRAFT;
  var draft = arsip && arsip.kunci === kunci ? arsip.isi : null;
  if (!lembar) return;
  lembar.addEventListener('click', function (e) {
    var pindah = e.target.closest('[data-buka-aksi="ubah_target"]');
    if (!pindah || !lembar.contains(pindah)) return;
    draft = {
      tes: Array.from(lembar.querySelectorAll('[data-ulang-untuk="tes"] input')).map(function (x) { return x.value; }),
      indikator: lembar.querySelector('#f_indikator').value,
      berubah: lembar._berubah
    };
    window.PENGERINGAN_DRAFT = {kunci: kunci, isi: draft};
    // Draft hanya di memori sesi halaman, termasuk sesudah target disimpan.
    lembar._berubah = false;
  }, true);
  lembar.addEventListener('click', function (e) {
    var hapus = e.target.closest('[data-titik-buang]');
    if (!hapus || !lembar.contains(hapus)) return;
    e.preventDefault();
    hapus.parentElement.remove();
    lembar.querySelector('[data-tambah="tes"]').hidden = false;
    lembar._berubah = true;
  });
  new MutationObserver(function () {
    lembar.querySelectorAll('[data-ulang-untuk="tes"] input').forEach(function (el, i) {
      if (!el.parentElement.classList.contains('pengeringan-titik')) {
        var baris = document.createElement('div'); baris.className = 'pengeringan-titik';
        el.before(baris); baris.appendChild(el);
        if (el.id !== 'f_tes') {
          var hapus = document.createElement('button');
          hapus.type = 'button'; hapus.className = 'btn btn--kecil'; hapus.dataset.titikBuang = '1';
          hapus.textContent = 'Hapus'; baris.appendChild(hapus);
        }
      }
      el.placeholder = 'titik ' + (i + 1);
      var tombol = el.parentElement.querySelector('[data-titik-buang]');
      if (tombol) tombol.setAttribute('aria-label', 'Hapus titik tes ' + (i + 1));
    });
    if (!draft) return;
    if (lembar.querySelector('#f_target') && !lembar.querySelector('#kembali-pengukuran')) {
      var tombol = document.createElement('button');
      tombol.type = 'button'; tombol.id = 'kembali-pengukuran'; tombol.className = 'btn btn--kecil';
      tombol.dataset.bukaAksi = 'kadar_air'; tombol.dataset.bawa = 'kode_lot';
      tombol.textContent = '← Kembali ke pengukuran';
      lembar.querySelector('.lembar__isi').appendChild(tombol);
    }
    if (lembar.querySelector('#f_tes')) {
      var pulih = draft; draft = null;
      window.PENGERINGAN_DRAFT = null;
      var tambah = lembar.querySelector('[data-tambah="tes"]');
      while (lembar.querySelectorAll('[data-ulang-untuk="tes"] input').length < pulih.tes.length) tambah.click();
      lembar.querySelectorAll('[data-ulang-untuk="tes"] input').forEach(function (el, i) { el.value = pulih.tes[i] || ''; });
      lembar.querySelector('#f_indikator').value = pulih.indikator;
      lembar._berubah = pulih.berubah;
    }
  }).observe(lembar, {childList: true, subtree: true});
})();
