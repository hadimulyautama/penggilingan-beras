"""Layar Stok Produk — HASIL pabrik, bukan bahannya.

Keputusan pemilik 26 September 2026: "bagusnya ada halaman baru yaitu Stok
Produk, dan kartu hasil sosoh berada di situ."

Sebabnya temuan QA hari itu: beras yang sudah keluar dari mesin sosoh tidak ada
di angka stok mana pun. `polishing_output_logs` dibaca tepat dua tempat di
seluruh repo — pembanding internal, dan satu baris ringkasan laporan — dan tak
satu pun layar stok membacanya. Beras baru MENJADI stok ketika seseorang
menjalankan "Catat packing"; di pabrik, jarak antara "sosoh selesai" dan
"packing dicatat" adalah jam, kadang hari. Sepanjang waktu itu berton-ton beras
berdiri di lantai sementara aplikasi menyebut stoknya nol.

Ketimpangannya dengan Gudang 1 yang membuatnya terasa hilang: lot giling yang
selesai berkartu lengkap di layar Stok, dan PK-nya terhitung siap kirim. Output
Gudang 1 adalah stok; output Gudang 2 tinggal baris log — padahal keduanya
sama-sama barang yang berdiri di lantai gudang.

PEMBAGIANNYA:
    /stok         BAHAN  — gabah di silo Gudang 1, PK di Gudang 2
    /stok-produk  HASIL  — DUA BLOK: beras, lalu hasil samping

SATU KARTU PER KATEGORI, bukan per lot (keputusan pemilik 26 September 2026):
"stok produk setiap kategori dijadikan 1 kartu saja dengan informasi inti total
jumlah stock. tetapi di setiap kartu ada informasi dari masing-masing
penyosohan dan informasi stock yang sudah keluar." — "misal. premium dijadikan
1 kartu saja."

Hitungannya di `services.stok.stok_produk`; layar ini cuma menggambar. Rincian
KEMASANNYA (merk × ukuran) tetap diambil dari `barang_jadi_g2`, hitungan yang
sudah dipakai layar lain — dua hitungan untuk satu pertanyaan akan berselisih
pada perubahan berikutnya.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.services import stok as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


@router.get("/stok-produk")
async def halaman_stok_produk(request: Request, akun=Depends(butuh_akun)):
    from app.web.layar import SELEPAN

    view = getattr(request.state, "view", "tamu")
    # Operator selepan tak punya urusan di sini — beras dan hasil samping lahir
    # di Gudang 2. Pintunya sudah tak ditawarkan (`PINTU_MATI`), tetapi pintu
    # yang disembunyikan bukan penjagaan: alamatnya bisa diketik, dan lembar
    # yang masih terbuka di layar orang lain masih bisa memanggilnya.
    if view == SELEPAN:
        raise HTTPException(403, "Layar ini milik Gudang 2.")
    async with SessionLocal() as db:
        kartu = await svc.stok_produk(db)
        bj = await svc.barang_jadi_g2(db)
    # Rincian kemasan digantung ke kartu kategorinya lewat `jenis` — kunci yang
    # sama yang dipakai `stok.jenis_produk`, jadi tak ada pemetaan kedua yang
    # bisa berselisih. Angkanya NETO (masuk − keluar) seperti di layar barang
    # jadi, supaya jumlahnya sama dengan baris "sudah dikemas" di kartunya;
    # rincian bruto di bawah angka neto akan dijumlah orang lalu tak cocok.
    kemasan: dict[str, list[dict]] = {}
    for k in bj.produk + bj.samping:
        kemasan.setdefault(k["jenis"], []).append(k)
    # ── DUA BLOK, bukan satu daftar (permintaan pemilik 28 September 2026) ──
    #
    # "tolong buat block khusus untuk beras dan block khusus hasil samping."
    #
    # Pemilahannya `stok.adalah_beras`, bukan dikerjakan templat: aturan "mana
    # yang beras" sudah dibaca hitungan packing dan kartu barang jadi, dan
    # aturan yang hidup kedua kali di Jinja akan berselisih dengan yang di
    # Python tanpa satu uji pun bisa menangkapnya.
    #
    # Jumlahnya DIHITUNG PER BLOK, dan itu yang sebetulnya diminta. Satu angka
    # besar yang menjumlah beras dengan bekatul bukan jumlah apa pun: keduanya
    # kilogram, harganya berbeda berkali-kali, dan pembelinya berbeda orang.
    beras = [k for k in kartu if svc.adalah_beras(k.jenis)]
    samping = [k for k in kartu if not svc.adalah_beras(k.jenis)]
    return await render_laci(
        request, "stok_produk.html", layar="stok_produk",
        kartu=kartu, kemasan=kemasan, beras=beras, samping=samping,
        sisa_beras=sum(k.sisa_kg for k in beras if k.sisa_kg > 0),
        sisa_samping=sum(k.sisa_kg for k in samping if k.sisa_kg > 0),
        curah_beras=sum(k.curah_kg for k in beras if k.curah_kg > 0),
        curah_samping=sum(k.curah_kg for k in samping if k.curah_kg > 0),
    )
