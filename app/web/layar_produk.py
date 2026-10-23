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
from app.services import jasa
from app.services import stok as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


@router.get("/stok-produk")
@router.get("/stok-produk/detail")
async def halaman_stok_produk(request: Request, akun=Depends(butuh_akun), jenis: str | None = None):
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
    from hmu_identitas import peran as P

    # Tombol “Masukkan broken ke silo” juga menerima Super Admin secara
    # eksplisit di endpoint. Pastikan tampilan kartu memakai gerbang yang sama.
    boleh_catat = (await _is_g2_operator(akun.user)
                   or P.super_saja(akun.user.role))
    if request.url.path.endswith("/detail"):
        return await _detail_produk(request, kartu, jenis, kemasan,
                                    boleh_catat=boleh_catat)
    return await render_laci(
        request, "stok_produk.html", layar="stok_produk",
        BOLEH_CATAT=boleh_catat,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        kartu=kartu, kemasan=kemasan, beras=beras, samping=samping,
        sisa_beras=sum(k.sisa_kg for k in beras if k.sisa_kg > 0),
        sisa_samping=sum(k.sisa_kg for k in samping if k.sisa_kg > 0),
        curah_beras=sum(k.curah_kg for k in beras if k.curah_kg > 0),
        curah_samping=sum(
            (k.curah_otomatis_kg if k.jenis in {"bekatul", "reject", "menir", "broken"}
             else k.curah_kg)
            for k in samping if k.sisa_kg > 0),
    )


