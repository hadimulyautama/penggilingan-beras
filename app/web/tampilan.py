"""Kerangka tampilan webapp: Jinja, render, dan pengalihan.

Dipisah dari rutenya supaya modul rute tidak saling mengimpor hanya untuk
memakai `render`.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

#: Dinaikkan setiap kali CSS atau JS berubah.
#:
#: Tanpa ini, perangkat yang sudah pernah membuka aplikasi akan memakai berkas
#: lama tanpa ada yang menyadarinya — dan pada layar pencatatan, JavaScript
#: lama berarti formulir yang bentuknya sudah berubah di server tetap dirender
#: dengan aturan yang sudah dicabut.
VERSI = "119"

templates.env.globals["VERSI"] = VERSI

from app.config import settings  # noqa: E402

#: Pita "MODE UJI" di tiap layar. Orang yang tak tahu ia sedang menguji akan
#: memperlakukan angka uji sebagai angka pabrik — dan itu kesalahan yang
#: baru ketahuan berminggu-minggu kemudian.
templates.env.globals["MODE_UJI"] = settings.mode_uji

from app.web.layar import MEJA, NAMA_VIEW, POLESAN, SELEPAN, SUPER  # noqa: E402
from app.web.nav import JUDUL, TAB   # noqa: E402  (butuh `templates` di atas)

templates.env.globals["TAB"] = TAB
templates.env.globals["TAB_KUNCI"] = {k for k, _, _, _, _ in TAB}
# Nama view dipakai kepala laci: orang yang sedang memakai "Lihat sebagai"
# harus bisa membaca layar SIAPA yang sedang ia lihat, dan "operator" saja
# tak menjawabnya di pabrik yang punya dua gudang.
templates.env.globals["NAMA_VIEW"] = NAMA_VIEW
# Dipakai templat untuk membedakan isi yang tak punya pintunya sendiri —
# mis. petak Beranda dan blok Orang & alat di Pengaturan.
templates.env.globals["V_MEJA"] = MEJA
templates.env.globals["V_SUPER"] = SUPER
templates.env.globals["V_SELEPAN"] = SELEPAN
templates.env.globals["V_POLESAN"] = POLESAN
# Judul layar naik ke bilah atas — laci menyembunyikan posisi orang,
# dan layar tanpa nama membuat orang menekan menu hanya untuk memastikan
# ia sedang di mana.
templates.env.globals["JUDUL"] = JUDUL

from app.web.lihat_sebagai import PILIHAN as _LIHAT_PILIHAN  # noqa: E402
templates.env.globals["LIHAT_PILIHAN"] = _LIHAT_PILIHAN

#: Nama fase barang di layar. Urutannya mengikuti perjalanan barang sendiri —
#: menunggu orang, panas di mesin, tersimpan di silo, menghasilkan — dan
#: warnanya di app.css mengikuti urutan yang sama, jadi posisinya terbaca
#: sekilas tanpa membaca hurufnya.
templates.env.globals["FASE"] = {
    "baru": "Belum ada tindakan",
    # Gabah yang menumpuk SUDAH ditindak — ia sengaja ditaruh di lantai karena
    # mesin dan silo tak siap menerimanya. Sebelum ini ia memakai fase "baru",
    # jadi kepingannya berbunyi "Belum ada tindakan" tepat di bawah judul blok
    # "Menumpuk di lantai" — dua kalimat yang saling membantah pada kartu yang
    # sama. Kepingan yang berbohong lebih buruk daripada kepingan yang tak ada,
    # karena ia dipercaya.
    "tumpuk": "Menumpuk di lantai",
    "dryer": "Di mesin pengering",
    "silo": "Transit di silo kering",
    "giling": "Proses giling",
}


def render(request: Request, nama: str, *, status_code: int = 200, **konteks):
    """Render template dengan konteks bawaan (akun yang sedang masuk).

    `layar` diturunkan dari nama template, bukan dikirim tiap pemanggil: bilah
    navigasi harus menyala di tab yang benar, dan satu pemanggil yang lupa
    mengirimnya berarti satu layar yang tabnya mati tanpa ada yang menyadari.
    """
    konteks.setdefault("akun", getattr(request.state, "akun", None))
    konteks.setdefault("LIHAT_SEBAGAI", getattr(request.state, "lihat_sebagai", None))
    konteks.setdefault("PERAN_ASLI", getattr(request.state, "peran_asli", None))
    konteks.setdefault("layar", nama.replace(".html", ""))
    # View ditetapkan `akun_opsional`, satu kali per permintaan. Layar tak
    # pernah menghitungnya sendiri — lihat `app.web.layar`.
    konteks.setdefault("VIEW", getattr(request.state, "view", "tamu"))
    konteks.setdefault("MENUNGGU", 0)
    return templates.TemplateResponse(request, nama, konteks, status_code=status_code)


async def render_laci(request: Request, nama: str, **konteks):
    """`render` untuk layar yang tak menyusun daftar `Berjalan` sendiri.

    Laci itu satu benda di seluruh aplikasi. Kalau angkanya ada di Beranda
    tapi hilang di List audit, yang dibaca orang bukan "layar ini tidak
    menghitung" melainkan "pekerjaannya sudah habis" — dan lencana yang
    kadang bohong lebih buruk daripada lencana yang tak pernah ada.

    Layar yang SUDAH memegang `Berjalan` tetap mengirim angkanya sendiri:
    memanggil ini di sana berarti menyusun ulang seluruh daftar dua kali
    hanya demi tiga angka.
    """
    from app.web.nav import lencana

    akun = getattr(request.state, "akun", None)
    return render(request, nama,
                  **{**await lencana(akun.user if akun else None), **konteks})


def redirect(tujuan: str) -> RedirectResponse:
    """Pengalihan setelah POST — 303 supaya peramban beralih ke GET."""
    return RedirectResponse(tujuan, status_code=303)
