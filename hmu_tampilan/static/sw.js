/* Service worker layar pabrik — produksi, gudang2, meja.
 *
 * Rancangannya meniru pos timbang (timbangan/app/timbangan/static/sw.js):
 * yang di-cache HANYA kerangka — CSS, JS, ikon, manifest, dan satu halaman
 * cadangan /luring. Halaman SELALU dari jaringan; gagal → /luring, tidak
 * pernah halaman basi. Produksi menandai halaman `no-store` (middleware
 * halaman_jangan_disimpan), dan service worker yang menyimpan halaman akan
 * melawan keputusan itu.
 *
 * VERSI datang dari alamat pendaftaran (`/sw.js?v=126`), bukan ditulis
 * tangan di sini: satu sumber kebenaran, `hmu_tampilan.VERSI`. Menaikkan
 * VERSI mengubah alamat berkas ini di mata peramban → worker baru terpasang
 * → cache lama dibuang di `activate`.
 */
var VERSI = new URL(self.location.href).searchParams.get('v') || '0';
var NAMA = 'hmu-' + VERSI;

var RANGKA = [
  '/static/app.css?v=' + VERSI,
  '/static/komponen-portal.css?v=' + VERSI,
  '/static/padiflow-brand.css?v=' + VERSI,
  '/static/padiflow-logo-terang.png?v=' + VERSI,
  '/static/padiflow-logo-gelap.png?v=' + VERSI,
  '/static/aksi.js?v=' + VERSI,
  '/static/pindah.js?v=' + VERSI,
  '/static/ikon-180.png?v=' + VERSI,
  '/static/ikon-192.png?v=' + VERSI,
  '/static/ikon-512.png?v=' + VERSI,
  '/static/manifest.json?v=' + VERSI,
  '/luring'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(NAMA)
      .then(function (c) { return c.addAll(RANGKA); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (nama) {
      return Promise.all(nama.map(function (n) {
        return n === NAMA ? null : caches.delete(n);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  // Hanya GET. POST/PUT tak pernah disentuh: aksi pabrik harus sampai ke
  // server atau gagal terang-terangan — tak ada jawaban dari simpanan.
  if (req.method !== 'GET') { return; }

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) { return; }

  // Kerangka: dari cache dulu, cepat dan tahan sinyal buruk.
  if (url.pathname.indexOf('/static/') === 0) {
    e.respondWith(
      caches.match(req).then(function (tersimpan) {
        return tersimpan || fetch(req).then(function (r) {
          if (r.ok) {
            var salinan = r.clone();
            caches.open(NAMA).then(function (c) { c.put(req, salinan); });
          }
          return r;
        });
      })
    );
    return;
  }

  // Halaman: selalu dari jaringan. Gagal → halaman luring, bukan data basi.
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req).catch(function () {
        return caches.match('/luring');
      })
    );
  }
});
