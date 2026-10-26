/* Layar pencatatan Pos Produksi.
 *
 * Formulirnya TIDAK ditulis di sini. Server yang mengirim daftar aksi beserta
 * spesifikasi tiap field (jenis, pilihan, sumber data jarak jauh) lewat
 * /api/actions/menu; berkas ini hanya merendernya. Menambah aksi baru
 * berarti menambah satu spesifikasi di Python — bukan menulis layar baru.
 */
(function () {
  "use strict";

  function perbaruiNamaBarang(sel) {
    var baris = sel.closest(".ulang__baris");
    if (!baris) return;
    var nama = baris.querySelector(".ulang__nama-lengkap");
    var satuan = baris.querySelector(".ulang__satuan");
    var ang = baris.querySelector('[data-p-jenis="angka"]');
    var unit = /^(bj:|[0-9]+\|)/.test(sel.value) ? "karung" : "kg";
    if (nama) {
      nama.textContent = sel.value && sel.selectedOptions.length ? sel.selectedOptions[0].textContent : "Pilih barang";
      nama.hidden = false;
    }
    if (satuan) satuan.textContent = sel.value ? unit : "karung / kg";
    if (ang) {
      ang.setAttribute("aria-label", "Jumlah " + (sel.value ? unit : "barang"));
      ang.inputMode = sel.value && unit === "karung" ? "numeric" : "decimal";
    }
  }

  var MENU = {};
  var kembaliSelesaiGiling = null;
  var kembaliSelesaiSosoh = null;
  var DATA = null;

  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : s;
    return d.innerHTML;
  }

  /* ── Kabar hasil ──
     Cukup BERHASIL atau GAGAL, atas keputusan pemilik. Sebelumnya seluruh
     kalimat server ditumpahkan ke sini — hasil berikut peringatannya — dan
     hasilnya sebuah paragraf yang menutupi layar setiap kali orang menekan
     satu tombol.

     Yang membuatnya cukup: sejak lembar aksinya menutup, LAYARNYA sendiri
     digambar ulang. Ke mana gabahnya masuk, berapa kadar airnya sekarang,
     kartu mana yang hilang — semuanya sudah terbaca di tempat aslinya. Kabar
     ini tinggal memastikan bahwa yang ditekan memang tersimpan.

     Gagal tetap membawa SEBABNYA. "Gagal" tanpa sebab tak bisa ditindaklanjuti
     — orangnya hanya tahu bahwa ia harus mencoba lagi, tanpa tahu apa yang
     harus diubah. */
  function kabar(pesan, jenis, rinci) {
    // Dialog berada di top layer: z-index kabar setinggi apa pun tetap di
    // belakangnya. Semua kegagalan saat borang terbuka mengikuti borang.
    if (jenis === "err" && lembarSedangTerbuka()) {
      salahFormulir($("lembar"), String(pesan));
      return;
    }
    var t = $("kabar");
    var teks;
    if (jenis === "err") {
      /* Sebab dari server sudah satu kalimat; awalannya saja yang dibuang
         supaya tak ada dua penanda berturut-turut. */
      teks = String(pesan == null ? "" : pesan)
        .split("\n")[0].replace(/^[⚠️!✗×]\s*/, "").trim() || "Gagal disimpan";
    } else {
      teks = rinci ? String(pesan || "Tersimpan").replace(/^[✓\s]+/, "").replace(/\*/g, "") :
        (/dibatalkan/i.test(String(pesan)) ? "Dibatalkan" : "Tersimpan");
    }
    t.innerHTML = '<div class="kabar__utama">'
      + '<span class="kabar__ikon" aria-hidden="true">'
      + (jenis === "err" ? "!" : "\u2713") + "</span>"
      + '<span class="kabar__teks">' + esc(teks) + "</span></div>";
    t.className = "kabar" + (jenis ? " kabar--" + jenis : "") + (rinci ? " kabar--hasil" : "");
    t.style.display = "block";
    t.onclick = function () { t.style.display = "none"; clearTimeout(t._t); };
    clearTimeout(t._t);
    /* Gagal menetap sampai ditekan: ia menghentikan pekerjaan dan menuntut
       tindakan. Berhasil boleh lewat — layarnya sendiri sudah membuktikannya. */
    if (jenis !== "err") {
      t._t = setTimeout(function () { t.style.display = "none"; }, rinci ? 6500 : 2600);
    }
  }

  /* ── Kabar dengan jalan mundur ──
   *
   * Aksi satu-ketuk — "Ke Silo A" di kartu — langsung menyimpan tanpa
   * konfirmasi, dan itu memang gunanya: operator memegang telepon satu tangan
   * sambil mengarahkan truk. Menambahkan dialog "yakin?" akan membayar
   * kecepatan itu dengan ketukan yang sama seringnya.
   *
   * Yang ditambahkan jalan mundurnya, bukan penghalang di depannya: kabar
   * "Tersimpan" membawa tombol BATALKAN selama delapan detik, dan tombol itu
   * membatalkan TEPAT catatan yang barusan dibuat — id-nya dibawa dari
   * jawaban server, bukan dicari ulang sebagai "yang terakhir".
   *
   * Delapan detik, bukan dua-setengah seperti kabar biasa: yang perlu
   * disadari orang di sini bukan "tersimpan" melainkan "salah silo", dan itu
   * baru terasa sesudah ia mengangkat kepala dari layar. */
  function kabarBisaBatal(pesan, logId) {
    var t = $("kabar");
    t.innerHTML = '<div class="kabar__utama">'
      + '<span class="kabar__ikon" aria-hidden="true">\u2713</span>'
      + '<span class="kabar__teks">' + esc(pesan || "Tersimpan") + "</span>"
      + '<button type="button" class="kabar__batal">BATALKAN</button></div>';
    t.className = "kabar kabar--ok";
    t.style.display = "block";
    clearTimeout(t._t);
    t._t = setTimeout(function () { t.style.display = "none"; }, 8000);

    t.querySelector(".kabar__batal").onclick = async function (e) {
      e.stopPropagation();
      this.disabled = true;
      this.textContent = "membatalkan…";
      try {
        var hasil = await kirim("/api/actions/undo", { lingkup: "saya:" + logId });
        t.style.display = "none";
        if (window.PINDAH && PINDAH.segarkan) {
          PINDAH.segarkan(function () { kabar(hasil.pesan || "Dibatalkan", "ok"); });
        } else {
          kabar(hasil.pesan || "Dibatalkan", "ok");
        }
      } catch (err) {
        kabar(String(err), "err");
      }
    };
    /* Menekan kabarnya sendiri tetap menutup — tetapi TIDAK lewat tombolnya,
       karena orang yang menutup kabar tak bermaksud membatalkan apa pun. */
    t.onclick = function () { t.style.display = "none"; clearTimeout(t._t); };
  }


  async function ambil(url) {
    var r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) {
      if (r.status === 401 || r.status === 403) { location.href = "/masuk?next=/aksi"; return null; }
      var e = await r.json().catch(function () { return {}; });
      throw (e.detail || ("Tidak bisa memuat (HTTP " + r.status + ")"));
    }
    return r.json();
  }

  /* Token CSRF dibaca dari kuki-nya sendiri.
     Situs lain bisa membuat peramban MENGIRIM kuki, tetapi tak bisa
     MEMBACANYA — jadi ia tak bisa menyertakan nilai yang sama di header
     permintaannya. Itulah yang membuat pola ini bekerja. */
  function kukiCsrf() {
    var el = document.getElementById("formulir-sesi");
    return el ? el.dataset.token : "";
  }

  async function kirim(url, isi) {
    if (window.SESIFORM && !SESIFORM.periksa()) throw "Sesi berubah. Salin isian lalu buka formulir baru dengan akun yang benar.";
    var r = await fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": kukiCsrf() },
      body: JSON.stringify(isi),
    });
    var j = await r.json().catch(function () { return {}; });
    if (window.SESIFORM && !SESIFORM.periksa()) throw "Sesi berubah ketika permintaan diproses. Periksa riwayat akun pembuka sebelum mengulang; permintaan yang sudah diterima mungkin selesai.";
    if (!r.ok) {
      /* ── Konflik: SEGARKAN daftarnya sekarang juga ──
         Dua orang membuka tiket yang sama; yang kedua ditolak, tetapi kartu
         basinya tetap berdiri di daftar dan hitungannya tak berubah. Orang
         itu akan mencobanya lagi — dan ditolak lagi. Pesannya kini menyebut
         siapa dan pukul berapa; daftarnya diperbarui supaya kartunya benar-
         benar hilang. Temuan QA UI-02. */
      if (r.status === 409 || /sudah dicatat|sudah ditautkan|sudah tercatat/i
          .test(String(j.detail || ""))) {
        if (window.PINDAH && !lembarSedangTerbuka()) { PINDAH.lupakan(); PINDAH.segarkan(); }
      }
      if(url === "/api/actions/masukkan-broken-silo" && r.status >= 500) throw new TypeError("Hasil pemindahan broken belum terkonfirmasi");
      throw (j.detail || ("Gagal disimpan (HTTP " + r.status + ")"));
    }
    /* Sesuatu baru saja tercatat: halaman yang tersimpan di memori kini
       menggambarkan keadaan SEBELUM catatan itu. Data yang telat sedikit
       masih bisa diterima; halaman yang tidak memuat pekerjaan yang baru
       saja dilakukan orangnya sendiri tidak. */
    if (window.PINDAH) { window.PINDAH.lupakan(); }
    return j;
  }

  /* Label aksi dari server diawali emoji ("🌾 Gabah masuk") — kosakata yang
     sudah dikenal operator dari bot. Emoji-nya dipisah ke kotak ikon supaya
     terbaca sebagai ikon, bukan sebagai hiasan di tengah kalimat. */
  /* Label medan lain, untuk kalimat "— pilih <medan itu> dulu —". Diambil
     dari spesifikasinya, bukan ditulis dua kali: judul medan induk yang
     berubah tanpa kalimat ini ikut berubah menyuruh orang memilih sesuatu
     yang tak ada lagi di layarnya. */
  function cariLabel(fields, nama) {
    var f = (fields || []).filter(function (x) { return x.name === nama; })[0];
    return f ? f.label : nama;
  }

  function belah(label) {
    var m = /^(\p{Extended_Pictographic}\uFE0F?)\s*(.*)$/u.exec(label || "");
    return m ? { ikon: m[1], teks: m[2] } : { ikon: "", teks: label || "" };
  }

  async function muat() {
    try {
      var d = await ambil("/api/dashboard");
      if (!d) return;
      var menu = [];
      try { menu = (await ambil("/api/actions/menu")) || []; } catch (e) { menu = []; }
      /* Urutan kelompok ikut dari server bersama menunya — ditempelkan pada
         aksi pertama, karena daftar itu memang satu-satunya yang dikirim.
         Menaruhnya di layar berarti dua tempat yang harus sepakat. */
      DATA = { menu: menu, urutGrup: (menu[0] && menu[0].urut_grup) || [] };
      MENU = {};
      menu.forEach(function (a) { MENU[a.id] = a; });
      gambar();
    } catch (e) {
      var wadah = $("layar");
      if (wadah) {
        wadah.innerHTML = '<div class="pesan pesan--err">' + esc(String(e)) + "</div>";
      }
    }
  }

  function gambar() {
    /* Layar Catat hanya berisi AKSI.
     *
     * Dulu ada pita tab kecil di atasnya berisi panel informasi khusus Admin
     * — "Tugas verifikasi & QC" dan "HPP beras terkini" — sisa zaman Mini App
     * Telegram, waktu segalanya harus muat di satu layar. Keduanya kini punya
     * rumahnya sendiri: yang menunggu tindakan ada di BERJALAN, angka HPP dan
     * stok ada di LAPORAN. Menyimpannya di sini pula berarti dua tempat untuk
     * satu hal, dan yang di sini tak pernah ikut diperbarui.
     *
     * Menyempilkannya sebagai pita kecil juga menyesatkan: ia terlihat seperti
     * saringan atas daftar aksi, padahal isinya bukan aksi sama sekali.
     */
    var layar = $("layar");
    {
      /* Yang sudah punya kartu tak digambar di sini. Server menandainya
         (`kartu: true`) dan tetap mengirimkannya, karena lembar yang dibuka
         dari kartu Antrian/Berjalan/Keputusan/Stok dibangun dari MENU yang
         sama — yang dibuang hanya tombolnya di katalog. Dua pintu untuk satu
         pekerjaan membuat orang bertanya yang mana yang benar. */
      var aksi = (DATA.menu || []).filter(function (a) { return !a.kartu; });
      /* Dikelompokkan, bukan didaftar datar. Tiga puluh kata kerja berjajar
         sama besar menuntut orang membaca semuanya untuk menemukan satu —
         persis keadaan yang sudah dibuang dari layar antrean. Kelompok dan
         urutannya datang dari SERVER: yang tahu pekerjaan mana milik siapa
         adalah spesifikasi aksinya, bukan layar yang menggambarnya. */
      var urut = DATA.urutGrup || [];
      var per = {};
      aksi.forEach(function (a) {
        var g = a.grup || "Lain-lain";
        (per[g] = per[g] || []).push(a);
      });
      var nama = urut.filter(function (g) { return per[g]; })
        .concat(Object.keys(per).filter(function (g) { return urut.indexOf(g) < 0; }));

      function kartuAksi(a) {
        var b = belah(a.label);
        return '<button class="tindakan" data-aksi="' + esc(a.id) + '">' +
          (b.ikon ? '<span class="tindakan__ikon tindakan__ikon--emoji">' + esc(b.ikon) + "</span>" : "") +
          '<span class="tindakan__isi"><span class="tindakan__nama">' + esc(b.teks) + "</span>" +
        (a.hint ? '<span class="tindakan__ket">' + esc(a.hint) + "</span>" : "") +
          "</span>" +
          '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="var(--redup-2)" ' +
          'stroke-width="2.2" stroke-linecap="round"><path d="M9 6l6 6-6 6"/></svg></button>';
      }

      layar.innerHTML = aksi.length
        ? nama.map(function (g) {
            return '<div><span class="lbl">' + esc(g) + " · " + per[g].length + "</span>" +
              '<div class="grup" style="gap:8px">' +
              per[g].map(kartuAksi).join("") + "</div></div>";
          }).join("")
        : '<div class="kartu"><p class="bantu">Tidak ada aksi untuk peran Anda.</p></div>';
      Array.prototype.forEach.call(layar.querySelectorAll("[data-aksi]"), function (b) {
        b.onclick = function () { bukaAksi(b.dataset.aksi); };
      });
    }
  }

  /* ── Yang sudah ditunjuk kartunya tak ditanyakan lagi ──
     Orang menekan kartu GB-20260831-01, lalu lembarnya membuka daftar
     tarik-turun dan memintanya memilih GB-20260831-01. Itu menyuruh orang
     memilih hal yang sama dua kali — dan kesempatan kedua itulah tempat ia
     salah pilih. Isiannya jadi KETERANGAN: teks biasa, tak bisa diubah,
     nilainya tetap ikut terkirim. */
  function nilaiBaris() {
    var tag = document.querySelector("script[data-nilai]");
    return (tag && tag.dataset.nilai) || "";
  }

  /* Lembar yang sedang terbuka menitipkan cara menyegarkan daftarnya di
     sini; `null` berarti tak ada lembar terbuka. */
  var segarkanPilihan = null;
  var terakhirMuat = 0;

  function bukaAksi(id, semula) {
    if (lembarSedangTerbuka() && !bolehBuang($("lembar"), function () {
      bukaAksi(id, semula);
    })) return;

    if (id === "muat_barang" || id === "muat_semua") {
      var muatanId = nilaiBaris().split("|")[0];
      location.assign("/muatan" + (/^[1-9]\d*$/.test(muatanId) ? "?perintah=" + encodeURIComponent(muatanId) : ""));
      return;
    }

    var a = MENU[id];
    if (!a) return;

    if (kembaliSelesaiSosoh && id !== 'akhiri_penyosohan' &&
        !(id === 'selesai_penyosohan' && semula && semula._dariSelesaiSosoh)) kembaliSelesaiSosoh = null;

    // Draf hanya mengikuti tautan Bebaskan silo dari formulir ini.
    if (kembaliSelesaiGiling && id !== 'selesai_giling' &&
        !(id === 'tutup_silo_giling' && semula && semula._dariSelesaiGiling)) kembaliSelesaiGiling = null;

    /* Yang dikunci hanya isian PENUNJUK — yang pertama bertipe pilihan.
       Di seluruh spesifikasi, isian itulah yang menyebut benda yang sedang
       dikerjakan; sisanya keputusan yang memang belum diambil. */
    var terkunci = nilaiBaris();
    var sumberAwalMasukkan = a.konteks_masukkan_silo ? terkunci : '';
    // Tautan lama menunjuk intake, belum bentuknya. Saat ada karung DAN
    // curah, tetap bawa intake tersebut tetapi biarkan memilih bagiannya.
    if (sumberAwalMasukkan && sumberAwalMasukkan.indexOf(':') < 0) terkunci = '';
    var lingkupKemas = id === "catat_packing" && terkunci.indexOf("curah@") === 0 ? terkunci.split("@") : null;
    if (lingkupKemas) terkunci = "";
    var namaKunci = "";
    if (terkunci) {
      for (var i = 0; i < (a.fields || []).length; i++) {
        var f0 = a.fields[i];
        /* `remote_banyak` ikut: pada medan itu "kunci" berarti TERCENTANG DI
           AWAL, bukan tak bisa diubah (lihat cabang rendernya). Tanpa ia
           disebut di sini, kartu Silo A membuka borang yang tak mencentang
           apa pun — dan orang harus memilih ulang benda yang baru saja ia
           tekan, yaitu persis kesempatan kedua untuk salah pilih yang
           penguncian ini ada untuk menutupnya. */
        if (f0.type !== "select" && f0.type !== "remote"
            && f0.type !== "remote_banyak") { continue; }
        if (f0.type === "select") {
          var ada = (f0.options || []).some(function (o) { return o[0] === terkunci; });
          if (!ada) { break; }
        }
        namaKunci = f0.name;
        break;
      }
    }

    // Baris kemasan sudah menunjuk sumber selain jenis beras. Keduanya
    // dibawa sebagai isian terkunci agar tidak memilih kemasan lain lagi.
    var tagBaris = document.querySelector("script[data-sumber-stok]");
    var tagPerintah = document.querySelector("script[data-perintah-detail]");
    var sumberBaris = id === "masukkan_beras_silo" && tagBaris
      ? (tagBaris.dataset.sumberStok || "") : "";
    function kunciMedan(f) {
      return f.name === namaKunci ? terkunci :
        (f.name === "sumber_stok" ? sumberBaris : "");
    }

    /* Tombol ke aksi LAIN — digambar di paling bawah, sesudah Simpan.
     *
     * Letaknya yang menyampaikan maksudnya. Di tengah borang ia terbaca
     * sebagai isian yang belum diisi; di bawah tombol Simpan ia terbaca
     * sebagai jalan keluar yang lain — dan memang itu: menekannya
     * meninggalkan borang ini dan membuka borang lain. */
    var tombolLain = (a.fields || []).filter(function (f) {
      return f.type === "tombol_aksi";
    }).map(function (f) {
      return '<button type="button" class="btn btn--kecil lembar__lain"' +
        ' data-buka-aksi="' + esc(f.aksi) + '"' +
        (f.bawa ? ' data-bawa="' + esc(f.bawa) + '"' : "") + ">" +
        esc(f.label) + "</button>";
    }).join("");

    var isi = (a.fields || []).map(function (f, i, semua) {
      if (f.type === "tombol_aksi") { return ""; }
      /* ── BEBERAPA pilihan sekaligus: centang, bukan daftar jatuh ──
       *
       * Satu giling boleh mengambil dari beberapa silo sekaligus (keputusan
       * pemilik 24 September 2026), dan hasilnya tetap satu lot. Daftar jatuh
       * `multiple` tak dipakai: di ponsel ia menuntut tekan-tahan atau tombol
       * Ctrl yang tak ada, dan yang tak tahu caranya akan mengira hanya satu
       * yang boleh dipilih — yaitu tepat kesalahpahaman yang hendak diperbaiki.
       *
       * Diletakkan SEBELUM cabang "terkunci" dengan sengaja: kartu yang
       * membuka lembar ini menyebut satu silo, dan silo itu DICENTANG, bukan
       * dikunci. Mengunci berarti orang yang menekan kartu Silo A tak bisa
       * menambahkan Silo B tanpa menutup borangnya dulu — kartu jadi kandang.
       *
       * Nilainya dikumpulkan di satu kolom tersembunyi (kode dipisah koma),
       * sebab pengumpul di bawah membaca `[data-name]`; `data-teks` menyimpan
       * tulisannya untuk kalimat konfirmasi, yang harus berbunyi "Silo A ·
       * Silo B", bukan "A,B". */
      if (f.type === "pratinjau") {
        return '<p class="nota" id="p_' + esc(f.name) +
          '" role="status" aria-live="polite">' + esc(f.label) + '</p>';
      }
      if (f.type === "remote_banyak") {
        return '<label class="lbl">' + esc(f.label) + "</label>" +
          '<div class="centangan" id="b_' + esc(f.name) + '">' +
          '<p class="bantu">memuat…</p></div>' +
          '<input type="hidden" data-name="' + esc(f.name) + '" data-banyak="1"' +
          (f.optional ? "" : ' data-wajib="1"') +
          ' data-label="' + esc(f.label) + '" value="">';
      }
      if (kunciMedan(f)) {
        var nilaiKunci = kunciMedan(f);
        var teks = nilaiKunci;
        if (f.type === "select") {
          (f.options || []).forEach(function (o) {
            if (o[0] === nilaiKunci) { teks = o[1]; }
          });
        }
        /* Tanpa label: label adalah pertanyaan, dan pertanyaan ini sudah
           dijawab saat kartunya ditekan. Yang tersisa cuma keterangan
           benda mana yang sedang dikerjakan — jadi borangnya terbaca mulai
           dari keputusan pertama yang memang belum diambil. */
        return '<p class="terkunci" id="t_' + esc(f.name) + '">' + esc(teks) + "</p>" +
          '<input type="hidden" data-name="' + esc(f.name) + '"' +
          ' data-label="' + esc(f.label) + '" value="' + esc(nilaiKunci) + '">';
      }
      var l = '<label class="lbl" for="f_' + esc(f.name) + '">' + esc(f.label) + "</label>";
      if (f.type === "datetime-local") {
        return l + '<input class="fld" type="datetime-local" id="f_' + esc(f.name) +
          '" data-name="' + esc(f.name) + '" data-label="' + esc(f.label) + '"' +
          (f.wajib ? ' data-wajib="1"' : '') + '>';
      }
      if (f.type === "select") {
        var opts = (f.options.length && f.options[0][0] === "")
          ? f.options : [["", "— pilih —"]].concat(f.options);
        var pilihan = l + '<select class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) + '"' +
          (f.optional ? "" : ' data-wajib="1"') + ' data-label="' + esc(f.label) + '">' +
          opts.map(function (o) {
            return '<option value="' + esc(o[0]) + '"' + (f.bawaan === o[0] ? ' selected' : '') + '>' + esc(o[1]) + "</option>";
          }).join("") + "</select>";
        return f.rincian ? '<details><summary>' + esc(f.rincian) + "</summary>" + pilihan + "</details>" : pilihan;
      }
      if (f.type === "remote") {
        // `optional` ada karena sebagian pilihan memang tak berlaku untuk
        // semua isian: merk hanya milik beras, mutu hanya milik beras putih.
        // Memaksanya wajib akan membuat orang mengarang jawaban.
        //
        // `induk` = medan lain yang menentukan isi daftar ini (silo mana yang
        // dipakai PROSES yang dipilih di atasnya). Sebelum induknya dipilih
        // daftarnya memang belum bisa dijawab, jadi yang tertulis "pilih dulu"
        // — bukan daftar mati yang menawarkan pilihan yang tak pernah dipakai,
        // lalu ditolak server sesudah ditekan.
        return l + '<select class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
          '"' + (f.optional ? "" : ' data-wajib="1"') +
          (f.induk ? ' data-induk="' + esc(f.induk) + '"' : "") +
          /* `value=""` pada PENAMPUNG SEMENTARA, dan itu bukan kerapian:
             <option> tanpa value memakai TULISANNYA sebagai nilai. Medan lain
             yang bergantung pada medan ini lalu membaca "memuat…" sebagai
             pilihan yang sah, memuat daftarnya dengan induk itu, dan menerima
             daftar kosong — layarnya berkata "(belum ada)" lalu mematikan
             tombol Simpan, padahal orangnya belum memilih apa pun. */
          ' data-label="' + esc(f.label) + '"><option value="">' +
          (f.induk ? "— pilih " + esc(belah(cariLabel(semua, f.induk)).teks.toLowerCase()) +
                     " dulu —" : "memuat…") +
          "</option></select>";
      }
      /* ── MEDAN DIKETIK SAMBIL MENYARING — daftar jatuh untuk pilihan BANYAK ──
       *
       * Keluhan pemilik 7 Oktober 2026 atas daftar jatuh `remote` biasa di
       * borang "Pindah kepemilikan karung": "harus bisa diketik sambil
       * memfilter dari list pelanggan yang ada di database." Daftar jatuh
       * `<select>` memaksa menggulir satu per satu begitu pelanggannya
       * banyak — pintu ini kotak TEKS yang menyaring daftar yang SAMA
       * (`ambil(f.source)`, satu kali, lalu disaring di sini tanpa
       * permintaan baru tiap huruf) sambil diketik, dan kolom tersembunyi di
       * sebelahnya yang membawa KODE/id-nya — pengumpul muatan tetap
       * menyapu `[data-name]` seperti biasa, tak perlu tahu bentuknya beda.
       *
       * Bukan ketik-bebas: yang terkirim HANYA pilihan yang benar-benar
       * disentuh (klik atau Enter), supaya tak ada nama yang diketik
       * sebagian lalu terkirim sebagai id kosong. Tulisan yang tak cocok
       * satu pilihan pun dikosongkan lagi saat kotaknya ditinggalkan
       * (`blur`, lihat `pasangKombo`) — borang yang terlihat terisi padahal
       * belum ada yang terpilih lebih berbahaya daripada kotak kosong. */
      if (f.type === "kombo") {
        return l + '<div class="kombo">' +
          '<input type="text" class="fld" id="x_' + esc(f.name) + '" autocomplete="off"' +
          ' placeholder="' + esc(f.placeholder || "Ketik untuk mencari…") + '">' +
          '<div class="kombo__saran" id="c_' + esc(f.name) + '" hidden></div></div>' +
          '<input type="hidden" data-name="' + esc(f.name) + '" data-cari="1"' +
          (f.optional ? "" : ' data-wajib="1"') +
          ' data-label="' + esc(f.label) + '" value="">';
      }
      /* ── MEDAN BERULANG BERPASANGAN — satu BARIS (barang + jumlah) ──
       *
       * Permintaan pemilik 29 September 2026: "admin bisa memilih barang yang
       * akan keluar beserta jumlahnya. lalu bisa klik tambah item lalu keluar
       * field baru untuk memilih item lain beserta jumlahnya, karena barang
       * keluar bisa multi item."
       *
       * Bedanya dengan `ulang` biasa, dan itu yang menuntut jenis tersendiri:
       * yang diulang SEPASANG, bukan satu kotak. Satu transaksi barang keluar
       * memuat beberapa macam barang, dan tiap macam punya jumlahnya sendiri.
       *
       * Anaknya sengaja TIDAK membawa `data-name`: pengumpul muatan dan
       * pembaca konfirmasi menyapu `[data-name]` dan akan memperlakukan
       * keduanya sebagai dua medan lepas — barangnya di satu kunci, jumlahnya
       * di kunci lain, dan pasangannya hilang. Mereka memakai `data-p` dan
       * dikumpulkan sendiri, per BARIS, supaya urutannya tak bisa tergeser.
       *
       * `data-wajib` hanya di baris pertama: menambah baris lalu
       * meninggalkannya kosong bukan kesalahan — orang menekan tombolnya lalu
       * berubah pikiran, dan menolak simpan karenanya menghukum keragu-raguan
       * yang wajar. Baris kosong dibuang saat dikumpulkan. */
      if (f.type === "ulang_barang") {
        var maksB = f.maks || 10;
        return l +
          '<div class="ulang ulang--pasangan" data-ulang-untuk="' + esc(f.name) + '"' +
          ' data-maks="' + maksB + '">' +
          barisBarang(f, true) +
          "</div>" +
          '<button type="button" class="btn btn--kecil ulang__tambah"' +
          ' data-tambah="' + esc(f.name) + '">' +
          esc(f.tambah || "+ Tambah item") + "</button>";
      }
      /* MEDAN BERULANG — satu kotak, lalu tombol yang menambah kotak.
       *
       * Alat tes kadar air dipakai di beberapa titik, dan berapa titiknya
       * berbeda tiap kali: tumpukan kecil cukup satu tusukan, yang besar
       * perlu empat. Empat kotak yang selalu tergambar memaksa operator
       * melihat tiga kotak kosong tiap kali ia mencatat satu titik — dan
       * borang yang sebagian besarnya kosong terbaca seperti borang yang
       * belum selesai diisi.
       *
       * Kotak pertama bawa `data-wajib`; yang ditambahkan tidak. Menambah
       * kotak lalu meninggalkannya kosong bukan kesalahan — orang menekan
       * tombolnya lalu berubah pikiran, dan menolak simpan karenanya akan
       * menghukum keragu-raguan yang wajar. */
      if (f.type === "ulang") {
        var maks = f.maks || 4;
        return l +
          '<div class="ulang" data-ulang-untuk="' + esc(f.name) + '"' +
          ' data-maks="' + maks + '">' +
          '<input class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
          '" data-ulang="1" data-wajib="1" data-label="' + esc(f.label) + '"' +
          ' type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*"' +
          ' autocomplete="off" enterkeyhint="next" placeholder="titik 1">' +
          "</div>" +
          '<button type="button" class="btn btn--kecil ulang__tambah"' +
          ' data-tambah="' + esc(f.name) + '">' +
          esc(f.tambah || "Tambah") + "</button>";
      }
      var angka = f.type === "number";
      // `wajib` OPT-IN, bukan kebalikan dari `optional`.
      //
      // Sebagian aksi sengaja meminta "isi minimal salah satu" — QC hasil
      // giling menerima kadar air ATAU broken ATAU susut. Menjadikan semua
      // kolom angka wajib secara diam-diam akan mematikan aksi-aksi itu, jadi
      // yang benar-benar wajib disebut satu per satu di spesifikasinya.
      /* type="text" + inputmode, BUKAN type="number": di ponsel yang terakhir
         memunculkan panah cacah yang tak berguna, menolak koma di sebagian
         papan ketik, dan diam-diam membuang nilai tak sah saat dibaca.
         Papan angka datang dari inputmode; koma diterima dan dibaca sebagai
         titik. enterkeyhint: "berikutnya" sepanjang rantai, "selesai" di
         kolom terakhir. */
      var terakhir = i === semua.length - 1;
      var inputAngka = '<input class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
        '"' + (f.wajib ? ' data-wajib="1"' : "") +
        ' data-label="' + esc(f.label) + '"' +
        ' type="text" inputmode="' + (angka ? "decimal" : "text") + '"' +
        (angka ? ' data-angka="1" pattern="[0-9]*[.,]?[0-9]*"' : "") +
        ' enterkeyhint="' + (terakhir ? "done" : "next") + '" autocomplete="off">';
      if (f.maksimal_karung) {
        return l + '<div class="jumlah-berdampingan">' + inputAngka +
          '<div class="maksimal-kemas" role="status" aria-live="polite">' +
          '<span>Maksimal kemas</span><strong id="maks_' + esc(f.name) + '">Pilih proses &amp; ukuran</strong>' +
          '</div></div>';
      }
      return l + inputAngka;
    }).join("");

    // Identitas kartu tetap terlihat ketika formulir menutupi daftar.
    // "Dibuka dari" adalah konteks asal, bukan pengganti validasi pilihan server.
    var asalKartu = Array.prototype.find.call(document.querySelectorAll("[data-konteks]"), function (n) {
      if (!terkunci) return false;
      var liens = n.matches("a[href]") ? [n] : Array.prototype.slice.call(n.querySelectorAll("a[href]"));
      return liens.some(function (l) {
        var u = new URL(l.href, location.href);
        return u.searchParams.get("buka") === id && u.searchParams.get("nilai") === String(terkunci);
      });
    });
    var konteksKartu = asalKartu ? '<p class="identitas-formulir" role="note">Dibuka dari: ' + esc(asalKartu.dataset.konteks) + '</p>' : '';
    var judul = a.konteks_tambah_sosoh ? "Tambah silo untuk mix bahan" : a.konteks_selesai_sosoh ? "Selesai penyosohan" : belah(a.label).teks;
    var hasilKumulatif = a.ringkasan_hasil;
    var hasilGiling = a.ringkasan_giling, formHasil = hasilKumulatif || hasilGiling;
    var kadarAir = a.ringkasan_kadar, targetAir = a.konteks_target, formAir = kadarAir || targetAir;
    var selesaiKering = a.konteks_selesai_pengeringan;
    var pindahSilo = a.konteks_pindah_silo;
    var mulaiGiling = a.konteks_mulai_giling;
    var mulaiSosoh = a.konteks_mulai_penyosohan, mulaiBahan = mulaiGiling || mulaiSosoh;
    var selesaiGiling = a.konteks_selesai_giling;
    var selesaiSosoh = a.konteks_selesai_sosoh;
    var bebaskanGiling = a.konteks_bebaskan_giling;
    var bebaskanSosoh = a.konteks_bebaskan_sosoh;
    var tambahGiling = a.konteks_tambah_giling;
    var tambahSosoh = a.konteks_tambah_sosoh;
    var unitTransferPk = a.unit_transfer_pk;
    var masukkanSilo = a.konteks_masukkan_silo;
    var masukkanBroken = a.konteks_broken_silo;
    var masukkanBeras = a.konteks_beras_silo;
    // Menir dan Reject memakai kontrak tiga field serta alokasi domain yang sama.
    var kemasBeras = a.konteks_kemas_beras;
    var masukkanMenir = a.konteks_menir_silo || a.konteks_reject_silo;
    var jenisMn = a.konteks_reject_silo ? 'reject' : 'menir', labelMn = a.konteks_reject_silo ? 'Reject' : 'Menir';
    var formKhusus = formHasil || formAir || selesaiKering || pindahSilo || mulaiBahan || selesaiGiling || selesaiSosoh || bebaskanGiling || bebaskanSosoh || tambahGiling || tambahSosoh || unitTransferPk || masukkanSilo || masukkanBroken || masukkanBeras || masukkanMenir || kemasBeras;
    var labelSimpan = (tambahGiling || tambahSosoh) ? "Tambahkan silo" : (bebaskanGiling || bebaskanSosoh) ? "Periksa sisa silo" : (selesaiGiling || selesaiSosoh) ? "Periksa penyelesaian" : mulaiSosoh ? "Mulai penyosohan" : mulaiGiling ? "Mulai giling · 1 lot" : pindahSilo ? "Pindahkan ke silo" : selesaiKering ? "Selesai & mulai pendinginan" : kadarAir ? "Simpan pengukuran" : formHasil ? "Simpan hasil" : (a.pratinjau_muat === "cepat" ? "Periksa penyerahan" : "Simpan");
    if (unitTransferPk) labelSimpan = unitTransferPk === 'minta' ? 'Minta PK' : 'Catat pengiriman';
    if (masukkanSilo) labelSimpan = 'Masukkan ke silo';
    if (masukkanBroken) labelSimpan = 'Masukkan broken ke silo';
    if (masukkanMenir) labelSimpan = 'Masukkan '+jenisMn+' ke silo';
    if (kemasBeras) labelSimpan = 'Catat pengemasan';
    if (masukkanBeras) labelSimpan = 'Masukkan beras ke silo';
    var lembar = $("lembar");
    lembar.classList.toggle("lembar--hasil", !!formKhusus);
    lembar.classList.toggle("lembar--kadar", !!formAir);
    lembar.classList.toggle("lembar--selesai-kering", !!selesaiKering);
    lembar.classList.toggle("lembar--pindah-silo", !!pindahSilo);
    lembar.classList.toggle("lembar--mulai-giling", !!mulaiGiling);
    lembar.classList.toggle("lembar--mulai-sosoh", !!mulaiSosoh);
    lembar.classList.toggle("lembar--selesai-giling", !!selesaiGiling);
    lembar.classList.toggle("lembar--selesai-sosoh", !!selesaiSosoh);
    lembar.classList.toggle("lembar--bebaskan-giling", !!bebaskanGiling);
    lembar.classList.toggle("lembar--bebaskan-sosoh", !!bebaskanSosoh);
    lembar.classList.toggle("lembar--tambah-giling", !!tambahGiling);
    lembar.classList.toggle("lembar--tambah-sosoh", !!tambahSosoh);
    lembar.classList.toggle('lembar--unit-pk', !!unitTransferPk);
    lembar.classList.toggle('lembar--masukkan-silo', !!masukkanSilo);
    lembar.classList.toggle('lembar--broken-silo', !!masukkanBroken);
    lembar.classList.toggle('lembar--beras-silo', !!masukkanBeras);
    lembar.classList.toggle('lembar--kemas-beras', !!kemasBeras);
    lembar.classList.toggle('lembar--menir-silo', !!masukkanMenir);
    lembar.setAttribute("aria-label", judul);
    lembar.innerHTML =
      '<div class="lembar__isi">' +
        '<div class="lembar__kepala"><h2>' + esc(judul) + "</h2>" +
          (formKhusus ? '' : '<button class="btn btn--kecil" id="tutup" type="button">Batal</button>') + '</div>' +
        (formKhusus ? '' : konteksKartu) +
        (a.hint && !formKhusus ? '<p class="bantu" style="margin-bottom:14px">' + esc(a.hint) + "</p>" : "") +
        '<div class="grup">' + isi + "</div>" +
        (formKhusus ? '<div class="hasil-actions"><button class="btn" id="tutup" type="button">Batal</button>' : '') +
        '<button class="btn btn--utama" id="simpan" type="button"' + (formKhusus ? '' : ' style="margin-top:18px"') + '>' + labelSimpan + '</button>' +
        (formKhusus ? '</div>' : '') +
        tombolLain +
      "</div>";
    if (asalKartu && !formKhusus) {
      var jenisKartu = asalKartu.querySelector(".proses-jenis");
      if (jenisKartu) {
        var jenisFormulir = jenisKartu.cloneNode(true);
        jenisFormulir.classList.add("proses-formulir");
        lembar.querySelector(".lembar__kepala").insertAdjacentElement("afterend", jenisFormulir);
      }
    }
    lembar._berubah = false;
    lembar._menyimpan = false;
    lembar.oninput = lembar.onchange = function () { lembar._berubah = true; };
    bukaLembar(lembar);
    document.body.style.overflow = "hidden";

    var dataMasukkan=null, nomorMasukkan=0, timerMasukkan;
    var kunciMasukkan=masukkanSilo?'silo-web-'+Array.prototype.map.call(crypto.getRandomValues(new Uint8Array(16)),function(n){return n.toString(16).padStart(2,'0');}).join(''):'';
    function medanMasukkan(nama,tampil,wajib){
      var e=$('f_'+nama);if(!e)return;
      e.disabled=!tampil;e.hidden=!tampil;e.dataset.pratinjauNonaktif=tampil?'':'1';e.toggleAttribute('data-wajib',!!wajib&&tampil);
      e.closest('.hasil-field').hidden=!tampil;
    }
    function kgMasukkan(kg,final){return kg==null?'Belum diketahui':(final===false?'± ':'')+Number(kg).toLocaleString('id-ID',{maximumFractionDigits:3})+' kg';}
    function pasanganMasukkan(label,isi,utama){return '<div class="mi-pair'+(utama?' mi-total':'')+'"><span>'+esc(label)+'</span><strong>'+esc(isi)+'</strong></div>';}
    function gambarMasukkan(d){
      var s=d&&d.sumber;
      var bantuanJumlah=$('mi-all').parentElement;bantuanJumlah.hidden=!s;
      if(!s){$('mi-stock').innerHTML='<p class="hasil-help">Pilih sumber untuk melihat saldo tersedia dan satuan pencatatan.</p>';return;}
      var karung=s.bentuk==='karung',curah=s.bentuk==='curah';
      medanMasukkan('jumlah_karung',karung,true);medanMasukkan('berat_kg',!karung,true);medanMasukkan('jumlah_karung_partai',s.bisa_lengkapi,false);
      var labelKg=lembar.querySelector('label[for="f_berat_kg"]');if(labelKg)labelKg.textContent=curah?'Berat curah yang dimasukkan (kg)':'Berat hasil timbang — jalur data lama (kg)';
      var bentuk=karung?'Berkarung':curah?'Curah':'Data lama / bagian karung';
      $('mi-stock').innerHTML='<div class="mi-stock-head"><div><strong>'+esc(s.kode)+'</strong><small>'+esc(s.pemilik)+' · '+esc(s.asal)+' · Gudang 2</small></div><span class="mi-badge">'+bentuk+'</span></div><div class="mi-stock-values"><div><span>'+(curah?'Berat curah tersedia':'Total berat tersedia')+'</span><strong>'+esc(kgMasukkan(s.saldo_kg,s.bobot_final))+'</strong><small>'+(s.saldo_kg==null?'Menunggu timbang':s.bobot_final?'Bobot final':'Bobot sementara · mengikuti timbang final')+'</small></div><div><span>'+(karung?'Karung utuh tersedia':'Jumlah karung')+'</span><strong>'+esc(curah?'Tidak berlaku':s.karung==null?'Belum tercatat':s.karung+' karung')+'</strong><small>'+(curah?'Stok curah dicatat dalam kg':'Saldo setelah pemindahan/pengeluaran')+'</small></div></div>'+
        (s.bagian_karung_kg>0.000001?'<p class="mi-note">Ada bagian karung '+esc(kgMasukkan(s.bagian_karung_kg,s.bobot_final))+' di luar karung utuh. Bagian tersebut tetap tercatat setelah pemindahan karung utuh.</p>':'')+
        (!karung&&!curah?'<p class="mi-note">Jumlah karung belum lengkap atau hanya tersisa bagian karung. Jalur kg lama dipertahankan; sumber ini tidak dinyatakan sebagai stok curah.</p>':'')+
        ((d.sejawat||[]).length?'<p class="mi-note">Partai ini juga memiliki sumber '+esc(d.sejawat[0].bentuk==='curah'?'curah':'berkarung')+'. Saldo bentuk lainnya tetap terpisah.</p>':'')+
        '<details><summary>Lihat asal dan saldo awal sumber</summary>'+pasanganMasukkan('Identitas sumber','Intake #'+s.intake_id+' · '+s.bentuk)+pasanganMasukkan('Berat awal partai',kgMasukkan(s.berat_awal,s.bobot_final))+pasanganMasukkan('Karung awal',s.karung_awal==null?'Belum tercatat':s.karung_awal+' karung')+pasanganMasukkan('Tiket timbang',s.tiket_id==null?'Belum tertaut':'#'+s.tiket_id)+((d.sejawat||[]).map(function(x){return pasanganMasukkan('Sumber '+x.bentuk,kgMasukkan(x.saldo_kg,x.bobot_final));}).join(''))+'</details>';
      var belum='Menunggu jumlah yang valid';
      $('mi-preview').innerHTML='<h3>Setelah dipindahkan</h3>'+pasanganMasukkan('Bentuk stok',bentuk)+(karung?pasanganMasukkan('Karung masuk silo',$('f_jumlah_karung').value||'Belum diisi'):'')+pasanganMasukkan('Berat masuk silo',d.pesan?'Belum valid':kgMasukkan(d.berat_masuk,s.bobot_final),true)+
        (karung?'<p class="mi-note">'+esc(s.rasio_kg==null?'Bobot per karung belum diketahui; tetap mengikuti timbang final.':'Bobot per karung partai: '+kgMasukkan(s.rasio_kg,s.bobot_final)+'. Berat dihitung otomatis.')+'</p>':'')+
        pasanganMasukkan('Silo tujuan',d.tujuan||'Belum dipilih')+(karung?pasanganMasukkan('Sisa karung di tumpukan',d.sisa_karung==null?belum:d.sisa_karung+' karung'):'')+pasanganMasukkan('Sisa berat sumber',d.sisa_kg==null?belum:kgMasukkan(d.sisa_kg,s.bobot_final))+
        '<p class="mi-note">Pemilik tetap '+esc(s.pemilik)+'. Belum ada stok yang dipindahkan.</p>'+(d.proses.length?'<p class="mi-warning">Silo sedang digunakan '+esc(d.proses.join(', '))+'. Bahan masuk sebagai tambahan proses tersebut; status mesin tidak diubah.</p>':'')+(d.pesan?'<p class="mi-note">'+esc(d.pesan)+'</p>':'');
      var semua=$('mi-all');semua.textContent=karung?'Isi seluruh '+s.karung+' karung':'Isi seluruh '+kgMasukkan(s.saldo_kg,s.bobot_final);
      semua.disabled=karung?!(s.karung>0):!(s.saldo_kg>0);
      $('mi-help').textContent=karung?'Isi karung utuh yang benar-benar dituang. Bobot dihitung dari sumber, bukan ukuran nominal.':curah?'Isi berat curah yang benar-benar dituang. Jumlah karung tidak berlaku.':'Jalur data lama tetap memakai bobot kg hasil timbang. Jangan menebak jumlah karung.';
    }
    function perbaruiMasukkan(e){
      if(!masukkanSilo)return;
      var asal=e&&e.target&&e.target.dataset.name;
      if(asal){
        lembar.querySelectorAll('.formulir-salah').forEach(function(x){x.remove();});
        lembar.querySelectorAll('[aria-invalid="true"]').forEach(function(x){x.removeAttribute('aria-invalid');x.removeAttribute('aria-describedby');});
        var pesanLama=lembar.querySelector('.formulir-gagal');
        if(pesanLama&&/^Periksa \d+ isian/.test(pesanLama.textContent))pesanLama.remove();
      }
      if(asal==='tumpukan'||asal==='jumlah_karung_partai'){
        ['jumlah_karung','berat_kg'].forEach(function(n){$('f_'+n).value='';});
        if(asal==='tumpukan'){$('f_jumlah_karung_partai').value='';$('f_silo').value='';}
        dataMasukkan=null;$('mi-all').disabled=true;
        ['jumlah_karung','berat_kg'].forEach(function(n){medanMasukkan(n,false,false);});
        $('mi-preview').textContent='Memuat sumber dan saldo terbaru…';
        if(asal==='tumpukan')$('mi-stock').textContent='Memuat sumber stok…';
      }
      clearTimeout(timerMasukkan);var nomor=++nomorMasukkan,borang=lembar.querySelector('.lembar__isi');
      var kunci=['tumpukan','silo','jumlah_karung','berat_kg','jumlah_karung_partai'].map(function(n){return encodeURIComponent(n)+'='+encodeURIComponent(nilaiMedan(n));}).join('&');
      if(!nilaiMedan('tumpukan')){dataMasukkan=null;gambarMasukkan(null);['jumlah_karung','berat_kg','jumlah_karung_partai'].forEach(function(n){medanMasukkan(n,false,false);});return;}
      timerMasukkan=setTimeout(function(){ambil(masukkanSilo.source+'?'+kunci).then(function(d){
        if(nomor!==nomorMasukkan||!lembar.open||lembar.querySelector('.lembar__isi')!==borang)return;
        dataMasukkan=d;gambarMasukkan(d);
      }).catch(function(err){if(nomor!==nomorMasukkan||lembar.querySelector('.lembar__isi')!==borang)return;$('mi-preview').textContent='Saldo belum dapat dibaca. Isian tetap utuh. '+String(err);});},150);
    }
    if(lembar._masukkan){lembar.removeEventListener('input',lembar._masukkan);lembar.removeEventListener('change',lembar._masukkan);}
    if(masukkanSilo){
      var grupMi=lembar.querySelector('.grup');
      (a.fields||[]).forEach(function(f){var input=grupMi.querySelector('[data-name="'+f.name+'"]'),kunci=input.type==='hidden'?input.previousElementSibling:null,label=grupMi.querySelector('label[for="f_'+f.name+'"]'),wadah=document.createElement('div');wadah.className='hasil-field';grupMi.insertBefore(wadah,label||kunci||input);if(label)wadah.appendChild(label);if(kunci){wadah.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(f.label)+'</span>');wadah.appendChild(kunci);}wadah.appendChild(input);if(f.type==='number'){var unit=document.createElement('div');unit.className='mi-count';input.before(unit);unit.appendChild(input);unit.insertAdjacentHTML('beforeend','<span>'+(['jumlah_karung','jumlah_karung_partai'].indexOf(f.name)>=0?'karung':'kg')+'</span>');if(f.name!=='berat_kg')input.inputMode='numeric';}});
      grupMi.insertAdjacentHTML('beforebegin','<p class="mi-hint">Pilih sumber stok. Satuan mengikuti bentuk stok yang tercatat.</p>');
      var layoutMi=document.createElement('div');layoutMi.className='mi-layout';grupMi.before(layoutMi);layoutMi.appendChild(grupMi);
      var stokMi=document.createElement('section');stokMi.id='mi-stock';stokMi.className='mi-stock';stokMi.setAttribute('aria-label','Saldo sumber stok tersedia');grupMi.querySelector('.hasil-field').after(stokMi);
      var tombolMi=document.createElement('div');tombolMi.className='mi-quantity-help';tombolMi.innerHTML='<p class="mi-note" id="mi-help"></p><button type="button" id="mi-all" class="btn btn--kecil" disabled>Isi seluruh</button>';grupMi.querySelector('[data-name="silo"]').closest('.hasil-field').before(tombolMi);
      var previewMi=document.createElement('aside');previewMi.className='mi-result-preview';previewMi.id='mi-preview';previewMi.setAttribute('aria-live','polite');previewMi.textContent='Pilih sumber stok untuk melihat pratinjau pemindahan.';layoutMi.appendChild(previewMi);
      $('mi-all').onclick=function(){if(!dataMasukkan||!dataMasukkan.sumber)return;var s=dataMasukkan.sumber,n=s.bentuk==='karung'?'jumlah_karung':'berat_kg';$('f_'+n).value=String(s.bentuk==='karung'?s.karung:s.saldo_kg);$('f_'+n).dispatchEvent(new Event('input',{bubbles:true}));$('f_'+n).focus();};
      ['jumlah_karung','berat_kg','jumlah_karung_partai'].forEach(function(n){medanMasukkan(n,false,false);});
      lembar._masukkan=perbaruiMasukkan;lembar.addEventListener('input',perbaruiMasukkan);lembar.addEventListener('change',perbaruiMasukkan);gambarMasukkan(null);
    }

    var nomorBroken=0,timerBroken,risikoBroken=false;
    function barisBroken(s){return '<article class="bk-source"><strong>'+esc(s.kode)+'</strong>'+pasanganMasukkan('Curah tercatat',kgMasukkan(s.curah))+pasanganMasukkan('Hasil mesin belum dialokasikan',kgMasukkan(s.mesin))+(s.packs||[]).map(function(p){return pasanganMasukkan(p.n+' karung × '+kgMasukkan(p.ukuran),kgMasukkan(p.kg));}).join('')+'</article>';}
    function gambarBroken(d){
      if(!d||!d.saldo){$('bk-stock').textContent='Pilih pemilik untuk melihat stok broken yang tersedia.';$('bk-preview').innerHTML='<h3>Rencana pemindahan</h3><p>Pilih pemilik stok broken terlebih dahulu.</p>';return;}
      var stockOpenBk=!!lembar.querySelector('#bk-stock details[open]'),planOpenBk=!!lembar.querySelector('#bk-preview details[open]');
      var s=d.saldo,p=d.rencana,locked=$('t_proses');if(locked)locked.textContent=d.pemilik+' · '+d.cakupan;
      $('bk-stock').innerHTML='<div class="mi-stock-head"><div><strong>Broken · '+esc(d.pemilik)+'</strong><small>'+esc(d.cakupan)+' · Gudang 2</small></div><span class="mi-badge">Tersedia</span></div><div class="mi-stock-values"><div><span>Total broken tersedia</span><strong>'+esc(kgMasukkan(s.total))+'</strong><small>Curah, hasil mesin, dan kemasan</small></div><div><span>Stok berkarung</span><strong>'+esc(s.karung+' karung')+'</strong><small>'+esc(kgMasukkan(s.kemasan))+' dalam kemasan</small></div></div>'+pasanganMasukkan('Curah tercatat',kgMasukkan(s.curah))+pasanganMasukkan('Hasil mesin belum dialokasikan',kgMasukkan(s.mesin))+'<details><summary>Rincian sumber dan ukuran karung</summary>'+d.sumber.map(barisBroken).join('')+'</details>';
      $('bk-preview').innerHTML='<h3>Rencana pemindahan</h3>'+(p?pasanganMasukkan('Masuk ke silo',kgMasukkan(p.kg),true):'<div class="bk-pending">'+pasanganMasukkan('Masuk ke silo','Menunggu berat yang valid')+'</div>')+pasanganMasukkan('Silo tujuan',p&&p.silo?p.silo:'Belum dipilih')+(p?pasanganMasukkan('Dari curah tercatat',kgMasukkan(p.curah))+pasanganMasukkan('Dari hasil mesin',kgMasukkan(p.mesin))+pasanganMasukkan('Dari isi karung',kgMasukkan(p.isi_karung))+(p.karung?'<p class="mi-warning"><strong>'+esc(p.karung+' karung dibongkar · '+kgMasukkan(p.bongkar_kg))+'</strong><br>'+esc(kgMasukkan(p.isi_karung))+' masuk silo; '+esc(kgMasukkan(p.kelebihan))+' tetap menjadi stok curah.</p><p class="mi-note">Karung kosong tidak ditambahkan kembali ke Stok Karung.</p>':'<p class="mi-note">Tidak perlu membongkar karung.</p>')+'<div class="bk-balance"><h4>Sisa setelah dipindahkan</h4>'+pasanganMasukkan('Curah tercatat',kgMasukkan(p.sisa.curah))+pasanganMasukkan('Hasil mesin belum dialokasikan',kgMasukkan(p.sisa.mesin))+pasanganMasukkan('Karung utuh',p.sisa.karung+' karung · '+kgMasukkan(p.sisa.kemasan))+pasanganMasukkan('Total stok broken',kgMasukkan(p.sisa.total),true)+'</div><details><summary>Urutan sumber yang dipakai</summary>'+p.urutan.map(function(u){return '<article class="bk-source"><strong>'+esc(u.kode+' · '+kgMasukkan(u.kg))+'</strong>'+pasanganMasukkan('Curah',kgMasukkan(u.curah))+pasanganMasukkan('Hasil mesin',kgMasukkan(u.mesin))+pasanganMasukkan('Isi karung',kgMasukkan(u.isi_karung))+'</article>';}).join('')+'</details>':'')+(d.pesan?'<p class="mi-warning">'+esc(d.pesan)+'</p>':'')+(d.proses_penerima.length?'<p class="mi-note">Silo digunakan '+esc(d.proses_penerima.join(', '))+'. Tambahan bahan tetap diperiksa terhadap proses sumber dan pemilik saat disimpan.</p>':'')+'<p class="mi-note">Perkiraan sebelum simpan. Belum ada pembukuan atau pemindahan stok; alokasi diperiksa ulang saat simpan.</p>';
      if(stockOpenBk&&lembar.querySelector('#bk-stock details'))lembar.querySelector('#bk-stock details').open=true;if(planOpenBk&&lembar.querySelector('#bk-preview details'))lembar.querySelector('#bk-preview details').open=true;
      if(p&&p.diminta_kg!==p.kg)$('bk-preview').insertAdjacentHTML('beforeend','<p class="mi-note">Isian '+esc(kgMasukkan(p.diminta_kg))+'; rencana mengikuti toleransi lama per baris. Hasil aktual ditampilkan setelah simpan.</p>');
    }
    function perbaruiBroken(e){
      if(!masukkanBroken)return;
      if(e&&e.target.dataset.name){lembar.querySelectorAll('.formulir-salah').forEach(function(x){x.remove();});lembar.querySelectorAll('[aria-invalid="true"]').forEach(function(x){x.removeAttribute('aria-invalid');x.removeAttribute('aria-describedby');});var errBk=lembar.querySelector('.formulir-gagal');if(errBk&&/^Periksa \d+ isian/.test(errBk.textContent))errBk.remove();}
      if(e&&e.target.dataset.name==='proses'){$('f_berat_kg').value='';$('f_silo').value='';$('bk-stock').textContent='Memuat saldo pemilik…';}
      clearTimeout(timerBroken);var n=++nomorBroken,b=lembar.querySelector('.lembar__isi'),q=['proses','silo','berat_kg'].map(function(k){return k+'='+encodeURIComponent(nilaiMedan(k));}).join('&');
      if(!nilaiMedan('proses')){gambarBroken(null);return;}
      timerBroken=setTimeout(function(){ambil(masukkanBroken.source+'?'+q).then(function(d){if(n!==nomorBroken||!lembar.open||lembar.querySelector('.lembar__isi')!==b)return;gambarBroken(d);}).catch(function(){if(n===nomorBroken&&lembar.querySelector('.lembar__isi')===b)$('bk-preview').textContent='Ringkasan belum tersedia. Isian tetap utuh; angka tidak dianggap nol.';});},150);
    }
    if(lembar._brokenSilo){lembar.removeEventListener('input',lembar._brokenSilo);lembar.removeEventListener('change',lembar._brokenSilo);}
    if(masukkanBroken){
      var gBk=lembar.querySelector('.grup');(a.fields||[]).forEach(function(f){var i=gBk.querySelector('[data-name="'+f.name+'"]'),k=i.type==='hidden'?i.previousElementSibling:null,l=gBk.querySelector('label[for="f_'+f.name+'"]'),w=document.createElement('div');w.className='hasil-field';gBk.insertBefore(w,l||k||i);if(l)w.appendChild(l);if(k){w.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(f.label)+'</span>');w.appendChild(k);}w.appendChild(i);});
      var layBk=document.createElement('div');layBk.className='mi-layout';gBk.before(layBk);layBk.appendChild(gBk);layBk.insertAdjacentHTML('beforebegin','<p class="mi-hint">Isi berat broken yang benar-benar masuk silo. Sumber diambil otomatis menurut urutan stok.</p>');
      var stockBk=document.createElement('section');stockBk.id='bk-stock';stockBk.className='mi-stock';stockBk.setAttribute('aria-label','Saldo broken tersedia');gBk.querySelector('.hasil-field').after(stockBk);
      var fldBk=$('f_berat_kg').closest('.hasil-field'),siloBk=$('f_silo').closest('.hasil-field');stockBk.after(fldBk);var countBk=document.createElement('div');countBk.className='mi-count';$('f_berat_kg').before(countBk);countBk.appendChild($('f_berat_kg'));countBk.insertAdjacentHTML('beforeend','<span>kg</span>');siloBk.insertAdjacentHTML('afterend','<p class="mi-note">Pada tiap proses sumber, curah dan hasil mesin digunakan sebelum karung dibongkar. Hasil serta proses tidak ditutup.</p>');
      var sideBk=document.createElement('aside');sideBk.id='bk-preview';sideBk.className='mi-result-preview';sideBk.setAttribute('aria-live','polite');layBk.appendChild(sideBk);gambarBroken(null);
      lembar._brokenSilo=perbaruiBroken;lembar.addEventListener('input',perbaruiBroken);lembar.addEventListener('change',perbaruiBroken);perbaruiBroken();
    }

    var urutKemas=0,timerKemas,risikoKemas=false;
    function gambarKemas(d){
      var beras=!d||d.beras;labelSimpan=beras?'Catat pengemasan':'Simpan';
      lembar.classList.toggle('lembar--kemas-beras',beras);lembar.classList.toggle('lembar--hasil',beras);
      lembar.querySelector('.lembar__kepala h2').textContent=beras?'Pengemasan beras':belah(a.label).teks;
      var labelMaks=lembar.querySelector('.maksimal-kemas span');if(labelMaks)labelMaks.textContent=beras?'Maksimal dari saldo beras':'Maksimal kemas';
      var labelMerk=lembar.querySelector('label[for="f_merk"]');if(labelMerk)labelMerk.textContent=beras?'Merek (opsional)':a.fields.filter(function(f){return f.name==='merk';})[0].label;
      var tanpaMerk=lembar.querySelector('#f_merk option[value=""]');if(tanpaMerk)tanpaMerk.textContent=beras?'Tanpa merek':'— pilih —';
      $('pk-stock').hidden=!beras;$('pk-karung').hidden=!beras;$('pk-preview').hidden=!beras;$('pk-hint').hidden=!beras;
      if(!beras){$('simpan').textContent='Simpan';return;}
      if(!risikoKemas&&!lembar._menyimpan)$('simpan').textContent='Catat pengemasan';
      if(!d){$('pk-stock').textContent='Pilih produk untuk melihat saldo yang dapat dikemas.';$('pk-karung').textContent='Pilih sumber dan ukuran untuk melihat stok karung.';$('pk-preview').innerHTML='<h3>Hasil pengemasan</h3><p class="mi-note">Pilih sumber hasil beras terlebih dahulu.</p>';return;}
      var open=!!lembar.querySelector('#pk-stock details[open]'),p=d.rencana,k=d.kemasan,s=d.saldo;
      $('pk-stock').innerHTML='<div class="mi-stock-head"><div><strong>'+esc(d.produk)+'</strong><small>'+esc(d.pemilik)+' · '+esc(d.kode)+'</small></div><span class="mi-badge">'+(d.status==='selesai'?'Sosoh selesai':'Sosoh berjalan')+'</span></div><div class="mi-stock-values"><div><span>Saldo dapat dikemas</span><strong>'+esc(kgMasukkan(s.tersedia))+'</strong><small>'+(d.status==='selesai'?'Sisa hasil pada proses dan jenis ini':'Hasil proses belum final')+'</small></div></div><details><summary>Rincian saldo sumber</summary>'+pasanganMasukkan('Hasil tercatat',kgMasukkan(s.hasil))+pasanganMasukkan('Sudah dikemas / dicatat curah',kgMasukkan(s.dialokasikan))+pasanganMasukkan('Sudah masuk silo',kgMasukkan(s.dipindah_silo))+pasanganMasukkan('Tersedia untuk dikemas',kgMasukkan(s.tersedia))+'</details>';
      if(open)lembar.querySelector('#pk-stock details').open=true;
      $('pk-karung').innerHTML=k?pasanganMasukkan('Stok karung tercatat',d.karung+' lembar')+'<p class="mi-note">'+esc(k.material+' · '+kgMasukkan(k.ukuran)+' · '+k.merek+' · '+d.pemilik)+'</p>':'Pilih kemasan untuk melihat stok karung.';
      if($('maks_jumlah_karung'))$('maks_jumlah_karung').textContent=d.maksimal==null?'Pilih ukuran karung':d.maksimal.toLocaleString('id-ID')+' karung';
      $('pk-preview').innerHTML='<h3>Hasil pengemasan</h3>'+pasanganMasukkan('Jenis dan mutu',d.produk)+pasanganMasukkan('Pemilik',d.pemilik)+(p?pasanganMasukkan('Kemasan',k.material+' '+kgMasukkan(k.ukuran))+pasanganMasukkan('Merek',k.merek)+pasanganMasukkan('Jumlah hasil kemasan',p.jumlah+' karung')+pasanganMasukkan('Total berat',kgMasukkan(p.berat),true)+'<section class="pk-remain"><h4>Setelah dicatat</h4>'+pasanganMasukkan('Sisa hasil belum dikemas',kgMasukkan(p.sisa))+pasanganMasukkan('Karung terpakai',p.jumlah+' lembar')+pasanganMasukkan('Sisa karung tercatat',p.sisa_karung+' lembar')+'</section>'+(p.sisa_karung<0?'<p class="mi-warning">Saldo karung tercatat kurang. Periksa pencatatan stok kemasan yang sesuai pemiliknya.</p>':''):'<p class="mi-note">'+esc(d.pesan||'Pilih kemasan dan isi jumlah karung untuk melihat hasilnya.')+'</p>')+(d.status!=='selesai'?'<p class="mi-warning"><strong>Hasil penyosohan belum final</strong><br>Pengemasan memakai hasil yang sudah tercatat. Proses penyosohan tetap berjalan.</p>':'')+'<p class="mi-note">Pengemasan memindahkan hasil menjadi stok barang jadi. Perkiraan ini belum mengubah stok.</p>';
    }
    function perbaruiKemas(e){
      if(!kemasBeras)return;
      if(risikoKemas&&$('simpan')){$('simpan').disabled=true;$('simpan').textContent='Perlu diperiksa';}
      var n=e&&e.target&&e.target.dataset.name;
      if(n){lembar.querySelectorAll('.formulir-salah').forEach(function(x){x.remove();});lembar.querySelectorAll('[aria-invalid="true"]').forEach(function(x){x.removeAttribute('aria-invalid');x.removeAttribute('aria-describedby');});var errPk=lembar.querySelector('.formulir-gagal');if(errPk&&!risikoKemas)errPk.remove();}
      if(n==='sumber'){$('f_jumlah_karung').value='';$('f_merk').value='';$('pk-stock').textContent='Memuat saldo sumber…';$('pk-preview').textContent='Memuat ringkasan…';}
      clearTimeout(timerKemas);var seq=++urutKemas,body=lembar.querySelector('.lembar__isi');
      if(!nilaiMedan('sumber')){gambarKemas(null);return;}
      var q=['sumber','kemasan','merk','jumlah_karung'].map(function(k){var v=nilaiMedan(k);return k+'='+encodeURIComponent(k==='jumlah_karung'?v.replace(',','.'):v);}).join('&');
      timerKemas=setTimeout(function(){ambil(kemasBeras.source+'?'+q).then(function(d){if(seq!==urutKemas||!lembar.open||lembar.querySelector('.lembar__isi')!==body)return;gambarKemas(d);}).catch(function(){if(seq===urutKemas&&lembar.querySelector('.lembar__isi')===body){$('pk-preview').textContent='Ringkasan belum tersedia. Isian tetap utuh; saldo tidak dianggap nol. Penyimpanan tetap diperiksa server.';}});},150);
    }
    if(lembar._kemasBeras){lembar.removeEventListener('input',lembar._kemasBeras);lembar.removeEventListener('change',lembar._kemasBeras);}
    if(kemasBeras){
      var grupPk=lembar.querySelector('.grup');(a.fields||[]).forEach(function(f){var i=grupPk.querySelector('[data-name="'+f.name+'"]'),isi=i.closest('.jumlah-berdampingan')||i,k=i.type==='hidden'?i.previousElementSibling:null,l=grupPk.querySelector('label[for="f_'+f.name+'"]'),w=document.createElement('div');w.className='hasil-field';grupPk.insertBefore(w,l||k||isi);if(l)w.appendChild(l);if(k){w.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(f.label)+'</span>');w.appendChild(k);}w.appendChild(isi);});
      var layPk=document.createElement('div');layPk.className='mi-layout';grupPk.before(layPk);layPk.appendChild(grupPk);layPk.insertAdjacentHTML('beforebegin','<p class="mi-hint" id="pk-hint">Pilih kemasan dan jumlah karung dari hasil beras yang tersedia.</p>');
      var stockPk=document.createElement('section');stockPk.id='pk-stock';stockPk.className='mi-stock';stockPk.setAttribute('aria-label','Saldo hasil beras yang dapat dikemas');grupPk.querySelector('[data-name="sumber"]').closest('.hasil-field').after(stockPk);
      var bagsPk=document.createElement('section');bagsPk.id='pk-karung';bagsPk.className='pk-bags';grupPk.querySelector('[data-name="merk"]').closest('.hasil-field').after(bagsPk);
      $('f_jumlah_karung').inputMode='numeric';var sidePk=document.createElement('aside');sidePk.id='pk-preview';sidePk.className='mi-result-preview';sidePk.setAttribute('aria-live','polite');layPk.appendChild(sidePk);gambarKemas(null);
      lembar._kemasBeras=perbaruiKemas;lembar.addEventListener('input',perbaruiKemas);lembar.addEventListener('change',perbaruiKemas);perbaruiKemas();
    }

    var nomorMenir=0,timerMenir,risikoMenir=false;
    function gambarMenir(d){
      if(!d){$('mn-stock').textContent='Pilih pemilik untuk melihat saldo '+jenisMn+' tersedia.';$('mn-preview').innerHTML='<h3>Rencana pemindahan</h3><p class="mi-note">Pilih pemilik stok '+jenisMn+' terlebih dahulu.</p>';$('mn-help').textContent='Isi berat yang benar-benar masuk silo.';return;}
      var so=!!lembar.querySelector('#mn-stock details[open]'),po=!!lembar.querySelector('#mn-preview details[open]'),p=d.rencana;
      $('mn-stock').innerHTML='<div class="mi-stock-head"><div><strong>'+labelMn+' · '+esc(d.pemilik)+'</strong><small>Stok pemilik terpilih · Gudang 2</small></div><span class="mi-badge">Tersedia</span></div><div class="mi-stock-values"><div><span>Total '+jenisMn+' tersedia</span><strong>'+esc(kgMasukkan(d.saldo_kg))+'</strong><small>Pengiriman dan pemindahan sebelumnya sudah diperhitungkan.</small></div></div><details><summary>Rincian saldo dan asal bahan</summary>'+pasanganMasukkan('Pengiriman curah',kgMasukkan(d.keluar_curah))+pasanganMasukkan('Pengiriman kemasan',kgMasukkan(d.keluar_kemasan))+d.sumber.map(function(r){return '<article class="mn-source"><strong>'+esc(r.kode)+' · '+esc(r.status==='selesai'?'Selesai':'Berjalan')+'</strong>'+pasanganMasukkan('Hak curah dan kemasan sebelum pindah',kgMasukkan(r.curah_pemilik+r.kemasan_pemilik))+pasanganMasukkan('Sudah dipindahkan',kgMasukkan(r.dipindah))+pasanganMasukkan('Pengiriman sudah diperhitungkan',kgMasukkan(r.keluar))+pasanganMasukkan('Tersedia dari proses ini',kgMasukkan(r.tersedia))+'</article>';}).join('')+'</details>';
      $('mn-help').classList.toggle('mi-inline-error',!!d.pesan);$('mn-help').textContent=d.pesan||'Isi berat yang benar-benar masuk silo. Desimal dapat digunakan.';
      $('mn-preview').innerHTML='<h3>Rencana pemindahan</h3>'+(p?pasanganMasukkan(''+labelMn+' masuk silo',kgMasukkan(p.kg),true):'<div class="mn-pending">'+pasanganMasukkan(''+labelMn+' masuk silo','Menunggu berat yang valid')+'</div>')+pasanganMasukkan('Silo tujuan',nilaiMedan('silo')||'Belum dipilih')+(p?'<div class="mn-impact"><strong>Sisa stok pemilik setelah dipindahkan</strong><span>'+esc(kgMasukkan(p.sisa_kg))+'</span></div><details><summary>Asal pengambilan · urutan proses</summary>'+p.fifo.map(function(r){return '<article class="mn-source"><strong>'+esc(r.kode)+'</strong>'+pasanganMasukkan('Diambil',kgMasukkan(r.kg))+pasanganMasukkan('Sisa sumber ini',kgMasukkan(r.sisa_kg))+'</article>';}).join('')+'</details>':'')+(d.peringatan_tujuan?'<p class="mi-warning">'+esc(d.peringatan_tujuan)+'</p>':'')+(d.proses_penerima.length?'<p class="mi-warning">Silo sedang dipakai '+esc(d.proses_penerima.map(function(r){return r.kode;}).join(', '))+'. '+(d.jasa_id!=null?'Stok jasa tidak boleh ditambahkan ke proses yang berjalan.':''+labelMn+' masuk sebagai tambahan bahan; proses tetap berjalan.')+'</p>':'')+'<p class="mi-note">Pemilik tetap '+esc(d.pemilik)+'. Perkiraan ini belum memindahkan stok.</p>';
      if(so&&lembar.querySelector('#mn-stock details'))lembar.querySelector('#mn-stock details').open=true;if(po&&lembar.querySelector('#mn-preview details'))lembar.querySelector('#mn-preview details').open=true;
    }
    function perbaruiMenir(e){
      if(!masukkanMenir)return;
      if(risikoMenir&&$('simpan')){$('simpan').disabled=true;$('simpan').textContent='Perlu diperiksa';}
      var nama=e&&e.target&&e.target.dataset.name;
      if(nama){lembar.querySelectorAll('.formulir-salah').forEach(function(x){x.remove();});lembar.querySelectorAll('[aria-invalid="true"]').forEach(function(x){x.removeAttribute('aria-invalid');x.removeAttribute('aria-describedby');});var err=lembar.querySelector('.formulir-gagal');if(err&&!risikoMenir)err.remove();}
      if(nama==='pemilik'){$('f_berat_kg').value='';$('mn-stock').textContent='Memuat saldo pemilik terpilih…';$('mn-preview').textContent='Memuat rencana pemindahan…';}
      clearTimeout(timerMenir);var n=++nomorMenir,b=lembar.querySelector('.lembar__isi');
      if(!nilaiMedan('pemilik')){gambarMenir(null);return;}
      var q=['pemilik','berat_kg','silo'].map(function(k){var v=nilaiMedan(k);return k+'='+encodeURIComponent(k==='berat_kg'?v.replace(',','.'):v);}).join('&');
      timerMenir=setTimeout(function(){ambil(masukkanMenir.source+'?'+q).then(function(d){if(n!==nomorMenir||!lembar.open||lembar.querySelector('.lembar__isi')!==b)return;gambarMenir(d);}).catch(function(){if(n===nomorMenir&&lembar.querySelector('.lembar__isi')===b)$('mn-preview').textContent='Ringkasan belum tersedia. Isian tetap utuh; saldo tidak dianggap nol. Penyimpanan tetap diperiksa server.';});},150);
    }
    if(lembar._menirSilo){lembar.removeEventListener('input',lembar._menirSilo);lembar.removeEventListener('change',lembar._menirSilo);}
    if(masukkanMenir){
      var grupMn=lembar.querySelector('.grup');(a.fields||[]).forEach(function(f){var i=grupMn.querySelector('[data-name="'+f.name+'"]'),k=i.type==='hidden'?i.previousElementSibling:null,l=grupMn.querySelector('label[for="f_'+f.name+'"]'),w=document.createElement('div');w.className='hasil-field';grupMn.insertBefore(w,l||k||i);if(l)w.appendChild(l);if(k){w.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(f.label)+'</span>');w.appendChild(k);}w.appendChild(i);});
      var layMn=document.createElement('div');layMn.className='mi-layout';grupMn.before(layMn);layMn.appendChild(grupMn);layMn.insertAdjacentHTML('beforebegin','<p class="mi-hint">Isi berat '+jenisMn+' yang benar-benar masuk silo. Pemilik dan asal bahan tetap tercatat.</p>');
      var stockMn=document.createElement('section');stockMn.id='mn-stock';stockMn.className='mi-stock';stockMn.setAttribute('aria-label','Saldo '+jenisMn+' tersedia');grupMn.querySelector('[data-name="pemilik"]').closest('.hasil-field').after(stockMn);
      var qtyMn=$('f_berat_kg'),unitMn=document.createElement('div');unitMn.className='mi-count';qtyMn.before(unitMn);unitMn.appendChild(qtyMn);unitMn.insertAdjacentHTML('beforeend','<span>kg</span>');unitMn.insertAdjacentHTML('afterend','<p class="mi-note" id="mn-help" aria-live="polite"></p>');stockMn.after(qtyMn.closest('.hasil-field'));
      var sideMn=document.createElement('aside');sideMn.id='mn-preview';sideMn.className='mi-result-preview';sideMn.setAttribute('aria-live','polite');layMn.appendChild(sideMn);gambarMenir(null);
      lembar._menirSilo=perbaruiMenir;lembar.addEventListener('input',perbaruiMenir);lembar.addEventListener('change',perbaruiMenir);perbaruiMenir();
    }

    var nomorBeras=0,timerBeras,risikoBeras=false;
    function barisAsalBeras(r){return '<article class="br-source"><strong>'+esc(r.kode)+'</strong><small>'+esc(r.asal)+(r.stok_id!=null?' · Stok #'+esc(r.stok_id):'')+'</small>'+pasanganMasukkan('Tersedia',kgMasukkan(r.kg))+(r.karung!=null?pasanganMasukkan('Karung',r.karung+' karung'):'')+'</article>';}
    function gambarBeras(d){
      if(!d){$('br-padanan').classList.remove('mi-inline-error');$('br-stock').textContent='Pilih jenis dan sumber stok untuk melihat saldo tersedia.';$('br-preview').innerHTML='<h3>Rencana pemindahan</h3><p class="mi-note">Pilih sumber stok beras terlebih dahulu.</p>';$('br-padanan').textContent='Input tetap dalam kg.';return;}
      var stockOpen=!!lembar.querySelector('#br-stock details[open]'),planOpen=!!lembar.querySelector('#br-preview details[open]'),p=d.rencana,kemasan=d.bentuk==='kemasan';
      var kemasanLabel=kemasan?[d.merek,d.bahan,kgMasukkan(d.ukuran)].join(' · '):'Curah · jumlah karung tidak berlaku';
      $('br-stock').innerHTML='<div class="mi-stock-head"><div><strong>'+esc(d.jenis_label)+'</strong><small>'+esc(d.pemilik)+' · Gudang 2</small></div><span class="mi-badge">'+(kemasan?'Kemasan':'Curah')+'</span></div><p class="mi-source-title">'+esc(kemasanLabel)+'</p><div class="mi-stock-values"><div><span>Berat sumber tersedia</span><strong>'+esc(kgMasukkan(d.saldo_kg))+'</strong><small>Saldo sumber yang dipilih</small></div><div><span>Jumlah karung tersedia</span><strong>'+esc(kemasan?d.karung+' karung':'Tidak berlaku')+'</strong><small>'+(kemasan?'Hanya merek dan kemasan ini':'Stok curah tetap dihitung dalam kg')+'</small></div></div><details><summary>Asal stok · urutan FIFO</summary>'+d.fifo.map(barisAsalBeras).join('')+(d.fifo.length?'':'<p class="mi-note">Tidak ada saldo sumber yang tersedia.</p>')+'</details>';
      $('br-padanan').classList.toggle('mi-inline-error',!!d.pesan);$('br-padanan').textContent=d.pesan?d.pesan:p&&kemasan?'Setara '+p.karung+' karung × '+kgMasukkan(d.ukuran)+'.':kemasan?'Isi berat sesuai kelipatan '+kgMasukkan(d.ukuran)+'.':'Input curah dalam kg. Kemasan tidak diambil untuk menutup kekurangan.';
      $('br-preview').innerHTML='<h3>Rencana pemindahan</h3>'+(p?pasanganMasukkan('Berat masuk silo',kgMasukkan(p.kg),true):'<div class="br-pending">'+pasanganMasukkan('Berat masuk silo','Menunggu berat yang valid')+'</div>')+(p&&kemasan?pasanganMasukkan('Karung dibongkar',p.karung+' karung'):'')+pasanganMasukkan('Silo tujuan',nilaiMedan('silo')||'Belum dipilih')+(p?'<div class="br-balance"><h4>Sisa sumber setelah dipindahkan</h4>'+pasanganMasukkan('Berat tersedia',kgMasukkan(p.sisa_kg),true)+(kemasan?pasanganMasukkan('Karung utuh',p.sisa_karung+' karung'):'')+'</div>':'')+'<p class="mi-note">'+(kemasan?'Seluruh isi karung yang dibongkar masuk silo. ':'')+'Stok kemasan lain dan curah yang tidak dipilih tetap tersedia.</p>'+(p?'<details><summary>Rincian sumber yang dipakai</summary>'+p.fifo.map(function(r){return '<article class="br-source"><strong>'+esc(r.kode)+'</strong><small>'+esc(r.asal)+(r.stok_id!=null?' · Stok #'+esc(r.stok_id):'')+'</small>'+pasanganMasukkan('Masuk silo',kgMasukkan(r.kg))+(r.karung!=null?pasanganMasukkan('Karung',r.karung+' karung'):'')+'</article>';}).join('')+'</details>':'')+(d.peringatan_tujuan?'<p class="mi-warning">'+esc(d.peringatan_tujuan)+'</p>':'')+(d.proses_penerima.length?'<p class="mi-warning">Silo sedang dipakai '+esc(d.proses_penerima.map(function(x){return x.kode;}).join(', '))+'. '+(d.jasa_id!=null?'Beras jasa tidak dapat ditambahkan ke proses yang berjalan.':'Tambahan bahan dan seluruh proses asal diperiksa kembali saat simpan.')+'</p>':'')+'<p class="mi-note">Pemilik: '+esc(d.pemilik)+'. Perkiraan ini belum memindahkan stok.</p>';
      if(stockOpen&&lembar.querySelector('#br-stock details'))lembar.querySelector('#br-stock details').open=true;if(planOpen&&lembar.querySelector('#br-preview details'))lembar.querySelector('#br-preview details').open=true;
    }
    function perbaruiBeras(e){
      if(!masukkanBeras)return;
      var nama=e&&e.target&&e.target.dataset.name;
      if(nama){lembar.querySelectorAll('.formulir-salah').forEach(function(x){x.remove();});lembar.querySelectorAll('[aria-invalid="true"]').forEach(function(x){x.removeAttribute('aria-invalid');x.removeAttribute('aria-describedby');});var err=lembar.querySelector('.formulir-gagal');if(err&&!risikoBeras)err.remove();}
      if(nama==='jenis'||nama==='sumber_stok'){$('f_berat_kg').value='';if(nama==='jenis'&&$('f_sumber_stok'))$('f_sumber_stok').value='';$('br-stock').textContent='Memuat saldo sumber terpilih…';$('br-preview').textContent='Memuat rencana pemindahan…';}
      clearTimeout(timerBeras);var n=++nomorBeras,b=lembar.querySelector('.lembar__isi');
      if(!nilaiMedan('jenis')||!nilaiMedan('sumber_stok')){gambarBeras(null);return;}
      var q=['jenis','sumber_stok','berat_kg','silo'].map(function(k){var v=nilaiMedan(k);return k+'='+encodeURIComponent(k==='berat_kg'?v.replace(',','.'):v);}).join('&');
      timerBeras=setTimeout(function(){ambil(masukkanBeras.source+'?'+q).then(function(d){if(n!==nomorBeras||!lembar.open||lembar.querySelector('.lembar__isi')!==b)return;gambarBeras(d);}).catch(function(){if(n===nomorBeras&&lembar.querySelector('.lembar__isi')===b)$('br-preview').textContent='Ringkasan belum tersedia. Isian tetap utuh; saldo tidak dianggap nol. Penyimpanan tetap diperiksa server.';});},150);
    }
    if(lembar._berasSilo){lembar.removeEventListener('input',lembar._berasSilo);lembar.removeEventListener('change',lembar._berasSilo);}
    if(masukkanBeras){
      var grupBr=lembar.querySelector('.grup');(a.fields||[]).forEach(function(f){var i=grupBr.querySelector('[data-name="'+f.name+'"]'),k=i.type==='hidden'?i.previousElementSibling:null,l=grupBr.querySelector('label[for="f_'+f.name+'"]'),w=document.createElement('div');w.className='hasil-field';grupBr.insertBefore(w,l||k||i);if(l)w.appendChild(l);if(k){w.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(f.label)+'</span>');w.appendChild(k);}w.appendChild(i);});
      var layBr=document.createElement('div');layBr.className='mi-layout';grupBr.before(layBr);layBr.appendChild(grupBr);layBr.insertAdjacentHTML('beforebegin','<p class="mi-hint">Pilih sumber beras, isi berat, lalu tentukan silo tujuan.</p>');
      var stockBr=document.createElement('section');stockBr.id='br-stock';stockBr.className='mi-stock';stockBr.setAttribute('aria-label','Saldo sumber beras tersedia');grupBr.querySelector('[data-name="sumber_stok"]').closest('.hasil-field').after(stockBr);
      var qtyBr=$('f_berat_kg'),unitBr=document.createElement('div');unitBr.className='mi-count';qtyBr.before(unitBr);unitBr.appendChild(qtyBr);unitBr.insertAdjacentHTML('beforeend','<span>kg</span>');unitBr.insertAdjacentHTML('afterend','<p class="mi-note" id="br-padanan" aria-live="polite"></p>');
      var sideBr=document.createElement('aside');sideBr.id='br-preview';sideBr.className='mi-result-preview';sideBr.setAttribute('aria-live','polite');layBr.appendChild(sideBr);gambarBeras(null);
      lembar._berasSilo=perbaruiBeras;lembar.addEventListener('input',perbaruiBeras);lembar.addEventListener('change',perbaruiBeras);perbaruiBeras();
    }

    function aturUnitPk() {
      if (!unitTransferPk) return;
      var karung = $('f_cara').value === 'karung';
      ['jumlah_karung', 'berat_curah_kg', 'berat'].forEach(function (nama) {
        var input = $('f_' + nama), nonaktif = nama === 'berat' ? karung : !karung;
        input.disabled = nonaktif;
        input.hidden = nonaktif;
        input.dataset.pratinjauNonaktif = nonaktif ? '1' : '';
        input.closest('.hasil-field').hidden = nonaktif;
        var label = lembar.querySelector('label[for="f_' + nama + '"]');
        if (label) label.hidden = nonaktif;
      });
      $('f_berat').toggleAttribute('data-wajib', !karung);
    }
    if (unitTransferPk) {
      var grupUnit = lembar.querySelector('.grup');
      (a.fields || []).filter(function (f) { return f.type !== 'pratinjau'; }).forEach(function (f) {
        var input = grupUnit.querySelector('[data-name="' + f.name + '"]');
        var kunci = input.type === 'hidden' ? input.previousElementSibling : null;
        var label = grupUnit.querySelector('label[for="f_' + f.name + '"]');
        var wadah = document.createElement('div'); wadah.className = 'hasil-field';
        grupUnit.insertBefore(wadah, label || kunci || input);
        if (label) wadah.appendChild(label);
        if (kunci) {
          wadah.insertAdjacentHTML('beforeend', '<span class="lbl">' + esc(f.label) + '</span>');
          wadah.appendChild(kunci);
          kunci.setAttribute('role', 'textbox'); kunci.setAttribute('aria-readonly', 'true');
          kunci.setAttribute('aria-label', f.label);
        }
        wadah.appendChild(input);
        if (f.type === 'number') {
          var satuan = document.createElement('div'); satuan.className = 'unit-pk-input';
          input.before(satuan); satuan.appendChild(input);
          satuan.insertAdjacentHTML('beforeend', '<span>' + (f.name === 'jumlah_karung' ? 'karung' : 'kg') + '</span>');
          if (f.name === 'jumlah_karung') input.inputMode = 'numeric';
        }
      });
      var layoutUnit = document.createElement('div'); layoutUnit.className = 'unit-pk-layout';
      grupUnit.before(layoutUnit); layoutUnit.appendChild(grupUnit);
      var asideUnit = document.createElement('aside'); asideUnit.className = 'unit-pk-summary';
      asideUnit.innerHTML = '<h3>Ringkasan ' + (unitTransferPk === 'minta' ? 'permintaan' : 'muatan aktual') + '</h3>';
      layoutUnit.appendChild(asideUnit); asideUnit.appendChild($('p_unit_pk'));
      asideUnit.insertAdjacentHTML('beforeend', '<p class="hasil-help">Satu karung PK sendiri = 50 kg. Isi curah atau bagian karung dalam kg. Untuk seluruh muatan hasil timbang, pilih cara kg.</p><p class="unit-pk-impact">' +
        (unitTransferPk === 'minta' ? 'Permintaan belum memindahkan stok. Admin menetapkan tujuan dan batas bobot; Gudang 1 mencatat muatan aktual.' : 'Catat yang benar-benar dimuat. Muatan boleh kurang dari persetujuan. Stok berpindah saat pengiriman tercatat; Admin menutupnya setelah itu.') + '</p>');
      $('f_cara').addEventListener('change', aturUnitPk);
      aturUnitPk();
    }

    // Hanya bantuan baca: tiga input/handler asli tetap mengirim TOTAL.
    // Kegagalan ringkasan tidak mematikan Simpan atau mengosongkan isian.
    var borangHasil = lembar.querySelector(".lembar__isi"), acuanHasil = null;
    var urutanHasil = 0, kunciHasil = "";
    function kgHasil(n) {
      if (n === null || !Number.isFinite(Number(n))) return "Belum tersedia";
      var bagian = String(n).split("e"), desimal = bagian[0].split(".");
      return desimal[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".") +
        (desimal.length > 1 ? "," + desimal[1] : "") + (bagian[1] ? "e" + bagian[1] : "") + " kg";
    }
    // Selisih bantuan ditulis sebagai desimal tanpa membulatkan input atau
    // memperlihatkan ekor biner (misalnya 700,2 − 700). Payload tetap Number
    // dari parser lama; layanan menghitung tambahan sebenarnya saat Simpan.
    function bedaDesimalHasil(total, lama) {
      var a = total.split("."), b = lama.split(".");
      if (!/^[+-]?\d+(?:\.\d+)?$/.test(lama)) return String(Number(total) - Number(lama));
      var skala = Math.max((a[1] || "").length, (b[1] || "").length);
      function bulat(p) { return BigInt(p[0] + (p[1] || "").padEnd(skala, "0")); }
      var beda = bulat(a) - bulat(b), negatif = beda < 0n;
      var teks = String(negatif ? -beda : beda).padStart(skala + 1, "0");
      if (skala) teks = (teks.slice(0, -skala) + "." + teks.slice(-skala)).replace(/0+$/, "").replace(/\.$/, "");
      return (negatif ? "-" : "") + teks;
    }
    function gambarRingkasanHasil() {
      if (!hasilKumulatif || !borangHasil.isConnected) return;
      var teks = nilaiMedan(hasilKumulatif.total).trim();
      var valid = /^[+-]?\d+(?:[.,]\d+)?$/.test(teks);
      var total = valid ? Number(teks.replace(",", ".")) : NaN;
      $("hasil-total").textContent = teks ? kgHasil(total) : "Belum diisi";
      var lama = acuanHasil && acuanHasil.tercatat;
      var delta = Number.isFinite(lama) && Number.isFinite(total) ? bedaDesimalHasil(teks.replace(",", "."), String(lama)) : null;
      $("hasil-tambahan").textContent = delta !== null ? (Number(delta) > 0 ? "+" : "") + kgHasil(delta) : "Belum tersedia";
      $("hasil-sebelum").textContent = Number.isFinite(lama) ? kgHasil(lama) :
        (nilaiMedan(hasilKumulatif.jenis) ? "Belum tersedia" : "Pilih jenis hasil");
    }
    function perbaruiRingkasanHasil(paksa) {
      if (!hasilKumulatif || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return;
      var kode = nilaiMedan(hasilKumulatif.proses), jenis = nilaiMedan(hasilKumulatif.jenis);
      var kunci = kode + "|" + jenis;
      if (kunci === kunciHasil && paksa !== true) { gambarRingkasanHasil(); return; }
      kunciHasil = kunci; acuanHasil = null;
      var nomor = ++urutanHasil;
      $("hasil-pemilik").textContent = kode ? "Memuat pemilik dan proses…" : "Pilih proses penyosohan";
      $("hasil-status").textContent = ""; $("hasil-milik").textContent = "";
      $("hasil-silos").textContent = kode ? "Konteks belum tersedia." : "Daftar mengikuti proses aktif yang dapat Anda akses.";
      gambarRingkasanHasil();
      if (!kode) return;
      fetch(hasilKumulatif.source + "?kode_proses=" + encodeURIComponent(kode) + "&jenis=" + encodeURIComponent(jenis),
        {credentials: "same-origin", cache: "no-store"}).then(function (r) {
        if (!r.ok) throw new Error("Ringkasan belum tersedia");
        return r.json();
      }).then(function (data) {
        if (nomor !== urutanHasil || lembar.querySelector(".lembar__isi") !== borangHasil || !lembar.open ||
            nilaiMedan(hasilKumulatif.proses) !== kode || nilaiMedan(hasilKumulatif.jenis) !== jenis) return;
        if (data.kode_proses !== kode || data.jenis !== jenis) throw new Error("Ringkasan tidak sesuai pilihan");
        acuanHasil = data;
        $("hasil-pemilik").textContent = data.pemilik || "Pemilik belum tercatat";
        $("hasil-milik").textContent = data.kepemilikan || "";
        $("hasil-status").textContent = ({berjalan:"Berjalan",dijeda:"Dijeda",selesai:"Selesai"})[data.status] || "Status belum diketahui";
        $("hasil-status").classList.toggle("lencana--hati", data.status === "dijeda");
        $("hasil-silos").textContent = (data.silos || []).map(function (s) { return s.nama + (s.dipakai ? "" : " (dilepas)"); }).join(" + ") || "Pemakaian silo belum tercatat.";
        if (data.sebab_jeda) $("hasil-silos").textContent += " · Jeda: " + data.sebab_jeda;
        gambarRingkasanHasil();
      }).catch(function () {
        if (nomor !== urutanHasil || lembar.querySelector(".lembar__isi") !== borangHasil || !lembar.open) return;
        acuanHasil = null;
        $("hasil-pemilik").textContent = "Konteks proses belum tersedia";
        $("hasil-silos").textContent = "Isian tetap utuh. Penyimpanan memeriksa data terbaru di server.";
        gambarRingkasanHasil();
      });
    }
    if (hasilKumulatif) {
      borangHasil.querySelector(".lembar__kepala").insertAdjacentHTML("afterend",
        '<div class="hasil-context"><div><span id="hasil-milik"></span><span class="lencana" id="hasil-status"></span></div>' +
        '<strong id="hasil-pemilik"></strong><small id="hasil-silos"></small></div>');
      var grupHasil = borangHasil.querySelector(".grup");
      [hasilKumulatif.proses, hasilKumulatif.jenis, hasilKumulatif.total].forEach(function (nama) {
        var input = grupHasil.querySelector('[data-name="' + nama + '"]');
        if (!input) return;
        var label = input.type === "hidden" ? null : grupHasil.querySelector('label[for="' + input.id + '"]');
        var terkunciHasil = input.type === "hidden" ? input.previousElementSibling : null;
        var wadah = document.createElement("div"); wadah.className = "hasil-field";
        grupHasil.insertBefore(wadah, label || terkunciHasil || input);
        if (!label) { label = document.createElement("span"); label.className = "lbl"; label.textContent = input.dataset.label; }
        wadah.appendChild(label);
        if (terkunciHasil) { wadah.appendChild(terkunciHasil); terkunciHasil.setAttribute("role", "textbox"); terkunciHasil.setAttribute("aria-label", input.dataset.label); terkunciHasil.setAttribute("aria-readonly", "true"); }
        wadah.appendChild(input);
        if (terkunciHasil) wadah.insertAdjacentHTML("beforeend", '<small class="hasil-help">Terisi dari proses yang dibuka.</small>');
        if (nama === hasilKumulatif.jenis) wadah.insertAdjacentHTML("beforeend", '<div class="hasil-before" role="status" aria-live="polite"><span>Sudah tercatat</span><strong id="hasil-sebelum">Pilih jenis hasil</strong></div>');
        if (nama === hasilKumulatif.total) {
          var unit = document.createElement("div"); unit.className = "hasil-unit"; wadah.appendChild(unit); unit.appendChild(input);
          unit.insertAdjacentHTML("beforeend", '<span aria-hidden="true">kg</span>');
          wadah.insertAdjacentHTML("beforeend", '<p class="hasil-help" id="hasil-hint">Isi <strong>total sejak awal proses</strong>, bukan hanya tambahannya.</p>');
          input.setAttribute("aria-describedby", "hasil-hint");
        }
      });
      borangHasil.querySelector(".hasil-actions").insertAdjacentHTML("beforebegin",
        '<div class="hasil-preview" role="status" aria-live="polite" aria-atomic="true"><div><span>Total setelah dicatat</span><strong id="hasil-total">Belum diisi</strong></div>' +
        '<div><span>Perkiraan tambahan</span><strong id="hasil-tambahan">Belum tersedia</strong></div><small>Tambahan akhir mengikuti catatan terbaru saat disimpan.</small></div>');
      borangHasil.addEventListener("input", function () { gambarRingkasanHasil(); });
      borangHasil.addEventListener("change", function (e) {
        if ([hasilKumulatif.proses, hasilKumulatif.jenis].indexOf(e.target.dataset.name) !== -1) perbaruiRingkasanHasil();
      });
      perbaruiRingkasanHasil();
    }

    // Penggilingan mencatat kumulatif terbaru, termasuk penurunan dan
    // nilai sama. Selisih di sini hanya pembanding, bukan mutasi stok.
    var acuanGiling = null, nomorGiling = 0, waktuGiling;
    function gambarRingkasanGiling() {
      if (!hasilGiling || !borangHasil.isConnected) return;
      var teks = nilaiMedan(hasilGiling.total).trim();
      var sah = /^[+-]?\d+(?:[.,]\d+)?$/.test(teks);
      var total = sah ? Number(teks.replace(",", ".")) : NaN;
      $("giling-total").textContent = teks ? kgHasil(total) : "Belum diisi";
      var lama = acuanGiling && acuanGiling.tercatat;
      var valid = Number.isFinite(total) && total > 0;
      var delta = Number.isFinite(lama) && valid ? bedaDesimalHasil(teks.replace(",", "."), String(lama)) : null;
      $("giling-perubahan").textContent = delta !== null ? (Number(delta) > 0 ? "+" : "") + kgHasil(delta) : "Belum tersedia";
      $("giling-sebelum").textContent = Number.isFinite(lama) ? kgHasil(lama) : (acuanGiling ? "Belum dicatat" : "Belum tersedia");
      if (!valid) {
        $("giling-total").textContent = teks ? "Isian belum valid" : "Belum diisi";
        $("giling-perubahan").textContent = "Belum dapat dihitung";
        $("giling-rendemen").textContent = "Belum dapat dihitung";
        $("giling-catatan").textContent = teks ? "Masukkan PK kumulatif yang valid dan lebih dari nol." : "Isi PK kumulatif untuk melihat ringkasan.";
        return;
      }
      $("giling-catatan").textContent = delta !== null && Number(delta) < 0
        ? "Kumulatif boleh turun untuk membetulkan catatan proses berjalan. Perubahan ini hanya pembanding."
        : delta !== null && Number(delta) === 0 ? "Nilai sama tetap mengikuti pencatatan penggilingan."
        : "Perubahan dibandingkan dengan catatan terakhir. Data diperiksa saat disimpan.";
    }
    function perbaruiRingkasanGiling() {
      if (!hasilGiling || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return;
      clearTimeout(waktuGiling);
      var kode = nilaiMedan(hasilGiling.proses), teks = nilaiMedan(hasilGiling.total).trim();
      var nomor = ++nomorGiling;
      if (!acuanGiling || acuanGiling.kode_proses !== kode) {
        acuanGiling = null;
        $("giling-pemilik").textContent = kode ? "Memuat pemilik dan proses…" : "Pilih proses penggilingan";
        ["giling-milik", "giling-status", "giling-jenis"].forEach(function (id) { $(id).textContent = ""; });
        $("giling-silos").textContent = kode ? "Konteks belum tersedia." : "Daftar mengikuti proses aktif yang dapat Anda akses.";
        $("giling-bobot").textContent = "Belum diketahui";
        $("giling-label-bobot").textContent = "Bobot gabah acuan";
        $("giling-label-rendemen").textContent = "Perkiraan rendemen";
      }
      $("giling-rendemen").textContent = kode && teks ? "Menghitung…" : "Belum dapat dihitung";
      gambarRingkasanGiling();
      if (!kode) return;
      var angka = /^[+-]?\d+(?:[.,]\d+)?$/.test(teks) ? Number(teks.replace(",", ".")) : NaN;
      var url = hasilGiling.source + "?kode_proses=" + encodeURIComponent(kode);
      if (Number.isFinite(angka) && angka > 0) url += "&berat_kumulatif=" + encodeURIComponent(angka);
      // Pembaca server memakai helper rendemen yang sama. Penundaan hanya
      // menghemat permintaan saat mengetik; isian/fokus tidak pernah diganti.
      waktuGiling = setTimeout(function () {
        fetch(url, {credentials:"same-origin", cache:"no-store"}).then(function (r) {
          if (!r.ok) throw new Error("Ringkasan belum tersedia");
          return r.json();
        }).then(function (data) {
          if (nomor !== nomorGiling || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil ||
              nilaiMedan(hasilGiling.proses) !== kode || nilaiMedan(hasilGiling.total).trim() !== teks) return;
          if (data.kode_proses !== kode) throw new Error("Ringkasan tidak sesuai pilihan");
          acuanGiling = data;
          $("giling-pemilik").textContent = data.pemilik || "Pemilik belum tercatat";
          $("giling-milik").textContent = data.kepemilikan || "";
          $("giling-status").textContent = ({berjalan:"Berjalan",dijeda:"Dijeda",selesai:"Selesai"})[data.status] || "Status belum diketahui";
          $("giling-status").classList.toggle("lencana--hati", data.status === "dijeda");
          $("giling-silos").textContent = (data.silos || []).join(" + ") || "Sumber silo belum tercatat.";
          if (data.sebab_jeda) $("giling-silos").textContent += " · Jeda: " + data.sebab_jeda;
          $("giling-jenis").textContent = data.jenis_pk ? "Jenis PK dari asal bahan · " + data.jenis_pk : "Jenis PK belum diketahui";
          $("giling-bobot").textContent = data.bobot_acuan === null ? "Belum diketahui" : kgHasil(data.bobot_acuan);
          $("giling-label-bobot").textContent = "Bobot gabah acuan" + (data.bobot_acuan === null ? "" : data.bobot_final ? " · final" : " · sementara");
          $("giling-label-rendemen").textContent = "Perkiraan rendemen" + (data.bobot_final ? "" : " · sementara");
          $("giling-rendemen").textContent = data.rendemen_teks || "Belum dapat dihitung";
          gambarRingkasanGiling();
        }).catch(function () {
          if (nomor !== nomorGiling || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return;
          acuanGiling = null;
          $("giling-pemilik").textContent = "Konteks proses belum tersedia";
          ["giling-milik", "giling-status", "giling-jenis"].forEach(function (id) { $(id).textContent = ""; });
          $("giling-silos").textContent = "Isian tetap utuh. Penyimpanan memeriksa data terbaru di server.";
          $("giling-bobot").textContent = "Belum diketahui";
          $("giling-label-bobot").textContent = "Bobot gabah acuan";
          $("giling-label-rendemen").textContent = "Perkiraan rendemen";
          $("giling-rendemen").textContent = "Belum dapat dihitung";
          gambarRingkasanGiling();
        });
      }, 150);
    }
    if (hasilGiling) {
      borangHasil.querySelector(".lembar__kepala").insertAdjacentHTML("afterend",
        '<div class="hasil-context giling-context"><div><span id="giling-milik"></span><span class="lencana" id="giling-status"></span></div>' +
        '<strong id="giling-pemilik"></strong><small id="giling-silos"></small><small id="giling-jenis"></small>' +
        '<div class="giling-basis"><span id="giling-label-bobot">Bobot gabah acuan</span><strong id="giling-bobot">Belum diketahui</strong></div></div>');
      var grupGiling = borangHasil.querySelector(".grup");
      [hasilGiling.proses, hasilGiling.total].forEach(function (nama) {
        var input = grupGiling.querySelector('[data-name="' + nama + '"]');
        if (!input) return;
        var label = input.type === "hidden" ? null : grupGiling.querySelector('label[for="' + input.id + '"]');
        var terkunci = input.type === "hidden" ? input.previousElementSibling : null;
        var wadah = document.createElement("div"); wadah.className = "hasil-field";
        grupGiling.insertBefore(wadah, label || terkunci || input);
        if (!label) { label = document.createElement("span"); label.className = "lbl"; label.textContent = input.dataset.label; }
        wadah.appendChild(label);
        if (terkunci) { wadah.appendChild(terkunci); terkunci.setAttribute("role", "textbox"); terkunci.setAttribute("aria-label", input.dataset.label); terkunci.setAttribute("aria-readonly", "true"); }
        wadah.appendChild(input);
        if (nama === hasilGiling.proses) {
          if (terkunci) wadah.insertAdjacentHTML("beforeend", '<small class="hasil-help">Terisi dari proses yang dibuka.</small>');
          wadah.insertAdjacentHTML("afterend", '<div class="hasil-before" role="status" aria-live="polite"><span>PK terakhir tercatat</span><strong id="giling-sebelum">Belum tersedia</strong></div>');
        } else {
          var unit = document.createElement("div"); unit.className = "hasil-unit"; wadah.appendChild(unit); unit.appendChild(input);
          unit.insertAdjacentHTML("beforeend", '<span aria-hidden="true">kg</span>');
          wadah.insertAdjacentHTML("beforeend", '<p class="hasil-help" id="giling-hint">Isi <strong>total PK sejak awal proses</strong>, bukan hanya tambahannya.</p>');
          input.setAttribute("aria-describedby", "giling-hint");
        }
      });
      borangHasil.querySelector(".hasil-actions").insertAdjacentHTML("beforebegin",
        '<div class="hasil-preview" role="status" aria-live="polite" aria-atomic="true"><div><span>Total PK dari isian</span><strong id="giling-total">Belum diisi</strong></div>' +
        '<div><span>Perubahan dari catatan terakhir</span><strong id="giling-perubahan">Belum tersedia</strong></div>' +
        '<div><span id="giling-label-rendemen">Perkiraan rendemen</span><strong id="giling-rendemen">Belum dapat dihitung</strong></div><small id="giling-catatan"></small></div>');
      borangHasil.addEventListener("input", perbaruiRingkasanGiling);
      borangHasil.addEventListener("change", function (e) { if (e.target.dataset.name === hasilGiling.proses) perbaruiRingkasanGiling(); });
      perbaruiRingkasanGiling();
    }

    // Bacaan alat tes dan mesin tetap terpisah. Browser mengirim isian
    // untuk bantuan baca; rumus dan ambang dijawab helper resmi di server.
    var dataAir = null, urutanAir = 0, timerAir;
    function isianAir() {
      var tes = [], salah = false;
      function angka(teks) {
        teks = String(teks || "").trim();
        if (!teks) return null;
        var n = /^[+-]?\d+(?:[.,]\d+)?$/.test(teks) ? Number(teks.replace(",", ".")) : NaN;
        if (!Number.isFinite(n) || n <= 0 || n > 100) { salah = true; return null; }
        return n;
      }
      borangHasil.querySelectorAll('[data-ulang-untuk="tes"] input').forEach(function (e) { var n = angka(e.value); if (n !== null) tes.push(n); });
      var mesin = angka(nilaiMedan("indikator"));
      return {tes:tes, mesin:mesin, salah:salah};
    }
    function gambarAir(isi, memuat) {
      if (!kadarAir) return;
      ["rata", "sebar", "mesin", "selisih"].forEach(function (nama) {
        $("air-" + nama).textContent = isi.salah ? "Isian belum valid" : memuat ? "Memuat…" :
          dataAir ? dataAir[nama + "_teks"] : (nama === "sebar" && isi.tes.length < 2 ? "Perlu minimal dua titik" : nama === "mesin" ? (isi.mesin === null ? "Belum diisi" : "Belum tersedia") : "Belum dapat dihitung");
      });
      $("air-jumlah").textContent = isi.salah ? "Periksa bacaan yang diisi" : isi.tes.length + " titik terukur";
      $("air-peringatan").textContent = !isi.salah && !memuat && dataAir ? (dataAir.peringatan || []).join("\n") : "";
      $("air-peringatan").hidden = !$("air-peringatan").textContent;
    }
    function perbaruiRingkasanAir() {
      if (!formAir || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return;
      clearTimeout(timerAir);
      var kode = nilaiMedan(formAir.proses), isi = isianAir(), nomor = ++urutanAir;
      if (!dataAir || dataAir.kode_lot !== kode) {
        dataAir = null;
        $("air-pemilik").textContent = kode ? "Memuat pemilik dan pengeringan…" : "Pilih pengeringan";
        ["air-milik","air-status"].forEach(function (id) { $(id).textContent = ""; });
        $("air-sumber").textContent = "Konteks belum tersedia.";
        $("air-target").textContent = "Belum tercatat";
      }
      gambarAir(isi, !!kode && !isi.salah && (isi.tes.length > 0 || isi.mesin !== null));
      if (!kode) return;
      var url = formAir.source + "?kode_lot=" + encodeURIComponent(kode);
      if (!isi.salah) {
        isi.tes.forEach(function (n) { url += "&tes=" + encodeURIComponent(n); });
        if (isi.mesin !== null) url += "&indikator=" + encodeURIComponent(isi.mesin);
      }
      timerAir = setTimeout(function () {
        fetch(url,{credentials:"same-origin",cache:"no-store"}).then(function (r) {
          if (!r.ok) throw new Error("Ringkasan belum tersedia");
          return r.json();
        }).then(function (d) {
          if (nomor !== urutanAir || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil || nilaiMedan(formAir.proses) !== kode) return;
          if (d.kode_lot !== kode) throw new Error("Konteks tidak sesuai pengeringan");
          dataAir = d;
          $("air-pemilik").textContent = d.pemilik || "Pemilik belum tercatat";
          $("air-milik").textContent = d.kepemilikan || "";
          $("air-status").textContent = ({berjalan:"Berjalan",dijeda:"Dijeda",selesai:"Selesai"})[d.status] || "Status belum diketahui";
          $("air-status").classList.toggle("lencana--hati", d.status === "dijeda");
          $("air-sumber").textContent = d.dryer + " · Bahan " + d.bahan + (d.sebab_jeda ? " · Jeda: " + d.sebab_jeda : "");
          $("air-target").textContent = d.target_teks || "Belum tercatat";
          gambarAir(isi, false);
        }).catch(function () {
          if (nomor !== urutanAir || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return;
          dataAir = null;
          $("air-pemilik").textContent = "Konteks pengeringan belum tersedia";
          ["air-milik","air-status"].forEach(function (id) { $(id).textContent = ""; });
          $("air-sumber").textContent = "Isian tetap utuh. Penyimpanan memeriksa data server.";
          $("air-target").textContent = "Belum tersedia";
          gambarAir(isi, false);
        });
      },150);
    }
    if (formAir) {
      borangHasil.querySelector(".lembar__kepala").insertAdjacentHTML("afterend",
        '<div class="hasil-context"><div><span id="air-milik"></span><span class="lencana" id="air-status"></span></div>' +
        '<strong id="air-pemilik"></strong><small id="air-sumber"></small>' +
        '<div class="giling-basis"><span>Target pengeringan saat ini</span><strong id="air-target">Belum tercatat</strong></div></div>');
      var grupAir = borangHasil.querySelector(".grup");
      ["kode_lot", kadarAir ? "indikator" : "target"].forEach(function (nama) {
        var input = grupAir.querySelector('[data-name="' + nama + '"]');
        if (!input) return;
        var label = input.type === "hidden" ? null : grupAir.querySelector('label[for="' + input.id + '"]');
        var terkunci = input.type === "hidden" ? input.previousElementSibling : null;
        var wadah = document.createElement("div"); wadah.className = "hasil-field";
        grupAir.insertBefore(wadah, label || terkunci || input);
        if (!label) { label = document.createElement("span"); label.className = "lbl"; label.textContent = input.dataset.label; }
        wadah.appendChild(label);
        if (terkunci) { wadah.appendChild(terkunci); terkunci.setAttribute("role","textbox"); terkunci.setAttribute("aria-label",input.dataset.label); terkunci.setAttribute("aria-readonly","true"); }
        wadah.appendChild(input);
        if (nama === "kode_lot") {
          if (terkunci) wadah.insertAdjacentHTML("beforeend",'<small class="hasil-help">Terisi dari pengeringan yang dibuka.</small>');
        } else {
          var unit = document.createElement("div"); unit.className="hasil-unit";wadah.appendChild(unit);unit.appendChild(input);
          unit.insertAdjacentHTML("beforeend",'<span aria-hidden="true">%</span>');
          if (kadarAir) { wadah.classList.add("kadar-mesin");wadah.insertAdjacentHTML("beforeend",'<p class="hasil-help">Opsional. Bacaan mesin tidak ikut rata-rata alat tes.</p>'); }
        }
      });
      if (kadarAir) {
        var titik = grupAir.querySelector('[data-ulang-untuk="tes"]'), labelTitik = grupAir.querySelector('label[for="f_tes"]');
        var bagian = document.createElement("section");bagian.className="kadar-alat";bagian.setAttribute("aria-label","Titik alat tes");
        grupAir.insertBefore(bagian,labelTitik);bagian.appendChild(labelTitik);labelTitik.removeAttribute("for");
        bagian.insertAdjacentHTML("beforeend",'<p class="hasil-help">Isi titik yang diukur. Titik pertama wajib; maksimal empat titik.</p>');
        bagian.appendChild(titik);bagian.appendChild(grupAir.querySelector('[data-tambah="tes"]'));
        titik.classList.add("kadar-titik-grid");
        titik._titikKadar = function () {
          titik.querySelectorAll("input").forEach(function (input,i) {
            input.id = i === 0 ? "f_tes" : "f_tes_" + (i+1);
            var lama = input.closest(".kadar-titik");
            if (lama) {
              var namaTitik=lama.querySelector("label");namaTitik.htmlFor=input.id;
              namaTitik.textContent="Titik " + (i+1) + (i === 0 ? " · wajib" : " · opsional");
              input.dataset.label="Titik " + (i+1) + " alat tes (%)";
              return;
            }
            if (i > 0) { input.removeAttribute("aria-invalid");input.removeAttribute("aria-describedby"); }
            var cell = document.createElement("div");cell.className="kadar-titik";input.before(cell);
            var label = document.createElement("label");label.htmlFor=input.id;label.textContent="Titik " + (i+1) + (i === 0 ? " · wajib" : " · opsional");
            cell.appendChild(label);var unit=document.createElement("div");unit.className="hasil-unit";cell.appendChild(unit);unit.appendChild(input);
            unit.insertAdjacentHTML("beforeend",'<span aria-hidden="true">%</span>');
            input.dataset.label="Titik " + (i+1) + " alat tes (%)";
            if (i > 0) {
              var hapus=document.createElement("button");hapus.type="button";hapus.className="btn btn--kecil";
              hapus.dataset.hapusKadar="1";hapus.textContent="Hapus titik";cell.appendChild(hapus);
            }
          });
          perbaruiRingkasanAir();
        };
        bagian.onclick = function(e) {
          var hapus=e.target.closest("[data-hapus-kadar]");if(!hapus)return;
          hapus.closest(".kadar-titik").remove();titik._titikKadar();
          var tambah=bagian.querySelector('[data-tambah="tes"]');tambah.hidden=false;tambah.focus();lembar._berubah=true;
        };
        borangHasil.querySelector(".hasil-actions").insertAdjacentHTML("beforebegin",'<div class="hasil-preview kadar-summary" role="status" aria-live="polite">' +
          '<div><span>Rata-rata alat tes<small id="air-jumlah"></small></span><strong id="air-rata">Belum dapat dihitung</strong></div>' +
          '<div><span>Sebaran tertinggi − terendah</span><strong id="air-sebar">Perlu minimal dua titik</strong></div>' +
          '<div><span>Bacaan mesin</span><strong id="air-mesin">Belum diisi</strong></div>' +
          '<div><span>Mesin − rata-rata alat tes</span><strong id="air-selisih">Belum dapat dihitung</strong></div>' +
          '<small>Pratinjau · angka mesin tidak dicampur dengan alat tes.</small></div><div class="kadar-warning" id="air-peringatan" role="status" hidden></div>');
        var aksiLain=borangHasil.querySelector('[data-buka-aksi="ubah_target"]');
        if (aksiLain) { var bagianLain=document.createElement("div");bagianLain.className="kadar-lain";aksiLain.before(bagianLain);bagianLain.appendChild(aksiLain);bagianLain.insertAdjacentHTML("beforeend",'<small>Tindakan terpisah; perubahan target meminta konfirmasi.</small>'); }
      }
      if (kadarAir) titik._titikKadar();
      borangHasil.addEventListener("input",perbaruiRingkasanAir);
      borangHasil.addEventListener("change",function (e) { if(e.target.dataset.name === formAir.proses) perbaruiRingkasanAir(); });
      perbaruiRingkasanAir();
    }

    // Dua input lama tetap milik generator. Konteks hanya dibaca; bacaan
    // terakhir tidak pernah disalin menjadi kadar air akhir yang wajib diukur.
    var dataSelesai = null, nomorSelesai = 0, kodeSelesai = "";
    var periksaSelesai = false, risikoSelesai = false;
    function tautanSelesai(dingin) {
      var kode = nilaiMedan(selesaiKering.proses);
      var url = "/proses-aktif/" + (dingin ? "pendinginan/" : "pengeringan/") + encodeURIComponent(kode);
      var asal = new URLSearchParams(location.search).get("kembali_kerja");
      return url + (asal ? "?kembali_kerja=" + encodeURIComponent(asal) : "");
    }
    async function perbaruiSelesai() {
      if (!selesaiKering || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return null;
      var kode = nilaiMedan(selesaiKering.proses), nomor = ++nomorSelesai;
      if (kode !== kodeSelesai) { periksaSelesai = false; risikoSelesai = false; }
      kodeSelesai = kode; dataSelesai = null;
      $("sk-pemilik").textContent = kode ? "Memuat konteks pengeringan…" : "Pilih pengeringan";
      ["sk-milik","sk-status","sk-sumber"].forEach(function(id) { $(id).textContent = ""; });
      ["sk-target","sk-durasi","sk-mulai","sk-mesin","sk-mesin-waktu","sk-tes","sk-tes-waktu"].forEach(function(id) { $(id).textContent = "Belum tersedia"; });
      $("sk-info").textContent = periksaSelesai ? "Memeriksa status dan catatan terbaru…" : "";
      $("sk-periksa").hidden = !periksaSelesai;
      $("sk-detail").hidden = true;
      $("simpan").disabled = lembar._menyimpan || periksaSelesai || risikoSelesai;
      if (!kode) return null;
      try {
        var r = await fetch(selesaiKering.source + "?kode_lot=" + encodeURIComponent(kode), {credentials:"same-origin", cache:"no-store"});
        if (!r.ok) throw new Error("Konteks belum tersedia");
        var d = await r.json();
        if (nomor !== nomorSelesai || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil || nilaiMedan(selesaiKering.proses) !== kode) return null;
        if (d.kode_lot !== kode) throw new Error("Konteks tidak sesuai pilihan");
        dataSelesai = d; periksaSelesai = false;
        $("sk-pemilik").textContent = d.pemilik || "Pemilik belum tercatat";
        $("sk-milik").textContent = d.kepemilikan || "";
        $("sk-status").textContent = ({berjalan:"Berjalan",dijeda:"Dijeda",selesai:"Pendinginan / tindak lanjut"})[d.status] || "Belum mulai / belum diketahui";
        $("sk-status").classList.toggle("lencana--hati",d.status === "dijeda");
        $("sk-sumber").textContent = [d.dryer,d.bahan ? "Bahan " + d.bahan : "",d.sebab_jeda ? "Jeda: " + d.sebab_jeda : ""].filter(Boolean).join(" · ");
        [["sk-target","target_teks"],["sk-durasi","durasi"],["sk-mulai","mulai"],["sk-mesin","mesin_terakhir"],["sk-mesin-waktu","mesin_waktu"],["sk-tes","tes_terakhir"],["sk-tes-waktu","tes_waktu"]].forEach(function(pair) { $(pair[0]).textContent = d[pair[1]] || "Belum tersedia"; });
        $("sk-info").textContent = d.dapat_diselesaikan === false ? "Pengeringan ini tidak lagi tersedia untuk diselesaikan dari formulir ini. Buka detail untuk melihat fase terbaru." : "";
        $("sk-detail").href = tautanSelesai(d.status === "selesai");
        $("sk-detail").hidden = d.dapat_diselesaikan !== false && !risikoSelesai;
        $("sk-periksa").hidden = true;
        $("simpan").disabled = lembar._menyimpan || d.dapat_diselesaikan === false || risikoSelesai;
        return d;
      } catch (e) {
        if (nomor !== nomorSelesai || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return null;
        $("sk-pemilik").textContent = "Konteks pengeringan belum tersedia";
        $("sk-sumber").textContent = "Isian tetap utuh. Penyimpanan diperiksa oleh server.";
        $("sk-info").textContent = periksaSelesai ? "Status penyimpanan belum dapat diperiksa. Periksa lagi atau buka detail sebelum mencoba kembali." : "";
        $("sk-detail").href = tautanSelesai(false); $("sk-detail").hidden = !periksaSelesai;
        $("sk-periksa").hidden = !periksaSelesai;
        return null;
      }
    }
    if (selesaiKering) {
      borangHasil.querySelector(".lembar__kepala").insertAdjacentHTML("afterend",
        '<section class="hasil-context sk-context"><div><span id="sk-milik"></span><span class="lencana" id="sk-status"></span></div>' +
        '<strong id="sk-pemilik"></strong><small id="sk-sumber"></small><div class="sk-facts">' +
        '<div><span>Target kadar air</span><strong id="sk-target">Belum tersedia</strong></div>' +
        '<div><span>Durasi sampai saat ini</span><strong id="sk-durasi">Belum tersedia</strong></div>' +
        '<div><span>Mulai pengeringan</span><strong id="sk-mulai">Belum tersedia</strong></div></div></section>');
      var grupSelesai = borangHasil.querySelector(".grup");
      ["kode_lot","kadar_air"].forEach(function(nama) {
        var input = grupSelesai.querySelector('[data-name="' + nama + '"]');
        var label = input.type === "hidden" ? null : grupSelesai.querySelector('label[for="' + input.id + '"]');
        var kunci = input.type === "hidden" ? input.previousElementSibling : null;
        var wadah = document.createElement("div");wadah.className = "hasil-field";
        grupSelesai.insertBefore(wadah,label || kunci || input);
        if (!label) { label = document.createElement("span");label.className = "lbl";label.textContent = input.dataset.label; }
        wadah.appendChild(label);
        if (kunci) { wadah.appendChild(kunci);kunci.setAttribute("role","textbox");kunci.setAttribute("aria-label",input.dataset.label);kunci.setAttribute("aria-readonly","true"); }
        wadah.appendChild(input);
        if (nama === "kadar_air") {
          var unit = document.createElement("div");unit.className = "hasil-unit";wadah.appendChild(unit);unit.appendChild(input);
          unit.insertAdjacentHTML("beforeend",'<span aria-hidden="true">%</span>');
          input.setAttribute("aria-describedby","sk-help");
          wadah.insertAdjacentHTML("beforeend",'<p class="hasil-help" id="sk-help">Wajib isi bacaan mesin saat dimatikan, lebih dari 0 sampai 100%.</p>');
        } else if (kunci) wadah.insertAdjacentHTML("beforeend",'<small class="hasil-help">Terisi dari pengeringan yang dibuka.</small>');
      });
      borangHasil.querySelector(".hasil-actions").insertAdjacentHTML("beforebegin",
        '<section class="sk-last" aria-label="Referensi pengukuran terakhir"><div><span>Mesin terakhir <strong id="sk-mesin">Belum tersedia</strong></span><small id="sk-mesin-waktu"></small></div>' +
        '<div><span>Alat tes terakhir <strong id="sk-tes">Belum tersedia</strong></span><small id="sk-tes-waktu"></small></div><small>Referensi saja. Isi bacaan akhir yang terlihat sekarang; angka di atas tidak diisikan otomatis.</small></section>' +
        '<section class="sk-effect"><h3>Setelah disimpan</h3><strong>Pengeringan → Pendinginan</strong><p>Bacaan mesin akhir: <strong id="sk-bacaan-akhir">Belum diisi</strong></p><p>Pengeringan selesai dan pendinginan otomatis dimulai. Gabah tetap di dryer.</p><p>Nyatakan sudah dingin melalui tindakan terpisah sebelum pindah ke silo.</p><small>Bacaan akhir dicatat sebagai bacaan mesin, terpisah dari hasil alat tes.</small></section>' +
        '<div class="sk-check"><p class="hasil-help" id="sk-info" role="status"></p><button class="btn" id="sk-periksa" type="button" hidden>Periksa status terbaru</button><a class="btn" id="sk-detail" hidden>Buka detail terbaru</a></div>');
      function tampilBacaanAkhir() {
        // Cermin ketikan saja: angka resmi dan validasi tetap milik jalur simpan.
        var teks = $("f_kadar_air").value.trim();
        $("sk-bacaan-akhir").textContent = teks ? teks + "%" : "Belum diisi";
      }
      $("f_kadar_air").addEventListener("input", tampilBacaanAkhir);
      $("f_kadar_air").addEventListener("change", tampilBacaanAkhir);
      tampilBacaanAkhir();
      $("sk-periksa").onclick = perbaruiSelesai;
      borangHasil.addEventListener("change",function(e) { if (e.target.dataset.name === selesaiKering.proses) perbaruiSelesai(); });
      perbaruiSelesai();
    }

    var dataPindah = null, urutanPindah = 0, periksaPindah = false;
    async function perbaruiPindah() {
      if (!pindahSilo || !borangHasil.isConnected) return null;
      var kode = nilaiMedan("kode_lot"), silo = nilaiMedan("silo"), nomor = ++urutanPindah;
      dataPindah = null;
      ["ps-milik","ps-pemilik","ps-sumber","ps-status","ps-dingin","ps-bobot","ps-dari","ps-ke","ps-isi","ps-owner","ps-kegiatan","ps-kapasitas","ps-sesudah"].forEach(function(id) { $(id).textContent = "Belum tersedia"; });
      $("ps-pemilik").textContent = kode ? "Memuat konteks pemindahan…" : "Pilih pengeringan";
      $("ps-lot").textContent = kode || "Belum dipilih";
      $("ps-tujuan").hidden = !silo;$("ps-peringatan").replaceChildren();$("ps-detail").hidden = true;
      if (!kode) return null;
      try {
        var d = await ambil(pindahSilo.source + "?kode_lot=" + encodeURIComponent(kode) + "&silo=" + encodeURIComponent(silo));
        if (!d || !lembar.open || !borangHasil.isConnected || nomor !== urutanPindah || kode !== nilaiMedan("kode_lot") || silo !== nilaiMedan("silo")) return null;
        dataPindah = d;
        $("ps-pemilik").textContent = d.pemilik + " · " + d.dryer;$("ps-milik").textContent = d.kepemilikan;
        $("ps-sumber").textContent = d.jumlah_batch + " batch sumber" + (d.pesanan ? " · " + d.pesanan : "");
        $("ps-status").textContent = d.status;$("ps-dingin").textContent = "Dinyatakan dingin: " + d.dingin;
        $("ps-bobot").textContent = d.bobot;$("ps-dari").textContent = d.dryer;
        $("ps-ke").textContent = d.tujuan ? d.tujuan.nama : "Pilih silo";
        $("ps-detail").href = d.detail;$("ps-detail").hidden = !periksaPindah && d.siap;
        $("simpan").disabled = !d.siap;periksaPindah = false;
        $("ps-info").textContent = d.siap ? "" : "Lot tidak lagi siap dipindah. Buka detail terbaru untuk memeriksa lokasi dan pendinginan.";
        if (d.tujuan) {
          $("ps-isi").textContent = d.tujuan.isi;$("ps-owner").textContent = d.tujuan.pemilik;
          $("ps-kegiatan").textContent = d.tujuan.kegiatan;$("ps-kapasitas").textContent = d.tujuan.kapasitas;
          $("ps-sesudah").textContent = d.tujuan.sesudah;
        }
        (d.peringatan || []).forEach(function(teks) { var p = document.createElement("p");p.className = "ps-warning";p.textContent = teks;$("ps-peringatan").appendChild(p); });
        return d;
      } catch (e) {
        if (nomor !== urutanPindah || !borangHasil.isConnected) return null;
        $("ps-pemilik").textContent = "Ringkasan pemindahan belum tersedia";
        $("ps-periksa").hidden = false;
        $("ps-info").textContent = "Pilihan tetap utuh. Pemeriksaan akhir dilakukan server saat menyimpan.";
        // Gangguan pratinjau awal bukan syarat bisnis baru. Setelah hasil
        // simpan tidak pasti, periksa keadaan dahulu tanpa mengulang POST.
        $("simpan").disabled = periksaPindah;
        return null;
      }
    }
    if (pindahSilo) {
      borangHasil.querySelector(".lembar__kepala").insertAdjacentHTML("afterend",
        '<section class="hasil-context ps-context"><div><span id="ps-milik"></span><span class="lencana" id="ps-status"></span></div><strong id="ps-pemilik">Pilih pengeringan</strong><small id="ps-sumber"></small><small id="ps-dingin"></small></section>');
      var grupPindah = borangHasil.querySelector(".grup");
      ["kode_lot","silo"].forEach(function(nama) {
        var input = grupPindah.querySelector('[data-name="' + nama + '"]');
        var label = input.type === "hidden" ? null : grupPindah.querySelector('label[for="' + input.id + '"]');
        var kunci = input.type === "hidden" ? input.previousElementSibling : null;
        var wadah = document.createElement("div");wadah.className = "hasil-field";
        grupPindah.insertBefore(wadah,label || kunci || input);
        if (!label) { label = document.createElement("span");label.className = "lbl";label.textContent = input.dataset.label; }
        wadah.appendChild(label);
        if (kunci) { wadah.appendChild(kunci);kunci.setAttribute("role","textbox");kunci.setAttribute("aria-label",input.dataset.label);kunci.setAttribute("aria-readonly","true"); }
        wadah.appendChild(input);
      });
      grupPindah.insertAdjacentHTML("beforeend",'<p class="hasil-help">Pindahkan seluruh lot ke satu silo tujuan. Pilihan silo mengikuti master alat Gudang 1.</p>');
      var tataPindah = document.createElement("div");tataPindah.className = "ps-layout";
      grupPindah.before(tataPindah);tataPindah.appendChild(grupPindah);
      tataPindah.insertAdjacentHTML("beforeend",'<div class="ps-preview"><div class="ps-route"><div><small>Dari</small><strong id="ps-dari">Belum tersedia</strong></div><span aria-hidden="true">→</span><div><small>Ke</small><strong id="ps-ke">Pilih silo</strong></div></div>' +
        '<section class="ps-card" id="ps-tujuan" hidden><h3>Silo tujuan saat ini</h3><dl><div><dt>Isi tercatat</dt><dd id="ps-isi"></dd></div><div><dt>Pemilik isi</dt><dd id="ps-owner"></dd></div><div><dt>Kegiatan</dt><dd id="ps-kegiatan"></dd></div><div><dt>Kapasitas informasi</dt><dd id="ps-kapasitas"></dd></div></dl><small>Kapasitas adalah keterangan, bukan batas penolakan.</small></section>' +
        '<section class="ps-card ps-summary"><h3>Ringkasan pemindahan</h3><dl><div><dt>Lot</dt><dd id="ps-lot">Belum dipilih</dd></div><div><dt>Bobot acuan lot</dt><dd id="ps-bobot">Belum tersedia</dd></div><div class="ps-total"><dt>Isi tercatat sesudah pindah</dt><dd id="ps-sesudah">Pilih silo</dd></div></dl><small>Bobot mengikuti batch sumber beserta kepastiannya. Pemindahan ini tidak menimbang ulang atau menghitung susut pengeringan.</small></section><div id="ps-peringatan" aria-live="polite"></div><p class="hasil-help">Setelah disimpan, gabah tercatat di silo dan dryer kosong. Mulai giling tetap tindakan terpisah; proses giling yang sudah berjalan tetap berjalan.</p></div>');
      borangHasil.querySelector(".hasil-actions").insertAdjacentHTML("beforebegin",'<div class="ps-check"><p id="ps-info" class="hasil-help" role="status"></p><button class="btn" id="ps-periksa" type="button" hidden>Periksa posisi lot & isi terbaru</button><a class="btn" id="ps-detail" hidden>Buka detail lot</a></div>');
      $("ps-periksa").onclick = perbaruiPindah;
      borangHasil.addEventListener("change",function(e) { if (["kode_lot","silo"].indexOf(e.target.dataset.name) >= 0) { bersihkanSalah(lembar);periksaPindah = false;$("simpan").disabled = false;perbaruiPindah(); } });
      perbaruiPindah();
    }

    // Ringkasan hanya membaca sumber yang sama dengan start_milling. Pilihan
    // tetap satu kelompok checkbox; tidak ada bobot/delta transaksi di browser.
    var urutanMulai = 0, periksaMulai = false;
    function pilihanMulai() {
      var el = borangHasil.querySelector('[data-name="silo"]');
      return String(el && el.value || "").split(",").filter(Boolean);
    }
    function perbaruiMulai() {
      if (!mulaiBahan || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return Promise.resolve(null);
      var pilihan = pilihanMulai(), kunci = pilihan.join(","), nomor = ++urutanMulai;
      $("mg-dipilih").textContent = pilihan.length ? pilihan.map(function (n) { return "Silo " + n; }).join(" + ") : "Belum dipilih";
      $("mg-bobot").textContent = pilihan.length ? "Memuat bobot…" : "Belum tersedia";
      $("mg-pemilik").textContent = "Belum tersedia";
      $("mg-bentuk").textContent = pilihan.length ? (mulaiSosoh ? "1 proses penyosohan" : "1 lot · sumber sedang dibaca") : "Belum dipilih";
      $("mg-per-silo").textContent = "";if(mulaiSosoh){$("ms-rinci").textContent="";$("ms-sumber").hidden=!pilihan.length;}$("mg-peringatan").textContent = "";$("mg-tautan").textContent = "";
      $("mg-final").textContent = pilihan.length ? "Ringkasan baca saja. Kondisi terbaru diperiksa saat menyimpan." : "Centang minimal satu silo sumber.";
      if (!pilihan.length) { periksaMulai = false;$("simpan").disabled = !borangHasil.querySelector('#b_silo input');return Promise.resolve(null); }
      return fetch(mulaiBahan.source + "?" + pilihan.map(function (n) { return "silo=" + encodeURIComponent(n); }).join("&"),
        {credentials:"same-origin",cache:"no-store"}).then(function (r) { if (!r.ok) throw new Error("Ringkasan belum tersedia");return r.json(); }).then(function (d) {
        if (nomor !== urutanMulai || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil || pilihanMulai().join(",") !== kunci) return null;
        if ((d.pilihan || []).join(",") !== kunci.toUpperCase()) throw new Error("Pilihan sudah berubah");
        $("mg-bobot").textContent = d.bobot;$("mg-pemilik").textContent = d.pemilik || "Pemilik belum tersedia";
        $("mg-bentuk").textContent = mulaiSosoh ? "1 proses penyosohan" : "1 lot · " + d.jumlah_sumber + " sumber bahan";
        $("mg-final").textContent = d.final ? (mulaiSosoh ? "Bobot diambil otomatis dari saldo silo saat disimpan." : "Bobot sumber sudah final.") : "Bobot bahan belum final; pemutakhiran mengikuti data timbang dan mekanisme lama.";
        (d.silos || []).forEach(function (s) {
          var baris = document.createElement("div"), nama = document.createElement("span"), berat = document.createElement("strong");
          nama.textContent = s.nama;berat.textContent = s.bobot;baris.append(nama,berat);if(!mulaiSosoh) $("mg-per-silo").appendChild(baris);
          if (s.detail) { var link = document.createElement("a");link.textContent = "Buka " + s.proses;link.href = s.detail;$("mg-tautan").appendChild(link); }
        });
        if(mulaiSosoh){
          (d.silos||[]).forEach(function(s){
            var blok=document.createElement('article');blok.className='ms-source';
            var judul=document.createElement('strong');judul.textContent=s.nama+' · '+s.bobot;blok.appendChild(judul);
            (s.komposisi||[]).forEach(function(k){var p=document.createElement('p');p.textContent=k.jenis+' · '+k.bobot;blok.appendChild(p);});
            (s.sumber||[]).forEach(function(r){var p=document.createElement('p');p.textContent=r.kode+' · '+r.jenis+' · '+r.bobot+' · '+r.pemilik;blok.appendChild(p);});
            $('ms-rinci').appendChild(blok);
          });
        }
        (d.peringatan || []).forEach(function (teks) { var p = document.createElement("p");p.className = "mg-warning";p.textContent = teks;$("mg-peringatan").appendChild(p); });
        $("simpan").disabled = periksaMulai && !d.siap;periksaMulai = periksaMulai && !d.siap;
        $("mg-info").textContent = d.siap ? "" : "Pilihan diperiksa kembali oleh server saat menyimpan. Perbaiki centang yang tidak sesuai.";
        return d;
      }).catch(function () {
        if (nomor !== urutanMulai || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return null;
        $("mg-bobot").textContent = "Belum tersedia";
        $("mg-final").textContent = "Ringkasan belum dapat dimuat. Pilihan tetap utuh; layanan memeriksa bobot dan pemilik saat menyimpan.";
        $("simpan").disabled = periksaMulai;
        return null;
      });
    }
    if (mulaiBahan) {
      borangHasil.querySelector(".lembar__kepala").insertAdjacentHTML("afterend", '<div class="mg-intro"><strong>Satu atau beberapa silo, satu '+(mulaiSosoh?'proses.':'lot.')+'</strong><span>Seluruh isi silo yang dipilih menjadi bahan satu proses '+(mulaiSosoh?'penyosohan.':'penggilingan.')+'</span></div>');
      var grupMulai = borangHasil.querySelector(".grup"), tataMulai = document.createElement("div");tataMulai.className = "mg-layout";
      grupMulai.before(tataMulai);tataMulai.appendChild(grupMulai);
      var daftarMulai = $("b_silo"), judulMulai = daftarMulai.previousElementSibling;
      var kelompokMulai = document.createElement("fieldset"), legendaMulai = document.createElement("legend");kelompokMulai.className = "mg-fieldset";
      legendaMulai.textContent = judulMulai.textContent;judulMulai.replaceWith(kelompokMulai);kelompokMulai.append(legendaMulai,daftarMulai);
      grupMulai.insertAdjacentHTML("beforeend",'<p class="hasil-help">'+(mulaiSosoh?'Daftar mengikuti silo aktif Gudang 2 dan saldo bahan sebenarnya.':'Daftar mengikuti silo aktif Gudang 1. Silo kosong dan silo yang masih dipakai giling tidak ditawarkan.')+'</p>');
      tataMulai.insertAdjacentHTML("beforeend",'<div class="mg-preview" aria-live="polite"><section class="mg-summary"><h3>Ringkasan giling baru</h3><dl><div><dt>Silo dipilih</dt><dd id="mg-dipilih">Belum dipilih</dd></div></dl><div id="mg-per-silo"></div><dl><div class="mg-total"><dt>Bobot gabah acuan</dt><dd id="mg-bobot">Belum tersedia</dd></div><div><dt>Pemilik</dt><dd id="mg-pemilik">Belum tersedia</dd></div><div><dt>Hasil pembentukan</dt><dd id="mg-bentuk">Belum dipilih</dd></div></dl><small id="mg-final">Centang minimal satu silo sumber.</small></section><div id="mg-peringatan"></div><div id="mg-tautan"></div><p class="hasil-help">Seluruh isi silo terpilih didaftarkan dalam satu proses. Hasil PK dicatat setelah giling berjalan; rendemen belum dihitung di formulir ini.</p></div>');
      borangHasil.querySelector(".hasil-actions").insertAdjacentHTML("beforebegin",'<div class="mg-check"><p id="mg-info" class="hasil-help" role="status"></p><button class="btn" id="mg-periksa" type="button" hidden>Periksa proses & silo terbaru</button></div>');
      if(mulaiSosoh){
        tataMulai.querySelector('h3').textContent='Ringkasan penyosohan baru';
        $('mg-bobot').previousElementSibling.textContent='Total bahan awal';
        $('mg-bentuk').previousElementSibling.textContent='Proses yang dibentuk';
        grupMulai.querySelector('.hasil-help').classList.add('ms-options-help');
        var petunjukSosoh=tataMulai.querySelector('.mg-preview>.hasil-help');petunjukSosoh.classList.add('ms-footer-help');petunjukSosoh.textContent='Memulai proses mencatat bahan awal. Sisa per silo dan hasil penyosohan dicatat lewat tindakan yang sudah ada. Silo tidak otomatis kosong.';borangHasil.querySelector('.hasil-actions').before(petunjukSosoh);
        $('mg-final').textContent='Bobot diambil otomatis dari saldo silo saat disimpan.';
        tataMulai.querySelector('.mg-preview').insertAdjacentHTML('beforeend','<details class="ms-sources" id="ms-sumber" hidden><summary>Lihat komposisi &amp; asal bahan</summary><p class="ms-origin-help">Riwayat asal masuk. Bobot asal bukan sisa per lot dan tidak ditambahkan lagi ke total bahan.</p><div id="ms-rinci"></div></details>');
      }
      $("mg-periksa").onclick = perbaruiMulai;
    }

    // Bantuan mix hanya membaca; payload tetap dua pilihan, tanpa delta/token.
    var nomorTg = 0;
    function perbaruiTg() {
      if (!tambahGiling || !lembar.open || lembar.querySelector('.lembar__isi') !== borangHasil) return Promise.resolve(null);
      var kode = nilaiMedan('kode_proses'), silo = nilaiMedan('silo'), nomor = ++nomorTg;
      $('tg-milik').textContent = '';$('tg-status').hidden = true;
      $('tg-pemilik').textContent = kode ? 'Memuat konteks…' : 'Pilih proses giling';
      $('tg-konteks').textContent = '';$('tg-awal').textContent = kode ? 'Memuat bahan…' : 'Belum tersedia';
      $('tg-label-tambah').textContent = 'Tambahan silo';$('tg-tambah').textContent = silo ? 'Memuat sumber…' : 'Belum dipilih';
      $('tg-setelah').textContent = 'Pilih silo dahulu';$('tg-sumber').hidden = true;$('tg-rinci').textContent = '';
      $('tg-peringatan').textContent = '';$('tg-final').textContent = 'Ringkasan baca saja; layanan memeriksa keadaan terbaru saat menyimpan.';
      $('tg-akibat').textContent = 'Bahan bergabung ke proses yang sama. Hasil PK tetap dicatat terpisah.';
      if (!kode) return Promise.resolve(null);
      return fetch(tambahGiling.source + '?kode_proses=' + encodeURIComponent(kode) + '&silo=' + encodeURIComponent(silo),
        {credentials:'same-origin',cache:'no-store'}).then(function(r){if(!r.ok)throw new Error();return r.json();}).then(function(d){
        if(nomor!==nomorTg || !lembar.open || lembar.querySelector('.lembar__isi')!==borangHasil || kode!==nilaiMedan('kode_proses') || silo!==nilaiMedan('silo'))return null;
        if(d.kode_proses!==kode || d.silo!==silo)throw new Error();
        $('tg-milik').textContent=d.kepemilikan;$('tg-pemilik').textContent=d.pemilik;
        $('tg-status').hidden=false;$('tg-status').textContent=d.status==='dijeda'?'Dijeda':d.status==='berjalan'?'Berjalan':d.status==='selesai'?'Selesai':'Status belum diketahui';
        $('tg-konteks').textContent=[kode,d.pesanan,(d.silos||[]).join(' + '),d.jumlah_sumber ? d.jumlah_sumber+' sumber tercatat' : 'Rincian sumber lama belum lengkap',d.sebab_jeda].filter(Boolean).join(' · ');
        $('tg-awal').textContent=d.bahan;$('tg-label-tambah').textContent=d.nama_silo ? 'Tambahan '+d.nama_silo : 'Tambahan silo';
        $('tg-tambah').textContent=silo?d.tambahan:'Belum dipilih';$('tg-setelah').textContent=d.setelah;
        $('tg-final').textContent=d.final?'Bobot mengikuti isi sumber yang masih tersedia.':'Bobot belum final. Total belum lengkap bila ada sumber menunggu timbang.';
        (d.peringatan||[]).forEach(function(t){var p=document.createElement('p');p.className='tg-warning';p.textContent=t;$('tg-peringatan').appendChild(p);});
        $('tg-sumber').hidden=!(d.sumber||[]).length;
        $('tg-sumber-judul').textContent=(d.nama_silo||'Silo terpilih')+' · '+(d.sumber||[]).length+' sumber tambahan';
        (d.sumber||[]).forEach(function(r){var el=document.createElement('article');el.className='tg-source';
          el.innerHTML='<strong>'+esc(r.sumber)+'</strong><span>'+esc(r.bobot)+'</span><small>'+esc([r.pemilik,r.pesanan,r.final?'Bobot pasti':'Bobot belum final'].filter(Boolean).join(' · '))+'</small>';
          $('tg-rinci').appendChild(el);});
        $('tg-akibat').textContent='Bahan bergabung ke proses yang sama. '+(d.status==='dijeda'?'Penggilingan tetap dijeda; ':d.status==='berjalan'?'Penggilingan tetap berjalan; ':'Status diperiksa kembali saat menyimpan; ')+'hasil PK tetap dicatat terpisah.';
        return d;
      }).catch(function(){
        if(nomor!==nomorTg || !lembar.open || lembar.querySelector('.lembar__isi')!==borangHasil)return null;
        $('tg-pemilik').textContent='Konteks belum tersedia';$('tg-awal').textContent='Belum tersedia';$('tg-tambah').textContent='Belum tersedia';$('tg-setelah').textContent='Belum dapat dihitung';
        $('tg-final').textContent='Ringkasan belum dapat dimuat. Pilihan tetap utuh; layanan memeriksa bahan dan pemilik saat menyimpan.';return null;
      });
    }
    if(tambahGiling){
      borangHasil.querySelector('.lembar__kepala').insertAdjacentHTML('afterend','<div class="tg-context"><div class="tg-context-top"><span id="tg-milik"></span><span id="tg-status" hidden></span></div><strong id="tg-pemilik">Pilih proses giling</strong><small id="tg-konteks"></small></div>');
      var grupTg=borangHasil.querySelector('.grup'),tataTg=document.createElement('div');tataTg.className='tg-layout';grupTg.before(tataTg);tataTg.appendChild(grupTg);
      ['kode_proses','silo'].forEach(function(nama){var input=grupTg.querySelector('[data-name="'+nama+'"]'),kunci=input.type==='hidden'?input.previousElementSibling:null,label=grupTg.querySelector('label[for="f_'+nama+'"]'),wadah=document.createElement('div');wadah.className='hasil-field';grupTg.insertBefore(wadah,label||kunci||input);if(label)wadah.appendChild(label);if(kunci){wadah.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(input.dataset.label)+'</span>');wadah.appendChild(kunci);kunci.setAttribute('role','textbox');kunci.setAttribute('aria-label',input.dataset.label);kunci.setAttribute('aria-readonly','true');}wadah.appendChild(input);});
      grupTg.insertAdjacentHTML('beforeend','<p class="hasil-help">Satu silo per penyimpanan. Bahan dari silo terpilih bergabung ke satu proses yang sama.</p>');
      tataTg.insertAdjacentHTML('beforeend','<div class="tg-preview" aria-live="polite"><section class="tg-summary"><h3>Bahan pada proses ini</h3><dl><div><dt>Bahan tercatat saat ini</dt><dd id="tg-awal">Belum tersedia</dd></div><div><dt id="tg-label-tambah">Tambahan silo</dt><dd id="tg-tambah">Belum dipilih</dd></div><div class="tg-total"><dt>Bahan setelah mix</dt><dd id="tg-setelah">Pilih silo dahulu</dd></div></dl><small id="tg-final"></small></section><div id="tg-peringatan"></div><details class="tg-sources" id="tg-sumber" hidden><summary id="tg-sumber-judul">Rincian sumber tambahan</summary><p class="hasil-help">Seluruh sumber yang tersedia dan belum terhubung ikut proses ini.</p><div id="tg-rinci"></div></details></div>');
      borangHasil.querySelector('.hasil-actions').insertAdjacentHTML('beforebegin','<p class="hasil-help tg-meta" id="tg-akibat">Bahan bergabung ke proses yang sama. Hasil PK tetap dicatat terpisah.</p><button type="button" class="btn tg-check" id="tg-periksa" hidden>Periksa proses & sumber terbaru</button>');
      $('tg-periksa').onclick=perbaruiTg;
      borangHasil.addEventListener('change',function(e){if(e.target.dataset.name==='kode_proses' || e.target.dataset.name==='silo'){bersihkanSalah(lembar);perbaruiTg();}});
      perbaruiTg();
    }

    var dataSs = null, nomorSs = 0, memeriksaSs = false, risikoSs = false;
    function pasanganSs(label, nilai, utama) {
      return '<div'+(utama?' class="ss-total"':'')+'><dt>'+esc(label)+'</dt><dd>'+esc(nilai)+'</dd></div>';
    }
    function persenSs(n) {return n == null ? 'Belum dapat dipastikan' : Number(n).toLocaleString('id-ID',{maximumFractionDigits:2})+'%';}
    function hasilSs(d, judulHasil) {
      return '<section class="ss-summary"><h3>'+esc(judulHasil)+'</h3><dl>'+pasanganSs('Bahan terpakai',d.bahan)+pasanganSs('Hasil beras',d.ada_hasil?kgHasil(d.beras):'Belum dicatat')+pasanganSs('Hasil samping',d.ada_hasil?kgHasil(d.samping):'Belum dicatat')+pasanganSs('Total semua hasil',d.ada_hasil?kgHasil(d.total):'Belum dicatat',true)+'</dl></section>';
    }
    function sumberSs(d) {
      return '<section class="ss-readiness"><h3>Pemeriksaan sisa silo</h3>'+ (d.sumber.length?d.sumber.map(function(r){return '<div class="ss-silo"><div><strong>'+esc(r.silo)+'</strong><small>Pemakaian #'+esc(r.id)+' · awal '+esc(kgHasil(r.awal))+' · tambahan '+esc(kgHasil(r.tambahan))+(r.dinamis?' · sumber karung dinamis':'')+'</small></div><span class="ss-badge'+(r.sisa==null?' ss-pending':'')+'">'+esc(r.sisa==null?'Belum diperiksa':'Sisa '+kgHasil(r.sisa))+'</span></div>';}).join(''):'<p>Sumber proses lama belum terverifikasi.</p>')+'<p class="ss-note">'+esc(d.sisa_lengkap?'Semua siklus sudah diperiksa. Sisa tetap di silo; proses belum otomatis selesai.':'Bebaskan setiap pemakaian silo melalui tindakan terpisah sebelum menutup proses.')+'</p></section>';
    }
    function rincianSs(d) {
      return '<details class="ss-details"><summary>Lihat seluruh hasil & neraca bahan</summary>'+[true,false].map(function(beras){return '<h3>'+(beras?'Hasil beras':'Hasil samping')+'</h3><dl>'+d.hasil.filter(function(r){return r.beras===beras;}).map(function(r){return pasanganSs(r.nama,r.kg==null?'Belum dicatat':kgHasil(r.kg));}).join('')+'</dl>';}).join('')+'<h3>Neraca tercatat</h3><dl>'+pasanganSs('Bahan terpakai',d.bahan)+pasanganSs('Total semua hasil',d.ada_hasil?kgHasil(d.total):'Belum dicatat')+pasanganSs('Selisih bahan dan hasil',d.selisih==null?'Belum dapat dipastikan':kgHasil(d.selisih))+pasanganSs('Rendemen beras',persenSs(d.rendemen))+'</dl><p class="ss-note">Angka mengikuti catatan proses. Jenis yang belum dicatat tidak menjadi isian wajib baru. Hasil belum final selama proses masih berjalan.</p></details>';
    }
    function konteksSs(d) {return [d.kepemilikan,d.pesanan,d.kode_proses,d.status==='dijeda'?'Dijeda · '+(d.sebab_jeda||'Sebab belum tersedia'):d.status==='selesai'?'Selesai':'Berjalan',d.mulai?'Mulai '+d.mulai:'Waktu mulai belum tersedia'].filter(Boolean).join(' · ');}
    async function perbaruiSs() {
      if(!selesaiSosoh || !lembar.open || lembar.querySelector('.lembar__isi')!==borangHasil)return null;
      var n=++nomorSs,kode=nilaiMedan('kode_proses');dataSs=null;
      $('ss-pemilik').textContent=kode?'Memuat konteks…':'Pilih proses penyosohan';$('ss-konteks').textContent='';$('ss-preview').textContent=kode?'Memuat ringkasan hasil dan pemakaian silo…':'Pilih proses untuk melihat hasil serta pemeriksaan sisa silo.';$('ss-bebaskan').hidden=true;
      if(!kode)return null;
      try{var r=await fetch(selesaiSosoh.source+'?kode_proses='+encodeURIComponent(kode),{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error();var d=await r.json();
        if(n!==nomorSs || !lembar.open || lembar.querySelector('.lembar__isi')!==borangHasil || nilaiMedan('kode_proses')!==kode)return null;
        if(d.kode_proses!==kode || !Array.isArray(d.sumber) || !Array.isArray(d.hasil))throw new Error();
        dataSs=d;$('ss-pemilik').textContent=d.pemilik;$('ss-konteks').textContent=konteksSs(d);
        $('ss-preview').innerHTML=hasilSs(d,'Ringkasan hasil tercatat')+sumberSs(d)+(!d.bobot_final?'<p class="ss-warning">Bobot bahan belum final. Rendemen belum dapat dipastikan; sinkronisasi sumber karung tetap mengikuti layanan lama.</p>':'')+rincianSs(d);
        $('ss-bebaskan').hidden=d.sisa_lengkap||d.status==='selesai';$('simpan').disabled=d.status==='selesai'||memeriksaSs;return d;
      }catch(_){if(n!==nomorSs || lembar.querySelector('.lembar__isi')!==borangHasil)return null;$('ss-pemilik').textContent='Konteks belum tersedia';$('ss-preview').textContent='Ringkasan belum dapat dimuat. Data tidak dianggap kosong. Pilihan tetap utuh; Periksa penyelesaian meminta pemeriksaan server terbaru.';return null;}
    }
    function konfirmasiSs(d) {
      return '<div class="ss-review-head"><h3>'+esc(d.kode_proses)+'</h3><strong>'+esc(d.pemilik)+'</strong><p>'+esc(konteksSs(d))+'</p></div><div class="ss-review-layout"><div>'+sumberSs(d)+'<p class="ss-note">Sisa tetap berada di silo. Penyelesaian tidak mengosongkan silo atau menghapus isi baru setelah pemakaian dibebaskan.</p></div><div>'+hasilSs(d,'Hasil yang akan ditutup')+'<p class="ss-yield">Rendemen beras <strong>'+esc(persenSs(d.rendemen))+'</strong></p>'+rincianSs(d)+'</div></div><div class="ss-warning"><strong>Konfirmasi setelah mesin benar-benar selesai</strong><p>Pencatatan hasil normal proses ini ditutup. Packing hasil yang tersedia tetap dapat dilakukan sesuai hak akses.</p></div>';
    }
    if(selesaiSosoh){
      kembaliSelesaiSosoh=null;
      borangHasil.querySelector('.lembar__kepala').insertAdjacentHTML('afterend','<div class="ss-stage"><strong>Periksa proses</strong><span>→ Konfirmasi selesai</span></div><div class="ss-context"><strong id="ss-pemilik">Pilih proses penyosohan</strong><small id="ss-konteks"></small></div>');
      var grupSs=borangHasil.querySelector('.grup'),tataSs=document.createElement('div');tataSs.className='ss-layout';grupSs.before(tataSs);tataSs.appendChild(grupSs);
      var inputSs=grupSs.querySelector('[data-name=kode_proses]'),labelSs=grupSs.querySelector('label'),kunciSs=inputSs.type==='hidden'?inputSs.previousElementSibling:null;
      if(kunciSs){kunciSs.insertAdjacentHTML('beforebegin','<span class="lbl">Proses penyosohan</span>');kunciSs.setAttribute('role','textbox');kunciSs.setAttribute('aria-readonly','true');kunciSs.setAttribute('aria-label','Proses penyosohan');}
      grupSs.insertAdjacentHTML('beforeend','<section class="ss-impact"><h3>Menutup seluruh proses di mesin</h3><p>Pastikan seluruh bahan sudah selesai melewati mesin dan semua hasil sudah dicatat.</p><p>Sisa silo tetap tersedia. Packing hasil yang tersedia tetap dapat dilakukan.</p></section><button type="button" class="btn ss-link" id="ss-bebaskan" hidden>Buka Bebaskan silo</button>');
      tataSs.insertAdjacentHTML('beforeend','<div class="ss-preview" id="ss-preview" aria-live="polite"></div>');
      $('ss-bebaskan').onclick=function(){kembaliSelesaiSosoh={kode:nilaiMedan('kode_proses'),draft:terbaca()};kembaliSelesaiSosoh.draft['kode:kode_proses']=kembaliSelesaiSosoh.kode;lembar._berubah=false;bukaAksi('selesai_penyosohan',{kode_proses:kembaliSelesaiSosoh.kode,_dariSelesaiSosoh:true});};
      borangHasil.addEventListener('change',function(e){if(e.target.dataset.name==='kode_proses'){bersihkanSalah(lembar);perbaruiSs();}});perbaruiSs();
    }
    if(a.id==='selesai_penyosohan' && kembaliSelesaiSosoh){
      borangHasil.querySelector('.lembar__kepala').insertAdjacentHTML('afterend','<p class="nota">Tindakan terpisah. Penyosohan belum selesai dan hasil tetap dapat dicatat. Kembali untuk memeriksa ulang penyelesaian seluruh proses.</p>');
    }

    var dataSg = null, nomorSg = 0, timerSg, memeriksaSg = false, risikoSg = false;
    function kgSg(n) { return n == null ? "Belum tersedia" : kgHasil(n); }
    function sumberSg(d) {
      return '<section class="sg-silos"><h3>Pemeriksaan sisa silo</h3>' + (d.sumber.length ? d.sumber.map(function (r) {
        var keterangan = r.sisa == null ? 'Sisa belum diperiksa melalui Bebaskan silo.' :
          r.sisa === 0 ? 'Sudah diperiksa · tidak ada sisa pada sumber ini.' : 'Sudah diperiksa · sisa tetap berada di silo.';
        return '<div class="sg-source"><div><strong>' + esc(r.silo) + '</strong><small>Sumber #' + esc(r.id) + ' · ' + esc(r.sumber) + '</small></div><span class="sg-badge' + (r.sisa == null ? ' sg-pending' : '') + '">' + (r.sisa == null ? 'Belum diperiksa' : 'Sisa ' + esc(kgSg(r.sisa))) + '</span><small class="sg-source-note">' + esc(keterangan) + '</small></div>';
      }).join('') : '<p>Sumber proses lama belum terverifikasi.</p>') + '</section>';
    }
    function pasangSg(nama, nilai) { var el = $("sg-" + nama);if (el) el.textContent = nilai; }
    function perbaruiSg() {
      if (!selesaiGiling || !lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil) return Promise.resolve(null);
      var kode = nilaiMedan("kode_proses"), berat = nilaiMedan("berat_akhir").trim(), n = ++nomorSg;
      dataSg = null;pasangSg("pemilik",kode ? "Memuat konteks proses…" : "Pilih proses giling");
      pasangSg("konteks","");["terakhir","acuan","terpakai","hasil","beda","stok"].forEach(function (x) { pasangSg(x,"Belum tersedia"); });
      $("sg-silos").textContent = kode ? "Memuat pemeriksaan sumber…" : "Pilih proses untuk melihat seluruh sumber silo.";$("sg-peringatan").textContent = "";
      if (!kode) return Promise.resolve(null);
      var url = selesaiGiling.source + "?kode_proses=" + encodeURIComponent(kode);
      if (/^[+]?\d+(?:[.,]\d+)?$/.test(berat) && Number.isFinite(Number(berat.replace(",",".")))) url += "&berat_akhir=" + encodeURIComponent(berat.replace(",","."));
      return fetch(url,{credentials:"same-origin",cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("Konteks belum tersedia");return r.json();}).then(function(d){
        if(n!==nomorSg || !lembar.open || lembar.querySelector(".lembar__isi")!==borangHasil || kode!==nilaiMedan("kode_proses") || berat!==nilaiMedan("berat_akhir").trim())return null;
        if(d.kode_proses!==kode)throw new Error("Konteks tidak sesuai proses");dataSg=d;
        pasangSg("pemilik",d.pemilik);pasangSg("konteks",d.kepemilikan+" · "+({berjalan:"Berjalan",dijeda:"Dijeda",selesai:"Selesai"}[d.status]||d.status)+" · "+d.silos.join(" + ")+" · Mulai "+d.mulai+(d.sebab_jeda?" · Jeda: "+d.sebab_jeda:""));
        pasangSg("terakhir",d.tercatat==null?"Belum ada hasil operator":kgSg(d.tercatat));
        pasangSg("acuan",(d.bobot_final?"":"Sementara · ")+kgSg(d.bobot_acuan));
        pasangSg("terpakai",d.terpakai==null?"Belum dapat dipastikan":(d.bobot_final?"":"Sementara · ")+kgSg(d.terpakai));
        var sah = !berat || (/^[+]?\d+(?:[.,]\d+)?$/.test(berat) && Number(berat.replace(",","."))>0);
        pasangSg("hasil",sah?kgSg(d.hasil_akhir):"Belum ada angka valid");pasangSg("beda",sah&&d.perubahan!=null?(d.perubahan>0?"+":"")+kgSg(d.perubahan):"Belum ada pembanding");pasangSg("stok",sah?kgSg(d.stok_sesudah):"Belum dapat dihitung");
        $("sg-silos").innerHTML=sumberSg(d);
        var notes=[];if(d.terverifikasi!=null)notes.push("Verifikasi output Admin "+kgSg(d.terverifikasi)+" tetap menjadi dasar stok. Isian ini mencatat hasil operator dan tidak mengganti verifikasi tersebut.");
        if(!d.bobot_final)notes.push("Bobot bahan belum final. Perbandingan hasil masih sementara; pemutakhiran mengikuti mekanisme timbang lama.");
        if(d.status==="selesai")notes.push("Proses sudah selesai. Buka detail terbaru; penyelesaian ulang tidak tersedia.");
        notes.forEach(function(t){var p=document.createElement("p");p.className="sg-warning";p.textContent=t;$("sg-peringatan").appendChild(p);});
        $("sg-bebaskan").hidden=d.sisa_lengkap||d.status==="selesai";$("simpan").disabled=d.status==="selesai";
        return d;
      }).catch(function(){if(n!==nomorSg || lembar.querySelector(".lembar__isi")!==borangHasil)return null;pasangSg("pemilik","Konteks belum tersedia");pasangSg("konteks","Isian tetap utuh. Periksa penyelesaian untuk meminta pemeriksaan server terbaru.");$("sg-silos").textContent="Pemeriksaan sumber belum dapat dimuat.";return null;});
    }
    function konfirmasiSg(d) {
      function pair(a,b,utama){return '<div'+(utama?' class="sg-total"':'')+'><dt>'+esc(a)+'</dt><dd>'+esc(b)+'</dd></div>';}
      return '<div class="sg-stage"><span>Isi hasil akhir →</span><strong>Periksa & konfirmasi</strong></div><div class="sg-review-head"><h3>'+esc(d.kode_proses)+'</h3><p>'+esc(d.pemilik+' · '+d.silos.join(' + '))+'</p></div>'+sumberSg(d)+
        '<section class="sg-summary"><h3>Hasil dan stok setelah selesai</h3><dl>'+pair('Hasil akhir PK operator',kgSg(d.hasil_akhir))+(d.terverifikasi!=null?pair('Dasar stok · verifikasi Admin',kgSg(d.terverifikasi)):'')+pair('Transfer terkirim',kgSg(d.transfer))+pair('Penjualan PK langsung',kgSg(d.penjualan))+pair('Retur diterima',kgSg(d.retur))+pair('PK tersedia',kgSg(d.stok_sesudah),true)+'</dl><small>PK tersedia sebelumnya '+esc(kgSg(d.stok_sebelum))+'. Penyelesaian tidak menambahkan hasil kumulatif dua kali.</small></section><p class="sg-warning">Konfirmasikan setelah mesin benar-benar selesai. Sisa tetap berada di silo; penyelesaian tidak mengosongkannya. Verifikasi output Admin tetap tindakan terpisah.</p>';
    }
    if(selesaiGiling){
      kembaliSelesaiGiling=null;
      borangHasil.querySelector('.lembar__kepala').insertAdjacentHTML('afterend','<div class="sg-stage"><strong>Isi hasil akhir</strong><span>→ Periksa ringkasan → Konfirmasi selesai</span></div><div class="sg-context"><strong id="sg-pemilik">Pilih proses giling</strong><small id="sg-konteks"></small></div>');
      var grupSg=borangHasil.querySelector('.grup'),tataSg=document.createElement('div');tataSg.className='sg-layout';grupSg.before(tataSg);tataSg.appendChild(grupSg);
      ['kode_proses','berat_akhir'].forEach(function(nama){
        var input=grupSg.querySelector('[data-name="'+nama+'"]'),kunci=input.type==='hidden'?input.previousElementSibling:null,label=grupSg.querySelector('label[for="f_'+nama+'"]'),wadah=document.createElement('div');wadah.className='hasil-field';
        grupSg.insertBefore(wadah,label||kunci||input);
        if(label)wadah.appendChild(label);
        if(kunci){wadah.insertAdjacentHTML('beforeend','<span class="lbl">Proses giling</span>');wadah.appendChild(kunci);kunci.setAttribute('role','textbox');kunci.setAttribute('aria-label','Proses giling');kunci.setAttribute('aria-readonly','true');}
        wadah.appendChild(input);
      });
      var angkaSg=$('f_berat_akhir'),unitSg=document.createElement('div');unitSg.className='hasil-unit';angkaSg.before(unitSg);unitSg.appendChild(angkaSg);unitSg.insertAdjacentHTML('beforeend','<span aria-hidden="true">kg</span>');
      grupSg.insertAdjacentHTML('beforeend','<p class="hasil-help">Total akhir PK proses ini, bukan tambahan sejak catatan terakhir. Kosongkan hanya untuk memakai hasil operator terakhir yang sudah tercatat.</p><div class="hasil-before"><span>PK terakhir tercatat</span><strong id="sg-terakhir">Belum tersedia</strong></div>');
      tataSg.insertAdjacentHTML('beforeend','<div class="sg-preview" aria-live="polite"><div id="sg-silos"></div><button class="sg-link btn" id="sg-bebaskan" type="button" hidden>Buka Bebaskan silo</button><section class="sg-summary"><h3>Ringkasan hasil akhir</h3><dl><div><dt>Gabah acuan</dt><dd id="sg-acuan">Belum tersedia</dd></div><div><dt>Bahan terpakai tercatat</dt><dd id="sg-terpakai">Belum tersedia</dd></div><div><dt>Hasil PK operator</dt><dd id="sg-hasil">Belum tersedia</dd></div><div><dt>Perubahan dari catatan terakhir</dt><dd id="sg-beda">Belum tersedia</dd></div><div class="sg-total"><dt>PK tersedia sesudah selesai</dt><dd id="sg-stok">Belum tersedia</dd></div></dl><small>Stok memakai hasil yang berlaku, retur diterima, transfer terkirim dan penjualan langsung. Hasil kumulatif tidak ditambahkan sebagai stok baru.</small></section><div id="sg-peringatan"></div></div>');
      $('sg-bebaskan').onclick=function(){kembaliSelesaiGiling={draft:terbaca(),kode:nilaiMedan('kode_proses')};kembaliSelesaiGiling.draft['kode:kode_proses']=kembaliSelesaiGiling.kode;lembar._berubah=false;bukaAksi('tutup_silo_giling',{kode_proses:kembaliSelesaiGiling.kode,_dariSelesaiGiling:true});};
      borangHasil.addEventListener('input',function(e){if(e.target.dataset.name==='berat_akhir'){bersihkanSalah(lembar);clearTimeout(timerSg);timerSg=setTimeout(perbaruiSg,150);}});
      borangHasil.addEventListener('change',function(e){if(e.target.dataset.name==='kode_proses'){bersihkanSalah(lembar);perbaruiSg();}});perbaruiSg();
    }
    // Tambahan G2 tetap satu kiriman kode + array silo. Ringkasan hanya baca;
    // tidak memakai syarat Mulai penyosohan untuk silo kosong yang dipakai ulang.
    var dataTs=null, nomorTs=0, nomorOpsiTs=0, timerTs, risikoTs=false;
    function pilihanTs(){var e=borangHasil.querySelector('[data-name="silo"][data-banyak]');return String(e&&e.value||'').split(',').filter(Boolean);}
    function pasangTs(k,v){var e=$('ts-'+k);if(e)e.textContent=v;}
    function kartuTs(o){var r=o.rincian;if(!r)return esc(o.label);return '<span class="ts-name"><strong>'+esc(r.nama)+'</strong><strong>'+esc(r.kosong?'Kosong':r.bobot)+'</strong></span><span class="ts-owner">'+esc(r.pakai_kembali?'Pakai kembali':r.pemilik)+((r.pesanan||[]).length?' · '+esc(r.pesanan.join(' · ')):'')+'</span><small>'+esc(r.kosong?'Pemakaian baru dibuka; bahan boleh diisi setelahnya.':(r.komposisi||[]).map(function(k){return k.jenis+' '+k.bobot;}).join(' + ')||'Komposisi belum tersedia')+'</small>';}
    function gambarTs(d){
      pasangTs('pemilik',d.pemilik);pasangTs('milik',d.kepemilikan);pasangTs('status',d.status==='dijeda'?'Dijeda':d.status==='selesai'?'Selesai':'Berjalan');
      pasangTs('konteks',[d.kode,d.pesanan,d.sumber_aktif.length?'Sumber aktif '+d.sumber_aktif.join(' + '):'Seluruh silo sebelumnya sudah dibebaskan',d.sebab_jeda].filter(Boolean).join(' · '));
      pasangTs('silo',d.silos.map(function(r){return r.nama;}).join(' + ')||'Belum dipilih');pasangTs('total',d.tambahan);pasangTs('owner',d.pemilik);
      pasangTs('impact',d.status==='selesai'?'Proses sudah selesai; silo tidak dapat ditambahkan. Buka detail untuk melihat keadaan terbaru.':'Tetap pada proses yang sama. Penyosohan '+(d.status==='dijeda'?'tetap dijeda':'tetap berjalan')+'; hasil dan sisa dicatat melalui tindakan yang sudah ada.');
      var ulang=d.silos.filter(function(r){return r.pakai_kembali;}),kosong=ulang.some(function(r){return r.kosong;});$('ts-reuse').hidden=!ulang.length;
      pasangTs('reuse-title',kosong?'Silo kosong dipakai kembali':'Pemakaian baru pada silo yang sama');pasangTs('reuse-text',kosong?'Pemakaian baru dimulai dengan bahan awal 0 kg untuk silo yang kosong. Bahan dapat diisi setelah silo ditambahkan. Riwayat sebelumnya tetap tersimpan.':'Saldo tersedia menjadi bahan awal pemakaian baru. Riwayat sisa dan bahan terpakai sebelumnya tetap tersimpan.');
      $('ts-warning').innerHTML=d.peringatan.map(function(x){return '<p>'+esc(x)+'</p>';}).join('');$('ts-warning').hidden=!d.peringatan.length;
      $('ts-details').hidden=!d.silos.length;$('ts-sumber').innerHTML=d.silos.map(function(r){return '<article class="ts-source"><strong>'+esc(r.nama+' · '+(r.kosong?'Kosong · menunggu pengisian':r.bobot))+'</strong><span>'+esc((r.komposisi||[]).map(function(k){return k.jenis+' '+k.bobot;}).join(' + ')||'Komposisi belum tersedia')+'</span>'+(r.sumber||[]).map(function(x){return '<small>'+esc(x.kode+' · '+x.jenis+' · '+x.bobot+' · '+x.pemilik)+'</small>';}).join('')+'</article>';}).join('');
    }
    function perbaruiTs(){
      if(!tambahSosoh||!lembar.open||lembar.querySelector('.lembar__isi')!==borangHasil)return Promise.resolve(null);
      clearTimeout(timerTs);var n=++nomorTs,kode=nilaiMedan('kode'),pilihan=pilihanTs(),kunci=pilihan.join(',');dataTs=null;
      pasangTs('total',kode?'Memuat ringkasan…':'Pilih proses dahulu');pasangTs('silo',pilihan.length?pilihan.join(' + '):'Belum dipilih');pasangTs('owner','Belum tersedia');pasangTs('pemilik',kode?'Memuat konteks…':'Pilih proses penyosohan');pasangTs('milik','');pasangTs('status','');pasangTs('konteks','');$('ts-details').hidden=true;$('ts-reuse').hidden=true;$('ts-warning').hidden=true;
      if(!kode){pasangTs('pemilik','Pilih proses penyosohan');pasangTs('milik','');pasangTs('status','');pasangTs('konteks','');return Promise.resolve(null);}
      return new Promise(function(resolve){timerTs=setTimeout(async function(){try{var url=tambahSosoh.source+'?kode='+encodeURIComponent(kode);pilihan.forEach(function(x){url+='&silo='+encodeURIComponent(x);});var r=await fetch(url,{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error();var d=await r.json();
        if(n!==nomorTs||!borangHasil.isConnected||!lembar.open||nilaiMedan('kode')!==kode||pilihanTs().join(',')!==kunci){resolve(null);return;}
        if(d.kode!==kode||!Array.isArray(d.silos))throw new Error();dataTs=d;gambarTs(d);resolve(d);
      }catch(_){if(n===nomorTs&&borangHasil.isConnected){pasangTs('total','Belum tersedia');pasangTs('pemilik','Konteks belum tersedia');$('ts-warning').hidden=false;$('ts-warning').textContent='Ringkasan belum dapat dimuat; bukan bahan nol. Pilihan tetap utuh dan penyimpanan tetap diperiksa oleh layanan.';}resolve(null);}},150);});
    }
    if(tambahSosoh){
      borangHasil.querySelector('.lembar__kepala').insertAdjacentHTML('afterend','<div class="ts-context"><div class="ts-top"><span id="ts-milik"></span><strong id="ts-status"></strong></div><strong id="ts-pemilik">Pilih proses penyosohan</strong><small id="ts-konteks"></small></div>');
      var grupTs=borangHasil.querySelector('.grup'),tataTs=document.createElement('div');tataTs.className='ts-layout';grupTs.before(tataTs);tataTs.appendChild(grupTs);
      var kodeTs=grupTs.querySelector('[data-name="kode"]'),kunciTs=kodeTs.type==='hidden'?kodeTs.previousElementSibling:null,labelTs=grupTs.querySelector('label[for="f_kode"]'),fieldTs=document.createElement('div');fieldTs.className='hasil-field';grupTs.insertBefore(fieldTs,labelTs||kunciTs||kodeTs);if(labelTs)fieldTs.appendChild(labelTs);if(kunciTs){fieldTs.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(kodeTs.dataset.label)+'</span>');fieldTs.appendChild(kunciTs);kunciTs.setAttribute('role','textbox');kunciTs.setAttribute('aria-readonly','true');kunciTs.setAttribute('aria-label',kodeTs.dataset.label);}fieldTs.appendChild(kodeTs);
      var daftarTs=$('b_silo'),judulTs=daftarTs.previousElementSibling,groupTs=document.createElement('fieldset');groupTs.className='ts-fieldset';var legendTs=document.createElement('legend');legendTs.textContent=judulTs.textContent;judulTs.replaceWith(groupTs);groupTs.append(legendTs,daftarTs);daftarTs.textContent='Pilih proses terlebih dahulu untuk melihat silo yang sesuai.';
      tataTs.insertAdjacentHTML('beforeend','<div class="ts-preview" aria-live="polite"><section class="ts-summary"><h3>Ringkasan tambahan</h3><dl><div><dt>Silo dipilih</dt><dd id="ts-silo">Belum dipilih</dd></div><div class="ts-total"><dt>Bahan awal pemakaian baru</dt><dd id="ts-total">Pilih silo dahulu</dd></div><div><dt>Pemilik proses</dt><dd id="ts-owner">Belum tersedia</dd></div></dl><small>Bobot tambahan mengikuti saldo saat disimpan. Pemakaian akhir dihitung setelah sisa diperiksa.</small></section><section class="ts-info" id="ts-reuse" hidden><strong id="ts-reuse-title"></strong><p id="ts-reuse-text"></p></section><section class="ts-warning" id="ts-warning" hidden></section><details class="ts-details" id="ts-details" hidden><summary>Lihat komposisi &amp; asal bahan</summary><p class="ts-help">Riwayat asal tetap dapat ditelusuri; bobot asal bukan pembagian saldo tersedia per lot.</p><div id="ts-sumber"></div></details></div>');
      borangHasil.querySelector('.hasil-actions').insertAdjacentHTML('beforebegin','<p class="ts-impact" id="ts-impact">Tetap pada proses yang sama. Hasil dan sisa dicatat melalui tindakan yang sudah ada.</p><button type="button" class="btn ts-check" id="ts-periksa" hidden>Periksa pilihan terbaru</button><a class="btn ts-check" id="ts-detail" hidden>Lihat penyosohan</a>');
      $('ts-periksa').onclick=async function(){var e=this;e.disabled=true;var d=await perbaruiTs();if(d){if(d.silos.some(function(x){return x.pemakaian_aktif;})){$('ts-warning').hidden=false;$('ts-warning').textContent='Sumber sudah terikat pada proses. Periksa hasil di detail; jangan mengirim ulang.';}else{risikoTs=false;$('simpan').disabled=false;pasangTs('impact','Pilihan terbaru sudah dibaca. Periksa ringkasan sebelum mencoba menyimpan kembali.');}}e.disabled=false;};
      borangHasil.addEventListener('change',function(e){if(e.target.dataset.name==='kode'){var v=borangHasil.querySelector('[data-name="silo"][data-banyak]');v.value='';v.dataset.teks='';if(!nilaiMedan('kode'))daftarTs.textContent='Pilih proses terlebih dahulu untuk melihat silo yang sesuai.';bersihkanSalah(lembar);perbaruiTs();$('simpan').textContent=labelSimpan;}});perbaruiTs();
    }

    // G2 membaca satu pemakaian terbuka. Ketikan/tombol tetap elemen yang
    // sama saat ringkasan diperbarui; blur tidak merender ulang formulir.
    var dataBsp=null, nomorBsp=0, timerBsp, memeriksaBsp=false, risikoBsp=false;
    function angkaBsp(){var t=nilaiMedan('sisa').trim();return /^[+]?\d+(?:[.,]\d+)?$/.test(t)&&Number.isFinite(Number(t.replace(',','.')))?Number(t.replace(',','.')):null;}
    function pasangBsp(k,v){var e=$('bsp-'+k);if(e)e.textContent=v;}
    function pasanganBsp(k,v,total){return '<div'+(total?' class="bsp-total"':'')+'><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>';}
    function bobotBsp(d,v){return v==null?'Belum diketahui':(d.bobot_final?'':'Sementara · ')+kgHasil(v);}
    function konteksBsp(d){return [d.kode_proses,d.pesanan,d.mulai?'Mulai '+d.mulai:'Waktu mulai belum tersedia',d.status==='dijeda'?d.sebab_jeda:null].filter(Boolean).join(' · ');}
    function statusBsp(d){return d.status==='dijeda'?'Dijeda':d.status==='selesai'?'Selesai':'Berjalan';}
    function sumberBsp(d){return d.sumber.map(function(r){return '<article class="bsp-source"><strong>'+esc(r.silo)+' · pemakaian #'+esc(r.id)+'</strong><small>'+esc(r.terbuka?'Masih terikat pada proses':'Sudah dibebaskan · sisa '+kgHasil(r.sisa))+'</small><small>Awal '+esc(kgHasil(r.awal))+' · tambahan '+esc(kgHasil(r.tambahan))+(r.dinamis?' · bobot mengikuti sumber karung':'')+'</small></article>';}).join('')||'<p>Sumber pemakaian belum tersedia.</p>';}
    function akibatBsp(d){return d.sisa==null?'Isi sisa berdasarkan pemeriksaan fisik.':d.sisa===0?'Sisa 0 menyatakan pemakaian ini tidak menyisakan bahan. Isi silo mengikuti perhitungan aktual.':'Sisa '+kgHasil(d.sisa)+' tetap berada di silo beserta pemilik dan jejak bahannya.';}
    function gambarBsp(d){
      pasangBsp('pemilik',d.pemilik);pasangBsp('milik',d.kepemilikan);pasangBsp('status',statusBsp(d));pasangBsp('konteks',konteksBsp(d));
      pasangBsp('awal',d.terbuka?bobotBsp(d,d.awal):'Pilih pemakaian terbuka');pasangBsp('tambahan',d.terbuka?bobotBsp(d,d.tambahan):'Belum tersedia');pasangBsp('sisa',d.sisa==null?'Belum diisi dengan benar':kgHasil(d.sisa));pasangBsp('terpakai',d.terpakai==null?'Belum dapat dihitung':bobotBsp(d,d.terpakai));
      pasangBsp('info',d.terbuka?'Pemakaian #'+d.pemakaian_id+' · '+d.silo+(d.bobot_final?' · bobot tercatat':' · bobot belum final; sinkronisasi karung tetap berlaku'):nilaiMedan('silo')?'Pemakaian tidak lagi terbuka. Sisa yang sudah tercatat tidak dapat ditimpa; gunakan koreksi Admin bila keliru.':'Pilih silo untuk melihat pemakaian yang masih terbuka.');
      pasangBsp('akibat',akibatBsp(d));pasangBsp('proses','Ikatan pemakaian yang dipilih dilepas. Penyosohan '+(d.status==='dijeda'?'tetap dijeda':'tetap berjalan')+'; hasil masih dapat dicatat.');
      $('bsp-sumber').innerHTML=sumberBsp(d);$('bsp-rincian').hidden=!d.sumber.length;
    }
    function perbaruiBsp(){
      if(!bebaskanSosoh||!lembar.open||lembar.querySelector('.lembar__isi')!==borangHasil)return Promise.resolve(null);
      var pilihanBsp=$('f_silo');if(pilihanBsp)Array.from(pilihanBsp.options).forEach(function(o){if(o.value){o.title=o.dataset.labelLengkap||o.textContent;o.dataset.labelLengkap=o.title;o.textContent=o.title.replace(/\s*\(awal .*$/, '');}});
      clearTimeout(timerBsp);var n=++nomorBsp,kode=nilaiMedan('kode_proses'),silo=nilaiMedan('silo'),teks=nilaiMedan('sisa');dataBsp=null;
      pasangBsp('pemilik',kode?'Memuat konteks…':'Pilih proses penyosohan');pasangBsp('milik','');pasangBsp('status','');pasangBsp('konteks','');['awal','tambahan','terpakai'].forEach(function(k){pasangBsp(k,'Belum tersedia');});pasangBsp('sisa',angkaBsp()==null?'Belum diisi dengan benar':kgHasil(angkaBsp()));pasangBsp('info',kode?'Memuat pemakaian silo…':'Pilih proses dan silo untuk melihat ringkasan.');$('bsp-rincian').hidden=true;
      if(!kode)return Promise.resolve(null);
      return new Promise(function(resolve){timerBsp=setTimeout(async function(){try{
        var url=bebaskanSosoh.source+'?kode_proses='+encodeURIComponent(kode)+'&silo='+encodeURIComponent(silo),angka=angkaBsp();if(angka!=null)url+='&sisa='+encodeURIComponent(angka);
        var r=await fetch(url,{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error();var d=await r.json();
        if(n!==nomorBsp||!lembar.open||lembar.querySelector('.lembar__isi')!==borangHasil||nilaiMedan('kode_proses')!==kode||nilaiMedan('silo')!==silo||nilaiMedan('sisa')!==teks){resolve(null);return;}
        if(d.kode_proses!==kode||!Array.isArray(d.sumber))throw new Error();dataBsp=d;gambarBsp(d);resolve(d);
      }catch(_){if(n===nomorBsp&&borangHasil.isConnected){pasangBsp('pemilik','Konteks belum tersedia');pasangBsp('info','Ringkasan belum dapat dimuat; bukan bahan nol. Isian tetap utuh. Periksa sisa silo untuk meminta pemeriksaan server terbaru.');}resolve(null);}},150);});
    }
    function konfirmasiBsp(d){
      return '<div class="bsp-review-head"><div class="bsp-top"><span>'+esc(d.kepemilikan)+'</span><strong>'+esc(statusBsp(d))+'</strong></div><h3>'+esc(d.kode_proses+' · '+d.silo)+'</h3><strong>'+esc(d.pemilik)+'</strong><small>'+esc(konteksBsp(d))+' · pemakaian #'+esc(d.pemakaian_id)+'</small></div>'+
        '<div class="bsp-review-grid"><section class="bsp-summary"><h3>Hasil pemeriksaan</h3><dl>'+pasanganBsp('Bahan awal pemakaian',bobotBsp(d,d.awal))+pasanganBsp('Tambahan selama pemakaian',bobotBsp(d,d.tambahan))+pasanganBsp('Sisa fisik yang diperiksa',kgHasil(d.sisa))+pasanganBsp('Bahan terpakai',bobotBsp(d,d.terpakai),true)+'</dl></section>'+
        '<section class="bsp-warning"><strong>'+esc(d.sisa===0?'Konfirmasi silo benar-benar kosong':'Sisa tetap tersedia di silo')+'</strong><p>'+esc(akibatBsp(d))+'</p><p>Hanya ikatan pemakaian silo ini yang dilepas.</p></section></div>'+
        '<section class="bsp-note"><h3>Penyosohan '+esc(d.status==='dijeda'?'tetap dijeda':'tetap berjalan')+'</h3><p>Hasil tetap dapat dicatat. Selesaikan penyosohan tetap tindakan terpisah, termasuk untuk silo terakhir.</p></section>'+
        '<details class="bsp-sources"><summary>Lihat seluruh pemakaian proses</summary>'+sumberBsp(d)+'</details>';
    }
    function hasilTerkiniBsp(isi){var info=document.createElement('p');info.className='bsp-note';info.textContent='Sisa tersimpan; memuat keadaan silo terbaru…';$('kabar').appendChild(info);fetch(bebaskanSosoh.source+'?kode_proses='+encodeURIComponent(isi.kode_proses)+'&silo='+encodeURIComponent(isi.silo),{credentials:'same-origin',cache:'no-store'}).then(function(r){if(!r.ok)throw new Error();return r.json();}).then(function(d){if(d.kode_proses!==isi.kode_proses)throw new Error();info.textContent='Penyosohan '+(d.status==='dijeda'?'tetap dijeda':'tetap berjalan')+'; hasil masih dapat dicatat. '+d.silo_sekarang.map(function(x){return x.silo+' · '+x.status+' · '+kgHasil(x.kg);}).join(' | ');}).catch(function(){info.textContent='Sisa sudah tersimpan. Keadaan silo terbaru belum dapat dibaca; periksa detail sebelum tindakan berikutnya.';});}
    if(bebaskanSosoh){
      borangHasil.querySelector('.lembar__kepala').insertAdjacentHTML('afterend','<div class="bsp-stage"><strong>Catat sisa</strong><span>→ Periksa → Konfirmasi</span></div><div class="bsp-context"><div class="bsp-top"><span id="bsp-milik"></span><strong id="bsp-status"></strong></div><strong id="bsp-pemilik">Pilih proses penyosohan</strong><small id="bsp-konteks"></small></div>');
      var grupBsp=borangHasil.querySelector('.grup'),tataBsp=document.createElement('div');tataBsp.className='bsp-layout';grupBsp.before(tataBsp);tataBsp.appendChild(grupBsp);
      ['kode_proses','silo','sisa'].forEach(function(nama){var input=grupBsp.querySelector('[data-name="'+nama+'"]'),kunci=input.type==='hidden'?input.previousElementSibling:null,label=grupBsp.querySelector('label[for="f_'+nama+'"]'),wadah=document.createElement('div');wadah.className='hasil-field';grupBsp.insertBefore(wadah,label||kunci||input);if(label)wadah.appendChild(label);if(kunci){wadah.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(input.dataset.label)+'</span>');wadah.appendChild(kunci);kunci.setAttribute('role','textbox');kunci.setAttribute('aria-readonly','true');kunci.setAttribute('aria-label',input.dataset.label);}wadah.appendChild(input);});
      var sisaBsp=$('f_sisa'),unitBsp=document.createElement('div');unitBsp.className='hasil-unit';sisaBsp.before(unitBsp);unitBsp.appendChild(sisaBsp);unitBsp.insertAdjacentHTML('beforeend','<span aria-hidden="true">kg</span>');sisaBsp.setAttribute('aria-describedby','bsp-hint');unitBsp.insertAdjacentHTML('afterend','<p class="hasil-help" id="bsp-hint">Wajib diisi dari pemeriksaan fisik. Isi 0 hanya jika silo benar-benar kosong.</p>');
      tataBsp.insertAdjacentHTML('beforeend','<div class="bsp-preview" aria-live="polite"><section class="bsp-summary"><h3>Ringkasan pemakaian silo</h3><dl><div><dt>Bahan awal pemakaian</dt><dd id="bsp-awal">Belum tersedia</dd></div><div><dt>Tambahan selama pemakaian</dt><dd id="bsp-tambahan">Belum tersedia</dd></div><div><dt>Sisa yang diperiksa</dt><dd id="bsp-sisa">Belum diisi</dd></div><div class="bsp-total"><dt>Bahan terpakai</dt><dd id="bsp-terpakai">Belum dapat dihitung</dd></div></dl><small id="bsp-info"></small></section><section class="bsp-impact"><h3>Setelah disimpan</h3><p id="bsp-akibat">Sisa tetap berada di silo sesuai pemeriksaan.</p><p id="bsp-proses">Hanya ikatan pemakaian silo dilepas; penyosohan dan pencatatan hasil tetap berjalan.</p></section><details class="bsp-sources" id="bsp-rincian" hidden><summary>Lihat seluruh pemakaian proses</summary><div id="bsp-sumber"></div></details></div>');
      borangHasil.addEventListener('input',function(e){if(e.target.dataset.name==='sisa'){bersihkanSalah(lembar);perbaruiBsp();}});
      borangHasil.addEventListener('change',function(e){if(['kode_proses','silo'].indexOf(e.target.dataset.name)>=0){sisaBsp.value='';if(e.target.dataset.name==='kode_proses'){$('f_silo').value='';}bersihkanSalah(lembar);perbaruiBsp();}});perbaruiBsp();
    }

    // Hanya pembebasan silo giling G1. Sumber, selisih, saldo dan token
    // dijawab server; ketikan tidak dirender ulang saat input kehilangan fokus.
    var dataBs=null, nomorBs=0, timerBs, memeriksaBs=false, risikoBs=false;
    function pasangBs(n,t){var el=$('bs-'+n);if(el)el.textContent=t;}
    function angkaBs(){var t=nilaiMedan('sisa').trim();return /^[+]?\d+(?:[.,]\d+)?$/.test(t)&&Number.isFinite(Number(t.replace(',','.')))?Number(t.replace(',','.')):null;}
    function pasanganBs(a,b,utama){return '<div'+(utama?' class="bs-total"':'')+'><dt>'+esc(a)+'</dt><dd>'+esc(b)+'</dd></div>';}
    function sumberBs(d){return d.sumber.map(function(r){return '<article class="bs-source"><strong>'+esc(r.sumber)+'</strong><small>Sumber #'+esc(r.id)+' · '+esc(r.silo)+'</small><span>'+esc(r.bobot==null?'Menunggu timbang':kgHasil(r.bobot))+'</span></article>';}).join('');}
    function statusBs(d){return {berjalan:'Berjalan',dijeda:'Dijeda',selesai:'Selesai'}[d.status]||'Status belum diketahui';}
    function lencanaBs(d){return '<span class="bs-status" data-status="'+esc(d.status)+'">'+esc(statusBs(d))+'</span>';}
    function konteksBs(d){return [d.pesanan||'',d.mulai?'Mulai '+d.mulai:'',d.sebab_jeda?'Jeda: '+d.sebab_jeda:''].filter(Boolean).join(' · ');}
    function gambarBs(d){
      pasangBs('milik',d.kepemilikan);pasangBs('status',statusBs(d));$('bs-status').dataset.status=d.status;$('bs-status').hidden=false;
      pasangBs('pemilik',d.pemilik);pasangBs('konteks',konteksBs(d));pasangBs('silo',d.silo||'Belum dipilih');
      pasangBs('bahan',d.bahan==null?'Belum dapat dipastikan':(d.bobot_final?'':'Sementara · ')+kgHasil(d.bahan));
      pasangBs('sisa',d.sisa==null?'Belum diisi dengan benar':kgHasil(d.sisa));pasangBs('terpakai',d.terpakai==null?'Belum dapat dipastikan':(d.bobot_final?'':'Sementara · ')+kgHasil(d.terpakai));
      pasangBs('akibat',d.sisa===0?'Silo dinyatakan kosong berdasarkan pemeriksaan fisik. Ikatan ke proses dilepas.':'Sisa lebih dari 0 tetap berada di silo. Ikatan ke proses dilepas.');
      pasangBs('proses',d.status==='dijeda'?'Penggilingan tetap dijeda. Silo lain dan hasil PK tidak berubah.':'Penggilingan tidak diselesaikan. Silo lain dan hasil PK tidak berubah.');
      var ds=$('bs-rincian');ds.hidden=!d.sumber.length;$('bs-jumlah').textContent='Lihat '+d.sumber.length+' sumber pada siklus ini';$('bs-sumber').innerHTML=sumberBs(d);
      pasangBs('info',!d.sumber_proses.length?'Sumber proses lama belum dapat dipastikan. Minta Admin memeriksa sumber; tidak ada silo yang dikosongkan.':d.status==='selesai'?'Proses sudah selesai. Buka detail terbaru.':nilaiMedan('silo')&&!d.terbuka?'Silo ini tidak lagi terbuka. Periksa detail dan pilihan sumber terbaru.':d.terbuka&&d.bahan==null?'Bobot sumber belum lengkap. Sisa positif belum dapat dicatat. Isi 0 hanya jika pemeriksaan fisik memastikan silo benar-benar kosong.':'Bobot dan sumber mengikuti siklus yang masih terbuka, bukan seluruh riwayat silo.');
    }
    function perbaruiBs(){
      if(!bebaskanGiling||!lembar.open||lembar.querySelector('.lembar__isi')!==borangHasil)return;
      clearTimeout(timerBs);var kode=nilaiMedan('kode_proses'),silo=nilaiMedan('silo'),teks=nilaiMedan('sisa'),n=++nomorBs;dataBs=null;
      pasangBs('pemilik',kode?'Memuat konteks proses…':'Pilih proses giling');pasangBs('milik','');$('bs-status').hidden=true;pasangBs('konteks','');pasangBs('silo',silo?'Silo '+silo:'Belum dipilih');
      ['bahan','terpakai'].forEach(function(x){pasangBs(x,'Belum tersedia');});pasangBs('sisa',angkaBs()==null?'Belum diisi dengan benar':kgHasil(angkaBs()));$('bs-rincian').hidden=true;
      pasangBs('info',kode?'Memuat sumber siklus…':'Pilih proses dan silo untuk melihat ringkasan.');if(!kode)return;
      var url=bebaskanGiling.source+'?kode_proses='+encodeURIComponent(kode)+'&silo='+encodeURIComponent(silo);var angka=angkaBs();if(angka!=null)url+='&sisa='+encodeURIComponent(angka);
      timerBs=setTimeout(function(){fetch(url,{credentials:'same-origin',cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('Konteks belum tersedia');return r.json();}).then(function(d){
        if(n!==nomorBs||!borangHasil.isConnected||nilaiMedan('kode_proses')!==kode||nilaiMedan('silo')!==silo||nilaiMedan('sisa')!==teks)return;
        if(d.kode_proses!==kode)throw new Error('Konteks tidak sesuai proses');dataBs=d;gambarBs(d);
      }).catch(function(){if(n!==nomorBs||!borangHasil.isConnected)return;pasangBs('pemilik','Konteks belum tersedia');pasangBs('info','Isian tetap utuh. Periksa sisa silo untuk meminta pemeriksaan terbaru dari server.');});},150);
    }
    function hasilTerkiniBs(isi){
            var hasilBs=document.createElement('p');hasilBs.className='bs-note';hasilBs.textContent='Memuat keadaan silo terbaru…';$('kabar').appendChild(hasilBs);
            fetch(bebaskanGiling.source+'?kode_proses='+encodeURIComponent(isi.kode_proses)+'&silo='+encodeURIComponent(isi.silo),{credentials:'same-origin',cache:'no-store'}).then(function(r){if(!r.ok)throw new Error();return r.json();}).then(function(d){if(d.kode_proses!==isi.kode_proses)throw new Error();hasilBs.textContent='Penggilingan '+(d.status==='dijeda'?'tetap dijeda':d.status==='berjalan'?'tetap berjalan':'mengikuti status terbaru')+'. '+d.silo_sekarang.map(function(x){return x.silo+' · '+x.status+' · '+x.bobot;}).join(' | ');}).catch(function(){hasilBs.textContent='Sisa telah tersimpan. Keadaan silo terbaru belum dapat dimuat; periksa detail sebelum tindakan berikutnya.';});
    }
    function konfirmasiBs(d){return '<div class="bs-stage"><span>Catat sisa →</span><strong>Periksa & konfirmasi</strong></div><div class="bs-review-head"><div class="bs-context-top"><span>'+esc(d.kepemilikan)+'</span>'+lencanaBs(d)+'</div><h3>'+esc(d.kode_proses+' · '+d.silo)+'</h3><p>'+esc(d.pemilik+' · '+d.sumber.length+' sumber pada siklus yang diperiksa')+'</p><small>'+esc(konteksBs(d))+'</small></div><section class="bs-summary"><h3>Hasil pemeriksaan</h3><dl>'+pasanganBs('Bahan tercatat pada siklus ini',d.bahan==null?'Menunggu timbang':(d.bobot_final?'':'Sementara · ')+kgHasil(d.bahan))+pasanganBs('Sisa fisik yang diperiksa',kgHasil(d.sisa))+pasanganBs('Bahan terpakai',d.terpakai==null?'Menunggu timbang':(d.bobot_final?'':'Sementara · ')+kgHasil(d.terpakai),true)+'</dl></section><div class="bs-warning"><strong>'+(d.sisa===0?'Konfirmasi silo benar-benar kosong':'Sisa tetap tersedia di silo')+'</strong><p>'+esc(d.sisa===0?'Angka 0 menyatakan seluruh bahan pada siklus ini sudah keluar dari silo.':kgHasil(d.sisa)+' tetap tercatat di silo; tidak dihapus atau dipindahkan ke lot lain.')+' Ikatan silo pada proses dilepas; penggilingan tidak ditutup'+(d.status==='dijeda'?' dan tetap dijeda':'')+'.</p></div><div class="bs-note"><strong>Hasil dan stok PK tidak diubah</strong><p>Ini pencatatan sisa bahan. Silo lain tetap terikat sesuai keadaannya. Selesai giling tetap tindakan terpisah.</p></div><details class="bs-sources"><summary>Lihat sumber pada siklus yang diperiksa</summary>'+sumberBs(d)+'</details>';}
    if(bebaskanGiling){
      borangHasil.querySelector('.lembar__kepala').insertAdjacentHTML('afterend','<div class="bs-stage"><strong>Catat sisa</strong><span>→ Periksa ringkasan → Konfirmasi</span></div><div class="bs-context"><div class="bs-context-top"><span id="bs-milik"></span><span class="bs-status" id="bs-status" hidden></span></div><strong id="bs-pemilik">Pilih proses giling</strong><small id="bs-konteks"></small></div>');
      var grupBs=borangHasil.querySelector('.grup'),tataBs=document.createElement('div');tataBs.className='bs-layout';grupBs.before(tataBs);tataBs.appendChild(grupBs);
      ['kode_proses','silo','sisa'].forEach(function(nama){var input=grupBs.querySelector('[data-name="'+nama+'"]'),kunci=input.type==='hidden'?input.previousElementSibling:null,label=grupBs.querySelector('label[for="f_'+nama+'"]'),wadah=document.createElement('div');wadah.className='hasil-field';grupBs.insertBefore(wadah,label||kunci||input);if(label)wadah.appendChild(label);if(kunci){wadah.insertAdjacentHTML('beforeend','<span class="lbl">'+esc(input.dataset.label)+'</span>');wadah.appendChild(kunci);kunci.setAttribute('role','textbox');kunci.setAttribute('aria-label',input.dataset.label);kunci.setAttribute('aria-readonly','true');}wadah.appendChild(input);});
      var sisaBs=$('f_sisa'),unitBs=document.createElement('div');unitBs.className='hasil-unit';sisaBs.before(unitBs);unitBs.appendChild(sisaBs);unitBs.insertAdjacentHTML('beforeend','<span aria-hidden="true">kg</span>');sisaBs.setAttribute('aria-describedby','bs-hint');unitBs.insertAdjacentHTML('afterend','<p class="hasil-help" id="bs-hint">Wajib diisi dari pemeriksaan fisik. Isi 0 hanya jika benar-benar kosong.</p>');
      tataBs.insertAdjacentHTML('beforeend','<div class="bs-preview" aria-live="polite"><section class="bs-summary"><h3>Ringkasan pembebasan</h3><dl></dl><p class="hasil-help bs-summary-note" id="bs-info" role="status"></p></section></div>');
      tataBs.querySelector('.bs-summary dl').innerHTML='<div><dt>Silo terpilih</dt><dd id="bs-silo">Belum dipilih</dd></div><div><dt>Bahan siklus yang masih terbuka</dt><dd id="bs-bahan">Belum tersedia</dd></div><div><dt>Sisa yang diperiksa</dt><dd id="bs-sisa">Belum diisi</dd></div><div class="bs-total"><dt>Terpakai dari siklus ini</dt><dd id="bs-terpakai">Belum tersedia</dd></div>';
      tataBs.querySelector('.bs-preview').insertAdjacentHTML('beforeend','<section class="bs-impact"><h3>Setelah disimpan</h3><strong id="bs-akibat">Ikatan silo pada proses dilepas. Sisa yang diperiksa tetap tercatat.</strong><p id="bs-proses">Penggilingan tidak diselesaikan. Silo lain dan hasil PK tidak berubah.</p></section><details class="bs-sources" id="bs-rincian" hidden><summary id="bs-jumlah">Lihat sumber pada siklus ini</summary><div id="bs-sumber"></div></details>');
      borangHasil.addEventListener('input',function(e){if(e.target.dataset.name==='sisa'){bersihkanSalah(lembar);perbaruiBs();}});
      borangHasil.addEventListener('change',function(e){if(['kode_proses','silo'].indexOf(e.target.dataset.name)>=0){bersihkanSalah(lembar);perbaruiBs();}});perbaruiBs();
    }

    if(a.id==='tutup_silo_giling' && kembaliSelesaiGiling){
      borangHasil.querySelector('.lembar__kepala').insertAdjacentHTML('afterend','<p class="nota">Tindakan terpisah. Hasil akhir PK belum disimpan dan penggilingan belum selesai. Isian penyelesaian tetap disimpan sementara pada formulir.</p>');
      $('tutup').textContent='Kembali ke penyelesaian';$('tutup').onclick=function(){bukaAksi('selesai_giling',kembaliSelesaiGiling.draft);};
    }

    // Angka turunan tetap dijawab server yang memiliki sumber bobotnya.
    // Nomor urut dan identitas borang mencegah jawaban lama menimpa pilihan
    // baru saat jaringan lambat atau operator cepat mengganti tumpukan.
    var urutanPratinjau = 0, waktuPratinjau, kunciPratinjau = "";
    function perbaruiPratinjau(e) {
      var borang = lembar.querySelector(".lembar__isi");
      var daftar = (a.fields || []).filter(function (f) { return f.type === "pratinjau"; });
      if (!daftar.length) return;
      // Surat jalan yang diketik untuk satu sumber tidak boleh terbawa ke
      // partai lain: N yang salah menggeser seluruh bobot partai berikutnya.
      daftar.forEach(function (f) {
        var nama = e && e.target && e.target.dataset.name;
        ((f.bersihkan || {})[nama] || []).forEach(function (medan) {
          var el = $("f_" + medan);
          if (el) el.value = "";
        });
      });
      var kunci = daftar.map(function (f) {
        return f.source + "?" + (f.acuan || []).map(function (nama) {
          return encodeURIComponent(nama) + "=" + encodeURIComponent(nilaiMedan(nama));
        }).join("&");
      }).join("|");
      if (kunci === kunciPratinjau) return;
      kunciPratinjau = kunci;
      var urutan = ++urutanPratinjau;
      clearTimeout(waktuPratinjau);
      daftar.forEach(function (f) {
        var kotak = $("p_" + f.name);
        if (kotak) kotak.textContent = "Menghitung bobot…";
      });
      waktuPratinjau = setTimeout(function () {
        daftar.forEach(function (f) {
          var url = f.source + "?" + (f.acuan || []).map(function (nama) {
            return encodeURIComponent(nama) + "=" + encodeURIComponent(nilaiMedan(nama));
          }).join("&");
          ambil(url).then(function (hasil) {
            if (!hasil || urutan !== urutanPratinjau || !lembar.open ||
                lembar.querySelector(".lembar__isi") !== borang) return;
            var kotak = $("p_" + f.name);
            if (kotak) kotak.textContent = hasil.teks;
            (f.acuan || []).forEach(function (nama) {
              var el = $("f_" + nama);
              if (!el || !el.dataset.angka) return;
              var nonaktif = (hasil.nonaktif || []).indexOf(nama) >= 0;
              el.disabled = nonaktif;
              el.dataset.pratinjauNonaktif = nonaktif ? "1" : "";
              el.hidden = nonaktif;
              var label = lembar.querySelector('label[for="f_' + nama + '"]');
              if (label) label.hidden = nonaktif;
            });
          }).catch(function () {
            if (urutan !== urutanPratinjau || lembar.querySelector(".lembar__isi") !== borang) return;
            var kotak = $("p_" + f.name);
            if (kotak) kotak.textContent = "Bobot belum dapat dimuat. Periksa jaringan; bobot diperiksa kembali saat menyimpan.";
          });
        });
      }, 150);
    }
    if (lembar._pratinjau) {
      lembar.removeEventListener("input", lembar._pratinjau);
      lembar.removeEventListener("change", lembar._pratinjau);
    }
    lembar._pratinjau = perbaruiPratinjau;
    lembar.addEventListener("input", perbaruiPratinjau);
    lembar.addEventListener("change", perbaruiPratinjau);
    perbaruiPratinjau();

    /* Nilai sebuah medan, apa pun bentuknya di layar: pilihan biasa, atau
       isian TERKUNCI yang menyimpan kodenya di kolom tersembunyi (kartu yang
       membuka lembar ini sudah menyebut bendanya). Medan yang bergantung
       padanya harus bekerja di kedua bentuk — kalau tidak, daftar silo kosong
       justru pada jalan yang paling sering dipakai: menekan kartunya. */
    var acuanJeda = {};
    var kunciJeda = a.pratinjau_jeda ? Array.prototype.map.call(crypto.getRandomValues(new Uint8Array(16)), function (n) {
      return n.toString(16).padStart(2, "0");
    }).join("") : "";
    function ambilAcuanJeda() {
      if (!a.pratinjau_jeda) return;
      var proses = nilaiMedan("proses");
      if (!proses || acuanJeda[proses]) return;
      var borangJeda = lembar.querySelector(".lembar__isi");
      ambil("/api/actions/acuan-jeda?proses=" + encodeURIComponent(proses)).then(function (j) {
        if (j && lembar.open && lembar.querySelector(".lembar__isi") === borangJeda && !acuanJeda[proses]) acuanJeda[proses] = j;
      }).catch(function () { /* Simpan tetap memeriksa keadaan terbaru. */ });
    }
    function aturWaktuJeda() {
      if (!a.pratinjau_jeda) return;
      var aktual = nilaiMedan("waktu_mode") === "aktual";
      (a.fields || []).forEach(function (f) {
        if (!f.waktu_aktual && f.name !== "sebab_lain") return;
        var el = $("f_" + f.name);
        var tampil = f.waktu_aktual ? aktual : nilaiMedan("sebab") === "Lainnya";
        if (!el) return;
        el.hidden = !tampil; el.disabled = !tampil;
        if (f.name === "sebab_lain") {
          if (tampil) el.setAttribute("data-wajib", "1"); else el.removeAttribute("data-wajib");
        }
        var label = lembar.querySelector('label[for="f_' + f.name + '"]');
        if (label) label.hidden = !tampil;
      });
    }
    var acuanMuat = {};
    function ambilAcuanMuat() {
      if (!a.pratinjau_muat) return;
      var perintah = nilaiMedan("perintah");
      if (!perintah) return;
      if (acuanMuat[perintah]) { perbaruiKonteksMuat(); return; }
      var borangAcuan = lembar.querySelector(".lembar__isi");
      ambil("/api/actions/pratinjau-muat?perintah=" + encodeURIComponent(perintah)).then(function (j) {
        if (!lembar.open || lembar.querySelector(".lembar__isi") !== borangAcuan) return;
        if (j && !acuanMuat[perintah]) acuanMuat[perintah] = j;
        perbaruiKonteksMuat();
      }).catch(function () { /* Simpan tetap mengambil cuplikan terbaru. */ });
    }
    function perbaruiKonteksMuat() {
      if (a.pratinjau_muat === "cepat") {
        var cepat = acuanMuat[nilaiMedan("perintah")];
        if (!cepat) return;
        var daftar = $("aktual_cepat");
        if (!daftar) {
          daftar = document.createElement("div"); daftar.id = "aktual_cepat";
          $("f_sebab").previousElementSibling.insertAdjacentElement("beforebegin", daftar);
        }
        var lama = {};
        daftar.querySelectorAll("input").forEach(function (el) { lama[el.dataset.name] = el.value; });
        daftar.innerHTML = cepat.baris.map(function (b) {
          var nama = "aktual_" + b.id;
          return '<label class="lbl" for="f_' + nama + '">' + esc(b.nama) + '</label>' +
            '<p class="bantu">Perintah ' + b.perintah + ' ' + esc(b.satuan) +
            ' · tercatat ' + b.dimuat + ' ' + esc(b.satuan) + '</p>' +
            '<div class="aktual-cepat__jumlah"><input class="fld" id="f_' + nama + '" data-name="' + nama +
            '" data-wajib="1" data-angka="1" data-label="Jumlah aktual ' + esc(b.nama) +
            '" inputmode="' + (b.satuan === "karung" ? "numeric" : "decimal") +
            '" placeholder="Jumlah aktual" value="' + esc(lama[nama] || "") + '">' +
            '<span class="jumlah-berdampingan__satuan">' + esc(b.satuan) + '</span></div>';
        }).join("");
        return;
      }
      if (a.pratinjau_muat !== "baris" || !$("f_jumlah")) return;
      var acuan = acuanMuat[nilaiMedan("perintah")];
      var item = acuan && acuan.baris.find(function (b) {
        return String(b.id) === nilaiMedan("baris");
      });
      var nota = $("konteks_muat");
      if (!nota) {
        nota = document.createElement("p");
        nota.className = "bantu";
        nota.id = "konteks_muat";
        $("f_jumlah").insertAdjacentElement("afterend", nota);
      }
      nota.textContent = item
        ? "Total sebelumnya " + item.dimuat + " " + item.satuan +
          ". Isi total terbaru, bukan tambahannya. " +
          (item.satuan === "karung" ? "Contoh: 20 ditambah 10 → isi 30. Karung wajib bilangan bulat." : "Gunakan kg; pecahan diperbolehkan.")
        : "Pilih barang pada perintah ini untuk melihat jumlah sebelumnya.";
      $("f_jumlah").inputMode = item && item.satuan === "karung" ? "numeric" : "decimal";
    }
    function nilaiMedan(nama) {
      var s = $("f_" + nama);
      if (s) { return s.value; }
      var sembunyi = lembar.querySelector('[data-name="' + nama + '"]');
      return sembunyi ? sembunyi.value : "";
    }

    function perbaruiMaksimalKemas() {
      var batas = $("maks_jumlah_karung");
      if (!batas) { return; }
      var sumber = $("f_sumber");
      var opsiSumber = sumber && sumber.options && sumber.selectedIndex >= 0
        ? sumber.options[sumber.selectedIndex] : null;
      var terkunciSumber = $("t_sumber");
      var berat = opsiSumber && opsiSumber.dataset.beratKg
        ? Number(opsiSumber.dataset.beratKg)
        : (terkunciSumber && terkunciSumber.dataset.beratKg
          ? Number(terkunciSumber.dataset.beratKg) : NaN);
      var kemasan = $("f_kemasan");
      var bagian = kemasan && kemasan.value ? kemasan.value.split("|") : [];
      var ukuran = bagian.length > 1 ? Number(bagian[bagian.length - 1]) : NaN;
      if (!Number.isFinite(berat) || !Number.isFinite(ukuran) || ukuran <= 0) {
        batas.textContent = nilaiMedan("sumber")
          ? "Pilih ukuran karung" : "Pilih proses & ukuran";
        batas.removeAttribute("data-jumlah");
        return;
      }
      var maksimal = Math.floor(berat / ukuran);
      batas.textContent = maksimal.toLocaleString("id-ID") + " karung";
      batas.dataset.jumlah = String(maksimal);
    }

    /* Kotak TEKS yang menyaring daftar jarak jauh sambil diketik — lihat
       catatan panjang pada `f.type === "kombo"` di atas. Daftarnya diambil
       SEKALI (`ambil(f.source)`, disimpan di elemen inputnya sendiri) lalu
       disaring di peramban tiap huruf; tak ada permintaan jaringan baru
       selama mengetik. Kolom tersembunyi yang membawa id-nya dikosongkan
       SETIAP KALI tulisannya berubah — pilihan lama tak boleh ikut
       terkirim diam-diam begitu orangnya mengetik nama lain. */
    function pasangKombo(f) {
      var masukan = $("x_" + f.name);
      var kotak = $("c_" + f.name);
      var simpanan = lembar.querySelector('[data-name="' + f.name + '"][data-cari]');
      if (!masukan || !kotak || !simpanan) { return; }

      ambil(f.source).then(function (daftar) {
        if (!daftar) { return; }
        masukan._daftarKombo = daftar;
        /* Pulih dari layar konfirmasi — oleh TULISANNYA (`terbaca()` cuma
           menyimpan label, bukan id), dicocokkan PERSIS sekali daftarnya
           datang. Sebangun `data-pulih` pada `muatBanyak`. */
        var pulih = simpanan.dataset.pulih;
        if (pulih !== undefined) {
          delete simpanan.dataset.pulih;
          var cocok = null;
          daftar.forEach(function (o) { if (o.label === pulih) cocok = o; });
          if (cocok) { masukan.value = cocok.label; simpanan.value = cocok.value; }
        }
        if (!daftar.length && !f.optional) {
          masukan.disabled = true;
          masukan.placeholder = f.kosong || "Belum ada pilihan.";
        }
      }).catch(function () {});

      // Pendengarnya terpasang SEKALI — `muatPilihan` bisa dipanggil ulang
      // (segar, lihat `segarkanPilihan`) selama lembarnya masih terbuka,
      // dan memasangnya lagi tiap kali berarti satu keystroke memicu
      // penyaringan berkali-kali lipat.
      if (masukan._komboTerpasang) { return; }
      masukan._komboTerpasang = true;

      function tutupSaran() { kotak.hidden = true; kotak.innerHTML = ""; }

      masukan.addEventListener("input", function () {
        simpanan.value = "";
        var q = masukan.value.trim().toLowerCase();
        var daftar = masukan._daftarKombo || [];
        if (!q) { tutupSaran(); return; }
        var cocok = daftar.filter(function (o) {
          return o.label.toLowerCase().indexOf(q) >= 0;
        }).slice(0, 8);
        if (!cocok.length) {
          kotak.innerHTML = '<div class="kombo__kosong">Tak ada yang cocok</div>';
          kotak.hidden = false;
          return;
        }
        kotak.innerHTML = cocok.map(function (o) {
          return '<div class="kombo__opsi" data-value="' + esc(o.value) +
            '" data-label="' + esc(o.label) + '">' + esc(o.label) + "</div>";
        }).join("");
        kotak.hidden = false;
      });

      // Enter memilih sarannya yang PERTAMA — tanpa ini orang yang mengetik
      // di ponsel harus berpindah tangan ke layar sentuh hanya untuk
      // menutup papan ketiknya dulu, baru bisa menyentuh satu baris.
      masukan.addEventListener("keydown", function (e) {
        if (e.key !== "Enter") { return; }
        var pertama = kotak.querySelector(".kombo__opsi");
        if (kotak.hidden || !pertama) { return; }
        e.preventDefault();
        masukan.value = pertama.dataset.label;
        simpanan.value = pertama.dataset.value;
        tutupSaran();
      });

      // `mousedown`, bukan `click`: tanpa ini `blur` di bawah menutup
      // kotaknya SEBELUM pilihannya sempat terbaca.
      kotak.addEventListener("mousedown", function (e) {
        var opsi = e.target.closest(".kombo__opsi");
        if (!opsi) { return; }
        masukan.value = opsi.dataset.label;
        simpanan.value = opsi.dataset.value;
        tutupSaran();
      });

      masukan.addEventListener("blur", function () {
        setTimeout(function () {
          tutupSaran();
          // Tulisan yang tak cocok satu pilihan pun BUKAN pilihan —
          // dikosongkan lagi supaya borangnya tak terlihat terisi padahal
          // belum ada yang benar-benar terpilih.
          if (!simpanan.value) { masukan.value = ""; }
        }, 150);
      });
    }

    /* Daftar centang: satu kotak per pilihan, nilainya dikumpulkan ke kolom
       tersembunyi. Dipisah dari `muatPilihan` karena bentuknya lain sejak
       akarnya — bukan satu <select> yang isinya ditukar, melainkan sekumpulan
       kotak yang masing-masing punya keadaan sendiri yang harus BERTAHAN
       melewati pemuatan ulang. */
    function muatBanyak(f, segar) {
      var sumber = f.source;
      if((mulaiSosoh || tambahSosoh) && f.name==="silo") sumber += "?rincian=true";
      // Detail perintah sudah menentukan barangnya; jangan memuat pilihan
      // milik truk lain atau bergantung pada batas halaman daftar.
      if (sumber === "/api/actions/item-perintah-ubah" && kunciMedan(f)) {
        sumber += "?pilihan=" + encodeURIComponent(kunciMedan(f));
      }
      if (f.induk) {
        var nilaiInduk = nilaiMedan(f.induk);
        if (!nilaiInduk) { return; }
        sumber += (sumber.indexOf("?") >= 0 ? "&" : "?") + "induk=" +
          encodeURIComponent(nilaiInduk);
      }
      var borangBanyak = lembar.querySelector(".lembar__isi");
      var indukTs=f.induk?nilaiMedan(f.induk):null,nomorDaftarTs=tambahSosoh?++nomorOpsiTs:0;
      ambil(sumber).then(function (daftar) {
        if (!daftar || (mulaiBahan && lembar.querySelector(".lembar__isi") !== borangBanyak)) { return; }
        if(tambahSosoh && (nomorDaftarTs!==nomorOpsiTs||lembar.querySelector(".lembar__isi")!==borangBanyak||(f.induk && nilaiMedan(f.induk)!==indukTs)))return;
        var wadah = $("b_" + f.name);
        var simpanan = lembar.querySelector('[data-name="' + f.name + '"][data-banyak]');
        if (!wadah || !simpanan) { return; }

        function sinkron() {
          var nilai = [], teks = [];
          Array.prototype.forEach.call(
            wadah.querySelectorAll('input[type="checkbox"]'), function (cb) {
              if (cb.checked) { nilai.push(cb.value); teks.push(cb.dataset.teks || cb.value); }
            });
          simpanan.value = nilai.join(",");
          simpanan.dataset.teks = teks.join(" · ");
          if (mulaiBahan) { bersihkanSalah(lembar);perbaruiMulai(); }
          if(tambahSosoh){bersihkanSalah(lembar);perbaruiTs();}
        }

        if ((mulaiBahan || tambahSosoh) && segar) {
          // Centang konflik tetap terlihat supaya operator dapat membacanya,
          // lalu melepas sendiri. Jangan diam-diam memulai sebagian sumber.
          wadah.querySelectorAll("input:checked").forEach(function (cb) {
            if (!daftar.some(function (o) { return o.value === cb.value; })) daftar.push({value:cb.value,label:cb.dataset.teks,rincian:{nama:"Silo " + cb.value,bobot:"Tidak lagi siap",pemilik:"Periksa proses terbaru",pesanan:[],asal:[],jumlah_sumber:null}});
          });
        }
        if (!daftar.length) {
          /* Sama seperti daftar jatuh yang kosong: dikatakan SEKARANG, bukan
             sesudah orang menekan Simpan dan ditolak. */
          wadah.innerHTML = '<p class="bantu" id="kosong_' + esc(f.name) + '">' +
            esc(f.kosong || "Belum ada pilihan. Aksi ini belum bisa dikerjakan sekarang.") +
            "</p>";
          simpanan.value = "";
          var tbl = $("simpan");
          if (tbl && !f.optional) { tbl.disabled = true; tbl.textContent = "Belum bisa disimpan"; }
          return;
        }

        /* Yang sudah tercentang orangnya bertahan; daftar yang disegarkan
           sambil menghapus centangnya lebih merugikan daripada daftar basi. */
        var sudah = String(simpanan.value || "").split(",").filter(Boolean);
        /* Kartu yang membuka lembar ini sudah menyebut satu benda — ia
           dicentang di awal, sekali, dan boleh dilepas kembali. */
        if (!segar && f.name === namaKunci && terkunci && sudah.indexOf(terkunci) < 0) {
          sudah.push(terkunci);
        }
        /* Pulih dari layar konfirmasi: KODE-nya, bukan tulisannya — tulisan
           pilihan boleh memuat "·" sendiri ("Silo A · 10.000 kg"), dan
           memecahnya dengan pemisah yang sama membuang separuh pilihan. */
        var pulih = (simpanan.dataset.pulih || "").split(",").filter(Boolean);
        delete simpanan.dataset.pulih;

        var fokusBanyak = (mulaiBahan || tambahSosoh) && wadah.contains(document.activeElement) ? document.activeElement.value : null;
        wadah.innerHTML = daftar.map(function (o) {
          var c = sudah.indexOf(o.value) >= 0 || pulih.indexOf(o.value) >= 0;
          var rincian = mulaiBahan && o.rincian;
          var teksKartu = tambahSosoh ? kartuTs(o) : rincian ? '<span class="mg-name"><strong>' + esc(rincian.nama) + '</strong><strong>' + esc(rincian.bobot) + '</strong></span><span class="mg-owner">' + esc(rincian.pemilik) + (rincian.pesanan.length ? ' · ' + esc(rincian.pesanan.join(" · ")) : '') + '</span>' + '<small>' + (rincian.jumlah_sumber === null ? '' : rincian.jumlah_sumber + (mulaiSosoh ? ' catatan asal · ' : ' sumber · ')) + esc(mulaiSosoh && rincian.komposisi ? rincian.komposisi.map(function(k){return k.jenis+' '+k.bobot;}).join(' + ') : rincian.asal.join(" + ")) + '</small>' : esc(o.label);
          return '<label class="centang"><input type="checkbox" value="' + esc(o.value) +
            '" data-teks="' + esc(o.label) + '"' + (c ? " checked" : "") + ">" +
            (tambahSosoh ? '<span class="ts-main">' : mulaiBahan ? '<span class="mg-main">' : '<span>') + teksKartu + "</span></label>";
        }).join("");
        Array.prototype.forEach.call(
          wadah.querySelectorAll('input[type="checkbox"]'), function (cb) {
            cb.addEventListener("change", sinkron);
          });
        /* Disetel SESUDAH kotaknya digambar: pilihan yang HILANG dari daftar
           (silonya baru saja diambil proses lain) tak boleh tetap terkirim
           hanya karena ia masih tercatat di kolom tersembunyi. */
        sinkron();
        if (fokusBanyak !== null) wadah.querySelectorAll("input").forEach(function (cb) { if (cb.value === fokusBanyak) cb.focus({preventScroll:true}); });
        var lamaNota = $("kosong_" + f.name);
        if (lamaNota) { lamaNota.remove(); }
        var tbl2 = $("simpan");
        if (tbl2 && tbl2.disabled) { tbl2.disabled = false; tbl2.textContent = labelSimpan; }
      }).catch(function () {
        if (!(mulaiBahan || tambahSosoh) || lembar.querySelector(".lembar__isi") !== borangBanyak) return;
        var kotak = $("b_" + f.name);
        if (kotak && !kotak.querySelector("input")) kotak.textContent = "Pilihan silo belum dapat dimuat. Periksa koneksi dan buka kembali formulir.";
      });
    }

    /* ── Daftar pilihan dimuat ULANG, bukan sekali ──
       Tiket timbang yang baru dibuat di Pos Timbang tak muncul di lembar yang
       sudah telanjur terbuka. Operator gudang membuka "Gabah masuk", menunggu
       truknya ditimbang, lalu tak menemukan tiketnya — dan satu-satunya jalan
       keluar yang ia temukan sendiri adalah menutup aplikasinya.

       `segar` = pemuatan ULANG, bukan yang pertama. Bedanya penting: pilihan
       yang sudah dijatuhkan orangnya harus bertahan, dan baris terkunci tak
       perlu dihitung ulang karena bendanya memang tak berubah. */
    /* Satu baris pasangan. Dipakai saat lembar digambar DAN saat tombol
     "+ Tambah item" ditekan — dua penulis untuk satu bentuk akan berbeda
     atributnya pada perubahan berikutnya, dan yang berbeda diam-diam adalah
     `data-wajib`. */
  function barisBarang(f, pertama) {
    var w = pertama ? ' data-wajib="1"' : "";
    return '<div class="ulang__baris">' +
      '<div class="ulang__pilihan"><select class="fld" aria-label="' + esc(f.label) + '" data-p="' + esc(f.name) + '" data-p-jenis="pilih"' +
      w + ' data-label="' + esc(f.label) + '">' +
      '<option value="">memuat…</option></select>' +
      '<p class="ulang__nama-lengkap" aria-hidden="true">Pilih barang</p></div>' +
      '<label class="ulang__jumlah"><input class="fld" data-p="' + esc(f.name) + '" data-p-jenis="angka"' +
      w + ' data-label="' + esc(f.label_angka || "Jumlah") + '"' +
      ' type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*"' +
      ' autocomplete="off" enterkeyhint="next" placeholder="' +
      esc(f.label_angka || "Jumlah") + '"><span class="ulang__satuan">karung / kg</span></label>' +
      '<button type="button" class="ulang__buang" data-buang="1"' +
      ' aria-label="Buang baris ini" title="Buang baris ini">×</button>' +
      "</div>";
  }

  /* Mengumpulkan baris-baris pasangan jadi daftar {pilih, jumlah}.
     Baris yang KOSONG SELURUHNYA dibuang; baris yang terisi separuh
     DIBIARKAN LEWAT — server yang menolaknya, dengan kalimat yang menyebut
     barang mana. Membuangnya diam-diam di sini membuat orang menekan Simpan
     lalu melihat perintahnya kurang satu barang tanpa tahu sebabnya. */
  function kumpulkanPasangan(lembar) {
    var hasil = {};
    Array.prototype.forEach.call(
      lembar.querySelectorAll(".ulang--pasangan[data-ulang-untuk]"),
      function (wadah) {
        var nama = wadah.dataset.ulangUntuk;
        var daftar = [];
        Array.prototype.forEach.call(wadah.querySelectorAll(".ulang__baris"),
          function (br) {
            var sel = br.querySelector('[data-p-jenis="pilih"]');
            var ang = br.querySelector('[data-p-jenis="angka"]');
            var pilih = sel ? String(sel.value || "").trim() : "";
            var jml = ang ? String(ang.value || "").trim() : "";
            if (!pilih && !jml) { return; }
            daftar.push({
              pilih: pilih,
              jumlah: jml === "" ? null : parseFloat(jml.replace(",", ".")),
              teks: (sel && sel.selectedIndex >= 0)
                ? sel.options[sel.selectedIndex].text : pilih
            });
          });
        hasil[nama] = daftar;
      });
    return hasil;
  }

  function muatPilihan(segar, hanya) {
      terakhirMuat = Date.now();
      (a.fields || []).forEach(function (f) {
      if (f.type === "remote_banyak") {
        if (!hanya || f.name === hanya) { muatBanyak(f, segar); }
        return;
      }
      if (f.type === "kombo") {
        if (!hanya || f.name === hanya) { pasangKombo(f); }
        return;
      }
      /* Wadah berpasangan: daftarnya dimuat SEKALI per induk lalu dipasang ke
         setiap baris yang sudah ada. Baris yang ditambahkan sesudah ini
         menyalin <option>-nya dari baris pertama, jadi tak ada permintaan
         kedua.

         `induk` (mis. "barang" bergantung "jasa" di Pengambilan barang
         jasa) BARU didukung di sini 11 Oktober 2026 — sebelumnya daftarnya
         dimuat SEKALI saja saat lembar dibuka, induknya BELUM tentu terisi,
         dan tak pernah dimuat ulang saat induknya berubah: medan barang
         terbaca "(belum ada)" selamanya, apa pun pesanan yang dipilih. */
      if (f.type === "ulang_barang") {
        if (hanya && f.name !== hanya) { return; }
        var sumberBarang = f.source;
        if (f.induk) {
          var indukBarang = nilaiMedan(f.induk);
          if (!indukBarang) { return; }
          sumberBarang += (sumberBarang.indexOf("?") >= 0 ? "&" : "?") +
            "induk=" + encodeURIComponent(indukBarang);
        }
        ambil(sumberBarang).then(function (daftar) {
          if (!daftar) return;
          var wadah = lembar.querySelector(
            '.ulang--pasangan[data-ulang-untuk="' + f.name + '"]');
          if (!wadah) return;
          var opsi = '<option value="">' +
            (daftar.length ? "— pilih —" : "(belum ada)") + "</option>" +
            daftar.map(function (o) {
              return '<option value="' + esc(o.value) + '">' + esc(o.label) +
                "</option>";
            }).join("");
          Array.prototype.forEach.call(wadah.querySelectorAll("select"),
            function (sel) {
              var dipilih = sel.value;
              sel.innerHTML = opsi;
              if (dipilih) { sel.value = dipilih; }
              perbaruiNamaBarang(sel);
              sel.onchange = function () { perbaruiNamaBarang(sel); };
            });
          var lamaNota = $("kosong_" + f.name);
          if (!daftar.length) {
            if (lamaNota) { return; }
            var nota = document.createElement("p");
            nota.className = "bantu";
            nota.id = "kosong_" + f.name;
            nota.style.marginTop = "6px";
            nota.textContent = f.kosong || ("Belum ada " +
              (f.label || "pilihan").toLowerCase() + ".");
            wadah.insertAdjacentElement("afterend", nota);
          } else if (lamaNota) {
            // Daftarnya TADI kosong (atau induknya baru saja berganti) dan
            // sekarang berisi — nota lama dicabut, sama seperti medan
            // `remote` biasa.
            lamaNota.remove();
          }
        });
        return;
      }
      if (f.type !== "remote") return;
      if (hanya && f.name !== hanya) { return; }
      /* Daftar yang bergantung medan lain tak dimuat sebelum induknya dipilih:
         jawabannya memang belum ada, dan daftar yang dimuat tanpa induk akan
         menawarkan SELURUH pilihan yang mungkin — persis kesalahan yang medan
         ini menggantikan. */
      var sumber = f.source;
      if (lingkupKemas && f.name === "sumber") {
        sumber += "?jenis=" + encodeURIComponent(lingkupKemas[1]) + "&pemilik=" + encodeURIComponent(lingkupKemas[2]);
      }
      // Detail perintah sudah menentukan barangnya; jangan memuat pilihan
      // milik truk lain atau bergantung pada batas halaman daftar.
      if (sumber === "/api/actions/item-perintah-ubah" && kunciMedan(f)) {
        sumber += "?pilihan=" + encodeURIComponent(kunciMedan(f));
      }
      if (f.induk) {
        var nilaiInduk = nilaiMedan(f.induk);
        if (!nilaiInduk) { return; }
        sumber += (sumber.indexOf("?") >= 0 ? "&" : "?") + "induk=" +
          encodeURIComponent(nilaiInduk);
      }
      var indukDiminta = f.induk ? nilaiMedan(f.induk) : null;
      var borangDiminta = lembar.querySelector(".lembar__isi");
      ambil(sumber).then(function (daftar) {
        if (!daftar || lembar.querySelector(".lembar__isi") !== borangDiminta ||
            (f.induk && nilaiMedan(f.induk) !== indukDiminta)) return;
        if (kunciMedan(f)) {
          if (segar) { return; }
          /* Nama bendanya baru diketahui sesudah daftarnya datang. Kalau
             ternyata tak ada yang cocok, barisnya sudah basi — kuncinya
             dilepas supaya orang bisa memilih sendiri, bukan mengirim nilai
             yang akan ditolak. */
          var cocok = null;
          daftar.forEach(function (o) { if (o.value === kunciMedan(f)) { cocok = o; } });
          var kotak = $("t_" + f.name);
          if (!kotak) { return; }
          if (cocok) {
            kotak.textContent = cocok.label;
            if (cocok.berat_kg != null) { kotak.dataset.beratKg = String(cocok.berat_kg); }
            perbaruiMaksimalKemas();
            perbaruiPratinjau();
            perbaruiRingkasanHasil();
            perbaruiRingkasanGiling();
        perbaruiSg();
        perbaruiBs();
        perbaruiBsp();
        perbaruiTg();
        perbaruiTs();
            perbaruiRingkasanAir();
            perbaruiMasukkan();
            perbaruiBroken();
            perbaruiBeras();
            perbaruiMenir();perbaruiKemas();
            return;
          }
          // Detail tetap menunjuk proses asal meskipun proses itu baru saja
          // selesai. Konteks baca menampilkan keadaannya; POST tetap memagari.
          if (formKhusus && f.name === formKhusus.proses) {
            perbaruiRingkasanHasil();
            perbaruiRingkasanGiling();
        perbaruiSg();
        perbaruiBs();
        perbaruiBsp();
        perbaruiTg();
        perbaruiTs();
            perbaruiRingkasanAir();
            return;
          }
          if ((f.name === "sumber_stok" && sumberBaris) ||
              (f.name === "baris" && (id === "ubah_item_perintah" || id === "hapus_item_perintah")) ||
              (f.name === "perintah" && tagPerintah && tagPerintah.dataset.perintahDetail)) {
            kotak.textContent = f.name !== "sumber_stok"
              ? "Perintah atau muatan berubah. Tutup formulir, muat ulang detail, dan periksa kembali."
              : "Stok pada baris ini sudah tidak tersedia. Tutup dan muat ulang halaman.";
            var tombolSimpan = $("simpan");
            if (tombolSimpan) { tombolSimpan.disabled = true; }
            return;
          }
          kotak.outerHTML =
            '<span class="lbl">' + esc(f.label) + "</span>" +
            '<select class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
            '" data-wajib="1" data-label="' + esc(f.label) + '">' +
            '<option value="">— pilih —</option>' + daftar.map(function (o) {
              return '<option value="' + esc(o.value) + '"' +
              (o.disabled ? ' disabled' : '') +
                (o.berat_kg != null ? ' data-berat-kg="' + esc(o.berat_kg) + '"' : "") +
                '>' + esc(o.label) + "</option>";
            }).join("") + "</select>";
          var sembunyi = lembar.querySelector('input[type="hidden"][data-name="' +
            f.name + '"]');
          if (sembunyi) { sembunyi.remove(); }
          return;
        }
        var s = $("f_" + f.name);
        if (!s) { return; }
        /* Apa yang sudah dipilih orangnya bertahan melewati pemuatan ulang.
           Daftar yang disegarkan sambil menghapus pilihan yang sedang dibuat
           lebih merugikan daripada daftar yang basi. */
        var dipilih = s.value;
        s.innerHTML = '<option value="">' + (daftar.length ? "— pilih —" : "(belum ada)") +
          "</option>" + daftar.map(function (o) {
            return '<option value="' + esc(o.value) + '"' +
              (o.disabled ? ' disabled' : '') +
              (o.berat_kg != null ? ' data-berat-kg="' + esc(o.berat_kg) + '"' : "") +
              '>' + esc(o.label) + "</option>";
          }).join("");
        if (dipilih) { s.value = dipilih; }
        if(masukkanSilo&&f.name==='tumpukan'&&!dipilih&&sumberAwalMasukkan){var bawaanMi=daftar.find(function(o){return o.value===sumberAwalMasukkan||o.value.split(':')[0]===sumberAwalMasukkan;});if(bawaanMi){s.value=bawaanMi.value;s.dispatchEvent(new Event('change',{bubbles:true}));sumberAwalMasukkan='';}}
        if ((selesaiGiling || selesaiSosoh) && f.name==='kode_proses' && semula && semula['kode:kode_proses']) s.value=semula['kode:kode_proses'];
        /* Tiket dari tautan aplikasi Timbangan dibawa sampai ke lembar ini.
           Pilihan tetap menunggu transaksi barang keluar dipilih lebih dulu;
           setelah daftar tiket terfilter menurut pembeli, baru pilih id yang
           dibawa URL bila tiket itu memang ada di daftar yang sah. */
        var tagAksi = document.querySelector('script[data-tiket]');
        var tiketDibawa = tagAksi && tagAksi.dataset.tiket;
        if (f.name === "tiket" && tiketDibawa && !dipilih) {
          var cocokTiket = Array.prototype.some.call(s.options, function (o) {
            return o.value === tiketDibawa;
          });
          if (cocokTiket) { s.value = tiketDibawa; }
        }
        /* Daftar bergantung yang isinya TEPAT SATU sudah menjawab dirinya
           sendiri: proses yang memakai satu silo tak menyisakan pilihan apa
           pun untuk dibuat. Menyuruh orang memilih satu-satunya kemungkinan
           adalah langkah yang hanya bisa salah ditekan. */
        else if ((f.induk || f.auto_satu) && daftar.length === 1) {
          s.value = daftar[0].value;
        }
        // Kalau daftarnya kosong, aksi ini memang belum bisa dikerjakan.
        // Katakan sekarang — bukan setelah orang menekan Simpan dan ditolak.
        // Pilihan yang boleh dikosongkan tak boleh menghentikan aksi ketika
        // daftarnya kebetulan kosong — belum ada merk bukan alasan bekatul
        // tidak bisa dicatat.
        if (!daftar.length && !f.optional) {
          s.disabled = true;
          if ($("kosong_" + f.name)) { return; }   // jangan menumpuk saat disegarkan
          var nota = document.createElement("p");
          nota.className = "bantu";
          nota.id = "kosong_" + f.name;
          nota.style.marginTop = "6px";
          /* Kalimat bawaan menebak dari NAMA field, dan tebakan itu bisa
             keliru berat: daftar "Mesin pengering" yang kosong berarti tak
             ada gabah yang menunggu dinyalakan — BUKAN bahwa pabrik ini tak
             punya mesin pengering. Server yang tahu artinya, jadi server yang
             menyediakan kalimatnya lewat `kosong`. */
          nota.textContent = f.kosong || ("Belum ada " +
            (f.label || "pilihan").toLowerCase() +
            ". Aksi ini belum bisa dikerjakan sekarang.");
          s.insertAdjacentElement("afterend", nota);
          var tbl = $("simpan");
          if (tbl) { tbl.disabled = true; tbl.textContent = "Belum bisa disimpan"; }
        } else if (daftar.length) {
          /* Daftarnya TADI kosong dan sekarang tidak. Lembar yang sudah
             terlanjur berkata "belum bisa disimpan" harus mencabut kembali
             ucapannya — kalau tidak, tiket yang baru datang terlihat di
             daftar tetapi tombol Simpan-nya tetap mati. */
          s.disabled = false;
          var lamaNota = $("kosong_" + f.name);
          if (lamaNota) { lamaNota.remove(); }
          var tbl2 = $("simpan");
          if (tbl2 && tbl2.disabled) { tbl2.disabled = false; tbl2.textContent = labelSimpan; }
        }
        perbaruiMaksimalKemas();
        perbaruiPratinjau();
        perbaruiKonteksMuat();
        perbaruiRingkasanHasil(true);
        perbaruiRingkasanGiling();
        perbaruiSg();
        perbaruiBs();
        perbaruiBsp();
        perbaruiTg();
        perbaruiTs();
        perbaruiRingkasanAir();
        perbaruiMasukkan();
        perbaruiBroken();
        perbaruiBeras();
        perbaruiMenir();perbaruiKemas();
        ambilAcuanJeda();
        aturWaktuJeda();
      }).catch(function () {});
      });
    }
    muatPilihan(false);
    ["sumber", "kemasan"].forEach(function (nama) {
      var s = $("f_" + nama);
      if (s) { s.addEventListener("change", perbaruiMaksimalKemas); }
    });
    perbaruiMaksimalKemas();
    /* Induk berubah → daftar anaknya ikut berubah. Tanpa ini medan bergantung
       cuma bekerja untuk proses yang dipilih PERTAMA, dan orang yang berubah
       pikiran memilih silo milik proses yang lain. */
    (a.fields || []).forEach(function (f) {
      if ((f.type !== "remote" && f.type !== "remote_banyak" &&
           f.type !== "ulang_barang") || !f.induk) { return; }
      var pi = $("f_" + f.induk);
      if (!pi) { return; }
      pi.addEventListener("change", function () {
        var anak = $("f_" + f.name);
        if (anak) {
          anak.innerHTML = '<option value="">memuat…</option>';
          anak.disabled = false;
        }
        var banyak = f.type === "remote_banyak" ? $("b_" + f.name) : null;
        if (banyak) { banyak.innerHTML = '<p class="bantu">memuat…</p>'; }
        if (f.type === "ulang_barang") {
          var wadahBarang = lembar.querySelector(
            '.ulang--pasangan[data-ulang-untuk="' + f.name + '"]');
          if (wadahBarang) {
            Array.prototype.forEach.call(wadahBarang.querySelectorAll("select"),
              function (sel) { sel.innerHTML = '<option value="">memuat…</option>'; });
          }
        }
        var lamaNota = $("kosong_" + f.name);
        if (lamaNota) { lamaNota.remove(); }
        var tbl = $("simpan");
        if (tbl && tbl.disabled) { tbl.disabled = false; tbl.textContent = "Simpan"; }
        muatPilihan(false, f.name);
      });
    });
    /* Siapa yang menyegarkan: pendengar di lingkup modul (di bawah), bukan
       pendengar baru tiap lembar dibuka — yang begitu menumpuk satu tiap
       pembukaan. */
    segarkanPilihan = function () { muatPilihan(true); };

    $("tutup").onclick = a.id === 'tutup_silo_giling' && kembaliSelesaiGiling ? function(){bukaAksi('selesai_giling',kembaliSelesaiGiling.draft);} : a.id === 'selesai_penyosohan' && kembaliSelesaiSosoh ? function(){bukaAksi('akhiri_penyosohan',kembaliSelesaiSosoh.draft);} : tutupLembar;

    // Nilai yang TERBACA orang, bukan yang dikirim ke server. Untuk pilihan,
    // yang berarti adalah tulisan di layarnya ("Pengering 1"), bukan angka id
    // di baliknya — dan konfirmasi yang menyebut id tidak mengonfirmasi apa
    // pun.
    function terbaca() {
      var v = {};
      Array.prototype.forEach.call(lembar.querySelectorAll("[data-name]"), function (el) {
        if (el.tagName === "SELECT" && el.selectedIndex >= 0) {
          v[el.dataset.name] = el.options[el.selectedIndex].text;
          return;
        }
        /* Isian terkunci menyimpan KODE-nya di kolom tersembunyi; yang harus
           dibaca orang adalah nama yang tertulis di sebelahnya. Kalimat
           konfirmasi yang menyebut "silo:2" alih-alih "Silo B" menuntut
           orangnya menerjemahkan sendiri — persis saat ia sedang diminta
           memastikan. */
        if (el.dataset.ulang) {
          /* Digabung, bukan ditimpa. Tanpa ini konfirmasi cuma menyebut
             titik TERAKHIR — dan yang diminta orangnya periksa justru
             seluruh titik yang baru ia ketik. */
          if (!String(el.value).trim()) return;
          v[el.dataset.name] = (v[el.dataset.name] ? v[el.dataset.name] + " · " : "")
            + el.value + "%";
          return;
        }
        /* Daftar centang: yang dibaca orang TULISANNYA. Kalimat konfirmasi
           yang berbunyi "A,B" menuntut ia menerjemahkan sendiri — persis saat
           ia sedang diminta memastikan. */
        if (el.dataset.banyak) {
          v[el.dataset.name] = el.dataset.teks || el.value;
          /* Kodenya dititipkan di kunci terpisah, untuk MEMULIHKAN centangnya
             saat orang menekan "Kembali" dari layar konfirmasi. Dulu
             pemulihannya mencocokkan tulisan, dan tulisan itu sendiri memuat
             "·" ("Silo A · 10.000 kg") — pemisah yang sama dengan yang
             menggabungkan beberapa pilihan. Hasilnya: yang kedua dan
             seterusnya lenyap diam-diam, dan orang yang cuma ingin memeriksa
             sekali lagi kehilangan separuh pilihannya. Ditemukan di peramban,
             bukan di uji.
             Kuncinya bertanda titik dua supaya tak pernah cocok dengan lubang
             {nama} di kalimat konfirmasi. */
          v["kode:" + el.dataset.name] = el.value;
          return;
        }
        /* Kombo: yang terbaca orang tulisan di kotaknya ("Bu Sri Uji"),
           bukan id tersembunyi di sebelahnya. */
        if (el.dataset.cari) {
          var tampil = $("x_" + el.dataset.name);
          v[el.dataset.name] = tampil ? tampil.value : "";
          return;
        }
        var kotak = el.type === "hidden" ? $("t_" + el.dataset.name) : null;
        v[el.dataset.name] = kotak ? kotak.textContent.trim() : el.value;
      });
      /* Baris pasangan: yang dibaca orang TULISAN barangnya, bukan idnya.
         Konfirmasi yang berbunyi "12|3 × 100" tak mengonfirmasi apa pun. */
      var pasanganT = kumpulkanPasangan(lembar);
      Object.keys(pasanganT).forEach(function (nama) {
        var baris = pasanganT[nama];
        if (!baris.length) { return; }
        v[nama] = baris.map(function (b) {
          return b.teks + " × " + (b.jumlah === null ? "?" : b.jumlah);
        }).join(" · ");
      });
      return v;
    }

    // Konfirmasi DIISI dengan jawaban orangnya sendiri.
    //
    // "Yakin?" tidak menanyakan apa pun — ia hanya melatih orang menekan Ya.
    // Yang berguna adalah mengulang angka yang baru saja ia ketik, supaya ia
    // membandingkannya dengan panel mesin di depannya. Karena itu teksnya
    // datang dari server dengan lubang {nama_field}, dan diisi di sini.
    function isikan(teks, v) {
      return String(teks).replace(/\{(\w+)\}/g, function (m, k) {
        return (v[k] === undefined || v[k] === "") ? m : v[k];
      });
    }

    // Isi yang DIKIRIM — dibaca sekali, sebelum layar apa pun diganti.
    function muatan() {
      var isi = {};
      Array.prototype.forEach.call(lembar.querySelectorAll("[data-name]"), function (el) {
        if (el.dataset.pratinjauNonaktif === "1") return;
        var v = el.value;
        /* Dikirim sebagai DAFTAR, bahkan bila cuma satu yang tercentang:
           server yang menerima kadang daftar kadang teks harus menebak, dan
           menebak sekali salah berarti giling atas silo yang tak dipilih. */
        if (el.dataset.banyak) {
          isi[el.dataset.name] = String(v || "").split(",").filter(Boolean);
          return;
        }
        if (el.dataset.angka || el.dataset.ulang) v = (v === "" ? null : parseFloat(String(v).replace(",", ".")));
        /* Medan berulang dikirim sebagai DAFTAR, dan yang kosong dibuang di
           sini — bukan di server. Kotak yang ditambahkan lalu ditinggalkan
           kosong bukan "titik bernilai nol"; ia titik yang tak pernah
           diukur, dan nol akan menyeret rata-ratanya turun. */
        if (el.dataset.ulang) {
          if (!isi[el.dataset.name]) isi[el.dataset.name] = [];
          if (v !== null && v !== "") isi[el.dataset.name].push(v);
          return;
        }
        isi[el.dataset.name] = v;
      });
      /* Baris pasangan dikumpulkan TERPISAH — anaknya tak ber-`data-name`,
         jadi gelung di atas tak pernah melihatnya. Dikirim sebagai daftar
         {pilih, jumlah}: satu transaksi barang keluar memuat beberapa macam
         barang, dan urutan pasangannya tak boleh bisa tergeser. */
      var pasangan = kumpulkanPasangan(lembar);
      Object.keys(pasangan).forEach(function (nama) {
        isi[nama] = pasangan[nama].map(function (b) {
          return { pilih: b.pilih, jumlah: b.jumlah };
        });
      });
      if(masukkanSilo) isi.kunci_kiriman=kunciMasukkan;
      return isi;
    }

    // Konfirmasi menyembunyikan formulir asli, bukan membongkarnya. Semua
    // baris tambahan, koma desimal, dan pilihan asinkron tetap milik operator.
    var borangAsli = null;
    function kembaliKeBorang() {
      if (!borangAsli) return;
      if (selesaiGiling) risikoSg=false;
      if (selesaiSosoh) {risikoSs=false;perbaruiSs();}
      if (bebaskanGiling) {risikoBs=false;perbaruiBs();}
      if (bebaskanSosoh) {risikoBsp=false;perbaruiBsp();}
      var konfirmasi = lembar.querySelector(".lembar__konfirmasi");
      if (konfirmasi) konfirmasi.remove();
      borangAsli.hidden = false;
      borangAsli = null;
      lembar.setAttribute("aria-label", judul);
      $("simpan").focus();
    }

    async function simpan(isi, v, tbl) {
      if ((selesaiSosoh && (lembar._menyimpan || risikoSs)) || (selesaiGiling && (lembar._menyimpan || risikoSg)) || (bebaskanGiling && (lembar._menyimpan || risikoBs)) || (bebaskanSosoh && (lembar._menyimpan || risikoBsp)) || (tambahSosoh && (lembar._menyimpan || risikoTs))) return;
      if(masukkanBroken && (lembar._menyimpan || risikoBroken)) return;
      if(masukkanBeras && (lembar._menyimpan || risikoBeras)) return;
      if(kemasBeras && (lembar._menyimpan || risikoKemas)) return;
      if(masukkanMenir && (lembar._menyimpan || risikoMenir)) return;
      var sebelumSelesai = dataSelesai;
      lembar._menyimpan = true;
      var grup = lembar.querySelector(".grup");
      if (grup) grup.inert = true;
      var kembali = $("kembali");
      if (kembali) kembali.disabled = true;
      if (tbl) { tbl.disabled = true; tbl.textContent = "Menyimpan…"; }
      try {
        var hasil = await kirim(a.post, isi);
        if (formKhusus && (!hasil || hasil.ok !== true)) throw new TypeError("Hasil simpan belum terkonfirmasi");
        // Tombolnya sendiri yang menjawab: memuat → tercentang, di tempat.
        if (tbl) { tbl.textContent = "✓ Tersimpan"; }
        await new Promise(function (r) { setTimeout(r, 260); });
        lembar._menyimpan = false;
        // Detail sudah selesai dikerjakan. Kembali ke daftar hanya setelah
        // server memastikan verifikasi berhasil, bukan saat tombol ditekan.
        if (a.id === "verifikasi_keluar" && /^\/barang-keluar\/[1-9]\d*\/?$/.test(location.pathname)) {
          lembar._berubah = false;
          lembar._riwayat = false;
          location.replace("/barang-keluar");
          return;
        }
        // Perintah baru langsung dikelola di detailnya. Jangan memanggil
        // history.back() dari penutupan modal bersamaan dengan navigasi ini.
        if (a.id === "perintah_keluar" && /^\/barang-keluar\/[1-9]\d*$/.test(hasil.tujuan || "")) {
          lembar._berubah = false;
          lembar._riwayat = false;
          location.replace(hasil.tujuan);
          return;
        }
        // Tutup modal menghabiskan satu entri history secara asinkron.
        // Tunggu Back milik modal dahulu sebelum mengganti alamat fase;
        // tanpa ini, Back dapat menimpa URL pendinginan yang baru dipasang.
        var balikSelesai = (selesaiKering || pindahSilo || mulaiBahan || selesaiGiling || selesaiSosoh || (a.id==='tutup_silo_giling' && kembaliSelesaiGiling)) && lembar._riwayat ? new Promise(function (resolve) {
          var selesaiBalik = function () { clearTimeout(batasBalik);window.removeEventListener("popstate",selesaiBalik);resolve(); };
          var batasBalik = setTimeout(selesaiBalik,1000);
          window.addEventListener("popstate",selesaiBalik,{once:true});
        }) : null;
        tutupLembar(true);
        if (balikSelesai) await balikSelesai;
        var pesan = /\/undo(?:$|\?)/.test(a.post) ? "Dibatalkan" : (hasil.pesan || "Tersimpan ✓");
        muat();
        /* Kartu yang barusan diselesaikan harus HILANG sekarang juga. Ia
           digambar server, jadi `muat()` — yang cuma memuat ulang daftar
           aksi — tak menyentuhnya sama sekali. Kabarnya ditampilkan sesudah
           isinya ditukar, karena ia ikut tersapu bersama isi lama. */
        function kabarHasil() {
          var peringatan = hasilGiling && hasil.peringatan;
          var utama = peringatan ? pesan.replace("\n" + peringatan, "") : pesan;
          if (kadarAir) {
            var baris = pesan.split("\n");
            peringatan = baris.filter(function (b) { return /^⚠/.test(b); }).map(function (b) { return b.replace(/^⚠️?\s*/, ""); }).join("\n");
            utama = baris.filter(function (b) { return !/^⚠/.test(b); }).join("\n");
          }
          kabar(utama, "ok", !!formKhusus);
          if(kemasBeras&&hasil.rincian_packing){var rp=hasil.rincian_packing,receiptPk=document.createElement('div');receiptPk.className='mi-receipt';receiptPk.innerHTML='<strong>Pengemasan tercatat</strong>'+pasanganMasukkan('Jumlah hasil kemasan',rp.jumlah+' karung')+pasanganMasukkan('Total berat',kgMasukkan(rp.berat))+(rp.setelah?pasanganMasukkan('Sumber',rp.setelah.kode+' · '+rp.setelah.produk)+pasanganMasukkan('Pemilik',rp.setelah.pemilik)+pasanganMasukkan('Sisa hasil belum dikemas',kgMasukkan(rp.setelah.saldo.tersedia))+pasanganMasukkan('Sisa karung tercatat',rp.setelah.karung==null?'Belum tersedia':rp.setelah.karung+' lembar'):'<p>Saldo terbaru belum tersedia; periksa Stok.</p>');$('kabar').appendChild(receiptPk);}
          if(masukkanMenir&&hasil['rincian_'+jenisMn]){var nyataMn=hasil['rincian_'+jenisMn],receiptMn=document.createElement('div');receiptMn.className='mi-receipt';receiptMn.innerHTML='<strong>'+labelMn+' tersimpan</strong>'+pasanganMasukkan('Berat masuk silo',kgMasukkan(nyataMn.kg))+pasanganMasukkan('Silo tujuan',nyataMn.silo)+(nyataMn.setelah?pasanganMasukkan('Pemilik',nyataMn.setelah.pemilik)+pasanganMasukkan('Sisa stok pemilik',kgMasukkan(nyataMn.setelah.saldo_kg)):'<p>Saldo terbaru belum terbaca; periksa Stok sebelum tindakan berikutnya.</p>')+'<details><summary>Catatan pemindahan</summary>'+esc(nyataMn.codes.join(', '))+'</details>';$('kabar').appendChild(receiptMn);}
          if(masukkanBeras&&hasil.rincian_beras){var nyataBr=hasil.rincian_beras,receiptBr=document.createElement('div');receiptBr.className='mi-receipt';receiptBr.innerHTML='<strong>Beras tersimpan</strong>'+pasanganMasukkan('Berat masuk silo',kgMasukkan(nyataBr.kg))+pasanganMasukkan('Silo tujuan',nyataBr.silo)+(nyataBr.karung?pasanganMasukkan('Karung dibongkar',nyataBr.karung+' karung'):'')+(nyataBr.setelah?pasanganMasukkan('Pemilik',nyataBr.setelah.pemilik)+pasanganMasukkan('Sisa sumber terpilih',kgMasukkan(nyataBr.setelah.saldo_kg))+(nyataBr.setelah.karung!=null?pasanganMasukkan('Sisa karung',nyataBr.setelah.karung+' karung'):''):'<p>Saldo terbaru belum terbaca; periksa Stok sebelum tindakan berikutnya.</p>')+'<details><summary>Catatan pemindahan</summary>'+esc(nyataBr.pemindahan.map(function(x){return x.kode;}).join(', '))+'</details>';$('kabar').appendChild(receiptBr);}
          if(masukkanBroken && hasil.rincian_broken){var nyataBk=hasil.rincian_broken,receiptBk=document.createElement('div');receiptBk.className='mi-receipt';receiptBk.innerHTML='<strong>Broken tersimpan</strong>'+pasanganMasukkan('Berat masuk silo',kgMasukkan(nyataBk.kg))+pasanganMasukkan('Silo tujuan',nyataBk.silo)+pasanganMasukkan('Dibongkar dari kemasan',kgMasukkan(nyataBk.dibongkar_kg))+(nyataBk.karung_dibongkar!=null?pasanganMasukkan('Karung utuh dibongkar',nyataBk.karung_dibongkar+' karung'):'')+(nyataBk.kemasan_dibongkar||[]).map(function(j){return pasanganMasukkan('Karung '+kgMasukkan(j.ukuran)+' tetap tersedia',j.saldo_karung+' lembar kosong');}).join('')+(nyataBk.setelah?pasanganMasukkan('Sisa curah',kgMasukkan(nyataBk.setelah.saldo.curah))+pasanganMasukkan('Sisa hasil mesin',kgMasukkan(nyataBk.setelah.saldo.mesin))+pasanganMasukkan('Kemasan tersisa',nyataBk.setelah.saldo.karung+' karung · '+kgMasukkan(nyataBk.setelah.saldo.kemasan))+pasanganMasukkan('Total sisa stok',kgMasukkan(nyataBk.setelah.saldo.total)):'<p>Saldo terbaru belum terbaca; periksa Stok sebelum tindakan berikutnya.</p>')+'<details><summary>Catatan pemindahan</summary>'+esc(nyataBk.kode.join(', '))+'</details>';$('kabar').appendChild(receiptBk);}
          if(masukkanSilo&&hasil.rincian_masukkan){var nyataMi=hasil.rincian_masukkan,catatanMi=document.createElement('div');catatanMi.className='mi-receipt';catatanMi.innerHTML='<strong>Hasil tersimpan · '+esc(nyataMi.kode_pindah)+'</strong>'+pasanganMasukkan('Bentuk sumber',nyataMi.bentuk==='karung'?'Berkarung':nyataMi.bentuk==='curah'?'Curah':'Data lama')+pasanganMasukkan('Berat masuk silo',kgMasukkan(nyataMi.berat_masuk,nyataMi.bobot_final))+(nyataMi.karung_masuk!=null?pasanganMasukkan('Karung masuk',nyataMi.karung_masuk+' karung'):'')+pasanganMasukkan('Silo tujuan',nyataMi.silo)+pasanganMasukkan('Sisa berat sumber',kgMasukkan(nyataMi.sisa_kg,nyataMi.bobot_final))+(nyataMi.sisa_karung!=null?pasanganMasukkan('Sisa karung',nyataMi.sisa_karung+' karung'):'')+(nyataMi.sejawat||[]).map(function(s){return pasanganMasukkan('Sumber '+s.bentuk+' tetap tersedia',kgMasukkan(s.saldo_kg,s.bobot_final));}).join('');$('kabar').appendChild(catatanMi);}
          if(a.id==='selesai_penyosohan' && kembaliSelesaiSosoh){var draftSs=kembaliSelesaiSosoh.draft;bukaAksi('akhiri_penyosohan',draftSs);}
          if(a.id==='tutup_silo_giling' && kembaliSelesaiGiling){var draftSg=kembaliSelesaiGiling.draft;bukaAksi('selesai_giling',draftSg);}
          if(bebaskanGiling) hasilTerkiniBs(isi);
          if(bebaskanSosoh) hasilTerkiniBsp(isi);
          if(tambahSosoh){var linkTs=document.createElement("a");linkTs.className="btn";linkTs.textContent="Lihat penyosohan";var balikTs=new URLSearchParams(location.search).get("kembali_kerja");linkTs.href="/proses-aktif/sosoh/"+encodeURIComponent(isi.kode)+(balikTs?"?kembali_kerja="+encodeURIComponent(balikTs):"");$("kabar").appendChild(linkTs);}
          if(tambahGiling){var lihatTg=document.createElement('a');lihatTg.className='btn';lihatTg.textContent='Lihat penggilingan';var kembaliTg=new URLSearchParams(location.search).get('kembali_kerja');lihatTg.href='/proses-aktif/giling/'+encodeURIComponent(isi.kode_proses)+(kembaliTg?'?kembali_kerja='+encodeURIComponent(kembaliTg):'');$('kabar').appendChild(lihatTg);}
          if(selesaiGiling && dataSg){var linkSg=document.createElement('a');linkSg.className='btn';linkSg.href='/riwayat-giling/'+dataSg.id;linkSg.textContent='Lihat riwayat penggilingan';$('kabar').appendChild(linkSg);}
          if (mulaiBahan && hasil.kode_proses) {
            if (hasil.pemilik) { var pemilikGiling = document.createElement("p");pemilikGiling.textContent = hasil.pemilik + " · " + (hasil.bobot_final ? "Bobot final" : "Bobot belum final");$("kabar").appendChild(pemilikGiling); }
            var lihatGiling = document.createElement("a");lihatGiling.className = "btn";lihatGiling.textContent = mulaiSosoh ? "Lihat penyosohan" : "Lihat penggilingan";
            var konteksGiling = new URLSearchParams(location.search).get("kembali_kerja");
            lihatGiling.href = (mulaiSosoh ? "/proses-aktif/sosoh/" : "/proses-aktif/giling/") + encodeURIComponent(hasil.kode_proses) + (konteksGiling ? "?kembali_kerja=" + encodeURIComponent(konteksGiling) : "");
            $("kabar").appendChild(lihatGiling);
          }
          if (selesaiKering) {
            var lihat = document.createElement("a");lihat.className = "btn";
            lihat.textContent = "Lihat pendinginan";
            var asalKerja = new URLSearchParams(location.search).get("kembali_kerja");
            lihat.href = "/proses-aktif/pendinginan/" + encodeURIComponent(isi.kode_lot) + (asalKerja ? "?kembali_kerja=" + encodeURIComponent(asalKerja) : "");
            $("kabar").appendChild(lihat);
          }
          if (peringatan) {
            $("kabar").insertAdjacentHTML("beforeend", '<div class="kabar__peringatan"><strong>Perlu diperiksa</strong><span>' + esc(peringatan) + '</span></div>');
            clearTimeout($("kabar")._t);
          }
        }
        if (window.PINDAH && PINDAH.segarkan) {
          // Penyegaran alamat fase lama menjalankan pengalihan halaman penuh
          // dan menghilangkan balasan simpan. Sesudah server mengonfirmasi,
          // segarkan alamat pendinginan yang sebenarnya, dengan konteks kembali.
          if (selesaiKering && /^\/proses-aktif\/pengeringan\/[^/]+\/?$/.test(location.pathname)) {
            var faseBaru = new URL(location.href);
            faseBaru.pathname = "/proses-aktif/pendinginan/" + encodeURIComponent(isi.kode_lot);
            history.replaceState(history.state, "", faseBaru.pathname + faseBaru.search + faseBaru.hash);
          }
          if(selesaiSosoh && dataSs && /^\/proses-aktif\/sosoh\//.test(location.pathname)){var tujuanSs=new URL(location.href);tujuanSs.pathname='/riwayat-sosoh/'+dataSs.id;history.replaceState(history.state,'',tujuanSs.pathname+tujuanSs.search+tujuanSs.hash);}
          if(selesaiGiling && dataSg && /^\/proses-aktif\/giling\//.test(location.pathname)){var tujuanSg=new URL(location.href);tujuanSg.pathname='/riwayat-giling/'+dataSg.id;history.replaceState(history.state,'',tujuanSg.pathname+tujuanSg.search+tujuanSg.hash);}
          PINDAH.segarkan(kabarHasil);
        } else {
          kabarHasil();
        }
      } catch (e) {
        lembar._menyimpan = false;
        if (grup) grup.inert = false;
        if (kembali) kembali.disabled = false;
        if (!((selesaiGiling || bebaskanGiling || selesaiSosoh || bebaskanSosoh) && e instanceof TypeError)) kembaliKeBorang();
        if (tbl) { tbl.disabled = false; tbl.textContent = labelSimpan; }
        var pesanGagal = e instanceof TypeError
          ? "Simpan belum terkonfirmasi. Periksa koneksi dan catatan terbaru sebelum mencoba lagi. Isian tetap utuh."
          : "Belum tersimpan. " + String(e);
        if (selesaiKering) {
          // log_moisture dapat sudah commit walau tahap penutupan gagal.
          // Baca ulang, jangan mengulang POST atau mengklaim rollback total.
          periksaSelesai = true;
          var terbaruSelesai = await perbaruiSelesai();
          if (!lembar.open || lembar.querySelector(".lembar__isi") !== borangHasil || nilaiMedan(selesaiKering.proses) !== isi.kode_lot) return;
          if (!terbaruSelesai) pesanGagal = "Simpan belum terkonfirmasi. Isian tetap utuh. Periksa status terbaru sebelum mencoba kembali.";
          else if (terbaruSelesai.dapat_diselesaikan === false) pesanGagal = "Status lot sudah berubah. Buka detail terbaru untuk memeriksa hasil; formulir tidak mengirim ulang. Isian tetap utuh.";
          else if (!sebelumSelesai || terbaruSelesai.jumlah_log !== sebelumSelesai.jumlah_log) {
            risikoSelesai = true;$("simpan").disabled = true;$("sk-detail").hidden = false;
            $("sk-info").textContent = "Periksa catatan pengukuran dan kelanjutan proses di detail terbaru.";
            pesanGagal = "Penyelesaian belum terkonfirmasi; catatan pengukuran mungkin sudah tersimpan. Buka detail terbaru untuk memeriksanya. Isian tetap utuh dan tidak dikirim ulang otomatis.";
          }
        }
        if (pindahSilo) {
          $("ps-periksa").hidden = false;
          periksaPindah = e instanceof TypeError;
          var terbaruPindah = await perbaruiPindah();
          if (terbaruPindah && !terbaruPindah.siap) pesanGagal = "Status atau lokasi lot sudah berubah. Periksa detail terbaru; formulir tidak mengirim ulang. Pilihan tetap utuh.";
        }
        if(tambahGiling){$('tg-periksa').hidden=false;await perbaruiTg();}
        if (mulaiBahan) {
          $("mg-periksa").hidden = false;periksaMulai = e instanceof TypeError;
          var terbaruMulai = await perbaruiMulai();
          if (terbaruMulai && !terbaruMulai.siap) pesanGagal = "Pilihan atau status silo sudah berubah. Periksa proses terbaru dan perbaiki centang; formulir tidak mengirim ulang. Pilihan tetap utuh.";
        }
        if(selesaiSosoh){
          if(e instanceof TypeError){risikoSs=true;if(tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}
            var cekSs=document.createElement('button');cekSs.type='button';cekSs.className='btn ss-link';cekSs.textContent='Periksa status proses terbaru';
            cekSs.onclick=async function(){cekSs.disabled=true;var d=await perbaruiSs();cekSs.disabled=false;var info=document.createElement('p');info.className='ss-note';info.textContent=d?d.status==='selesai'?'Proses sudah selesai. Buka riwayat; jangan kirim ulang.':'Proses masih aktif. Kembali dan minta pemeriksaan baru sebelum konfirmasi.':'Status belum terkonfirmasi. Pilihan dan ringkasan tetap utuh.';cekSs.after(info);if(d){var l=document.createElement('a');l.className='btn';l.href=d.detail;l.textContent='Buka detail terbaru';info.after(l);}};
            lembar.querySelector('.lembar__konfirmasi').appendChild(cekSs);
          }else{risikoSs=false;perbaruiSs();}
        }
        if(selesaiGiling){
          if(e instanceof TypeError){risikoSg=true;if(tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}
            var cekSg=document.createElement('button');cekSg.type='button';cekSg.className='btn';cekSg.textContent='Periksa status proses terbaru';
            cekSg.onclick=async function(){cekSg.disabled=true;var d=await perbaruiSg();cekSg.disabled=false;var info=document.createElement('p');info.className='nota';info.textContent=d?d.status==='selesai'?'Proses sudah selesai. Periksa hasil di riwayat; jangan kirim ulang.':'Proses masih aktif. Kembali periksa isian lalu minta ringkasan baru sebelum konfirmasi.':'Status belum dapat dikonfirmasi. Ringkasan dan isian tetap utuh.';cekSg.after(info);if(d){var l=document.createElement('a');l.className='btn';l.href=d.detail;l.textContent='Buka detail terbaru';info.after(l);}};
            lembar.querySelector('.lembar__konfirmasi').appendChild(cekSg);
          }else{risikoSg=false;perbaruiSg();}
        }
        if(tambahSosoh){risikoTs=e instanceof TypeError;$('ts-periksa').hidden=false;$('ts-detail').hidden=false;$('ts-detail').href='/proses-aktif/sosoh/'+encodeURIComponent(isi.kode);if(risikoTs&&tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}await perbaruiTs();}
        if(bebaskanSosoh){
          if(e instanceof TypeError){risikoBsp=true;if(tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}var cekBsp=document.createElement('button');cekBsp.type='button';cekBsp.className='btn';cekBsp.textContent='Periksa pemakaian terbaru';cekBsp.onclick=async function(){cekBsp.disabled=true;try{var r=await fetch(bebaskanSosoh.source+'?kode_proses='+encodeURIComponent(isi.kode_proses)+'&silo='+encodeURIComponent(isi.silo),{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error();var d=await r.json();var p=document.createElement('p');p.className='bsp-note';p.textContent=d.terbuka?'Pemakaian masih terbuka. Kembali dan periksa ulang ringkasan sebelum menyimpan.':'Pemakaian tidak lagi terbuka. Periksa catatan sisa di detail; jangan kirim ulang.';cekBsp.after(p);}catch(_){var p=document.createElement('p');p.textContent='Status belum terkonfirmasi. Isian dan ringkasan tetap utuh; tidak dikirim ulang otomatis.';cekBsp.after(p);}finally{cekBsp.disabled=false;}};lembar.querySelector('.lembar__konfirmasi').appendChild(cekBsp);
          }else{risikoBsp=false;perbaruiBsp();}
        }
        if(bebaskanGiling && e instanceof TypeError){risikoBs=true;if(tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}
          var cekBs=document.createElement('button');cekBs.type='button';cekBs.className='btn bs-check';cekBs.textContent='Periksa sumber & silo terbaru';
          cekBs.onclick=async function(){cekBs.disabled=true;var info=document.createElement('p');info.className='bs-note';cekBs.after(info);
            try{var r=await fetch(bebaskanGiling.source+'?kode_proses='+encodeURIComponent(isi.kode_proses)+'&silo='+encodeURIComponent(isi.silo),{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error();var d=await r.json();if(d.kode_proses!==isi.kode_proses)throw new Error();
              info.textContent=d.terbuka?'Sumber masih terbuka. Kembali periksa isian dan minta ringkasan baru sebelum konfirmasi.':'Siklus tidak lagi terbuka. Periksa catatan sisa di detail terbaru; jangan kirim ulang.';var link=document.createElement('a');link.className='btn';link.textContent='Buka detail terbaru';link.href=d.detail;info.after(link);
            }catch(_){info.textContent='Keadaan terbaru belum dapat dibaca. Ringkasan dan isian tetap utuh; tidak ada pengiriman ulang otomatis.';}finally{cekBs.disabled=false;}};
          lembar.querySelector('.lembar__konfirmasi').appendChild(cekBs);
        }
        if(masukkanBroken){pesanGagal='Pemindahan belum berhasil sepenuhnya. '+String(e)+' Periksa saldo dan riwayat sebelum mencoba kembali; isian tetap utuh.';perbaruiBroken();}
        if(masukkanBroken && (e instanceof TypeError || /Sesi berubah ketika/.test(String(e)))){
          risikoBroken=true;if(tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}
          pesanGagal='Pemindahan belum terkonfirmasi. Jangan kirim ulang sebelum memeriksa Stok dan riwayat; layanan ini belum menjamin retry idempoten. Isian tetap utuh.';
          var cekBroken=document.createElement('a');cekBroken.className='btn';cekBroken.href='/stok';cekBroken.textContent='Buka stok dan riwayat broken';lembar.querySelector('.hasil-actions').before(cekBroken);
        }
        if(kemasBeras){perbaruiKemas();}
        if(kemasBeras&&(e instanceof TypeError||/Sesi berubah ketika/.test(String(e)))){risikoKemas=true;if(tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}pesanGagal='Pengemasan belum terkonfirmasi. Periksa Stok dan riwayat sebelum mencoba kembali; isian tetap utuh dan tidak dikirim ulang otomatis.';var cekPk=document.createElement('a');cekPk.className='btn';cekPk.href='/stok';cekPk.textContent='Buka Stok dan riwayat';lembar.querySelector('.hasil-actions').before(cekPk);}
        if(masukkanMenir){perbaruiMenir();}
        if(masukkanMenir&&(e instanceof TypeError||/Sesi berubah ketika/.test(String(e)))){risikoMenir=true;if(tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}pesanGagal='Pemindahan belum terkonfirmasi. Periksa Stok dan riwayat sebelum mencoba kembali; isian tetap utuh dan tidak dikirim ulang otomatis.';var cekMn=document.createElement('a');cekMn.className='btn';cekMn.href='/stok';cekMn.textContent='Buka stok dan riwayat '+jenisMn;lembar.querySelector('.hasil-actions').before(cekMn);}
        if(masukkanBeras){perbaruiBeras();}
        if(masukkanBeras&&(e instanceof TypeError||/Sesi berubah ketika/.test(String(e)))){risikoBeras=true;if(tbl){tbl.disabled=true;tbl.textContent='Perlu diperiksa';}pesanGagal='Pemindahan belum terkonfirmasi. Periksa Stok dan riwayat sebelum mencoba kembali; isian tetap utuh dan tidak dikirim ulang otomatis.';var cekBr=document.createElement('a');cekBr.className='btn';cekBr.href='/stok';cekBr.textContent='Buka stok dan riwayat beras';lembar.querySelector('.hasil-actions').before(cekBr);}
        salahFormulir(lembar, pesanGagal);
      }
    }

    function tanyaYakin(isi, v, khusus) {
      var k = khusus || a.konfirmasi;
      borangAsli = lembar.querySelector(".lembar__isi");
      borangAsli.hidden = true;
      var konfirmasi = document.createElement("div");
      konfirmasi.className = "lembar__isi lembar__konfirmasi";
      konfirmasi.innerHTML =
        '<div class="lembar__kepala"><h2>' + esc(k.judul || "Sudah benar?") + "</h2>" +
          '<button class="btn btn--kecil" id="kembali" type="button">Kembali</button></div>' +
          '<p class="bantu" style="margin-bottom:18px">' + esc(isikan(k.teks || "", v)).replace(/\n/g, "<br>") + "</p>" +
          '<button class="btn btn--utama" id="ya" type="button">' +
            esc(k.ya || "Ya, lanjutkan") + "</button>";
      if(selesaiGiling && k.rincian){
        konfirmasi.innerHTML='<div class="lembar__kepala"><h2>'+esc(k.judul)+'</h2></div>'+konfirmasiSg(k.rincian)+'<div class="hasil-actions"><button class="btn" id="kembali" type="button">Kembali periksa isian</button><button class="btn btn--utama" id="ya" type="button">Selesaikan giling</button></div>';
      }
      if(selesaiSosoh && k.rincian){
        konfirmasi.innerHTML='<div class="lembar__kepala"><h2>'+esc(k.judul)+'</h2></div>'+konfirmasiSs(k.rincian)+'<div class="hasil-actions"><button class="btn" id="kembali" type="button">Kembali</button><button class="btn btn--utama" id="ya" type="button">Selesaikan penyosohan</button></div>';
      }
      if(bebaskanSosoh && k.rincian){konfirmasi.innerHTML='<div class="lembar__kepala"><h2>Periksa sisa silo</h2></div>'+konfirmasiBsp(k.rincian)+'<div class="hasil-actions"><button class="btn" id="kembali" type="button">Kembali</button><button class="btn btn--utama" id="ya" type="button">Simpan sisa; bebaskan dari proses</button></div>';}
      if(bebaskanGiling && k.rincian){
        konfirmasi.innerHTML='<div class="lembar__kepala"><h2>'+esc(k.judul)+'</h2></div>'+konfirmasiBs(k.rincian)+'<div class="hasil-actions"><button class="btn" id="kembali" type="button">Kembali periksa isian</button><button class="btn btn--utama" id="ya" type="button">Simpan sisa; bebaskan dari proses</button></div>';
      }
      // Kembali menampilkan elemen formulir yang sama, berikut seluruh pilihannya.
      lembar.appendChild(konfirmasi);
      lembar.setAttribute("aria-label", k.judul || "Sudah benar?");
      $("kembali").onclick = kembaliKeBorang;
      $("kembali").focus();
      $("ya").onclick = function () { simpan(isi, v, $("ya")); };
    }

    $("simpan").onclick = async function () {
      if (formKhusus && lembar._menyimpan) return;
      if(selesaiGiling && memeriksaSg) return;
      if(selesaiSosoh && memeriksaSs) return;
      if(bebaskanGiling && memeriksaBs) return;
      if(bebaskanSosoh && memeriksaBsp) return;
      if (selesaiKering && (periksaSelesai || risikoSelesai || (dataSelesai && dataSelesai.dapat_diselesaikan === false))) return;
      if (mulaiBahan && periksaMulai) return;
      if (pindahSilo && (periksaPindah || (dataPindah && !dataPindah.siap))) return;
      // Semua pilihan WAJIB dipilih. Membiarkan pilihan pertama jadi default
      // berarti sebagian catatan akan diam-diam masuk ke tujuan yang salah.
      bersihkanSalah(lembar);
      var kurang = [];
      Array.prototype.forEach.call(lembar.querySelectorAll("[data-wajib], [data-p], [data-angka], [data-ulang]"), function (el) {
        if (el.disabled) return;
        var nilai = String(el.value).trim();
        var pasangan = el.closest(".ulang__baris");
        var terisi = pasangan && Array.prototype.some.call(pasangan.querySelectorAll("[data-p]"), function (p) { return p.value.trim(); });
        var wajib = el.hasAttribute("data-wajib") || terisi;
        var angka = el.hasAttribute("data-angka") || el.hasAttribute("data-ulang") || el.dataset.pJenis === "angka";
        var pesan = !nilai && wajib ? "Isi " + (el.dataset.label || el.dataset.name || "isian ini") + "." : "";
        if (nilai && angka && (!/^[+-]?\d+(?:[.,]\d+)?$/.test(nilai) || !Number.isFinite(Number(nilai.replace(",", "."))))) {
          pesan = "Masukkan angka yang benar.";
        }
        if (nilai && el.dataset.pJenis === "angka" && Number(nilai.replace(",", ".")) <= 0) pesan = "Jumlah harus lebih dari nol.";
        if (formHasil && el.dataset.name === formHasil.total && nilai &&
            Number.isFinite(Number(nilai.replace(",", "."))) && Number(nilai.replace(",", ".")) <= 0) pesan = "Total hasil harus lebih dari nol.";
        if ((formAir || selesaiKering) && ["tes","indikator","target","kadar_air"].indexOf(el.dataset.name) !== -1 && nilai &&
            Number.isFinite(Number(nilai.replace(",", "."))) && (Number(nilai.replace(",", ".")) <= 0 || Number(nilai.replace(",", ".")) > 100)) pesan = "Isi persen lebih dari 0 dan maksimal 100%.";
        if((bebaskanGiling || bebaskanSosoh) && el.dataset.name==="sisa" && nilai && Number.isFinite(Number(nilai.replace(",","."))) && Number(nilai.replace(",","."))<0)pesan="Sisa harus nol atau lebih.";
        if(selesaiGiling && el.dataset.name==="berat_akhir" && nilai && Number.isFinite(Number(nilai.replace(",","."))) && Number(nilai.replace(",","."))<=0)pesan="Hasil akhir PK harus lebih dari nol.";
        if (unitTransferPk && nilai && el.dataset.name === 'jumlah_karung' && (!Number.isInteger(Number(nilai.replace(',', '.'))) || Number(nilai.replace(',', '.')) < 0)) pesan = 'Jumlah karung harus bilangan bulat, nol atau lebih.';
        if (unitTransferPk && nilai && el.dataset.name === 'berat_curah_kg' && Number(nilai.replace(',', '.')) < 0) pesan = 'Bobot curah tidak boleh negatif.';
        if(masukkanSilo&&nilai&&['jumlah_karung','jumlah_karung_partai'].indexOf(el.dataset.name)>=0&&(!Number.isInteger(Number(nilai.replace(',','.')))||Number(nilai.replace(',','.'))<=0))pesan='Isi jumlah karung bulat lebih dari nol.';
        if(kemasBeras&&nilai&&el.dataset.name==='jumlah_karung'&&(!Number.isInteger(Number(nilai.replace(',','.')))||Number(nilai.replace(',','.'))<=0))pesan='Jumlah karung wajib bilangan bulat lebih dari nol.';
        if((masukkanBeras||masukkanMenir)&&nilai&&el.dataset.name==='berat_kg'&&Number(nilai.replace(',','.'))<=0)pesan='Isi berat lebih dari nol.';
        if(masukkanSilo&&nilai&&el.dataset.name==='berat_kg'&&Number(nilai.replace(',','.'))<=0)pesan='Isi berat lebih dari nol.';
        if (pesan) { kurang.push({el: el, pesan: pesan}); }
      });
      if (unitTransferPk && $('f_cara').value === 'karung' && !$('f_jumlah_karung').value.trim() && !$('f_berat_curah_kg').value.trim()) {
        kurang.push({el: $('f_jumlah_karung'), pesan: 'Isi jumlah karung atau bobot curah yang diperlukan.'});
      }
      if (kurang.length) {
        kurang.forEach(function (k, i) {
          var tampak = k.el.type === "hidden" ? ($("x_" + k.el.dataset.name) || $("b_" + k.el.dataset.name) || k.el) : k.el;
          var p = document.createElement("p");
          p.className = "formulir-salah"; p.id = "salah-isian-" + i;
          p.textContent = k.pesan;
          tampak.setAttribute("aria-invalid", "true");
          tampak.setAttribute("aria-describedby", p.id);
          var baris = tampak.closest(".ulang__baris");
          var sesudah = baris || tampak;
          while (sesudah.nextElementSibling && sesudah.nextElementSibling.classList.contains("formulir-salah")) {
            sesudah = sesudah.nextElementSibling;
          }
          sesudah.insertAdjacentElement("afterend", p);
          k.tampak = tampak;
        });
        salahFormulir(lembar, "Periksa " + kurang.length + " isian yang ditandai.");
        var awal = kurang[0].tampak;
        if (awal.type === "hidden") awal = $("simpan");
        if (!/^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(awal.tagName)) awal.tabIndex = -1;
        var pilihanAwal = awal.querySelector("input, select, button");
        (pilihanAwal || awal).focus(); awal.scrollIntoView({block: "center"});
        return;
      }

      var isi = muatan(), v = terbaca();
      // Ditanyakan SESUDAH isian lengkap: konfirmasi yang muncul sebelum
      // angkanya ada tidak punya apa-apa untuk dibandingkan.
      if (a.pratinjau_jeda) {
        var tombolJeda = $("simpan");
        var borangJeda = lembar.querySelector(".lembar__isi");
        tombolJeda.disabled = true;
        try {
          var keadaanJeda = await ambil("/api/actions/acuan-jeda?proses=" + encodeURIComponent(isi.proses));
          if (!keadaanJeda || !lembar.open || lembar.querySelector(".lembar__isi") !== borangJeda || nilaiMedan("proses") !== isi.proses) return;
          var awalJeda = acuanJeda[isi.proses];
          var berubahJeda = awalJeda && awalJeda.dasar !== keadaanJeda.dasar;
          isi.dasar = keadaanJeda.dasar;
          isi.kunci_kiriman = kunciJeda;
          if (isi.waktu_mode !== "aktual") { isi.waktu_kejadian = null; isi.alasan_terlambat = ""; }
          var waktuJeda = isi.waktu_mode === "aktual" ? String(isi.waktu_kejadian).replace("T", " ") + " WIB" : "sekarang, saat dikonfirmasi";
          var akibatJeda = a.pratinjau_jeda === "hentikan" ? "Mesin dicatat berhenti; proses tetap terbuka." :
            a.pratinjau_jeda === "kondisi" ? "Mesin tetap dijeda. Mulai jeda dan waktu berjalan tidak berubah; riwayat penyebab sebelumnya disimpan." : "Mesin dicatat berjalan kembali; interval jeda ditutup pada waktu kejadian.";
          tanyaYakin(isi, v, {judul: berubahJeda ? "Keadaan jeda BERUBAH — periksa ulang" : "Periksa kejadian jeda",
            teks: keadaanJeda.teks + "\n\nWaktu kejadian: " + waktuJeda +
              (isi.sebab ? "\nSebab: " + (isi.sebab === "Lainnya" ? isi.sebab_lain : isi.sebab) : "") +
              (isi.catatan ? "\nCatatan kondisi: " + isi.catatan : "") +
              (isi.alasan_terlambat ? "\nAlasan terlambat: " + isi.alasan_terlambat : "") + "\n\n" + akibatJeda,
            ya: a.pratinjau_jeda === "kondisi" ? "Simpan kondisi; tetap dijeda" : a.pratinjau_jeda === "hentikan" ? "Catat mesin berhenti" : "Catat mesin dilanjutkan"});
        } catch (e) { salahFormulir(lembar, String(e)); }
        finally { tombolJeda.disabled = false; }
        return;
      }
      if (a.pratinjau_silo) {
        var tombolSilo = $("simpan"), borangSilo = lembar.querySelector(".lembar__isi");
        tombolSilo.disabled = true;
        if(bebaskanGiling)memeriksaBs=true;
        var urutanBsp=nomorBsp;
        if(bebaskanSosoh)memeriksaBsp=true;
        try {
          var ringkasSilo = await ambil("/api/actions/pratinjau-bebaskan-silo?jenis=" + encodeURIComponent(a.pratinjau_silo) +
            "&kode_proses=" + encodeURIComponent(isi.kode_proses) + "&silo=" + encodeURIComponent(isi.silo || "") + "&sisa=" + encodeURIComponent(isi.sisa));
          if (!ringkasSilo || !lembar.open || lembar.querySelector(".lembar__isi") !== borangSilo ||
              nilaiMedan("kode_proses") !== isi.kode_proses) return;
          if((bebaskanGiling || bebaskanSosoh) && (nilaiMedan('silo')!==isi.silo || muatan().sisa!==isi.sisa))return;
          if(bebaskanSosoh && urutanBsp!==nomorBsp)return;
          if((bebaskanGiling || bebaskanSosoh) && (!ringkasSilo.dasar || !ringkasSilo.rincian || ringkasSilo.rincian.kode_proses!==isi.kode_proses || ringkasSilo.rincian.sisa!==isi.sisa))throw new Error('Ringkasan sisa belum lengkap. Periksa kembali.');
          isi.dasar = ringkasSilo.dasar;
          tanyaYakin(isi, v, {judul: "Periksa sisa silo", teks: ringkasSilo.teks, rincian: ringkasSilo.rincian, ya: "Simpan sisa; bebaskan dari proses"});
        } catch (e) { salahFormulir(lembar, String(e)); }
        finally { tombolSilo.disabled = false;memeriksaBs=false;memeriksaBsp=false; }
        return;
      }
      if (a.pratinjau_proses) {
        var tombolProses = $("simpan");
        var borangProses = lembar.querySelector(".lembar__isi");
        tombolProses.disabled = true;
        if(selesaiGiling)memeriksaSg=true;
        var pemeriksaanSs=nomorSs;
        if(selesaiSosoh)memeriksaSs=true;
        try {
          var alamatProses = "/api/actions/pratinjau-selesai-proses?jenis=" +
            encodeURIComponent(a.pratinjau_proses) + "&kode_proses=" + encodeURIComponent(isi.kode_proses);
          if (isi.berat_akhir != null) alamatProses += "&berat_akhir=" + encodeURIComponent(isi.berat_akhir);
          var ringkasProses = await ambil(alamatProses);
          if (!ringkasProses || !lembar.open || lembar.querySelector(".lembar__isi") !== borangProses ||
              nilaiMedan("kode_proses") !== isi.kode_proses || (selesaiSosoh && pemeriksaanSs!==nomorSs) || (selesaiGiling && (muatan().berat_akhir !== isi.berat_akhir))) return;
          if((selesaiGiling || selesaiSosoh) && (!ringkasProses.dasar || !ringkasProses.rincian || ringkasProses.rincian.kode_proses!==isi.kode_proses))throw new Error('Ringkasan penyelesaian belum lengkap. Periksa kembali.');
          isi.dasar = ringkasProses.dasar;
          tanyaYakin(isi, v, {judul: "Seluruh proses benar-benar selesai?",
            teks: ringkasProses.teks, rincian: ringkasProses.rincian,
            ya: a.pratinjau_proses === "giling" ? "Selesaikan giling" : "Selesaikan penyosohan"});
        } catch (e) { salahFormulir(lembar, String(e)); }
        finally { tombolProses.disabled = false;memeriksaSg=false;memeriksaSs=false; }
        return;
      }
      if (a.pratinjau_qc) {
        var tombolQc = $("simpan");
        var borangQc = lembar.querySelector(".lembar__isi");
        tombolQc.disabled = true;
        try {
          var qc = await ambil("/api/actions/pratinjau-tutup-qc?kode_batch=" + encodeURIComponent(isi.kode_batch));
          if (!qc || !lembar.open || lembar.querySelector(".lembar__isi") !== borangQc ||
              nilaiMedan("kode_batch") !== isi.kode_batch) return;
          isi.dasar = qc.dasar;
          tanyaYakin(isi, v, {judul: "Tutup QC sebelum lima pemeriksaan?",
            teks: qc.teks + "\n\nAlasan: " + isi.alasan,
            ya: "Tutup QC dengan " + qc.jumlah + " pemeriksaan"});
        } catch (e) { salahFormulir(lembar, String(e)); }
        finally { tombolQc.disabled = false; }
        return;
      }
      if (a.pratinjau_muat) {
        var tombol = $("simpan");
        tombol.disabled = true;
        var borangPratinjau = lembar.querySelector(".lembar__isi");
        try {
          var kini = await ambil("/api/actions/pratinjau-muat?perintah=" + encodeURIComponent(isi.perintah));
          if (!kini || !lembar.isConnected || !lembar.open ||
              lembar.querySelector(".lembar__isi") !== borangPratinjau ||
              nilaiMedan("perintah") !== isi.perintah) return;
          var awal = acuanMuat[isi.perintah];
          var beda = awal && awal.dasar !== kini.dasar;
          var teks = beda ? "PERINTAH ATAU MUATAN BERUBAH sejak formulir dibuka.\nSebelumnya:\n" + awal.teks + "\n\nTerbaru:\n" : "";
          teks += kini.teks;
          if (a.pratinjau_muat === "cepat") {
            acuanMuat[isi.perintah] = kini;
            if (!kini.cepat) {
              salahFormulir(lembar, "Total perintah tidak lagi di bawah 200 kg. Gunakan alur muat biasa."); return;
            }
            if (!awal || beda) {
              perbaruiKonteksMuat();
              salahFormulir(lembar, "Perintah atau muatan berubah. Isian tetap disimpan; periksa target terbaru dan jumlah aktual, lalu konfirmasi ulang."); return;
            }
            isi.baris = [];
            var kurangCepat = false;
            teks = kini.teks.split("\n")[0] + "\n\n";
            for (var b of kini.baris) {
              var jumlah = isi["aktual_" + b.id];
              if (!Number.isFinite(jumlah) || jumlah < 0 || jumlah > b.perintah ||
                  (b.satuan === "karung" && !Number.isInteger(jumlah))) {
                salahFormulir(lembar, "Periksa jumlah aktual " + b.nama + ". Isi 0 jika tidak diserahkan; karung wajib bulat dan tidak melebihi perintah.");
                $("f_aktual_" + b.id).focus(); return;
              }
              isi.baris.push({id: b.id, jumlah: jumlah});
              kurangCepat = kurangCepat || jumlah < b.perintah;
              teks += b.nama + "\nPerintah " + b.perintah + " → diserahkan " + jumlah + " " + b.satuan + "\n";
            }
            if (!isi.baris.some(function (b) { return b.jumlah > 0; })) {
              salahFormulir(lembar, "Isi jumlah aktual lebih dari 0 pada barang yang diserahkan."); return;
            }
            if (kurangCepat && !String(isi.sebab || "").trim()) {
              salahFormulir(lembar, "Jumlah kurang dari perintah. Tulis alasan barang tidak diserahkan.");
              $("f_sebab").focus(); return;
            }
            if (isi.sebab) teks += "\nAlasan: " + isi.sebab;
            teks += "\n\nPastikan barang sudah diserahkan. Stok berkurang sesuai jumlah aktual ini dan perintah selesai. Tiket timbang tidak wajib.";
            isi.dasar = kini.dasar;
            isi.diserahkan = true;
            tanyaYakin(isi, v, {judul: "Konfirmasi penyerahan", teks: teks,
              ya: "Jumlah benar, barang sudah diserahkan"});
            return;
          }
          if (a.pratinjau_muat === "baris") {
            var itemMuat = kini.baris.find(function (b) { return String(b.id) === isi.baris; });
            if (!itemMuat) { salahFormulir(lembar, "Barang tidak lagi tersedia pada perintah ini. Pilih ulang barang."); return; }
            if (!Number.isFinite(isi.jumlah) || isi.jumlah <= 0 ||
                (itemMuat.satuan === "karung" && !Number.isInteger(isi.jumlah))) {
              salahFormulir(lembar, "Total yang sudah dimuat " +
                (itemMuat.satuan === "karung" ? "dalam karung wajib bilangan bulat lebih dari 0." : "wajib lebih dari 0 kg."));
              $("f_jumlah").setAttribute("aria-invalid", "true");
              $("f_jumlah").focus(); return;
            }
            teks += "\n\n" + itemMuat.nama + ": total sebelumnya " + itemMuat.dimuat + " " + itemMuat.satuan +
              " → total yang sudah dimuat " + isi.jumlah + " " + itemMuat.satuan +
              ". Angka ini mengganti total sebelumnya; bukan tambahan.";
          } else if (a.pratinjau_muat === "semua") {
            teks += "\n\nSetelah dikonfirmasi, setiap barang menjadi sejumlah perintah. Pastikan seluruh sisa di atas SUDAH BENAR-BENAR dimuat.";
          } else {
            var kurang = kini.baris.some(function (b) { return b.sisa > 0; });
            if (kurang && !String(isi.sebab || "").trim()) {
              salahFormulir(lembar, "Muatan kurang dari perintah. Tulis alasan barang tidak terkirim.");
              $("f_sebab").focus(); return;
            }
            teks += "\n\nYang dikirim hanya jumlah sudah dimuat. Sisa tidak dikirim.";
            if (isi.sebab) teks += "\nAlasan: " + isi.sebab;
          }
          isi.dasar = kini.dasar;
          acuanMuat[isi.perintah] = kini;
          tanyaYakin(isi, v, {judul: "Periksa muatan aktual", teks: teks,
            ya: a.pratinjau_muat === "baris" ? "Catat total aktual ini" :
                (a.pratinjau_muat === "semua" ? "Semua sudah dimuat, selesaikan" : "Selesaikan sesuai muatan aktual")});
        } catch (e) { salahFormulir(lembar, String(e)); }
        finally { tombol.disabled = false; }
        return;
      }
      if (a.konfirmasi) { tanyaYakin(isi, v); return; }
      simpan(isi, v, $("simpan"));
    };

    // Isian yang sudah diketik dikembalikan saat orang menekan "Kembali"
    // dari layar konfirmasi. Pilihan `remote` dipulihkan lewat tulisannya,
    // karena daftarnya baru selesai dimuat sesudah ini.
    if (semula) {
      Array.prototype.forEach.call(lembar.querySelectorAll("[data-name]"), function (el) {
        /* Daftar centang dipulihkan lewat KODE, dan diperiksa lebih dulu:
           kotaknya belum ada saat ini dijalankan, jadi yang dititipkan
           `data-pulih` dan dipakai `muatBanyak` begitu daftarnya datang. */
        if (el.dataset.banyak) {
          el.dataset.pulih = semula["kode:" + el.dataset.name] || "";
          return;
        }
        /* Kombo: daftarnya baru selesai dimuat sesudah ini (sebangun
           `remote`/`remote_banyak`) — tulisannya dititipkan dulu,
           dicocokkan di `pasangKombo` begitu daftarnya datang. */
        if (el.dataset.cari) {
          el.dataset.pulih = semula[el.dataset.name] || "";
          return;
        }
        var t = semula[el.dataset.name];
        if (t === undefined || t === "") return;
        /* Medan berulang disimpan sebagai satu teks bergabung ("18% · 19%").
           Dipecah lagi di sini, dan kotaknya ditambah sebanyak yang perlu —
           kalau tidak, orang yang menekan "Kembali" kehilangan titik kedua
           dan seterusnya tanpa diberi tahu. */
        if (el.dataset.ulang) {
          if (el.previousElementSibling) return;   // cukup sekali per wadah
          var titik = String(t).split("·").map(function (x) {
            return x.replace("%", "").trim();
          }).filter(Boolean);
          var wadah = el.parentNode;
          titik.forEach(function (nilai, i) {
            var kotak = wadah.querySelectorAll("input")[i];
            if (!kotak) {
              kotak = el.cloneNode(true);
              kotak.removeAttribute("id");
              kotak.removeAttribute("data-wajib");
              kotak.placeholder = "titik " + (i + 1);
              wadah.appendChild(kotak);
            }
            kotak.value = nilai;
          });
          return;
        }
        if (el.tagName !== "SELECT") { el.value = t; return; }
        var pasang = function () {
          for (var i = 0; i < el.options.length; i++) {
            if (el.options[i].text === t) { el.selectedIndex = i; return true; }
          }
          return false;
        };
        if (!pasang()) setTimeout(pasang, 400);
        if (selesaiGiling) setTimeout(perbaruiSg,450);
        if (selesaiSosoh) setTimeout(perbaruiSs,450);
      });
    }

    if (a.pratinjau_jeda) {
      aturWaktuJeda(); ambilAcuanJeda();
      ["proses", "waktu_mode", "sebab"].forEach(function (nama) {
        var el = $("f_" + nama);
        if (el) el.addEventListener("change", function () { aturWaktuJeda(); ambilAcuanJeda(); });
      });
    }
    if (a.pratinjau_muat) {
      ambilAcuanMuat();
      var pilihPerintah = $("f_perintah");
      if (pilihPerintah) pilihPerintah.addEventListener("change", ambilAcuanMuat);
      var pilihBaris = $("f_baris");
      if (pilihBaris) pilihBaris.addEventListener("change", perbaruiKonteksMuat);
    }
    var pertama = lembar.querySelector(".fld");
    if (pertama) pertama.focus();
  }

  /* ── Lembar = <dialog> bawaan peramban ──
   *
   * showModal() memberi yang dulu ditiru sendiri: fokus terkunci di dalam
   * lembar, Escape dan tombol Kembali Android menutupnya (peristiwa `cancel`),
   * latar (::backdrop) yang menutup seluruh layar termasuk bilah navigasi —
   * tanpa pustaka, tanpa mengangkat elemennya ke luar `.isi`. Peramban tanpa
   * <dialog> mendapat jalur lama: atribut open + display flex. */
  function bukaLembar(lembar) {
    if (!lembarSedangTerbuka() && window.PINDAH) {
      // Satu entri membuat Back menutup lembar lebih dulu. PINDAH memakai
      // kait ini sebelum mengganti halaman agar formulir tidak tersapu.
      history.pushState(history.state, "", location.href);
      lembar._riwayat = true;
      var alamatLembar = location.href;
      PINDAH.tutupLembarRiwayat = function () {
        if (lembar._abaikanBalik) {
          lembar._abaikanBalik = false;
          lupakanBuka();
          return true;
        }
        if (!lembarSedangTerbuka() || !lembar._riwayat) return false;
        lembar._riwayat = false;
        if (lembar._konfirmasiBuang) lembar._konfirmasiBuang._selesai(false);
        else tutupLembar();
        if (lembarSedangTerbuka()) {
          history.pushState(history.state, "", alamatLembar);
          lembar._riwayat = true;
        }
        return true;
      };
    }
    if (typeof lembar.showModal === "function") {
      if (!lembar.open) { lembar.showModal(); }
    } else {
      lembar.setAttribute("open", "");
      lembar.style.display = "flex";
    }
  }

  function lembarSedangTerbuka() {
    var l = $("lembar");
    return !!(l && (l.open || l.style.display === "flex"));
  }

  function bersihkanSalah(l) {
    l.querySelectorAll(".formulir-salah, .formulir-gagal").forEach(function (e) { e.remove(); });
    l.querySelectorAll('[aria-invalid="true"]').forEach(function (e) {
      e.removeAttribute("aria-invalid"); e.removeAttribute("aria-describedby");
    });
  }

  function salahFormulir(l, pesan) {
    var p = l.querySelector(".formulir-gagal");
    if (!p) {
      p = document.createElement("p"); p.className = "pesan pesan--err formulir-gagal";
      p.setAttribute("role", "alert"); p.tabIndex = -1;
      var kepala = l.querySelector(".lembar__isi:not([hidden]) .lembar__kepala");
      kepala.insertAdjacentElement("afterend", p);
    }
    p.textContent = pesan;
    p.focus(); p.scrollIntoView({block: "center"});
  }

  function bolehBuang(l, lanjut) {
    if (l._menyimpan) return false;
    if (!l._berubah) return true;
    if (l._konfirmasiBuang) return false;
    // Dialog terpisah mempertahankan DOM formulir, termasuk pilihan berulang.
    // Menolak/menekan Escape hanya menutup pertanyaan, tidak membuang isian.
    var d = document.createElement("dialog");
    d.className = "konfirmasi-isian";
    d.setAttribute("aria-labelledby", "judul-buang-isian");
    d.setAttribute("aria-describedby", "pesan-buang-isian");
    d.innerHTML = '<p class="konfirmasi-isian__asal"></p>' +
      '<h2 id="judul-buang-isian">Tutup tanpa menyimpan?</h2>' +
      '<p id="pesan-buang-isian">Perubahan Anda belum disimpan. Jika ditutup, isian yang baru diubah akan dibuang.</p>' +
      '<div class="konfirmasi-isian__tombol">' +
      '<button type="button" class="btn btn--utama" data-lanjut-isi autofocus>Lanjut isi</button>' +
      '<button type="button" class="btn" data-buang-isian>Buang &amp; tutup</button></div>';
    var judul = l.querySelector(".lembar__isi:not([hidden]) h2");
    d.querySelector(".konfirmasi-isian__asal").textContent = judul ? judul.textContent : "Formulir";
    l._konfirmasiBuang = d;
    document.body.appendChild(d);
    function selesai(buang) {
      if (l._konfirmasiBuang !== d) return;
      l._konfirmasiBuang = null;
      d.close();
      d.remove();
      if (buang && !l._menyimpan && lembarSedangTerbuka()) {
        l._berubah = false;
        lanjut();
      }
    }
    d._selesai = selesai;
    d.querySelector("[data-lanjut-isi]").onclick = function () { selesai(false); };
    d.querySelector("[data-buang-isian]").onclick = function () { selesai(true); };
    d.addEventListener("keydown", function (e) {
      if (e.key !== "Tab") return;
      // Dialog native dapat melepas fokus ke bilah browser di ujung urutan.
      // Putar kedua tombol secara eksplisit; Escape tetap memakai cancel.
      var tombol = d.querySelectorAll("button:not(:disabled)");
      var posisi = Array.prototype.indexOf.call(tombol, document.activeElement);
      var tujuan = e.shiftKey
        ? (posisi <= 0 ? tombol.length - 1 : posisi - 1)
        : (posisi + 1) % tombol.length;
      e.preventDefault();
      tombol[tujuan].focus();
    });
    d.addEventListener("click", function (e) { if (e.target === d) selesai(false); });
    d.addEventListener("cancel", function (e) { e.preventDefault(); selesai(false); });
    d.addEventListener("close", function () { selesai(false); }, {once: true});
    d.showModal();
    return false;
  }

  function tutupLembar(paksa) {
    var l = $("lembar");
    // onclick memberi Event sebagai argumen: hanya boolean true boleh melewati pagar.
    if (paksa !== true && !bolehBuang(l, function () { tutupLembar(true); })) return;
    l._berubah = false;
    if (l._riwayat) {
      l._riwayat = false;
      l._abaikanBalik = true;
      history.back();
    }
    if (typeof l.close === "function") {
      if (l.open) { l.close(); }
    } else {
      l.removeAttribute("open");
      l.style.display = "none";
    }
    document.body.style.overflow = "";
    segarkanPilihan = null;
    /* ── Bendera "sedang mengetik" ikut dilepas ──
       `pindah.js` menyetelnya saat orang menyentuh isian apa pun, dan
       gunanya menahan segar-otomatis supaya ketikan yang belum tersimpan tak
       hilang. Tetapi ia hanya direset saat halaman BERPINDAH. Jadi sesudah
       menyentuh satu isian lalu menekan Batal, segar-otomatis mati diam-diam
       sampai orangnya kebetulan pindah halaman: sepuluh denyut, nol
       permintaan, dan layar yang makin lama makin basi tanpa tanda apa pun.
       Temuan QA P-K-19. */
    if (window.PINDAH && PINDAH.lupakanSentuhan) { PINDAH.lupakanSentuhan(); }
    lupakanBuka();
  }

  /* ── Menyegarkan daftar saat lembar kembali dilihat ──
     Lembar aksi sering dibiarkan terbuka sementara orangnya mengurus hal
     lain — menimbang truk, menelepon, mengunci layar. Saat ia kembali,
     daftarnya sudah setua kepergiannya.

     Dua kejadian dipakai karena keduanya berbeda: `visibilitychange` untuk
     layar ponsel yang mati dan hidup lagi, `focus` untuk berpindah tab atau
     kembali dari aplikasi lain. Keduanya dipasang SEKALI, di lingkup modul.

     Jeda 10 detik supaya berpindah-pindah tab dengan cepat tidak menjelma
     jadi rentetan permintaan ke server. */
  var JEDA_SEGAR = 10000;

  function mungkinSegarkan() {
    if (!segarkanPilihan) { return; }                  // tak ada lembar terbuka
    if (document.hidden) { return; }
    if (Date.now() - terakhirMuat < JEDA_SEGAR) { return; }
    segarkanPilihan();
  }

  (window.PINDAH && PINDAH.pasang ? PINDAH.pasang : function (s, j, f) {
    s.addEventListener(j, f);
  })(document, "visibilitychange", mungkinSegarkan);
  (window.PINDAH && PINDAH.pasang ? PINDAH.pasang : function (s, j, f) {
    s.addEventListener(j, f);
  })(window, "focus", mungkinSegarkan);

  /* ── Alamat harus mengatakan yang sebenarnya ──
     Kartu di antrean menaut ke `?buka=…&nilai=…`, dan lembarnya terbuka
     karena alamat itu. Begitu lembarnya ditutup — lewat Batal, Escape,
     ketukan di luar, atau simpan yang berhasil — alamatnya tetap berkata
     "lembar sedang terbuka", padahal tidak.

     Akibatnya kartu yang sama MATI: perpindahan halaman instan menolak
     tautan yang alamatnya sama persis dengan alamat sekarang (kalau tidak,
     tiap ketukan pada tab yang sedang aktif akan memuat ulang halaman).
     Jadi ketukan kedua tak menghasilkan apa pun, dan satu-satunya jalan
     keluar adalah memuat ulang halaman — yang tak terpikir siapa pun.

     Dibersihkan dengan `replaceState`, bukan `pushState`: menutup lembar
     bukan langkah baru dalam riwayat. Tombol Kembali harus membawa orang ke
     layar sebelumnya, bukan membuka lagi lembar yang baru saja ia tutup. */
  function lupakanBuka() {
    if (!window.history || !history.replaceState) { return; }
    var u = new URL(location.href);
    if (!u.searchParams.has("buka") && !u.searchParams.has("nilai") &&
        !u.searchParams.has("tiket") && !u.searchParams.has("sumber_stok")) { return; }
    u.searchParams.delete("buka");
    u.searchParams.delete("nilai");
    u.searchParams.delete("tiket");
    u.searchParams.delete("sumber_stok");
    history.replaceState(history.state, "", u.pathname + u.search + u.hash);
  }

  $("lembar").addEventListener("click", function (e) {
    if (e.target.id === "lembar") tutupLembar();     // ketukan di latar
  });
  /* Escape / tombol Kembali pada <dialog>: peramban meminta izin lewat
     `cancel`; ditolak lalu ditutup lewat jalur yang sama dengan Batal, supaya
     bendera ketikan dan alamat ?buka= ikut dibersihkan. */
  $("lembar").addEventListener("cancel", function (e) {
    e.preventDefault();
    tutupLembar();
  });
  /* Lewat PINDAH, bukan langsung ke `document`: skrip halaman dijalankan
     ulang tiap kali isinya ditukar, dan pendengar yang dipasang langsung
     akan menumpuk sekali tiap perpindahan. */
  PINDAH.pasang(document, "keydown", function (e) {
    if ($("lembar")._konfirmasiBuang) return;
    if (e.key === "Escape" && lembarSedangTerbuka()) { e.preventDefault(); tutupLembar(); }
  });

  PINDAH.pasang(window, "beforeunload", function (e) {
    var l = $("lembar");
    if (lembarSedangTerbuka() && (l._berubah || l._menyimpan)) {
      e.preventDefault(); e.returnValue = "";
    }
  });

  /* ── Tombol tujuan di dalam kartu ──
     Tanpa lembar sama sekali: kartunya dibentangkan, tujuannya ditekan,
     selesai. Dipasang lewat PINDAH supaya tak menumpuk tiap perpindahan,
     dan didelegasikan supaya kartu yang datang bersama layar yang digambar
     ulang ikut hidup tanpa dipasangi ulang satu per satu. */
  PINDAH.pasang(document, "click", async function (e) {
    var t = e.target.closest ? e.target.closest("[data-kirim]") : null;
    if (!t || t.disabled) { return; }
    e.preventDefault();
    var semula = t.innerHTML;
    t.disabled = true;
    t.classList.add("pilihan__satu--jalan");
    try {
      var hasil = await kirim(t.dataset.post, JSON.parse(t.dataset.kirim));
      var pesan = hasil.pesan || "Tersimpan ✓";
      muat();
      /* Server menyebutkan id catatannya; itu yang dipakai BATALKAN, bukan
         "cari yang terakhir" — antara menekan dan membatalkan, rekan di pos
         sebelah bisa saja sudah mencatat sesuatu. */
      if (hasil.log_id) {
        if (window.PINDAH && PINDAH.segarkan) {
          PINDAH.segarkan(function () { kabarBisaBatal(pesan, hasil.log_id); });
        } else {
          kabarBisaBatal(pesan, hasil.log_id);
        }
        return;
      }
      if (window.PINDAH && PINDAH.segarkan) {
        PINDAH.segarkan(function () { kabar(pesan, "ok"); });
      } else {
        kabar(pesan, "ok");
      }
    } catch (err) {
      /* Tombolnya dihidupkan lagi: yang ditolak biasanya bisa diperbaiki
         dengan memilih tujuan lain, dan kartu yang mati sesudah satu
         penolakan memaksa orang memuat ulang halaman. */
      t.disabled = false;
      t.classList.remove("pilihan__satu--jalan");
      t.innerHTML = semula;
      kabar(String(err), "err");
    }
  });

  /* ── Tombol di dalam lembar: tambah kotak, dan buka aksi lain ──
   *
   * Dipasang SEKALI di sini, bukan di dalam `bukaAksi`. `#lembar` adalah
   * elemen yang TETAP — yang ditukar tiap kali aksi dibuka hanyalah isinya —
   * jadi pendengar yang dipasang di dalam `bukaAksi` menumpuk satu tiap kali
   * lembar dibuka. Sesudah membuka lembar tiga kali, satu ketukan "Tambah"
   * menambah TIGA kotak. Bug itu sempat masuk hari ini bersama medan
   * berulangnya sendiri.
   *
   * Lewat PINDAH.pasang: `document` tak ikut ditukar saat halaman berpindah,
   * jadi pendengar yang dipasang langsung padanya juga menumpuk — satu tiap
   * perpindahan halaman. */
  (window.PINDAH && PINDAH.pasang ? PINDAH.pasang : function (s, j, f) {
    s.addEventListener(j, f);
  })(document, "click", function (e) {
    if (!e.target.closest) return;
    if (e.target.closest("#lembar [data-buang], #lembar [data-tambah]")) $("lembar")._berubah = true;

    /* Baris yang salah dipilih DIBUANG, bukan dikosongkan satu per satu.
       Baris pertama tak pernah hilang — ia pembawa `data-wajib` dan cetakan
       untuk baris berikutnya; kalau ia bisa dibuang, wadahnya jadi kosong dan
       tombol "+ Tambah item" tak punya apa pun untuk disalin. */
    var buang = e.target.closest("[data-buang]");
    if (buang) {
      e.preventDefault();
      var br = buang.closest(".ulang__baris");
      var wd = br && br.parentNode;
      if (!wd || wd.querySelectorAll(".ulang__baris").length <= 1) {
        if (br) {
          Array.prototype.forEach.call(br.querySelectorAll("select, input"),
            function (x) { x.value = ""; });
        }
        return;
      }
      br.remove();
      var tbl = document.querySelector(
        '[data-tambah="' + wd.dataset.ulangUntuk + '"]');
      if (tbl) { tbl.hidden = false; }
      return;
    }

    var tambah = e.target.closest("[data-tambah]");
    if (tambah) {
      e.preventDefault();
      var wadah = document.querySelector(
        '#lembar [data-ulang-untuk="' + tambah.dataset.tambah + '"]');
      if (!wadah) return;
      /* Wadah berpasangan menyalin satu BARIS utuh — beserta <option> yang
         sudah terlanjur dimuat, jadi baris baru langsung berisi daftarnya
         tanpa menunggu jaringan sekali lagi. `data-wajib` dilepas: hanya baris
         pertama yang wajib. */
      if (wadah.classList.contains("ulang--pasangan")) {
        var barisAda = wadah.querySelectorAll(".ulang__baris");
        var maksP = parseInt(wadah.dataset.maks, 10) || 10;
        if (barisAda.length >= maksP) return;
        var salin = barisAda[0].cloneNode(true);
        bersihkanSalah(salin);
        Array.prototype.forEach.call(salin.querySelectorAll("[data-wajib]"),
          function (x) { x.removeAttribute("data-wajib"); });
        Array.prototype.forEach.call(salin.querySelectorAll("select, input"),
          function (x) { x.value = ""; });
        wadah.appendChild(salin);
        var pilihBaru = salin.querySelector("select");
        if (pilihBaru) { perbaruiNamaBarang(pilihBaru); pilihBaru.onchange = function () { perbaruiNamaBarang(pilihBaru); }; pilihBaru.focus(); }
        if (barisAda.length + 1 >= maksP) tambah.hidden = true;
        return;
      }
      var ada = wadah.querySelectorAll("input").length;
      var maks = parseInt(wadah.dataset.maks, 10) || 4;
      if (ada >= maks) return;
      var kotak = wadah.querySelector("input").cloneNode(true);
      kotak.value = "";
      kotak.removeAttribute("id");          // id harus tetap satu di halaman
      kotak.removeAttribute("data-wajib");  // hanya titik pertama yang wajib
      kotak.placeholder = "titik " + (ada + 1);
      wadah.appendChild(kotak);
      if (wadah._titikKadar) wadah._titikKadar();
      kotak.focus();
      /* Tombolnya HILANG saat penuh, bukan diam tak menanggapi. Tombol yang
         ditekan lalu tak melakukan apa pun terbaca sebagai aplikasi rusak,
         dan orangnya menekannya berkali-kali untuk memastikan. */
      if (ada + 1 >= maks) tambah.hidden = true;
      return;
    }

    var pindah = e.target.closest("[data-buka-aksi]");
    if (pindah) {
      e.preventDefault();
      /* Benda yang sedang dikerjakan ikut dibawa, jadi orangnya tak ditanya
         dua kali "lot yang mana" — ia baru saja menjawabnya di borang yang
         sedang ditinggalkan. Yang dibawa TULISANNYA, bukan kodenya:
         pemulihan isian mencocokkan pilihan lewat teks yang tampil. */
      var bawa = {};
      if (pindah.dataset.bawa) {
        var el = document.querySelector('#lembar [data-name="' + pindah.dataset.bawa + '"]');
        var kunci = document.getElementById("t_" + pindah.dataset.bawa);
        if (kunci) { bawa[pindah.dataset.bawa] = kunci.textContent.trim(); }
        else if (el && el.tagName === "SELECT" && el.selectedIndex >= 0) {
          bawa[pindah.dataset.bawa] = el.options[el.selectedIndex].text;
        }
      }
      bukaAksi(pindah.dataset.bukaAksi, bawa);
    }
  });

  /* ── Katalog aksi hanya dimuat di layar yang memang menampungnya ──
     Skrip ini dimuat di enam layar, dan `muat()` memanggil dua endpoint —
     salah satunya yang terberat di aplikasi. Hanya `aksi_lain.html` yang
     punya wadah `#layar`; di lima layar lain hasilnya dibuang begitu saja,
     lalu `$("layar").innerHTML` melempar TypeError yang menghentikan SELURUH
     skrip, termasuk pendengar tombol di bawahnya.

     Dan karena `pindah.js` menjalankan ulang skrip tiap perpindahan halaman
     DAN tiap denyut, pemborosan itu berulang terus. Temuan QA UI-01. */
  if ($("layar")) { muat(); }

  /* Dibuka dari layar Berjalan: satu baris di sana menaut ke aksi yang
     menutupnya. Menurunkan orang di daftar aksi lalu menyuruhnya mencari
     sendiri akan membatalkan seluruh gunanya layar itu. */
  (function () {
    var tag = document.querySelector("script[data-buka]");
    var id = tag && tag.dataset.buka;
    if (!id) { return; }
    // Hak muat mencakup operator pengganti walaupun aksi tidak di katalog.
    if (id === "muat_barang" || id === "muat_semua") { bukaAksi(id); return; }
    /* ── Katalog dimuat juga saat dibuka lewat ?buka= ──
       Sejak perbaikan QA UI-01 (produksi 6be8636), `muat()` hanya dipanggil
       di layar yang punya `#layar` — Catat pekerjaan lain. Di Beranda,
       Antrian tunggu, Sedang berjalan, dan Keputusan MENU karenanya kosong,
       dan pemantau di bawah menunggu 4 detik lalu menyerah: menekan kartu
       tak pernah membuka lembarnya (temuan QA R-P-10). Tambalan ini lahir di
       salinan gudang2 (12 September 2026) dan dinaikkan ke paket saat Tahap 1
       karena benar untuk SEMUA aplikasi. Yang dimuat hanya katalognya, bukan
       dashboard — UI-01 tetap terjaga. */
    if (!Object.keys(MENU).length) {
      ambil("/api/actions/menu").then(function (menu) {
        (menu || []).forEach(function (a) { MENU[a.id] = a; });
      }).catch(function () {});
    }
    var coba = 0;
    var jam = setInterval(function () {
      if (MENU[id]) { clearInterval(jam); bukaAksi(id); isiDariBaris(); return; }
      // Menu datang dari server; kalau setelah beberapa detik aksinya tetap
      // tak ada, ia memang tak berlaku untuk peran ini — diamkan saja,
      // daftar aksinya sudah tampil dan orang bisa memilih sendiri.
      if (++coba > 40) { clearInterval(jam); }
    }, 100);
  })();

  /* Isi lembar dari baris yang ditekan di layar Berjalan.
   *
   * Barisnya sudah menunjuk satu tiket, satu lot, satu batch — menanyakannya
   * lagi di dalam lembar berarti orang memilih hal yang sama dua kali, dan
   * kesempatan kedua itulah tempat ia salah pilih.
   *
   * Pilihan jarak jauh dimuat setelah lembarnya tampil, jadi nilainya
   * dipasang berulang sampai daftarnya datang — lalu berhenti.
   *
   * ⚠ `change` DIPICU TANGAN sesudah `s.value =` — temuan 5 Oktober 2026.
   * Medan `induk` (mis. "silo" bergantung "kode_proses", "tiket" bergantung
   * "perintah") memuat ulang isinya lewat pendengar `change` pada induknya
   * (lihat `pi.addEventListener("change", ...)` di atas). `s.value = nilai`
   * TIDAK memicu event itu — ia cuma mengubah properti, bukan mensimulasikan
   * ketukan orang — jadi medan anak yang induknya diisi di sinilah yang
   * selama ini diam kosong selamanya tiap kartu dibuka lewat `?buka=&nilai=`,
   * sebab satu-satunya pemicu lain `segarkanPilihan` (fokus/visibilitas
   * kembali, berjeda 10 detik) belum tentu pernah tertekan sebelum orangnya
   * mengetik. Memicunya di sini memperbaiki SETIAP medan `induk` yang
   * pernah atau akan menjadi anak dari medan yang diisi lewat jalur ini —
   * bukan cuma satu borang. */
  function isiDariBaris() {
    var tag = document.querySelector("script[data-nilai]");
    var nilai = tag && tag.dataset.nilai;
    if (!nilai) { return; }
    var sisa = 40;
    var jam = setInterval(function () {
      var kena = false;
      Array.prototype.forEach.call(
        document.querySelectorAll("#lembar select[data-name]"), function (s) {
          if (s.value) { return; }
          for (var i = 0; i < s.options.length; i++) {
            if (s.options[i].value === nilai) {
              s.value = nilai;
              kena = true;
              s.dispatchEvent(new Event("change", { bubbles: true }));
              return;
            }
          }
        });
      if (kena || --sisa <= 0) { clearInterval(jam); }
    }, 100);
  }
})();
