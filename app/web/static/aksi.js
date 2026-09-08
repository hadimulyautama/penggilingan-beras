/* Layar pencatatan Pos Produksi.
 *
 * Formulirnya TIDAK ditulis di sini. Server yang mengirim daftar aksi beserta
 * spesifikasi tiap field (jenis, pilihan, sumber data jarak jauh) lewat
 * /miniapp/actions/menu; berkas ini hanya merendernya. Menambah aksi baru
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

  function kabar(pesan, jenis) {
    var t = $("kabar");
    t.textContent = pesan;
    t.className = "kabar" + (jenis ? " kabar--" + jenis : "");
    t.style.display = "block";
    clearTimeout(t._t);
    t._t = setTimeout(function () { t.style.display = "none"; }, 4200);
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

  async function kirim(url, isi) {
    var r = await fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(isi),
    });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw (j.detail || ("Gagal disimpan (HTTP " + r.status + ")"));
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
      var d = await ambil("/miniapp/dashboard");
      if (!d) return;
      var menu = [];
      try { menu = (await ambil("/miniapp/actions/menu")) || []; } catch (e) { menu = []; }
      DATA = { menu: menu };
      MENU = {};
      menu.forEach(function (a) { MENU[a.id] = a; });
      gambar();
    } catch (e) {
      $("layar").innerHTML = '<div class="pesan pesan--err">' + esc(String(e)) + "</div>";
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
      var aksi = DATA.menu || [];
      layar.innerHTML = aksi.length
        ? aksi.map(function (a) {
            var b = belah(a.label);
            return '<button class="tindakan" data-aksi="' + esc(a.id) + '">' +
              (b.ikon ? '<span class="tindakan__ikon tindakan__ikon--emoji">' + esc(b.ikon) + "</span>" : "") +
              '<span class="tindakan__isi"><span class="tindakan__nama">' + esc(b.teks) + "</span>" +
              (a.hint ? '<span class="tindakan__ket">' + esc(a.hint) + "</span>" : "") +
              "</span>" +
              '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="var(--redup-2)" ' +
              'stroke-width="2.2" stroke-linecap="round"><path d="M9 6l6 6-6 6"/></svg></button>';
          }).join("")
        : '<div class="kartu"><p class="bantu">Tidak ada aksi untuk peran Anda.</p></div>';
      Array.prototype.forEach.call(layar.querySelectorAll("[data-aksi]"), function (b) {
        b.onclick = function () { bukaAksi(b.dataset.aksi); };
      });
    }
  }

  function bukaAksi(id, semula) {
    var a = MENU[id];
    if (!a) return;

    var isi = (a.fields || []).map(function (f) {
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
      var angka = f.type === "number";
      // `wajib` OPT-IN, bukan kebalikan dari `optional`.
      //
      // Sebagian aksi sengaja meminta "isi minimal salah satu" — QC hasil
      // giling menerima kadar air ATAU broken ATAU susut. Menjadikan semua
      // kolom angka wajib secara diam-diam akan mematikan aksi-aksi itu, jadi
      // yang benar-benar wajib disebut satu per satu di spesifikasinya.
      return l + '<input class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
        '"' + (f.wajib ? ' data-wajib="1"' : "") +
        ' data-label="' + esc(f.label) + '"' +
        ' type="' + (angka ? "number" : "text") + '" inputmode="' + (angka ? "decimal" : "text") +
        '" autocomplete="off">';
    }).join("");

    var judul = belah(a.label).teks;
    var lembar = $("lembar");
    lembar.innerHTML =
      '<div class="lembar__isi" role="dialog" aria-modal="true" aria-label="' + esc(judul) + '">' +
        '<div class="lembar__kepala"><h2>' + esc(judul) + "</h2>" +
          '<button class="btn btn--kecil" id="tutup" type="button">Batal</button></div>' +
        (a.hint ? '<p class="bantu" style="margin-bottom:14px">' + esc(a.hint) + "</p>" : "") +
        '<div class="grup">' + isi + "</div>" +
        '<button class="btn btn--utama" id="simpan" type="button" style="margin-top:18px">Simpan</button>' +
      "</div>";
    lembar.style.display = "flex";
    document.body.style.overflow = "hidden";

    (a.fields || []).forEach(function (f) {
      if (f.type !== "remote") return;
      ambil(f.source).then(function (daftar) {
        if (!daftar) return;
        var s = $("f_" + f.name);
        s.innerHTML = '<option value="">' + (daftar.length ? "— pilih —" : "(belum ada)") +
          "</option>" + daftar.map(function (o) {
            return '<option value="' + esc(o.value) + '">' + esc(o.label) + "</option>";
          }).join("");
        // Kalau daftarnya kosong, aksi ini memang belum bisa dikerjakan.
        // Katakan sekarang — bukan setelah orang menekan Simpan dan ditolak.
        // Pilihan yang boleh dikosongkan tak boleh menghentikan aksi ketika
        // daftarnya kebetulan kosong — belum ada merk bukan alasan bekatul
        // tidak bisa dicatat.
        if (!daftar.length && !f.optional) {
          s.disabled = true;
          var nota = document.createElement("p");
          nota.className = "bantu";
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
        }
      }).catch(function () {});
    });

    $("tutup").onclick = tutupLembar;

    // Nilai yang TERBACA orang, bukan yang dikirim ke server. Untuk pilihan,
    // yang berarti adalah tulisan di layarnya ("Pengering 1"), bukan angka id
    // di baliknya — dan konfirmasi yang menyebut id tidak mengonfirmasi apa
    // pun.
    function terbaca() {
      var v = {};
      Array.prototype.forEach.call(lembar.querySelectorAll("[data-name]"), function (el) {
        v[el.dataset.name] = (el.tagName === "SELECT" && el.selectedIndex >= 0)
          ? el.options[el.selectedIndex].text : el.value;
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
        if (el.type === "number") v = (v === "" ? null : parseFloat(v));
        isi[el.dataset.name] = v;
      });
      return isi;
    }

    async function simpan(isi, v, tbl) {
      if (tbl) { tbl.disabled = true; tbl.textContent = "Menyimpan…"; }
      try {
        var hasil = await kirim(a.post, isi);
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

  function tutupLembar() {
    $("lembar").style.display = "none";
    document.body.style.overflow = "";
    lupakanBuka();
  }

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
    if (e.target.id === "lembar") tutupLembar();
  });
  /* Lewat PINDAH, bukan langsung ke `document`: skrip halaman dijalankan
     ulang tiap kali isinya ditukar, dan pendengar yang dipasang langsung
     akan menumpuk sekali tiap perpindahan. */
  PINDAH.pasang(document, "keydown", function (e) {
    if (e.key === "Escape" && $("lembar").style.display === "flex") tutupLembar();
  });

  muat();

  /* Dibuka dari layar Berjalan: satu baris di sana menaut ke aksi yang
     menutupnya. Menurunkan orang di daftar aksi lalu menyuruhnya mencari
     sendiri akan membatalkan seluruh gunanya layar itu. */
  (function () {
    var tag = document.querySelector("script[data-buka]");
    var id = tag && tag.dataset.buka;
    if (!id) { return; }
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
