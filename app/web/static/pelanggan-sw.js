/* Worker pelanggan tidak menyimpan halaman, PDF, sesi, atau data pelanggan.
 * Juga tidak menghapus cache worker produksi yang cakupannya lebih luas.
 * Cadangan luring tertanam agar tidak bergantung pada cache milik app lain.
 */
const LURING = `<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f5f5ef" media="(prefers-color-scheme:light)"><meta name="theme-color" content="#111914" media="(prefers-color-scheme:dark)"><title>Tanpa jaringan · PadiFlow Pelanggan</title>
<style>:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;min-height:100dvh;display:grid;place-items:center;padding:24px;font:18px/1.6 system-ui;background:#f5f5ef;color:#202b25}main{max-width:34rem}h1{font-size:1.5rem}a{display:inline-block;padding:12px 20px;border-radius:10px;background:#326d45;color:#fff;text-decoration:none}@media(prefers-color-scheme:dark){body{background:#111914;color:#f5f5ef}}</style>
</head><body><main><p>PadiFlow Pelanggan</p><h1>Tanpa jaringan</h1><p>Sambungkan perangkat ke internet untuk melihat data dan laporan terbaru milik Anda.</p><a href="/pelanggan/">Coba lagi</a></main></body></html>`;

self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || req.mode !== 'navigate' ||
      url.origin !== self.location.origin || !url.pathname.startsWith('/pelanggan/') ||
      url.pathname.endsWith('.pdf')) return;
  event.respondWith(fetch(req).catch(() => new Response(LURING, {
    status: 503, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}
  })));
});
