"""Tiga tombol pengelolaan akun benar-benar ditekan, lewat HTTP.

Temuan QA R-P-01 & R-P-07, 12 September 2026.

Sampai hari ini tak ada satu uji pun yang MENJALANKAN `/pengguna/buat`,
`/pengguna/reset`, atau `/pengguna/status`. Yang ada hanya uji yang membaca
fungsi pembantunya. Akibatnya sebuah `import` yang menunjuk modul salah lolos
ke pabrik: ketiga rute itu 500, dan tak ada yang berbunyi sampai Super Admin
menekan tombolnya.

Maka ujinya lewat HTTP sungguhan dan basis data sungguhan. `ImportError` di
dalam fungsi hanya muncul saat fungsinya dipanggil, dan `NOT NULL` hanya
muncul saat barisnya benar-benar ditulis — keduanya tak terlihat dari
pembacaan kode.
"""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.asyncio


async def _super(pg, *, username: str = "bos", sandi: str = "rahasia123",
                 harus_ganti: bool = False, mode: str = "pribadi") -> int:
    """Satu Super Admin yang sudah masuk — pemegang ketiga tombol itu."""
    from app.models import ProduksiAkun, User
    from app.web.security import hash_sandi

    async with pg() as db:
        orang = User(nama="Bos Uji", role="superadmin", status="aktif")
        db.add(orang)
        await db.flush()
        akun = ProduksiAkun(
            user_id=orang.id, username=username,
            password_hash=hash_sandi(sandi), mode_perangkat=mode,
            status="aktif", harus_ganti_sandi=harus_ganti,
        )
        db.add(akun)
        await db.commit()
        await db.refresh(akun)
        return akun.id


async def _orang_biasa(pg, *, nama: str = "Budi Operator") -> int:
    from app.models import User

    async with pg() as db:
        u = User(nama=nama, role="operator", status="aktif")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _token(pg, akun_id: int) -> str:
    from app.models import ProduksiAkun
    from app.web.security import buat_token

    async with pg() as db:
        return buat_token(await db.get(ProduksiAkun, akun_id))


def _klien(token: str) -> httpx.AsyncClient:
    from app.main import app
    from app.web import csrf, security

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji")
    t = csrf.terbitkan_baru()
    c.cookies.set(security.NAMA_COOKIE, token)
    c.cookies.set(csrf.NAMA_COOKIE, t)
    c._csrf = t  # dipakai tiap POST di bawah
    return c


def _cookie_sesi(r: httpx.Response) -> str | None:
    """Nilai `produksi_sesi` yang AKHIRNYA dipakai peramban.

    Dibaca dari header balasan, bukan dari toples cookie klien: di sana
    cookie lama dan baru bisa hidup berdampingan, dan yang terbaca belum
    tentu yang baru saja diterbitkan.

    Yang diambil adalah Set-Cookie TERAKHIR, karena itulah yang menang di
    peramban. Satu balasan bisa membawa lebih dari satu — rutenya menerbitkan
    satu, middleware bisa menerbitkan satu lagi sesudahnya — dan justru
    urutan itulah yang bisa salah.
    """
    from app.web.security import NAMA_COOKIE

    nilai = None
    for baris in r.headers.get_list("set-cookie"):
        nama, _, sisa = baris.partition("=")
        if nama.strip() == NAMA_COOKIE:
            nilai = sisa.split(";")[0]
    return nilai


async def _jejak(pg) -> list[str]:
    """Isi kolom catatan pada activity_logs — bukti tindakannya terekam."""
    from sqlalchemy import select

    from app.models import ActivityLog

    async with pg() as db:
        baris = (await db.execute(
            select(ActivityLog).where(ActivityLog.table_name == "produksi_akun")
        )).scalars().all()
        return [b.new_value or "" for b in baris]


# ── /pengguna/buat ────────────────────────────────────────────────────────

