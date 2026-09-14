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

from app.database import SessionLocal
from app.peran import PERAN_ADMIN_KEATAS
from app.models import ProduksiAkun
from app.web.security import (ada_superadmin, butuh_admin, butuh_akun,
                               butuh_super)
from app.web.tampilan import redirect, render
from hmu_core import User

router = APIRouter(tags=["webapp"])


@router.get("/pengaturan")
async def halaman_pengaturan(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    from app.services.setelan import fitur_mutu, sebab_jeda, target_kadar_air
    from app.services.undo import BATAS_UNDO
    from app.web.nav import lencana

    # Setelan kerja hanya ditampilkan kepada admin ke atas — operator mengurus
    # data dirinya sendiri dan sandinya sendiri, tak lebih.
    tuan = akun.peran in PERAN_ADMIN_KEATAS
    async with SessionLocal() as db:
        target = await target_kadar_air(db) if tuan else None
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
    return render(
        request, "pengaturan.html",
        **await lencana(akun.user),
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
        err=_PESAN.get(request.query_params.get("err", ""))
            or request.query_params.get("err_teks", ""),
        tuan=tuan, target_bawaan=target, sebab_jeda=sebab, mutu_aktif=mutu_aktif,
        ada_super=ada_super,
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
        isi = list(daftar[jenis])
        tambah, buang = tambah.strip(), buang.strip()
        if tambah:
            if tambah in isi:
                return redirect("/pengaturan?err_teks=" + quote("Sebab itu sudah ada."))
            isi.append(tambah[:120])
        elif buang:
            if buang not in isi:
                return redirect("/pengaturan?err_teks=" + quote("Sebab itu sudah tak ada."))
            isi.remove(buang)
        else:
            return redirect("/pengaturan")
        daftar[jenis] = isi
        try:
            await set_sebab_jeda(db, daftar, user=u)
        except ValueError as e:
            return redirect(f"/pengaturan?err_teks={quote(str(e))}")
    return redirect("/pengaturan?pesan=sebab-diubah")


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
    "mutu-nyala": "Pencatatan mutu dinyalakan.",
    "mutu-padam": "Pencatatan mutu dimatikan — borang QC dan baris mutu "
                  "disembunyikan dari semua layar.",
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
    nyala = request.cookies.get("produksi_terik") != "1"
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
    from app.penggilingan.gudang1.services.drying import dryers_g1
    from app.penggilingan.gudang1.services.silo import _silo_content_kg, silos_g1
    from app.web.nav import lencana

    async with SessionLocal() as db:
        mesin = await dryers_g1(db)
        silo = [(s, await _silo_content_kg(db, s.id)) for s in await silos_g1(db)]
    return render(
        request, "alat.html", kembali="/pengaturan", layar="pengaturan",
        **await lencana(akun.user),
        mesin=mesin, silo=silo, maks=MAKS_ALAT,
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
        pesan_err=_ERR.get(request.query_params.get("err", "")),
    )


_ERR = {
    "nama-pendek": "Nama alat minimal 3 huruf.",
    "kapasitas": "Kapasitas harus lebih dari 0 kg.",
    "penuh": f"Sudah ada {MAKS_ALAT} alat — hapus atau nonaktifkan dulu.",
    "kembar": "Sudah ada alat dengan nama itu.",
    "terisi": "Alat itu masih ada isinya — kosongkan dulu.",
}


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
                     kapasitas_kg=kapasitas_kg, status="aktif"))
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-ditambah")


@router.post("/pengaturan/alat/silo")
async def tambah_silo(
    request: Request, nama: str = Form(...),
    akun: ProduksiAkun = Depends(butuh_super),
):
    """Tambah silo gabah kering.

    Tanpa kapasitas: silo memang tak berbatas (keputusan Direksi 2 September
    2026), dan meminta angka yang tidak dipakai hanya mengundang orang
    mengarangnya.
    """
    from app.models import Silo
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id, silos_g1

    nama = " ".join(nama.split())
    if nama.lower().startswith("silo "):
        nama = nama[5:].strip()
    if len(nama) < 1:
        return redirect("/pengaturan/alat?err=nama-pendek")
    penuh = f"Silo {nama}"
    async with SessionLocal() as db:
        ada = await silos_g1(db)
        if len(ada) >= MAKS_ALAT:
            return redirect("/pengaturan/alat?err=penuh")
        if any(s.nama_silo.lower() == penuh.lower() for s in ada):
            return redirect("/pengaturan/alat?err=kembar")
        db.add(Silo(warehouse_id=await _g1_warehouse_id(db), nama_silo=penuh,
                    kapasitas_ton=0))
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-ditambah")


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
