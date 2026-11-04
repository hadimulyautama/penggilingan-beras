/* Navigasi baca portal: cache hanya di memori tab, terpisah akun, tanpa POST. */
(function () {
  'use strict';
  function pengarah(ops) {
    var cache = new Map(), urutan = 0, menavigasi = false, memperbarui = false;
    function ingat(url, html) {
      if (!html) return;
      cache.delete(url); cache.set(url, { html: html, saat: ops.waktu() });
      if (cache.size > 8) cache.delete(cache.keys().next().value);
    }
    function terakhir(url) {
      var item = cache.get(url);
      return item && ops.waktu() - item.saat < 30000 ? item.html : null;
    }
    async function pindah(url, dorong, gulung, judul) {
      var nomor = ++urutan, lama = terakhir(url), sentuhan;
      if (lama && !ops.pasang(lama, url, dorong, gulung)) { ops.utuh(url); return; }
      var bertahap = !lama && ops.kerangka ? ops.kerangka(url, dorong, gulung, judul) : false;
      sentuhan = ops.sentuhan(); menavigasi = true;
      ops.status(lama ? 'memperbarui' : 'memuat');
      var baru;
      try { baru = await ops.ambil(url); } catch (_) { baru = null; }
      if (nomor !== urutan) return;
      menavigasi = false;
      if (baru && typeof baru.html === 'string') { url = baru.url; baru = baru.html; }
      if (!baru || typeof baru !== 'string') {
        if (baru && baru.login) { ops.utuh('/pelanggan/masuk'); }
        else if (baru && baru.utuh) { ops.utuh(baru.utuh); }
        else if (bertahap && ops.gagal) { ops.gagal(url, function () { return pindah(url, false, gulung, judul); }); }
        else ops.utuh(url);
        return;
      }
      ingat(url, baru);
      // Respons yang sama tidak perlu mengganti rincian yang sudah dibuka
      // atau meminta pengguna memuat ulang halaman yang tidak berubah.
      if (lama === baru) { ops.status('selesai'); return; }
      if (lama && sentuhan !== ops.sentuhan()) {
        // Navigasi dari cache juga mengikuti pembaruan tanpa meminta ketukan.
        // Bila pengguna mulai mengisi filter, denyut berikutnya melanjutkan
        // sesudah fokus dilepas; isian dan posisi tidak ditimpa.
        if (!ops.siap || ops.siap()) {
          if (!ops.pasang(baru, url, false, gulung, true)) { ops.utuh(url); return; }
        }
        ops.status('selesai'); return;
      }
      if (!ops.pasang(baru, url, lama || bertahap ? false : dorong, gulung)) { ops.utuh(url); return; }
      ops.status('selesai');
    }
    return {
      pindah: pindah, ingat: ingat, bersihkan: function () { cache.clear(); ++urutan; menavigasi = false; },
      perbarui: async function (url, gulung) {
        if (menavigasi || memperbarui) return;
        memperbarui = true;
        var nomor = urutan, baru;
        try {
          try { baru = await ops.ambil(url); } catch (_) { baru = null; }
          if (nomor !== urutan) return;
          if (baru && baru.login) { cache.clear(); ops.utuh('/pelanggan/masuk'); return; }
          if (baru && typeof baru.html === 'string') { url = baru.url; baru = baru.html; }
          if (!baru || typeof baru !== 'string') {
            ops.status('tertunda'); return;
          }
          if (ops.siap && !ops.siap()) return;
          if (!ops.pasang(baru, url, false, gulung, true)) { cache.clear(); ops.utuh(url); return; }
          ingat(url, baru); ops.status('selesai');
        } finally { memperbarui = false; }
      },
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
  function kerangka(url, dorong, gulung, judul) {
    if (nonce() !== sesi) return false;
    if (dorong) {
      history.replaceState(Object.assign({}, history.state, { portalScroll: main.scrollTop }), '', alamat());
      history.pushState({ portal: 1, portalScroll: 0 }, '', url);
    }
    var nom = judul || 'Halaman';
    main.innerHTML = '<section class="halaman-memuat" aria-busy="true"><h1></h1><p role="status" aria-live="polite">Memuat data…</p><div class="halaman-memuat__baris" aria-hidden="true"><i></i><i></i><i></i></div></section>';
    main.querySelector('h1').textContent = nom;
    document.title = nom + ' · PadiFlow Pelanggan';
    var path = new URL(url, location.origin).pathname;
    document.querySelectorAll('.portal-sidebar nav a[href],.portal-bawah a[href]').forEach(function (link) {
      var p = new URL(link.href, location.origin).pathname;
      var aktif = p === path || p !== '/pelanggan/' && path.indexOf(p + '/') === 0;
      if (aktif) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
      if (link.classList.contains('pintu')) link.classList.toggle('pintu--kini', aktif);
    });
    var menu = document.getElementById('menu-pelanggan');
    if (menu) {
      if (document.querySelector('.portal-bawah a[aria-current]')) menu.removeAttribute('data-current');
      else menu.setAttribute('data-current', 'true');
    }
    main.scrollTop = gulung || 0;
    main.focus({ preventScroll: true });
    window.dispatchEvent(new Event('portal:halaman'));
    return true;
  }
  function gagal(url, ulangi) {
    status('selesai');
    main.innerHTML = '<section class="halaman-memuat"><h1>Data belum dapat dimuat</h1><p role="alert">Periksa koneksi Anda, lalu coba lagi.</p><button class="btn" type="button">Coba lagi</button> <a class="btn" data-utuh>Muat ulang halaman</a></section>';
    main.querySelector('button').addEventListener('click', ulangi);
    main.querySelector('a').href = url;
  }
  function status(mode, muat) {
    if (timer) clearTimeout(timer);
    if (pesan) pesan.remove();
    main.removeAttribute('aria-busy');
    pesan = null;
    if (mode === 'selesai') return;
    if (mode === 'tertunda') { mode = 'gagal'; muat = function () { segarkan(true); }; }
    if (mode === 'memuat' && main.querySelector('.halaman-memuat')) {
      main.setAttribute('aria-busy', 'true'); return;
    }
    function tampilkan() {
      var tempat = document.querySelector('.portal-top-identitas');
      if (!tempat) return;
      pesan = document.createElement('div');
      pesan.className = 'portal-status-navigasi';
      pesan.setAttribute('role', 'status');
      pesan.setAttribute('aria-live', 'polite');
      pesan.textContent = mode === 'gagal' ? 'Data belum berhasil diperbarui. Tampilan masih memakai data sebelumnya. ' : mode === 'perubahan' ? 'Data terbaru tersedia. ' : mode === 'simpan' ? 'Menyimpan…' : mode === 'memperbarui' ? 'Memperbarui data…' : 'Membuka halaman…';
      if (muat) {
        var b = document.createElement('button'); b.type = 'button'; b.textContent = 'Muat data terbaru';
        b.addEventListener('click', muat); pesan.appendChild(b);
      }
      tempat.appendChild(pesan);
    }
    if (muat) { tampilkan(); return; }
    main.setAttribute('aria-busy', 'true');
    // Navigasi cepat tetap tenang. Status hanya muncul bila pengguna menunggu,
    // dalam kepala halaman; tidak menutupi isi atau mewarnai status bar HP.
    timer = setTimeout(function () {
      tampilkan();
      timer = setTimeout(function () { if (pesan) pesan.textContent = 'Respons belum diterima. Periksa koneksi Anda.'; }, 10800);
    }, 1200);
  }
  function ambil(url) {
    if (janji.has(url)) return janji.get(url);
    var controller = new AbortController(), batas = setTimeout(function () { controller.abort(); }, 12000);
    var p = fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: { 'X-Portal-Navigasi': '1', 'Accept': 'text/html' } }).then(function (r) {
        if (r.status === 401) return { login: true };
        if (!r.ok || !(r.headers.get('Content-Type') || '').startsWith('text/html')) return { utuh: r.url || url };
        if (r.redirected) {
          var cible = new URL(r.url, location.href);
          if (cible.origin === location.origin && cible.pathname === '/pelanggan/masuk') return { login: true };
          if (!aman(cible)) return { utuh: r.url || url };
          return r.text().then(function (html) { return { html: html, url: cible.pathname + cible.search }; });
        }
        return r.text();
      }).finally(function () { clearTimeout(batas); janji.delete(url); });
    janji.set(url, p); return p;
  }
  function pasang(html, url, dorong, gulung, otomatis) {
    if (nonce() !== sesi) return false;
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var baru = doc.getElementById('isi-pelanggan');
    if (!baru || doc.body.getAttribute('data-portal-akun') !== akun) return false;
    var keadaan = otomatis && window.KEADAAN_BACA ? KEADAAN_BACA.ambil(main) : null;
    if (otomatis && main.innerHTML === baru.innerHTML) return true;
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
    else if (url !== alamat()) history.replaceState({ portal: 1, portalScroll: gulung || 0 }, '', url);
    if (otomatis) { if (keadaan) KEADAAN_BACA.pulihkan(main,keadaan); }
    else { main.scrollTop = gulung || 0; main.focus({ preventScroll: true }); }
    window.dispatchEvent(new Event('portal:halaman'));
    return true;
  }
  var router = pengarah({ waktu: Date.now, sentuhan: function () { return sentuhan; }, ambil: ambil,
    pasang: pasang, kerangka: kerangka, gagal: gagal, status: status, siap: siapSegar, utuh: function (url) { location.assign(url); } });
  window.PORTAL_NAV = { buka: function (url, judul) {
    var u = new URL(url, location.href);
    if (!aman(u) || nonce() !== sesi) { router.bersihkan(); location.assign(u.href); return; }
    return router.pindah(u.pathname + u.search, u.pathname + u.search !== alamat(), 0, judul);
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
    e.preventDefault(); window.PORTAL_NAV.buka(url.href, a.textContent.trim().replace(/\s+/g, ' ').slice(0, 90));
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
  var segarTimer = null, segarTerakhir = 0;
  function siapSegar() {
    var aktif = document.activeElement, pilihan = window.getSelection && window.getSelection();
    return !document.hidden && !(aktif && main.contains(aktif) && aktif.matches('input,textarea,select,button,[contenteditable=true]'))
      && !(pilihan && !pilihan.isCollapsed && main.contains(pilihan.anchorNode));
  }
  async function segarkan(paksa) {
    clearTimeout(segarTimer);
    if (document.hidden) return;
    if (nonce() !== sesi) { router.bersihkan(); location.reload(); return; }
    if (siapSegar() && (paksa || Date.now() - segarTerakhir >= 3000)) {
      segarTerakhir = Date.now();
      await router.perbarui(alamat(), main.scrollTop);
    }
    clearTimeout(segarTimer);
    segarTimer = setTimeout(function () { segarkan(false); }, 30000);
  }
  document.addEventListener('visibilitychange', function () {
    clearTimeout(segarTimer);
    if (!document.hidden) segarkan(true);
  });
  window.addEventListener('focus', function () { segarkan(false); });
  window.addEventListener('online', function () { segarkan(true); });
  segarTimer = setTimeout(function () { segarkan(false); }, 30000);
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
