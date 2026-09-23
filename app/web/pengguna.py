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
from app.web.security import butuh_super, hash_sandi, sandi_acak
from app.web.tampilan import redirect, render
from hmu_core import User
from hmu_identitas import masuk as identitas
from hmu_identitas import peran as P

router = APIRouter(tags=["webapp"])

_MODE = ("pribadi", "bersama")
#: Peran yang boleh dipilih. Sengaja sama persis dengan `users.role` di master
#: — menambah tingkat baru di sini tanpa menambahnya di sana akan membuat orang
#: terdaftar dengan peran yang tak dikenali pemeriksa hak akses mana pun.
PERAN = tuple((kode, P.LABEL[kode], ket) for kode, ket in P.PILIHAN)



#: Sebanyak-banyaknya orang tanpa akun yang ditampilkan sekaligus. Daftar
#: yang lebih panjang dari ini tak bisa dipakai memilih sambil berdiri, dan
#: yang dicari orang selalu beberapa nama teratas.
MAKS_BELUM = 50


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


def _terlalu_tinggi(pelaku, peran_sasaran: str | None) -> bool:
    """Sasaran berperan LEBIH TINGGI daripada pelaku?

    Jaring pengaman "belum ada Super Admin → Direksi diterima" ada supaya
    pabrik tak terkunci. Tetapi selama jaring itu terbentang, Direksi berdiri
    di halaman ini dengan wewenang penuh — dan dua jalur di sini tak pernah
    membandingkan tingkat sama sekali: membuatkan login, dan menyetel ulang
    sandi. Jadi ia bisa membuatkan login baru untuk orang ber-peran Super
    Admin, lalu memakai sandi awal yang ia bacakan sendiri. Temuan QA P-S-10.

    `simpan_ubah` sudah punya perbandingan ini sejak awal; yang ditambahkan
    sekarang hanyalah memakainya di dua jalur yang terlewat.
    """
    return P.terlalu_tinggi(getattr(pelaku, "peran", ""), peran_sasaran)


async def _catat(db, akun_id: int, aksi: str, sasaran: str, pelaku,
                 keterangan: str = "") -> None:
    """Tulis jejak audit untuk tindakan pengelolaan akun.

    Yang dijaga bukan pencegahannya melainkan kemungkinan menelusurinya:
    pembuatan login, reset sandi, dan penonaktifan adalah tindakan yang
    akibatnya baru terlihat berhari-hari kemudian, oleh orang lain.

    `akun_id` WAJIB dan bukan kebetulan wajib. `activity_logs.record_id`
    berstatus NOT NULL, jadi baris tanpa nomor akun tak pernah sampai ke
    basis data — dan yang gagal bukan sekadar catatannya melainkan seluruh
    transaksinya: reset sandi yang batal, penonaktifan yang tak jadi.
    Menjadikannya parameter tanpa nilai bawaan memindahkan kekeliruan itu
    dari saat tombolnya ditekan ke saat kodenya ditulis.
    """
    from app.services.activity_log import log_activity

    await log_activity(
        db, table_name="produksi_akun", record_id=akun_id, action="UPDATE",
        changed_by=getattr(pelaku, "user_id", None),
        new_value=f"{aksi} · {sasaran}" + (f" · {keterangan}" if keterangan else ""),
    )


