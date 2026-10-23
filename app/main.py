"""Entrypoint produksi: FastAPI + bot pabrik (long-polling) dalam satu proses.

Kantor AI TIDAK lagi dijalankan di sini — bot, poller proaktif, dan heartbeat-nya
pindah ke service & repo sendiri (github.com/hadimulyautama/kantor). Yang tersisa
untuk Kantor hanyalah API internal `/internal/produksi/*` (app/web/internal.py)
yang dipanggilnya untuk membaca data pabrik.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import hmu_tampilan

from app.config import settings
from app.database import SessionLocal
from app.services.dashboard import dashboard_data, render_dashboard_html
from app.penggilingan.gudang1.services.sinkron_bobot import run_sinkron_bobot_poller
from app.services.kledo_scheduler import run_kledo_scheduler
from app.services.scheduler import run_late_drying_scheduler
from app.services.seed import seed_master
from app.web.auth import router as auth_router
from app.web.internal import router as internal_router
from app.web.internal_kledo import router as internal_kledo_router
from app.web.aksi_inventory import router as aksi_inventory_router
from app.web.aksi_undo import router as aksi_undo_router
from app.web.laporan import router as laporan_router
from app.web.laporan_navigasi import router as laporan_navigasi_router
from app.web.layar_audit import router as audit_router
from app.web.layar_berjalan import router as berjalan_router
from app.web.pengaturan import router as pengaturan_router
from app.web.mode_uji import router as mode_uji_router
from app.web.layar_gudang import router as gudang_router
from app.web.layar_keputusan import router as keputusan_router
from app.web.layar_kabar import router as kabar_router
from app.web.layar_jasa import router as jasa_router
from app.web.layar_keluar import router as keluar_router
from app.web.kemas_ulang import router as kemas_ulang_router
from app.web.draf_keluar import router as draf_keluar_router
from app.web.layar_retur import router as retur_router
from app.web.layar_retur_asal import router as retur_asal_router
from app.web.layar_produk import router as produk_router
from app.web.layar_riwayat import router as riwayat_router
from app.web.layar_sosoh import router as sosoh_router
from app.web.layar_stok import router as stok_router
from app.web.lihat_sebagai import router as lihat_sebagai_router
from app.web.api import router as api_router
from app.web.pengguna import router as pengguna_router
from app.web.security import (
    AksesDitolak,
    ButuhLogin,
    NAMA_COOKIE,
    akun_opsional,
    buat_token,
    umur_sesi_detik,
)
from app.web.seed_akun import seed_akun_awal
from app.web.tampilan import BASE_DIR, render

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pastikan data master ada (penting untuk DB kosong: staging / DB baru).
    try:
        await seed_master()
    except Exception:
        log.exception("Seed master gagal (lanjut jalan)")
    try:
        await seed_akun_awal()
    except Exception:
        log.exception("Seed akun webapp gagal (lanjut jalan)")
    sched_task = asyncio.create_task(run_late_drying_scheduler())
    sinkron_task = asyncio.create_task(run_sinkron_bobot_poller())
    kledo_task = asyncio.create_task(run_kledo_scheduler())
    from app.services.retur_pekerja import jalankan as jalankan_retur
    retur_task = asyncio.create_task(jalankan_retur())
    log.info("Backend siap. Tanpa bot — pencatatan lewat Pos Produksi.")
    try:
        yield
    finally:
        # Hentikan task latar dengan membatalkan. Guard karena saat --reload
        # task bisa belum/selesai berjalan.
        for task in (sched_task, sinkron_task, kledo_task, retur_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Error saat menghentikan task latar")


app = FastAPI(title="Sistem Penggilingan Beras — Backend", lifespan=lifespan)
app.include_router(api_router)
# Service worker + halaman /luring (Tahap A rasa native) — dari paket tampilan.
app.include_router(hmu_tampilan.router_pwa(render))
app.include_router(aksi_inventory_router)
app.include_router(aksi_undo_router)
app.include_router(laporan_router)
app.include_router(laporan_navigasi_router)
from app.web.layar_pekerjaan import router as pekerjaan_router
app.include_router(pekerjaan_router)
app.include_router(berjalan_router)
app.include_router(audit_router)
app.include_router(pengaturan_router)
app.include_router(mode_uji_router)
app.include_router(keputusan_router)
app.include_router(gudang_router)
app.include_router(produk_router)
app.include_router(draf_keluar_router)
app.include_router(kemas_ulang_router)
app.include_router(keluar_router)
app.include_router(retur_router)
app.include_router(retur_asal_router)
app.include_router(jasa_router)
app.include_router(sosoh_router)
app.include_router(riwayat_router)
from app.web.layar_transfer import router as transfer_detail_router
app.include_router(transfer_detail_router)
app.include_router(kabar_router)
app.include_router(stok_router)
app.include_router(lihat_sebagai_router)
app.include_router(internal_router)
app.include_router(internal_kledo_router)
app.include_router(auth_router)
app.include_router(pengguna_router)
#: Berkas statis: milik aplikasi (manifest.json) di depan, paket tampilan
#: (app.css, aksi.js, pindah.js, ikon) di belakang. Aturan cache-nya — setahun
#: untuk alamat bercap `?v=`, sejam untuk yang tidak — kini hidup di paket;
#: dulu kelas `StatisTerCache` di sini. Nama lamanya dipertahankan sebagai
#: alias supaya uji yang membaca sumbernya tetap menemukan aturan itu.
StatisTerCache = hmu_tampilan.StatisBerlapis
app.mount("/static", hmu_tampilan.StatisBerlapis(BASE_DIR / "static"), name="static")


@app.middleware("http")
async def alamat_lama_miniapp(request: Request, call_next):
    """Alias peralihan: `/miniapp/*` dilayani sebagai `/api/*`.

    Awalan `/miniapp` warisan Mini App Telegram dibuang 14 Sep 2026. Halaman
    yang sudah terbuka di ponsel sebelum deploy masih memegang JS lama yang
    memanggil alamat lama; tanpa alias, denyut penandanya 404 sampai orangnya
    memuat ulang. Dibuang setelah Tahap A rasa native (service worker) jalan.
    """
    jalur = request.scope.get("path", "")
    if jalur.startswith("/miniapp/"):
        request.scope["path"] = "/api/" + jalur[len("/miniapp/"):]
    return await call_next(request)


# ── Sesi & penjaga halaman ──

@app.middleware("http")
async def halaman_jangan_disimpan(request: Request, call_next):
    """Halaman TIDAK boleh disimpan peramban. Asetnya boleh; halamannya jangan.

    Aset bercap versi (`aksi.js?v=59`) sengaja disimpan setahun dan ditandai
    `immutable` — alamat baru untuk isi baru, jadi salinan lama tak pernah
    terpakai. Yang menentukan alamat mana yang diminta adalah HALAMANNYA.

    Dan halamannya selama ini tak membawa `Cache-Control` sama sekali. Tanpa
    itu peramban boleh menyimpannya menurut tebakannya sendiri — dan aplikasi
    yang dipasang di layar depan iPhone memang menyimpannya. Akibatnya halaman
    lama yang tersimpan tetap menunjuk `?v=58`, peramban dengan patuh
    menyajikan berkas v58 dari simpanannya karena memang ditandai `immutable`,
    dan pemakainya melihat aplikasi versi lama padahal servernya sudah lama
    menyajikan yang baru. Menutup aplikasi pun tak menolong; hanya memasang
    ulang yang menolong, dan tak ada yang terpikir melakukannya.

    Isinya juga memang tak layak disimpan: tiap halaman menampilkan keadaan
    pabrik pada detik itu dan berbeda untuk tiap orang.
    """
    balasan = await call_next(request)
    jenis = balasan.headers.get("content-type", "")
    if jenis.startswith("text/html"):
        balasan.headers["Cache-Control"] = "no-store, must-revalidate"
        balasan.headers["Pragma"] = "no-cache"
    return balasan


@app.middleware("http")
async def perpanjang_sesi_pendek(request: Request, call_next):
    """Sesi perangkat gudang dihitung dari pemakaian TERAKHIR, bukan dari jam
    masuk: cookie-nya diperbarui setiap permintaan. Efeknya sesi mati sendiri
    setelah ditinggal menganggur — bukan memutus orang yang sedang bekerja.

    **Tapi tidak bila rutenya sendiri sudah mengurus cookie itu.** `akun` di
    sini dimuat pada AWAL permintaan; bila rutenya menaikkan versi token di
    tengah jalan — ganti sandi, keluar dari semua perangkat — objek ini masih
    memegang versi yang lama. Header terbitan middleware terpasang SESUDAH
    milik rutenya, dan peramban memakai yang terakhir: token usang menimpa
    token yang benar, lalu orangnya terlempar ke halaman masuk persis sesudah
    berhasil mengganti sandinya sendiri. Temuan QA R-P-07.

    Yang diperiksa sengaja keberadaan headernya, bukan daftar alamat rute:
    daftar alamat harus diingat setiap kali ada rute baru yang menyentuh
    cookie sesi, dan yang harus diingat pada akhirnya terlupakan.
    """
    # Respons simpan A yang tiba sesudah login B tidak boleh menerbitkan
    # ulang cookie A. Halaman GET sesudah simpan memperpanjang sesi yang
    # benar-benar masih aktif di peramban; denyut pemeriksaan tidak dihitung.
    balasan = await call_next(request)
    akun = getattr(request.state, "akun", None)
    sudah_diurus = any(
        b.partition("=")[0].strip() == NAMA_COOKIE
        for b in balasan.headers.getlist("set-cookie")
    )
    if (akun is not None and akun.sesi_pendek
            and request.method == "GET"
            and not getattr(request.state, "jangan_perpanjang_sesi", False)
            and balasan.status_code < 400 and not sudah_diurus
            and not getattr(request.state, "lewat_meja", False)):
        balasan.set_cookie(
            NAMA_COOKIE, buat_token(akun), max_age=umur_sesi_detik(akun),
            httponly=True, samesite="lax",
            secure=request.url.scheme == "https", path="/",
        )
    return balasan


@app.middleware("http")
async def penjaga_csrf(request: Request, call_next):
    """Formulir POST wajib membawa token yang cocok dengan cookie-nya.

    Cookie sesi sudah bertanda `SameSite=Lax`, dan itu memang menahan sebagian
    besar kiriman dari situs lain. Tetapi ia menahannya DI PERAMBAN: yang
    menjaga adalah pengaturan di sisi pengunjung, bukan pemeriksaan di sisi
    kita. Temuan QA P-S-15.

    Halaman masuk ikut dipagari. Tanpa itu, situs lain bisa memaksa peramban
    seseorang masuk sebagai akun milik penyerang, dan pekerjaan yang ia catat
    sesudahnya tercatat atas nama orang lain.
    """
    from app.web import csrf as _csrf

    if _csrf.perlu_periksa(request.method, request.url.path):
        di_kuki = request.cookies.get(_csrf.NAMA_COOKIE)
        dikirim = request.headers.get(_csrf.NAMA_HEADER)
        if not dikirim:
            # ── Badan permintaan DIBACA lalu DIKEMBALIKAN ──
            #
            # Middleware memegang objek `Request` sendiri, terpisah dari yang
            # nanti diterima rutenya. Membaca formulir di sini tanpa
            # mengembalikan badannya membuat rute menunggu aliran yang sudah
            # habis — dan yang terlihat orang adalah SETIAP kiriman formulir
            # menggantung, bukan galat.
            badan = await request.body()

            async def _terima() -> dict:
                return {"type": "http.request", "body": badan, "more_body": False}

            request._receive = _terima
            try:
                formulir = await request.form()
                dikirim = formulir.get(_csrf.NAMA_FIELD)
            except Exception:  # noqa: BLE001 — badan JSON, bukan formulir
                dikirim = None
            request._receive = _terima
        from app.web.security import baca_token, NAMA_COOKIE
        sesi = baca_token(request.cookies.get(NAMA_COOKIE))
        diharapkan = _csrf.untuk_sesi(di_kuki or "", sesi, request.cookies.get("produksi_lihat", "")) if di_kuki else None
        if not _csrf.cocok(diharapkan, dikirim):
            log.warning("Token CSRF tak cocok pada %s %s",
                        request.method, request.url.path)
            return render(
                request, "error.html",
                pesan=("Sesi kedaluwarsa atau identitas pembuka formulir berubah. Isian belum disimpan. "
                       "Kembali ke tab formulir untuk menyalin isian, lalu masuk dengan akun "
                       "yang benar dan buka formulir baru."),
                status_code=403,
            )

    balasan = await call_next(request)
    # Terbitkan sekali per peramban, lalu biarkan. Token yang diganti tiap
    # permintaan membuat dua tab yang terbuka bersamaan saling membatalkan.
    if not request.cookies.get(_csrf.NAMA_COOKIE):
        nilai = getattr(request.state, "csrf", None) or _csrf.terbitkan_baru()
        balasan.set_cookie(
            _csrf.NAMA_COOKIE, nilai, max_age=365 * 24 * 3600,
            httponly=False,   # dibaca skrip halaman untuk permintaan JSON
            samesite="lax", secure=request.url.scheme == "https", path="/",
        )
    return balasan


@app.middleware("http")
async def wajib_ganti_sandi_dulu(request: Request, call_next):
    """Selama sandi awal belum diganti, TIDAK ADA tulisan yang diterima.

    Sebelumnya `harus_ganti_sandi` hanya mengarahkan orangnya ke formulir
    saat login. Pengalihan itu soal tampilan; POST ke alamat mana pun tetap
    diterima apa adanya. Jadi sandi awal yang diberikan lisan oleh Super
    Admin — dan karenanya dipegang dua orang — tetap bisa dipakai bekerja
    tanpa batas. Temuan QA P-S-07.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if request.url.path in ("/ganti-sandi", "/keluar", "/keluar-semua"):
        return await call_next(request)
    if request.url.path.startswith(("/health", "/internal/")):
        return await call_next(request)

    from app.web.security import akun_opsional as _akun

    akun = await _akun(request)
    if akun is not None and akun.harus_ganti_sandi:
        return render(
            request, "error.html",
            pesan=("Ganti kata sandi awal Anda dulu sebelum mencatat apa pun. "
                   "Buka menu Ganti sandi."),
            status_code=403,
        )
    return await call_next(request)


