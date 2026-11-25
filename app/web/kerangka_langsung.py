"""Dokumen kerangka native, bukan cache HTML transaksi atau pintu izin baru."""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)
LITERAL = ('/barang-masuk', '/barang-masuk?status=belum',
           '/barang-masuk?status=diterima', '/pekerjaan?tab=berjalan',
           '/pekerjaan', '/pekerjaan?tab=tindakan')
OPSIONAL = ('/jasa',)
BATAS_DOKUMEN_NATIVE = 4 * 1024 * 1024


def kemas_frame(frames: dict[str, str]) -> dict:
    """Intern baris persis, tanpa menormalkan HTML/atribut/urutan script."""
    potongan, indeks, rujukan = [], {}, {}
    for alamat, html in frames.items():
        refs = []
        for baris in html.splitlines(keepends=True):
            nomor = indeks.get(baris)
            if nomor is None:
                nomor = len(potongan)
                indeks[baris] = nomor
                potongan.append(baris)
            refs.append(nomor)
        rujukan[alamat] = refs
    return dict(penyandian='baris-1', potongan=potongan, frames=rujukan)


def alamat_pekerjaan(request: Request) -> tuple[str, ...]:
    """Dua tautan tab native pada filter saat ini, tanpa baca koleksi/aksi.

    Katalog bukan wildcard URL atau data transaksi. Formulir filter yang baru
    diketik tetap mengikuti negosiasi HTML native sebelum GET isi. Tautan ini
    hanya membuat pindah TAB dengan filter yang sudah tampil lebih dini.
    """
    sah = {'tab', 'jenis', 'kepemilikan', 'gudang', 'pemasok', 'cari',
           'pelanggan_id', 'kembali_jasa', 'asal', 'kategori', 'grup', 'informasi',
           'halaman', 'buka', 'nilai'}
    if (request.url.path != '/pekerjaan' or len(request.url.query) > 3000
            or any(k not in sah for k in request.query_params)):
        return ()
    from app.web.layar_pekerjaan import tautan
    return tuple(tautan(request, '/pekerjaan', tab=tab, asal='', kategori='', grup='', informasi='')
                 for tab in ('tindakan', 'berjalan'))


def sah_rujukan(registry: dict) -> bool:
    potongan, frames = registry.get('potongan'), registry.get('frames')
    if (registry.get('versi') != 2 or registry.get('penyandian') != 'baris-1'
            or not isinstance(potongan, list) or not 0 < len(potongan) <= 16384
            or not all(isinstance(s, str) and s for s in potongan)
            or not isinstance(frames, dict) or not set(LITERAL).issubset(frames)
            or len(frames) > len(LITERAL) + len(OPSIONAL) + 2
            or len(set(frames) - set(LITERAL) - set(OPSIONAL)) > 2):
        return False
    from urllib.parse import urlsplit, parse_qs
    for alamat in set(frames) - set(LITERAL):
        if alamat in OPSIONAL:
            continue
        if not isinstance(alamat, str):
            return False
        try:
            u = urlsplit(alamat)
            q = parse_qs(u.query, keep_blank_values=True)
        except (TypeError, ValueError):
            return False
        if (len(alamat) > 4096 or u.scheme or u.netloc or u.fragment
                or u.path != '/pekerjaan' or q.get('tab') not in (['tindakan'], ['berjalan'])
                or any(k in q for k in ('buka', 'nilai', 'halaman'))):
            return False
    for refs in frames.values():
        if (not isinstance(refs, list) or not 0 < len(refs) <= 16384
                or not all(type(i) is int and 0 <= i < len(potongan) for i in refs)
                or sum(len(potongan[i]) for i in refs) > 524288):
            return False
    return True