async def _muat(pesan_ok: str | None = None, pesan_err: str | None = None,
                sandi_awal: dict | None = None) -> dict:
    """Daftar akun + orang di `users` yang belum punya akun."""
    async with SessionLocal() as db:
        akun_list = (await db.execute(
            select(ProduksiAkun).options(selectinload(ProduksiAkun.user))
            .order_by(ProduksiAkun.username)
        )).scalars().all()
        # ── Disaring di SQL, dan dibatasi ──
        #
        # Dulu seluruh tabel orang ditarik ke memori lalu disaring di Python.
        # Itu baik-baik saja selagi orangnya belasan; ia berhenti baik-baik
        # saja tanpa ada yang menyadarinya. Batasnya juga bukan hiasan: daftar
        # sepanjang ratusan nama tak bisa dipakai memilih sambil berdiri, dan
        # yang dicari orang di layar ini selalu beberapa nama teratas.
        # Temuan QA P-S-08.
        sudah = {a.user_id for a in akun_list}
        q = select(User).where(User.status == "aktif")
        if sudah:
            q = q.where(User.id.notin_(sudah))
        belum = list((await db.execute(
            q.order_by(User.nama).limit(MAKS_BELUM)
        )).scalars())
    return {"akun_list": akun_list, "kembali": "/", "PERAN": PERAN,
            "belum": [{"id": u.id, "nama": u.nama, "role": u.role,
                       "saran": _saran_username(u.nama)} for u in belum],
            # `/pengguna/<id>` hanya ada DI SINI; Meja meneruskan borangnya ke
            # rute ini dan tak punya halaman ubahnya sendiri. Templatnya satu
            # berkas di paket sejak 23 September 2026, jadi yang memutuskan
            # apakah tautan "Ubah" muncul adalah app-nya, bukan salinannya.
            "ada_ubah": True,
            "pesan_ok": pesan_ok, "pesan_err": pesan_err, "sandi_awal": sandi_awal}


@router.get("/pengguna")
async def halaman_pengguna(request: Request, _=Depends(butuh_super)):
    return render(request, "pengguna.html", **await _muat())