@app.exception_handler(Exception)
async def _galat_tak_terduga(request: Request, exc: Exception):
    """Halaman galat NETRAL — tanpa nama tabel, tanpa pesan asyncpg.

    Galat asyncpg mentah dulu tampil apa adanya ke pengguna: nama tabel, nama
    kolom, dan potongan SQL. Itu peta bagi siapa pun yang membacanya, dan bagi
    operator ia sekadar layar yang menakutkan. Yang lengkap tetap masuk log —
    di sanalah tempatnya. Temuan QA P-S-12.
    """
    log.exception("Galat tak tertangani pada %s %s", request.method, request.url.path)
    return render(
        request, "error.html",
        pesan=("Ada gangguan di sistem. Catatan Anda mungkin belum tersimpan — "
               "coba lagi sebentar lagi, dan beri tahu Super Admin bila "
               "berulang."),
        status_code=500,
    )


@app.exception_handler(ButuhLogin)
async def _belum_masuk(request: Request, exc: ButuhLogin):
    from urllib.parse import quote

    from app.web.security import tujuan_aman

    # Path-nya sendiri sudah relatif, tetapi disaring lewat jalur yang sama
    # dengan yang dari luar: satu fungsi yang menentukan apa itu "tujuan yang
    # boleh", bukan dua aturan yang bisa berbeda.
    return RedirectResponse(
        f"/masuk?next={quote(tujuan_aman(request.url.path))}", status_code=303)


