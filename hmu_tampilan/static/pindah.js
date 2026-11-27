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
  var gagal = {};         // hanya membedakan putus jaringan dari pengalihan sesi
  var bingkai = null;
  var siapkan = null;     // pemanas simpanan, dipasang saat DOM siap
  var penyediaKerangkaLangsung = null; // opt-in presentasi, bawaan tidak memasang apa pun
  var pembacaRiwayat = null; // opt-in baca panel; dialog native selalu didahulukan
  var pilihKerangkaHalaman = null; // aplikasi memilih sendiri; bawaan tetap native
  var nomorPindah = 0, tujuanPindah = null, nomorSentuhan = 0;
  var dataMenunggu = null, pointerAktif = false;
  var navigasiMenunggu = null, pesanNavigasi = null;
  document.addEventListener("pointerdown", function () { nomorSentuhan++; pointerAktif = true; }, true);
  function lepasPointer() { pointerAktif = false; setTimeout(pasangMenunggu, 0); }
  document.addEventListener('pointerup', lepasPointer, true);
  document.addEventListener('pointercancel', lepasPointer, true);
  document.addEventListener('click', function () { setTimeout(pasangMenunggu, 0); });
  document.addEventListener('keyup', function () { setTimeout(pasangMenunggu, 0); });
  document.addEventListener("keydown", function () { nomorSentuhan++; }, true);

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
    aturPembacaRiwayat: function (pembaca) {
      if (pembaca !== null && typeof pembaca !== "function") throw new TypeError("Pembaca riwayat harus fungsi atau null.");
      pembacaRiwayat = pembaca;
    },
    // Kemampuan presentasi saja. Tidak mengganti penjaga editor atau izin server.
    aturKerangkaHalaman: function (pilih) {
      if (pilih !== null && typeof pilih !== "function") {
        throw new TypeError("Pemilih kerangka harus fungsi atau null.");
      }
      pilihKerangkaHalaman = pilih;
    },
    // Dokumen baru sudah dirender aplikasi dengan konteks native saat ini.
    // Provider tidak membaca jaringan, izin, data transaksi, atau DOM layar lama.
    aturKerangkaLangsung: function (penyedia) {
      if (penyedia !== null && typeof penyedia !== "function") {
        throw new TypeError("Penyedia kerangka langsung harus fungsi atau null.");
      }
      penyediaKerangkaLangsung = penyedia;
    },
    selaraskanChrome: function (doc) {
      if (!chromeSama(doc)) return false;
      selaraskanChrome(doc);
      // Hydration juga menyelesaikan pembacaan route yang sama. Penanda
      // target ikut native, tanpa mengadopsi konteks atau sesi yang baru.
      var lama = document.querySelector(".bingkai"), baru = doc.querySelector(".bingkai");
      ["data-pindah-alamat", "data-pindah-kerangka"].forEach(function (nama) {
        if (baru.hasAttribute(nama)) lama.setAttribute(nama, baru.getAttribute(nama));
        else lama.removeAttribute(nama);
      });
      return true;
    },
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
      var generasi = nomorPindah;
      delete simpan[alamat];
      if (!bingkai) { if (sesudah) { sesudah(); } return; }
      ambil(alamat).then(function (teks) {
        if (teks && generasi === nomorPindah && location.pathname + location.search === alamat) {
          pasang(teks, alamat);
        }
        if (sesudah) { sesudah(); }
      });
    },

    /* ── Melepas bendera "sedang mengetik" ──
     *
     * Bendera itu menahan segar-otomatis supaya ketikan yang belum tersimpan
     * tak hilang, dan sampai 11 September 2026 ia hanya dilepas saat halaman
     * BERPINDAH. Jadi sesudah menyentuh satu isian lalu menekan Batal,
     * segar-otomatis mati diam-diam sampai orangnya kebetulan pindah halaman:
     * sepuluh denyut menghasilkan nol permintaan, dan layarnya makin lama
     * makin basi tanpa satu tanda pun. Temuan QA P-K-19.
     *
     * Dipanggil `aksi.js` saat lembar ditutup — di sanalah ketikan yang
     * ditahan itu benar-benar berhenti ada.
     */
    lupakanSentuhan: function () { disentuh = false; },

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
      if (!bingkai) { return; }
      /* Penanda TETAP ditanya walau orangnya sedang mengetik: yang tak boleh
         adalah menukar isi layar, bukan mengetahui sinyalnya putus. Dan
         sejak Tahap C, isinya memang TIDAK PERNAH ditukar diam-diam: bila
         berubah, pil "perubahan baru" yang muncul — orangnya yang memutuskan
         kapan tata letak bergerak. */
      if (perluSegar && (bolehDiam() || pembacaEditor())) muatPerubahan();
      statistik.tanya++;
      tanyaPenanda().then(terimaPenanda);
    },
    /* Ketukan pil: tukar isi SEKARANG, atas permintaan orangnya. */
    muatPerubahan: function () { muatPerubahan(); },
    jalur: function () { return jalur; },
    statistik: function () {
      return { tanya: statistik.tanya, dorongan: statistik.dorongan, perubahan: jumlahPerubahan };
    }
  };
  function cabutSemua() {
    pembacaRiwayat = null;
    terpasang.forEach(function (p) { p[0].removeEventListener(p[1], p[2]); });
    terpasang = [];
  }

  if (!window.fetch || !window.history || !history.pushState) { return; }

  // Hanya editor yang mengumumkan kesiapan baca secara eksplisit boleh ikut.
  // SDK tidak menebak draf, kunci pending, atau aturan transaksi dari markup.
  function editorBolehPindah() {
    if (document.querySelector("[data-kemas-ulang]")) return false;
    return Array.prototype.every.call(document.querySelectorAll("[data-editor-perintah]"), function (el) {
      try { return typeof el.pfCanNavigateRead === "function" && el.pfCanNavigateRead() === true; }
      catch (_) { return false; }
    });
  }

  // Izin tautan tetap berasal dari navigasi yang dirender server, bukan
  // awalan URL bebas. data-utuh tetap menjadi fallback untuk SDK lama.
  function daftarRiwayatBaca(path) {
    return ["/riwayat-sosoh", "/riwayat-giling", "/riwayat-pengeringan",
      "/riwayat-qc/gabah-basah", "/riwayat-qc/gabah-kering", "/riwayat-qc/pk-hasil-giling",
      "/riwayat-qc/pk-luar", "/riwayat-qc/beras-hasil-sosoh", "/audit", "/laporan"].indexOf(path) !== -1;
  }

  function tautanRiwayatBaca(a) {
    if (!a || !a.matches("[data-pindah-riwayat]")) return false;
    var root = a.closest("[data-laporan-kontrol]");
    if (!root || a.origin !== location.origin || a.search || a.hash || !daftarRiwayatBaca(a.pathname)) return false;
    try {
      var allowed = JSON.parse(root.dataset.bolehAlamat || "[]");
      var tabs = JSON.parse(root.dataset.tujuanTab || "[]");
      var strings = function (xs) { return Array.isArray(xs) && xs.every(function (x) { return typeof x === "string"; }); };
      if (!strings(allowed) || !Array.isArray(tabs)) return false;
      for (var i = 0; i < tabs.length; i++) {
        var tab = tabs[i];
        if (!tab || typeof tab !== "object") return false;
        if (tab.boleh === true) {
          if (!strings(tab.alamat)) return false;
          allowed = allowed.concat(tab.alamat);
        }
      }
      return allowed.indexOf(a.pathname) !== -1;
    } catch (_) { return false; }
  }

  function aliasRiwayat(alamat) {
    var u = new URL(alamat, location.href);
    return u.origin === location.origin && !u.hash && (u.pathname === "/riwayat" || u.pathname === "/laporan-riwayat");
  }

  function bolehDitangani(a) {
    // Editor memakai navigasi utuh agar beforeunload menjaga draf gagal simpan.
    if (!editorBolehPindah()) { return false; }
    if (!a || !a.getAttribute) { return false; }
    var h = a.getAttribute("href");
    if (!h || h.charAt(0) === "#") { return false; }
    if (a.hash || /\.(pdf|csv)$/i.test(a.pathname)) { return false; }
    if (a.target || a.hasAttribute("download") || (a.hasAttribute("data-utuh") && !tautanRiwayatBaca(a))) { return false; }
    return a.origin === location.origin;
  }

  function memakaiKerangkaHalaman(alamat) {
    if (!pilihKerangkaHalaman) { return false; }
    try { return pilihKerangkaHalaman(alamat) === true; }
    catch (e) { return false; } // kontrak opt-in gagal: jalur native tetap ada
  }

  function rencanaKerangkaLangsung(alamat, dorong) {
    if (!penyediaKerangkaLangsung || !editorBolehPindah()) return null;
    try {
      var hasil = penyediaKerangkaLangsung({ alamat: alamat, sebab: dorong ? "push" : "pop" });
      var kini = document.querySelector(".bingkai"), sesi = document.getElementById("formulir-sesi");
      var cap = document.documentElement.getAttribute("data-versi") || "";
      if (!hasil || hasil.versi !== 1 || hasil.alamat !== alamat || typeof hasil.html !== "string" || hasil.html.length > 524288
          || !cap || hasil.cap !== cap || !kini || !sesi || !sesi.dataset.token
          || !hasil.konteks || hasil.konteks !== kini.dataset.pindahKonteks) return null;
      var tujuan = new URL(alamat, location.href);
      if (tujuan.origin !== location.origin || tujuan.hash || tujuan.pathname + tujuan.search !== alamat) return null;
      var doc = new DOMParser().parseFromString(hasil.html, "text/html");
      var frame = doc.querySelector(".bingkai"), isi = doc.getElementById("isi-halaman"), sesiBaru = doc.getElementById("formulir-sesi");
      if (doc.querySelectorAll(".bingkai").length !== 1 || doc.querySelectorAll("#isi-halaman").length !== 1
          || !frame || !isi || !frame.contains(isi) || !sesiBaru || !frame.contains(sesiBaru)
          || doc.querySelectorAll("#formulir-sesi").length !== 1 || sesiBaru.dataset.token !== sesi.dataset.token
          || doc.documentElement.getAttribute("data-versi") !== cap
          || frame.dataset.pindahKonteks !== hasil.konteks || frame.dataset.pindahAlamat !== alamat
          || frame.dataset.pindahKerangka !== "1" || frame.querySelector(".halaman-memuat")
          || !isi.querySelector("h1,section[aria-label],[role=region][aria-label]")) return null;
      var tanda = Array.prototype.filter.call(isi.childNodes, function (n) { return n.nodeType === 8; });
      var awal = tanda.findIndex(function (n) { return n.data.trim() === "isi-halaman:mulai"; });
      var akhir = tanda.findIndex(function (n) { return n.data.trim() === "isi-halaman:akhir"; });
      if (awal < 0 || akhir <= awal) return null;
      return hasil;
    } catch (e) { return null; } // gagal presentasi tidak boleh membuka target lain
  }

  function kunciBaca(alamat, kerangkaHalaman, tanpaSimpan) {
    if (tanpaSimpan) return "native:" + alamat;
    return kerangkaHalaman ? "kerangka:" + alamat : alamat;
  }

  /* Kerangka foreground tidak berbagi janji/cache HTML dengan pembaca data. */
  function ambil(alamat, kerangkaHalaman, tanpaSimpan, denganAlamat) {
    var kunci = (denganAlamat ? "alias:" : "") + kunciBaca(alamat, kerangkaHalaman, tanpaSimpan);
    if (sedang[kunci]) { return sedang[kunci]; }
    delete gagal[kunci];
    var bolehSimpan = !kerangkaHalaman && !tanpaSimpan;
    var batas = new AbortController();
    var pewaktu = setTimeout(function () { batas.abort(); }, 15000);
    var janji = fetch(alamat, {
      credentials: "same-origin",
      cache: "no-store",
      signal: batas.signal,
      headers: kerangkaHalaman
        ? { "X-Pindah": "1", "X-Kerangka-Halaman": "1" }
        : { "X-Pindah": "1" }
    }).then(function (r) {
      /* Detail stok dapat habis sesudah kartunya dilihat. Halaman pemulihan
         404 yang ditandai server tetap boleh dipasang, agar refresh setelah
         simpan mengganti kartu lama dan navigasi tidak jatuh ke JSON mentah.
         Galat tidak disimpan: kunjungan berikutnya harus bertanya lagi.
         Redirect sesi, JSON API, dan galat tanpa penanda tetap memakai
         penjagaan navigasi utuh yang semula. */
      var pulih = r.status === 404 && r.headers.get("X-Pindah-Halaman") === "1"
        && (r.headers.get("Content-Type") || "").split(";")[0].trim() === "text/html";
      var kanonik = alamat;
      if (denganAlamat) {
        // Alamat menempel pada hasil yang sama, sehingga dua klik/response
        // berlomba tidak dapat memasangkan HTML dengan URL milik respons lain.
        var akhir = new URL(r.url, location.href);
        if (!aliasRiwayat(alamat) || akhir.origin !== location.origin || akhir.hash
            || !daftarRiwayatBaca(akhir.pathname) || r.status !== 200
            || (r.headers.get("Content-Type") || "").split(";")[0].trim() !== "text/html") return null;
        kanonik = akhir.pathname + akhir.search;
      }
      if ((r.redirected && !denganAlamat) || (!r.ok && !pulih)) {
        if (!r.redirected && r.status >= 500) gagal[kunci] = true;
        return null;
      }
      if (pulih) { bolehSimpan = false; delete simpan[alamat]; }
      return r.text().then(function (teks) { return denganAlamat ? { teks: teks, alamat: kanonik } : teks; });
    }).catch(function () {
      gagal[kunci] = true;
      return null;              // jaringan putus — biarkan peramban mencoba
    }).then(function (teks) {
      clearTimeout(pewaktu);
      delete sedang[kunci];
      if (teks && bolehSimpan) { simpan[alamat] = teks; }
      var daftarKunci = Object.keys(simpan);
      if (daftarKunci.length > 20) { delete simpan[daftarKunci[0]]; }
      return teks;
    });
    sedang[kunci] = janji;
    return janji;
  }

  function batasIsi(doc) {
    var main = doc.getElementById("isi-halaman");
    if (!main) return null;
    var nodes = Array.prototype.slice.call(main.childNodes);
    var awal = nodes.filter(function (n) { return n.nodeType === 8 && n.data.trim() === "isi-halaman:mulai"; });
    var akhir = nodes.filter(function (n) { return n.nodeType === 8 && n.data.trim() === "isi-halaman:akhir"; });
    if (awal.length !== 1 || akhir.length !== 1 || nodes.indexOf(awal[0]) >= nodes.indexOf(akhir[0])) return null;
    return { main: main, awal: awal[0], akhir: akhir[0] };
  }

  // Konteks Kembali Jasa hanya presentasi. Normalisasi dibatasi pada
  // Ringkasan tujuan yang persis sama, bukan pengecualian halaman asal.
  function alamatRingkasanJasa(doc) {
    var raw = doc.querySelector(".bingkai")?.dataset.pindahAlamat;
    if (typeof raw !== "string" || raw.length > 4096 || raw.charAt(0) !== "/" || raw.indexOf("\\") !== -1) return null;
    try {
      var u = new URL(raw, location.origin);
      var keys = ["tab", "status", "cari", "halaman", "pesanan_halaman", "pesanan_cari", "pesanan_status"];
      if (u.origin !== location.origin || u.hash || !/^\/jasa\/pelanggan\/[1-9]\d{0,9}$/.test(u.pathname)
          || Number(u.pathname.split("/").pop()) > 2147483647 || (u.searchParams.get("tab") || "ringkasan") !== "ringkasan"
          || Array.from(u.searchParams.keys()).some(function (k) { return keys.indexOf(k) < 0 || u.searchParams.getAll(k).length !== 1 || u.searchParams.get(k).length > 200; })) return null;
      return u.pathname + u.search;
    } catch (_) { return null; }
  }

  function rapikanRujukanJasa(salin, tujuan) {
    if (!tujuan || !salin.matches(".desktop-chrome__shortcuts")) return;
    salin.querySelectorAll("a[href]").forEach(function (a) {
      try {
        var u = new URL(a.getAttribute("href"), location.origin);
        var kembali = u.searchParams.getAll("kembali_jasa");
        if (u.origin !== location.origin || u.hash || kembali.length !== 1 || kembali[0] !== tujuan) return;
        u.searchParams.delete("kembali_jasa");
        a.setAttribute("href", u.pathname + u.search);
      } catch (_) {} // rujukan tak cocok tetap berbeda dan memakai jalur native
    });
  }

  // Abaikan hanya penanda presentasi yang memang berubah per halaman.
  // Identitas, tautan berizin, formulir dan kontrol lain harus tetap persis.
  function sidikChrome(el, kembaliJasa) {
    if (!el) return null;
    var salin = el.cloneNode(true);
    rapikanRujukanJasa(salin, kembaliJasa);
    salin.querySelectorAll(".pintu__jml").forEach(function (n) { n.remove(); });
    [salin].concat(Array.prototype.slice.call(salin.querySelectorAll("*"))).forEach(function (n) {
      ["aria-current", "open"].forEach(function (a) { n.removeAttribute(a); });
      n.classList.remove("pintu--kini", "pintu-sub__satu--kini");
      if (!n.getAttribute("class")) n.removeAttribute("class");
    });
    if (salin.id === "laci") {
      // Hanya pintu Riwayat yang ditandai server boleh mengingat daftar
      // terakhir. Jangan menyamakan perubahan tautan lain dengan bookmark:
      // perubahan izin, tujuan tak dikenal, dan markup lama tetap native.
      var riwayat = salin.querySelectorAll("[data-pindah-menu]");
      var daftarRiwayat = ["/riwayat", "/riwayat-sosoh", "/riwayat-giling", "/riwayat-pengeringan",
        "/riwayat-qc/gabah-basah", "/riwayat-qc/gabah-kering", "/riwayat-qc/pk-hasil-giling",
        "/riwayat-qc/pk-luar", "/riwayat-qc/beras-hasil-sosoh", "/audit"];
      if (riwayat.length !== 1 || !riwayat[0].matches('a.pintu[data-pindah-menu="laporan_riwayat"]')
          || daftarRiwayat.indexOf(riwayat[0].getAttribute("href")) < 0) return null;
      riwayat[0].setAttribute("href", "/riwayat");
      salin.removeAttribute("hidden");
      var ukur = salin.querySelector(".laci__ukur");
      if (ukur) ukur.removeAttribute("aria-valuenow");
    }
    // Jinja dapat memberi lekukan berbeda ketika lencana tidak dirender.
    function rapikan(n) {
      Array.prototype.slice.call(n.childNodes).forEach(function (anak) {
        if (anak.nodeType === 3 && !anak.textContent.trim()) anak.remove();
        else if (anak.nodeType === 1) rapikan(anak);
      });
    }
    rapikan(salin);
    return salin.outerHTML;
  }

  function chromeSama(doc) {
    var lama = document.querySelector(".bingkai"), baru = doc.querySelector(".bingkai");
    var sesi = document.getElementById("formulir-sesi"), sesiBaru = doc.getElementById("formulir-sesi");
    var cap = document.documentElement.getAttribute("data-versi");
    if (!cap || doc.documentElement.getAttribute("data-versi") !== cap || !lama || !baru
        || !lama.dataset.pindahKonteks || lama.dataset.pindahKonteks !== baru.dataset.pindahKonteks
        || !sesi || !sesiBaru || !sesi.dataset.token || sesi.dataset.token !== sesiBaru.dataset.token
        || sesi.outerHTML !== sesiBaru.outerHTML || document.body.className !== doc.body.className
        || !batasIsi(document) || !batasIsi(doc)) return false;
    var wajib = ["#laci", "header.bar", ".desktop-chrome", "#buka-laci", ".bar__balik", ".bar__merek", ".desktop-chrome__crumbrow"];
    if (wajib.some(function (q) { return document.querySelectorAll(q).length !== 1 || doc.querySelectorAll(q).length !== 1; })) return false;
    var laciLama = sidikChrome(document.getElementById("laci")), laciBaru = sidikChrome(doc.getElementById("laci"));
    if (!laciLama || !laciBaru || laciLama !== laciBaru) return false;
    // Pita sesi/penyamaran dan pintu cepat juga merupakan batas konteks.
    var luar = function (frame) {
      return Array.prototype.filter.call(frame.children, function (n) {
        return n.id !== "isi-halaman" && n.id !== "laci" && n.id !== "formulir-sesi" && n.id !== "lembar" && n.tagName !== "SCRIPT";
      }).map(function (n) { return n.outerHTML; }).join("");
    };
    if (luar(lama) !== luar(baru)) return false;
    var kembaliJasa = alamatRingkasanJasa(doc);
    return sidikChrome(document.querySelector(".desktop-chrome__shortcuts"), kembaliJasa) === sidikChrome(doc.querySelector(".desktop-chrome__shortcuts"), kembaliJasa);
  }

  function selaraskanChrome(doc) {
    ["#buka-laci", ".bar__balik"].forEach(function (q) {
      var a = document.querySelector(q), b = doc.querySelector(q);
      ["href", "hidden", "style", "aria-label"].forEach(function (nama) {
        if (b.hasAttribute(nama)) a.setAttribute(nama, b.getAttribute(nama)); else a.removeAttribute(nama);
      });
    });
    var merek = document.querySelector(".bar__merek"), baru = doc.querySelector(".bar__merek");
    merek.textContent = baru.textContent; merek.setAttribute("aria-label", baru.getAttribute("aria-label") || "");
    document.querySelector(".desktop-chrome__crumbrow").innerHTML = doc.querySelector(".desktop-chrome__crumbrow").innerHTML;
    var balik = document.querySelector('.desktop-theme input[name="balik"]'), balikBaru = doc.querySelector('.desktop-theme input[name="balik"]');
    if (balik && balikBaru) balik.value = balikBaru.value;
    var menu = document.getElementById("laci").querySelectorAll(".pintu,.pintu-sub__satu");
    var menuBaru = doc.getElementById("laci").querySelectorAll(".pintu,.pintu-sub__satu");
    Array.prototype.forEach.call(menu, function (n, i) {
      ["class", "aria-current"].forEach(function (a) {
        if (menuBaru[i].hasAttribute(a)) n.setAttribute(a, menuBaru[i].getAttribute(a)); else n.removeAttribute(a);
      });
      if (menuBaru[i].parentElement && menuBaru[i].parentElement.tagName === "DETAILS" && menuBaru[i].parentElement.open
          && n.parentElement && n.parentElement.tagName === "DETAILS") n.parentElement.open = true;
      n.querySelectorAll(".pintu__jml").forEach(function (badge) { badge.remove(); });
      menuBaru[i].querySelectorAll(".pintu__jml").forEach(function (badge) { n.appendChild(badge.cloneNode(true)); });
    });
    if (alamatRingkasanJasa(doc)) {
      // Guard sudah membuktikan node/izin/tujuan dasar identik. Perbarui
      // href saja agar konteks pelanggan lama tidak melekat pada tujuan baru.
      var cepat = document.querySelectorAll(".desktop-chrome__shortcuts a[href]");
      doc.querySelectorAll(".desktop-chrome__shortcuts a[href]").forEach(function (a, i) {
        cepat[i].setAttribute("href", a.getAttribute("href"));
      });
    }
    document.title = doc.title || document.title;
  }

  /* ── Memasang HTML yang sudah di tangan ── */
  function pasang(teks, alamat, halus, resetScroll) {
    var doc = new DOMParser().parseFromString(teks, "text/html");
    var baru = doc.querySelector(".bingkai");
    if (!baru || !chromeSama(doc)) { location.href = alamat; return false; }

    cabutSemua();
    disentuh = false;   // halamannya berganti — ketikan lamanya memang pergi
    /* Perpindahan dibungkus view transition DALAM dokumen (ketukan tak pernah
       jadi navigasi peramban, jadi aturan CSS @view-transition tak berlaku
       di sini). Hanya untuk PERPINDAHAN yang diketuk orang — penyegaran
       diam-diam tak boleh menggerakkan layar di bawah jari. Tanpa dukungan,
       jalurnya persis seperti sebelumnya. */
    if (halus && document.startViewTransition) {
      var generasi = nomorPindah;
      var transisi = document.startViewTransition(function () {
        if (generasi === nomorPindah) { tukar(doc, baru, resetScroll); }
      });
      // Ketukan berikutnya boleh melewati animasi yang masih berjalan.
      // `ready` ditolak saat animasi dilewati; pemasangan halaman tetap jalan.
      transisi.ready.catch(function () {});
    } else {
      tukar(doc, baru, resetScroll);
    }
    return true;
  }

  function tukar(doc, baru, resetScroll) {
    // CSS khusus detail harus ikut saat navigasi parsial. Sebelumnya hanya
    // isi body yang ditukar: detail yang dibuka lewat sidebar/kartu dapat
    // kehilangan gaya, meskipun reload langsung terlihat benar.
    Array.prototype.forEach.call(doc.querySelectorAll('head link[rel="stylesheet"][href]'), function (link) {
      var ada = Array.prototype.some.call(document.querySelectorAll('head link[rel="stylesheet"][href]'), function (lama) {
        return lama.getAttribute('href') === link.getAttribute('href');
      });
      if (!ada) { document.head.appendChild(link.cloneNode(true)); }
    });
    selaraskanChrome(doc);
    // Bingkai luar dipertahankan native. Marker konteks harus ikut dokumen
    // baru, agar registry lama tidak hidup melewati perubahan sesi/otoritas.
    ["data-pindah-konteks", "data-pindah-alamat", "data-pindah-kerangka"].forEach(function (nama) {
      if (baru.hasAttribute(nama)) bingkai.setAttribute(nama, baru.getAttribute(nama));
      else bingkai.removeAttribute(nama);
    });
    var batas = batasIsi(document), sumber = batasIsi(doc);
    var lembar = document.getElementById("lembar");
    if (lembar && lembar.parentNode === bingkai) lembar.remove();
    while (batas.awal.nextSibling !== batas.akhir) batas.awal.nextSibling.remove();
    var skrip = [];
    while (sumber.awal.nextSibling !== sumber.akhir) {
      var node = sumber.awal.nextSibling;
      if (node.nodeType === 1) {
        if (node.tagName === "SCRIPT") skrip.push(node);
        Array.prototype.push.apply(skrip, node.querySelectorAll("script"));
      }
      batas.main.insertBefore(node, batas.akhir);
    }
    // Hanya navigasi push biasa mulai di atas. Pop/refresh tetap memberi
    // ruang kepada pemulih posisi halaman native, sebelum skripnya berjalan.
    if (resetScroll === true) batas.main.scrollTop = 0;
    tandaiSegar();
    // Isi yang baru dipasang adalah keadaan sekarang: hitungan pil dimulai
    // dari nol, dan penanda berikutnya menjadi titik acuan baru.
    hapusPilPerubahan();
    penanda = null;

    /* Skrip yang datang lewat innerHTML tidak dijalankan peramban —
       harus dibuatkan ulang elemennya. Tanpa ini layar Catat dan Laporan
       tampil utuh tetapi tak satu tombolnya hidup. */
    skrip.forEach(function (lama) {
      var s = document.createElement("script");
      Array.prototype.forEach.call(lama.attributes, function (at) {
        s.setAttribute(at.name, at.value);
      });
      s.textContent = lama.textContent;
      if (s.src) { s.async = false; }
      lama.parentNode.replaceChild(s, lama);
    });
    angkatLembar();
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

  /* VERSI yang sedang berjalan di ponsel ini — dibaca dari <html data-versi>,
     yang ditulis server saat halaman UTUH terakhir dimuat. Sesudah itu
     perpindahan terjadi di dalam dokumen (bingkai ditukar), jadi angka ini
     bisa bertahan berhari-hari pada app yang terpasang di layar utama. */
  var VERSI_JALAN = document.documentElement.getAttribute("data-versi") || "";

  function tanyaPenanda() {
    return fetch("/api/keadaan", { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { tandaiPutus(false); return r.ok ? r.json() : null; })
      .then(function (j) { return (j && j.n) ? j : null; })
      .catch(function () { tandaiPutus(true); return null; });
  }

  /* ── Satu pintu untuk penanda, dari kanal mana pun ──
   *
   * `null` berarti BELUM TAHU (baru dibuka, atau gagal bertanya) — jangan
   * dihitung sebagai perubahan. Perubahan sungguhan menambah hitungan pil;
   * layarnya sendiri tak disentuh sampai pil diketuk. Satu-satunya
   * pengecualian: layar tanpa sasaran ketukan (`data-segar-sendiri`, papan
   * pantau) boleh menyegar sendiri — tak ada jari yang bisa mendarat salah. */
  var jumlahPerubahan = 0, perluSegar = false, sedangSegar = false;
  var statistik = { tanya: 0, dorongan: 0 };

  function terimaPenanda(j) {
    if (!j) { return; }
    var n = String(j.n);
    tandaiSegar();
    if (j.versi && VERSI_JALAN && String(j.versi) !== VERSI_JALAN) { tawarkanVersi(j.versi); }
    if (penanda !== null && n !== penanda) perluSegar = true;
    if (perluSegar && (bolehDiam() || pembacaEditor())) muatPerubahan();
    penanda = n;
  }

  function tawarkanPerubahan() { perluSegar = true; if (bolehDiam()) muatPerubahan(); }

  function hapusPilPerubahan() {
    var pil = document.querySelector(".pil-perubahan");
    if (pil) { pil.remove(); }
    jumlahPerubahan = 0;
  }

  function pembacaEditor() { var editor=document.querySelector('[data-editor-perintah]'); return editor && typeof editor.pfReadRefresh==='function' ? editor : null; }
  function muatPerubahan() {
    if (tujuanPindah !== null) return;
    var editor=pembacaEditor();
    if(editor){ if(sedangSegar||document.visibilityState!=='visible')return; sedangSegar=true; Promise.resolve(editor.pfReadRefresh()).then(function(ok){if(ok)perluSegar=false;}).finally(function(){sedangSegar=false;});return; }
    if (sedangSegar || !bolehDiam() || document.querySelector("[data-editor-perintah],[data-kemas-ulang]")) return;
    var alamat = location.pathname + location.search, generasi = nomorPindah;
    if (!bingkai) return;
    sedangSegar = true;
    delete simpan[alamat];
    ambil(alamat).then(function (teks) {
      if (!teks || location.pathname + location.search !== alamat || generasi !== nomorPindah || !bolehDiam()) return;
      var keadaan = window.KEADAAN_BACA && KEADAAN_BACA.ambil(bingkai);
      if (!pasang(teks, alamat)) return;
      if (keadaan) KEADAAN_BACA.pulihkan(bingkai, keadaan);
      perluSegar = false;
    }).finally(function () { sedangSegar = false; });
  }

  /* ── Kanal dorong (SSE) — jalur pertama; denyut 10 detik jadi jalur kedua ──
   *
   * Railway bisa memutus sambungan panjang: saat putus, denyut mengambil
   * alih dan sambungan dicoba lagi dengan jeda menaik (1 → 30 detik). Tidak
   * menyambung saat halaman tak terlihat — tak ada gunanya menahan sambungan
   * untuk layar di dalam kantong. */
  var jalur = "denyut";
  var aliran = null;
  var jedaSambung = 1000;
  var sambungUlang = null;

  function sambungAliran() {
    if (aliran || !window.EventSource || document.visibilityState !== "visible") { return; }
    var es = new EventSource("/api/aliran");
    aliran = es;
    es.onmessage = function (e) {
      var j = null;
      try { j = JSON.parse(e.data); } catch (x) { j = null; }
      if (!j) { return; }
      jalur = "sse";
      jedaSambung = 1000;
      statistik.dorongan++;
      tandaiPutus(false);
      terimaPenanda(j);
    };
    es.onerror = function () {
      es.close();
      if (aliran === es) { aliran = null; }
      jalur = "denyut";
      jadwalkanSambung();
    };
  }

  function jadwalkanSambung() {
    if (sambungUlang) { return; }
    sambungUlang = setTimeout(function () {
      sambungUlang = null;
      sambungAliran();
    }, jedaSambung);
    jedaSambung = Math.min(jedaSambung * 2, 30000);
  }

  function putuskanAliran() {
    if (aliran) { aliran.close(); aliran = null; }
    jalur = "denyut";
  }

  /* ── Sinyal hilang: cap waktu selebar layar, tombol aksi mati ──
   *
   * Angka di layar ini adalah keadaan pukul sekian — dan orangnya harus
   * tahu itu SEBELUM membacanya, jadi barisnya selebar layar di atas, bukan
   * ikon kecil di sudut. Tombol aksi dinonaktifkan sungguhan, bukan sekadar
   * gagal saat ditekan: yang menekan lalu tak terjadi apa-apa akan menekan
   * lima kali, dan kelimanya terkirim saat sinyal kembali. Pulih sendiri
   * begitu penanda terbaca lagi. Persetujuan pemilik 14 Sep 2026. */
  var pukulSegar = null;

  function tandaiPutus(putus) {
    var bar = document.querySelector(".putus");
    if (putus) {
      if (!bar) {
        bar = document.createElement("div");
        bar.className = "putus";
        document.body.appendChild(bar);
        document.body.classList.add("putus-jaringan");
      }
      bar.textContent = "Data pukul " + (pukulSegar || "?") + " · sedang offline";
      var sasaran = document.querySelectorAll(".bingkai button, .bingkai .btn, .bingkai input[type=submit]");
      Array.prototype.forEach.call(sasaran, function (b) {
        // Kontrol baca-saja seperti Tutup laporan tetap bisa dipakai offline.
        if (b.disabled || b.hasAttribute("data-putus") || b.hasAttribute("data-boleh-offline")) { return; }
        b.setAttribute("data-putus", "1");
        b.disabled = true;
      });
    } else if (bar) {
      bar.remove();
      document.body.classList.remove("putus-jaringan");
      Array.prototype.forEach.call(document.querySelectorAll("[data-putus]"), function (b) {
        b.removeAttribute("data-putus");
        b.disabled = false;
      });
    }
  }
  window.addEventListener("offline", function () { tandaiPutus(true); });
  window.addEventListener("online", function () { window.PINDAH.diam(); });

  /* ── Data acuan untuk saat sinyal hilang ──
   *
   * HANYA daftar yang berubah mingguan (pemasok, pelanggan, jenis barang,
   * nama silo & pengering) — nama saja, dari /api/acuan. Disimpan selagi
   * jaringan ada; /luring menampilkannya di bawah cap waktu. Tak pernah isi
   * silo, antrean, atau stok: angka yang berubah tiap jam lebih berbahaya
   * basi daripada tidak ada. */
  var KUNCI_ACUAN = "hmu_acuan";

  function simpanAcuan() {
    if (!navigator.onLine) { return; }
    fetch("/api/acuan", { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.daftar) { return; }
        try { localStorage.setItem(KUNCI_ACUAN, JSON.stringify(j)); } catch (e) { /* penuh */ }
      })
      .catch(function () { /* nanti lagi */ });
  }

  function gambarAcuan() {
    var wadah = document.querySelector("[data-acuan]");
    if (!wadah) { return; }
    var j = null;
    try { j = JSON.parse(localStorage.getItem(KUNCI_ACUAN) || "null"); } catch (e) { j = null; }
    pukulSegar = j && j.pukul ? j.pukul : pukulSegar;
    tandaiPutus(true);
    if (!j) {
      wadah.innerHTML = '<p class="bantu">Belum ada daftar acuan tersimpan di ponsel ini.</p>';
      return;
    }
    var html = '<div class="acuan">';
    j.daftar.forEach(function (d) {
      if (!d.isi || !d.isi.length) { return; }
      html += "<h3>" + teks(d.judul) + "</h3><ul>" +
        d.isi.map(function (x) { return "<li>" + teks(x) + "</li>"; }).join("") + "</ul>";
    });
    wadah.innerHTML = html + "</div>";
  }

  function teks(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* Pembaruan rilis ditangani modul tersendiri, termasuk dokumen lama
     yang baru menerima isi .bingkai dari server. Jangan mengganti isian. */
  function tawarkanVersi(versi) {
    document.dispatchEvent(new CustomEvent("padiflow:versi", {detail: {versi: String(versi)}}));
  }

  /* Service worker: kerangka dari cache, halaman dari jaringan, /luring
     saat putus. Alamatnya membawa VERSI supaya deploy = worker baru. */
  if ("serviceWorker" in navigator && VERSI_JALAN) {
    navigator.serviceWorker.register("/sw.js?v=" + VERSI_JALAN, { scope: "/" })
      .catch(function () { /* tanpa service worker aplikasi tetap jalan */ });
  }

  function bolehDiam() {
    if (disentuh) { return false; }
    if (lembarTerbuka()) { return false; }
    var f = document.activeElement;
    if (f && /^(INPUT|SELECT|TEXTAREA)$/.test(f.tagName)) { return false; }
    return true;
  }

  document.addEventListener("input", function (e) { if (!e.target.form || (e.target.form.method || "get").toLowerCase() !== "get") disentuh = true; }, true);
  document.addEventListener("change", function (e) { if (!e.target.form || (e.target.form.method || "get").toLowerCase() !== "get") disentuh = true; }, true);

  /* ── Kesegaran data, terlihat ──
   *
   * Layar ini menyegarkan dirinya diam-diam, dan kadang TIDAK — saat ada
   * lembar terbuka, saat orangnya sedang mengetik, atau saat jaringan mati.
   * Tanpa tanda apa pun, operator tak punya cara membedakan "angka ini baru"
   * dari "angka ini sudah setengah jam tak berubah", dan keputusan diambil
   * di atas data basi tanpa ada yang menyadarinya. Temuan QA P-K-19.
   *
   * Ditulis kecil di sudut, bukan sebagai peringatan: ia informasi, bukan
   * masalah — dan peringatan yang muncul tiap menit berhenti dibaca.
   */
  function tandaiSegar() {
    var el = document.getElementById("segar");
    if (!el) {
      el = document.createElement("div");
      el.id = "segar";
      el.className = "segar";
      document.body.appendChild(el);
    }
    var t = new Date();
    pukulSegar = String(t.getHours()).padStart(2, "0") + ":" +
      String(t.getMinutes()).padStart(2, "0");
    el.textContent = "diperbarui " + pukulSegar;
  }

  function lembarTerbuka() {
    var l = document.getElementById("lembar");
    return !!(l && (l.open || l.style.display === "flex"));
  }

  /* ── Perpindahan ── */
  function sibuk(ya) {
    if (!bingkai) { return; }
    bingkai.classList.toggle("menunggu", ya);
    if (ya) { bingkai.setAttribute("aria-busy", "true"); }
    else { bingkai.removeAttribute("aria-busy"); }
  }

  function tahanNavigasi() {
    var main = document.getElementById('isi-halaman');
    if (!main) return false;
    var nodes = Array.prototype.slice.call(main.childNodes);
    var awal = nodes.find(function (n) { return n.nodeType === 8 && n.data.trim() === 'isi-halaman:mulai'; });
    var akhir = nodes.find(function (n) { return n.nodeType === 8 && n.data.trim() === 'isi-halaman:akhir'; });
    if (!awal || !akhir || nodes.indexOf(awal) >= nodes.indexOf(akhir)) return false;
    var isi = nodes.slice(nodes.indexOf(awal) + 1, nodes.indexOf(akhir)).filter(function (node) { return node.nodeType === 1; });
    navigasiMenunggu = { main: main, sibuk: main.getAttribute('aria-busy'), isi: isi.map(function (node) {
      var sebelum = node.getAttribute('inert'); node.setAttribute('inert', '');
      return { node: node, inert: sebelum };
    }) };
    // Header/hamburger juga berada di main. Hanya isi lama yang dibekukan;
    // menu dan indikator bilah tetap dapat dipakai tanpa menggeser layout.
    main.setAttribute('aria-busy', 'true');
    // Sama seperti navigasi lama yang telah lolos veto editor: lembar aksi
    // tidak boleh tertinggal interaktif di luar batas isi halaman.
    var lembarLama = document.getElementById('lembar');
    if (lembarLama) lembarLama.remove();
    return true;
  }

  function pulihkanNavigasi() {
    if (!navigasiMenunggu) return;
    var lama = navigasiMenunggu; navigasiMenunggu = null;
    lama.isi.forEach(function (item) {
      if (item.inert === null) item.node.removeAttribute('inert');
      else item.node.setAttribute('inert', item.inert);
    });
    if (lama.sibuk === null) lama.main.removeAttribute('aria-busy');
    else lama.main.setAttribute('aria-busy', lama.sibuk);
  }

  function hapusPesanNavigasi() {
    if (pesanNavigasi) pesanNavigasi.remove();
    pesanNavigasi = null;
  }

  function gagalMuat(alamat, judul, dorong) {
    var main = document.getElementById('isi-halaman');
    if (!main) { location.href = alamat; return; }
    hapusPesanNavigasi();
    var pesan = document.createElement('div'); pesan.className = 'pesan pesan--err';
    pesan.setAttribute('role', 'alert');
    pesan.appendChild(document.createTextNode('Halaman belum dapat dibuka. Periksa koneksi, lalu '));
    var coba = document.createElement('button'); coba.type = 'button'; coba.className = 'btn'; coba.textContent = 'Coba lagi';
    coba.addEventListener('click', function () { pindah(alamat, dorong, judul); });
    pesan.appendChild(coba); main.appendChild(pesan); pesanNavigasi = pesan;
  }

  function pasangMenunggu() {
    if (!dataMenunggu) return;
    if (dataMenunggu.nomor !== nomorPindah) { dataMenunggu = null; return; }
    var laci = document.getElementById('laci');
    // Jangan mengganti elemen sasaran di antara sentuh dan lepas, atau
    // menutup menu yang baru dibuka saat data masih dalam perjalanan.
    if (pointerAktif || laci && !laci.hidden) return;
    var data = dataMenunggu; dataMenunggu = null;
    pulihkanNavigasi();
    tujuanPindah = null; sibuk(false);
    // Inisialisasi dokumen native harus membaca URL tujuan yang sudah benar.
    // Popstate tidak menambah entri baru; klik/retry menambah tepat sekali.
    try {
      if (data.dorong) history.pushState({ pindah: 1 }, '', data.alamat);
      else if (data.kanonik && location.pathname + location.search !== data.alamat) history.replaceState(history.state, '', data.alamat);
      pasang(data.teks, data.alamat, false, data.dorong === true);
    } catch (e) { location.href = data.alamat; }
  }

  function pindah(alamat, dorong, judul) {
    // Hanya pilihan terakhir yang boleh memasang HTML, termasuk bila
    // respons lama datang setelah klik sidebar/detail berikutnya.
    var nomor = ++nomorPindah;
    dataMenunggu = null;
    pulihkanNavigasi(); hapusPesanNavigasi();
    tujuanPindah = alamat;
    var langsung = rencanaKerangkaLangsung(alamat, dorong);
    if (langsung) {
      // Inisialisasi native membaca location; URL harus sudah tepat sebelum
      // tukar() menjalankan ulang script. Validasi di atas belum mengubah DOM.
      if (dorong) history.pushState({ pindah: 1 }, "", alamat);
      tujuanPindah = null; sibuk(false);
      try { pasang(langsung.html, alamat, false, dorong === true); }
      catch (e) {
        // URL sudah menjadi tujuan tervalidasi. Kegagalan kontrol/DOM harus
        // kembali ke GET native, bukan meninggalkan layar setengah terpasang.
        location.href = alamat;
      }
      return;
    }
    var kerangkaHalaman = memakaiKerangkaHalaman(alamat);
    // HTML data yang dipanaskan bukan dokumen kerangka konteks terbaru.
    var tersimpan = kerangkaHalaman ? null : simpan[alamat];

    if (tersimpan) {
      sibuk(false);
      // Sudah di tangan: tampilkan sekarang juga, tanpa menyeberangi laut.
      if (!pasang(tersimpan, alamat, true, dorong === true)) { return; }
      if (dorong) { history.pushState({ pindah: 1 }, "", alamat); }
      // Lalu periksa diam-diam apakah sudah berubah.
      delete simpan[alamat];
      var sentuhanAwal = nomorSentuhan;
      ambil(alamat).then(function (teks) {
        /* Hanya menyegarkan kalau orangnya masih di halaman itu, isinya
           memang berbeda, dan tak ada lembar terbuka. Menukar isi di bawah
           jari orang yang sedang membaca laporan lebih buruk daripada angka
           yang telat setengah detik. */
        if (nomor !== nomorPindah) { return; }
        tujuanPindah = null;
        if (!teks || teks === tersimpan) { return; }
        if (location.pathname + location.search !== alamat) { return; }
        if (lembarTerbuka()) { return; }
        // Pengguna sudah mulai memakai halaman/menu. Mengganti DOM sekarang
        // dapat membuang sasaran di antara pointerdown dan click, sehingga
        // ketukan pertama terasa diabaikan. Simpan versi baru untuk nanti.
        if (nomorSentuhan !== sentuhanAwal || disentuh) {
          jumlahPerubahan++;
          tawarkanPerubahan();
          return;
        }
        pasang(teks, alamat, true);
      });
      return;
    }

    // Tanpa provider native, jangan mengganti isi dengan layar transisi.
    // Tujuan bertahap dibaca sebagai HTML native, dengan janji/cache terpisah
    // agar HTML penuh tidak menjadi cache baru bagi rute data bertahap.
    if (!tahanNavigasi()) { tujuanPindah = null; location.href = alamat; return; }
    sibuk(true);
    var alias = aliasRiwayat(alamat);
    var permintaan = alias ? ambil(alamat, false, true, true) : ambil(alamat, false, kerangkaHalaman);
    permintaan.then(function (hasil) {
      var teks = alias && hasil ? hasil.teks : hasil;
      if (nomor !== nomorPindah) { return; }
      if (!teks) {
        pulihkanNavigasi();
        sibuk(false); tujuanPindah = null;
        if (gagal[(alias ? "alias:" : "") + kunciBaca(alamat, false, kerangkaHalaman || alias)]) { gagalMuat(alamat, judul, dorong); }
        else { location.href = alamat; }
        return;
      }
      dataMenunggu = { teks: teks, alamat: alias ? hasil.alamat : alamat, kanonik: alias, nomor: nomor, dorong: dorong };
      pasangMenunggu();
    });
  }

  /* ── Menangkap ketukan ── */
  function mulai() {
  bingkai = document.querySelector(".bingkai");
  if (!bingkai) { return; }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) { return; }
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!bolehDitangani(a)) { return; }
    var alamat = a.pathname + a.search;
    if (tujuanPindah === alamat) { e.preventDefault(); return; }
    if (alamat === location.pathname + location.search) {
      // Klik kembali ke halaman kini juga membatalkan tujuan yang menunggu.
      ++nomorPindah; tujuanPindah = null; sibuk(false);
      dataMenunggu = null; pulihkanNavigasi(); hapusPesanNavigasi();
      e.preventDefault(); return;
    }
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
    var label = a.querySelector('.pintu__nama') || a.querySelector('.benda__judul');
    pindah(alamat, true, (label || a).textContent.trim().replace(/\s+/g, ' ').slice(0, 90));
  });

  /* Mulai mengambil saat jari MENYENTUH, bukan saat diangkat. Jeda antara
     sentuh dan angkat 80–150 ms — itu potongan gratis dari waktu tunggu. */
  function dahului(e) {
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!bolehDitangani(a)) { return; }
    var alamat = a.pathname + a.search;
    // Jangan membayar pembaca penuh sebelum navigasi opt-in meminta kerangkanya.
    if (memakaiKerangkaHalaman(alamat)) { return; }
    if (!simpan[alamat] && !sedang[alamat]) { ambil(alamat); }
  }
  document.addEventListener("touchstart", dahului, { passive: true });
  document.addEventListener("mouseover", dahului);

  window.addEventListener("popstate", function () {
    if (window.PINDAH.tutupLembarRiwayat && window.PINDAH.tutupLembarRiwayat()) return;
    // Satu pemilik untuk Back/Forward panel yang telah mengadopsi kontrak.
    // Nilai selain true/exception tetap melalui navigasi native yang terjaga.
    if (pembacaRiwayat) {
      try { if (pembacaRiwayat(location.pathname + location.search, history.state) === true) return; }
      catch (_) { /* pembaca opsional gagal: gunakan jalur native */ }
    }
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
        if (!memakaiKerangkaHalaman(alamat) && alamat !== location.pathname + location.search && !simpan[alamat]) {
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
      // Jalur kedua: hanya bertanya bila kanal dorong sedang tak hidup.
      if (document.visibilityState === "visible" && jalur !== "sse") { window.PINDAH.diam(); }
    }, 10000);
  }

  function hentikanDenyut() {
    if (denyut) { clearInterval(denyut); denyut = null; }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      window.PINDAH.diam();
      mulaiDenyut();
      jedaSambung = 1000;
      sambungAliran();
    } else {
      hentikanDenyut();
      putuskanAliran();
    }
  });

  /* Sebagian peramban mengembalikan halaman dari simpanan maju-mundurnya
     tanpa memicu `visibilitychange` sama sekali. */
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) { window.PINDAH.diam(); }
  });

  if (document.visibilityState === "visible") { mulaiDenyut(); sambungAliran(); }

  function siapAcuan() {
    gambarAcuan();
    if (!document.querySelector("[data-acuan]")) {
      simpanAcuan();
      setInterval(simpanAcuan, 30 * 60 * 1000);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", siapAcuan);
  } else {
    siapAcuan();
  }
})();
