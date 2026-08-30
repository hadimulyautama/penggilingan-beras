/* Timbangan — lapisan perangkat.
 *
 * Tiga tugas, tidak lebih:
 *   1. memberi tahu petugas saat jaringan hilang, dan menahan kiriman
 *      di perangkat sampai jaringan kembali;
 *   2. menerima angka timbangan dengan koma maupun titik;
 *   3. menahan kirim ganda dari ketukan dobel.
 *
 * Sengaja tanpa kerangka kerja: satu berkas, tanpa proses bangun, bisa
 * dibaca dan diperbaiki siapa pun yang memegang sistem ini nanti.
 */
(function () {
  'use strict';

  var PREFIX = '/timbangan';
  var GUDANG = 'timbangan-antrean';   // localStorage: kiriman menunggu jaringan

  // ── Antrean kiriman ────────────────────────────────────────────────

  function bacaAntrean() {
    try { return JSON.parse(localStorage.getItem(GUDANG) || '[]'); }
    catch (e) { return []; }
  }

  function tulisAntrean(daftar) {
    try { localStorage.setItem(GUDANG, JSON.stringify(daftar)); }
    catch (e) { /* penyimpanan penuh atau diblokir — abaikan diam-diam */ }
    tampilkanJumlah();
  }

  function tampilkanJumlah() {
    var n = bacaAntrean().length;
    document.querySelectorAll('[data-antrean]').forEach(function (el) {
      el.textContent = n ? '· ' + n + ' menunggu terkirim' : '';
    });
  }

  function antrekan(kiriman) {
    var daftar = bacaAntrean();
    // Dikunci pada kode transaksi: mengantre dua kali tidak menggandakan.
    var i = daftar.findIndex(function (k) {
      return k.kode === kiriman.kode && k.url === kiriman.url;
    });
    if (i >= 0) { daftar[i] = kiriman; } else { daftar.push(kiriman); }
    tulisAntrean(daftar);
  }

  function kirimAntrean() {
    var daftar = bacaAntrean();
    if (!daftar.length || !navigator.onLine) { return; }

    var kiriman = daftar[0];
    fetch(kiriman.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(kiriman.data),
      credentials: 'same-origin'
    }).then(function (r) {
      // 4xx berarti server menolak isinya — mengirim ulang selamanya tidak
      // akan menolong, jadi baris itu dibuang agar antrean tidak macet.
      if (r.ok || (r.status >= 400 && r.status < 500)) {
        tulisAntrean(bacaAntrean().slice(1));
        kirimAntrean();
      }
    }).catch(function () { /* masih tanpa jaringan — coba lagi nanti */ });
  }

  // ── Penanda luring ─────────────────────────────────────────────────

  function perbaruiStatusJaringan() {
    document.body.classList.toggle('luring', !navigator.onLine);
    if (navigator.onLine) { kirimAntrean(); }
  }

  window.addEventListener('online', perbaruiStatusJaringan);
  window.addEventListener('offline', perbaruiStatusJaringan);

  // ── Angka timbangan ────────────────────────────────────────────────

  // Petugas mengetik '13.600', '13,600', '13600', atau '0.250' — semuanya sah.
  // Aturannya sama persis dengan `_angka()` di sisi server: satu titik dengan
  // tiga angka di belakangnya adalah pemisah ribuan HANYA bila angka di
  // depannya bukan nol. '0.250' adalah seperempat kilogram, bukan 250.
  function bakukanAngka(teks) {
    var s = String(teks || '').replace(/\s/g, '');
    if (s.indexOf(',') >= 0) { return s.replace(/\./g, '').replace(',', '.'); }
    var titik = s.split('.').length - 1;
    if (titik > 1) { return s.replace(/\./g, ''); }
    if (titik === 1) {
      var bagian = s.split('.');
      var depanBermakna = bagian[0].replace(/^[-+]/, '').replace(/^0+/, '') !== '';
      if (bagian[1].length === 3 && depanBermakna) { return s.replace('.', ''); }
    }
    return s;
  }

  document.addEventListener('blur', function (e) {
    if (!e.target.matches || !e.target.matches('[data-berat]')) { return; }
    var bersih = bakukanAngka(e.target.value);
    if (bersih !== '' && !isNaN(Number(bersih))) { e.target.value = bersih; }
  }, true);

  // ── Penahan kirim ganda ────────────────────────────────────────────

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.dataset.terkirim === '1') { e.preventDefault(); return; }
    form.dataset.terkirim = '1';
    form.querySelectorAll('button[type=submit]').forEach(function (t) {
      t.disabled = true;
      if (t.dataset.sibuk) { t.textContent = t.dataset.sibuk; }
    });
    // Bila navigasi gagal (jaringan putus di tengah), tombol dibuka kembali
    // supaya petugas tidak terjebak di layar yang tidak bisa apa-apa.
    setTimeout(function () {
      form.dataset.terkirim = '';
      form.querySelectorAll('button[type=submit]').forEach(function (t) {
        t.disabled = false;
      });
    }, 8000);
  });

  // ── Peringatan angka janggal ───────────────────────────────────────

  // Bukan penolakan: alat memang membaca kelipatan 10 kg, jadi angka yang
  // bukan kelipatan itu patut ditanya, bukan dilarang.
  document.addEventListener('input', function (e) {
    if (!e.target.matches || !e.target.matches('[data-berat]')) { return; }
    var kotak = e.target.closest('.grup');
    if (!kotak) { return; }
    var catatan = kotak.querySelector('[data-janggal]');
    if (!catatan) {
      catatan = document.createElement('div');
      catatan.className = 'bantu peringatan';
      catatan.setAttribute('data-janggal', '');
      kotak.appendChild(catatan);
    }
    var n = Number(bakukanAngka(e.target.value));
    var kelipatan = Number(document.body.dataset.kelipatan || 10);
    catatan.textContent = (n && kelipatan && n % kelipatan !== 0)
      ? 'Angka ini bukan kelipatan ' + kelipatan + ' kg — pastikan sudah benar.'
      : '';
  });

  // ── Mulai ──────────────────────────────────────────────────────────

  perbaruiStatusJaringan();
  tampilkanJumlah();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register(PREFIX + '/static/sw.js', { scope: PREFIX + '/' })
      .catch(function () { /* tanpa service worker aplikasi tetap jalan */ });
  }

  window.timbangan = { antrekan: antrekan, kirimAntrean: kirimAntrean };
})();
