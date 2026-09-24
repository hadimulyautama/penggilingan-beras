"""Layar Stok — PK yang masih ada, dan gudangnya mengikuti VIEW pembacanya.

Satu alamat, dua isi. Operator selepan melihat lot giling Gudang 1; operator
polesan melihat silo dan tumpukan Gudang 2; Admin ke atas melihat keduanya,
Gudang 1 lebih dulu. Sebelum ini semua orang melihat Gudang 1 — termasuk
operator yang bekerja di Gudang 2, yang halaman Stoknya seluruhnya berisi
barang gudang sebelah.

Operator hanya membaca. Yang boleh mengoreksi hanya Admin ke atas, dan yang
dikoreksi adalah HASIL GILINGNYA — bukan angka stoknya.

Bedanya penting. Stok = hasil − dikirim − dijual; membolehkan orang mengetik
stok berarti membolehkan salah satu dari ketiganya dibengkokkan tanpa jejak,
dan selisih yang ditutupi berhenti jadi pertanyaan. Yang dibuka di sini justru
aksi yang sudah ada dan sudah tercatat: verifikasi output giling. Ia menulis
`berat_output_final_kg`, masuk log aktivitas, bisa dibatalkan lewat List audit,
dan karena rendemen serta stok adalah TURUNAN dari angka itu, keduanya berubah
sendiri — tak ada angka kedua yang bisa berselisih.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import SessionLocal
from app.services import stok as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


async def _karung(db, view: str, gudang: str = "") -> list[dict]:
    """Baris stok karung yang boleh dilihat view ini — atau daftar kosong.

    Operator Gudang 1 tidak melihat blok ini sama sekali: karung mengemas
    beras JADI, dan itu pekerjaan Gudang 2. Yang memegang kedua gudang
    (Admin ke atas) ikut melihat karung PK di Gudang 1, karena ia yang
    memesannya.

    `gudang` = pil penyaring di kepala halaman (kunci pendek, "" = semua).
    Karung ikut disaring karena membuka "Gudang 1" lalu melihat karung Gudang 2
    di bawahnya membuat penyaringnya berbohong — kalimat yang sama dipakai Meja.
    Namanya diterjemahkan dari master (`NAMA_GUDANG`), bukan dibandingkan
    sebagai teks: nama gudang bisa diubah, kunci pendeknya tidak.
    """
    from app.web.layar import NAMA_GUDANG, gudang1, gudang2

    if not gudang2(view):
        return []
    from app.penggilingan.inventory import packaging as kms

    nama = NAMA_GUDANG.get(gudang, "") if gudang else ""
    return [b for b in await kms.stok_kemasan_rinci(db)
            if (b["gudang"] != "Gudang 1" or gudang1(view))
            and (not nama or b["gudang"] == nama)]


@router.get("/stok")
async def halaman_stok(request: Request, akun=Depends(butuh_akun)):
    from app.services.setelan import fitur_mutu

    from app.web.layar import GUDANG, MEJA, NAMA_GUDANG, POLESAN, gudang1, gudang2

    view = getattr(request.state, "view", "tamu")
    # ── Penyaring gudang (celah ke-5, setengahnya tertinggal) ──
    #
    # Aturannya SATU dan sudah ditulis di layar Sedang berjalan: pilnya milik
    # view yang memegang KEDUA gudang (`GUDANG if view in MEJA else ()`).
    # Halaman ini dulu memasok daftar kosong dengan alasan "Pos Produksi
    # memberi tiap orang SATU gudang lewat view" — benar untuk operator, salah
    # untuk Admin & Super Admin, dan justru dua view itulah yang mendapat
    # pilnya di /berjalan. Satu app, satu nama kontrak, dua jawaban (QA 24
    # September 2026 (c) butir 7).
    saring = GUDANG if view in MEJA else ()
    gudang = request.query_params.get("gudang") or ""
    if gudang not in {g for g, _, _ in saring}:
        gudang = ""                       # nilai karangan dari URL diabaikan
    async with SessionLocal() as db:
        # Gudang 1 per LOT GILING, Gudang 2 per TEMPAT — dua satuan, karena
        # bendanya memang dua rupa (lihat catatan di `app.services.stok`).
        #
        # ── PK Gudang 1 TERLIHAT oleh operator Gudang 2 ──
        #
        # Keputusan pemilik 24 September 2026, dan hanya di layar Stok. Dulu
        # syaratnya `gudang1(view)` saja, dengan alasan tertulis: "operator
        # hanya menerima gudangnya sendiri; halaman Stok yang menampilkan silo
        # gudang sebelah menjawab pertanyaan yang tak ia ajukan."
        #
        # Kalimat itu tetap BENAR untuk silo dan dryer Gudang 1 — dan SALAH
        # untuk PK yang sudah jadi. PK itulah BAHAN BAKU orang ini: yang
        # memutuskan "hari ini menyosoh apa" perlu tahu ada KS atau KL berapa
        # di sebelah, mutunya bagaimana, dan dari gabah siapa. Selama ia tak
        # bisa melihatnya, satu-satunya cara mengetahuinya adalah bertanya
        # lewat telepon — dan yang ditanya lewat telepon tak pernah tercatat.
        #
        # Yang TETAP tertutup untuknya, dan sengaja: silo & dryer Gudang 1
        # (blok `tempat` di bawah punya gerbangnya sendiri), stok karung
        # Gudang 1 (`_karung`), dan halaman `/gudang/g1` (403 di rutenya).
        # Melihat bahan bukan memegang gudangnya.
        #
        # Blok ini berjudul "PK di Gudang 1" dan totalnya hanya menjumlah lot
        # ini — bukan menyatu dengan stok Gudang 2. Operator yang mengira
        # barang ini sudah ada di gudangnya akan menghitung stok yang tak ia
        # pegang.
        #
        # Penyaringnya ikut menentukan apa yang dibaca, bukan menyembunyikan
        # yang sudah dibaca: kueri stok gudang sebelah mahal, dan membayarnya
        # untuk angka yang tak akan tampil tak ada gunanya. Hari ini operator
        # tak ditawari pil gudang sama sekali (`saring` kosong baginya), jadi
        # `gudang` selalu "" dan syarat di bawah lolos. KALAU kelak pil itu
        # diberikan kepada operator, syarat ini harus ditinjau ulang: bagi
        # operator polesan, "Gudang 1" berarti melihat BAHAN, bukan melihat
        # gudang orang lain.
        lot = (await svc.pk_gudang1(db)
               if (gudang1(view) or gudang2(view)) and gudang in ("", "g1") else [])
        tempat = (await svc.pk_gudang2(db)
                  if gudang2(view) and gudang in ("", "g2") else [])
        mutu_aktif = await fitur_mutu(db)
        karung = await _karung(db, view, gudang)
        # ── Barang jadi & hasil samping ──
        # Gerbang yang SAMA dengan stok karung tepat di bawahnya: barang jadi
        # lahir di Gudang 2, jadi operator selepan tak melihatnya. Sampai 23
        # September 2026 layar ini tak punya bloknya sama sekali — hitungannya
        # terkunci di `gudang2_api.stok`, dan Pos Produksi yang memegang KEDUA
        # gudang justru buta terhadap apa yang sudah jadi.
        # Barang jadi milik Gudang 2, jadi ia ikut penyaring di kepala halaman —
        # membuka "Gudang 1" lalu melihat barang jadi Gudang 2 di bawahnya
        # membuat penyaringnya berbohong (kalimat yang sama di Meja).
        bj = (await svc.barang_jadi_g2(db) if gudang2(view) and gudang in ("", "g2")
              else svc.BarangJadiG2(produk=[], samping=[]))
    return await render_laci(
        request, "stok.html", layar="stok",
        lot=lot, tempat=tempat,
        # `SARING_GUDANG` = nama kontrak templat bersama (Tahap 2). Kosong untuk
        # operator: ia sudah diberi satu gudang lewat view-nya, dan pil tunggal
        # bernama "Semua" tak membedakan apa pun.
        SARING_GUDANG=saring, gudang=gudang,
        produk=bj.produk, samping=bj.samping,
        total=sum(l.tersedia for l in lot),
        # `is_admin` sudah memakai peran EFEKTIF: saat admin memakai "Lihat
        # sebagai operator", `akun.user.role` diganti, jadi tombolnya ikut
        # hilang — samaran yang masih memegang wewenangnya bukan samaran.
        # Penjagaan sungguhannya tetap di rute aksinya sendiri; ini hanya
        # menyembunyikan tombol yang memang tak akan berhasil ditekan.
        # Koreksi hasil giling milik Gudang 1. Operator polesan tak punya
        # hasil giling untuk dikoreksi, dan tombolnya pun tak ada di
        # kartunya — tetapi `boleh_ubah` juga yang memasang `aksi.js` di
        # kaki halaman, jadi ia dimatikan di view yang tak memuat kartunya.
        boleh_ubah=akun.is_admin and view != POLESAN,
        # ── "Minta lot ini" — hanya view yang memegang Gudang 2 ──
        #
        # Operator selepan tak boleh melihatnya (bukan pekerjaannya), dan Admin
        # tak membutuhkannya — ia bisa memindahkan langsung. Menyembunyikan
        # tombolnya BUKAN penjagaan: rutenya dijaga sendiri
        # (`api.act_minta_pk_g1` menuntut operator Gudang 2), dan yang di sini
        # cuma menghindari menawarkan pintu yang akan ditolak.
        boleh_minta=view == POLESAN,
        # Stok karung, keputusan pemilik 23 September 2026: dilihat operator
        # Gudang 2, Admin, dan Super Admin — TIDAK operator Gudang 1. Aturan
        # siapa-melihat-apa tidak ditulis ulang di sini; ia sudah bernama
        # `gudang2(view)`, dan karung memang barang Gudang 2 (kecuali karung
        # PK, yang ikut ke sana hanya bagi yang juga memegang Gudang 1).
        karung=karung,
        # Mutu bisa dimatikan seluruhnya di Pengaturan — termasuk barisnya di
        # kartu ini. Setengah mati adalah yang terburuk: kartu yang masih
        # menyebut "belum dinilai" sementara borangnya tak ada menagih
        # pekerjaan yang tak bisa dikerjakan siapa pun.
        mutu_aktif=mutu_aktif,
        # Lembarnya terbuka DI SINI, bukan melemparkan orang ke layar aksi:
        # yang sedang dibaca adalah kartu ini, dan berpindah layar berarti
        # kehilangan tempatnya.
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
    )
