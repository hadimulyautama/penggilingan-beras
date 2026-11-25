"""Adapter baca bertahap untuk dua halaman, bukan pembaca stok baru.

Kerangka hanya berisi struktur dan pilihan navigasi yang sudah diizinkan.
Isi tetap disusun rute lama dengan aktor efektif yang diperiksa ulang pada
setiap GET. Penanda di bawah mengikat hasil baca ke sesi/konteks pembukanya;
penanda bukan izin dan tidak pernah dipakai melewati penjaga rute lama.
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.web.security import butuh_akun

router = APIRouter(tags=["webapp"])
ALAMAT = {"pekerjaan": "/pekerjaan", "stok": "/stok", "jasa": "/jasa", "barang-masuk": "/barang-masuk", "beranda": "/"}
from app.web.riwayat_bertahap import TUJUAN as RIWAYAT_TUJUAN
ALAMAT.update({kind: data['path'] for kind, data in RIWAYAT_TUJUAN.items()})


def memakai_kerangka(request: Request, jenis: str) -> bool:
    from app.web.portal.scope import is_customer_read

    return (not getattr(request.state, "isi_halaman_bertahap", False)
            # Negosiasi renderer saja, bukan izin. Pemanggil HTML lama dan
            # refresh X-Pindah tetap menerima data native. Browser document
            # atau permintaan kerangka eksplisit dapat membaca struktur dulu.
            and (request.headers.get("X-Kerangka-Halaman") == "1"
                 or request.headers.get("X-Pindah") != "1"
                 and request.headers.get("Sec-Fetch-Mode") == "navigate"
                 and request.headers.get("Sec-Fetch-Dest") in {"document", "empty"})
            and not is_customer_read(request)
            and not (jenis == "barang-masuk" and request.headers.get("X-Barang-Masuk-Cari") == "1")
            and request.url.path == ALAMAT[jenis])


def penanda_konteks(request: Request, akun) -> str:
    from hmu_tampilan import CAP_ASET
    from app.web import csrf
    from app.web.security import NAMA_COOKIE, baca_token

    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, "csrf", None)
    if not nonce:
        nonce = csrf.terbitkan_baru()
        request.state.csrf = nonce
    sesi = csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)),
                          request.cookies.get("produksi_lihat", ""))
    hak = getattr(request.state, "akses_produk", None)
    nilai = [sesi, akun.id, akun.user.id, akun.user.role,
             getattr(akun.user, "default_warehouse_id", None),
             getattr(request.state, "view", "tamu"),
             getattr(hak, "company_id", None), CAP_ASET]
    return hashlib.sha256(json.dumps(nilai, ensure_ascii=True).encode()).hexdigest()


def penanda(request: Request, akun, jenis: str) -> str:
    if jenis in ('stok', 'beranda') or jenis in RIWAYAT_TUJUAN:
        # Korelasi baca, bukan izin/tanda tangan. Struktur kosong dapat
        # mengikat filter baru di browser; GET tetap memeriksa aktor native.
        return penanda_konteks(request, akun) + '|' + ALAMAT[jenis] + (
            '?' + request.url.query if request.url.query else '')
    nilai = [penanda_konteks(request, akun), ALAMAT[jenis], request.url.query]
    return hashlib.sha256(json.dumps(nilai).encode()).hexdigest()


def _pilihan(nama, label, nilai, opsi, **tambahan):
    return dict(name=nama, label=label, value=nilai,
                options=[dict(value=k, label=n) for k, n in opsi], **tambahan)


def kolom_daftar(jenis: str, mutu: bool = False):
    if jenis == 'tindakan':
        return ["Kode & pekerjaan", "Kepemilikan", "Status", "Ringkasan", "Tindakan"]
    if jenis == 'pekerjaan':
        return ["Kode & proses", "Kepemilikan", "Status / mulai", "Ringkasan", "Tindakan"]
    if jenis == 'bahan':
        return (["Lot / kode · tanggal", "Pemilik", "Letak", "Status"]
                + (["Kadar air", "Broken", "Susut", "Nilai kualitas"] if mutu else [])
                + ["Kondisi", "Berat tersedia", "Tindakan"])
    if jenis == 'produk':
        return ["Produk", "Hasil sosoh", "Keluar", "Dikemas / tercatat", "Curah / belum dikemas", "Sisa di gudang", "Tindakan"]
    return ["No.", "Merek", "Jenis karung", "Ukuran", "Jumlah", "Status / tindakan"]


async def konteks_kerangka(request: Request, akun):
    """Metadata izin/menu yang sama; satu pembacaan untuk beberapa frame.

    Tidak memanggil pembaca daftar, stok atau jumlah. Ini bukan cache data dan
    bukan perubahan izin; GET isi halaman tetap memeriksa akun saat digunakan.
    """
    from app.database import SessionLocal
    from app.services.berjalan import Berjalan
    from app.services.setelan import fitur_mutu
    from app.services.cakupan_fasilitas import boleh_jenis
    from app.web.api import _is_g1_operator
    from app.peran import can_see_financials

    # Gunakan struktur menu native tanpa membaca koleksi pekerjaan. Daftar
    # kosong hanya menyediakan bentuk; jumlah tab tetap ditandai belum dibaca.
    async with SessionLocal() as db:
        navigasi = Berjalan(mutu_aktif=await fitur_mutu(db))
        navigasi.pintu_produk = not (await _is_g1_operator(akun.user)
                                      and not can_see_financials(akun.user))
        navigasi.boleh_riwayat_sosoh = await boleh_jenis(db, akun.user, 'penyosohan')
        navigasi.boleh_riwayat_g1 = (await boleh_jenis(db, akun.user, 'penggilingan')
                                   or await boleh_jenis(db, akun.user, 'pengeringan'))
    konteks = navigasi.lencana()
    if getattr(request.state, 'view', 'tamu') == 'tamu':
        from hmu_identitas import peran as P
        if P.operator_saja(akun.user.role):
            from app.web.akses import hak_view
            from app.services.cakupan_fasilitas import boleh_baca_stok
            async with SessionLocal() as db:
                izin_transfer = await boleh_baca_stok(db, akun.user)
            konteks['AKSES'] = {**hak_view('tamu'), 'transfer': izin_transfer}
    return konteks


async def kerangka(request: Request, akun, jenis: str, *, navigasi=None, stok_lokasi=None):
    from app.web.tampilan import render

    q = request.query_params
    data = dict(kind=jenis, title="Pekerjaan" if jenis == "pekerjaan" else "Stok",
                stamp=penanda(request, akun, jenis),
                data_url="/api/halaman-bertahap/" + jenis + ("?" + request.url.query if request.url.query else ""))
    konteks = dict(layar=jenis, SHELL=data,
                   **(await konteks_kerangka(request, akun) if navigasi is None else navigasi))
    if jenis == 'barang-masuk':
        from app.web.barang_masuk_bertahap import kerangka as kerangka_masuk
        return await kerangka_masuk(request, akun, konteks)
    if jenis == 'jasa':
        from app.web.jasa_bertahap import kerangka as kerangka_jasa
        return await kerangka_jasa(request, akun, konteks)
    if jenis == "pekerjaan":
        from app.services.kelompok_kerja import JENIS_KERJA
        from app.web.layar_pekerjaan import pilihan, tautan
        from app.web.layar import GUDANG

        href = lambda **p: tautan(request, "/pekerjaan", **p)
        tab = pilihan(request, "tab", {"tindakan", "berjalan"}, "tindakan")
        tipe = pilihan(request, "jenis", dict(JENIS_KERJA))
        gudang = pilihan(request, "gudang", {g for g, _, _ in GUDANG})
        pemilik = pilihan(request, "kepemilikan", {"jasa", "pabrik"})
        data.update(
            search=dict(name="cari", label="Cari nama, kode atau plat", value=q.get("cari", "")[:200]),
            reset_url=href(jenis="", kepemilikan="", gudang="", pemasok=""),
            columns=kolom_daftar('pekerjaan' if tab == 'berjalan' else 'tindakan'),
            tab=tab, scope="Pekerjaan dalam cakupan akses dan gudang kerja Anda",
            filtered=any(q.get(k) for k in ("jenis", "kepemilikan", "gudang", "pemasok", "cari", "pelanggan_id", "asal", "kategori", "grup", "informasi")),
            tabs=[dict(label=n, href=href(tab=k, asal="", kategori="", grup="", informasi=""), active=k == tab, boleh=True)
                  for k, n in [("tindakan", "Perlu tindakan"), ("berjalan", "Berjalan")]]
                 + [dict(label="Pekerjaan lain", href="/pekerjaan/catat-lain?" + urlencode({"kembali": href()}), active=False, boleh=True)],
            filters=[_pilihan("jenis", "Jenis pekerjaan", tipe, [("", "Semua jenis"), *JENIS_KERJA]),
                     _pilihan("kepemilikan", "Kepemilikan", pemilik, [("", "Semua kepemilikan"), ("pabrik", "Milik pabrik"), ("jasa", "Jasa")]),
                     _pilihan("gudang", "Gudang", gudang, [("", "Semua gudang"), *((g, nama) for g, nama, _ in GUDANG)]),
                     _pilihan("pemasok", "Nama pihak", q.get("pemasok", ""), [(q.get("pemasok", ""), q.get("pemasok") or "Semua nama")],
                              disabled=True, reason="Pilihan nama tersedia setelah daftar selesai dibaca.")])
        # Navigasi Pekerjaan memakai helper existing, tetapi jumlah belum
        # diketahui; jangan menggambar nol sebagai hasil pembacaan.
        konteks.update(tab=tab, href=href, total_tindakan="…", total_jalan="…",
                       jenis=tipe, gudang=gudang, nama_saring=[], pelanggan_saring="",
                       per_jenis=[(key, nama, "…") for key, nama in JENIS_KERJA],
                       kerangka_pekerjaan=True)
    else:
        from app.database import SessionLocal
        from app.services.cakupan_fasilitas import boleh_baca_stok
        from app.services.setelan import fitur_mutu
        from app.web.stok_navigasi import HALAMAN, siapkan

        tab, pemilik = q.get("tab", "bahan"), q.get("pemilik", "semua")
        if tab not in {"bahan", "produk", "karung"} or pemilik not in {"semua", "pabrik", "jasa"}:
            raise HTTPException(422, "Pilihan stok tidak dikenal.")
        async with SessionLocal() as db:
            # Produk/karung sudah menolak tanpa gudang aktif pada pembaca
            # native. Bahan mempertahankan kontrak native (daftar kosong).
            if tab != "bahan" and not await boleh_baca_stok(db, akun.user):
                raise HTTPException(403, "Gudang kerja aktif diperlukan untuk membaca stok.")
            mutu = await fitur_mutu(db) if tab == "bahan" else False
        nama = next(k for k, v in HALAMAN.items() if v == (tab, "jasa" if pemilik == "jasa" else "pabrik"))
        awal = dict(lot=[], tempat=[], daftar=[], karung=[], semua_kepemilikan=pemilik == "semua")
        await siapkan(request, nama, awal, metadata_navigasi=stok_lokasi)
        nav = awal["STOK_NAV"]
        columns = kolom_daftar(tab, mutu)
        from app.web.stok_navigasi import alamat
        data.update(tab=tab, columns=columns, scope=nav["cakupan"] + " · " + nav["lokasi"],
                    stock_nav=nav, stock_owner_allowed=awal.get('BOLEH_KEPEMILIKAN', False),
                    search=dict(name="cari", label="Cari nama atau kode stok", value=q.get("cari", "")[:200]),
                    reset_url=alamat(tab, "semua", cari=q.get("cari", "")[:200]),
                    filtered=pemilik != "semua" or any(q.get(k) for k in ("gudang", "cari", "pelanggan_id")),
                    tabs=[dict(label=t["nama"], href=t["href"], active=t["kunci"] == tab, boleh=t["boleh"]) for t in nav["tab"]],
                    filters=[_pilihan("pemilik", "Kepemilikan", pemilik, [(t["kunci"], t["nama"]) for t in nav["milik"]]),
                             _pilihan("gudang", "Gudang", q.get("gudang", ""), [("", "Semua gudang")] + [(t["kunci"], t["nama"]) for t in nav["lokasi_pil"] if t["kunci"]]),
                             _pilihan("pelanggan_id", "Pelanggan", str(nav["pelanggan_id"] or ""), [("", "Semua pelanggan")] + [(str(k), n) for k, n in nav["pelanggan"]],
                                      disabled=True, reason="Pilihan pelanggan tersedia setelah stok selesai dibaca.")])
    fields = {f["name"] for f in data["filters"]} | {"cari", "halaman", "buka", "nilai"}
    data["hidden"] = {k: v for k, v in q.items() if k not in fields}
    data["hidden"]["tab"] = data["tab"]
    # Pilihan remote sementara dinonaktifkan, bukan dibuang dari konteks
    # saat pengguna mencari sebelum opsi selesai dibaca.
    data["hidden"].update({f["name"]: f["value"] for f in data["filters"] if f.get("disabled") and f["value"]})
    response = render(request, "halaman_bertahap.html", **konteks)
    if jenis == 'stok':
        # Header native dipakai dalam root baca, bukan STOK_NAV global yang
        # akan memasang controller/filter baris sebelum data tersedia.
        import re
        from html import escape
        response.body = re.sub(
            rb'\bdata-sk-cetak(?:="")?(?=[\s>])',
            b'data-sk-cetak="" disabled aria-describedby="shell-cetak-alasan"', response.body)
        response.body = re.sub(
            rb'(<select class="fld" name="pelanggan_id")(?: disabled)?(>)',
            rb'\1 disabled aria-describedby="shell-pelanggan-alasan"\2', response.body)
        response.body = response.body.replace(
            b'<p class="bantu" data-stok-pelanggan-status role="status" hidden></p>',
            b'<p class="bantu" id="shell-pelanggan-alasan" data-stok-pelanggan-status role="status">Pilihan pelanggan tersedia setelah stok selesai dibaca.</p>')
        if nav['pelanggan_id']:
            marker = b'<form class="sk-form-filter" method="get" action="/stok">'
            response.body = response.body.replace(marker, marker + (
                '<input type="hidden" name="pelanggan_id" value="'
                + escape(str(nav['pelanggan_id']), quote=True) + '">').encode())
        response.headers['content-length'] = str(len(response.body))
    if jenis == 'pekerjaan':
        response.body = response.body.replace(
            b'data-lk-cetak=""',
            b'data-lk-cetak="" disabled aria-describedby="shell-cetak-alasan"')
        response.body = response.body.replace(
            b'data-lk-buka="pk-panduan"',
            b'data-lk-buka="pk-panduan" aria-controls="pk-panduan"')
        response.headers['content-length'] = str(len(response.body))
    response.headers["Cache-Control"] = "private, no-store"
    return response


async def _isi(request: Request, akun, jenis: str):
    if jenis not in ALAMAT:
        raise HTTPException(404, "Halaman tidak dikenal.")
    if jenis in ('barang-masuk', 'beranda') or jenis in RIWAYAT_TUJUAN:
        from app.web.portal.scope import is_customer_read
        if is_customer_read(request):
            raise HTTPException(403, 'Gunakan halaman portal sesuai cakupan pelanggan.')
    from starlette.requests import Request as NativeRequest

    scope = {**request.scope, "path": ALAMAT[jenis], "raw_path": ALAMAT[jenis].encode(),
             "state": {**request.scope.get("state", {}), "isi_halaman_bertahap": True}}
    native = NativeRequest(scope)
    if jenis == 'beranda':
        from app.main import beranda
        response = await beranda(native)
    elif jenis == "pekerjaan":
        from app.web.layar_pekerjaan import halaman_pekerjaan
        response = await halaman_pekerjaan(native, akun)
    elif jenis == 'barang-masuk':
        from app.web.layar_pekerjaan import halaman_barang_masuk
        response = await halaman_barang_masuk(native, akun)
    elif jenis == 'jasa':
        from app.web.layar_jasa import halaman_jasa
        response = await halaman_jasa(native, akun)
    elif jenis in RIWAYAT_TUJUAN:
        if jenis == 'riwayat-sosoh':
            from app.web.layar_sosoh import halaman_riwayat_sosoh
            response = await halaman_riwayat_sosoh(native, akun)
        else:
            from app.web.layar_riwayat import halaman_riwayat_giling, halaman_riwayat_pengeringan
            response = await (halaman_riwayat_giling if jenis == 'riwayat-giling' else halaman_riwayat_pengeringan)(native, akun)
    else:
        from app.web.layar_stok import halaman_stok
        response = await halaman_stok(native, akun)
    if jenis == 'barang-masuk' and response.status_code == 503:
        return native, response
    if response.status_code != 200:
        raise HTTPException(409, "Tujuan halaman berubah. Buka kembali halaman dari menu.")
    response.headers["Cache-Control"] = "private, no-store"
    return native, response


@router.get("/api/halaman-bertahap/{jenis}")
async def isi_halaman(jenis: str, request: Request, akun=Depends(butuh_akun)):
    native, response = await _isi(request, akun, jenis)
    return JSONResponse(dict(stamp=penanda(native, akun, jenis), html=response.body.decode("utf-8")),
                        status_code=response.status_code if jenis == "barang-masuk" else 200,
                        headers={"Cache-Control": "private, no-store"})


@router.get("/api/halaman-bertahap/stok/html")
async def pilihan_pelanggan(request: Request, akun=Depends(butuh_akun)):
    # Consumer filter stok lama membaca HTML option. Adapter ini hanya
    # mengganti alamat GET consumer tersebut pada dua halaman yang diadopsi.
    native, response = await _isi(request, akun, "stok")
    response.headers["X-Halaman-Konteks"] = penanda_konteks(native, akun)
    return response