@app.exception_handler(AksesDitolak)
async def _akses_ditolak(request: Request, exc: AksesDitolak):
    return render(request, "error.html", pesan=exc.pesan, status_code=403)


@app.get("/", response_class=HTMLResponse)
async def beranda(request: Request):
    """Pintu masuk webapp: keadaan pabrik hari ini + pintu ke halaman lain.

    Angkanya diambil dari `dashboard_data` — bagian `operasional` saja, yang
    murni jumlah dan tak memuat data uang, sehingga aman dilihat operator.
    """
    akun = await akun_opsional(request)
    if akun is None:
        return RedirectResponse("/masuk", status_code=303)

    from app.services import berjalan as svc

    # Benda yang berjalan diambil dari daftar yang SAMA dengan layar Sedang
    # berjalan, bukan disusun ulang di sini. Beranda yang menghitung sendiri
    # apa yang berjalan adalah Beranda yang cepat atau lambat menyebut angka
    # yang berbeda dari layar sebelahnya — dan yang berbeda diam-diam justru
    # tak akan ada yang menyadarinya.
    from app.web.layar import MEJA as V_MEJA
    from app.web.layar import gudang1, petak_beranda

    view = getattr(request.state, "view", "tamu")
    o, jalan, petak = {}, svc.Berjalan(), []
    papan = None
    # Sesi terpisah: kegagalan satu kueri tidak membatalkan pembacaan
    # bagian lain, dan hasil gagal tidak boleh dianggap angka nol.
    muat = dict(pekerjaan=False, ringkasan=False, pengiriman=False, perhatian=False)
    pengiriman_n = None
    masuk_n = informasi_n = None
    try:
        async with SessionLocal() as db:
            jalan = await svc.untuk(db, akun.user)
            from app.services.kelompok_kerja import bagi
            kerja = bagi(jalan)
            masuk_n, informasi_n = len(kerja.masuk), len(kerja.informasi)
            muat['pekerjaan'] = True
    except Exception:
        log.exception("Beranda: pekerjaan gagal dimuat")
    angka = None
    try:
        async with SessionLocal() as db:
            if gudang1(view):
                o = (await dashboard_data(db)).get("operasional", {}) or {}
            if view in V_MEJA:
                from app.services import beranda as svc_beranda
                angka = await svc_beranda.angka_gudang(db)
            petak = await petak_beranda(db, view, o, angka=angka)
            muat['ringkasan'] = True
    except Exception:
        log.exception("Beranda: ringkasan gagal dimuat")
    if view in V_MEJA and muat['pekerjaan'] and muat['ringkasan']:
        try:
            async with SessionLocal() as db:
                papan = await svc_beranda.papan(db, jalan.berjalan + jalan.transit,
                                                jalan.meja, angka=angka)
                muat['perhatian'] = True
        except Exception:
            log.exception("Beranda: peringatan pabrik gagal dimuat")
    try:
        from app.services import barang_keluar as svc_keluar
        async with SessionLocal() as db:
            pengiriman_n = len(await svc_keluar.menunggu_muat(db, akun.user))
            muat['pengiriman'] = True
    except Exception:
        log.exception("Beranda: pengiriman gagal dimuat")
    lencana = jalan.lencana()
    if not muat['pekerjaan']:
        for k in ('MENUNGGU','BERJALAN','BARANG_MASUK','PEKERJAAN','KEPUTUSAN','MUTU','PRODUK','KABAR'):
            lencana[k] = None
    # Hitungan Beranda mengikuti daftar tujuan, tanpa mengubah lencana global.
    lencana['BARANG_MASUK'] = masuk_n

    # Hanya kunci yang dikenal yang jadi pesan — teks bebas dari URL tak
    # pernah ditampilkan, supaya halaman ini tak bisa dipakai menitipkan
    # kalimat palsu lewat tautan.
    _PESAN = {"sandi-diganti": "Kata sandi berhasil diganti."}

    from app.services.beranda import sapaan_dan_tanggal
    sapaan, tanggal_tampil = sapaan_dan_tanggal(akun.user.nama if akun.user else None)

    return render(
        request, "beranda.html",
        sapaan=sapaan, tanggal_tampil=tanggal_tampil,
        PENGIRIMAN=pengiriman_n, MUAT_BERANDA=muat, INFORMASI=informasi_n,
        # Cakupan "Semua gudang" & pintu "Pesanan Jasa" (Akses cepat) — dari
        # SINI, bukan templat bersama membandingkan `VIEW in V_MEJA` sendiri.
        # `beranda.html` dipakai lebih dari satu app; templat yang menebak
        # peran adalah templat yang bisa menebak salah di app sebelah
        # (`tests/test_paket.py::test_beranda_gudang_menyerahkan_pintu_keputusan_ke_app`).
        semua_gudang=view in V_MEJA,
        # Petaknya disusun `app.web.layar` menurut view — Beranda tak lagi
        # punya satu bentuk yang dipakai bersama oleh empat peran.
        petak=petak,
        berjalan=jalan.berjalan, transit=jalan.transit,
        lama=svc._lama,
        # Membuka lembar aksi DI LAYAR INI, bukan melemparkan orang ke
        # antrean untuk menekan tombol yang tadi ia lihat di sini.
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        # Keempat angka laci + pintu yang padam, dari satu tempat: layar yang
        # menyalin tiga kata kunci cepat atau lambat lupa yang keempat.
        **lencana,
        # ── Pintu "Menunggu keputusan" (Tahap 2, beranda.html naik ke paket) ──
        #
        # Kerja meja berdiri sejajar kerja gudang, dan hanya untuk yang punya
        # meja — gerbangnya `V_MEJA`, persis seperti dulu di templat. Di
        # Operasi Gudang 2 bendera ini SELALU mati: layar Menunggu keputusan
        # hidup di Meja Administrasi, jadi di sana pintunya akan jadi tautan
        # mati ke rute yang tak ada.
        blok_keputusan=view in V_MEJA,
        # Pintu "Mutu & QC" — gerbang yang sama (kerja meja), tetapi padam saat
        # pencatatan mutu dimatikan di Pengaturan: pintu yang isinya pasti nol
        # mengajari orang mengabaikan pintu. Benderanya dari daftar yang sudah
        # di tangan, bukan kueri kedua.
        blok_mutu=view in V_MEJA and jalan.mutu_aktif,
        # Blok "Perlu perhatian" & baris gudang: hanya bila papannya dihitung.
        # `papan` bisa None karena kueri gagal (halaman ini sengaja tetap tampil
        # tanpa angka), jadi bendanya dibaca dari satu tempat — bukan dari
        # `view in V_MEJA` lagi, yang akan menggambar blok kosong saat gagal.
        blok_perhatian=papan is not None,
        perhatian=(papan.perhatian if papan else []),
        gudang=(papan.gudang if papan else []),
        rinci_keputusan=papan is not None,
        n_permintaan=(papan.n_permintaan if papan else 0),
        n_output=(papan.n_output if papan else 0),
        n_mutu=(papan.n_mutu if papan else 0),
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
    )