async def test_buat_login_berhasil_dan_terekam(pg):
    aid = await _super(pg)
    uid = await _orang_biasa(pg)
    async with _klien(await _token(pg, aid)) as c:
        r = await c.post("/pengguna/buat", data={
            "user_id": uid, "username": "budi", "_csrf": c._csrf})

    assert r.status_code == 200, r.text[:400]
    # Sandi awalnya tampil sekali — itu satu-satunya kesempatan membacanya.
    assert "budi" in r.text
    jejak = await _jejak(pg)
    assert any("buat login" in j for j in jejak), jejak


# ── /pengguna/reset ───────────────────────────────────────────────────────

async def test_reset_sandi_berhasil_dan_terekam(pg):
    aid = await _super(pg)
    sasaran = await _super(pg, username="budi")
    async with _klien(await _token(pg, aid)) as c:
        r = await c.post("/pengguna/reset", data={
            "akun_id": sasaran, "_csrf": c._csrf})

    assert r.status_code == 200, r.text[:400]
    jejak = await _jejak(pg)
    assert any("reset sandi" in j for j in jejak), jejak


# ── /pengguna/status ──────────────────────────────────────────────────────

async def test_nonaktifkan_berhasil_dan_terekam(pg):
    """Tombol yang memutus akses di KETIGA aplikasi. Bila rutenya 500,
    `users.status` tak pernah tersentuh dan orangnya tetap punya akses —
    diam-diam, karena layarnya cuma menampilkan halaman galat."""
    from app.models import ProduksiAkun

    aid = await _super(pg)
    sasaran = await _super(pg, username="budi")
    async with _klien(await _token(pg, aid)) as c:
        r = await c.post("/pengguna/status", data={
            "akun_id": sasaran, "_csrf": c._csrf})

    assert r.status_code == 200, r.text[:400]
    async with pg() as db:
        akun = await db.get(ProduksiAkun, sasaran)
        assert akun.status == "nonaktif"
    jejak = await _jejak(pg)
    assert any("status" in j for j in jejak), jejak


async def test_nonaktifkan_benar_benar_memutus_ketiga_aplikasi(pg):
    """X-11 dan P-S-05 baru berlaku bila rutenya benar-benar selesai.

    Keduanya sudah ditulis sejak 11 September, dan keduanya diuji langsung ke
    fungsinya — lulus. Yang tak pernah diuji adalah jalan menuju ke sana:
    rutenya 500 sebelum sempat menyimpan apa pun, jadi di pabrik sungguhan
    `users.status` tetap 'aktif' dan tokennya tetap berlaku. Dua pagar yang
    ada di kode tetapi tak pernah terpasang.

    Maka yang diperiksa di sini AKIBATNYA, sesudah tombolnya ditekan lewat
    HTTP: saklar yang dibaca Kantor dan Timbangan ikut turun, dan token yang
    sedang beredar berhenti berlaku saat itu juga.
    """
    from app.models import ProduksiAkun, User
    from app.web.security import akun_opsional

    class _Permintaan:
        class _State:
            pass

        def __init__(self, token):
            self.cookies = {"produksi_sesi": token}
            self.state = self._State()

    aid = await _super(pg)
    sasaran = await _super(pg, username="budi")
    token_korban = await _token(pg, sasaran)
    assert await akun_opsional(_Permintaan(token_korban)) is not None, (
        "tokennya harus sah SEBELUM dinonaktifkan, kalau tidak ujinya kosong")

    async with _klien(await _token(pg, aid)) as c:
        r = await c.post("/pengguna/status", data={
            "akun_id": sasaran, "_csrf": c._csrf})
    assert r.status_code == 200, r.text[:400]

    async with pg() as db:
        akun = await db.get(ProduksiAkun, sasaran)
        orang = await db.get(User, akun.user_id)
        # X-11: satu saklar untuk ketiga aplikasi.
        assert orang.status == "nonaktif", (
            "users.status masih aktif — Kantor dan Timbangan tetap membukakan "
            "pintu untuk orang yang baru saja dinonaktifkan di pabrik")

    # P-S-05: yang sedang bekerja langsung berhenti, bukan menunggu 30 hari.
    assert await akun_opsional(_Permintaan(token_korban)) is None, (
        "token lama masih diterima sesudah akunnya dinonaktifkan")


