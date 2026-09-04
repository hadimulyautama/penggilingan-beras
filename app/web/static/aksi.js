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
  var TAB = "aksi";

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
      DATA = { sections: d.sections || [], menu: menu };
      MENU = {};
      menu.forEach(function (a) { MENU[a.id] = a; });
      gambar();
    } catch (e) {
      $("layar").innerHTML = '<div class="pesan pesan--err">' + esc(String(e)) + "</div>";
    }
  }

  function gambar() {
    var tab = $("tab");
    var bagian = (DATA.sections || []).map(function (s) { return s.title; });
    var daftar = [["aksi", "Aksi"]].concat(bagian.map(function (j, i) { return ["s" + i, j]; }));
    tab.innerHTML = daftar.map(function (t) {
      return '<button class="tab' + (TAB === t[0] ? " tab--aktif" : "") +
        '" data-tab="' + t[0] + '">' + esc(t[1]) + "</button>";
    }).join("");
    tab.style.display = daftar.length > 1 ? "" : "none";
    Array.prototype.forEach.call(tab.querySelectorAll("[data-tab]"), function (b) {
      b.onclick = function () { TAB = b.dataset.tab; gambar(); };
    });

    var layar = $("layar");
    if (TAB === "aksi") {
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
    } else {
      var s = (DATA.sections || [])[parseInt(TAB.slice(1), 10)];
      layar.innerHTML = s
        ? '<div class="kartu"><span class="lbl">' + esc(s.title) + "</span>" +
          '<pre class="rincian">' + esc(s.body) + "</pre></div>"
        : "";
    }
  }

  function bukaAksi(id) {
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
      return l + '<input class="fld" id="f_' + esc(f.name) + '" data-name="' + esc(f.name) +
        '" type="' + (angka ? "number" : "text") + '" inputmode="' + (angka ? "decimal" : "text") +
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
          nota.textContent = "Belum ada " + (f.label || "pilihan").toLowerCase() +
            ". Aksi ini belum bisa dikerjakan sekarang.";
          s.insertAdjacentElement("afterend", nota);
          var tbl = $("simpan");
          if (tbl) { tbl.disabled = true; tbl.textContent = "Belum bisa disimpan"; }
        }
      }).catch(function () {});
    });

    $("tutup").onclick = tutupLembar;
    $("simpan").onclick = async function () {
      var tbl = $("simpan");
      // Semua pilihan WAJIB dipilih. Membiarkan pilihan pertama jadi default
      // berarti sebagian catatan akan diam-diam masuk ke tujuan yang salah.
      var kurang = [];
      Array.prototype.forEach.call(lembar.querySelectorAll("select[data-wajib]"), function (el) {
        if (!el.value) kurang.push(el.dataset.label || el.dataset.name);
      });
      if (kurang.length) { kabar("Belum dipilih: " + kurang.join(", "), "err"); return; }

      tbl.disabled = true;
      tbl.textContent = "Menyimpan…";
      try {
        var isi = {};
        Array.prototype.forEach.call(lembar.querySelectorAll("[data-name]"), function (el) {
          var v = el.value;
          if (el.type === "number") v = (v === "" ? null : parseFloat(v));
          isi[el.dataset.name] = v;
        });
        var hasil = await kirim(a.post, isi);
        tutupLembar();
        kabar(hasil.pesan || "Tersimpan ✓", "ok");
        muat();
      } catch (e) {
        kabar(String(e), "err");
        tbl.disabled = false;
        tbl.textContent = "Simpan";
      }
    };

    var pertama = lembar.querySelector(".fld");
    if (pertama) pertama.focus();
  }

  function tutupLembar() {
    $("lembar").style.display = "none";
    document.body.style.overflow = "";
  }

  $("lembar").addEventListener("click", function (e) {
    if (e.target.id === "lembar") tutupLembar();
  });
  document.addEventListener("keydown", function (e) {
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
      if (MENU[id]) { clearInterval(jam); bukaAksi(id); return; }
      // Menu datang dari server; kalau setelah beberapa detik aksinya tetap
      // tak ada, ia memang tak berlaku untuk peran ini — diamkan saja,
      // daftar aksinya sudah tampil dan orang bisa memilih sendiri.
      if (++coba > 40) { clearInterval(jam); }
    }, 100);
  })();
})();