async def susun_registry(request: Request, akun, *, navigasi=None) -> dict | None:
    from hmu_tampilan import CAP_ASET
    from app.web import csrf
    from app.web.halaman_bertahap import konteks_kerangka, kerangka, penanda_konteks
    from app.web.security import baca_token, NAMA_COOKIE

    # render asli telah memilih nonce. Penyusunan opsional tidak menerbitkan,
    # mengubah scope/akun atau memperbarui sesi pada permintaan sumber.
    if not (request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)):
        return None
    state = dict(request.scope.get('state', {}))
    state.update(menyusun_kerangka_langsung=True, frame_kerangka_langsung=True)
    nav_request = Request({**request.scope, 'state': dict(state)})
    if navigasi is None:
        navigasi = await konteks_kerangka(nav_request, akun)
    frames = {}
    for alamat in dict.fromkeys((*LITERAL, *alamat_pekerjaan(request))):
        path, _, query = alamat.partition('?')
        native = Request({**request.scope, 'path': path, 'raw_path': path.encode(),
                          'query_string': query.encode(), 'state': dict(state)})
        jenis = 'pekerjaan' if path == '/pekerjaan' else 'barang-masuk'
        try:
            response = await kerangka(native, akun, jenis, navigasi=navigasi)
        except HTTPException as error:
            # Tab terfilter tambahan bersifat opsional. Kegagalan tujuan itu
            # tidak membuang kerangka dasar; sesi/akses yang invalid tetap
            # menghentikan registry dan tidak diubah menjadi frame sukses.
            if alamat not in LITERAL and error.status_code in (404, 422, 503):
                continue
            raise
        if response.status_code != 200:
            if alamat not in LITERAL and response.status_code in (404, 422, 503):
                continue
            return None
        frames[alamat] = response.body.decode('utf-8')
    # Pintu Jasa memakai predicate otoritatif yang sama dengan halaman_jasa.
    # Yang dibawa hanya struktur default; saldo/pelanggan tidak dibaca di sini.
    # Operator tetap tidak mendapat kerangka maupun akses endpoint Jasa.
    from app.peran import can_see_financials
    if can_see_financials(akun.user):
        native = Request({**request.scope, 'path': '/jasa', 'raw_path': b'/jasa',
                          'query_string': b'', 'state': dict(state)})
        try:
            response = await kerangka(native, akun, 'jasa', navigasi=navigasi)
            if response.status_code == 200:
                frames['/jasa'] = response.body.decode('utf-8')
            elif response.status_code in (401, 403):
                raise HTTPException(response.status_code, 'Konteks kerangka Jasa tidak tersedia.')
            else:
                log.warning('Kerangka Jasa opsional tidak tersedia: HTTP %s', response.status_code)
        except HTTPException as error:
            # Perubahan sesi/hak tidak disamarkan sebagai kegagalan presentasi.
            if error.status_code in (401, 403):
                raise
            log.warning('Kerangka Jasa opsional tidak tersedia: HTTP %s', error.status_code)
        except Exception as error:
            # Jangan menjatuhkan enam tujuan dasar karena satu template opsional.
            # Nama kelas cukup; isi exception bisa memuat parameter pengguna.
            log.warning('Kerangka Jasa opsional tidak tersedia: %s', type(error).__name__)
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    sesi = csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)),
                          request.cookies.get('produksi_lihat', ''))
    return dict(versi=2, konteks=penanda_konteks(nav_request, akun), cap=CAP_ASET,
                sesi=sesi, **kemas_frame(frames))


