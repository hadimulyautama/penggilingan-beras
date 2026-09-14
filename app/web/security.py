"""Keamanan webapp produksi: sesi cookie dan penjaga peran.

Sandi, bentuk token, dan keputusan "boleh masuk?" bukan lagi milik berkas
ini: sejak Tahap 2 rancang ulang (13 September 2026) semuanya di paket
bersama `hmu_identitas` — sandi (`sandi`), token (`token`), akun (`model`),
dan pintu (`masuk`, `pintu`) — yang dipakai timbangan, Meja, Gudang 2, dan
Kantor juga. Yang tinggal di sini: kunci HMAC milik aplikasi ini, cookie,
umur sesi per jenis perangkat, jalur header Meja, "lihat sebagai", view, dan
dependency FastAPI. Nama-nama lama (`hash_sandi`, `buat_token`, …) diekspor
ulang supaya pemakainya tak perlu berubah.

Peran TIDAK disimpan pada akun. Ia dibaca dari `users` lewat relasi,
sehingga tak mungkin berbeda antara master dan webapp.
"""
from __future__ import annotations

import logging
import os

from fastapi import Depends, Request

from app.config import settings
from app.database import SessionLocal
from app.models import ProduksiAkun
from hmu_identitas import masuk as _masuk
from hmu_identitas import peran as P
from hmu_identitas import token as _token
from hmu_identitas.sandi import (HASH_TIRUAN, cek_sandi, cek_sandi_async,  # noqa: F401
                                 hash_sandi, sandi_acak)
from hmu_identitas.token import MAKS_ID as _MAKS_ID  # noqa: F401
from hmu_identitas.token import _b64d, _b64e  # noqa: F401  (dipakai uji lama)

log = logging.getLogger("web.security")

NAMA_COOKIE = "produksi_sesi"

#: Daftar nama pengguna yang PERNAH masuk di perangkat ini — bukan rahasia,
#: bukan token. Gunanya menghapus pengetikan berulang di perangkat gudang:
#: operator memilih namanya lalu hanya mengetik sandi. Isinya sengaja cuma
#: nama pengguna, dan hanya dibaca server saat merender halaman masuk.
COOKIE_PERANGKAT = "produksi_perangkat"
MAKS_NAMA_PERANGKAT = 4

class ButuhLogin(Exception):
    """Belum login — pengguna diarahkan ke halaman masuk."""


class AksesDitolak(Exception):
    """Sudah login tetapi peran tidak mencukupi."""

    def __init__(self, pesan: str = "Halaman ini tidak tersedia untuk peran Anda."):
        super().__init__(pesan)
        self.pesan = pesan


# ─────────────────────────── Sesi ───────────────────────────

_KUNCI_SEMENTARA: bytes | None = None


def _kunci() -> bytes:
    rahasia = settings.secret_key
    if not rahasia:
        # ── Di SERVER ini kekeliruan, bukan keadaan yang boleh berlanjut ──
        #
        # Kunci acak per proses berarti seluruh sesi hangus tiap deploy, dan
        # itu bukan sekadar merepotkan: ia membuat kekeliruan konfigurasi
        # tampak seperti gangguan biasa, sehingga tak pernah diperbaiki.
        # Peringatan di log sudah ada sejak dulu dan tak pernah dibaca siapa
        # pun. Temuan QA P-S-16.
        if settings.lingkungan_produksi:
            raise RuntimeError(
                "SECRET_KEY kosong. Di server, kunci penanda-tangan sesi wajib "
                "disetel — tanpanya semua orang keluar sendiri tiap deploy. "
                "Setel SECRET_KEY lalu jalankan ulang."
            )
        # Di laptop: kunci acak per proses sudah cukup, dan pagar yang
        # menghalangi pengembangan akan dimatikan orang.
        global _KUNCI_SEMENTARA
        if _KUNCI_SEMENTARA is None:
            _KUNCI_SEMENTARA = os.urandom(32)
            log.warning(
                "SECRET_KEY belum diset — memakai kunci sementara; semua sesi "
                "login akan hangus setiap kali server restart."
            )
        return _KUNCI_SEMENTARA
    return _token.kunci_dari(rahasia)


def umur_sesi_detik(akun: ProduksiAkun) -> int:
    """Umur sesi menurut jenis perangkat.

    HP pribadi: panjang — membuka aplikasi lagi tidak boleh meminta sandi,
    karena pencatatan terjadi sambil berdiri di dekat mesin dan setiap
    hambatan kecil berujung pencatatan yang ditunda lalu dikarang.

    Perangkat bersama: pendek — supaya pekerjaan tidak tercatat atas nama
    orang yang memakainya sebelum Anda.
    """
    if akun.sesi_pendek:
        return settings.sesi_bersama_menit * 60
    return settings.sesi_hari * 24 * 3600