@app.get("/health")
async def health() -> dict:
    """Kesehatan, termasuk apakah SKEMA-nya selaras dengan kode ini.

    Sebelumnya jawabannya "ok" tanpa pernah melihat basis datanya. Layanan
    yang menyala di atas skema yang tertinggal satu migrasi menerima
    pencatatan dan menyimpannya salah — dan tak ada satu tanda pun yang
    menyebut sebabnya. Temuan QA X-04.
    """
    from app.web.skema import keadaan

    skema = await keadaan()
    return {
        "status": "ok" if skema["selaras"] else "skema-tidak-selaras",
        "skema": skema,
        "model": settings.claude_model,
    }


def _pintasan_aksi(view: str) -> tuple[tuple[str, str], ...]:
    """Tombol kecil di bawah antrean, per view.

    Membatalkan adalah satu-satunya aksi operator yang tak berwujud benda di
    gudang — yang dibatalkan bukan gabah melainkan catatan yang baru saja
    dibuat — jadi ia tak punya kartu, dan bersama katalog yang dicabut dari
    laci operator ia akan hilang sama sekali.

    Polesan kehilangan katalognya 21 September 2026, jadi dua aksinya yang
    juga tak punya kartu ikut ke sini: packing dan bekatul curah lahir SESUDAH
    proses ditutup. Admin ke atas masih mendapat katalognya di laci, jadi
    baginya daftar ini kosong — dua pintu untuk satu pekerjaan hanya membuat
    orang ragu pintu mana yang benar.
    """
    from app.web.layar import POLESAN, SELEPAN

    if view == POLESAN:
        return (("catat_packing", "Catat packing"),
                ("catat_bekatul", "Catat bekatul"),
                ("undo", "Batalkan input terakhir"))
    if view == SELEPAN:
        return (("undo", "Batalkan input terakhir"),)
    return ()


