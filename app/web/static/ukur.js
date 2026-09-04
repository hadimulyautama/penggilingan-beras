/* SEMENTARA — pengukur kerangka aplikasi. Hapus bersama barisnya di base.html. */
(function () {
  "use strict";
  function mulai() {
    var bingkai = document.querySelector(".bingkai");
    var isi = document.querySelector(".isi");
    if (!bingkai || !isi) { return; }

    function env(sisi) {
      var d = document.createElement("div");
      d.style.cssText = "position:fixed;left:0;right:0;bottom:0;visibility:hidden;" +
        "padding-top:env(safe-area-inset-" + sisi + ");height:0;box-sizing:content-box;";
      document.body.appendChild(d);
      var v = d.offsetHeight; d.remove(); return v;
    }
    var b = bingkai.getBoundingClientRect();
    var bar = document.querySelector(".bilah");
    var n = bar ? bar.getBoundingClientRect() : null;
    var g = getComputedStyle(bingkai);

    var baris = [
      ["innerHeight", innerHeight],
      ["screen.height", screen.height],
      ["bingkai posisi", g.position],
      ["bingkai atas", Math.round(b.top)],
      ["bingkai tinggi", Math.round(b.height)],
      ["SISA di bawah bingkai", Math.round(innerHeight - b.bottom)],
      ["SISA di bawah bilah", n ? Math.round(innerHeight - n.bottom) : "-"],
      ["bilah padding-bawah", bar ? getComputedStyle(bar).paddingBottom : "-"],
      ["env atas / bawah", env("top") + " / " + env("bottom")],
      ["body tinggi", Math.round(document.body.getBoundingClientRect().height)],
      ["standalone", (matchMedia("(display-mode: standalone)").matches ||
                      navigator.standalone === true) ? "YA" : "tidak"],
    ];

    var kotak = document.createElement("div");
    kotak.style.cssText =
      "background:#2a1a1a;border:1px solid #d9695a;border-radius:8px;padding:9px 11px;" +
      "font:11.5px/1.5 ui-monospace,Menlo,monospace;color:#f0d8d4;";
    kotak.innerHTML = "<b style='color:#d9695a'>UKUR KERANGKA (sementara)</b><br>" +
      baris.map(function (r) { return r[0] + ": <b>" + r[1] + "</b>"; }).join("<br>");
    isi.insertBefore(kotak, isi.firstChild);

    /* Pita hijau dipaku ke tepi bawah, di atas segalanya: kalau ia terlihat
       menyentuh tepi layar, jendelanya memang sampai bawah dan yang kurang
       adalah kerangkanya. */
    var pita = document.createElement("div");
    pita.style.cssText = "position:fixed;left:0;right:0;bottom:0;height:14px;" +
      "background:#56b880;z-index:9999;";
    document.body.appendChild(pita);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mulai);
  } else { mulai(); }
})();