def buat_token(akun: ProduksiAkun) -> str:
    """Token sesi bertanda tangan (bentuknya milik `hmu_identitas.token`).

    `v` adalah versi token akun. Ia naik saat orangnya keluar dari semua
    perangkat, saat sandinya diganti atau direset, dan saat perannya berubah —
    dan token yang membawa versi lama berhenti berlaku saat itu juga. Temuan
    QA P-S-05.
    """
    return _token.buat_token(_kunci(), akun_id=int(akun.id),
                             versi=int(getattr(akun, "token_version", 1) or 1),
                             umur_detik=umur_sesi_detik(akun))


def baca_token(token: str | None) -> tuple[int, int] | None:
    """(akun_id, versi) bila token sah & belum kedaluwarsa; selain itu None.
    Tak pernah melempar (QA P-S-12)."""
    d = _token.baca_token(_kunci(), token)
    return None if d is None else (d["akun_id"], d["versi"])


def token_masih_berlaku(dibaca: tuple[int, int] | None, *, versi_akun: int) -> bool:
    """Apakah token yang sudah dibaca masih sepadan dengan versi akunnya."""
    return dibaca is not None and dibaca[1] >= int(versi_akun or 1)


def tujuan_aman(nilai: str | None) -> str:
    """Alamat tujuan setelah masuk — hanya path di aplikasi ini sendiri.

    Halaman masuk yang mengantar orang ke situs lain adalah halaman masuk yang
    bisa dipakai memanen sandi: alamat yang diklik benar, tampilannya benar,
    dan yang terbuka berikutnya bukan milik kita. `//evil.example` adalah
    bentuk yang paling sering terlewat — peramban membacanya sebagai alamat
    lengkap tanpa skema, bukan sebagai path. Temuan QA P-S-06.
    """
    v = (nilai or "").strip()
    if not v.startswith("/"):
        return "/"
    # Satu garis miring, dan yang kedua bukan garis miring maupun backslash.
    if v[1:2] in ("/", "\\"):
        return "/"
    if any(c in v for c in ("\r", "\n", "\\")):
        return "/"
    return v


# ─────────────────────────── Dependency ───────────────────────────

def akun_dari_meja(request: Request) -> tuple[int, int] | None:
    """(id akun, versi token) dari header service Meja — atau None.

    Meja Administrasi (repo `meja/`) adalah aplikasi lain, tetapi ORANGNYA
    sama: akun `produksi_akun`, peran di `users`. Ia masuk lewat
    `/internal/meja/masuk`, lalu setiap permintaan berikutnya membawa token
    service (`X-Internal-Token`), nomor akun (`X-Meja-Akun`), dan versi token
    yang ia terima saat masuk (`X-Meja-Versi`). Versi itulah yang membuat
    "keluar dari semua perangkat", ganti sandi, dan penonaktifan ikut memutus
    sesi Meja — aturannya SATU dengan cookie, bukan salinan yang bisa
    tertinggal.

    Tokennya HARUS cocok dulu; tanpa itu header akun apa pun diabaikan. Yang
    bisa memalsukan nomor akun hanyalah yang memegang token service — dan
    yang memegangnya adalah Meja sendiri.
    """
    from app.web import csrf as _csrf

    if not _csrf.dari_meja(request.headers):
        return None
    try:
        akun_id = int(request.headers.get("x-meja-akun", ""))
        versi = int(request.headers.get("x-meja-versi", "") or 1)
    except ValueError:
        return None
    return akun_id, versi


