/* Penutupan memakai aktual yang sudah dicatat. Angka dan syarat berasal
   dari layanan lama; tidak ada panggilan Muat semua dari formulir ini. */
(function () {
  'use strict';
  var root = document.querySelector('[data-selesai-muatan]');
  if (!root || root.dataset.siap) return;
  root.dataset.siap = '1';
  var data = JSON.parse(document.getElementById('selesai-awal').textContent);
  var boleh = root.dataset.boleh === '1';
  var isi = root.querySelector('[data-isi-selesai]');
  var galat = root.querySelector('[data-galat]');
  var kabar = root.querySelector('[data-kabar]');
  var refresh = root.querySelector('[data-terbaru]');
  var pilihan = null, tahap = 'daftar', rencana = null;
  var draf = {}, alasanAwal = '', sibuk = false, basi = false, tidakPasti = false;

  function el(tag, teks, kelas) {
    var e = document.createElement(tag);
    if (teks != null) e.textContent = teks;
    if (kelas) e.className = kelas;
    return e;
  }
  function tombol(teks, fn, utama) {
    var b = el('button', teks, 'btn' + (utama ? ' cm-utama' : ''));
    b.type = 'button'; b.onclick = fn; return b;
  }
  function angka(n) { return Number(n).toLocaleString('id-ID', {maximumFractionDigits:6}); }
  function pair(w, k, v) {
    var e = el('div', null, 'cm-pasang');
    e.append(el('span', k), el('strong', v)); w.append(e);
  }
  function pesan(teks) { galat.textContent = teks; galat.hidden = false; }
  function cari(id) {
    for (var k of data.kiriman) for (var p of k.pelanggan)
      if (p.id === id) return {kiriman:k, pelanggan:p};
    return null;
  }
  function tertutup(p) { return p.status === 'dimuat' || p.status === 'selesai'; }
  function labelStatus(p) {
    return {perintah:'Belum diselesaikan', dimuat:'Selesai muat', selesai:'Pengiriman terverifikasi', batal:'Dibatalkan'}[p.status] || p.status;
  }
  function konteks(k, p) {
    var box = el('div', null, 'cm-konteks');
    box.append(el('strong', p ? p.nama : k.plat || 'Armada belum dipilih'));
    box.append(el('span', p ? p.kode + ' · ' + (k.plat || 'Armada menyusul') : 'Satu kiriman · rincian per pelanggan'));
    box.append(el('span', k.tiket ? k.tiket.kode + ' · ' + (k.tiket.status_tiket === 'SELESAI' ? 'Timbang kedua selesai' : 'Timbang pertama selesai') : 'Tiket menyusul'));
    return box;
  }
  function barang(rows, sudahTutup) {
    var box = el('div', null, 'sm-barang');
    rows.forEach(function (i) {
      var row = el('section', null, 'cm-barang'); row.dataset.item = i.id;
      row.append(el('h3', i.nama_lengkap || i.nama), el('span', i.lokasi + ' · ' + i.pemilik, 'cm-bantu'));
      var met = el('div', null, 'cm-angka');
      [['Perintah', i.perintah], ['Aktual dimuat', i.dimuat], [sudahTutup ? 'Tidak terkirim' : 'Belum dimuat', i.sisa]].forEach(function (v) {
        var m = el('div'); m.append(el('span', v[0]), el('strong', angka(v[1]) + ' ' + i.satuan)); met.append(m);
      });
      row.append(met); box.append(row);
    });
    return box;
  }
  function kesiapan(k) {
    var box = el('section', null, 'sm-siap'); box.dataset.kesiapan = k.kesiapan;
    box.append(el('strong', k.pelanggan_selesai + ' dari ' + k.jumlah_pelanggan + ' pelanggan selesai muat'));
    pair(box, 'Total perintah', angka(k.total_perintah_kg) + ' kg');
    pair(box, 'Muatan aktual armada', angka(k.total_dimuat_kg) + ' kg');
    pair(box, k.semua_selesai_muat ? 'Total tidak terkirim' : 'Sisa terhadap perintah', angka(k.total_sisa_kg) + ' kg');
    if (!k.semua_selesai_muat && k.total_tidak_terkirim_kg > 0)
      pair(box, 'Tidak terkirim dari pelanggan yang selesai', angka(k.total_tidak_terkirim_kg) + ' kg');
    var kata = {
      menunggu_pelanggan:'Selesaikan pemeriksaan setiap pelanggan. Kiriman belum selesai muat dan belum siap dilanjutkan ke pemeriksaan akhir.',
      menunggu_tiket:'Seluruh pelanggan selesai muat. Tiket belum dipilih; pilih tiket armada setelah timbang pertama sesuai alur Pengiriman, lalu lanjutkan timbang kedua dan pemeriksaan yang berlaku.',
      menunggu_timbang_kedua:'Seluruh pelanggan selesai muat. Lanjutkan timbang kedua di TeraFlow; verifikasi pengiriman tetap menunggu tiket selesai dan pemeriksaan yang berlaku.',
      menunggu_pemeriksaan:'Seluruh pelanggan selesai muat dan timbang kedua selesai. Lanjutkan pemeriksaan Pengiriman; verifikasi akhir belum dilakukan.',
      terverifikasi:'Pengiriman sudah terverifikasi sesuai prosesnya.',
      dibatalkan:'Kiriman dibatalkan; tidak ada pelanggan aktif untuk diselesaikan.'
    };
    box.append(el('p', kata[k.kesiapan] || 'Periksa status kiriman di Pengiriman.', 'cm-bantu'));
    return box;
  }
  function tampilAlasan(w, judul, teks) {
    w.append(el('h3', judul), el('p', teks || 'Tidak ada keterangan.', 'sm-alasan'));
  }
  function daftar() {
    if (!data.kiriman.length) isi.append(el('p', 'Tidak ada tugas muat. Perintah yang tersedia akan muncul di sini.'));
    var stack = el('div', null, 'cm-stack');
    data.kiriman.forEach(function (k) {
      stack.append(konteks(k));
      k.pelanggan.forEach(function (p) {
        var card = el('section', null, 'cm-pelanggan'); card.dataset.perintah = p.id;
        var head = el('header', null, 'cm-kepala'), nama = el('div');
        nama.append(el('h2', p.nama), el('small', p.kode)); head.append(nama, el('span', labelStatus(p), 'cm-status'));
        card.append(head, barang(p.barang, tertutup(p)));
        pair(card, 'Subtotal aktual', angka(p.total_dimuat_kg) + ' kg');
        if (tertutup(p) && p.penutupan && p.penutupan.alasan) tampilAlasan(card, 'Alasan / keterangan', p.penutupan.alasan);
        if (p.status !== 'batal') {
          var b = tombol(tertutup(p) ? 'Ringkasan penyelesaian' : 'Periksa & selesaikan muatan', function () { buka(p.id); });
          b.dataset.selesaiPelanggan = p.id;
          b.disabled = sibuk || basi || tidakPasti || (!tertutup(p) && !boleh);
          b.setAttribute('aria-label', b.textContent + ' untuk ' + p.nama); card.append(b);
        }
        stack.append(card);
      });
      stack.append(kesiapan(k));
    });
    isi.append(stack);
  }
  function buka(id) {
    if (sibuk || basi || tidakPasti) return;
    var p = cari(id); if (!p) return;
    pilihan = p; rencana = null; tahap = tertutup(p.pelanggan) ? 'hasil' : 'form';
    if (draf[id] == null) draf[id] = '';
    alasanAwal = draf[id]; galat.hidden = true; gambar();
  }
  function dampak() {
    var p = pilihan.pelanggan, box = el('aside', null, 'cm-ringkasan');
    box.append(el('h3', tahap === 'hasil' ? 'Dampak penyelesaian' : 'Yang akan diselesaikan'));
    pair(box, 'Pelanggan', rencana ? rencana.pelanggan : p.nama);
    pair(box, 'Total perintah', angka(rencana ? rencana.total_perintah_kg : p.total_perintah_kg) + ' kg');
    pair(box, 'Aktual tetap dimuat', angka(rencana ? rencana.total_aktual_kg : p.total_dimuat_kg) + ' kg');
    pair(box, 'Tidak terkirim', angka(rencana ? rencana.tidak_terkirim_kg : p.total_sisa_kg) + ' kg');
    var efek = el('div', null, 'sm-dampak');
    efek.append(el('strong', 'Jumlah aktual dan stok fisik tetap'));
    efek.append(el('p', 'Kekurangan tidak diisi otomatis. Penyelesaian tidak menambah muatan atau mengurangi stok lagi.'));
    efek.append(el('p', 'Sisa perintah pelanggan ini ditutup dan tidak lagi menahan saldo. Barang yang tidak dimuat tetap berada di stok.'));
    efek.append(el('p', 'Pelanggan lain tidak diselesaikan. Ini belum merupakan verifikasi akhir pengiriman.'));
    box.append(efek); return box;
  }
  function kembali() {
    if (sibuk) return;
    if (tahap === 'review') { tahap = 'form'; rencana = null; gambar(); return; }
    if (tahap !== 'hasil' && draf[pilihan.pelanggan.id] !== alasanAwal) {
      var q = el('section', null, 'cm-periksa');
      q.append(el('strong', 'Alasan belum disimpan'), el('p', 'Kembali tanpa menyelesaikan muatan?'));
      var a = el('div', null, 'cm-tindakan');
      a.append(tombol('Tetap isi', function () { q.remove(); }), tombol('Buang & kembali', function () {
        draf[pilihan.pelanggan.id] = ''; pilihan = null; tahap = 'daftar'; gambar();
      })); q.append(a); isi.prepend(q); return;
    }
    pilihan = null; tahap = 'daftar'; rencana = null; gambar();
  }
  function form() {
    var k = pilihan.kiriman, p = pilihan.pelanggan, box = el('section', null, 'cm-form');
    var hasil = tahap === 'hasil';
    box.append(el('h2', hasil ? 'Ringkasan penyelesaian' : tahap === 'review' ? 'Konfirmasi selesai muat' : 'Selesai muat pelanggan'), konteks(k, p));
    var layout = el('div', null, 'cm-layout'), fields = el('div', null, 'cm-isian');
    fields.append(barang(rencana ? rencana.barang : p.barang, true));
    if (hasil) {
      var tutup = p.penutupan || {};
      tampilAlasan(fields, 'Alasan / keterangan tersimpan', tutup.alasan);
      if (tutup.petugas) fields.append(el('p', 'Diselesaikan oleh ' + tutup.petugas, 'cm-bantu'));
      if (draf[p.id] && draf[p.id].trim() !== (tutup.alasan || '')) tampilAlasan(fields, 'Alasan yang sempat Anda isi', draf[p.id]);
    } else if (tahap === 'review') tampilAlasan(fields, 'Alasan / keterangan', rencana.alasan);
    else {
      var label = el('label', p.alasan_wajib ? 'Alasan barang tidak terkirim · wajib' : 'Keterangan penyelesaian · opsional'); label.htmlFor = 'sm-sebab';
      var input = el('textarea'); input.id = 'sm-sebab'; input.rows = 3; input.value = draf[p.id];
      input.setAttribute('aria-required', p.alasan_wajib ? 'true' : 'false');
      input.disabled = !boleh || p.status !== 'perintah';
      input.oninput = function () { draf[p.id] = input.value; rencana = null; if (!basi && !tidakPasti) galat.hidden = true; };
      fields.append(label, input, el('p', p.alasan_wajib ? 'Isi alasan untuk kekurangan yang ditampilkan. Spasi kosong tidak dianggap alasan.' : 'Muatan sesuai perintah dalam toleransi layanan; keterangan boleh dikosongkan.', 'cm-bantu'));
      if (!p.ada_muatan) {
        fields.append(el('p', 'Belum ada muatan aktual yang memenuhi syarat. Catat muatan dahulu, atau mintakan pembatalan kepada pihak berwenang.', 'cm-bantu'));
        var a = el('a', 'Buka Catat muatan'); a.href = '/muatan?perintah=' + p.id; fields.append(a);
      }
    }
    layout.append(fields, dampak()); box.append(layout);
    if (hasil) { box.append(el('p', 'Sisa ditampilkan sebagai Tidak terkirim; jumlah aktual tetap sesuai catatan muat.', 'cm-bantu'), kesiapan(k)); }
    var actions = el('div', null, 'cm-tindakan'); actions.append(tombol(tahap === 'review' ? 'Kembali periksa' : 'Kembali ke kiriman bersama', kembali));
    if (!hasil) {
      var b = tombol(tahap === 'review' ? 'Selesaikan sesuai muatan aktual' : 'Periksa penyelesaian', tahap === 'review' ? simpan : periksa, true);
      b.dataset.konfirmasi = ''; b.disabled = !boleh || !p.bisa_selesai || basi || tidakPasti; actions.append(b);
    }
    box.append(actions); isi.append(box);
  }
  function gambar() { isi.replaceChildren(); if (tahap === 'daftar') daftar(); else form(); }
  function payload() {
    var p = pilihan.pelanggan;
    return {perintah:String(p.id), kiriman_id:pilihan.kiriman.id, pelanggan_id:p.pelanggan_id,
      item_ids:p.barang.map(function (i) { return i.id; }), dasar:p.dasar, sebab:draf[p.id] || ''};
  }
  function kunci(v) {
    sibuk = v;
    root.querySelectorAll('button,textarea').forEach(function (e) {
      if (v) { e.dataset.sebelumKunci = e.disabled ? '1' : '0'; e.disabled = true; }
      else if (e.dataset.sebelumKunci != null) { e.disabled = e.dataset.sebelumKunci === '1'; delete e.dataset.sebelumKunci; }
    });
    if (!v && pilihan) {
      var b = isi.querySelector('[data-konfirmasi]');
      if (b) b.disabled = !boleh || !pilihan.pelanggan.bisa_selesai || basi || tidakPasti;
    }
  }
  async function panggil(url, method, body) {
    if (window.SESIFORM && !SESIFORM.periksa()) throw Error('Sesi berubah. Alasan tetap tersedia; masuk dengan akun pembuka formulir.');
    var tag = document.getElementById('formulir-sesi'), ctrl = new AbortController();
    var timeout = setTimeout(function () { ctrl.abort(); }, 20000);
    try {
      var r = await fetch(url, {method:method, credentials:'same-origin', signal:ctrl.signal,
        headers:{'Content-Type':'application/json', 'X-CSRF-Token':tag ? tag.dataset.token : ''}, body:body ? JSON.stringify(body) : undefined});
      var j = await r.json().catch(function () { return {}; });
      if (window.SESIFORM && !SESIFORM.periksa()) throw Error('Sesi berubah; periksa status muatan sebelum mengulang.');
      if (!r.ok) { var e = Error(typeof j.detail === 'string' ? j.detail : 'Permintaan belum dapat diproses. Alasan tetap tersedia.'); e.status = r.status; throw e; }
      return j;
    } finally { clearTimeout(timeout); }
  }
  async function periksa() {
    if (sibuk || basi || tidakPasti || !pilihan || !boleh || !pilihan.pelanggan.bisa_selesai) return;
    var body = payload();
    if (pilihan.pelanggan.alasan_wajib && !body.sebab.trim()) { pesan('Isi alasan barang tidak terkirim. Spasi kosong tidak dianggap alasan.'); return; }
    kunci(true);
    try {
      var j = await panggil('/api/actions/periksa-selesai-muat', 'POST', body);
      if (j.dasar !== body.dasar || !Array.isArray(j.barang) || j.perintah_id !== pilihan.pelanggan.id) throw Error('Ringkasan belum lengkap. Periksa muatan terbaru.');
      rencana = j; tahap = 'review'; galat.hidden = true; gambar();
    } catch (e) { pesan(e.message); rencana = null; if (e.status === 409) basi = true; }
    finally { kunci(false); }
  }
  async function simpan() {
    if (sibuk || !rencana || basi || tidakPasti || !boleh) return;
    kunci(true); galat.hidden = true;
    try {
      var j = await panggil('/api/actions/selesai-muat', 'POST', payload());
      if (j.ok !== true) throw Error('Balasan penyelesaian belum lengkap.');
      kabar.textContent = j.pesan || 'Muatan pelanggan selesai sesuai aktual.'; kabar.hidden = false;
      await terbaru(true);
    } catch (e) {
      tidakPasti = !e.status || e.status >= 500; basi = e.status === 409;
      pesan(tidakPasti ? 'Status penyelesaian belum dapat dipastikan. Alasan tetap tersedia. Periksa status muatan terbaru atau riwayat sebelum mengulang.' : e.message);
      rencana = null; tahap = 'form'; gambar();
    } finally { kunci(false); }
  }
  async function terbaru(tersimpan) {
    if (sibuk && !tersimpan) return;
    var id = pilihan ? pilihan.pelanggan.id : null;
    if (!tersimpan) kunci(true);
    try {
      var j = await panggil('/api/actions/papan-selesai-muat' + (root.dataset.perintah ? '?perintah=' + encodeURIComponent(root.dataset.perintah) : ''), 'GET');
      if (!Array.isArray(j.kiriman)) throw Error('Status muatan belum lengkap.');
      data = j; rencana = null; basi = false; tidakPasti = false; galat.hidden = true;
      pilihan = id == null ? null : cari(id); tahap = pilihan ? tertutup(pilihan.pelanggan) ? 'hasil' : 'form' : 'daftar';
      if (!tersimpan) { kabar.textContent = 'Muatan terbaru dimuat. Alasan tetap tersedia; baca rincian lalu periksa dan konfirmasi ulang.'; kabar.hidden = false; }
      gambar();
    } catch (e) {
      basi = true;
      pesan(tersimpan ? 'Penyelesaian sudah dikonfirmasi server, tetapi ringkasan belum dapat dimuat. Periksa status terbaru sebelum tindakan berikutnya.' : e.message);
    } finally { if (!tersimpan) kunci(false); }
  }
  refresh.onclick = function () { terbaru(false); };
  gambar();
  if (root.dataset.buka === '1' && root.dataset.perintah) buka(Number(root.dataset.perintah));
})();
