/* Layar pencatatan Pos Produksi.
 *
 * Formulirnya TIDAK ditulis di sini. Server yang mengirim daftar aksi beserta
 * spesifikasi tiap field (jenis, pilihan, sumber data jarak jauh) lewat
 * /api/actions/menu; berkas ini hanya merendernya. Menambah aksi baru
 * berarti menambah satu spesifikasi di Python — bukan menulis layar baru.
 */
(function () {
  "use strict";

  var MENU = {};
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
  function kabar(pesan, jenis) {
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
      teks = /dibatalkan/i.test(String(pesan)) ? "Dibatalkan" : "Tersimpan";
    }
    t.innerHTML = '<div class="kabar__utama">'
      + '<span class="kabar__ikon" aria-hidden="true">'
      + (jenis === "err" ? "!" : "\u2713") + "</span>"
      + '<span class="kabar__teks">' + esc(teks) + "</span></div>";
    t.className = "kabar" + (jenis ? " kabar--" + jenis : "");
    t.style.display = "block";
    t.onclick = function () { t.style.display = "none"; clearTimeout(t._t); };
    clearTimeout(t._t);
    /* Gagal menetap sampai ditekan: ia menghentikan pekerjaan dan menuntut
       tindakan. Berhasil boleh lewat — layarnya sendiri sudah membuktikannya. */
    if (jenis !== "err") {
      t._t = setTimeout(function () { t.style.display = "none"; }, 2600);
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
    var a = MENU[id];
    if (!a) return;
    if (lembarSedangTerbuka() && !bolehBuang($("lembar"))) return;

    /* Yang dikunci hanya isian PENUNJUK — yang pertama bertipe pilihan.
       Di seluruh spesifikasi, isian itulah yang menyebut benda yang sedang
       dikerjakan; sisanya keputusan yang memang belum diambil. */
    var terkunci = nilaiBaris();
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
        return l + '<select class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) + '"' +
          (f.optional ? "" : ' data-wajib="1"') + ' data-label="' + esc(f.label) + '">' +
          opts.map(function (o) {
            return '<option value="' + esc(o[0]) + '"' + (f.bawaan === o[0] ? ' selected' : '') + '>' + esc(o[1]) + "</option>";
          }).join("") + "</select>";
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
    var judul = belah(a.label).teks;
    var lembar = $("lembar");
    lembar.setAttribute("aria-label", judul);
    lembar.innerHTML =
      '<div class="lembar__isi">' +
        '<div class="lembar__kepala"><h2>' + esc(judul) + "</h2>" +
          '<button class="btn btn--kecil" id="tutup" type="button">Batal</button></div>' +
        konteksKartu +
        (a.hint ? '<p class="bantu" style="margin-bottom:14px">' + esc(a.hint) + "</p>" : "") +
        '<div class="grup">' + isi + "</div>" +
        '<button class="btn btn--utama" id="simpan" type="button" style="margin-top:18px">Simpan</button>' +
        tombolLain +
      "</div>";
    lembar._berubah = false;
    lembar._menyimpan = false;
    lembar.oninput = lembar.onchange = function () { lembar._berubah = true; };
    bukaLembar(lembar);
    document.body.style.overflow = "hidden";

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
        batas.textContent = "Pilih proses & ukuran";
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
      if (f.induk) {
        var nilaiInduk = nilaiMedan(f.induk);
        if (!nilaiInduk) { return; }
        sumber += (sumber.indexOf("?") >= 0 ? "&" : "?") + "induk=" +
          encodeURIComponent(nilaiInduk);
      }
      ambil(sumber).then(function (daftar) {
        if (!daftar) { return; }
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

        wadah.innerHTML = daftar.map(function (o) {
          var c = sudah.indexOf(o.value) >= 0 || pulih.indexOf(o.value) >= 0;
          return '<label class="centang"><input type="checkbox" value="' + esc(o.value) +
            '" data-teks="' + esc(o.label) + '"' + (c ? " checked" : "") + ">" +
            "<span>" + esc(o.label) + "</span></label>";
        }).join("");
        Array.prototype.forEach.call(
          wadah.querySelectorAll('input[type="checkbox"]'), function (cb) {
            cb.addEventListener("change", sinkron);
          });
        /* Disetel SESUDAH kotaknya digambar: pilihan yang HILANG dari daftar
           (silonya baru saja diambil proses lain) tak boleh tetap terkirim
           hanya karena ia masih tercatat di kolom tersembunyi. */
        sinkron();
        var lamaNota = $("kosong_" + f.name);
        if (lamaNota) { lamaNota.remove(); }
        var tbl2 = $("simpan");
        if (tbl2 && tbl2.disabled) { tbl2.disabled = false; tbl2.textContent = "Simpan"; }
      }).catch(function () {});
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
      '<select class="fld" data-p="' + esc(f.name) + '" data-p-jenis="pilih"' +
      w + ' data-label="' + esc(f.label) + '">' +
      '<option value="">memuat…</option></select>' +
      '<input class="fld" data-p="' + esc(f.name) + '" data-p-jenis="angka"' +
      w + ' data-label="' + esc(f.label_angka || "Jumlah") + '"' +
      ' type="text" inputmode="decimal" pattern="[0-9]*[.,]?[0-9]*"' +
      ' autocomplete="off" enterkeyhint="next" placeholder="' +
      esc(f.label_angka || "Jumlah") + '">' +
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
            return;
          }
          if (f.name === "sumber_stok" && sumberBaris) {
            kotak.textContent = "Stok pada baris ini sudah tidak tersedia. Tutup dan muat ulang halaman.";
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
          if (tbl2 && tbl2.disabled) { tbl2.disabled = false; tbl2.textContent = "Simpan"; }
        }
        perbaruiMaksimalKemas();
        perbaruiKonteksMuat();
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

    $("tutup").onclick = tutupLembar;

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
      return isi;
    }

    // Konfirmasi menyembunyikan formulir asli, bukan membongkarnya. Semua
    // baris tambahan, koma desimal, dan pilihan asinkron tetap milik operator.
    var borangAsli = null;
    function kembaliKeBorang() {
      if (!borangAsli) return;
      var konfirmasi = lembar.querySelector(".lembar__konfirmasi");
      if (konfirmasi) konfirmasi.remove();
      borangAsli.hidden = false;
      borangAsli = null;
      lembar.setAttribute("aria-label", judul);
      $("simpan").focus();
    }

    async function simpan(isi, v, tbl) {
      lembar._menyimpan = true;
      var grup = lembar.querySelector(".grup");
      if (grup) grup.inert = true;
      var kembali = $("kembali");
      if (kembali) kembali.disabled = true;
      if (tbl) { tbl.disabled = true; tbl.textContent = "Menyimpan…"; }
      try {
        var hasil = await kirim(a.post, isi);
        // Tombolnya sendiri yang menjawab: memuat → tercentang, di tempat.
        if (tbl) { tbl.textContent = "✓ Tersimpan"; }
        await new Promise(function (r) { setTimeout(r, 260); });
        lembar._menyimpan = false;
        tutupLembar(true);
        var pesan = /\/undo(?:$|\?)/.test(a.post) ? "Dibatalkan" : (hasil.pesan || "Tersimpan ✓");
        muat();
        /* Kartu yang barusan diselesaikan harus HILANG sekarang juga. Ia
           digambar server, jadi `muat()` — yang cuma memuat ulang daftar
           aksi — tak menyentuhnya sama sekali. Kabarnya ditampilkan sesudah
           isinya ditukar, karena ia ikut tersapu bersama isi lama. */
        if (window.PINDAH && PINDAH.segarkan) {
          PINDAH.segarkan(function () { kabar(pesan, "ok"); });
        } else {
          kabar(pesan, "ok");
        }
      } catch (e) {
        lembar._menyimpan = false;
        if (grup) grup.inert = false;
        if (kembali) kembali.disabled = false;
        kembaliKeBorang();
        if (tbl) { tbl.disabled = false; tbl.textContent = "Simpan"; }
        salahFormulir(lembar, e instanceof TypeError
          ? "Simpan belum terkonfirmasi. Periksa koneksi dan catatan terbaru sebelum mencoba lagi. Isian tetap utuh."
          : "Belum tersimpan. " + String(e));
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
      // Kembali menampilkan elemen formulir yang sama, berikut seluruh pilihannya.
      lembar.appendChild(konfirmasi);
      lembar.setAttribute("aria-label", k.judul || "Sudah benar?");
      $("kembali").onclick = kembaliKeBorang;
      $("kembali").focus();
      $("ya").onclick = function () { simpan(isi, v, $("ya")); };
    }

    $("simpan").onclick = async function () {
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
        if (pesan) { kurang.push({el: el, pesan: pesan}); }
      });
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
        try {
          var ringkasSilo = await ambil("/api/actions/pratinjau-bebaskan-silo?jenis=" + encodeURIComponent(a.pratinjau_silo) +
            "&kode_proses=" + encodeURIComponent(isi.kode_proses) + "&silo=" + encodeURIComponent(isi.silo || "") + "&sisa=" + encodeURIComponent(isi.sisa));
          if (!ringkasSilo || !lembar.open || lembar.querySelector(".lembar__isi") !== borangSilo ||
              nilaiMedan("kode_proses") !== isi.kode_proses) return;
          isi.dasar = ringkasSilo.dasar;
          tanyaYakin(isi, v, {judul: "Periksa sisa silo", teks: ringkasSilo.teks, ya: "Simpan sisa; bebaskan dari proses"});
        } catch (e) { salahFormulir(lembar, String(e)); }
        finally { tombolSilo.disabled = false; }
        return;
      }
      if (a.pratinjau_proses) {
        var tombolProses = $("simpan");
        var borangProses = lembar.querySelector(".lembar__isi");
        tombolProses.disabled = true;
        try {
          var alamatProses = "/api/actions/pratinjau-selesai-proses?jenis=" +
            encodeURIComponent(a.pratinjau_proses) + "&kode_proses=" + encodeURIComponent(isi.kode_proses);
          if (isi.berat_akhir != null) alamatProses += "&berat_akhir=" + encodeURIComponent(isi.berat_akhir);
          var ringkasProses = await ambil(alamatProses);
          if (!ringkasProses || !lembar.open || lembar.querySelector(".lembar__isi") !== borangProses ||
              nilaiMedan("kode_proses") !== isi.kode_proses) return;
          isi.dasar = ringkasProses.dasar;
          tanyaYakin(isi, v, {judul: "Seluruh proses benar-benar selesai?",
            teks: ringkasProses.teks,
            ya: a.pratinjau_proses === "giling" ? "Selesaikan giling" : "Selesaikan penyosohan"});
        } catch (e) { salahFormulir(lembar, String(e)); }
        finally { tombolProses.disabled = false; }
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
        tutupLembar();
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

  function bolehBuang(l) {
    return !l._menyimpan && (!l._berubah || window.confirm(
      "Buang perubahan yang belum disimpan? Pilih Batal untuk melanjutkan pengisian."));
  }

  function tutupLembar(paksa) {
    var l = $("lembar");
    // onclick memberi Event sebagai argumen: hanya boolean true boleh melewati pagar.
    if (paksa !== true && !bolehBuang(l)) return;
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
        if (pilihBaru) { pilihBaru.focus(); }
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
