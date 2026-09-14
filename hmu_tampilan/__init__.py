"""hmu_tampilan — satu paket tampilan untuk semua layar PT Hadi Mulya Utama.

Lahir 13 September 2026 (Tahap 1 rancang ulang, temuan QA X-22): sampai hari
itu `app.css` (1.360 baris), `aksi.js` (877), `pindah.js` (473), `base.html`,
dan `_benda.html` disalin ke tiga repo — produksi, gudang2, meja — dan dua
perbaikan berperilaku hidup hanya di salinan. Sekarang sumbernya SATU, di
repo `tampilan/`, dan tiap aplikasi memasangnya lewat dua pintu:

    templates = Jinja2Templates(directory=".../templates")
    hmu_tampilan.pasang_jinja(templates, app_nama="Pos Produksi", pwa_nama="Pos Produksi")
    app.mount("/static", hmu_tampilan.StatisBerlapis(".../static"), name="static")

Templat aplikasi dicari LEBIH DULU, lalu templat paket — jadi `base.html` dan
`_benda.html` datang dari paket, sedangkan layar (`beranda.html`, …) tetap
milik aplikasi. Berkas statis pun berlapis: `manifest.json` milik aplikasi,
`app.css`/`aksi.js`/`pindah.js`/ikon milik paket.

VERSI ada di sini, satu nomor untuk semua. Naikkan setiap kali isi paket
berubah; alamat aset bercap versi (`?v=`), jadi salinan lama di ponsel tak
pernah terpakai lagi.

Cara sampai ke aplikasi: DI-VENDOR (disalin utuh ke `<repo>/hmu_tampilan/`
oleh `scripts/sinkron.py` di repo tampilan) — sama seperti `hmu_core` di
produksi — karena Railway membangun tiap service dari repo-nya sendiri dan
Dockerfile hanya melihat isi repo itu. Salinan vendored membawa
`MANIFEST.sha256`; `penjaga.py` membandingkannya supaya salinan yang disunting
tangan atau basi ketahuan di uji, bukan di gudang.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import ChoiceLoader, FileSystemLoader

#: Naikkan setiap kali CSS/JS/templat paket berubah. Nomor melanjutkan
#: hitungan produksi (terakhir 123) supaya cap versi di ponsel operator tak
#: pernah mundur.
VERSI = "129"

AKAR = Path(__file__).resolve().parent
STATIC_DIR = AKAR / "static"
TEMPLATES_DIR = AKAR / "templates"

#: Berkas yang HANYA boleh ada di paket. Repo aplikasi yang menyimpan berkas
#: bernama ini di luar folder vendored berarti menyalin lagi — ditolak
#: `penjaga.salinan_terlarang`.
BERKAS_PAKET = (
    "app.css", "aksi.js", "pindah.js", "sw.js",
    "ikon-180.png", "ikon-192.png", "ikon-512.png",
    "base.html", "_benda.html", "luring.html",
)


def router_pwa(render):
    """Dua rute yang membuat manifest berguna saat sinyal hilang.

    `GET /sw.js` — service worker, dari AKAR aplikasi, bukan dari /static/:
    peramban menolak worker yang mengaku menaungi cakupan di atas letaknya
    sendiri (pelajaran pos timbang). `Cache-Control: no-cache` karena inilah
    berkas yang memutuskan versi cache lainnya; kalau ia sendiri basi,
    pembaruan tak pernah sampai. VERSI-nya ikut sebagai `?v=` pada
    pendaftaran di pindah.js, jadi berkas ini statis dan sama untuk semua.

    `GET /luring` — halaman cadangan yang disimpan worker saat dipasang.
    `render` milik aplikasi dipakai supaya kerangkanya (base.html, tema,
    nama aplikasi) sama dengan layar lain.
    """
    # `Request` WAJIB dikenal di tingkat modul: anotasi di berkas ini berupa
    # teks (`from __future__ import annotations`), dan FastAPI mencarinya di
    # global modul — diimpor di dalam fungsi, ia jadi parameter kueri (422).
    router = APIRouter()

    @router.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(
            STATIC_DIR / "sw.js", media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )

    @router.get("/luring", include_in_schema=False)
    async def luring(request: Request):
        return render(request, "luring.html")

    return router


def pasang_jinja(templates, *, app_nama: str, pwa_nama: str,
                 mode_uji: bool = False, mockup: bool = False) -> None:
    """Pasang pemuat berlapis + global yang dibaca `base.html` paket.

    `templates` = `fastapi.templating.Jinja2Templates` milik aplikasi. Pemuat
    aplikasinya dipertahankan di depan; paket di belakang.
    """
    env = templates.env
    env.loader = ChoiceLoader([env.loader, FileSystemLoader(str(TEMPLATES_DIR))])
    env.globals["VERSI"] = VERSI
    env.globals["APP_NAMA"] = app_nama
    env.globals["PWA_NAMA"] = pwa_nama
    env.globals.setdefault("MODE_UJI", mode_uji)
    env.globals.setdefault("MOCKUP", mockup)


class StatisBerlapis(StaticFiles):
    """Berkas statis aplikasi DULU, lalu berkas paket — satu alamat `/static`.

    Cache mengikuti aturan produksi (dulu `StatisTerCache` di main.py): alamat
    bercap `?v=` boleh disimpan setahun (berkas yang berubah dimintakan dengan
    alamat baru), yang tak bercap — ikon, manifest — berumur satu jam.
    """

    def __init__(self, app_static: str | Path | None = None, **kw):
        super().__init__(directory=str(STATIC_DIR), **kw)
        lapis = [Path(app_static)] if app_static else []
        self.all_directories = lapis + [STATIC_DIR]

    async def get_response(self, path: str, scope):
        balasan = await super().get_response(path, scope)
        bercap = b"v=" in dict(scope).get("query_string", b"")
        balasan.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if bercap else "public, max-age=3600"
        )
        return balasan
