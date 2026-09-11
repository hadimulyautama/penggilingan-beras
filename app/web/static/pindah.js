/* Perpindahan halaman yang terasa seketika di jaringan yang jauh.
 *
 * Layanan ini berjalan di San Francisco; dari Indonesia satu perjalanan
 * pulang-pergi memakan ~270 ms sebelum sebutir piksel digambar. Kerja
 * servernya sendiri hanya ~20 ms — jadi yang dirasakan lambat itu jarak,
 * bukan beban. Menulis ulang aplikasinya tidak memindahkan Samudra Pasifik.
 *
 * Yang bisa dilakukan adalah tidak menunggu jarak itu pada saat orang
 * menekan. Halaman bertab disimpan di memori, ditampilkan seketika saat
 * ditekan, lalu diperbarui diam-diam setelah jawaban server datang. Pemilik
 * memilih pertukaran ini dengan sadar: "data agak lambat tidak apa-apa,
 * paling tidak perpindahan halaman responsif."
 *
 * Simpanannya di MEMORI, bukan di cakram atau service worker — ia lenyap
 * saat tab ditutup. Itu disengaja: halaman-halaman ini berisi angka milik
 * perusahaan dan menempel pada sesi orang yang sedang masuk; ia tak boleh
 * hidup lebih lama dari sesinya.
 */
