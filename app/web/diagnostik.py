"""Satu halaman ukur, sementara.

Bilah navigasi menyisakan pita kosong di bawahnya pada perangkat pemilik.
Dua tebakan sudah meleset — `bottom: 0`, lalu `100dvh` — karena keduanya
dibangun di atas dugaan tentang cara iOS menghitung tepi layar, dan dugaan
itu tak bisa diuji dari mesin pengembang: peramban di sini tak punya area
aman, takik, maupun indikator beranda.

Jadi halaman ini menanyakannya langsung ke perangkatnya. Dibuka sekali,
difoto, lalu berkas ini dan barisnya di main.py DIHAPUS. Ia tidak menyentuh
basis data dan tidak mengubah apa pun.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

HALAMAN = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<title>Ukur tampilan</title>
<style>
  html, body { margin: 0; background: #0d1418; color: #dce7ec;
               font: 15px/1.5 ui-monospace, Menlo, monospace; }
  /* Tiga pita warna: kalau kerangka benar-benar sampai tepi, TIDAK ada
     warna gelap yang tersisa di atas atau di bawah. */
  .atas, .bawah { position: fixed; left: 0; right: 0; height: 6px; background: #d9695a; }
  .atas { top: 0; } .bawah { bottom: 0; }
  .kotak { position: fixed; inset: 0; border: 2px solid #4fb3d9; box-sizing: border-box;
           display: flex; flex-direction: column; }
  .isi { flex: 1 1 auto; overflow-y: auto; padding: 14px; }
  table { border-collapse: collapse; width: 100%; }
  td { padding: 3px 0; vertical-align: top; }
  td:first-child { color: #8ba0ab; padding-right: 10px; white-space: nowrap; }
  b { color: #56b880; }
  .palang { flex-shrink: 0; background: #16212a; border-top: 1px solid #2b3b45;
            padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
            text-align: center; color: #4fb3d9; }
</style>
</head>
<body>
<div class="atas"></div><div class="bawah"></div>
<div class="kotak">
  <div class="isi"><h1 style="margin:0 0 10px;font-size:17px;color:#4fb3d9">Ukur tampilan</h1><table id="t"><tr><td>memuat…</td></tr></table></div>
  <div class="palang">INI TEPI BAWAH KERANGKA &nbsp;·&nbsp; <a href="/pengaturan" style="color:#8ba0ab">kembali</a></div>
</div>
<script>
function sa(sisi) {
  var d = document.createElement("div");
  d.style.cssText = "position:fixed;height:env(safe-area-inset-" + sisi + ");";
  document.body.appendChild(d);
  var v = getComputedStyle(d).height;
  d.remove();
  return v;
}
try {
var k = document.querySelector(".kotak").getBoundingClientRect();
var p = document.querySelector(".palang").getBoundingClientRect();
var vv = window.visualViewport || {};
var baris = [
  ["innerHeight", innerHeight],
  ["clientHeight", document.documentElement.clientHeight],
  ["visualViewport.h", Math.round(vv.height || 0)],
  ["screen.height", screen.height],
  ["devicePixelRatio", devicePixelRatio],
  ["safe-area ATAS", sa("top")],
  ["safe-area BAWAH", sa("bottom")],
  ["100dvh", (function () { var d = document.createElement("div");
      d.style.cssText = "position:fixed;height:100dvh"; document.body.appendChild(d);
      var v = getComputedStyle(d).height; d.remove(); return v; })()],
  ["100svh / 100lvh", (function () {
      function u(x) { var d = document.createElement("div");
        d.style.cssText = "position:fixed;height:" + x; document.body.appendChild(d);
        var v = getComputedStyle(d).height; d.remove(); return v; }
      return u("100svh") + " / " + u("100lvh"); })()],
  ["kerangka atas", Math.round(k.top)],
  ["kerangka tinggi", Math.round(k.height)],
  ["SISA DI BAWAH", Math.round(innerHeight - p.bottom)],
  ["standalone", (matchMedia("(display-mode: standalone)").matches ||
                  navigator.standalone === true) ? "YA" : "tidak"],
  ["peramban", navigator.userAgent.slice(0, 70)],
];
document.getElementById("t").innerHTML = baris.map(function (b) {
  return "<tr><td>" + b[0] + "</td><td><b>" + b[1] + "</b></td></tr>";
}).join("");
} catch (e) {
  /* Tanpa ini, satu galat kecil menghasilkan halaman kosong — dan halaman
     kosong tidak memberi tahu apa-apa selain "coba lagi". */
  document.getElementById("t").innerHTML =
    "<tr><td>GALAT</td><td><b>" + String(e && e.message || e) + "</b></td></tr>";
}
</script>
</body>
</html>"""


@router.get("/diagnostik-tampilan", response_class=HTMLResponse)
async def diagnostik() -> HTMLResponse:
    """Sengaja TANPA login.

    Percobaan pertama memakai `butuh_akun`, dan hasilnya pemilik hanya melihat
    halaman masuk — alamat yang dibuka dari pesan mendarat di peramban yang
    belum punya sesi. Halaman ini tidak membaca basis data dan tidak
    menampilkan apa pun milik perusahaan; yang diukurnya hanya layar orang
    yang sedang membukanya sendiri.
    """
    return HTMLResponse(HALAMAN)
