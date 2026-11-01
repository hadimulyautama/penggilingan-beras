/* Tautan lama ke satu pesanan tetap membuka halaman yang memuatnya. GET saja. */
(function () {
  "use strict";
  function bukaPesanan() {
    var panel = document.querySelector("#pesanan-pelanggan");
    var match = /^#pesanan-(\d+)$/.exec(location.hash);
    if (!panel || !match || document.querySelector("dialog[open]")) return;
    var catatan = document.getElementById("pesanan-" + match[1]);
    if (catatan) { catatan.open = true; catatan.scrollIntoView({block:"start"}); return; }
    var url = new URL(location.href);
    if (panel.dataset.pesananBanyak !== "1" || url.searchParams.get("pesanan_id") === match[1]) return;
    url.searchParams.set("tab", "ringkasan");
    url.searchParams.set("pesanan_id", match[1]);
    location.replace(url.href);
  }
  bukaPesanan();
  if (window.PINDAH) window.PINDAH.pasang(window, "hashchange", bukaPesanan);
  else window.addEventListener("hashchange", bukaPesanan);
})();