async def akun_opsional(request: Request) -> ProduksiAkun | None:
    """Akun dari cookie sesi — atau dari header service Meja — atau None.
    Tidak pernah melempar error."""
    dibaca = baca_token(request.cookies.get(NAMA_COOKIE))
    lewat_meja = False
    if dibaca is None:
        dibaca = akun_dari_meja(request)
        lewat_meja = dibaca is not None
    request.state.lewat_meja = lewat_meja
    if dibaca is None:
        return None
    akun_id, versi = dibaca
    async with SessionLocal() as db:
        # SATU fungsi "boleh masuk?" untuk semua aplikasi: akun ada & aktif,
        # orangnya aktif di MASTER (`users.status` — saklar yang berlaku di
        # produksi, timbangan, Meja, Gudang 2, Kantor; QA X-11), dan versi
        # token sepadan (QA P-S-05). Peran ikut termuat (relasi joined)
        # sebelum sesi ditutup.
        akun = await _masuk.akun_aktif(db, akun_id, versi)
        if akun is None:
            return None
        _ = akun.peran

    # ── Melihat sebagai peran lain ──
    #
    # Ditimpa DI SINI, satu titik, sesudah sesi basis data ditutup: objeknya
    # sudah lepas, jadi perubahan ini tak mungkin ikut tersimpan. Seluruh
    # keputusan tampilan — tab, daftar aksi, laporan, pengaturan — bertanya
    # pada peran yang sama, jadi semuanya ikut tanpa satu pun disentuh.
    #
    # Peran asli disimpan tersendiri: ia yang menentukan siapa boleh menyamar,
    # dan ia pula yang harus tetap terbaca supaya orang bisa kembali.
    from app.web.lihat_sebagai import GUDANG, NAMA_KUKI

    request.state.peran_asli = None
    request.state.lihat_sebagai = None
    request.state.pita_samar = None
    if akun is not None and akun.user is not None:
        asli = akun.user.role
        request.state.peran_asli = asli
        # Meja menitipkan samarannya lewat header, bukan kuki — ia tak
        # punya kuki. Aturannya tetap satu: `peran_efektif` hanya menurun.
        diminta = (request.headers.get("x-meja-lihat") if lewat_meja
                   else request.cookies.get(NAMA_KUKI))
        efektif = P.peran_efektif(asli, diminta)
        if efektif != P.normal(asli):
            akun.user.role = efektif
            request.state.lihat_sebagai = efektif
        # ── Gudang yang sedang dikerjakan ──
        #
        # Operator SELALU melekat pada satu gudang untuk satu permintaan.
        # Samaran admin → operator mewarisi gudang si penyamar (yang biasanya
        # tak punya), jadi gudangnya ditetapkan dari permintaannya. Dan sejak
        # 13 Sep 2026 operator SENDIRI boleh berpindah gudang (keputusan
        # pemilik: operator saling menggantikan) — gudang utamanya hanya layar
        # pertama, bukan pagar. Hak dan layar mengikuti gudang yang dipilih.
        _, gd = P.urai(diminta)
        if P.operator_saja(efektif) and gd and P.boleh_ganti_gudang(asli):
            from sqlalchemy import select as _select
            from app.models import Warehouse as _W
            async with SessionLocal() as db2:
                wid = (await db2.execute(
                    _select(_W.id).where(_W.nama_gudang.like(GUDANG[gd]))
                )).scalars().first()
            if wid is not None and wid != akun.user.default_warehouse_id:
                akun.user.default_warehouse_id = wid
                request.state.lihat_sebagai = f"operator {gd.upper()}"
                if P.operator_saja(asli):
                    # Bukan "melihat sebagai": ia sungguh bekerja di sana.
                    # Pitanya menyebut gudangnya dengan huruf besar di atas
                    # SETIAP layar — operator yang salah kira sedang di
                    # gudang lain akan mencatat ke tempat yang salah, dan
                    # itu lebih buruk daripada tak bisa menggantikan.
                    request.state.pita_samar = (
                        f"BEKERJA DI GUDANG {gd[-1]} · bukan gudang utama Anda")
            elif wid is not None and efektif != P.normal(asli):
                request.state.lihat_sebagai = f"operator {gd.upper()}"

    # ── View: layar siapa yang sedang digambar ──
    #
    # DI SINI, sesudah peran efektif ditetapkan, bukan di tiap layar. Empat
    # layar yang masing-masing menghitung sendiri "ini operator gudang mana"
    # adalah empat tempat yang bisa menjawab berbeda — dan yang berbeda
    # diam-diam tak akan ada yang menyadarinya sampai ada operator yang
    # melihat gudang orang lain.
    from app.web.layar import TAMU, view_untuk

    request.state.view = TAMU
    if akun is not None and akun.user is not None:
        try:
            request.state.view = await view_untuk(akun.user)
        except Exception:
            # Basis data yang sedang terganggu tak boleh menjatuhkan halaman;
            # `tamu` menampilkan layar paling sedikit, bukan paling banyak.
            log.exception("View gagal ditentukan (layar tamu dipakai)")

    request.state.akun = akun
    return akun


async def butuh_akun(request: Request) -> ProduksiAkun:
    """Wajib login. Bila belum → diarahkan ke halaman masuk."""
    akun = await akun_opsional(request)
    if akun is None:
        raise ButuhLogin()
    return akun