@router.get("/stok-produk-jasa")
@router.get("/stok-produk-jasa/detail")
async def halaman_stok_produk_jasa(request: Request, akun=Depends(butuh_akun),
                                  jenis: str | None = None, pelanggan_id: int | None = None):
    """Barang jadi & hasil samping MILIK PESANAN JASA — terpisah per PELANGGAN.

    Keputusan pemilik 6 Oktober 2026: *"buat saja halaman khusus stock
    produk dan stock hasil samping dari jasa. masuk di sub menu stock ...
    tapi pisahkan per pelanggan pemilik barang."* Lalu: *"tampilannya juga
    harus konsisten seperti kartu stock milik kami sendiri."* Dan koreksi
    susulan: *"pemisahannya bukan per proses. tapi per pelanggan."*

    `/stok-produk` memuat barang PABRIK saja (keputusan yang sama) — barang
    titipan disaring KELUAR dari sana, bukan disembunyikan: halaman ini
    tempatnya. Kartunya rupa yang SAMA PERSIS dengan `/stok-produk` (empat
    suku + laci FIFO, `stok.stok_produk(jasa_id=...)` + makro `st.blok` yang
    sama) — bukan rupa yang lebih sederhana.

    ⚠⚠ SATU SEKSI PER PELANGGAN (`Jasa.pelanggan_id`), BUKAN PER PESANAN
    (`Jasa.id`). "SATU PESANAN, BEBERAPA KEDATANGAN" berarti kedatangan
    ulang dari pelanggan yang SAMA tetap melahirkan `Jasa` BARU (lihat
    docstring modelnya) — dan pengelompokan per pesanan memecah barang satu
    pelanggan jadi beberapa seksi berbeda, tepat kebalikan dari yang
    diminta. `stok.stok_produk` menerima DAFTAR `jasa_id` justru untuk ini:
    seluruh pesanan pelanggan yang sama disatukan dalam SATU panggilan,
    bukan digabung belakangan dari beberapa kartu terpisah.

    ── Bekatul: disebut, DAN sejak 6 Oktober 2026 juga berkartu+bertombol ──

    Keluhan pemilik mula-mula: *"bekatulnya kenapa tidak ada di halaman
    produk jasa? tetap harus ada."* Jawaban pertama (28 September–6 Oktober):
    baris informasi tanpa tombol, sebab bekatul otomatis milik pabrik
    (keputusan 12). PEMBALIKAN menyusul hari yang sama, sesudah laporan
    lapangan operator packing bekatul jasa dan Stok Produk pabrik menuduh
    salah catat: *"jadi stock terpisah sampai pindah kepemilikan"* — bekatul
    sekarang mengikuti pola broken/menir/reject apa adanya.

    Akibatnya DUA bentuk sekaligus, dan keduanya BENAR untuk pertanyaan
    yang berbeda:

      · Bekatul yang MASIH MILIK PESANAN (hasil_ditahan tak menahannya, kasus
        BARU/bawaan) ikut `kartu` lewat `stok_produk(jasa_id=...)` apa
        adanya — masuk `samping` di bawah, berkartu PENUH (Hasil sosoh/
        Keluar/Dikemas/Curah) persis broken/menir/reject, DAN kalau sudah
        dicatat curah dapat tombol "Pindah kepemilikan" sendiri
        (`bekatul_curah_kg`, mengikuti bentuk `broken_curah_kg` tepat di
        bawah) — karung bekatulnya sudah tertangani otomatis lewat `st.blok`
        yang sama (`boleh_pindah`).
      · Bekatul yang SUDAH TERLANJUR MILIK PABRIK (pesanan lama yang
        `hasil_ditahan`-nya belum dibackfill, migrasi
        `0073_bekatul_bukan_ditahan`) TETAP baris informasi tanpa tombol
        (`bekatul_kg`) — tak ada kepemilikan untuk dipindah, sudah pabrik.
        Jarang terjadi pasca migrasi, tapi disebut tetap — bukan
        disembunyikan, pola yang sama dengan `jasa.nota_jasa()`.

    ── Pindah kepemilikan: Admin & Super Admin saja ──

    `BOLEH_PINDAH` dioper ke templat dengan gerbang yang SAMA dengan
    `produk_jasa_tersedia`/`act_pindah_kepemilikan_produk`
    (`can_see_financials`) — operator yang membuka halaman ini tak boleh
    melihat tombol yang akan ditolak rutenya.
    """
    from sqlalchemy import func, select

    from app.models import Pelanggan
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.penggilingan.inventory.finished_goods import (hitung_stok_bekatul,
                                                            hitung_stok_broken_curah)
    from app.penggilingan.inventory.models import (ByproductStock,
                                                    FinishedGoodsStock, ProductSku)
    from app.peran import can_see_financials
    from app.web.layar import SELEPAN
    from hmu_identitas import peran as P
    from app.web.api import _is_g2_operator

    view = getattr(request.state, "view", "tamu")
    # Gerbang yang SAMA dengan `/stok-produk`: barang jadi & titipannya
    # lahir di Gudang 2.
    if view == SELEPAN:
        raise HTTPException(403, "Layar ini milik Gudang 2.")
    async with SessionLocal() as db:
        # Pesanan mana saja yang PERNAH menghasilkan sosoh — lalu pelanggan
        # mana yang memiliki tiap pesanan itu. Sumber BERSAMA dengan picker
        # katalog umum (`aksi_inventory.produk_jasa_tersedia`) — lihat
        # docstring `jasa_ids_per_pelanggan_dengan_hasil` untuk kenapa
        # keduanya wajib mengelompokkan dengan cara yang SAMA.
        jasa_per_pelanggan = await jasa.jasa_ids_per_pelanggan_dengan_hasil(db)
        from app.web.portal.scope import is_customer_read
        if is_customer_read(request):
            pid=request.state.portal_scope.reader.pelanggan_id
            jasa_per_pelanggan={pid:jasa_per_pelanggan[pid]} if pid in jasa_per_pelanggan else {}
        detail = request.url.path.endswith("/detail")
        if detail:
            if pelanggan_id not in jasa_per_pelanggan:
                raise HTTPException(404, "Stok produk pelanggan ini tidak ditemukan.")
            jasa_per_pelanggan = {pelanggan_id: jasa_per_pelanggan[pelanggan_id]}
        nama_pelanggan = {pid: n for pid, n in (await db.execute(
            select(Pelanggan.id, Pelanggan.nama_pelanggan)
            .where(Pelanggan.id.in_(jasa_per_pelanggan or {0}))
        )).all()}

        # Bekatul yang SUDAH MILIK PABRIK (bukan lagi milik pesanan) — per
        # proses, lalu per pesanan, lewat `source_id` (proses sosohnya).
        # Dibaca SEKALI untuk seluruh pelanggan, bukan satu kueri per seksi.
        #
        # ⚠⚠ DISARING `jasa_id IS NULL` — SEJAK 6 Oktober 2026 ini WAJIB,
        # bukan kosmetik. Bekatul yang MASIH milik pesanan (kasus umum
        # pasca-pembalikan keputusan 12) sudah tersebut lewat `kartu`
        # (`stok_produk(jasa_id=...)`, masuk `samping`) dan `bekatul_curah_kg`
        # di bawah — menjumlahkannya LAGI di sini tanpa saringan ini akan
        # menghitung bekatul yang SAMA dua kali: sekali sebagai kartu
        # bertombol, sekali lagi sebagai baris "sudah milik pabrik" yang
        # justru bohong untuk bekatul yang belum dipindah.
        #
        # DUA RUMAH, dan keduanya dijumlah — bekatul punya dua rumah sejak
        # 28 September 2026 (curah `ByproductStock` ATAU dikarungi
        # `FinishedGoodsStock`, lihat catatan panjangnya di `stok.
        # stok_produk`).
        bekatul_per_proc: dict[int, float] = {}
        for pid, kg in (await db.execute(
            select(ByproductStock.source_id,
                   func.coalesce(func.sum(ByproductStock.berat_kg), 0))
            .where(ByproductStock.jenis_produk == "bekatul",
                   ByproductStock.source_type == "polishing",
                   ByproductStock.jasa_id.is_(None))
            .group_by(ByproductStock.source_id)
        )).all():
            bekatul_per_proc[pid] = bekatul_per_proc.get(pid, 0.0) + float(kg)
        for pid, kg in (await db.execute(
            select(FinishedGoodsStock.source_id,
                   func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(ProductSku.kategori == "bekatul",
                   FinishedGoodsStock.source_type == "polishing",
                   FinishedGoodsStock.jasa_id.is_(None))
            .group_by(FinishedGoodsStock.source_id)
        )).all():
            bekatul_per_proc[pid] = bekatul_per_proc.get(pid, 0.0) + float(kg)
        proc_per_jasa: dict[int, list[int]] = {}
        for pid, jid in (await db.execute(
            select(PolishingProcess.id, PolishingProcess.jasa_id)
            .where(PolishingProcess.jasa_id.isnot(None))
        )).all():
            proc_per_jasa.setdefault(jid, []).append(pid)

        boleh_pindah = can_see_financials(akun.user)
        bj = await svc.barang_jadi_g2(db)
        daftar = []
        for pelanggan_id, jasa_ids in jasa_per_pelanggan.items():
            kartu = await svc.stok_produk(db, jasa_id=jasa_ids)
            bekatul_kg = sum(
                bekatul_per_proc.get(pid, 0.0)
                for jid in jasa_ids for pid in proc_per_jasa.get(jid, []))
            # Broken yang sudah dicatat CURAH (`byproduct_stock`, lewat
            # `catat_broken`) — TERPISAH dari `curah_kg` kartu "Broken" di
            # atas, yang menjawab pertanyaan lain ("belum tercatat sama
            # sekali"). Ia tak punya baris kemasan (bukan karung), jadi
            # tombol pindah kepemilikannya berdiri sendiri, bukan di dalam
            # `st.blok`. SATU panggilan dengan daftar `jasa_ids` (bukan
            # dijumlah per pesanan) — `hitung_stok_broken_curah` kini
            # menerima daftar sebangun `stok_produk()`, supaya angka yang
            # ditampilkan dan angka yang dijaga tombolnya adalah SATU
            # sumber: tombolnya membawa seluruh `jasa_ids` ini juga (lihat
            # `jasa_ids` di bawah), bukan cuma pesanan pertama — kalau
            # tombol hanya menunjuk satu pesanan, pagar jumlah transfer akan
            # menolak jumlah yang terlihat benar di kartu tapi melebihi sisa
            # SATU pesanan itu saja.
            broken_curah_kg = await hitung_stok_broken_curah(db, jasa_id=jasa_ids)
            # Bekatul curah yang MASIH milik pesanan ini — sebangun persis
            # `broken_curah_kg` di atas, bedanya cuma fungsi & jenisnya.
            # Bekatul yang sudah dikarungi TAK di sini: ia sudah ikut
            # `kartu`/`samping` (empat suku `stok_produk`, tombolnya lewat
            # `st.blok` biasa) — baris ini cuma belahan curahnya.
            bekatul_curah_kg = await hitung_stok_bekatul(db, jasa_id=jasa_ids)
            if (not kartu and bekatul_kg < 0.5 and broken_curah_kg < 0.5
                    and bekatul_curah_kg < 0.5):
                continue
            kemasan: dict[str, list[dict]] = {}
            for k in bj.produk + bj.samping:
                if k.get("jasa_id") not in jasa_ids:
                    continue
                kemasan.setdefault(k["jenis"], []).append(k)
            beras = [k for k in kartu if svc.adalah_beras(k.jenis)]
            samping = [k for k in kartu if not svc.adalah_beras(k.jenis)]
            daftar.append({
                "pelanggan_id": pelanggan_id,
                "pemilik": nama_pelanggan.get(pelanggan_id) or f"pelanggan #{pelanggan_id}",
                # SELURUH pesanan pelanggan ini — dipakai tombol curah
                # broken (`nilai=cr:broken|1,2,3`, lihat `_stok.html`) supaya
                # jumlah yang dijaga sama dengan `broken_curah_kg` di atas.
                "jasa_ids": jasa_ids,
                "kemasan": kemasan, "beras": beras, "samping": samping,
                "sisa_beras": sum(k.sisa_kg for k in beras if k.sisa_kg > 0),
                "sisa_samping": sum(k.sisa_kg for k in samping if k.sisa_kg > 0),
                "curah_beras": sum(k.curah_kg for k in beras if k.curah_kg > 0),
                "curah_samping": sum(
                    (k.curah_otomatis_kg if k.jenis in {"bekatul", "reject", "menir", "broken"}
                     else k.curah_kg)
                    for k in samping if k.sisa_kg > 0),
                "bekatul_kg": bekatul_kg,
                "bekatul_curah_kg": bekatul_curah_kg,
                "broken_curah_kg": broken_curah_kg,
            })
    daftar.sort(key=lambda p: p["pemilik"])
    # Samakan visibilitas tombol silo dengan gerbang aksi di API: operator
    # Gudang 2 tanpa akses finansial, atau Super Admin. Ini terpisah dari
    # BOLEH_PINDAH yang hanya mengatur pemindahan kepemilikan produk.
    boleh_masukkan_silo = (
        (await _is_g2_operator(akun.user) and not can_see_financials(akun.user))
        or P.super_saja(akun.user.role)
    )
    if detail:
        if not daftar:
            raise HTTPException(404, "Stok produk pelanggan ini tidak ditemukan.")
        p = daftar[0]
        return await _detail_produk(request, p["beras"] + p["samping"], jenis, p["kemasan"],
                                    pemilik=p["pemilik"], pelanggan_id=pelanggan_id,
                                    jasa_ids=p["jasa_ids"], boleh_pindah=boleh_pindah,
                                    boleh_masukkan_silo=boleh_masukkan_silo,
                                    curah_titipan={"broken":p["broken_curah_kg"],
                                                   "bekatul":p["bekatul_curah_kg"]})
    return await render_laci(
        request, "stok_produk_jasa.html", layar="stok_produk_jasa",
        daftar=daftar, BOLEH_PINDAH=boleh_pindah,
        BOLEH_MASUKKAN_SILO=boleh_masukkan_silo,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
    )


async def _detail_produk(request, kartu, jenis, kemasan, *, pemilik=None,
                         pelanggan_id=None, jasa_ids=(), boleh_catat=False,
                         boleh_pindah=False, boleh_masukkan_silo=False, curah_titipan=None):
    """Detail membaca kartu dan saringan pemilik yang sama dengan daftar."""
    k = next((k for k in kartu if k.jenis == jenis), None)
    if k is None:
        raise HTTPException(404, "Kategori stok produk ini tidak ditemukan.")
    halaman = "/stok-produk-jasa" if pelanggan_id is not None else "/stok-produk"
    from urllib.parse import urlencode
    detail_href = halaman + "/detail?" + urlencode({"jenis": jenis, **(
        {"pelanggan_id": pelanggan_id} if pelanggan_id is not None else {})})
    # Hak tampilan sama dengan endpoint silo; admin biasa tetap dapat membaca
    # tabel, sementara perpindahan dikerjakan operator G2 atau Super Admin.
    from hmu_identitas import peran as P
    from app.peran import can_see_financials
    from app.web.api import _is_g2_operator
    user = request.state.akun.user
    boleh_silo = ((await _is_g2_operator(user) and not can_see_financials(user))
                  or P.super_saja(user.role))
    boleh_kemas = await _is_g2_operator(user) or can_see_financials(user)
    rows = []
    otomatis = jenis in svc._UKURAN_KEMASAN_OTOMATIS
    owners = list(jasa_ids) if pelanggan_id is not None else [None]
    cards = {owners[0]: k} if len(owners) == 1 else {}
    if len(owners) > 1:
        async with SessionLocal() as db:
            for owner in owners:
                cards[owner] = next((c for c in await svc.stok_produk(db,jasa_id=owner)
                                     if c.jenis == jenis), None)

    from app.models import FinishedGoodsStock, ProductSku, RiceQualityStandard
    from sqlalchemy import select
    async with SessionLocal() as db:
        sisa_rows=(await db.execute(select(FinishedGoodsStock,ProductSku.kategori,RiceQualityStandard.kode)
            .join(ProductSku,ProductSku.id==FinishedGoodsStock.product_sku_id)
            .outerjoin(RiceQualityStandard,RiceQualityStandard.id==FinishedGoodsStock.rice_quality_standard_id)
            .where(FinishedGoodsStock.curah_kemas_ulang.is_(True),FinishedGoodsStock.berat_total_kg>0,
                FinishedGoodsStock.jasa_id.is_(None) if owners == [None] else FinishedGoodsStock.jasa_id.in_(owners)))).all()
        sisa_rows=[r for r in sisa_rows if svc.jenis_produk(r[1],r[2])==jenis]
    def kemas_href(sku_id,std_id,owner):
        return '/stok-produk/kemas-ulang?'+urlencode(dict(sku_id=sku_id,**({'std_id':std_id} if std_id else {}),**({'jasa_id':owner} if owner else {})))
    def baris(*, owner, bentuk, berat, jumlah=0, ukuran=0, merk="", bahan="", p=None):
        token = "pabrik" if owner is None else str(owner)
        aksi = ("masukkan_beras_silo" if jenis in svc.BERAS_JENIS else
                {"broken":"masukkan_broken_silo","menir":"masukkan_menir_silo",
                 "reject":"masukkan_reject_silo"}.get(jenis))
        sumber = (f"sku:{p['sku_id']}|{token}" if p and ukuran else f"curah|{token}")
        nilai = (f"{jenis}|{'pabrik' if owner is None else 'jasa'}" if jenis in svc.BERAS_JENIS else
                 f"pemilik|{token}" if jenis == "broken" else token)
        params = {"buka":aksi,"nilai":nilai}
        if jenis in svc.BERAS_JENIS:
            params["sumber_stok"] = sumber
        href = detail_href + "&" + urlencode(params) if aksi and berat > 0.5 and boleh_silo else None
        pindah = (f"bj:{p['sku_id']}|{p['std_id'] or ''}|{owner}"
                  if p and owner is not None and jumlah and boleh_pindah else None)
        rows.append(dict(bentuk=bentuk,kg=berat,karung=jumlah,ukuran=ukuran,merk=merk,
                         bahan=bahan,href=href,pindah=pindah,
                         kemas_baru=(detail_href+"&"+urlencode({"buka":"catat_packing","nilai":f"curah@{jenis}@{token}"})) if not p and not jumlah and berat>0.5 and boleh_kemas else None,
                         kemas=kemas_href(p["sku_id"],p["std_id"],owner) if p and jumlah and boleh_kemas else None,
                         sumber=sumber if jenis in svc.BERAS_JENIS else None))

    if otomatis:
        # Hasil samping mempertahankan pembagian kemasan otomatis yang sudah
        # dipakai kartu stok; per pesanan agar pemilik tidak tercampur.
        for owner in owners:
            c = cards.get(owner)
            if c is None:
                continue
            nyata=[p for p in kemasan.get(jenis,[]) if p.get('jasa_id')==owner]
            residu=sum(float(r[0].berat_total_kg) for r in sisa_rows if r[0].jasa_id==owner)
            ukuran_auto,jumlah_auto,kg_auto,curah_auto=svc._packing_otomatis(jenis,max(0,c.sisa_kg-sum(p['kg'] for p in nyata)-residu))
            if kg_auto:baris(owner=owner,bentuk="Kemasan otomatis",berat=kg_auto,jumlah=jumlah_auto,ukuran=ukuran_auto,bahan="Kemasan otomatis")
            for p in nyata:
                baris(owner=owner,bentuk="Kemasan",berat=p['kg'],jumlah=p['karung'],ukuran=p['ukuran'],merk=p['merk'],bahan=p['bahan'],p=p)
            if curah_auto:baris(owner=owner,bentuk="Curah",berat=curah_auto)
    else:
        for p in kemasan.get(jenis, []):
            baris(owner=p.get("jasa_id"),bentuk="Kemasan" if p["ukuran"] else "Curah",
                  berat=p["kg"],jumlah=p["karung"],ukuran=p["ukuran"],
                  merk=p["merk"],bahan=p["bahan"],p=p)
        for owner in owners:
            c = cards.get(owner)
            if c is not None:
                residu=sum(float(r[0].berat_total_kg) for r in sisa_rows if r[0].jasa_id==owner)
                curah_belum=c.curah_kg-residu
                if abs(curah_belum)>0.5:
                    baris(owner=owner,bentuk="Curah · belum dikemas",berat=curah_belum)
    for fg,_,_ in sisa_rows:
        rows.append(dict(bentuk='Sisa kemas ulang (curah)',kg=float(fg.berat_total_kg),karung=0,ukuran=0,merk='',bahan='',href=None,pindah=None,sumber=None,
            kemas=kemas_href(fg.product_sku_id,fg.rice_quality_standard_id,fg.jasa_id) if boleh_kemas else None))
    return await render_laci(request, "stok_produk_detail.html",
        layar="stok_produk_jasa" if pelanggan_id is not None else "stok_produk",
        breadcrumb_detail=k.nama, k=k, beras=svc.adalah_beras(k.jenis), pemilik=pemilik or "Pabrik",
        pelanggan_id=pelanggan_id, jasa_ids=jasa_ids, kemasan=kemasan,
        kembali=halaman, halaman_aksi=halaman, curah_titipan=curah_titipan,
        baris_kemasan=rows, detail_href=detail_href,
        sumber_stok=request.query_params.get("sumber_stok") or "",
        BOLEH_CATAT=boleh_catat, BOLEH_PINDAH=boleh_pindah,
        BOLEH_MASUKKAN_SILO=boleh_masukkan_silo,
        buka=request.query_params.get("buka") or "", nilai=request.query_params.get("nilai") or "")


@router.get("/stok-karung")
async def halaman_stok_karung(request: Request, akun=Depends(butuh_akun)):
    """Stok karung kosong (kemasan) milik PABRIK — DIPISAH dari `/stok` 7
    Oktober 2026 (keputusan pemilik: karung butuh stok terpisah per
    pemilik, menyusul "Stok Karung Jasa" di bawah).

    Blok ini dulu menempel di `/stok` (keputusan 23 September 2026); pindah
    ke halamannya sendiri sekarang karena ia butuh PEMILIK sebagai sumbu
    baru, dan sumbu itu tak ada tempatnya di halaman BAHAN — pola yang sama
    dengan kepindahan "Stok Produk" dari dalam `/stok` 26 September 2026.

    Gerbangnya SAMA dengan dulu di `/stok` (`gudang2(view)` — Gudang 2,
    Admin, Super Admin, TIDAK operator Gudang 1): karung mengemas beras
    JADI, pekerjaan Gudang 2; yang memegang kedua gudang ikut melihat
    karung PK Gudang 1, karena ia yang memesannya. Operator Gudang 2 SAJA
    (bukan admin ke atas) tak melihat baris "Gudang 1" (karung PK) — pola
    `_karung()` yang dulu hidup di `layar_stok.py`, dipertahankan persis.
    """
    from app.penggilingan.inventory import packaging as kms
    from app.peran import can_see_financials
    from app.web.layar import gudang1, gudang2

    view = getattr(request.state, "view", "tamu")
    if not gudang2(view):
        raise HTTPException(403, "Layar ini milik Gudang 2.")
    async with SessionLocal() as db:
        karung = [b for b in await kms.stok_kemasan_rinci(db, pelanggan_id=None)
                  if b["gudang"] != "Gudang 1" or gudang1(view)]
    return await render_laci(
        request, "stok_karung.html", layar="stok_karung",
        karung=karung, BOLEH_PINDAH=can_see_financials(akun.user),
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
    )


@router.get("/stok-karung-jasa")
async def halaman_stok_karung_jasa(request: Request, akun=Depends(butuh_akun)):
    """Karung kosong MILIK PESANAN JASA — per PELANGGAN, padanan
    `/stok-produk-jasa` untuk kemasan.

    Sumbernya `packaging.pindah_kepemilikan_karung`: karung tak punya
    tiket timbang, jadi SATU-SATUNYA jalan sebuah baris pembelian jadi
    milik pelanggan adalah dipindah lewat tombol "Pindah kepemilikan" di
    `/stok-karung` (pabrik) — halaman ini murni INFORMASI, tanpa tombol
    (arahnya cuma satu jalan: pabrik → pelanggan, bukan sebaliknya).

    ⚠ PER KONTAK (`pelanggan_id`), BUKAN PER PESANAN JASA — koreksi
    pemilik 7 Oktober 2026 (lihat catatan panjang di `packaging.
    pindah_kepemilikan_karung`). Beda dari `/stok-produk-jasa` (yang
    mengelompokkan `Jasa.id` per pelanggan lewat tabel `Jasa`), di sini
    `PackagingPurchase.pelanggan_id` SUDAH langsung menunjuk kontaknya —
    tak ada indirection lewat `Jasa` sama sekali.
    """
    from sqlalchemy import select

    from app.models import Pelanggan
    from app.penggilingan.inventory import packaging as kms
    from app.web.layar import gudang2

    view = getattr(request.state, "view", "tamu")
    if not gudang2(view):
        raise HTTPException(403, "Layar ini milik Gudang 2.")
    async with SessionLocal() as db:
        pelanggan_ids = await kms.pelanggan_ids_dengan_karung(db)
        from app.web.portal.scope import is_customer_read
        if is_customer_read(request):
            pelanggan_ids=[pid for pid in pelanggan_ids if pid==request.state.portal_scope.reader.pelanggan_id]
        nama_pelanggan = {pid: n for pid, n in (await db.execute(
            select(Pelanggan.id, Pelanggan.nama_pelanggan)
            .where(Pelanggan.id.in_(pelanggan_ids or [0]))
        )).all()}
        daftar = []
        for pelanggan_id in pelanggan_ids:
            karung = await kms.stok_kemasan_rinci(db, pelanggan_id=pelanggan_id)
            if not karung:
                continue
            daftar.append({
                "pemilik": nama_pelanggan.get(pelanggan_id) or f"pelanggan #{pelanggan_id}",
                "pelanggan_id": pelanggan_id,
                "karung": karung,
            })
    daftar.sort(key=lambda p: p["pemilik"])
    return await render_laci(
        request, "stok_karung_jasa.html", layar="stok_karung_jasa",
        daftar=daftar,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
    )
