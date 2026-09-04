/* SEMENTARA — mencari APA yang menyusutkan jendela dari 852 jadi 793.
 *
 * Kerangkanya sudah terbukti benar: ia mengisi jendelanya persis (sisa 0).
 * Yang salah jendelanya. Dan halaman ukur yang berdiri sendiri — di jendela
 * terpasang YANG SAMA — melapor 852, jadi penyebabnya ada di `<head>`
 * aplikasi ini, pada sesuatu yang tidak dimiliki halaman itu.
 *
 * Tiga tersangka, ketiganya dimatikan satu per satu SAAT BERJALAN lalu
 * innerHeight diukur ulang. Yang mana pun yang mengubah angkanya, dialah
 * pelakunya — tanpa perlu satu deploy per tebakan.
 */
(function () {
  "use strict";

  function tunggu(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function mulai() {
    var isi = document.querySelector(".isi");
    var bingkai = document.querySelector(".bingkai");
    if (!isi || !bingkai) { return; }

    var html = document.documentElement, body = document.body;
    var awal = innerHeight;

    // A — html/body: overflow hidden + height 100%
    var simpanH = html.style.cssText, simpanB = body.style.cssText;
    html.style.overflow = "visible"; html.style.height = "auto";
    body.style.overflow = "visible"; body.style.height = "auto";
    await tunggu(350);
    var tanpaOverflow = innerHeight;
    html.style.cssText = simpanH; body.style.cssText = simpanB;
    await tunggu(250);

    // B — <meta name="theme-color">
    var tema = document.querySelector('meta[name="theme-color"]');
    var indukTema = tema && tema.parentNode;
    if (tema) { tema.remove(); }
    await tunggu(350);
    var tanpaTema = innerHeight;
    if (tema && indukTema) { indukTema.appendChild(tema); }
    await tunggu(250);

    // C — <link rel="manifest">
    var man = document.querySelector('link[rel="manifest"]');
    var indukMan = man && man.parentNode;
    if (man) { man.remove(); }
    await tunggu(350);
    var tanpaManifest = innerHeight;
    if (man && indukMan) { indukMan.appendChild(man); }

    function env(sisi) {
      var d = document.createElement("div");
      d.style.cssText = "position:fixed;left:0;right:0;bottom:0;visibility:hidden;" +
        "padding-top:env(safe-area-inset-" + sisi + ");height:0;box-sizing:content-box;";
      body.appendChild(d); var v = d.offsetHeight; d.remove(); return v;
    }
    function tandai(n) {
      return n === awal ? n + "  (tetap)" : n + "  ← BERUBAH";
    }

    var baris = [
      ["layar", screen.height],
      ["jendela sekarang", awal],
      ["A· tanpa overflow-hidden", tandai(tanpaOverflow)],
      ["B· tanpa theme-color", tandai(tanpaTema)],
      ["C· tanpa manifest", tandai(tanpaManifest)],
      ["env atas / bawah", env("top") + " / " + env("bottom")],
      ["standalone", (matchMedia("(display-mode: standalone)").matches ||
                      navigator.standalone === true) ? "YA" : "tidak"],
    ];

    var kotak = document.createElement("div");
    kotak.style.cssText =
      "background:#2a1a1a;border:1px solid #d9695a;border-radius:8px;padding:9px 11px;" +
      "font:12px/1.6 ui-monospace,Menlo,monospace;color:#f0d8d4;";
    kotak.innerHTML = "<b style='color:#d9695a'>SIAPA YANG MENYUSUTKAN JENDELA</b><br>" +
      baris.map(function (r) { return r[0] + ": <b>" + r[1] + "</b>"; }).join("<br>");
    isi.insertBefore(kotak, isi.firstChild);

    var pita = document.createElement("div");
    pita.style.cssText = "position:fixed;left:0;right:0;bottom:0;height:14px;" +
      "background:#56b880;z-index:9999;";
    body.appendChild(pita);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mulai);
  } else { mulai(); }
})();
