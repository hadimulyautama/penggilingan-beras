"""Kelola akun webapp — hanya Super Admin.

Akun TIDAK pernah dihapus, hanya dinonaktifkan: `created_by` pada ribuan
catatan lama menunjuk ke `users.id`, dan orangnya harus tetap bisa dikenali
bertahun-tahun setelah ia berhenti.

Sandi awal dibuatkan sistem, dibacakan sekali kepada orangnya, dan wajib
diganti saat ia pertama masuk — sehingga Super Admin tidak ikut memegang sandi
orang lain.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from fastapi import APIRouter, Depends, Form, Request

from app.database import SessionLocal
from app.models import ProduksiAkun
from app.models.akun import mode_bawaan
from app.web.security import butuh_admin, hash_sandi, sandi_acak
from app.web.tampilan import redirect, render
from hmu_core import User

router = APIRouter(tags=["webapp"])

_MODE = ("pribadi", "bersama")
#: Peran yang boleh dipilih. Sengaja sama persis dengan `users.role` di master
#: — menambah tingkat baru di sini tanpa menambahnya di sana akan membuat orang
#: terdaftar dengan peran yang tak dikenali pemeriksa hak akses mana pun.
PERAN = (
    ("operator", "Operator", "Mencatat pekerjaan di gudangnya. Tidak melihat angka uang."),
    ("admin", "Admin", "Seluruh pencatatan, verifikasi harga, dan laporan uang."),
    ("superadmin", "Super Admin", "Semua di atas, ditambah mengelola orang, "
                                  "akun, dan alat. Tingkat tertinggi."),
)



def _saran_username(nama: str) -> str:
    """Tebakan nama pengguna dari nama orang: kata pertama, huruf kecil.

    Super Admin tetap boleh menggantinya. Gunanya menghapus satu keputusan kecil
    yang tak ada nilainya — dan mencegah kebun binatang nama pengguna yang
    formatnya berbeda-beda tergantung siapa yang sedang membuatkan akun.
    """
    kata = ["".join(c for c in k.lower() if c.isalnum()) for k in nama.split()]
    kata = [k for k in kata if k]
    # Lewati inisial: "M. Yusuf" harus jadi "yusuf", bukan "m".
    for k in kata:
        if len(k) >= 3:
            return k[:20]
    return "".join(kata)[:20]


async def _muat(pesan_ok: str | None = None, pesan_err: str | None = None,
                sandi_awal: dict | None = None) -> dict:
    """Daftar akun + orang di `users` yang belum punya akun."""
    async with SessionLocal() as db:
        akun_list = (await db.execute(
            select(ProduksiAkun).options(selectinload(ProduksiAkun.user))
            .order_by(ProduksiAkun.username)
        )).scalars().all()
        sudah = {a.user_id for a in akun_list}
        belum = [
            u for u in (await db.execute(
                select(User).where(User.status == "aktif").order_by(User.nama)
            )).scalars().all()
            if u.id not in sudah
        ]
    return {"akun_list": akun_list, "kembali": "/", "PERAN": PERAN,
            "belum": [{"id": u.id, "nama": u.nama, "role": u.role,
                       "saran": _saran_username(u.nama)} for u in belum],
            "pesan_ok": pesan_ok, "pesan_err": pesan_err, "sandi_awal": sandi_awal}


@router.get("/pengguna")
async def halaman_pengguna(request: Request, _=Depends(butuh_admin)):
    return render(request, "pengguna.html", **await _muat())


@router.post("/pengguna/buat")
async def buat_akun(
    request: Request,
    user_id: int = Form(...),
    username: str = Form(...),
    _=Depends(butuh_admin),
):
    uname = username.strip().lower()
    if not uname or " " in uname or len(uname) < 3:
        return render(request, "pengguna.html",
                      **await _muat(pesan_err="Nama pengguna minimal 3 huruf, tanpa spasi."))
    sandi = sandi_acak()
    async with SessionLocal() as db:
        orang = await db.get(User, user_id)
        if orang is None:
            return render(request, "pengguna.html",
                          **await _muat(pesan_err="Orang itu tidak ada di daftar pengguna."))
        bentrok = (await db.execute(
            select(ProduksiAkun).where(ProduksiAkun.username == uname)
        )).scalars().first()
        if bentrok is not None:
            return render(request, "pengguna.html",
                          **await _muat(pesan_err=f"Nama pengguna '{uname}' sudah dipakai."))
        db.add(ProduksiAkun(
            user_id=orang.id, username=uname, password_hash=hash_sandi(sandi),
            mode_perangkat=mode_bawaan(orang.role), harus_ganti_sandi=True,
        ))
        await db.commit()
        nama = orang.nama
    # Sandi awal ditampilkan sebagai blok tersendiri, bukan diselipkan dalam
    # kalimat: ini satu-satunya kesempatan membacanya, dan yang membacanya
    # sedang berdiri di depan orangnya.
    return render(request, "pengguna.html", **await _muat(
        sandi_awal={"nama": nama, "username": uname, "sandi": sandi,
                    "judul": "Akun dibuat"}))


@router.post("/pengguna/reset")
async def reset_sandi(request: Request, akun_id: int = Form(...), _=Depends(butuh_admin)):
    sandi = sandi_acak()
    async with SessionLocal() as db:
        akun = await db.get(ProduksiAkun, akun_id)
        if akun is None:
            return render(request, "pengguna.html", **await _muat(pesan_err="Akun tidak ditemukan."))
        akun.password_hash = hash_sandi(sandi)
        akun.harus_ganti_sandi = True
        uname, nama = akun.username, akun.nama
        await db.commit()
    return render(request, "pengguna.html", **await _muat(
        sandi_awal={"nama": nama, "username": uname, "sandi": sandi,
                    "judul": "Sandi disetel ulang"}))


@router.post("/pengguna/status")
async def ubah_status(request: Request, akun_id: int = Form(...), _=Depends(butuh_admin)):
    async with SessionLocal() as db:
        akun = await db.get(ProduksiAkun, akun_id)
        if akun is None:
            return render(request, "pengguna.html", **await _muat(pesan_err="Akun tidak ditemukan."))
        akun.status = "nonaktif" if akun.status == "aktif" else "aktif"
        pesan = f"Akun '{akun.username}' sekarang {akun.status}."
        await db.commit()
    return render(request, "pengguna.html", **await _muat(pesan_ok=pesan))


@router.post("/pengguna/mode")
async def ubah_mode(
    request: Request, akun_id: int = Form(...), mode: str = Form(...),
    _=Depends(butuh_admin),
):
    if mode not in _MODE:
        return render(request, "pengguna.html", **await _muat(pesan_err="Jenis perangkat tidak dikenal."))
    async with SessionLocal() as db:
        akun = await db.get(ProduksiAkun, akun_id)
        if akun is None:
            return render(request, "pengguna.html", **await _muat(pesan_err="Akun tidak ditemukan."))
        akun.mode_perangkat = mode
        pesan = (f"Perangkat '{akun.username}' disetel ke "
                 f"{'milik gudang (sesi pendek)' if mode == 'bersama' else 'milik sendiri (sesi panjang)'}.")
        await db.commit()
    return render(request, "pengguna.html", **await _muat(pesan_ok=pesan))



@router.post("/pengguna/orang-baru")
async def orang_baru(
    request: Request,
    nama: str = Form(...),
    peran: str = Form(...),
    gudang: str = Form(""),
    akun=Depends(butuh_admin),
):
    """Daftarkan ORANG baru — bukan akunnya.

    Dua langkah, dan sengaja tidak disatukan. Mendaftarkan orang menetapkan
    perannya dan menempatkannya di gudang; membuatkan akun menyerahkan sandi
    yang harus dibacakan di depan orangnya. Menyatukan keduanya berarti sandi
    awal muncul di layar pada saat Super Admin masih mengetik nama — jauh sebelum
    orangnya berdiri di sana.

    Nomor Telegram tidak diminta. Syarat itu milik bot, yang tak punya cara
    lain mengenali penuturnya; orang yang masuk lewat layar ini dikenali dari
    kredensialnya sendiri.
    """
    from app.services.user_admin import UserAdminError, register_user

    nama = " ".join(nama.split())
    if len(nama) < 3:
        return render(request, "pengguna.html",
                      **await _muat(pesan_err="Nama minimal 3 huruf."))
    if peran not in {p[0] for p in PERAN}:
        return render(request, "pengguna.html",
                      **await _muat(pesan_err="Peran tidak dikenal."))

    async with SessionLocal() as db:
        # Nama kembar bukan kesalahan data, tetapi hampir selalu kesalahan
        # ketik — dan dua "Budi" tanpa pembeda membuat daftar akun mustahil
        # dipakai. Ditolak dengan menyebut yang sudah ada, supaya Super Admin bisa
        # memutuskan sendiri: salah ketik, atau memang dua orang.
        kembar = (await db.execute(
            select(User).where(User.nama == nama, User.status != "nonaktif")
        )).scalars().first()
        if kembar is not None:
            return render(request, "pengguna.html", **await _muat(
                pesan_err=f"'{nama}' sudah terdaftar sebagai "
                          f"{kembar.role}. Bila ini orang lain, bedakan namanya."))
        try:
            pesan = await register_user(
                db, actor=akun.user, nama=nama, role=peran,
                gudang=int(gudang) if gudang in ("1", "2") else None,
                telegram_id=None, no_hp=None, lewat_sandi=True,
            )
        except UserAdminError as e:
            return render(request, "pengguna.html",
                          **await _muat(pesan_err=str(e.args[0] if e.args else e)))
    return render(request, "pengguna.html", **await _muat(pesan_ok=pesan))


# ─────────────────────── Ubah satu akun ───────────────────────

@router.get("/pengguna/{akun_id}")
async def halaman_ubah(request: Request, akun_id: int, _=Depends(butuh_admin)):
    """Satu akun, satu halaman — mengikuti bentuk aplikasi Timbangan.

    Sebelumnya peran orang TIDAK bisa diubah setelah ia didaftarkan: operator
    yang naik jadi staff harus didaftarkan ulang sebagai orang kedua, dan
    seluruh catatan lamanya tertinggal atas nama yang pertama.
    """
    async with SessionLocal() as db:
        a = (await db.execute(
            select(ProduksiAkun).options(selectinload(ProduksiAkun.user))
            .where(ProduksiAkun.id == akun_id)
        )).scalars().first()
        if a is None:
            return render(request, "pengguna.html",
                          **await _muat(pesan_err="Akun tidak ditemukan."))
        jml_admin = await _jumlah_admin(db)
    return render(request, "pengguna_ubah.html", a=a, PERAN=PERAN, _MODE=_MODE,
                  jml_admin=jml_admin, kembali="/pengguna",
                  pesan_err=_ERR_UBAH.get(request.query_params.get("err", "")),
                  pesan_ok=_OK_UBAH.get(request.query_params.get("ok", "")))


_ERR_UBAH = {
    "nama": "Nama minimal 3 huruf.",
    "username": "Nama pengguna minimal 3 huruf, tanpa spasi.",
    "dipakai": "Nama pengguna itu sudah dipakai akun lain.",
    "peran": "Peran tidak dikenal.",
    "admin-terakhir": ("Ini satu-satunya akun tingkat tertinggi yang aktif. "
                       "Angkat orang lain dulu — kalau tidak, tak ada yang "
                       "bisa mengelola akun lagi."),
}
_OK_UBAH = {"tersimpan": "Perubahan tersimpan.", "tidak-berubah": "Tidak ada yang diubah."}


async def _jumlah_admin(db) -> int:
    """Berapa akun tingkat tertinggi yang masih aktif — penjaga agar tak tersisa nol."""
    baris = (await db.execute(
        select(ProduksiAkun).options(selectinload(ProduksiAkun.user))
        .where(ProduksiAkun.status == "aktif")
    )).scalars().all()
    return sum(1 for x in baris if x.user is not None and x.user.role == "admin")


@router.post("/pengguna/{akun_id}")
async def simpan_ubah(
    request: Request,
    akun_id: int,
    nama: str = Form(""),
    username: str = Form(""),
    peran: str = Form(""),
    mode: str = Form(""),
    akun=Depends(butuh_admin),
):
    nama = " ".join(nama.split())
    uname = username.strip().lower()
    if nama and len(nama) < 3:
        return redirect(f"/pengguna/{akun_id}?err=nama")
    if uname and (" " in uname or len(uname) < 3):
        return redirect(f"/pengguna/{akun_id}?err=username")
    if peran and peran not in {p[0] for p in PERAN}:
        return redirect(f"/pengguna/{akun_id}?err=peran")
    if mode and mode not in _MODE:
        return redirect(f"/pengguna/{akun_id}?err=peran")

    async with SessionLocal() as db:
        a = (await db.execute(
            select(ProduksiAkun).options(selectinload(ProduksiAkun.user))
            .where(ProduksiAkun.id == akun_id)
        )).scalars().first()
        if a is None or a.user is None:
            return redirect("/pengguna")

        # Menurunkan akun tertinggi terakhir mengunci semua orang di luar pengelolaan
        # akun — termasuk yang menurunkannya. Ditolak SEBELUM tersimpan, bukan
        # diperbaiki sesudahnya, karena sesudahnya tak ada yang bisa.
        if (peran and a.user.role == "admin" and peran != "admin"
                and await _jumlah_admin(db) <= 1):
            return redirect(f"/pengguna/{akun_id}?err=admin-terakhir")

        if uname and uname != a.username:
            bentrok = (await db.execute(
                select(ProduksiAkun).where(ProduksiAkun.username == uname,
                                           ProduksiAkun.id != a.id)
            )).scalars().first()
            if bentrok is not None:
                return redirect(f"/pengguna/{akun_id}?err=dipakai")

        berubah = []
        if nama and nama != a.user.nama:
            a.user.nama = nama
            berubah.append("nama")
        if uname and uname != a.username:
            a.username = uname
            berubah.append("nama pengguna")
        if peran and peran != a.user.role:
            a.user.role = peran
            berubah.append("peran")
        if mode and mode != a.mode_perangkat:
            a.mode_perangkat = mode
            berubah.append("jenis perangkat")
        if not berubah:
            return redirect(f"/pengguna/{akun_id}?ok=tidak-berubah")
        await db.commit()
    return redirect(f"/pengguna/{akun_id}?ok=tersimpan")
