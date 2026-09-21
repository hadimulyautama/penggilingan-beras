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
    var t = $("kabar");
    var teks;
    if (jenis === "err") {
      /* Sebab dari server sudah satu kalimat; awalannya saja yang dibuang
         supaya tak ada dua penanda berturut-turut. */
      teks = String(pesan == null ? "" : pesan)
        .split("\n")[0].replace(/^[⚠️!✗×]\s*/, "").trim() || "Gagal disimpan";
    } else {
      teks = "Tersimpan";
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
    var bagian = ("; " + document.cookie).split("; produksi_csrf=");
    return bagian.length === 2 ? bagian.pop().split(";").shift() : "";
  }

  async function kirim(url, isi) {
    var r = await fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": kukiCsrf() },
      body: JSON.stringify(isi),
    });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) {
      /* ── Konflik: SEGARKAN daftarnya sekarang juga ──
         Dua orang membuka tiket yang sama; yang kedua ditolak, tetapi kartu
         basinya tetap berdiri di daftar dan hitungannya tak berubah. Orang
         itu akan mencobanya lagi — dan ditolak lagi. Pesannya kini menyebut
         siapa dan pukul berapa; daftarnya diperbarui supaya kartunya benar-
         benar hilang. Temuan QA UI-02. */
      if (r.status === 409 || /sudah dicatat|sudah ditautkan|sudah tercatat/i
          .test(String(j.detail || ""))) {
        if (window.PINDAH) { PINDAH.lupakan(); PINDAH.segarkan(); }
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

    /* Yang dikunci hanya isian PENUNJUK — yang pertama bertipe pilihan.
       Di seluruh spesifikasi, isian itulah yang menyebut benda yang sedang
       dikerjakan; sisanya keputusan yang memang belum diambil. */
    var terkunci = nilaiBaris();
    var namaKunci = "";
    if (terkunci) {
      for (var i = 0; i < (a.fields || []).length; i++) {
        var f0 = a.fields[i];
        if (f0.type !== "select" && f0.type !== "remote") { continue; }
        if (f0.type === "select") {
          var ada = (f0.options || []).some(function (o) { return o[0] === terkunci; });
          if (!ada) { break; }
        }
        namaKunci = f0.name;
        break;
      }
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
      if (f.name === namaKunci) {
        var teks = terkunci;
        if (f.type === "select") {
          (f.options || []).forEach(function (o) {
            if (o[0] === terkunci) { teks = o[1]; }
          });
        }
        /* Tanpa label: label adalah pertanyaan, dan pertanyaan ini sudah
           dijawab saat kartunya ditekan. Yang tersisa cuma keterangan
           benda mana yang sedang dikerjakan — jadi borangnya terbaca mulai
           dari keputusan pertama yang memang belum diambil. */
        return '<p class="terkunci" id="t_' + esc(f.name) + '">' + esc(teks) + "</p>" +
          '<input type="hidden" data-name="' + esc(f.name) + '"' +
          ' data-label="' + esc(f.label) + '" value="' + esc(terkunci) + '">';
      }
      var l = '<label class="lbl" for="f_' + esc(f.name) + '">' + esc(f.label) + "</label>";
      if (f.type === "select") {
        var opts = (f.options.length && f.options[0][0] === "")
          ? f.options : [["", "— pilih —"]].concat(f.options);
        return l + '<select class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) + '"' +
          (f.optional ? "" : ' data-wajib="1"') + ' data-label="' + esc(f.label) + '">' +
          opts.map(function (o) {
            return '<option value="' + esc(o[0]) + '">' + esc(o[1]) + "</option>";
          }).join("") + "</select>";
      }
      if (f.type === "remote") {
        // `optional` ada karena sebagian pilihan memang tak berlaku untuk
        // semua isian: merk hanya milik beras, mutu hanya milik beras putih.
        // Memaksanya wajib akan membuat orang mengarang jawaban.
        return l + '<select class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
          '"' + (f.optional ? "" : ' data-wajib="1"') +
          ' data-label="' + esc(f.label) + '"><option>memuat…</option></select>';
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
      return l + '<input class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
        '"' + (f.wajib ? ' data-wajib="1"' : "") +
        ' data-label="' + esc(f.label) + '"' +
        ' type="text" inputmode="' + (angka ? "decimal" : "text") + '"' +
        (angka ? ' data-angka="1" pattern="[0-9]*[.,]?[0-9]*"' : "") +
        ' enterkeyhint="' + (terakhir ? "done" : "next") + '" autocomplete="off">';
    }).join("");

    var judul = belah(a.label).teks;
    var lembar = $("lembar");
    lembar.setAttribute("aria-label", judul);
    lembar.innerHTML =
      '<div class="lembar__isi">' +
        '<div class="lembar__kepala"><h2>' + esc(judul) + "</h2>" +
          '<button class="btn btn--kecil" id="tutup" type="button">Batal</button></div>' +
        (a.hint ? '<p class="bantu" style="margin-bottom:14px">' + esc(a.hint) + "</p>" : "") +
        '<div class="grup">' + isi + "</div>" +
        '<button class="btn btn--utama" id="simpan" type="button" style="margin-top:18px">Simpan</button>' +
        tombolLain +
      "</div>";
    bukaLembar(lembar);
    document.body.style.overflow = "hidden";

    /* ── Daftar pilihan dimuat ULANG, bukan sekali ──
       Tiket timbang yang baru dibuat di Pos Timbang tak muncul di lembar yang
       sudah telanjur terbuka. Operator gudang membuka "Gabah masuk", menunggu
       truknya ditimbang, lalu tak menemukan tiketnya — dan satu-satunya jalan
       keluar yang ia temukan sendiri adalah menutup aplikasinya.

       `segar` = pemuatan ULANG, bukan yang pertama. Bedanya penting: pilihan
       yang sudah dijatuhkan orangnya harus bertahan, dan baris terkunci tak
       perlu dihitung ulang karena bendanya memang tak berubah. */
    function muatPilihan(segar) {
      terakhirMuat = Date.now();
      (a.fields || []).forEach(function (f) {
      if (f.type !== "remote") return;
      ambil(f.source).then(function (daftar) {
        if (!daftar) return;
        if (f.name === namaKunci) {
          if (segar) { return; }
          /* Nama bendanya baru diketahui sesudah daftarnya datang. Kalau
             ternyata tak ada yang cocok, barisnya sudah basi — kuncinya
             dilepas supaya orang bisa memilih sendiri, bukan mengirim nilai
             yang akan ditolak. */
          var cocok = null;
          daftar.forEach(function (o) { if (o.value === terkunci) { cocok = o; } });
          var kotak = $("t_" + f.name);
          if (!kotak) { return; }
          if (cocok) { kotak.textContent = cocok.label; return; }
          kotak.outerHTML =
            '<span class="lbl">' + esc(f.label) + "</span>" +
            '<select class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
            '" data-wajib="1" data-label="' + esc(f.label) + '">' +
            '<option value="">— pilih —</option>' + daftar.map(function (o) {
              return '<option value="' + esc(o.value) + '">' + esc(o.label) + "</option>";
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
            return '<option value="' + esc(o.value) + '">' + esc(o.label) + "</option>";
          }).join("");
        if (dipilih) { s.value = dipilih; }
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
      }).catch(function () {});
      });
    }
    muatPilihan(false);
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
        var kotak = el.type === "hidden" ? $("t_" + el.dataset.name) : null;
        v[el.dataset.name] = kotak ? kotak.textContent.trim() : el.value;
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
      return isi;
    }

    async function simpan(isi, v, tbl) {
      if (tbl) { tbl.disabled = true; tbl.textContent = "Menyimpan…"; }
      try {
        var hasil = await kirim(a.post, isi);
        // Tombolnya sendiri yang menjawab: memuat → tercentang, di tempat.
        if (tbl) { tbl.textContent = "✓ Tersimpan"; }
        await new Promise(function (r) { setTimeout(r, 260); });
        tutupLembar();
        var pesan = hasil.pesan || "Tersimpan ✓";
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
        kabar(String(e), "err");
        // Borangnya dibuka ulang berisi jawaban yang sama: yang gagal biasanya
        // satu isian, dan mengetik semuanya lagi adalah hukuman untuk kesalahan
        // yang belum tentu miliknya.
        bukaAksi(id, v);
      }
    }

    function tanyaYakin(isi, v) {
      var k = a.konfirmasi;
      lembar.querySelector(".lembar__isi").innerHTML =
        '<div class="lembar__kepala"><h2>' + esc(k.judul || "Sudah benar?") + "</h2>" +
          '<button class="btn btn--kecil" id="kembali" type="button">Kembali</button></div>' +
          '<p class="bantu" style="margin-bottom:18px">' + esc(isikan(k.teks || "", v)) + "</p>" +
          '<button class="btn btn--utama" id="ya" type="button">' +
            esc(k.ya || "Ya, lanjutkan") + "</button>";
      // Kembali membuka ULANG borangnya — isian yang sudah diketik tidak
      // boleh hilang hanya karena orang ingin memeriksanya sekali lagi.
      $("kembali").onclick = function () { bukaAksi(id, v); };
      $("ya").onclick = function () { simpan(isi, v, $("ya")); };
    }

    $("simpan").onclick = function () {
      // Semua pilihan WAJIB dipilih. Membiarkan pilihan pertama jadi default
      // berarti sebagian catatan akan diam-diam masuk ke tujuan yang salah.
      var kurang = [];
      Array.prototype.forEach.call(lembar.querySelectorAll("[data-wajib]"), function (el) {
        if (!String(el.value).trim()) kurang.push(el.dataset.label || el.dataset.name);
      });
      if (kurang.length) { kabar("Belum diisi: " + kurang.join(", "), "err"); return; }

      var isi = muatan(), v = terbaca();
      // Ditanyakan SESUDAH isian lengkap: konfirmasi yang muncul sebelum
      // angkanya ada tidak punya apa-apa untuk dibandingkan.
      if (a.konfirmasi) { tanyaYakin(isi, v); return; }
      simpan(isi, v, $("simpan"));
    };

    // Isian yang sudah diketik dikembalikan saat orang menekan "Kembali"
    // dari layar konfirmasi. Pilihan `remote` dipulihkan lewat tulisannya,
    // karena daftarnya baru selesai dimuat sesudah ini.
    if (semula) {
      Array.prototype.forEach.call(lembar.querySelectorAll("[data-name]"), function (el) {
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

  function tutupLembar() {
    var l = $("lembar");
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
    if (!u.searchParams.has("buka") && !u.searchParams.has("nilai")) { return; }
    u.searchParams.delete("buka");
    u.searchParams.delete("nilai");
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
    if (e.key === "Escape" && lembarSedangTerbuka()) tutupLembar();
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

    var tambah = e.target.closest("[data-tambah]");
    if (tambah) {
      e.preventDefault();
      var wadah = document.querySelector(
        '#lembar [data-ulang-untuk="' + tambah.dataset.tambah + '"]');
      if (!wadah) return;
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
   * dipasang berulang sampai daftarnya datang — lalu berhenti. */
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
              return;
            }
          }
        });
      if (kena || --sisa <= 0) { clearInterval(jam); }
    }, 100);
  }
})();