@router.post("/pengguna/buat")
async def buat_akun(
    request: Request,
    user_id: int = Form(...),
    username: str = Form(...),
    pelaku=Depends(butuh_super),
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
        if _terlalu_tinggi(pelaku, orang.role):
            return render(request, "pengguna.html", **await _muat(
                pesan_err=("Orang itu berperan lebih tinggi daripada Anda — "
                           "loginnya hanya bisa dibuat oleh peran yang sama "
                           "atau di atasnya.")))
        bentrok = (await db.execute(
            select(ProduksiAkun).where(ProduksiAkun.username == uname)
        )).scalars().first()
        if bentrok is not None:
            return render(request, "pengguna.html",
                          **await _muat(pesan_err=f"Nama pengguna '{uname}' sudah dipakai."))
        akun = ProduksiAkun(
            user_id=orang.id, username=uname, password_hash=hash_sandi(sandi),
            mode_perangkat=mode_bawaan(orang.role), harus_ganti_sandi=True,
        )
        db.add(akun)
        # Di-flush lebih dulu supaya jejaknya menyebut nomor akun yang
        # sesungguhnya. Tanpa itu jejak "buat login" jadi satu-satunya
        # tindakan pengelolaan akun yang tak bisa ditelusuri balik ke akunnya.
        await db.flush()
        await _catat(db, akun.id, "buat login", f"{orang.nama} ({uname})",
                     pelaku, f"peran {orang.role}")
        await db.commit()
        nama = orang.nama
    # Sandi awal ditampilkan sebagai blok tersendiri, bukan diselipkan dalam
    # kalimat: ini satu-satunya kesempatan membacanya, dan yang membacanya
    # sedang berdiri di depan orangnya.
    return render(request, "pengguna.html", **await _muat(
        sandi_awal={"nama": nama, "username": uname, "sandi": sandi,
                    "judul": "Akun dibuat"}))


@router.post("/pengguna/reset")
async def reset_sandi(request: Request, akun_id: int = Form(...),
                      pelaku=Depends(butuh_super)):
    sandi = sandi_acak()
    async with SessionLocal() as db:
        akun = await db.get(ProduksiAkun, akun_id)
        if akun is None:
            return render(request, "pengguna.html", **await _muat(pesan_err="Akun tidak ditemukan."))
        if _terlalu_tinggi(pelaku, akun.peran):
            return render(request, "pengguna.html", **await _muat(
                pesan_err=("Akun itu berperan lebih tinggi daripada Anda — "
                           "sandinya tak bisa Anda setel ulang.")))
        akun.password_hash = hash_sandi(sandi)
        akun.harus_ganti_sandi = True
        # Sandi yang disetel ulang memutus sesi lama di semua perangkat.
        # Tanpa ini, sandi lama yang sudah dicuri tetap berguna — dan justru
        # itulah alasan sandinya disetel ulang.
        akun.token_version = (akun.token_version or 1) + 1
        uname, nama = akun.username, akun.nama
        await _catat(db, akun.id, "reset sandi", f"{nama} ({uname})", pelaku)
        await db.commit()
    return render(request, "pengguna.html", **await _muat(
        sandi_awal={"nama": nama, "username": uname, "sandi": sandi,
                    "judul": "Sandi disetel ulang"}))


@router.post("/pengguna/status")
async def ubah_status(request: Request, akun_id: int = Form(...),
                      pelaku=Depends(butuh_super)):
    """Nonaktifkan / aktifkan — untuk KETIGA aplikasi sekaligus.

    Sampai 11 September 2026 ada tiga bendera nonaktif yang terpisah
    (`users.status`, `produksi_akun.status`, `timbangan_akun.status`), dan tak
    satu baris kode pun pernah menyetel yang pertama. Jadi menonaktifkan orang
    di sini tidak memutus akses Kantor maupun Timbangan: ia keluar dari
    pabrik, dan asisten Telegram-nya tetap menjawab. Temuan QA X-11.

    `users.status` adalah saklar yang sudah dibaca Kantor di setiap
    permintaan; yang kurang hanyalah sesuatu yang pernah menyetelnya.
    """
    async with SessionLocal() as db:
        akun = await db.get(ProduksiAkun, akun_id)
        if akun is None:
            return render(request, "pengguna.html", **await _muat(pesan_err="Akun tidak ditemukan."))
        if _terlalu_tinggi(pelaku, akun.peran):
            return render(request, "pengguna.html", **await _muat(
                pesan_err=("Akun itu berperan lebih tinggi daripada Anda — "
                           "statusnya tak bisa Anda ubah.")))
        aktifkan = akun.status != "aktif"
        try:
            # SATU saklar (paket identitas): `users.status` + cermin di akun
            # + versi token naik, sehingga sesi yang sedang berjalan ikut
            # putus SEKARANG — di produksi, timbangan, Meja, Gudang 2, Kantor.
            # Super Admin aktif terakhir ditolak di sana.
            await identitas.nonaktifkan(db, akun.user_id, aktif=aktifkan)
        except identitas.Tolak as e:
            return render(request, "pengguna.html", **await _muat(pesan_err=e.pesan))
        await db.refresh(akun)
        pesan = (f"Akun '{akun.username}' sekarang {akun.status} — "
                 "berlaku juga di Kantor dan Timbangan.")
        await _catat(db, akun.id, f"status → {akun.status}", akun.username,
                     pelaku, "termasuk users.status")
        await db.commit()
    return render(request, "pengguna.html", **await _muat(pesan_ok=pesan))


@router.post("/pengguna/mode")
async def ubah_mode(
    request: Request, akun_id: int = Form(...), mode: str = Form(...),
    _=Depends(butuh_super),
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
    akun=Depends(butuh_super),
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
    # Langit-langit yang sama seperti saat MENGUBAH peran. Ditulis di kedua
    # tempat karena keduanya jalan masuk yang berbeda: yang dijaga cuma satu
    # akan dilewati lewat yang lain, dan mendaftarkan orang baru berperan
    # lebih tinggi lalu masuk sebagai dia adalah jalan memutar yang sama
    # panjangnya dengan satu ketukan.
    if P.terlalu_tinggi(akun.peran, peran):
        return render(request, "pengguna.html",
                      **await _muat(pesan_err=_ERR_UBAH["terlalu-tinggi"]))

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
async def halaman_ubah(request: Request, akun_id: int, _=Depends(butuh_super)):
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
    "terlalu-tinggi": ("Peran itu di atas peran Anda sendiri. Yang bisa "
                       "mengangkat orang setinggi dirinya bisa mengangkat "
                       "dirinya sendiri."),
}
_OK_UBAH = {"tersimpan": "Perubahan tersimpan.", "tidak-berubah": "Tidak ada yang diubah."}


async def _jumlah_admin(db) -> int:
    """Berapa akun tingkat tertinggi yang masih aktif — penjaga agar tak tersisa nol."""
    baris = (await db.execute(
        select(ProduksiAkun).options(selectinload(ProduksiAkun.user))
        .where(ProduksiAkun.status == "aktif")
    )).scalars().all()
    # `is_admin`, bukan `role == "admin"`: superadmin ADA DI ATAS admin, jadi
    # ia jelas termasuk "tingkat tertinggi". Menghitungnya harfiah membuat
    # penjaga ini salah dua arah sekaligus — menolak admin terakhir yang mau
    # NAIK ke superadmin (padahal tingkatnya bertambah, bukan berkurang), dan
    # menganggap nol akun tertinggi di pabrik yang seluruh adminnya sudah
    # dinaikkan.
    return sum(1 for x in baris if x.user is not None and x.is_admin)


@router.post("/pengguna/{akun_id}")
async def simpan_ubah(
    request: Request,
    akun_id: int,
    nama: str = Form(""),
    username: str = Form(""),
    peran: str = Form(""),
    mode: str = Form(""),
    akun=Depends(butuh_super),
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

        # Menurunkan akun tertinggi terakhir mengunci semua orang di luar
        # pengelolaan akun — termasuk yang menurunkannya. Ditolak SEBELUM
        # tersimpan, bukan diperbaiki sesudahnya, karena sesudahnya tak ada
        # yang bisa.
        #
        # Yang dibandingkan TINGKATNYA, bukan namanya. Berbunyi `peran !=
        # "admin"` dulu, dan itu salah dua arah sekaligus:
        #
        # · Admin terakhir yang mau NAIK ke Super Admin ikut ditolak —
        #   padahal tingkatnya bertambah, bukan berkurang. Di pabrik yang
        #   Super Admin-nya belum pernah diangkat, itu berarti puncak tangga
        #   tak bisa diisi oleh siapa pun, selamanya. Catatan di
        #   `_jumlah_admin` sudah menyebut bahaya ini dan membetulkan cara
        #   MENGHITUNGNYA; syaratnya sendiri terlewat.
        # · Super Admin terakhir yang diturunkan jadi operator LOLOS, karena
        #   perannya bukan "admin" sehingga syaratnya tak pernah menyala.
        #   Persis lubang yang penjaga ini dibuat untuk menutup.
        # ── Langit-langit: tak seorang pun mengangkat orang lebih tinggi
        #    dari dirinya sendiri ──
        #
        # Tanpa ini, "boleh mengelola akun" diam-diam berarti "boleh jadi
        # apa saja": daftar perannya memuat Super Admin, dan tak ada yang
        # melarang seseorang memilihkannya untuk dirinya sendiri. Satu
        # ketukan, dan tangganya tak punya puncak lagi.
        #
        # Hari ini gerbang halaman ini sudah Super Admin saja, jadi aturan
        # ini belum menolak siapa pun. Ia ditulis justru karena itu: gerbang
        # bisa dilonggarkan lagi suatu hari — sudah pernah — dan aturan yang
        # baru ditambahkan setelah pintunya dibuka selalu terlambat.
        if peran and P.terlalu_tinggi(akun.peran, peran):
            return redirect(f"/pengguna/{akun_id}?err=terlalu-tinggi")

        turun = P.tingkat(peran) < P.tingkat(a.user.role)
        if peran and a.is_admin and turun and await _jumlah_admin(db) <= 1:
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
            # Perannya berubah, jadi sesi yang sedang berjalan membawa hak
            # yang sudah bukan miliknya. Yang turun harus benar-benar turun,
            # dan itu tak terjadi sampai tokennya diperbarui.
            a.token_version = (a.token_version or 1) + 1
            berubah.append("peran")
        if mode and mode != a.mode_perangkat:
            a.mode_perangkat = mode
            berubah.append("jenis perangkat")
        if not berubah:
            return redirect(f"/pengguna/{akun_id}?ok=tidak-berubah")
        await db.commit()
    return redirect(f"/pengguna/{akun_id}?ok=tersimpan")