async def lengkapi_dokumen(request: Request, response):
    """Hanya dokumen HTML native penuh; stream/partial/API tidak disentuh.

    Header asli (termasuk beberapa Set-Cookie), background dan status tetap
    milik respons native. Registry opsional gagal tertutup ke navigasi lama.
    """
    from app.web.portal.scope import is_customer_read
    akun = getattr(request.state, 'akun', None)
    if (request.method != 'GET' or response.status_code != 200 or not akun
            or not getattr(request.state, 'dokumen_native_kerangka', False)
            or request.url.path.startswith(('/api/', '/miniapp/', '/pelanggan', '/static/'))
            or request.headers.get('X-Pindah') == '1'
            or request.headers.get('X-Barang-Masuk-Cari') == '1'
            or is_customer_read(request)
            or getattr(request.state, 'menyusun_kerangka_langsung', False)
            or response.headers.get('content-disposition')
            or not response.headers.get('content-type', '').startswith('text/html')
            or response.headers.get('content-encoding')):
        return response
    # MonitoringHTTP menyisipkan skrip pada HTML native dan sengaja melepas
    # Content-Length. Marker ukuran hanya berasal dari renderer aplikasi;
    # header request atau panjang jaringan bukan bukti stream boleh dibaca.
    panjang = getattr(request.state, 'panjang_html_native_kerangka', None)
    if type(panjang) is not int or not 0 < panjang <= BATAS_DOKUMEN_NATIVE:
        return response
    iterator = response.body_iterator
    chunks, ukuran = [], 0
    async for part in iterator:
        chunks.append(part)
        ukuran += len(part.encode() if isinstance(part, str) else part)
        if ukuran > BATAS_DOKUMEN_NATIVE:
            # Wrapper bisa menambah byte. Batas terlampaui bukan alasan
            # mengirim HTML terpotong atau membuang sisa stream asli.
            async def asli():
                try:
                    for chunk in chunks:
                        yield chunk
                    async for chunk in iterator:
                        yield chunk
                finally:
                    tutup = getattr(iterator, 'aclose', None)
                    if tutup is not None:
                        await tutup()
            response.body_iterator = asli()
            return response
    body = b''.join(part.encode() if isinstance(part, str) else part for part in chunks)
    if b'<!-- isi-halaman:akhir -->' in body and b'data-pindah-konteks=' in body:
        try:
            from app.web.halaman_bertahap import konteks_kerangka
            nav_request = Request({**request.scope, 'state': dict(request.scope.get('state', {}))})
            navigasi = await konteks_kerangka(nav_request, akun)
            registry = await susun_registry(request, akun, navigasi=navigasi)
            if registry:
                # Penyusunan opsional harus selesai utuh sebelum badan native
                # diubah. Kegagalan template/shape pun tetap default-off.
                if (not sah_rujukan(registry)
                        or not all(isinstance(registry.get(k), str) and registry[k]
                                   for k in ('konteks', 'cap', 'sesi'))
                        or body.count(b'</body>') != 1):
                    raise ValueError('Bentuk registry belum tersedia')
                from app.web.tampilan import templates
                stok = None
                try:
                    from app.web.stok_kerangka_langsung import susun as susun_stok
                    stok = await susun_stok(request, akun, navigasi=navigasi)
                except Exception as error:
                    if isinstance(error, HTTPException) and error.status_code in (401, 403):
                        raise
                    # Kegagalan keluarga opsional tidak merusak enam frame
                    # wajib. Tidak mencetak parameter atau meniru frame sukses.
                    log.warning('Kerangka Stok belum tersedia (%s)', type(error).__name__)
                riwayat = None
                try:
                    from app.web.riwayat_bertahap import susun as susun_riwayat
                    riwayat = await susun_riwayat(request, akun, navigasi=navigasi)
                except Exception as error:
                    if isinstance(error, HTTPException) and error.status_code in (401, 403):
                        raise
                    log.warning('Kerangka Riwayat belum tersedia (%s)', type(error).__name__)
                beranda = None
                try:
                    from app.web.beranda_bertahap import susun as susun_beranda
                    beranda = await susun_beranda(request, akun, navigasi=navigasi)
                except Exception as error:
                    if isinstance(error, HTTPException) and error.status_code in (401, 403):
                        raise
                    log.warning('Kerangka Beranda belum tersedia (%s)', type(error).__name__)
                host = templates.get_template('_kerangka_langsung_registry.html').render(registry=registry, stok=stok, riwayat=riwayat, beranda=beranda).encode()
                siap = body.replace(b'</body>', host + b'\n</body>', 1)
                body = siap
        except Exception as e:
            # Hanya tambahan presentasi ini yang opsional. Handler native,
            # pembacaan stream dan CancelledError tetap di luar penangkap.
            log.warning('Metadata kerangka langsung belum tersedia (%s); navigasi native dipertahankan', type(e).__name__)
    async def isi():
        yield body
    response.body_iterator = isi()
    response.headers['content-length'] = str(len(body))
    return response
