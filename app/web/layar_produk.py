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
        # ⚠ Barang TITIPAN (pesanan jasa) tak ikut rincian halaman ini —
        # kartu kategorinya (`kartu`, dari `stok_produk()`) sengaja tetap
        # PABRIK saja. Barang titipan mendapat halamannya sendiri sejak 6
        # Oktober 2026 (`/stok-produk-jasa`, keputusan pemilik). Tanpa
        # saringan ini, rincian kemasan di sini akan menjumlah lebih besar
        # daripada kepala kartunya — dua angka bertentangan di satu kartu.
        if k.get("jasa_id") is not None:
            continue
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
    # ── OBATNYA DI SEBELAH KELUHANNYA ──
    #
    # Laporan operator 30 September 2026: "pilihan bekatul curah belum ada,
    # jika ada katul yg belum dikemas, pada stok produk tertulis belum
    # dicatat." Aksinya SELALU ada — "Catat bekatul (curah)" — tetapi ia
    # tinggal di Catat pekerjaan lain, sedangkan yang membaca "belum dicatat"
    # sedang berdiri di halaman ini. Tulisan itu sendiri benar; ia keluhan
    # aplikasi tentang pekerjaan yang belum dilakukan. Yang salah cuma
    # letaknya: menagih di satu layar dan menyediakan obatnya di layar lain.
    #
    # Lembarnya terbuka DI HALAMAN INI, sama seperti Barang Keluar — orang
    # yang sedang membaca angka bekatulnya tak boleh tiba-tiba berdiri di
    # daftar pekerjaan gudang.
    #
    # TIGA HAL harus benar bersamaan, dan yang ketiga paling mudah terlupa:
    # rutenya membaca `?buka=`, templatnya jadi tuan rumah dialognya, DAN
    # `aksi.js` ikut dimuat. Tanpa yang ketiga tombolnya cuma memuat ulang
    # halaman — kesalahan yang persis pernah terjadi di layar Stok.
    from app.web.api import _is_g2_operator

    boleh_catat = await _is_g2_operator(akun.user)
    return await render_laci(
        request, "stok_produk.html", layar="stok_produk",
        BOLEH_CATAT=boleh_catat,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        kartu=kartu, kemasan=kemasan, beras=beras, samping=samping,
        sisa_beras=sum(k.sisa_kg for k in beras if k.sisa_kg > 0),
        sisa_samping=sum(k.sisa_kg for k in samping if k.sisa_kg > 0),
        curah_beras=sum(k.curah_kg for k in beras if k.curah_kg > 0),
        curah_samping=sum(k.curah_kg for k in samping if k.curah_kg > 0),
    )


@router.get("/stok-produk-jasa")
async def halaman_stok_produk_jasa(request: Request, akun=Depends(butuh_akun)):
    """Barang jadi & hasil samping MILIK PESANAN JASA — terpisah per pelanggan.

    Keputusan pemilik 6 Oktober 2026: *"buat saja halaman khusus stock
    produk dan stock hasil samping dari jasa. masuk di sub menu stock ...
    tapi pisahkan per pelanggan pemilik barang."* Lalu: *"tampilannya juga
    harus konsisten seperti kartu stock milik kami sendiri."*

    `/stok-produk` memuat barang PABRIK saja (keputusan yang sama) — barang
    titipan disaring KELUAR dari sana, bukan disembunyikan: halaman ini
    tempatnya. SATU SEKSI PER PESANAN, kartunya rupa yang SAMA PERSIS dengan
    `/stok-produk` (empat suku + laci FIFO, `stok.stok_produk(jasa_id=...)`
    + makro `st.blok` yang sama) — bukan rupa yang lebih sederhana; dua
    halaman yang menjawab pertanyaan serupa dengan dua rupa kartu berbeda
    membuat orang mengira satunya kurang lengkap.

    Satu panggilan `stok_produk` per pesanan, bukan satu kueri borongan
    disaring belakangan: `jasa_id` sudah menyaring di SUMBERNYA (proses,
    dikemas, keluar) — lihat catatan panjang di sana untuk kenapa itu
    penting (bekatul, terutama).
    """
    from sqlalchemy import select

    from app.penggilingan.gudang2.models import PolishingProcess
    from app.services.jasa import nama_pemilik_banyak
    from app.web.layar import SELEPAN

    view = getattr(request.state, "view", "tamu")
    # Gerbang yang SAMA dengan `/stok-produk`: barang jadi & titipannya
    # lahir di Gudang 2.
    if view == SELEPAN:
        raise HTTPException(403, "Layar ini milik Gudang 2.")
    async with SessionLocal() as db:
        jasa_ids = sorted((await db.execute(
            select(PolishingProcess.jasa_id.distinct())
            .where(PolishingProcess.jasa_id.isnot(None))
        )).scalars().all())
        nama = await nama_pemilik_banyak(db, jasa_ids)
        bj = await svc.barang_jadi_g2(db)
        daftar = []
        for jid in jasa_ids:
            kartu = await svc.stok_produk(db, jasa_id=jid)
            if not kartu:
                continue
            kemasan: dict[str, list[dict]] = {}
            for k in bj.produk + bj.samping:
                if k.get("jasa_id") != jid:
                    continue
                kemasan.setdefault(k["jenis"], []).append(k)
            beras = [k for k in kartu if svc.adalah_beras(k.jenis)]
            samping = [k for k in kartu if not svc.adalah_beras(k.jenis)]
            daftar.append({
                "pemilik": nama.get(jid) or f"pesanan #{jid}",
                "kemasan": kemasan, "beras": beras, "samping": samping,
                "sisa_beras": sum(k.sisa_kg for k in beras if k.sisa_kg > 0),
                "sisa_samping": sum(k.sisa_kg for k in samping if k.sisa_kg > 0),
                "curah_beras": sum(k.curah_kg for k in beras if k.curah_kg > 0),
                "curah_samping": sum(k.curah_kg for k in samping if k.curah_kg > 0),
            })
    daftar.sort(key=lambda p: p["pemilik"])
    return await render_laci(
        request, "stok_produk_jasa.html", layar="stok_produk_jasa",
        daftar=daftar,
    )
