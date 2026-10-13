"""Halaman Pengaturan — satu tempat untuk hal yang jarang diubah.

Dipisahkan dari beranda dengan sengaja. Beranda dipakai puluhan kali sehari
dan isinya keadaan pabrik; pengaturan dibuka beberapa kali setahun. Menaruh
keduanya berdampingan membuat yang sering dipakai harus melewati yang jarang.

Tiga bagian, dan urutannya mengikuti seberapa sering dipakai:
  · **Akun saya** — nama & kata sandi, milik siapa pun yang sedang masuk;
  · **Pengguna** — Super Admin saja;
  · **Alat** — dryer & silo, Super Admin saja.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request

from app.config import settings
from app.database import SessionLocal
from app.peran import PERAN_ADMIN_KEATAS
from app.models import ProduksiAkun
from app.web.layar import SUPER as V_SUPER
from app.web.layar import view_untuk
from hmu_identitas import peran as _P
from app.web.security import (ada_superadmin, butuh_admin, butuh_akun,
                               butuh_super)
from app.web.tampilan import redirect, render
from app.web import versi as _versi
from hmu_core import User

router = APIRouter(tags=["webapp"])


@router.get("/pengaturan/gudang")
async def halaman_gudang_pengaturan(request: Request, akun: ProduksiAkun = Depends(butuh_super)):
    from sqlalchemy import select
    from hmu_core import Warehouse
    from app.web.nav import lencana

    async with SessionLocal() as db:
        daftar = (await db.execute(select(Warehouse).order_by(
            Warehouse.aktif.desc(), Warehouse.kode_fungsi, Warehouse.nama_gudang
        ))).scalars().all()
        gudang = [{"id": w.id, "nama": w.nama_gudang, "alamat": w.alamat or "",
                   "latitude": str(w.latitude) if w.latitude is not None else "",
                   "longitude": str(w.longitude) if w.longitude is not None else "",
                   "fungsi": w.kode_fungsi, "aktif": w.aktif}
                  for w in daftar]
    return render(request, "gudang_pengaturan.html", layar="pengaturan",
                  kembali="/pengaturan", gudang=gudang,
                  pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
                  pesan_err=request.query_params.get("err_teks", "")
                  or _PESAN.get(request.query_params.get("err", "")),
                  **await lencana(akun.user))


@router.post("/pengaturan/gudang/tambah")
async def tambah_gudang(
    request: Request, nama: str = Form(...), alamat: str = Form(""),
    latitude: str = Form(""), longitude: str = Form(""),
    akun: ProduksiAkun = Depends(butuh_super),
):
    from sqlalchemy import func, select
    from hmu_core import Warehouse
    nama = nama.strip()
    if len(nama) < 2 or len(nama) > 100:
        return redirect("/pengaturan/gudang?err_teks=" + quote("Nama gudang harus 2–100 karakter."))
    try:
        lat = float(latitude.replace(",", ".")) if latitude.strip() else None
        lon = float(longitude.replace(",", ".")) if longitude.strip() else None
    except ValueError:
        return redirect("/pengaturan/gudang?err_teks=" + quote("Koordinat harus berupa angka."))
    if lat is not None and not -90 <= lat <= 90 or lon is not None and not -180 <= lon <= 180:
        return redirect("/pengaturan/gudang?err_teks=" + quote("Koordinat di luar batas yang valid."))
    async with SessionLocal() as db:
        duplicate = (await db.execute(select(Warehouse.id).where(
            func.lower(Warehouse.nama_gudang) == nama.lower(), Warehouse.aktif.is_(True)
        ))).first()
        if duplicate:
            return redirect("/pengaturan/gudang?err_teks=" + quote("Nama gudang itu sudah digunakan."))
        db.add(Warehouse(nama_gudang=nama, alamat=alamat.strip() or None,
                         latitude=lat, longitude=lon, aktif=True))
        await db.commit()
    return redirect("/pengaturan/gudang?pesan=gudang-ditambah")


@router.post("/pengaturan/gudang/edit")
async def edit_gudang(
    request: Request, gudang_id: int = Form(...), nama: str = Form(...),
    alamat: str = Form(""), latitude: str = Form(""), longitude: str = Form(""),
    akun: ProduksiAkun = Depends(butuh_super),
):
    from sqlalchemy import func, select
    from hmu_core import Warehouse
    nama = nama.strip()
    if len(nama) < 2 or len(nama) > 100:
        return redirect("/pengaturan/gudang?err_teks=" + quote("Nama gudang harus 2–100 karakter."))
    try:
        lat = float(latitude.replace(",", ".")) if latitude.strip() else None
        lon = float(longitude.replace(",", ".")) if longitude.strip() else None
    except ValueError:
        return redirect("/pengaturan/gudang?err_teks=" + quote("Koordinat harus berupa angka."))
    if (lat is not None and not -90 <= lat <= 90) or (lon is not None and not -180 <= lon <= 180):
        return redirect("/pengaturan/gudang?err_teks=" + quote("Koordinat di luar batas yang valid."))
    async with SessionLocal() as db:
        wh = await db.get(Warehouse, gudang_id)
        if wh is None or not wh.aktif:
            return redirect("/pengaturan/gudang?err_teks=" + quote("Gudang tidak ditemukan atau sudah dihapus."))
        duplicate = (await db.execute(select(Warehouse.id).where(
            func.lower(Warehouse.nama_gudang) == nama.lower(), Warehouse.id != wh.id,
            Warehouse.aktif.is_(True)
        ))).first()
        if duplicate:
            return redirect("/pengaturan/gudang?err_teks=" + quote("Nama gudang itu sudah digunakan."))
        wh.nama_gudang, wh.alamat = nama, alamat.strip() or None
        wh.latitude, wh.longitude = lat, lon
        await db.commit()
    return redirect("/pengaturan/gudang?pesan=gudang-diubah")


@router.post("/pengaturan/gudang/hapus")
async def hapus_gudang(request: Request, gudang_id: int = Form(...),
                       akun: ProduksiAkun = Depends(butuh_super)):
    from sqlalchemy import select
    from hmu_core import Dryer, Silo, User, Warehouse
    async with SessionLocal() as db:
        wh = await db.get(Warehouse, gudang_id)
        if wh is None or not wh.aktif:
            return redirect("/pengaturan/gudang?err_teks=" + quote("Gudang tidak ditemukan atau sudah dihapus."))
        if wh.kode_fungsi in {"g1", "g2"}:
            return redirect("/pengaturan/gudang?err_teks=" + quote(
                "Gudang selepan dan penyosohan adalah bagian alur produksi; keduanya tidak bisa dihapus."))
        if (await db.execute(select(Silo.id).where(Silo.warehouse_id == wh.id))).first() \
                or (await db.execute(select(Dryer.id).where(Dryer.warehouse_id == wh.id))).first() \
                or (await db.execute(select(User.id).where(User.default_warehouse_id == wh.id))).first():
            return redirect("/pengaturan/gudang?err_teks=" + quote(
                "Gudang masih dipakai oleh silo, mesin, atau akun. Pindahkan datanya dahulu."))
        wh.aktif = False
        await db.commit()
    return redirect("/pengaturan/gudang?pesan=gudang-dihapus")


def _proses_view(view: str) -> tuple[tuple[str, str], ...]:
    """Proses yang sebab berhentinya boleh diatur view ini — urut seperti
    `jeda.SEBAB`, yaitu urutan perjalanan barang."""
    from app.penggilingan.gudang1.services.jeda import (GUDANG_PROSES, NAMA_PROSES,
                                                        SEBAB)
    from app.web.layar import boleh_lihat_gudang

    return tuple((k, NAMA_PROSES[k]) for k in SEBAB
                 if boleh_lihat_gudang(view, GUDANG_PROSES[k]))


@router.get("/pengaturan")
async def halaman_pengaturan(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    from app.services import kledo_sinkron
    from app.services.setelan import fitur_mutu, sebab_jeda
    from app.services.undo import BATAS_UNDO
    from app.web.nav import lencana

    # Setelan kerja hanya ditampilkan kepada admin ke atas — operator mengurus
    # data dirinya sendiri dan sandinya sendiri, tak lebih.
    tuan = akun.peran in PERAN_ADMIN_KEATAS
    async with SessionLocal() as db:
        sebab = await sebab_jeda(db) if tuan else {}
        mutu_aktif = await fitur_mutu(db) if tuan else False
        # Blok "Pengelolaan sistem" milik Super Admin — TETAPI hanya kalau
        # Super Admin-nya ada. Pabrik ini menjalankan satu akun Admin dan nol
        # Super Admin, jadi menyembunyikannya dari Admin menyembunyikannya
        # dari semua orang: satu-satunya jalan mengangkat Super Admin pertama
        # ada di balik pintu yang baru saja ditutup untuk semua.
        #
        # Menyembuhkan dirinya sendiri: begitu ada satu Super Admin aktif,
        # bloknya hilang dari layar Admin tanpa ada yang perlu menyentuh apa
        # pun. Dan ia tak pernah bisa mengunci siapa pun di luar.
        ada_super = await ada_superadmin() if tuan else False
    # Potret tanpa basis data (singleton di memori proses ini) — aman dibaca
    # di luar `async with SessionLocal()` di atas.
    kledo = kledo_sinkron.status() if tuan else None
    # Versi kode yang sedang berjalan — untuk SEMUA peran, di kaki halaman.
    # Peringatan skema tertinggal hanya dirender untuk admin ke atas (di
    # templat); operator tak bisa menjalankan migrasi, jadi baginya itu cuma
    # kotak merah yang tak bisa ia tutup.
    versi = await _versi.info()
    # ── Bendera blok (Tahap 2, templat Pengaturan naik ke paket) ──
    #
    # Templat bersama tidak menebak peran; ia memasang blok yang app-nya
    # nyatakan. Syaratnya PERSIS yang dulu tertulis di templat ini, cuma
    # pindah tempat — dan di sinilah tempatnya, karena di sini `view` dan
    # `PERAN_ASLI` sudah ada tanpa perlu dibaca ulang dari templat.
    view = await view_untuk(akun.user)
    peran_asli = getattr(request.state, "peran_asli", None) or akun.peran
    return render(
        request, "pengaturan.html",
        **await lencana(akun.user),
        versi=versi,
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
        err=_PESAN.get(request.query_params.get("err", ""))
            or request.query_params.get("err_teks", ""),
        tuan=tuan, sebab_jeda=sebab, mutu_aktif=mutu_aktif,
        kledo=kledo,
        ada_super=ada_super,
        blok_kelola=view == V_SUPER or (tuan and not ada_super),
        kelola_darurat=view != V_SUPER,
        blok_lihat_sebagai=_P.admin_keatas(peran_asli),
        blok_kerja_gudang=_P.boleh_ganti_gudang(peran_asli),
        # ── Sebab berhenti per proses: DITURUNKAN, bukan diketik ──
        #
        # Dulu tuple ini berisi dua proses dengan alasan tertulis "setelan
        # Gudang 2 diurus dari Meja". Akibatnya tak ada satu layar pun di Pos
        # Produksi yang bisa menambah atau membuang sebab berhenti mesin sosoh —
        # dan itu satu-satunya hal yang menahan pemensiunan app Meja (QA 24
        # September 2026, jawaban atas pertanyaan pemilik "boleh dihapus?").
        #
        # Sekarang dari `jeda.SEBAB` berikut gudang pemiliknya, disaring dengan
        # VIEW: proses keempat cukup didaftar di `jeda.py`, dan operator selepan
        # tak pernah ditawari setelan mesin yang tak ada di gudangnya. Hari ini
        # penyaring itu tak mengubah apa pun — blok setelan memang hanya untuk
        # admin ke atas, yang memegang kedua gudang — tetapi aturannya jadi
        # tertulis di tempat yang benar, bukan tersimpan sebagai kebetulan.
        PROSES=_proses_view(view),
        blok_setelan=tuan,
        blok_mode_uji=settings.mode_uji and view == V_SUPER,
        JAM_BATAS=int(BATAS_UNDO.total_seconds() // 3600),
    )


@router.post("/pengaturan/target-kadar-air")
async def ubah_target_bawaan(request: Request, nilai: str = Form(...),
                             akun: ProduksiAkun = Depends(butuh_admin)):
    from app.services.setelan import set_target_kadar_air

    # Kolomnya `inputmode="decimal"`, dan papan ketik itu memberi KOMA di
    # lokal Indonesia. Dulu `nilai: float` — koma ditolak sebagai 422 tanpa
    # kalimat yang bisa dibaca orang.
    try:
        angka = float(nilai.replace(",", "."))
    except ValueError:
        return redirect(f"/pengaturan?err_teks={quote('Target kadar air harus angka.')}")
    async with SessionLocal() as db:
        u = await db.get(User, akun.user.id)
        try:
            await set_target_kadar_air(db, angka, user=u)
        except ValueError as e:
            return redirect(f"/pengaturan?err_teks={quote(str(e))}")
    return redirect("/pengaturan?pesan=target-diubah")


@router.post("/pengaturan/fitur-mutu")
async def ubah_fitur_mutu(request: Request, aktif: str = Form(""),
                          akun: ProduksiAkun = Depends(butuh_admin)):
    """Nyalakan atau matikan seluruh pencatatan mutu.

    Satu tombol, bukan kotak centang yang harus disusul "Simpan": setelan
    yang perlu dua ketukan sering tinggal satu — orang mencentangnya lalu
    berpindah layar, dan yang tersimpan tetap yang lama.
    """
    from app.services.setelan import set_fitur_mutu

    async with SessionLocal() as db:
        u = await db.get(User, akun.user.id)
        await set_fitur_mutu(db, aktif == "1", user=u)
    return redirect("/pengaturan?pesan="
                    + ("mutu-nyala" if aktif == "1" else "mutu-padam"))


@router.post("/pengaturan/sebab-jeda")
async def ubah_sebab_jeda(request: Request, jenis: str = Form(...),
                          tambah: str = Form(""), buang: str = Form(""),
                          akun: ProduksiAkun = Depends(butuh_admin)):
    """Tambah atau buang satu sebab berhenti.

    Satu tombol satu perubahan: borang yang mengirim seluruh daftar sekaligus
    akan menimpa perubahan orang lain yang membuka layar yang sama semenit
    lebih dulu.
    """
    from app.services.setelan import sebab_jeda, set_sebab_jeda

    async with SessionLocal() as db:
        u = await db.get(User, akun.user.id)
        daftar = await sebab_jeda(db)
        if jenis not in daftar:
            return redirect("/pengaturan?err_teks=" + quote("Jenis proses tak dikenal."))
        tujuan = "/pengaturan/alat" if jenis == "pengeringan" else "/pengaturan"
        isi = list(daftar[jenis])
        tambah, buang = tambah.strip(), buang.strip()
        if tambah:
            if tambah in isi:
                return redirect(tujuan + "?err_teks=" + quote("Sebab itu sudah ada."))
            isi.append(tambah[:120])
        elif buang:
            if buang not in isi:
                return redirect(tujuan + "?err_teks=" + quote("Sebab itu sudah tak ada."))
            isi.remove(buang)
        else:
            return redirect(tujuan)
        daftar[jenis] = isi
        try:
            await set_sebab_jeda(db, daftar, user=u)
        except ValueError as e:
            return redirect(f"{tujuan}?err_teks={quote(str(e))}")
    return redirect(f"{tujuan}?pesan=sebab-diubah")


@router.post("/pengaturan/kledo-kontak")
async def mulai_sinkron_kledo_kontak(
    request: Request, akun: ProduksiAkun = Depends(butuh_admin)
):
    """Mulai satu putaran sinkron kontak Kledo di latar.

    TIDAK menunggu selesainya — ~600 kontak Kledo diambil berhalaman-halaman,
    cukup lama untuk menahan permintaan HTTP ini sampai kena gateway timeout
    Railway. Hasilnya dibaca lewat `kledo_sinkron.status()` saat halaman ini
    dimuat ulang (lihat `halaman_pengaturan`), bukan dari balasan permintaan
    ini.
    """
    from app.services import kledo_sinkron

    if not kledo_sinkron.status().terkonfigurasi:
        return redirect("/pengaturan?err=kledo-belum-tersambung")
    if not kledo_sinkron.mulai():
        return redirect("/pengaturan?err=kledo-sedang-berjalan")
    return redirect("/pengaturan?pesan=kledo-dimulai")


#: Hanya kunci yang dikenal yang jadi pesan — teks bebas dari URL tak pernah
#: ditampilkan, supaya halaman ini tak bisa dipakai menitipkan kalimat palsu
#: lewat tautan.
_PESAN = {
    "nama-diganti": "Nama Anda sudah diperbarui.",
    "terik-nyala": ("Mode terik menyala untuk perangkat ini — layar terang "
                    "untuk kerja di bawah matahari."),
    "terik-padam": "Mode terik dipadamkan untuk perangkat ini.",
    "nama-pendek": "Nama minimal 3 huruf.",
    "nama-dipakai": ("Nama itu sudah dipakai orang lain. Nama Anda tertulis "
                     "sebagai pelaku di setiap catatan, jadi dua orang "
                     "bernama sama membuat catatan keduanya tak bisa "
                     "dibedakan lagi."),
    "target-diubah": "Target kadar air bawaan sudah diperbarui.",
    "sebab-diubah": "Daftar sebab berhenti sudah diperbarui.",
    "sandi-diganti": "Kata sandi berhasil diganti.",
    "alat-ditambah": "Alat baru ditambahkan.",
    "alat-diubah": "Alat diperbarui.",
    "silo-diubah": "Nama dan filter komoditas silo berhasil disimpan.",
    "silo-dihapus": "Silo dihapus dari daftar aktif. Catatan lama tetap tersimpan.",
    "mutu-nyala": "Pencatatan mutu dinyalakan.",
    "mutu-padam": "Pencatatan mutu dimatikan — borang QC dan baris mutu "
                  "disembunyikan dari semua layar.",
    "kledo-dimulai": ("Sinkron kontak Kledo dimulai di latar — muat ulang "
                       "halaman ini sebentar lagi untuk melihat hasilnya."),
    "kledo-belum-tersambung": "Kledo belum tersambung — KLEDO_API_KEY belum diisi.",
    "kledo-sedang-berjalan": "Sinkron kontak Kledo sudah berjalan — tunggu sampai selesai.",
}


@router.post("/pengaturan/terik")
async def ganti_terik(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    """Nyala/padamkan mode terik untuk PERANGKAT ini.

    Tema gelap enak di dalam gudang dan nyaris tak terbaca di halaman —
    sebagian pekerjaan memang terjadi di sana: truk yang ditimbang, gabah yang
    dijemur. Temuan QA UI-04.

    Disimpan di kuki perangkat, bukan di akun: satu orang memakai ponselnya
    sendiri di dalam dan perangkat gudang di luar, dan yang menentukan bukan
    siapa dia melainkan di mana layarnya berada.
    """
    # Tanpa cookie, mode terang sedang aktif sebagai bawaan; tombol pertama
    # harus mematikannya, bukan mengaktifkannya lagi.
    nyala = request.cookies.get("produksi_terik", "1") != "1"
    balasan = redirect("/pengaturan?pesan="
                       + ("terik-nyala" if nyala else "terik-padam"))
    balasan.set_cookie(
        "produksi_terik", "1" if nyala else "0",
        max_age=365 * 24 * 3600, httponly=False, samesite="lax",
        secure=request.url.scheme == "https", path="/",
    )
    return balasan


@router.post("/pengaturan/nama")
async def ganti_nama(
    request: Request,
    nama: str = Form(...),
    akun: ProduksiAkun = Depends(butuh_akun),
):
    """Ganti nama sendiri — yang tampil di seluruh catatan.

    Namanya BUKAN sekadar label layar: ia menempel pada ribuan catatan lama
    lewat `created_by`, dan yang berubah di sini ikut berubah di semua catatan
    itu. Itu memang yang diinginkan — orangnya sama, ejaannya yang salah — dan
    justru karena itu tak boleh sembarang dikosongkan atau disingkat jadi satu
    huruf, sebab daftar akun lalu mustahil dibaca.
    """
    nama = " ".join(nama.split())
    if len(nama) < 3:
        return redirect("/pengaturan?err=nama-pendek")
    async with SessionLocal() as db:
        orang = await db.get(User, akun.user_id)
        if orang is None:
            return redirect("/pengaturan")
        # ── Nama kembar ditolak ──
        #
        # Nama inilah yang tertulis sebagai PELAKU di seluruh catatan, dan
        # layar audit menampilkannya apa adanya. Operator yang mengganti
        # namanya menjadi nama Direksi karenanya membuat catatannya sendiri
        # terbaca sebagai catatan Direksi — tak ada satu pun layar yang bisa
        # membedakan keduanya lagi. Temuan QA P-S-11.
        #
        # Dibandingkan tanpa memedulikan huruf besar-kecil dan spasi ganda:
        # "wahid  nurhani" dan "Wahid Nurhani" terbaca sama oleh orang, dan
        # orang itulah yang dikelabui.
        from sqlalchemy import func as _f, select as _select

        kembar = (await db.execute(
            _select(User).where(_f.lower(User.nama) == nama.lower(),
                               User.id != orang.id)
        )).scalars().first()
        if kembar is not None:
            return redirect("/pengaturan?err=nama-dipakai")
        orang.nama = nama
        await db.commit()
    return redirect("/pengaturan?pesan=nama-diganti")


# ─────────────────────────── Alat: dryer & silo ───────────────────────────

#: Batas yang bukan hiasan. Nol alat membuat seluruh alur berhenti; jumlah
#: yang keterlaluan hampir pasti salah ketik, dan daftar sepanjang itu tak
#: bisa dipakai memilih sambil berdiri.
MAKS_ALAT = 12


@router.get("/pengaturan/alat")
async def halaman_alat(request: Request, akun: ProduksiAkun = Depends(butuh_super)):
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.silo_policy import daftar_diizinkan, LABEL_KOMODITAS
    from app.penggilingan.gudang1.services.drying import dryers_g1
    from app.penggilingan.gudang1.services.silo import _silo_content_kg, silos_g1
    from app.penggilingan.gudang2.service import _g2_warehouse_id, hitung_stok_silo
    from app.web.nav import lencana

    async with SessionLocal() as db:
        # Bentuk kamus, bukan tuple `(silo, kg)`: `alat.html` satu berkas di
        # paket sejak 23 September 2026, dan bentuk tuple yang dulu dipakai di
        # sini adalah satu-satunya sebab ia hidup dua kali. Bentuk ini lahir
        # sebagai JSON `/internal/meja/alat`; pintu itu dicabut 24 September
        # bersama app Meja, bentuknya tinggal karena templatnya memakainya.
        # Objek ORM pun berhenti bocor ke templat.
        from app.services.setelan import sebab_jeda, target_kadar_air
        target_global = await target_kadar_air(db)
        sebab = await sebab_jeda(db)
        mesin = [{"id": d.id, "nama": d.nama, "kapasitas": float(d.kapasitas_kg or 0),
                  "target": float(d.target_kadar_air) if d.target_kadar_air is not None else target_global,
                  "status": d.status} for d in await dryers_g1(db)]
        silo = [{"id": s.id, "nama_silo": s.nama_silo,
                 "nama_tampil": (s.nama_silo[5:].strip()
                                 if s.nama_silo.lower().startswith("silo ")
                                 and len(s.nama_silo.strip()) > 6 else s.nama_silo),
                 "komoditas": daftar_diizinkan(s, "g1"),
                 "komoditas_label": ", ".join(LABEL_KOMODITAS[k] for k in daftar_diizinkan(s, "g1")),
                 "opsi_komoditas": [{"kode": k, "label": LABEL_KOMODITAS[k],
                                     "aktif": k in daftar_diizinkan(s, "g1")}
                                    for k in ("gabah_kering",)],
                 "gudang": "g1",
                 "kg": float(await _silo_content_kg(db, s.id))}
                for s in await silos_g1(db)]
        # Silo Gudang 2 (PK & broken, keputusan pemilik 6 Oktober 2026) —
        # daftar TERPISAH dari silo gabah kering di atas: isinya dihitung
        # beda (`hitung_stok_silo`, bukan `_silo_content_kg`), dan jenisnya
        # (`jenis_isi`) wajib ikut terlihat.
        wid_g2 = await _g2_warehouse_id(db)
        silo_g2 = [{"id": s.id, "nama_silo": s.nama_silo,
                    "nama_tampil": (s.nama_silo[5:].strip()
                                    if s.nama_silo.lower().startswith("silo ")
                                    and len(s.nama_silo.strip()) > 6 else s.nama_silo),
                    "jenis_isi": s.jenis_isi,
                    "komoditas": daftar_diizinkan(s, "g2"),
                    "komoditas_label": ", ".join(LABEL_KOMODITAS[k] for k in daftar_diizinkan(s, "g2")),
                    "opsi_komoditas": [{"kode": k, "label": LABEL_KOMODITAS[k],
                                        "aktif": k in daftar_diizinkan(s, "g2")}
                                       for k in ("pk", "beras_putih", "reject", "broken", "menir")],
                    "gudang": "g2",
                    "kg": float(await hitung_stok_silo(db, s.id))}
                   for s in (await db.execute(
                       select(Silo).where(Silo.warehouse_id == wid_g2, Silo.aktif.is_(True))
                       .order_by(Silo.nama_silo)
                   )).scalars().all()]
    return render(
        request, "alat.html", kembali="/pengaturan", layar="pengaturan",
        **await lencana(akun.user),
        mesin=mesin, silo=silo, silo_g2=silo_g2, maks=MAKS_ALAT,
        sebab_pengeringan=sebab.get("pengeringan", []),
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
        pesan_err=(_ERR.get(request.query_params.get("err", ""))
                   or request.query_params.get("err_teks", "")),
    )


_ERR = {
    "nama-pendek": "Nama alat minimal 3 huruf.",
    "kapasitas": "Kapasitas harus lebih dari 0 kg.",
    "penuh": f"Sudah ada {MAKS_ALAT} alat — hapus atau nonaktifkan dulu.",
    "kembar": "Sudah ada alat dengan nama itu.",
    "terisi": "Alat itu masih ada isinya — kosongkan dulu.",
}

_PESAN.update({
    "gudang-ditambah": "Gudang ditambahkan.",
    "gudang-diubah": "Perubahan gudang disimpan.",
    "gudang-dihapus": "Gudang diarsipkan dari daftar aktif.",
})


@router.post("/pengaturan/alat/dryer")
async def tambah_dryer(
    request: Request, nama: str = Form(...), kapasitas_kg: str = Form(...),
    akun: ProduksiAkun = Depends(butuh_super),
):
    """Tambah mesin pengering.

    Kapasitas diminta di sini, bukan diberi bawaan: dua mesin di pabrik yang
    sama belum tentu sama besarnya, dan angka bawaan yang salah akan menolak
    truk atau menerima muatan yang tak kering merata — keduanya diam-diam.
    """
    from app.models import Dryer
    from app.penggilingan.gudang1.services.drying import dryers_g1
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id
    from app.services.setelan import target_kadar_air

    nama = " ".join(nama.split())
    # `inputmode="numeric"` tanpa type=number: nilainya teks, dibaca di sini.
    try:
        kapasitas_kg = int(float(kapasitas_kg.replace(",", ".")))
    except ValueError:
        return redirect(f"/pengaturan/alat?err_teks={quote('Kapasitas harus angka.')}")
    if len(nama) < 3:
        return redirect("/pengaturan/alat?err=nama-pendek")
    if kapasitas_kg <= 0:
        return redirect("/pengaturan/alat?err=kapasitas")
    async with SessionLocal() as db:
        ada = await dryers_g1(db)
        if len(ada) >= MAKS_ALAT:
            return redirect("/pengaturan/alat?err=penuh")
        if any(d.nama.lower() == nama.lower() for d in ada):
            return redirect("/pengaturan/alat?err=kembar")
        db.add(Dryer(warehouse_id=await _g1_warehouse_id(db), nama=nama,
                     kapasitas_kg=kapasitas_kg, target_kadar_air=await target_kadar_air(db),
                     status="aktif"))
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-ditambah")


@router.post("/pengaturan/alat/dryer/edit")
async def edit_dryer(
    request: Request, dryer_id: int = Form(...), nama: str = Form(...),
    kapasitas_kg: str = Form(...), target_kadar_air: str = Form(...),
    akun: ProduksiAkun = Depends(butuh_super),
):
    from app.models import Dryer
    from app.penggilingan.gudang1.services.drying import dryers_g1

    nama = " ".join(nama.split())
    try:
        kapasitas = float(kapasitas_kg.replace(",", "."))
        target = float(target_kadar_air.replace(",", "."))
    except ValueError:
        return redirect("/pengaturan/alat?err_teks=" + quote("Kapasitas dan target harus berupa angka."))
    if len(nama) < 3 or len(nama) > 50:
        return redirect("/pengaturan/alat?err=nama-pendek")
    if kapasitas <= 0:
        return redirect("/pengaturan/alat?err=kapasitas")
    if not 5 <= target <= 30:
        return redirect("/pengaturan/alat?err_teks=" + quote("Target kadar air harus antara 5% dan 30%."))
    async with SessionLocal() as db:
        d = await db.get(Dryer, dryer_id)
        daftar = await dryers_g1(db)
        if d is None or d.id not in {x.id for x in daftar}:
            return redirect("/pengaturan/alat?err_teks=" + quote("Mesin pengering tidak ditemukan."))
        if any(x.id != d.id and x.nama.casefold() == nama.casefold() for x in daftar):
            return redirect("/pengaturan/alat?err=kembar")
        d.nama, d.kapasitas_kg, d.target_kadar_air = nama, kapasitas, target
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-diubah")


@router.post("/pengaturan/alat/silo")
async def tambah_silo(
    request: Request, nama: str = Form(...), gudang: str = Form("g1"),
    jenis_isi: str = Form("campuran"),
    akun: ProduksiAkun = Depends(butuh_super),
):
    """Tambah silo gabah di Gudang 1 atau silo campuran di Gudang 2.

    Tanpa kapasitas: silo memang tak berbatas (keputusan Direksi 2 September
    2026), dan meminta angka yang tidak dipakai hanya mengundang orang
    mengarangnya.

    Silo Gudang 1 selalu khusus gabah. Silo Gudang 2 merupakan silo campuran
    untuk PK, beras putih, broken, menir, dan reject; bekatul tidak disimpan di
    silo. `jenis_isi` hanya metadata warisan dan tidak membatasi arus barang.

    """
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.silo_policy import KOMODITAS_G1, KOMODITAS_G2
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id, silos_g1
    from app.penggilingan.gudang2.service import _g2_warehouse_id

    nama = " ".join(nama.split())
    if nama.lower().startswith("silo "):
        nama = nama[5:].strip()
    if len(nama) < 1:
        return redirect("/pengaturan/alat?err=nama-pendek")
    penuh = f"Silo {nama}"
    g2 = (gudang or "g1").strip().lower() == "g2"
    isi = "campuran"
    async with SessionLocal() as db:
        if g2:
            wid = await _g2_warehouse_id(db)
            ada = (await db.execute(
                select(Silo).where(Silo.warehouse_id == wid)
            )).scalars().all()
        else:
            wid = await _g1_warehouse_id(db)
            ada = await silos_g1(db)
        if len(ada) >= MAKS_ALAT:
            return redirect("/pengaturan/alat?err=penuh")
        if any(s.nama_silo.lower() == penuh.lower() for s in ada):
            return redirect("/pengaturan/alat?err=kembar")
        db.add(Silo(warehouse_id=wid, nama_silo=penuh, kapasitas_ton=0,
                    jenis_isi=(isi if g2 else "gabah"),
                    komoditas_diizinkan=list(KOMODITAS_G2 if g2 else KOMODITAS_G1)))
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-ditambah")


@router.post("/pengaturan/alat/silo/edit")
async def edit_silo(
    request: Request, silo_id: int = Form(...), nama: str = Form(...),
    komoditas: list[str] = Form([]),
    akun: ProduksiAkun = Depends(butuh_super),
):
    """Ubah nama dan filter bahan silo; filter mengatur pemasukan berikutnya."""
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id
    from app.penggilingan.gudang2.service import _g2_warehouse_id
    from app.penggilingan.silo_policy import KOMODITAS_G1, KOMODITAS_G2

    nama = " ".join(nama.split())
    if not nama or len(nama) > 50:
        return redirect("/pengaturan/alat?err_teks=" + quote("Nama silo tidak valid."))
    nama_lengkap = nama
    pilihan = list(dict.fromkeys(komoditas))
    async with SessionLocal() as db:
        silo = (await db.execute(select(Silo).where(Silo.id == silo_id).with_for_update())).scalar_one_or_none()
        if silo is None or not silo.aktif:
            return redirect("/pengaturan/alat?err_teks=" + quote("Silo tidak ditemukan."))
        g1_id, g2_id = await _g1_warehouse_id(db), await _g2_warehouse_id(db)
        if silo.warehouse_id == g1_id:
            valid = KOMODITAS_G1
        elif silo.warehouse_id == g2_id:
            valid = KOMODITAS_G2
        else:
            return redirect("/pengaturan/alat?err_teks=" + quote("Gudang silo tidak dikenal."))
        if not pilihan or any(k not in valid for k in pilihan):
            return redirect("/pengaturan/alat?err_teks=" + quote("Pilih komoditas yang valid."))
        pilihan = [k for k in valid if k in pilihan]
        ada_nama = (await db.execute(select(Silo.id).where(
            Silo.warehouse_id == silo.warehouse_id,
            Silo.id != silo.id,
            Silo.nama_silo.ilike(nama_lengkap),
        ))).scalar_one_or_none()
        if ada_nama is not None:
            return redirect("/pengaturan/alat?err_teks=" + quote("Nama silo sudah dipakai di gudang ini."))
        silo.nama_silo = nama_lengkap
        silo.komoditas_diizinkan = pilihan
        await db.commit()
    return redirect("/pengaturan/alat?pesan=silo-diubah")


@router.post("/pengaturan/alat/silo/hapus")
async def hapus_silo(
    request: Request, silo_id: int = Form(...),
    akun: ProduksiAkun = Depends(butuh_super),
):
    """Arsipkan silo kosong agar keluar dari operasi tanpa menghapus riwayat."""
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id, _silo_content_kg
    from app.penggilingan.gudang2.service import _g2_warehouse_id, hitung_stok_silo
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage
    from app.penggilingan.gudang1.services.silo import giling_berjalan_untuk_silo

    async with SessionLocal() as db:
        silo = (await db.execute(select(Silo).where(Silo.id == silo_id).with_for_update())).scalar_one_or_none()
        if silo is None:
            return redirect("/pengaturan/alat?err_teks=" + quote("Silo tidak ditemukan."))
        if silo.warehouse_id == await _g1_warehouse_id(db):
            stok = await _silo_content_kg(db, silo.id)
        elif silo.warehouse_id == await _g2_warehouse_id(db):
            stok = await hitung_stok_silo(db, silo.id)
        else:
            return redirect("/pengaturan/alat?err_teks=" + quote("Gudang silo tidak dikenal."))
        if stok > 0.5:
            return redirect("/pengaturan/alat?err_teks=" + quote("Silo masih berisi stok; kosongkan sebelum dihapus."))
        giling_aktif = await giling_berjalan_untuk_silo(db, silo.id)
        sosoh_aktif = (await db.execute(
            select(PolishingSiloUsage.id)
            .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
            .where(PolishingSiloUsage.silo_id == silo.id, PolishingProcess.status == "proses")
            .limit(1)
        )).scalar_one_or_none()
        if giling_aktif is not None or sosoh_aktif is not None:
            return redirect("/pengaturan/alat?err_teks=" + quote(
                "Silo sedang dipakai proses berjalan; selesaikan proses sebelum menghapus."))
        silo.aktif = False
        await db.commit()
    return redirect("/pengaturan/alat?pesan=silo-dihapus")


@router.post("/pengaturan/alat/dryer/status")
async def ubah_status_dryer(
    request: Request, dryer_id: int = Form(...),
    akun: ProduksiAkun = Depends(butuh_super),
):
    """Nonaktifkan atau aktifkan mesin — TIDAK menghapusnya.

    Mesin tidak pernah dihapus: lot pengeringan lama menunjuk ke sana, dan
    riwayatnya harus tetap bisa dibaca bertahun-tahun setelah mesinnya
    dijual. Yang dimatikan hanya kemampuannya menerima gabah baru.
    """
    from app.models import Dryer
    from app.penggilingan.gudang1.services.drying import active_drying_lot

    async with SessionLocal() as db:
        d = await db.get(Dryer, dryer_id)
        if d is None:
            return redirect("/pengaturan/alat")
        if d.status == "aktif":
            if await active_drying_lot(db, d.id) is not None:
                return redirect("/pengaturan/alat?err=terisi")
            d.status = "nonaktif"
        else:
            d.status = "aktif"
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-diubah")
