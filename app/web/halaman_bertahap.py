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
ALAMAT = {"pekerjaan": "/pekerjaan", "stok": "/stok"}


def memakai_kerangka(request: Request, jenis: str) -> bool:
    from app.web.portal.scope import is_customer_read

    return (not getattr(request.state, "isi_halaman_bertahap", False)
            # PINDAH menyegarkan/membandingkan HTML data pada latar. Header
            # hanya memilih renderer; autentikasi dan pembaca tetap sama.
            and request.headers.get("X-Pindah") != "1"
            and not is_customer_read(request)
            and request.url.path == ALAMAT[jenis]
            and (jenis != "pekerjaan" or request.query_params.get("tab") == "berjalan"))


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
    nilai = [penanda_konteks(request, akun), ALAMAT[jenis], request.url.query]
    return hashlib.sha256(json.dumps(nilai).encode()).hexdigest()


def _pilihan(nama, label, nilai, opsi, **tambahan):
    return dict(name=nama, label=label, value=nilai,
                options=[dict(value=k, label=n) for k, n in opsi], **tambahan)


async def kerangka(request: Request, akun, jenis: str):
    from app.web.nav import _KOSONG
    from app.web.tampilan import render

    q = request.query_params
    data = dict(kind=jenis, title="Pekerjaan" if jenis == "pekerjaan" else "Stok",
                stamp=penanda(request, akun, jenis),
                data_url="/api/halaman-bertahap/" + jenis + ("?" + request.url.query if request.url.query else ""))
    konteks = dict(layar=jenis, SHELL=data, **_KOSONG())
    if jenis == "pekerjaan":
        from app.services.kelompok_kerja import JENIS_KERJA
        from app.web.layar_pekerjaan import pilihan, tautan

        href = lambda **p: tautan(request, "/pekerjaan", **p)
        tipe = pilihan(request, "jenis", dict(JENIS_KERJA))
        gudang = pilihan(request, "gudang", {"g1", "g2"})
        pemilik = pilihan(request, "kepemilikan", {"jasa", "pabrik"})
        data.update(
            search=dict(name="cari", label="Cari nama, kode atau plat", value=q.get("cari", "")[:200]),
            reset_url=href(jenis="", kepemilikan="", gudang="", pemasok=""),
            columns=["Kode & proses", "Kepemilikan", "Status / mulai", "Ringkasan", "Tindakan"],
            tab="berjalan", scope="Proses dalam cakupan akses dan gudang kerja Anda",
            filtered=any(q.get(k) for k in ("jenis", "kepemilikan", "gudang", "pemasok", "cari", "pelanggan_id", "asal", "kategori", "grup", "informasi")),
            tabs=[dict(label=n, href=href(tab=k, asal="", kategori="", grup="", informasi=""), active=k == "berjalan", boleh=True)
                  for k, n in [("tindakan", "Perlu tindakan"), ("berjalan", "Berjalan")]]
                 + [dict(label="Pekerjaan lain", href="/pekerjaan/catat-lain?" + urlencode({"kembali": href()}), active=False, boleh=True)],
            filters=[_pilihan("jenis", "Jenis pekerjaan", tipe, [("", "Semua jenis"), *JENIS_KERJA]),
                     _pilihan("kepemilikan", "Kepemilikan", pemilik, [("", "Semua kepemilikan"), ("pabrik", "Milik pabrik"), ("jasa", "Jasa")]),
                     _pilihan("gudang", "Gudang", gudang, [("", "Semua gudang"), ("g1", "Gudang 1"), ("g2", "Gudang 2")]),
                     _pilihan("pemasok", "Nama pihak", q.get("pemasok", ""), [(q.get("pemasok", ""), q.get("pemasok") or "Semua nama")],
                              disabled=True, reason="Pilihan nama tersedia setelah daftar selesai dibaca.")])
        # Navigasi Pekerjaan memakai helper existing, tetapi jumlah belum
        # diketahui; jangan menggambar nol sebagai hasil pembacaan.
        konteks.update(tab="berjalan", href=href, total_tindakan="…", total_jalan="…")
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
        await siapkan(request, nama, awal)
        nav = awal["STOK_NAV"]
        columns = (["Lot / kode · tanggal", "Pemilik", "Letak", "Status"]
                   + (["Kadar air", "Broken", "Susut", "Nilai kualitas"] if mutu else [])
                   + ["Kondisi", "Berat tersedia", "Tindakan"] if tab == "bahan" else
                   ["Produk", "Hasil sosoh", "Keluar", "Dikemas / tercatat", "Curah / belum dikemas", "Sisa di gudang", "Tindakan"] if tab == "produk" else
                   ["No.", "Merek", "Jenis karung", "Ukuran", "Jumlah", "Status / tindakan"])
        from app.web.stok_navigasi import alamat
        data.update(tab=tab, columns=columns, scope=nav["cakupan"] + " · " + nav["lokasi"],
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
    response.headers["Cache-Control"] = "private, no-store"
    return response


async def _isi(request: Request, akun, jenis: str):
    if jenis not in ALAMAT:
        raise HTTPException(404, "Halaman tidak dikenal.")
    if jenis == "pekerjaan" and request.query_params.get("tab") != "berjalan":
        raise HTTPException(422, "Pilih tab Berjalan.")
    from starlette.requests import Request as NativeRequest

    scope = {**request.scope, "path": ALAMAT[jenis], "raw_path": ALAMAT[jenis].encode(),
             "state": {**request.scope.get("state", {}), "isi_halaman_bertahap": True}}
    native = NativeRequest(scope)
    if jenis == "pekerjaan":
        from app.web.layar_pekerjaan import halaman_pekerjaan
        response = await halaman_pekerjaan(native, akun)
    else:
        from app.web.layar_stok import halaman_stok
        response = await halaman_stok(native, akun)
    if response.status_code != 200:
        raise HTTPException(409, "Tujuan halaman berubah. Buka kembali halaman dari menu.")
    response.headers["Cache-Control"] = "private, no-store"
    return native, response


@router.get("/api/halaman-bertahap/{jenis}")
async def isi_halaman(jenis: str, request: Request, akun=Depends(butuh_akun)):
    native, response = await _isi(request, akun, jenis)
    return JSONResponse(dict(stamp=penanda(native, akun, jenis), html=response.body.decode("utf-8")),
                        headers={"Cache-Control": "private, no-store"})


@router.get("/api/halaman-bertahap/stok/html")
async def pilihan_pelanggan(request: Request, akun=Depends(butuh_akun)):
    # Consumer filter stok lama membaca HTML option. Adapter ini hanya
    # mengganti alamat GET consumer tersebut pada dua halaman yang diadopsi.
    native, response = await _isi(request, akun, "stok")
    response.headers["X-Halaman-Konteks"] = penanda_konteks(native, akun)
    return response
