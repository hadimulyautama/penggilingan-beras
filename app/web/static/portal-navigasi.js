/* Navigasi baca portal: cache hanya di memori tab, terpisah akun, tanpa POST. */
(function () {
  'use strict';
  function pengarah(ops) {
    var cache = new Map(), urutan = 0;
    function ingat(url, html) {
      if (!html) return;
      cache.delete(url); cache.set(url, { html: html, saat: ops.waktu() });
      if (cache.size > 8) cache.delete(cache.keys().next().value);
    }
    function terakhir(url) {
      var item = cache.get(url);
      return item && ops.waktu() - item.saat < 30000 ? item.html : null;
    }
    async function pindah(url, dorong, gulung) {
      var nomor = ++urutan, lama = terakhir(url), sentuhan;
      if (lama && !ops.pasang(lama, url, dorong, gulung)) { ops.utuh(url); return; }
      sentuhan = ops.sentuhan();
      ops.status(lama ? 'memperbarui' : 'memuat');
      var baru;
      try { baru = await ops.ambil(url); } catch (_) { baru = null; }
      if (nomor !== urutan) return;
      if (!baru || typeof baru !== 'string') {
        ops.utuh(baru && baru.login ? '/pelanggan/masuk' : url); return;
      }
      ingat(url, baru);
      if (lama && sentuhan !== ops.sentuhan()) {
        ops.status('perubahan', function () { pindah(url, false, gulung); }); return;
      }
      if (!ops.pasang(baru, url, lama ? false : dorong, gulung)) { ops.utuh(url); return; }
      ops.status('selesai');
    }
    return {
      pindah: pindah, ingat: ingat, bersihkan: function () { cache.clear(); ++urutan; },
      siapkan: async function (url) {
        if (terakhir(url)) return;
        try { var html = await ops.ambil(url); if (typeof html === 'string') ingat(url, html); } catch (_) {}
      }
    };
  }
  // Inti pengarah juga diuji tanpa peramban, dengan urutan respons terbalik.
  window.buatPengarahPortal = pengarah;
  var main = document.getElementById('isi-pelanggan');
  if (!main || !window.fetch || !window.history) return;
  var akun = document.body.getAttribute('data-portal-akun'), sentuhan = 0;
  var janji = new Map(), pesan = null, timer = null;
  function nonce() {
    return document.cookie.split('; ').find(function (s) { return s.indexOf('produksi_csrf=') === 0; }) || '';
  }
  var sesi = nonce();
  function alamat() { return location.pathname + location.search; }
  function aman(url) {
    return url.origin === location.origin && (url.pathname === '/pelanggan' || url.pathname.indexOf('/pelanggan/') === 0)
      && !/\/(masuk|keluar|sw\.js|manifest\.webmanifest)$/.test(url.pathname)
      && !/\.(pdf|csv)$/i.test(url.pathname) && !url.hash;
  }
  function status(mode, muat) {
    if (timer) clearTimeout(timer);
    if (pesan) pesan.remove();
    main.removeAttribute('aria-busy');
    pesan = null;
    if (mode === 'selesai') return;
    pesan = document.createElement('div');
    pesan.setAttribute('role', 'status');
    pesan.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;padding:8px 16px;background:#174c41;color:#fff;text-align:center;font:500 14px/1.5 system-ui;pointer-events:none';
    pesan.textContent = mode === 'perubahan' ? 'Data terbaru tersedia. ' : mode === 'simpan' ? 'Menyimpan…' : mode === 'memperbarui' ? 'Tampilan terakhir — memuat data terbaru…' : 'Membuka halaman…';
    if (muat) {
      var b = document.createElement('button'); b.type = 'button'; b.textContent = 'Muat data terbaru';
      b.style.cssText = 'margin-left:10px;pointer-events:auto'; b.addEventListener('click', muat); pesan.appendChild(b);
    } else {
      main.setAttribute('aria-busy', 'true');
      timer = setTimeout(function () { if (pesan) pesan.textContent = 'Respons belum diterima. Periksa koneksi Anda.'; }, 12000);
    }
    document.body.appendChild(pesan);
  }
  function ambil(url) {
    if (janji.has(url)) return janji.get(url);
    var controller = new AbortController(), batas = setTimeout(function () { controller.abort(); }, 12000);
    var p = fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: { 'X-Portal-Navigasi': '1', 'Accept': 'text/html' } }).then(function (r) {
        if (r.status === 401) return { login: true };
        if (!r.ok || r.redirected || !(r.headers.get('Content-Type') || '').startsWith('text/html')) return null;
        return r.text();
      }).finally(function () { clearTimeout(batas); janji.delete(url); });
    janji.set(url, p); return p;
  }
  function pasang(html, url, dorong, gulung) {
    if (nonce() !== sesi) return false;
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var baru = doc.getElementById('isi-pelanggan');
    if (!baru || doc.body.getAttribute('data-portal-akun') !== akun) return false;
    if (dorong) history.replaceState(Object.assign({}, history.state, { portalScroll: main.scrollTop }), '', alamat());
    doc.querySelectorAll('link[rel=stylesheet][href]').forEach(function (link) {
      var ada = Array.from(document.querySelectorAll('link[rel=stylesheet][href]')).some(function (el) { return el.getAttribute('href') === link.getAttribute('href'); });
      if (!ada) document.head.appendChild(link.cloneNode(true));
    });
    main.innerHTML = baru.innerHTML;
    // Hanya dua skrip baca yang memang diizinkan proyeksi portal. Skrip
    // aksi produksi tidak pernah ikut dijalankan dalam portal pelanggan.
    main.querySelectorAll('[data-share-siap]').forEach(function (el) { el.removeAttribute('data-share-siap'); });
    main.querySelectorAll('script[src]').forEach(function (lama) {
      var sumber = new URL(lama.getAttribute('src'), location.href);
      if (sumber.origin !== location.origin || !['/static/saring-kerja.js', '/static/pdf-penerimaan.js'].includes(sumber.pathname)) return;
      var s = document.createElement('script'); s.src = sumber.href; s.async = false;
      lama.replaceWith(s);
    });
    document.title = doc.title;
    document.querySelectorAll('.portal-sidebar nav a[href],.portal-bawah a[href]').forEach(function (link) {
      var fresh = Array.from(doc.querySelectorAll('.portal-sidebar nav a[href],.portal-bawah a[href]')).find(function (el) { return el.getAttribute('href') === link.getAttribute('href'); });
      var aktif = fresh && fresh.hasAttribute('aria-current');
      if (aktif) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
      if (link.classList.contains('pintu')) link.classList.toggle('pintu--kini', !!aktif);
    });
    var baruMenu = doc.getElementById('menu-pelanggan'), menu = document.getElementById('menu-pelanggan');
    if (menu && baruMenu) menu.toggleAttribute('data-current', baruMenu.hasAttribute('data-current'));
    // Formulir Keluar milik kerangka awal tetap membawa cap pembukanya.
    // Akun dan nonce diperiksa sebelum memasang halaman; bila berganti,
    // navigasi utuh menerbitkan kerangka/formulir baru. Jangan menimpa cap
    // formulir tetap dengan metadata milik konten/detail yang diganti.
    if (dorong) history.pushState({ portal: 1, portalScroll: 0 }, '', url);
    main.scrollTop = gulung || 0;
    main.focus({ preventScroll: true });
    window.dispatchEvent(new Event('portal:halaman'));
    return true;
  }
  var router = pengarah({ waktu: Date.now, sentuhan: function () { return sentuhan; }, ambil: ambil,
    pasang: pasang, status: status, utuh: function (url) { location.assign(url); } });
  window.PORTAL_NAV = { buka: function (url) {
    var u = new URL(url, location.href);
    if (!aman(u) || nonce() !== sesi) { router.bersihkan(); location.assign(u.href); return; }
    return router.pindah(u.pathname + u.search, u.pathname + u.search !== alamat(), 0);
  } };
  router.ingat(alamat(), document.documentElement.outerHTML);
  document.addEventListener('pointerdown', function () { sentuhan++; }, true);
  document.addEventListener('keydown', function () { sentuhan++; }, true);
  document.addEventListener('input', function () { sentuhan++; }, true);
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.target || a.hasAttribute('download') || a.hasAttribute('data-utuh')) return;
    var url = new URL(a.href, location.href);
    if (!aman(url)) return;
    e.preventDefault(); window.PORTAL_NAV.buka(url.href);
  });
  document.addEventListener('submit', function (e) {
    if (e.defaultPrevented || e.target.target) return;
    if ((e.target.method || 'get').toLowerCase() !== 'get') { router.bersihkan(); status('simpan'); return; }
    var url = new URL(e.target.action, location.href);
    if (!aman(url)) return;
    url.search = new URLSearchParams(new FormData(e.target)).toString();
    e.preventDefault(); window.PORTAL_NAV.buka(url.href);
  });
  window.addEventListener('popstate', function (e) {
    if (nonce() !== sesi) { location.reload(); return; }
    router.pindah(alamat(), false, e.state && e.state.portalScroll || 0);
  });
  window.addEventListener('pageshow', function (e) {
    if (!e.persisted) return;
    router.bersihkan();
    if (nonce() !== sesi) { location.reload(); return; }
    router.pindah(alamat(), false, main.scrollTop);
  });
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && nonce() !== sesi) { router.bersihkan(); location.reload(); }
  });
  var hover;
  function siapkan(e) {
    if (document.hidden || (navigator.connection && navigator.connection.saveData)) return;
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a) return;
    var url = new URL(a.href, location.href);
    if (!aman(url) || url.pathname + url.search === alamat() || nonce() !== sesi) return;
    clearTimeout(hover);
    hover = setTimeout(function () { router.siapkan(url.pathname + url.search); }, e.type === 'touchstart' ? 0 : 120);
  }
  document.addEventListener('mouseover', siapkan);
  document.addEventListener('focusin', siapkan);
  document.addEventListener('touchstart', siapkan, { passive: true });
  function siapkanUtama() {
    if (document.hidden || (navigator.connection && navigator.connection.saveData)) return;
    var awal = sentuhan;
    ['/pelanggan/barang-saya', '/pelanggan/jasa-saya'].reduce(function (p, url) {
      return p.then(function () { if (sentuhan === awal && url !== alamat() && nonce() === sesi) return router.siapkan(url); });
    }, Promise.resolve());
  }
  if (window.requestIdleCallback) requestIdleCallback(siapkanUtama, { timeout: 2500 });
  else setTimeout(siapkanUtama, 1500);
})();
