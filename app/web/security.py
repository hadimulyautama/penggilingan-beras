"""Keamanan webapp produksi: sandi, sesi cookie, dan penjaga peran.

Tanpa dependensi tambahan — `hashlib.scrypt` dari pustaka standar dan cookie
bertanda tangan HMAC-SHA256. Polanya menyalin `app/timbangan/security.py` di
repo timbangan yang sudah berjalan di pos timbang; disamakan dengan sengaja
supaya orang yang memperbaiki salah satunya langsung paham yang lain.

Perbedaannya satu: peran TIDAK disimpan pada akun. Ia dibaca dari `users` lewat
relasi, sehingga tak mungkin berbeda antara master dan webapp.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import ProduksiAkun

log = logging.getLogger("web.security")

NAMA_COOKIE = "produksi_sesi"

#: Daftar nama pengguna yang PERNAH masuk di perangkat ini — bukan rahasia,
#: bukan token. Gunanya menghapus pengetikan berulang di perangkat gudang:
#: operator memilih namanya lalu hanya mengetik sandi. Isinya sengaja cuma
#: nama pengguna, dan hanya dibaca server saat merender halaman masuk.
COOKIE_PERANGKAT = "produksi_perangkat"
MAKS_NAMA_PERANGKAT = 4

# Parameter scrypt: seimbang antara aman & ringan untuk server kecil.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1


class ButuhLogin(Exception):
    """Belum login — pengguna diarahkan ke halaman masuk."""


class AksesDitolak(Exception):
    """Sudah login tetapi peran tidak mencukupi."""

    def __init__(self, pesan: str = "Halaman ini tidak tersedia untuk peran Anda."):
        super().__init__(pesan)
        self.pesan = pesan


# ─────────────────────────── Sandi ───────────────────────────

def hash_sandi(sandi: str) -> str:
    """Hash sandi → 'scrypt$n$r$p$salt$hash' (salt acak per pengguna)."""
    if not sandi or len(sandi) < 6:
        raise ValueError("Kata sandi minimal 6 karakter.")
    salt = secrets.token_bytes(16)
    kunci = hashlib.scrypt(
        sandi.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${kunci.hex()}"


def cek_sandi(sandi: str, tersimpan: str) -> bool:
    """Verifikasi sandi terhadap hash tersimpan (tahan timing attack)."""
    try:
        skema, n, r, p, salt_hex, hash_hex = (tersimpan or "").split("$")
        if skema != "scrypt":
            return False
        kunci = hashlib.scrypt(
            (sandi or "").encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(kunci.hex(), hash_hex)


#: Hash yang TIDAK pernah cocok dengan sandi apa pun, dipakai saat nama
#: penggunanya tak dikenal.
#:
#: Tanpa ini, nama yang ada dijawab dalam ~55 ms (scrypt dijalankan) dan nama
#: yang tak ada dalam ~5 ms (tak ada yang dijalankan). Selisih itu adalah
#: daftar nama pengguna perusahaan, terbuka bagi siapa pun yang mau
#: mengukurnya. Temuan QA P-S-13.
#:
#: Dihitung sekali saat modul dimuat, dari sandi acak yang langsung dibuang.
HASH_TIRUAN = hash_sandi(secrets.token_urlsafe(24))


async def cek_sandi_async(sandi: str, tersimpan: str) -> bool:
    """`cek_sandi` di threadpool — scrypt memakan ~50 ms CPU.

    Dijalankan langsung di event loop, dua belas permintaan masuk bersamaan
    menahan SELURUH aplikasi: QA mengukur /health naik dari 4 ms ke 119 ms
    sementara orang-orang mengetik sandinya. Yang tersendat bukan halaman
    masuk saja, melainkan setiap layar yang sedang dibuka siapa pun.
    Temuan QA P-S-04.
    """
    import asyncio

    return await asyncio.to_thread(cek_sandi, sandi, tersimpan)


def sandi_acak(panjang: int = 10) -> str:
    """Sandi awal yang mudah dibacakan lewat telepon — tanpa huruf/angka rancu."""
    abjad = "abcdefghjkmnpqrstuvwxyz23456789"  # tanpa i l o 0 1
    return "".join(secrets.choice(abjad) for _ in range(panjang))


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
    return hashlib.sha256(rahasia.encode()).digest()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


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


#: Batas atas nomor akun yang masuk akal. Id di luar rentang ini dulu sampai
#: ke basis data apa adanya dan pulang sebagai galat asyncpg mentah — yang
#: tampil ke pengguna sebagai halaman 500 berisi nama tabel. Temuan QA P-S-12.
_MAKS_ID = 2 ** 31 - 1


def buat_token(akun: ProduksiAkun) -> str:
    """Token sesi bertanda tangan: <payload>.<signature>.

    `v` adalah versi token akun. Ia naik saat orangnya keluar dari semua
    perangkat, saat sandinya diganti atau direset, dan saat perannya berubah —
    dan token yang membawa versi lama berhenti berlaku saat itu juga. Tanpa
    angka ini, token yang sudah beredar tak bisa ditarik kembali oleh tindakan
    apa pun: "keluar" hanya menghapus cookie di perangkat yang menekannya,
    sementara perangkat lain tetap masuk sampai 30 hari. Temuan QA P-S-05.
    """
    kedaluwarsa = datetime.now(timezone.utc) + timedelta(
        seconds=umur_sesi_detik(akun)
    )
    payload = _b64e(json.dumps(
        {"sub": int(akun.id), "exp": int(kedaluwarsa.timestamp()),
         "v": int(getattr(akun, "token_version", 1) or 1)},
        separators=(",", ":"),
    ).encode())
    tanda = _b64e(hmac.new(_kunci(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{tanda}"


def baca_token(token: str | None) -> tuple[int, int] | None:
    """(akun_id, versi) bila token sah & belum kedaluwarsa; selain itu None.

    **Tak pernah melempar.** Cookie datang dari luar, jadi isinya bisa apa
    saja — termasuk huruf non-ASCII, yang dulu menjatuhkan `compare_digest`
    dengan TypeError dan membuat SETIAP halaman menjawab 500, bukan hanya
    halaman masuk. Temuan QA P-S-12.
    """
    if not token or "." not in token:
        return None
    try:
        payload, _, tanda = token.partition(".")
        harapan = _b64e(hmac.new(_kunci(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(tanda, harapan):
            return None
        data = json.loads(_b64d(payload))
        if int(data["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            return None
        akun_id = int(data["sub"])
        if not 0 < akun_id <= _MAKS_ID:
            return None
        # Token lama (dibuat sebelum kolom versi ada) dianggap versi 1: deploy
        # tak boleh memutus semua orang sekaligus, hanya mereka yang versinya
        # memang sudah dinaikkan sesudahnya.
        return akun_id, int(data.get("v", 1) or 1)
    except (ValueError, KeyError, TypeError, UnicodeError, AttributeError):
        return None


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

async def akun_opsional(request: Request) -> ProduksiAkun | None:
    """Akun dari cookie sesi, atau None. Tidak pernah melempar error."""
    dibaca = baca_token(request.cookies.get(NAMA_COOKIE))
    if dibaca is None:
        return None
    akun_id, _versi = dibaca
    async with SessionLocal() as db:
        akun = (
            await db.execute(
                select(ProduksiAkun).where(
                    ProduksiAkun.id == akun_id,
                    ProduksiAkun.status == "aktif",
                )
            )
        ).scalars().first()
        if akun is not None:
            # ── Tiga pemeriksaan yang dulu tak ada satu pun ──
            #
            # Versi token: token yang dibuat sebelum orangnya keluar dari
            # semua perangkat, mengganti sandi, atau perannya berubah sudah
            # bukan miliknya lagi.
            #
            # Status di MASTER: dinonaktifkan di `users` berarti orangnya
            # tidak lagi bekerja di sini, dan itu berlaku untuk ketiga
            # aplikasi. Sebelumnya yang diperiksa hanya status akun
            # produksinya sendiri. Temuan QA P-S-05 & X-11.
            if not token_masih_berlaku(dibaca, versi_akun=akun.token_version):
                return None
            if akun.user is None or (akun.user.status or "").lower() != "aktif":
                return None
            # Peran ikut termuat (relasi lazy="joined") sebelum sesi ditutup.
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
    from app.web.lihat_sebagai import GUDANG, NAMA_KUKI, peran_efektif, urai

    request.state.peran_asli = None
    request.state.lihat_sebagai = None
    if akun is not None and akun.user is not None:
        asli = akun.user.role
        request.state.peran_asli = asli
        diminta = request.cookies.get(NAMA_KUKI)
        efektif = peran_efektif(asli, diminta)
        if efektif != (asli or "").strip().lower():
            akun.user.role = efektif
            request.state.lihat_sebagai = efektif
            # Operator SELALU melekat pada satu gudang. Tanpa ini, samaran
            # mewarisi gudang milik yang menyamar — dan akun admin biasanya
            # tak punya gudang default sama sekali, sehingga layar Catat
            # tampil KOSONG: "Tidak ada aksi untuk peran Anda".
            _, gd = urai(diminta)
            if efektif == "operator" and gd:
                from sqlalchemy import select as _select
                from app.models import Warehouse as _W
                async with SessionLocal() as db2:
                    wid = (await db2.execute(
                        _select(_W.id).where(_W.nama_gudang.like(GUDANG[gd]))
                    )).scalars().first()
                if wid is not None:
                    akun.user.default_warehouse_id = wid
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
    """Adakah satu pun akun Super Admin yang masih AKTIF.

    Aktif, bukan sekadar terdaftar: Super Admin yang dinonaktifkan tak bisa
    membuka pintu apa pun, jadi menganggapnya ada sama saja mengunci pabrik
    atas nama orang yang tak bisa datang.
    """
    from sqlalchemy import func, select as _select

    from app.models import ProduksiAkun as _A, User as _U

    async with SessionLocal() as db:
        n = (await db.execute(
            _select(func.count(_A.id))
            .join(_U, _U.id == _A.user_id)
            .where(_A.status == "aktif", _U.role == "superadmin")
        )).scalar() or 0
    return n > 0


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
    from sqlalchemy import func

    async with SessionLocal() as db:
        return bool((await db.execute(
            select(func.count(ProduksiAkun.id))
        )).scalar_one())
