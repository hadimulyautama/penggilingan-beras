/* Sampel disimpan saat spesifikasi dipilih, sebelum hasil pemeriksaan.
   Kunci kiriman tetap sama bila jaringan putus setelah server menyimpannya. */
(function () {
  'use strict';
  var root = document.querySelector('[data-qc-sosoh]');
  if (!root || root.dataset.siap) return;
  var form = root.querySelector('[data-qc-editor]');
  if (!form) return;
  root.dataset.siap = '1';
  var pilihan = form.querySelector('[data-qc-pilihan]');
  var hasil = form.querySelector('[data-qc-hasil]');
  var simpan = form.querySelector('[data-qc-simpan]');
  var galat = form.querySelector('[data-qc-galat]');
  var identitas = form.querySelector('[data-qc-identitas]');
  var kabar = form.querySelector('[data-qc-kabar]');
  var id = null, sibuk = false, kiriman = null;
  function pasang(target, jenis, fn) {
    if (window.PINDAH) PINDAH.pasang(target, jenis, fn);
    else target.addEventListener(jenis, fn);
  }
  function buka() {
    form.hidden = false;
    // Menahan segar otomatis selama editor terbuka, bahkan sebelum angka
    // pertama diketik. Penyimpanan sampel sendiri juga memancarkan perubahan.
    form.dispatchEvent(new Event('change', {bubbles:true}));
    form.scrollIntoView({block:'nearest', behavior:'smooth'});
  }
  function segarkan() {
    if (window.PINDAH) { PINDAH.lupakan(); PINDAH.segarkan(); }
    else location.reload();
  }
  function kunci(on) {
    sibuk = on;
    pilihan.disabled = on;
    hasil.disabled = on || !id;
    simpan.disabled = on || !id;
    root.querySelectorAll('[data-qc-lengkapi],[data-qc-nanti],[data-qc-baru]').forEach(function (b) { b.disabled = on; });
  }
  async function kirim(url, body) {
    if (window.SESIFORM && !SESIFORM.periksa()) throw Error('Sesi berubah. Masuk dengan akun pembuka formulir ini.');
    var token = document.getElementById('formulir-sesi');
    var controller = new AbortController(), timeout = setTimeout(function () { controller.abort(); }, 20000);
    try {
      var r = await fetch(url, {method:'POST', credentials:'same-origin', signal:controller.signal,
        headers:{'Content-Type':'application/json','X-CSRF-Token':token ? token.dataset.token : ''}, body:JSON.stringify(body)});
      var j = await r.json();
      if (window.SESIFORM && !SESIFORM.periksa()) throw Error('Sesi berubah saat menyimpan. Periksa riwayat sebelum mengulang.');
      if (!r.ok) throw Error(typeof j.detail === 'string' ? j.detail : 'Periksa nilai pemeriksaan dan coba kembali.');
      return j;
    } finally { clearTimeout(timeout); }
  }
  function terikat(nomor, jenis, waktu) {
    id = Number(nomor);
    pilihan.hidden = true;
    identitas.hidden = false;
    identitas.textContent = 'Sampel #' + id + ' · ' + jenis + ' · diambil ' + waktu + ' WIB. Identitas tetap mengikuti sampel ini.';
    hasil.disabled = false;
    simpan.disabled = false;
    form.querySelector('[data-qc-tajuk]').textContent = 'Lengkapi hasil QC';
  }
  document.querySelectorAll('[data-qc-baru]').forEach(function (b) {
    pasang(b, 'click', function () {
      if (sibuk) return;
      // Sampel yang sudah tersimpan tetap ditawarkan sampai hasil diisi atau
      // pengguna memilih lanjutkan nanti, sehingga ketukan ganda tak membuat sampel baru.
      buka();
    });
  });
  pasang(root, 'click', async function (e) {
    var b = e.target.closest('[data-qc-jenis],[data-qc-lengkapi],[data-qc-nanti]');
    if (!b || sibuk) return;
    galat.textContent = '';
    if (b.hasAttribute('data-qc-nanti')) { segarkan(); return; }
    if (b.hasAttribute('data-qc-lengkapi')) {
      if (id) {
        if (id !== Number(b.dataset.qcLengkapi)) galat.textContent = 'Selesaikan atau pilih Lanjutkan nanti sebelum membuka sampel lain.';
        buka(); return;
      }
      form.reset(); terikat(b.dataset.qcLengkapi, b.dataset.label, b.dataset.waktu); buka(); return;
    }
    if (id) return;
    if (kiriman && kiriman.jenis !== b.dataset.qcJenis) {
      galat.textContent = 'Status sampel sebelumnya belum pasti. Tekan kembali spesifikasi yang sama untuk memulihkannya.'; return;
    }
    if (!kiriman) kiriman = {kode_proses:root.dataset.kode, jenis:b.dataset.qcJenis,
      kunci_kiriman:crypto.randomUUID()};
    kunci(true);
    try {
      var j = await kirim('/api/actions/sampel-qc-sosoh', kiriman);
      var waktu = new Intl.DateTimeFormat('id-ID', {timeZone:'Asia/Jakarta',dateStyle:'short',timeStyle:'short'}).format(new Date(j.waktu_sampel));
      terikat(j.sampel_id, b.textContent.trim(), waktu);
      kabar.textContent = 'Sampel tersimpan. Hasil lab boleh dilengkapi nanti.';
      if (window.PINDAH) PINDAH.lupakan();
    } catch (err) { galat.textContent = (err.name === 'AbortError' ? 'Jaringan terputus.' : err.message) + ' Tekan spesifikasi yang sama untuk mencoba kembali.'; }
    finally { kunci(false); }
  });
  pasang(form, 'submit', async function (e) {
    e.preventDefault();
    if (sibuk || !id) return;
    galat.textContent = '';
    var body = {sampel_id:id}, ada = false;
    for (var key of ['kadar_air','broken_persen','md','transparant','whiteness']) {
      var raw = form.elements[key].value.trim().replace(',', '.');
      var n = raw === '' ? null : Number(raw);
      var persen = key === 'kadar_air' || key === 'broken_persen';
      if (n !== null && (!Number.isFinite(n) || n < 0 || (persen && n > 100))) {
        galat.textContent = persen ? 'Kadar air dan broken harus antara 0 dan 100%.' : 'MD, Transparant, dan Whiteness harus berupa angka tidak negatif.'; return;
      }
      // Kirim teks desimal asli supaya server membulatkan 1,005 menjadi 1,01
      // tanpa melewati pembulatan float JavaScript lebih dahulu.
      body[key] = raw === '' ? null : raw; if (n !== null) ada = true;
    }
    for (var nama of ['catatan_lab']) {
      body[nama] = form.elements[nama].value.trim() || null;
      if (body[nama]) ada = true;
    }
    if (!ada) { galat.textContent = 'Isi minimal satu hasil pemeriksaan.'; return; }
    kunci(true);
    try { await kirim('/api/actions/qc-sosoh', body); segarkan(); }
    catch (err) { galat.textContent = err.name === 'AbortError' ? 'Jaringan terputus. Periksa riwayat; isian tetap tersedia.' : err.message; kunci(false); }
  });
  if (location.hash === '#qc-sosoh' && root.querySelector('[data-qc-baru]')) buka();
})();
