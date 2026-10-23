"""hmu_tampilan — satu paket tampilan untuk semua layar PT Hadi Mulya Utama.

Lahir 13 September 2026 (Tahap 1 rancang ulang, temuan QA X-22): sampai hari
itu `app.css` (1.360 baris), `aksi.js` (877), `pindah.js` (473), `base.html`,
dan `_benda.html` disalin ke tiga repo — produksi, gudang2, meja — dan dua
perbaikan berperilaku hidup hanya di salinan. Sekarang sumbernya SATU, di
repo `tampilan/`.

Sejak 24 September 2026 yang memakainya tinggal SATU aplikasi: app Gudang 2
dan app Meja dihapus (keputusan pemilik — tidak dipakai lagi, seluruh
pekerjaan lewat Pos Produksi). Paketnya tetap berdiri sendiri, dan alasannya
tak berubah: ia yang membuat CSS/JS punya satu sumber yang bisa diuji, bukan
lima salinan di dalam repo aplikasi.

Tiap aplikasi memasangnya lewat dua pintu:

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
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import ChoiceLoader, FileSystemLoader

#: Naikkan setiap kali CSS/JS/templat paket berubah. Nomor melanjutkan
#: hitungan produksi (terakhir 123) supaya cap versi di ponsel operator tak
#: pernah mundur.
VERSI = "428"

AKAR = Path(__file__).resolve().parent
STATIC_DIR = AKAR / "static"
TEMPLATES_DIR = AKAR / "templates"

#: Berkas yang HANYA boleh ada di paket. Repo aplikasi yang menyimpan berkas
#: bernama ini di luar folder vendored berarti menyalin lagi — ditolak
#: `penjaga.salinan_terlarang`.
BERKAS_PAKET = (
    "app.css", "komponen-portal.css", "_ikon_portal.html", "aksi.js", "pindah.js", "sw.js",
    "ikon-180.png", "ikon-192.png", "ikon-512.png",
    "base.html", "_benda.html", "_kepemilikan.html", "_proses_visual.html", "_operasional.html", "luring.html",
    # ── Delapan LAYAR yang naik ke paket 23 September 2026 ──
    # Inventaris QA hari itu: paket memuat 3 berkas, dan 41 berkas templat
    # disalin tangan untuk ~16 layar. Tiga di antaranya salinan murni (beda 0
    # baris), lima sudah hanyut tanpa sengaja — `ganti_sandi.html` paling jauh:
    # panjangnya 42 vs 43 baris tetapi 73 barisnya berbeda, karena diformat
    # ulang sendiri-sendiri. Nama-nama ini ada di sini supaya
    # `penjaga.salinan_terlarang` MENOLAK kemunculannya lagi di luar paket:
    # itulah satu-satunya hal yang mencegah duplikasinya tumbuh kembali.
    "error.html", "laporan.html", "aksi_lain.html", "audit.html",
    "pengguna.html", "masuk.html", "alat.html", "ganti_sandi.html",
    # Potongan baris versi 21c: satu sumber untuk keempat app.
    "_versi.html",
    # ── Tahap 2, 23 September 2026: layar yang memang BEDA per peran ──
    # Bedanya sah, jadi yang disatukan kerangkanya: blok dipasang atau tidak
    # menurut bendera yang app-nya hitung dengan mesin view yang sudah ada.
    # Kalimat yang benar-benar milik satu app tinggal di `_kata_*.html`
    # app itu — nama itu sengaja TIDAK terdaftar di sini.
    "pengaturan.html", "_pengaturan_formulir.html", "_pengaturan_terik.html",
    "_pengaturan_ikon.html", "pengaturan.css", "aksi.html",
    # `beranda.html` = beranda aplikasi GUDANG (produksi & gudang2). Beranda
    # Meja adalah layar LAIN, bukan variannya (keputusan pemilik 12 September
    # 2026), dan bernama `beranda_meja.html` di repo meja — jadi nama ini boleh
    # dijaga ketat tanpa menghalanginya.
    "beranda.html", "_beranda.html",
    # `stok.html` = stok PK (Pos Produksi & Meja). Layar Stok Gudang 2
    # menjawab pertanyaan LAIN — barang jadi — dan bernama `stok_gudang2.html`.
    "stok.html", "_stok.html",
    # Ringkasan SATU gudang, sasaran baris gudang di Beranda. Naik ke paket 24
    # September 2026 bersama rute `/gudang/<gid>` di Pos Produksi — ia salah
    # satu layar yang harus tetap ada sesudah app meja dihapus.
    "gudang.html",
    # Pil penyaring gudang — lahir dua kali (stok & berjalan) pada hari yang
    # sama, disatukan 24 September 2026 sebelum keduanya sempat berselisih.
    "_saring.html",
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
                 mode_uji: bool = False, mockup: bool = False,
                 zona: str = "Asia/Jakarta") -> None:
    """Pasang pemuat berlapis + global yang dibaca `base.html` paket.

    `templates` = `fastapi.templating.Jinja2Templates` milik aplikasi. Pemuat
    aplikasinya dipertahankan di depan; paket di belakang.

    `zona` memasang saringan `jam` — lihat di bawah. Bawaannya Asia/Jakarta,
    dan aplikasi yang punya setelan zona sendiri wajib mengirimkannya.
    """
    env = templates.env
    env.loader = ChoiceLoader([env.loader, FileSystemLoader(str(TEMPLATES_DIR))])
    env.globals["VERSI"] = VERSI
    # Pintu laci yang tak ditawarkan pada permintaan ini (kunci layar). App yang
    # tak pernah mematikan layar apa pun tak perlu menyebutnya sama sekali —
    # tanpa bawaan ini, `kunci not in PINTU_MATI` di `base.html` akan menabrak
    # Undefined di app yang lain, dan laci yang gagal dirender berarti orang
    # terkurung di layar yang sedang ia buka.
    env.globals["PINTU_MATI"] = ()
    # Sub-menu laci per pintu: {kunci: [(alamat, nama, jumlah)]}. Bawaannya
    # KOSONG di sini, alasan yang sama dengan `PINTU_MATI` di atas: app yang
    # tak punya sub-menu tak perlu menyebutnya, dan `SUBMENU.get(...)` atas
    # Undefined akan menggagalkan render SELURUH laci — orang lalu terkurung
    # di layar yang sedang ia buka.
    env.globals["SUBMENU"] = {}
    env.globals["APP_NAMA"] = app_nama
    env.globals["PWA_NAMA"] = pwa_nama
    env.globals.setdefault("MODE_UJI", mode_uji)
    env.globals.setdefault("MOCKUP", mockup)

    # ── SARINGAN `jam` — dan sebabnya struktural, bukan kerapian ──
    #
    # Laporan operator 30 September 2026: "jam pada kabar belum sesuai". Benar,
    # dan tujuh jam melesetnya: `notifications.created_at` adalah `timestamptz`,
    # asyncpg mengembalikannya ber-UTC, dan `k.waktu.strftime(...)` di templat
    # mencetaknya apa adanya. Empat templat lain mengidap hal yang sama tanpa
    # ada yang menyadarinya — dan itulah masalah sesungguhnya: `strftime`
    # BEKERJA. Ia tak pernah gagal, tak pernah berkabar, dan cacatnya cuma
    # terlihat oleh orang yang membandingkannya dengan jam tangannya.
    #
    # Jadi yang diperbaiki bukan lima barisnya melainkan yang MUDAH DIKETIK:
    # sesudah ini `| jam` lebih pendek daripada `.strftime(...)`, dan yang
    # lupa memakainya tertangkap pagar `test_tampilan_paket.py`.
    #
    # Naif dilewatkan apa adanya: kolom tanpa zona memang sudah waktu lokal,
    # dan memaksanya berpindah zona akan menggesernya tujuh jam ke arah lain.
    def _jam(saat, bentuk: str = "%d/%m %H:%M") -> str:
        if saat is None:
            return ""
        if getattr(saat, "tzinfo", None) is not None:
            saat = saat.astimezone(ZoneInfo(zona))
        return saat.strftime(bentuk)

    env.filters["jam"] = _jam



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