# ── ganti sandi pertama ───────────────────────────────────────────────────

async def test_ganti_sandi_pertama_tidak_melempar_ke_halaman_masuk(pg):
    """Orang yang baru saja mengganti sandi awalnya HARUS tetap masuk.

    Versi tokennya naik pada langkah yang sama, jadi cookie yang terbit
    sesudahnya wajib membawa versi yang BENAR-BENAR tersimpan. Membawa versi
    lama artinya ia terlempar ke halaman masuk persis sesudah berhasil —
    dan yang dilihatnya adalah sandi barunya "tidak bekerja".
    """
    from app.models import ProduksiAkun
    from app.web.security import baca_token

    aid = await _super(pg, username="budi", sandi="sandiawal1",
                       harus_ganti=True)
    async with _klien(await _token(pg, aid)) as c:
        r = await c.post("/ganti-sandi", data={
            "sandi_baru": "sandibaru9", "ulangi": "sandibaru9",
            "_csrf": c._csrf})
        assert r.status_code in (302, 303), r.text[:400]
        kue = _cookie_sesi(r)

    assert kue, "cookie sesi tidak diperbarui"
    dibaca = baca_token(kue)
    assert dibaca is not None, "token baru tidak sah"
    async with pg() as db:
        akun = await db.get(ProduksiAkun, aid)
        tersimpan = akun.token_version or 1
    assert dibaca[1] == tersimpan, (
        f"cookie membawa versi {dibaca[1]} sementara yang tersimpan "
        f"{tersimpan} — orangnya akan terlempar ke halaman masuk")

    # Dan buktinya di lapisan yang sebenarnya: permintaan berikutnya diterima.
    async with _klien(kue) as c2:
        lanjut = await c2.get("/pengguna")
    assert lanjut.status_code == 200, (
        "sesudah ganti sandi pertama, halaman berikutnya menolak sesinya")


async def test_ganti_sandi_pertama_di_perangkat_gudang_juga_tetap_masuk(pg):
    """Kasus yang sebenarnya terjadi di pabrik — dan yang lolos dari uji.

    Operator dapat `mode_perangkat="bersama"` secara bawaan, dan justru
    operatorlah yang menerima sandi awal dari Super Admin. Di jalur itu ada
    satu lapis lagi: middleware perpanjang-sesi menerbitkan ULANG cookie
    sesi dari objek akun yang dimuat di AWAL permintaan — versi tokennya
    masih yang lama. Header itu terpasang SESUDAH milik rutenya, jadi
    peramban memakai yang terakhir: token usang menimpa token yang benar.

    Akibatnya persis yang disebut komentar di rute ganti-sandi sebagai hal
    yang ingin dicegah. Temuan QA R-P-07.
    """
    from app.models import ProduksiAkun
    from app.web.security import baca_token

    aid = await _super(pg, username="opgudang", sandi="sandiawal1",
                       harus_ganti=True, mode="bersama")
    async with _klien(await _token(pg, aid)) as c:
        r = await c.post("/ganti-sandi", data={
            "sandi_baru": "sandibaru9", "ulangi": "sandibaru9",
            "_csrf": c._csrf})
        assert r.status_code in (302, 303), r.text[:400]
        kue = _cookie_sesi(r)

    async with pg() as db:
        tersimpan = (await db.get(ProduksiAkun, aid)).token_version or 1

    dibaca = baca_token(kue or "")
    assert dibaca is not None, "token terakhir tidak sah"
    assert dibaca[1] == tersimpan, (
        f"cookie TERAKHIR membawa versi {dibaca[1]} sementara yang tersimpan "
        f"{tersimpan} — operatornya terlempar ke halaman masuk")

    async with _klien(kue) as c2:
        lanjut = await c2.get("/")
    assert lanjut.status_code == 200, (
        "sesudah ganti sandi pertama, permintaan berikutnya ditolak")
