/* Memasang kode baru pada saat aman, tanpa tombol reload atau kehilangan isian.
 * Dimuat di dalam bingkai juga: dokumen lama dapat menerima modul ini lewat
 * penyegaran data yang sudah didukung, lalu memperbarui kerangka secara utuh. */
(function () {
  "use strict";
  var skrip = document.currentScript;
  var cap = skrip ? new URL(skrip.src, location.href).searchParams.get("v") : "";
  if (window.PEMBARUAN_APLIKASI) {
    window.PEMBARUAN_APLIKASI.terima(cap);
    return;
  }
  var awal = document.documentElement.getAttribute("data-versi") || "";
  var menunggu = "", berjalan = false, pewaktu = null, pointer = false;
  var isian = new Set();
  function aman() {
    if (document.hidden || navigator.onLine === false || pointer) return false;
    if (document.querySelector('dialog[open], .lembar[open], [data-editor-perintah], [data-kemas-ulang]')) return false;
    var fokus = document.activeElement;
    if (fokus && /^(INPUT|TEXTAREA|SELECT)$/.test(fokus.tagName)) return false;
    // Formulir GET hanya saringan. Isian POST atau isian tanpa form harus
    // selesai/dilepas dari layar dulu. Editor khusus mempunyai penjaga di atas.
    var ada = false;
    isian.forEach(function (el) {
      var dialog = el.closest('dialog, .lembar');
      if (!el.isConnected || (dialog && !dialog.open)) isian.delete(el);
      else ada = true;
    });
    return !ada;
  }
  function periksa() {
    clearTimeout(pewaktu);pewaktu = null;
    if (!menunggu || berjalan) return;
    if (aman()) {
      berjalan = true;
      location.reload();
      return;
    }
    var pil = document.querySelector('.pil-versi');
    if (!pil || pil.tagName === 'BUTTON') {
      if (pil) pil.remove();
      pil = document.createElement('p');pil.className = 'pil-versi';pil.setAttribute('role', 'status');
      document.body.appendChild(pil);
    }
    pil.textContent = 'Pembaruan dipasang otomatis setelah isian selesai.';
    if (!document.hidden && navigator.onLine !== false) pewaktu = setTimeout(periksa, 1000);
  }
  function terima(versi) {
    if (!versi || !awal || String(versi) === awal) return;
    menunggu = String(versi);
    periksa();
  }
  window.PEMBARUAN_APLIKASI = {terima: terima};
  document.addEventListener('padiflow:versi', function (e) { terima(e.detail && e.detail.versi); });
  document.addEventListener('input', function (e) {
    if (!e.isTrusted) return;
    var form = e.target.form;
    if (!form || String(form.method).toLowerCase() !== 'get') isian.add(form || e.target);
  }, true);
  document.addEventListener('pointerdown', function () { pointer = true; }, true);
  document.addEventListener('pointerup', function () { pointer = false;setTimeout(periksa, 0); }, true);
  document.addEventListener('pointercancel', function () { pointer = false;setTimeout(periksa, 0); }, true);
  document.addEventListener('focusout', function () { setTimeout(periksa, 0); });
  document.addEventListener('visibilitychange', periksa);
  window.addEventListener('online', periksa);
  // Dokumen lama masih membawa cap lama pada <html>. Ketika bingkainya
  // menerima skrip rilis baru, pasang kerangka baru tanpa menunggu ketukan.
  terima(cap);
})();