@app.get("/aksi", response_class=HTMLResponse)
async def halaman_aksi(request: Request):
    from app.web.security import butuh_akun
    from app.web.layar_pekerjaan import halaman_pekerjaan, halaman_barang_masuk
    from app.services.kelompok_kerja import PENERIMAAN
    akun = await butuh_akun(request)
    buka = request.query_params.get('buka','')
    if buka == 'perintah_keluar':
        return RedirectResponse('/barang-keluar/baru',303)
    # Grup lama bahan memuat penerimaan dan penempatan. Deep-link tindakan
    # menentukan tujuan; bookmark grup tanpa tindakan membuka tiket masuk,
    # dengan pintu ke penempatan pada Pekerjaan tetap terlihat di sana.
    if buka in PENERIMAAN or (request.query_params.get('grup')=='bahan' and not buka):
        return await halaman_barang_masuk(request,akun)
    return await halaman_pekerjaan(request,akun)


@app.get("/pekerjaan/catat-lain", response_class=HTMLResponse)
@app.get("/aksi-lain", response_class=HTMLResponse)
async def halaman_aksi_lain(request: Request):
    """Katalog aksi lengkap — yang tak berwujud benda di gudang.

    Dulu ia menggantung di bawah antrean sebagai `<details>`. Antrean adalah
    daftar BENDA; daftar kata kerja di bawahnya cuma menawarkan pintu kedua
    untuk pekerjaan yang sudah punya pintu, dan membuat antrean berhenti
    berarti apa yang ia namai.
    """
    from app.web.layar import POLESAN, SELEPAN

    akun = await akun_opsional(request)
    if akun is None:
        return RedirectResponse("/masuk", status_code=303)
    # Operator selepan dan polesan tak punya halaman ini. Pintunya sudah
    # dicabut dari laci, tetapi alamatnya tetap bisa diketik atau tersimpan
    # sebagai pintasan — dan halaman yang katanya tak ada tetapi tetap
    # terbuka adalah halaman yang tetap ada. Dialihkan, bukan ditolak:
    # seluruh pekerjaannya memang ada di antrean, jadi ke sanalah orangnya
    # diantar.
    if getattr(request.state, "view", "") in (SELEPAN, POLESAN):
        return RedirectResponse("/aksi" + ("?" + request.url.query if request.url.query else ""), status_code=303)
    from urllib.parse import urlencode
    from app.web.layar_pekerjaan import konteks_aman, siapkan_daftar_pekerjaan, daftar_tab_pekerjaan, pilihan
    from app.services.kelompok_kerja import JENIS_KERJA
    from app.web.katalog_navigasi import tujuan_duplikat

    kembali = konteks_aman(request.query_params.get("kembali")) or "/pekerjaan"
    if not kembali.startswith("/pekerjaan?") and kembali != "/pekerjaan":
        kembali = "/pekerjaan"
    buka = request.query_params.get("buka") or ""
    nilai = request.query_params.get("nilai") or ""
    tujuan, petunjuk, asal, nama = await tujuan_duplikat(buka, nilai, request.query_params)
    if tujuan:
        return RedirectResponse(tujuan, status_code=303)
    if request.url.path == "/aksi-lain":
        return RedirectResponse("/pekerjaan/catat-lain?" + urlencode(dict(request.query_params)), status_code=303)
    from urllib.parse import parse_qsl, urlsplit
    konteks_tab = dict(parse_qsl(urlsplit(kembali).query))
    for k in ('buka', 'nilai', 'halaman', 'asal', 'kategori', 'grup', 'informasi'):
        konteks_tab.pop(k, None)
    tab_tindakan = '/pekerjaan?' + urlencode({**konteks_tab, 'tab': 'tindakan'})
    tab_berjalan = '/pekerjaan?' + urlencode({**konteks_tab, 'tab': 'berjalan'})
    permintaan_tab = Request({**request.scope, 'query_string': urlencode(konteks_tab).encode()})
    b, kelompok, _ = await siapkan_daftar_pekerjaan(permintaan_tab, akun.user)
    _, _, _, total_tindakan, total_jalan = daftar_tab_pekerjaan(
        kelompok, pilihan(permintaan_tab, 'kepemilikan', {'jasa', 'pabrik'}),
        pilihan(permintaan_tab, 'gudang', {'g1', 'g2'}),
        pilihan(permintaan_tab, 'jenis', dict(JENIS_KERJA)))
    return render(request, "aksi_lain.html", layar="pekerjaan", kembali=kembali,
                  tab_tindakan=tab_tindakan, tab_berjalan=tab_berjalan,
                  total_tindakan=total_tindakan, total_jalan=total_jalan,
                  breadcrumb_induk={"alamat": kembali, "nama": "Pekerjaan"},
                  petunjuk=petunjuk, asal_tindakan=asal, nama_asal=nama,
                  buka="" if petunjuk else buka, nilai=nilai,
                  **b.lencana())


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, token: str = Query("")) -> HTMLResponse:
    """Dashboard produksi staff (web). Dilindungi token rahasia.

    **Tokennya lebih baik dikirim sebagai header `X-Dashboard-Token`.** Yang
    ada di query string ikut tertulis di log akses, di riwayat peramban, dan
    di header Referer saat halamannya menaut ke mana pun — tiga tempat yang
    tak satu pun dianggap rahasia oleh siapa pun. Query string tetap diterima
    karena tautan yang sudah beredar masih dipakai; header didahulukan.
    Temuan QA P-S-14.

    Perbandingannya konstan-waktu: `!=` berhenti di huruf pertama yang
    berbeda, dan selisih waktunya cukup untuk menebak token huruf demi huruf.
    """
    if not settings.dashboard_token:
        raise HTTPException(status_code=404, detail="Dashboard web tidak aktif.")
    dikirim = request.headers.get("x-dashboard-token") or token or ""
    if not hmac.compare_digest(dikirim, settings.dashboard_token):
        raise HTTPException(status_code=403, detail="Token tidak valid.")
    async with SessionLocal() as db:
        data = await dashboard_data(db)
    return HTMLResponse(render_dashboard_html(data))
