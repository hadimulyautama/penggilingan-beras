"""Layar Riwayat sosoh — ke mana perginya bahan baku tiap penyosohan.

Keputusan pemilik 2 Oktober 2026: *"berisi kartu proses sosoh yang selesai
berikut seluruh informasinya dan hasilnya. terkhusus berapa persen yang jadi
beras, berapa persen broken, berapa persen menir, berapa persen bekatul, lalu
berapa persen susut debu/bobot."*

Yang dijawabnya tak dijawab layar lain, dan itu sebabnya ia berdiri sendiri:

    /stok-produk   BERAPA yang ada sekarang — per kategori, seluruh riwayat
    /berjalan      proses yang MASIH menyala, angkanya belum final
    /laporan       apa yang terjadi HARI INI, seluruh pabrik
    halaman ini    satu proses = satu kartu, dan NERACANYA: 100% bahan baku
                   dibagi ke beras, samping, dan susut

Pertanyaan "berapa persen susut" tak bisa dijawab layar stok sama sekali: stok
menyebut apa yang ADA, sedangkan susut justru yang TIDAK ada — ia cuma terbaca
sebagai selisih antara yang masuk mesin dan yang keluar darinya.

HANYA YANG SELESAI. Proses berjalan sudah punya pintunya di `/berjalan`, dan
persen yang dihitung dari hasil yang masih bertambah akan dibaca sebagai hasil
akhir — lalu dipakai menilai mesin.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter()

#: Sekali muat. Cukup besar untuk memuat sebulan penyosohan di pabrik ini,
#: cukup kecil untuk halaman yang dibuka di gudang lewat 4G.
SEKALI = 30


@router.get("/riwayat-sosoh")
async def halaman_riwayat_sosoh(request: Request, akun=Depends(butuh_akun)):
    """Kartu penyosohan selesai, terbaru lebih dulu, berikut neraca bobotnya."""
    from app.penggilingan.gudang2.polishing import SAMPING_DISEBUT, riwayat_sosoh
    from app.web.api import _is_g2_operator

    # ⚠ DIJAGA DI RUTENYA, bukan cuma di daftar pintu. Keputusan pemilik:
    # "hanya super admin, admin dan operator gudang 2 yang bisa lihat" —
    # dan `nav.TAB` hanya memilih pintu MANA YANG DITAWARKAN; alamatnya tetap
    # bisa diketik, dan halaman di ponsel berumur panjang.
    #
    # `_is_g2_operator` sudah berarti tepat ketiganya: admin ke atas selalu
    # boleh, operator hanya bila Gudang 2 yang SEDANG ia kerjakan (operator
    # tak terikat satu gudang — ia berpindah lewat "Kerja di gudang").
    # Menuliskan sendiri "superadmin atau admin atau operator g2" di sini
    # berarti menyebut peran harfiah, dan peran baru di puncak sudah sembilan
    # kali tertinggal di gerbang yang menyebut nama.
    if not await _is_g2_operator(akun.user):
        raise HTTPException(
            403, "Riwayat sosoh milik Admin ke atas dan operator Gudang 2.")

    sebelum = request.query_params.get("sebelum")
    try:
        sebelum_id = int(sebelum) if sebelum else None
    except ValueError:
        # Kursor ngawur diperlakukan sebagai "dari awal", bukan galat: ia
        # datang dari alamat yang diketik atau ditempel, dan halaman yang
        # menolak dengan 422 tak memberi jalan keluar kepada yang membacanya.
        sebelum_id = None

    async with SessionLocal() as db:
        kartu, lagi = await riwayat_sosoh(db, batas=SEKALI, sebelum=sebelum_id)
    return await render_laci(
        request, "riwayat_sosoh.html",
        kartu=kartu, lagi=lagi, SEKALI=SEKALI,
        SAMPING_DISEBUT=SAMPING_DISEBUT,
        # Kursor halaman berikutnya: id kartu TERAKHIR yang digambar.
        sesudah=(kartu[-1].id if kartu and lagi else None),
        # Halaman kedua dan seterusnya butuh jalan kembali — tanpa ini
        # satu-satunya jalan pulang adalah tombol kembali peramban, dan
        # `pindah.js` membuat riwayat peramban tak sejalan dengan halamannya.
        dari_awal=bool(sebelum_id),
    )