async def butuh_staff(akun: ProduksiAkun = Depends(butuh_akun)) -> ProduksiAkun:
    """Admin ke atas — batas yang sama dengan `can_see_financials`."""
    if not akun.is_staff:
        raise AksesDitolak("Halaman ini hanya untuk staff kantor.")
    return akun


async def butuh_admin(akun: ProduksiAkun = Depends(butuh_akun)) -> ProduksiAkun:
    """Direksi ke atas.

    Namanya sempat berbohong: docstring-nya berbunyi "Super Admin saja"
    padahal `is_admin` menerima Direksi juga. Yang benar-benar hanya untuk
    Super Admin sekarang punya penjaganya sendiri di bawah.
    """
    if not akun.is_admin:
        raise AksesDitolak("Halaman ini hanya untuk Direksi ke atas.")
    return akun


async def ada_superadmin() -> bool:
    """Adakah satu pun akun Super Admin yang masih AKTIF (akun DAN orangnya).

    Aktif, bukan sekadar terdaftar: Super Admin yang dinonaktifkan tak bisa
    membuka pintu apa pun, jadi menganggapnya ada sama saja mengunci pabrik
    atas nama orang yang tak bisa datang.
    """
    async with SessionLocal() as db:
        return await _masuk.ada_superadmin_aktif(db)


async def butuh_super(akun: ProduksiAkun = Depends(butuh_akun)) -> ProduksiAkun:
    """Super Admin saja — mengelola ORANG, AKUN, dan ALAT.

    Batas ini tertulis di daftar peran sejak awal: Super Admin = "semua di
    atas, ditambah mengelola orang, akun, dan alat". Sampai sekarang ia cuma
    keterangan; gerbangnya menerima Direksi juga.

    Ia bukan soal kerapian melainkan soal tangga. Yang bisa mengelola akun
    bisa mengubah peran — termasuk perannya sendiri — jadi selama Direksi
    boleh masuk ke sini, tangganya tak punya puncak: satu ketukan dan ia
    Super Admin. Menutup pintunya menutup jalan itu sekaligus.

    **Kecuali belum ada Super Admin sama sekali.** Pabrik yang seluruh
    akunnya Direksi tak punya siapa pun yang bisa mengangkat Super Admin
    pertama — dan pintu satu-satunya menuju ke sana adalah pintu ini. Kunci
    yang ditinggal di dalam rumah. Maka selama tak ada satu pun Super Admin
    AKTIF, Direksi diterima.

    Itu tidak melemahkan kuncinya. Untuk sampai ke keadaan "tak ada Super
    Admin", seseorang harus menurunkan atau menonaktifkan Super Admin
    terakhir — dan itu hanya bisa dikerjakan DI SINI, di balik pintu yang
    baru saja ditutup untuknya. Jalan pintasnya lewat penjaga "akun tertinggi
    terakhir", yang menolak penurunan itu.

    Sengaja BUKAN diselesaikan lewat basis data. Pemulihan yang menuntut
    seseorang membuka Postgres berarti pabrik berhenti sampai orang itu
    sempat — dan orang itu selama ini saya.
    """
    if not akun.is_super and not (akun.is_admin and not await ada_superadmin()):
        raise AksesDitolak(
            "Halaman ini hanya untuk Super Admin — mengelola orang, akun, "
            "dan alat.")
    return akun


def baca_nama_perangkat(nilai: str | None) -> list[str]:
    """Nama pengguna yang tercatat pernah masuk di perangkat ini."""
    if not nilai:
        return []
    keluar: list[str] = []
    for bagian in nilai.split(","):
        nama = bagian.strip().lower()
        # Saring ketat: isi cookie datang dari peramban, jadi tak pernah
        # dipercaya sebagai apa pun selain kandidat nama pengguna.
        if nama and nama.isascii() and nama.replace("_", "").replace("-", "").isalnum():
            if nama not in keluar:
                keluar.append(nama)
    return keluar[:MAKS_NAMA_PERANGKAT]


def tulis_nama_perangkat(nilai: str | None, username: str) -> str:
    """Taruh `username` di depan daftar perangkat, buang duplikat."""
    daftar = [username] + [n for n in baca_nama_perangkat(nilai) if n != username]
    return ",".join(daftar[:MAKS_NAMA_PERANGKAT])


async def ada_akun() -> bool:
    """True bila sudah ada akun webapp — dipakai untuk pengaturan awal."""
    from sqlalchemy import func, select

    async with SessionLocal() as db:
        return bool((await db.execute(
            select(func.count(ProduksiAkun.id))
        )).scalar_one())
