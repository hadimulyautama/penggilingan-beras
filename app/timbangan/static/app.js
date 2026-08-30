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

  // ── Pilihan panjang jadi kolom ketik ───────────────────────────────
  //
  // Daftar supplier ikut Kledo, jadi isinya ratusan nama. Menggulir daftar
  // sepanjang itu di ponsel, sambil truk menunggu, adalah cara membuat orang
  // salah pilih.
  //
  // Peningkatan bertahap: <select> tetap dirender server dan tetap menjadi
  // pemegang nilai yang dikirim. Bila berkas ini gagal dimuat, petugas masih
  // mendapat dropdown biasa yang berfungsi penuh — bukan layar mati.
  //
  // Penyaringan memakai daftar yang SUDAH ada di halaman; tidak ada panggilan
  // ke server, jadi tetap bekerja tanpa sinyal.

  function pasangPencarian(pilih) {
    var opsi = [];
    Array.prototype.forEach.call(pilih.querySelectorAll('option'), function (o) {
      if (!o.value) { return; }
      var induk = o.parentNode;
      opsi.push({
        nilai: o.value,
        label: o.textContent.trim(),
        kelompok: induk.tagName === 'OPTGROUP' ? induk.label : ''
      });
    });
    if (opsi.length < 12) { return; }   // masih nyaman sebagai dropdown biasa

    var bungkus = document.createElement('div');
    bungkus.className = 'cari';
    var kotak = document.createElement('input');
    kotak.type = 'text';
    kotak.className = 'fld teks';
    kotak.setAttribute('autocomplete', 'off');
    kotak.setAttribute('enterkeyhint', 'search');
    kotak.placeholder = pilih.dataset.cari || 'Ketik untuk mencari…';
    var hasil = document.createElement('div');
    hasil.className = 'cari__hasil';
    var terpilih = document.createElement('div');
    terpilih.className = 'cari__terpilih';

    bungkus.appendChild(kotak);
    bungkus.appendChild(hasil);
    pilih.parentNode.insertBefore(bungkus, pilih);
    pilih.parentNode.insertBefore(terpilih, pilih.nextSibling);
    pilih.style.display = 'none';

    function tampilkanTerpilih() {
      var v = pilih.value;
      if (!v) { terpilih.textContent = ''; return; }
      var ada = opsi.filter(function (o) { return o.nilai === v; })[0];
      terpilih.innerHTML = '';
      var teks = document.createElement('span');
      teks.textContent = 'Terpilih: ' + (ada ? ada.label : v);
      var hapus = document.createElement('button');
      hapus.type = 'button';
      hapus.textContent = 'Ganti';
      hapus.addEventListener('click', function () {
        pilih.value = '';
        kotak.value = '';
        tampilkanTerpilih();
        kotak.focus();
      });
      terpilih.appendChild(teks);
      terpilih.appendChild(hapus);
    }

    function cocok(o, kata) {
      return o.label.toLowerCase().indexOf(kata) >= 0;
    }

    function gambar() {
      var kata = kotak.value.trim().toLowerCase();
      hasil.innerHTML = '';
      if (!kata) { return; }

      var ketemu = opsi.filter(function (o) { return cocok(o, kata); });
      if (!ketemu.length) {
        var kosong = document.createElement('div');
        kosong.className = 'cari__kosong';
        kosong.textContent = 'Tidak ada yang cocok dengan "' + kotak.value.trim() + '"';
        hasil.appendChild(kosong);
        return;
      }

      var kelompokTerakhir = null;
      ketemu.slice(0, 25).forEach(function (o) {
        if (o.kelompok && o.kelompok !== kelompokTerakhir) {
          kelompokTerakhir = o.kelompok;
          var judul = document.createElement('div');
          judul.className = 'kelompok';
          judul.textContent = o.kelompok;
          hasil.appendChild(judul);
        }
        var b = document.createElement('button');
        b.type = 'button';
        b.textContent = o.label;
        b.addEventListener('click', function () {
          pilih.value = o.nilai;
          kotak.value = '';
          hasil.innerHTML = '';
          tampilkanTerpilih();
        });
        hasil.appendChild(b);
      });
      if (ketemu.length > 25) {
        var sisa = document.createElement('div');
        sisa.className = 'cari__kosong';
        sisa.textContent = ketemu.length - 25 + ' lainnya — ketik lebih lengkap';
        hasil.appendChild(sisa);
      }
    }

    kotak.addEventListener('input', gambar);
    kotak.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        // Jangan mengirim formulir hanya karena petugas menekan Enter di
        // kolom cari; pilih hasil teratas bila ada.
        e.preventDefault();
        var pertama = hasil.querySelector('button');
        if (pertama) { pertama.click(); }
      } else if (e.key === 'Escape') {
        hasil.innerHTML = '';
      }
    });
    document.addEventListener('click', function (e) {
      if (!bungkus.contains(e.target)) { hasil.innerHTML = ''; }
    });

    tampilkanTerpilih();
  }

  document.querySelectorAll('select[data-cari]').forEach(pasangPencarian);

  // ── Mulai ──────────────────────────────────────────────────────────

  perbaruiStatusJaringan();
  tampilkanJumlah();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register(PREFIX + '/sw.js', { scope: PREFIX + '/' })
      .catch(function () { /* tanpa service worker aplikasi tetap jalan */ });
  }

  window.timbangan = { antrekan: antrekan, kirimAntrean: kirimAntrean };

  /* Baris tabel yang bisa dibuka.
   *
   * Tautan "Ubah" tetap ada supaya bisa dijangkau papan ketik dan pembaca
   * layar; ini hanya memperlebar sasaran sentuh ke seluruh baris — di layar
   * ponsel tombol sekecil itu sering meleset.
   */
  document.addEventListener('click', function (e) {
    if (!e.target.closest) { return; }
    var baris = e.target.closest('tr[data-buka]');
    if (!baris) { return; }
    // Jangan rebut klik yang memang punya tujuan sendiri.
    if (e.target.closest('a, button, input, select, label')) { return; }
    // Jangan pindah halaman saat orang sedang menyorot teks untuk disalin.
    var sorot = window.getSelection && window.getSelection().toString();
    if (sorot) { return; }
    window.location.href = baris.getAttribute('data-buka');
  });

})();