(function () {
  "use strict";

  var simpan = {};        // alamat -> HTML utuh yang terakhir dilihat
  var sedang = {};        // alamat -> janji yang sedang berjalan (jangan dobel)
  var bingkai = null;
  var siapkan = null;     // pemanas simpanan, dipasang saat DOM siap

  /* Pendengar tingkat dokumen milik HALAMAN, bukan milik aplikasi.
     Skrip halaman dijalankan ulang tiap kali isinya ditukar; kalau
     pendengarnya dipasang langsung ke `document`, ia menumpuk sekali tiap
     perpindahan sampai satu ketukan dijalankan lima kali. Yang dipasang
     lewat sini dicabut lebih dulu pada perpindahan berikutnya.

     INI DIDEFINISIKAN LEBIH DULU, sebelum apa pun yang menyentuh DOM, dan
     berkasnya dimuat di <head>. Skrip halaman Laporan berjalan sebaris
     dengan isinya — jauh sebelum </body> — jadi kalau PINDAH baru ada di
     kaki halaman, layar Laporan mati sejak ketukan pertama. */
  var terpasang = [];
  window.PINDAH = {
    pasang: function (sasaran, jenis, fn) {
      sasaran.addEventListener(jenis, fn);
      terpasang.push([sasaran, jenis, fn]);
    },
    /* Dipanggil sesudah sesuatu tercatat. Mengosongkan saja tidak cukup:
       tanpa dipanaskan ulang, lima ketukan berikutnya kembali menunggu
       laut — tepat sesudah orangnya menyelesaikan satu pekerjaan dan
       hendak memeriksa hasilnya. */
    lupakan: function () {
      simpan = {};
      if (siapkan) { setTimeout(siapkan, 250); }
    },
    /* ── Gambar ulang layar yang sedang dibuka ──
       `lupakan` membuang simpanan, tetapi layar YANG SEDANG DILIHAT tidak
       ikut berubah — kartunya digambar server, bukan oleh skrip aksi. Jadi
       sesudah harga diverifikasi, kartunya tetap berdiri di layar sampai
       orangnya pergi lalu kembali. Layar yang masih menagih pekerjaan yang
       baru saja diselesaikan orang itu sendiri adalah cara tercepat membuat
       orang berhenti mempercayainya.

       `sesudah` dipanggil setelah isinya ditukar — di situlah tempat
       menampilkan ulang kabar "Tersimpan ✓", karena kabarnya ikut tersapu
       bersama isi lama. */
    segarkan: function (sesudah) {
      var alamat = location.pathname + location.search;
      delete simpan[alamat];
      if (!bingkai) { if (sesudah) { sesudah(); } return; }
      ambil(alamat).then(function (teks) {
        if (teks && location.pathname + location.search === alamat) {
          pasang(teks, alamat);
        }
        if (sesudah) { sesudah(); }
      });
    },

    /* ── Menyegarkan DIAM-DIAM ──
     *
     * Bedanya dengan `segarkan`: yang ini boleh MEMBATALKAN diri sendiri.
     * Ia berjalan tanpa diminta — saat aplikasi kembali ke depan, dan tiap
     * setengah menit — jadi ia harus tahu kapan tidak boleh mengganggu.
     *
     * Tiga keadaan yang membuatnya mundur:
     *   · ada lembar aksi terbuka — menukar isi di bawah borang yang sedang
     *     diisi berarti membuang ketikan orang;
     *   · ada kotak isian yang sedang dipegang — sama saja;
     *   · isinya ternyata tidak berubah — menukar HTML yang identik tetap
     *     menghapus posisi gulung dan menjalankan ulang skripnya.
     *
     * Posisi gulung dikembalikan. `pasang` menukar seluruh isi `.bingkai`,
     * jadi tanpa ini orang yang sedang membaca baris ke-20 dilempar kembali
     * ke atas tiap kali ada operator mencatat sesuatu — dan itu jauh lebih
     * mengganggu daripada angka yang telat.
     */
    diam: function () {
      var alamat = location.pathname + location.search;
      if (!bingkai) { return; }
      if (!bolehDiam()) { return; }

      var lama = bingkai.innerHTML;

      tanyaPenanda().then(function (p) {
        var sama = (p !== null && penanda !== null && p === penanda);
        if (p !== null) { penanda = p; }
        if (sama) { return; }        // tak ada yang berubah: berhenti di sini
        lanjutkan();
      });

      function lanjutkan() {
      delete simpan[alamat];
      ambil(alamat).then(function (teks) {
        if (!teks) { return; }
        if (location.pathname + location.search !== alamat) { return; }
        // Diperiksa LAGI: orangnya bisa mulai mengetik tepat selagi
        // permintaan ini masih di jalan.
        if (!bolehDiam()) { return; }

        var doc = new DOMParser().parseFromString(teks, "text/html");
        var isiBaru = doc.querySelector(".bingkai");
        if (!isiBaru || isiBaru.innerHTML === lama) { return; }

        var gulung = document.querySelector(".isi");
        var atas = gulung ? gulung.scrollTop : 0;
        if (!pasang(teks, alamat)) { return; }
        var g2 = document.querySelector(".isi");
        if (g2 && atas) { g2.scrollTop = atas; }
      });
      }
    }
  };
  function cabutSemua() {
    terpasang.forEach(function (p) { p[0].removeEventListener(p[1], p[2]); });
    terpasang = [];
  }

  if (!window.fetch || !window.history || !history.pushState) { return; }

  function bolehDitangani(a) {
    if (!a || !a.getAttribute) { return false; }
    var h = a.getAttribute("href");
    if (!h || h.charAt(0) === "#") { return false; }
    if (a.target || a.hasAttribute("download") || a.hasAttribute("data-utuh")) { return false; }
    return a.origin === location.origin;
  }

  /* ── Mengambil, dan hanya sekali untuk alamat yang sama ── */
  function ambil(alamat) {
    if (sedang[alamat]) { return sedang[alamat]; }
    var janji = fetch(alamat, {
      credentials: "same-origin",
      headers: { "X-Pindah": "1" }
    }).then(function (r) {
      /* Dialihkan ke halaman masuk, atau ditolak: serahkan pada peramban.
         Sesi yang habis harus terlihat sebagai sesi yang habis, bukan
         sebagai halaman kosong. */
      if (!r.ok || r.redirected) { return null; }
      return r.text();
    }).catch(function () {
      return null;              // jaringan putus — biarkan peramban mencoba
    }).then(function (teks) {
      delete sedang[alamat];
      if (teks) { simpan[alamat] = teks; }
      return teks;
    });
    sedang[alamat] = janji;
    return janji;
  }

  /* ── Memasang HTML yang sudah di tangan ── */
  function pasang(teks, alamat) {
    var doc = new DOMParser().parseFromString(teks, "text/html");
    var baru = doc.querySelector(".bingkai");
    if (!baru) { location.href = alamat; return false; }

    cabutSemua();
    disentuh = false;   // halamannya berganti — ketikan lamanya memang pergi
    document.title = doc.title || document.title;
    bingkai.innerHTML = baru.innerHTML;

    /* Skrip yang datang lewat innerHTML tidak dijalankan peramban —
       harus dibuatkan ulang elemennya. Tanpa ini layar Catat dan Laporan
       tampil utuh tetapi tak satu tombolnya hidup. */
    Array.prototype.forEach.call(bingkai.querySelectorAll("script"), function (lama) {
      var s = document.createElement("script");
      Array.prototype.forEach.call(lama.attributes, function (at) {
        s.setAttribute(at.name, at.value);
      });
      s.textContent = lama.textContent;
      lama.parentNode.replaceChild(s, lama);
    });
    angkatLembar();
    return true;
  }

  /* Lembar aksi/laporan ditulis DI DALAM `{% block isi %}`, jadi ia lahir di
     dalam `.isi` — satu-satunya bagian yang menggulung. Di Safari, elemen
     yang menggulung menjadi konteks penumpukan tersendiri, dan `z-index: 20`
     milik lembar terkurung di dalamnya: bilah navigasi tergambar DI ATAS
     lembar, menutupi tombol simpannya. Diangkat menjadi anak langsung
     `.bingkai`, ia bersaing sederajat dengan bilah dan selalu menang —
     tanpa bergantung pada tafsir peramban. `position: fixed` membuatnya
     keluar dari aliran, jadi ia tidak menjadi item flex di sana. */
  function angkatLembar() {
    if (!bingkai) { return; }
    var l = document.getElementById("lembar");
    if (l && l.parentNode !== bingkai) { bingkai.appendChild(l); }
  }

  /* ── Halaman yang sudah DISENTUH tak boleh digambar ulang ──
   *
   * Memeriksa "ada kotak yang sedang dipegang" saja TIDAK CUKUP, dan itu
   * terbukti: pemilik menanyakannya pada 11 September 2026, lalu diuji —
   * ketikan di borang Pengaturan HILANG, diganti nilai dari server.
   *
   * Urutan kejadiannya biasa saja. Orang mengetik namanya, lalu menggulir
   * ke bawah sebentar untuk melihat setelan lain; kotaknya kehilangan fokus.
   * Di detik itu orang lain mengubah sesuatu di halaman yang sama, isinya
   * jadi berbeda, dan penyegaran menukar seluruh isi bingkai.
   *
   * Lembar aksi memang sudah aman — `lembarTerbuka` menjaganya, dan di
   * sanalah hampir semua pencatatan terjadi. Yang bocor adalah borang BIASA:
   * Pengaturan, ganti sandi, kelola pengguna. Sedikit dipakai, tetapi yang
   * hilang di sana adalah ketikan orang yang tak pernah diberi tahu kenapa.
   *
   * Maka sekali sebuah halaman disentuh, ia tak lagi disegarkan otomatis
   * sampai orangnya pergi sendiri. Penandanya direset tiap `pasang`, karena
   * saat itu halamannya memang berganti. */
  var disentuh = false;

  /* ── Penanda keadaan: bertanya dulu, mengunduh belakangan ──
   *
   * Denyut ini dulu mengunduh SELURUH halaman (14–26 KB) hanya untuk
   * menyimpulkan "tak ada yang berubah" di hampir semua denyutnya. Sekitar
   * 17 MB kuota per perangkat per sif, dan operator memakai kuotanya sendiri.
   *
   * Sekarang yang ditanya lebih dulu satu penanda pendek. Halamannya baru
   * diambil kalau penandanya berbeda dari yang terakhir dilihat — dan karena
   * bertanya jadi murah, jaraknya bisa dirapatkan dari 30 detik ke 10.
   *
   * `null` berarti BELUM TAHU, dan itu diperlakukan sebagai "mungkin
   * berubah": halamannya tetap diambil. Keadaan itu terjadi tepat sesudah
   * aplikasi dibuka — dan di situlah justru yang paling mungkin basi, karena
   * telepon bisa saja sejam di dalam kantong. Menganggapnya "tak berubah"
   * berarti mengulang persis keluhan yang sedang diperbaiki.
   *
   * Gagal bertanya juga `null`: jaringan putus, atau sesi habis dan yang
   * datang halaman masuk, bukan JSON. Yang terakhir itu penting — kalau
   * pengalihan ke halaman masuk ditafsirkan sebagai "ada perubahan", layarnya
   * akan memuat ulang tanpa henti. */
  var penanda = null;

  function tanyaPenanda() {
    return fetch("/miniapp/keadaan", { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { return (j && j.n) ? String(j.n) : null; })
      .catch(function () { return null; });
  }

  function bolehDiam() {
    if (disentuh) { return false; }
    if (lembarTerbuka()) { return false; }
    var f = document.activeElement;
    if (f && /^(INPUT|SELECT|TEXTAREA)$/.test(f.tagName)) { return false; }
    return true;
  }

  document.addEventListener("input", function () { disentuh = true; }, true);
  document.addEventListener("change", function () { disentuh = true; }, true);

  function lembarTerbuka() {
    var l = document.getElementById("lembar");
    return !!(l && l.style.display === "flex");
  }

  /* ── Perpindahan ── */
  function pindah(alamat, dorong) {
    var tersimpan = simpan[alamat];

    if (tersimpan) {
      // Sudah di tangan: tampilkan sekarang juga, tanpa menyeberangi laut.
      if (!pasang(tersimpan, alamat)) { return; }
      if (dorong) { history.pushState({ pindah: 1 }, "", alamat); }
      // Lalu periksa diam-diam apakah sudah berubah.
      delete simpan[alamat];
      ambil(alamat).then(function (teks) {
        /* Hanya menyegarkan kalau orangnya masih di halaman itu, isinya
           memang berbeda, dan tak ada lembar terbuka. Menukar isi di bawah
           jari orang yang sedang membaca laporan lebih buruk daripada angka
           yang telat setengah detik. */
        if (!teks || teks === tersimpan) { return; }
        if (location.pathname + location.search !== alamat) { return; }
        if (lembarTerbuka()) { return; }
        pasang(teks, alamat);
      });
      return;
    }

    // Belum ada: tunggu, sambil menunjukkan bahwa sesuatu sedang berjalan.
    bingkai.classList.add("menunggu");
    ambil(alamat).then(function (teks) {
      bingkai.classList.remove("menunggu");
      if (!teks) { location.href = alamat; return; }
      if (!pasang(teks, alamat)) { return; }
      if (dorong) { history.pushState({ pindah: 1 }, "", alamat); }
    });
  }

  /* ── Menangkap ketukan ── */
  function mulai() {
  bingkai = document.querySelector(".bingkai");
  if (!bingkai) { return; }

  document.addEventListener("click", function (e) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) { return; }
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!bolehDitangani(a)) { return; }
    var alamat = a.pathname + a.search;
    if (alamat === location.pathname + location.search) { e.preventDefault(); return; }
    e.preventDefault();

    /* Tab yang ditekan menyala SEKARANG, bukan setelah halamannya datang.
       Tanpa ini ketukan terasa tidak terdaftar dan orang menekan dua kali. */
    var tab = a.classList.contains("bilah__tab") ? a : null;
    if (tab) {
      Array.prototype.forEach.call(
        document.querySelectorAll(".bilah__tab"), function (t) {
          t.classList.toggle("bilah__tab--aktif", t === tab);
        });
    }
    pindah(alamat, true);
  });

  /* Mulai mengambil saat jari MENYENTUH, bukan saat diangkat. Jeda antara
     sentuh dan angkat 80–150 ms — itu potongan gratis dari waktu tunggu. */
  function dahului(e) {
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!bolehDitangani(a)) { return; }
    var alamat = a.pathname + a.search;
    if (!simpan[alamat] && !sedang[alamat]) { ambil(alamat); }
  }
  document.addEventListener("touchstart", dahului, { passive: true });
  document.addEventListener("mouseover", dahului);

  window.addEventListener("popstate", function () {
    pindah(location.pathname + location.search, false);
  });

  /* Empat tab lain diambil saat aplikasi sedang diam, supaya ketukan
     pertama ke masing-masingnya pun sudah tidak menunggu. Halamannya kecil
     dan servernya hanya butuh ~20 ms; yang mahal cuma jaraknya, dan jarak
     itu dibayar di sini, bukan saat orang menunggu. */
  function siapkanTab() {
    Array.prototype.forEach.call(
      document.querySelectorAll(".bilah__tab"), function (t) {
        var alamat = t.pathname + t.search;
        if (alamat !== location.pathname + location.search && !simpan[alamat]) {
          ambil(alamat);
        }
      });
  }
  angkatLembar();
  siapkan = siapkanTab;
  if (window.requestIdleCallback) {
    requestIdleCallback(siapkanTab, { timeout: 2500 });
  } else {
    setTimeout(siapkanTab, 1200);
  }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mulai);
  } else {
    mulai();
  }

  /* ── Layar yang tidak pernah berubah sendiri ──
   *
   * Masalah yang dilaporkan pemilik pada 10 September 2026: operator mencatat
   * sesuatu dari HP-nya, dan di layar pemilik tak terjadi apa-apa. Ia harus
   * MEMATIKAN aplikasinya dulu, lalu membukanya lagi, baru perubahannya
   * terlihat.
   *
   * Sebabnya bukan cache yang basi — `pindah` sudah memeriksa ulang tiap kali
   * orang berpindah layar. Sebabnya lebih sederhana dan lebih buruk: TAK ADA
   * SATU PUN pemicu penyegaran. Halaman digambar sekali saat dibuka, lalu
   * diam selamanya. Aplikasi terpasang di layar utama tak pernah dimuat ulang
   * saat dibuka kembali dari latar belakang — ia melanjutkan DOM yang sama —
   * jadi satu-satunya cara memaksanya adalah mematikan aplikasinya.
   *
   * Layar pabrik yang menunjukkan keadaan setengah jam lalu tanpa memberi
   * tahu bahwa ia basi lebih buruk daripada layar yang kosong: yang kosong
   * membuat orang bertanya, yang basi membuat orang yakin.
   *
   * Dua pemicu, dan keduanya perlu:
   *   · KEMBALI KE DEPAN — inilah yang menjawab keluhannya. Telepon dikantongi,
   *     dikeluarkan lagi, dan yang pertama dilihat orang harus keadaan
   *     sekarang, bukan keadaan saat ia mengantonginya.
   *   · DENYUT tiap setengah menit — untuk telepon yang tergeletak menyala di
   *     meja, atau layar yang dipasang di dinding. Hanya berdetak saat halaman
   *     TERLIHAT; yang di latar belakang tak menghabiskan baterai maupun kuota.
   */
  var denyut = null;

  function mulaiDenyut() {
    if (denyut) { return; }
    denyut = setInterval(function () {
      if (document.visibilityState === "visible") { window.PINDAH.diam(); }
    }, 10000);
  }

  function hentikanDenyut() {
    if (denyut) { clearInterval(denyut); denyut = null; }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      window.PINDAH.diam();
      mulaiDenyut();
    } else {
      hentikanDenyut();
    }
  });

  /* Sebagian peramban mengembalikan halaman dari simpanan maju-mundurnya
     tanpa memicu `visibilitychange` sama sekali. */
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) { window.PINDAH.diam(); }
  });

  if (document.visibilityState === "visible") { mulaiDenyut(); }
})();
