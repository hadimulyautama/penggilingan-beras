"""Dua layar kerja MEJA: "Menunggu keputusan" dan "Mutu & QC".

Keduanya di satu berkas karena keduanya satu daftar yang dipotong dua
(`services.keputusan.JENIS`) — dan potongan yang tinggal di dua berkas cepat
atau lambat jadi dua daftar. Pemisahannya permintaan pemilik 24 September 2026:
harga & pencocokan output di `/keputusan`, mutu di `/mutu`.


Barisnya pernah menumpang di Antrian tunggu, dan itu menyalahi aturan yang
paling sering diucapkan pemilik: **begitu gabah punya tempat, ia keluar dari
antrean.** Gabah di baris-baris ini sudah lama punya tempat — sudah di mesin
pengering, sudah di silo, bahkan sudah digiling. Yang belum selesai bukan
gabahnya melainkan keputusannya: harganya belum diverifikasi, mutunya belum
diperiksa, outputnya belum dicocokkan.

Menaruhnya di antrean membuat orang mencari gabah yang sebenarnya sudah
ditempatkan — dan layar yang memerintahkan pencarian sia-sia akan berhenti
dipercaya, termasuk saat ia benar.

Hanya admin ke atas. Sejak awal ini memang pekerjaan admin; operator tak
pernah melihatnya, dan admin yang sedang memakai Mode operator pun tidak —
peran efektifnyalah yang ditanya, bukan peran aslinya.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import SessionLocal
from app.services import berjalan as svc
from app.services import keputusan as K
from app.web.security import butuh_admin
from app.web.tampilan import render

router = APIRouter(tags=["webapp"])

#: Blok tiap layar, BERURUT — DITURUNKAN dari `services.keputusan.JENIS`.
#:
#: Sampai 23 September 2026 daftar ini hidup di dalam templat, dan isinya tiga
#: dari enam jenis yang `b.meja` sungguh bawa: harga PK luar, mutu PK luar, dan
#: pembetulan bobot giling ada di data tetapi tak digambar di layar mana pun —
#: pekerjaan yang menahan uang, tak tertagih, tanpa satu pun tanda.
#:
#: Sejak 24 September 2026 layarnya DUA (permintaan pemilik), dan itu membuat
#: bahaya yang sama jadi dua rupa: jenis baru yang muncul di KEDUA layar, atau
#: tak di mana pun. Karena itu keduanya diturunkan dari satu tupel, dan
#: `AKSI_DIKENAL` — yang dipakai jaring penangkap — adalah GABUNGANNYA.
JENIS_KEPUTUSAN: tuple[tuple[str, str], ...] = K.blok(mutu=False)
JENIS_MUTU: tuple[tuple[str, str], ...] = K.blok(mutu=True)

#: Id yang sudah punya bloknya sendiri DI SALAH SATU layar. Sisanya jatuh ke
#: blok jaring di `/keputusan`, supaya jenis yang lahir nanti TERLIHAT — meski
#: judulnya belum dipikirkan — bukan hilang diam-diam seperti tiga jenis di atas.
#:
#: Jaringnya SATU, dan tinggal di `/keputusan`. Dua jaring yang masing-masing
#: menolak daftarnya sendiri akan menggambar jenis ketujuh dua kali.
AKSI_DIKENAL: tuple[str, ...] = K.SEMUA


@router.get("/keputusan")
async def halaman_keputusan(request: Request, akun=Depends(butuh_admin)):
    async with SessionLocal() as db:
        b = await svc.untuk(db, akun.user)
    meja_non_mutu = [x for x in b.meja if not K.golongan_mutu(x.aksi)]

    # ── SARINGAN GRUP — permintaan pemilik 2 Oktober 2026: "lakukan yang
    # sama ke menunggu keputusan". Bentuknya sama persis dengan `/aksi`
    # (`?grup=` di sana), hanya alamat & sumbernya yang beda: `?golongan=`,
    # grupnya dari `services/keputusan.py` lewat `svc.grup_keputusan`.
    #
    # Angkanya dihitung dari `meja_non_mutu` SEBELUM disaring — sub-menu yang
    # menyebut "0" untuk golongan yang sedang tidak dipilih akan membuat
    # orang menyimpulkan pekerjaannya habis.
    n_golongan = {k: 0 for k, _ in svc.GRUP_KEPUTUSAN}
    for x in meja_non_mutu:
        n_golongan[svc.grup_keputusan(x)] += 1
    golongan = (request.query_params.get("golongan") or "").strip()
    if golongan not in dict(svc.GRUP_KEPUTUSAN):
        golongan = ""       # alamat ngawur = tampilkan semuanya, bukan 422
    meja_tampil = ([x for x in meja_non_mutu if svc.grup_keputusan(x) == golongan]
                   if golongan else meja_non_mutu)

    return render(
        request, "keputusan.html", layar="keputusan",
        meja=meja_tampil, lama=svc._lama,
        # Pil saringan: hanya golongan yang BERISI ditawarkan, ditambah yang
        # sedang dipilih — sama alasannya dengan `GRUP_PIL` di `/aksi`.
        GRUP_PIL=[(k, nama, n_golongan[k]) for k, nama in svc.GRUP_KEPUTUSAN
                 if n_golongan[k] or k == golongan],
        GRUP_KINI=golongan,
        GRUP_TOTAL=sum(n_golongan.values()),
        # Jaringnya memakai SELURUH meja — termasuk golongan mutu — supaya
        # jenis yang tak dikenal tertangkap di sini apa pun golongannya yang
        # kelak diberikan orang kepadanya. Disaring golongan juga: memilih
        # "Lainnya" tak boleh tetap menjaring item yang sudah tergambar di
        # golongan lain.
        semua_meja=(b.meja if not golongan or golongan == "lain"
                   else [x for x in b.meja if svc.grup_keputusan(x) == golongan]),
        JENIS_KEPUTUSAN=JENIS_KEPUTUSAN, AKSI_DIKENAL=AKSI_DIKENAL,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        **b.lencana(),
    )


@router.get("/mutu")
async def halaman_mutu(request: Request, akun=Depends(butuh_admin)):
    """"Mutu & QC" — dua blok yang pecah dari Menunggu keputusan.

    Gerbangnya SAMA dengan `/keputusan` (`butuh_admin`, peran efektif): mutu
    selalu jadi kerja meja, dan memisahkan layarnya tidak memindahkan
    wewenangnya. Admin yang sedang memakai "Lihat sebagai operator" pun ditolak
    — samaran yang masih memegang wewenangnya bukan samaran.

    **Operator tidak melihat halaman ini sama sekali** (pemilik, 24 September
    2026). Yang ia lihat adalah MUTU BARANGNYA, di tempat barang itu berada:
    baris mutu pada kartu di layar Stok dan pada kartu proses yang sedang
    berjalan. Bedanya bukan soal kerahasiaan melainkan soal pekerjaan —
    menilai mutu dan MENAGIH penilaian itu dua pekerjaan berbeda, dan yang
    kedua dikerjakan dari meja.

    Pencatatan mutu bisa dimatikan seluruhnya di Pengaturan. Saat mati, laci
    tak menawarkan pintunya (`Berjalan.lencana` → `PINTU_MATI`) — tetapi
    alamatnya tetap bisa diketik, dan halaman yang kosong tanpa penjelasan
    terbaca seperti "sudah beres". Maka ia menyebut sebabnya.
    """
    async with SessionLocal() as db:
        b = await svc.untuk(db, akun.user)
    return render(
        request, "mutu.html", layar="mutu",
        meja=[x for x in b.meja if K.golongan_mutu(x.aksi)], lama=svc._lama,
        JENIS_MUTU=JENIS_MUTU,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        **b.lencana(),
    )
