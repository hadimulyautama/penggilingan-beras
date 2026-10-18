"""Rute masuk, keluar, dan ganti sandi webapp produksi.

Dua jenis perangkat, dua perlakuan sesi (lihat `ProduksiAkun.mode_perangkat`):

- **Operator — perangkat gudang.** Sesi pendek dan diperpanjang tiap kali
  dipakai, jadi ia mati sendiri setelah ditinggal menganggur. Tanpa itu,
  orang berikutnya yang memegang perangkat akan mencatat pekerjaannya atas
  nama orang sebelumnya, dan jejak auditnya tetap rapi tapi isinya salah.
- **Admin & staff — perangkat sendiri.** Sesi panjang; membuka aplikasi lagi
  tidak meminta sandi.

Karena perangkat gudang berarti login berkali-kali dalam sehari, halaman masuk
mengingat siapa saja yang pernah memakai perangkat itu dan menawarkannya
sebagai tombol: pilih nama, ketik sandi. Yang disimpan hanya nama pengguna —
tidak ada token, tidak ada sandi.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request

from app.database import SessionLocal, now_local
from app.models import ProduksiAkun
from app.web import gerbang_masuk as gerbang
from app.web.security import (
    COOKIE_PERANGKAT,
    NAMA_COOKIE,
    akun_opsional,
    baca_nama_perangkat,
    buat_token,
    butuh_akun,
    tujuan_aman,
    tulis_nama_perangkat,
    umur_sesi_detik,
)
from app.web.tampilan import redirect, render
from hmu_identitas import masuk as identitas
from hmu_identitas import pintu

log = logging.getLogger("web.auth")

router = APIRouter(tags=["webapp"])

_SETAHUN = 365 * 24 * 3600


def _bersihkan_nama(v: str | None) -> str:
    """Nama pengguna dari URL — disaring ketat sebelum masuk ke halaman."""
    nama = (v or "").strip().lower()
    if not nama or len(nama) > 50 or not nama.isascii():
        return ""
    return nama if nama.replace("_", "").replace("-", "").isalnum() else ""


@router.get("/masuk")
async def halaman_masuk(request: Request):
    akun = await akun_opsional(request)
    if akun is not None:
        return redirect("/")
    pilih = _bersihkan_nama(request.query_params.get("u"))
    riwayat = baca_nama_perangkat(request.cookies.get(COOKIE_PERANGKAT))
    return render(
        request, "masuk.html",
        tujuan=tujuan_aman(request.query_params.get("next", "")),
        username=pilih,
        riwayat=[n for n in riwayat if n != pilih],
    )


@router.post("/masuk")
async def proses_masuk(
    request: Request,
    username: str = Form(...),
    sandi: str = Form(...),
    tujuan: str = Form(""),
):
    uname = username.strip().lower()
    tujuan = tujuan_aman(tujuan)
    ip = request.client.host if request.client else ""
    riwayat = baca_nama_perangkat(request.cookies.get(COOKIE_PERANGKAT))

    def gagal(pesan: str):
        # Nama pengguna dikembalikan ke formulir. Mengosongkannya berarti
        # mengetik ulang hanya karena salah satu huruf sandi — hukuman untuk
        # kesalahan yang bukan di situ.
        return render(request, "masuk.html", tujuan=tujuan, username=uname,
                      riwayat=[n for n in riwayat if n != uname], pesan_err=pesan)

    # ── Pembatas percobaan, per nama pengguna DAN alamat ──
    #
    # Tanpa ini seluruh daftar sandi bisa dicoba satu per satu, dan tak ada
    # satu baris pun yang mencatat bahwa itu sedang terjadi. Temuan QA P-S-04.
    sisa = gerbang.boleh_coba(uname, ip)
    if sisa is not None:
        return gagal(
            f"Terlalu banyak percobaan. Coba lagi {int(sisa // 60) + 1} menit "
            "lagi, atau hubungi Super Admin bila lupa sandi."
        )

    async with SessionLocal() as db:
        # Kredensial diperiksa paket identitas: waktu jawab yang sama untuk
        # nama yang tak ada (QA P-S-13), scrypt di threadpool (QA P-S-04),
        # status akun DAN status orangnya di master (QA X-11). Pesan yang
        # sama untuk nama tak dikenal maupun sandi salah.
        try:
            akun = await identitas.periksa_kredensial(db, uname, sandi)
        except identitas.Tolak as e:
            gerbang.catat_gagal(uname, ip)
            return gagal(e.pesan)
        # Pintu per aplikasi (keputusan pemilik 13 Sep 2026). Pos Produksi
        # masih menerima admin sampai Meja dipakai sungguhan.
        sebab = pintu.sebab_tolak(akun.peran, pintu.PRODUKSI)
        if sebab:
            # Tidak dihitung sebagai percobaan gagal: sandinya benar, yang
            # menolak perannya. Alasan lengkapnya di `gerbang_masuk.
            # catat_sandi_benar` — hitungan yang sama dipakai ketiga app.
            gerbang.catat_sandi_benar(uname, ip)
            return gagal(sebab)

        gerbang.catat_berhasil(uname, ip)
        akun.terakhir_login = now_local()
        wajib_ganti = akun.harus_ganti_sandi
        await db.commit()
        await db.refresh(akun)

    balasan = redirect("/ganti-sandi" if wajib_ganti else (tujuan or "/"))
    balasan.set_cookie(
        NAMA_COOKIE, buat_token(akun), max_age=umur_sesi_detik(akun),
        httponly=True, samesite="lax", secure=request.url.scheme == "https", path="/",
    )
    balasan.set_cookie(
        COOKIE_PERANGKAT,
        tulis_nama_perangkat(request.cookies.get(COOKIE_PERANGKAT), uname),
        max_age=_SETAHUN, httponly=True, samesite="lax",
        secure=request.url.scheme == "https", path="/",
    )
    _reset_perangkat(balasan, request)
    return balasan


@router.post("/keluar")
async def proses_keluar(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    """Keluar hanya membuang sesi. Daftar nama di perangkat sengaja DITAHAN —
    itulah yang membuat pemakai berikutnya cukup menekan namanya.

    Perangkat LAIN tidak ikut keluar; untuk itu ada `/keluar-semua`.
    """
    balasan = redirect(f"/masuk?u={akun.username}")
    balasan.delete_cookie(NAMA_COOKIE, path="/")
    _reset_perangkat(balasan, request)
    return balasan


@router.post("/keluar-semua")
async def proses_keluar_semua(request: Request,
                              akun: ProduksiAkun = Depends(butuh_akun)):
    """Putuskan sesi di SEMUA perangkat — termasuk yang tak ada di tangan.

    Inilah yang dicari orang saat HP-nya hilang, dan sampai 11 September 2026
    jalannya tidak ada sama sekali: "Keluar" hanya menghapus cookie di
    perangkat yang menekannya, sementara yang hilang tetap masuk sampai 30
    hari. Temuan QA P-S-05.
    """
    await naikkan_versi_token(akun.id, sebab="keluar dari semua perangkat")
    balasan = redirect(f"/masuk?u={akun.username}&pesan=keluar-semua")
    balasan.delete_cookie(NAMA_COOKIE, path="/")
    _reset_perangkat(balasan, request)
    return balasan


async def naikkan_versi_token(akun_id: int, *, sebab: str = "") -> None:
    """Naikkan versi token sebuah akun → seluruh sesinya berhenti berlaku.

    Dipanggil saat keluar-semua, ganti sandi, reset sandi, perubahan peran,
    dan penonaktifan. Satu fungsi, dipanggil dari lima tempat: versi yang
    dinaikkan dengan UPDATE yang ditulis ulang di tiap tempat akan tertinggal
    di salah satunya — dan yang tertinggal justru jadi satu-satunya tindakan
    yang tampak memutus akses padahal tidak.
    """
    async with SessionLocal() as db:
        await identitas.naikkan_versi(db, akun_id)
    if sebab:
        log.info("Versi token akun %s dinaikkan — %s", akun_id, sebab)


@router.get("/ganti-sandi")
async def halaman_ganti_sandi(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    return render(request, "ganti_sandi.html", wajib=akun.harus_ganti_sandi,
                  kembali=None if akun.harus_ganti_sandi else "/")


@router.post("/ganti-sandi")
async def proses_ganti_sandi(
    request: Request,
    sandi_baru: str = Form(...),
    ulangi: str = Form(...),
    sandi_lama: str = Form(""),
    akun: ProduksiAkun = Depends(butuh_akun),
):
    wajib = akun.harus_ganti_sandi

    def gagal(pesan: str):
        return render(request, "ganti_sandi.html", wajib=wajib,
                      kembali=None if wajib else "/", pesan_err=pesan)

    # Saat sandi masih sandi awal dari Super Admin, sandi lama TIDAK diminta:
    # orangnya baru saja membuktikan dirinya beberapa detik lalu di halaman
    # masuk, dan memintanya mengetik ulang sandi yang justru sedang dibuang
    # hanya menambah satu kesempatan salah ketik.
    if sandi_baru != ulangi:
        return gagal("Kata sandi baru dan ulangannya tidak sama.")
    async with SessionLocal() as db:
        try:
            # Sandi yang diganti memutus sesi LAMA di semua perangkat (versi
            # naik di paket). Tanpa ini, sandi yang sudah dicuri tetap
            # berguna sesudah diganti — yang justru alasan orang menggantinya.
            await identitas.ganti_sandi(db, akun, sandi_lama=sandi_lama,
                                        sandi_baru=sandi_baru, wajib_lama=not wajib)
        except identitas.Tolak as e:
            return gagal(e.pesan)
        akun_baru = await db.get(ProduksiAkun, akun.id)
        token_baru = buat_token(akun_baru)
        umur = umur_sesi_detik(akun_baru)

    # Selesai berarti selesai: kembali ke beranda dengan kabar baiknya, bukan
    # tertinggal di formulir yang sudah tidak ada gunanya.
    #
    # Cookie-nya diperbarui di sini juga: versi tokennya baru saja naik, jadi
    # tanpa token baru orangnya akan terlempar ke halaman masuk persis
    # sesudah berhasil mengganti sandinya sendiri.
    balasan = redirect("/?pesan=sandi-diganti")
    balasan.set_cookie(
        NAMA_COOKIE, token_baru, max_age=umur,
        httponly=True, samesite="lax",
        secure=request.url.scheme == "https", path="/",
    )
    return balasan


def _reset_perangkat(balasan, request):
    # Nama pemakai boleh diingat, gudang kerja dan formulir sesi lama tidak.
    from app.web import csrf
    from app.web.lihat_sebagai import NAMA_KUKI
    balasan.delete_cookie(NAMA_KUKI, path="/")
    balasan.set_cookie(csrf.NAMA_COOKIE, csrf.terbitkan_baru(), path="/",
        samesite="lax", secure=request.url.scheme == "https", httponly=False)


@router.get("/api/sesi-formulir")
async def sesi_formulir(request: Request):
    request.state.jangan_perpanjang_sesi = True
    from fastapi.responses import JSONResponse
    from app.web import csrf
    from app.web.security import baca_token
    akun = await akun_opsional(request)
    if akun is None:
        return JSONResponse({"token": "", "aktif": False}, headers={"Cache-Control": "no-store"})
    return JSONResponse({"aktif": True, "token": csrf.untuk_sesi(
        request.cookies.get(csrf.NAMA_COOKIE, ""), baca_token(request.cookies.get(NAMA_COOKIE)),
        request.cookies.get("produksi_lihat", ""))}, headers={"Cache-Control": "no-store"})
