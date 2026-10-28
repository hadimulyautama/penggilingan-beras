"""Layar Barang Keluar — satu transaksi, beberapa macam barang, tiga langkah.

Permintaan pemilik 28 September 2026: "kita butuh satu halaman untuk transaksi
barang keluar. 1 transaksi bisa beberapa macam barang yang keluar."

Sampai halaman ini ada, barang keluar tak punya rumah sama sekali: catatannya
tersebar di kartu Stok Produk (sebagai baris "sudah keluar" per kategori) dan di
List audit (sebagai baris mentah). Tak satu pun menjawab pertanyaan yang
sebenarnya ditanyakan orang — "truk yang tadi siang itu bawa apa saja?" — sebab
keduanya menyusun menurut BARANG, bukan menurut TRUK.

Barang Keluar memuat pekerjaan pengiriman dan riwayatnya. Verifikasi Admin
berlangsung di sini; pengiriman tidak digandakan di Menunggu Keputusan.
Transaksi selesai dan batal masuk tabel riwayat, dengan halaman detail sendiri.
"""
from __future__ import annotations

from app.web.portal.scope import is_customer_read

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.penggilingan.inventory.models import (OUT_BATAL, OUT_DIMUAT, OUT_HIDUP,
                                               OUT_PERINTAH, OUT_SELESAI)
from app.services import barang_keluar as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])

#: Urutan keadaan di layar: yang menunggu tangan dulu, riwayat belakangan.
#: Angkanya kecil = makin atas.
_URUT = {OUT_PERINTAH: 0, OUT_DIMUAT: 1, OUT_SELESAI: 2, OUT_BATAL: 3}

#: Kata yang dibaca orang untuk tiap keadaan, berikut warna kepingnya.
#: Ditulis sekali di sini — kata keadaan yang disusun ulang di templat akan
#: berbeda ejaannya dari yang dipakai layanan, dan bedanya baru ketahuan saat
#: ada yang menyaring.
KEADAAN = {
    OUT_PERINTAH: ("Menunggu dimuat", "baru"),
    OUT_DIMUAT: ("Menunggu verifikasi", "dryer"),
    OUT_SELESAI: ("Selesai", "giling"),
    OUT_BATAL: ("Dibatalkan", "bahaya"),
}


@router.get("/barang-keluar")
@router.get("/barang-keluar/{transaksi_id}")
async def halaman_barang_keluar(request: Request, akun=Depends(butuh_akun),
                                 transaksi_id: int | None = None,
                                 sebelum: int | None = None, q: str = "", status: str = "", sejak: str = ""):
    from datetime import date
    from urllib.parse import urlencode
    q = q.strip()[:200]
    status = status if status in KEADAAN else ""
    try:
        tanggal = date.fromisoformat(sejak) if sejak else None
    except ValueError:
        raise HTTPException(422, "Tanggal pencarian tidak valid.")
    from app.peran import can_see_financials
    from fastapi.responses import RedirectResponse
    from app.web.api import _is_g1_operator, _is_g2_operator

    # Periksa izin positif, bukan hanya menolak view G1: operator tanpa
    # gudang juga tidak berhak membaca daftar maupun URL detail langsung.
    boleh_perintah = can_see_financials(akun.user)
    if not is_customer_read(request) and not (boleh_perintah or await _is_g2_operator(akun.user)):
        raise HTTPException(403, "Pengiriman tersedia untuk Admin dan Operator Gudang 2. "
                            "Pilih gudang kerja melalui menu Kerja di gudang.")
    if request.query_params.get("buka") == "perintah_keluar":
        return RedirectResponse("/barang-keluar/baru", 303)
    # Super Admin melihat seluruh alur, termasuk tugas muat (28 Oktober).
    # Admin tetap memakai tampilan penerbitan/verifikasi yang sudah berlaku.
    from hmu_identitas import peran as P
    boleh_muat = (P.super_saja(akun.user.role) or not boleh_perintah
                  and (await _is_g2_operator(akun.user)
                       or await _is_g1_operator(akun.user)))

    draf_saya = []
    from app.web.stok_navigasi import pelanggan_diminta
    pid=pelanggan_diminta(request)
    from app.models import OutgoingRecord
    customer_scope={'allowed_ids':request.state.portal_scope.ids(OutgoingRecord)} if is_customer_read(request) else {}
    async with SessionLocal() as db:
        if boleh_perintah and transaksi_id is None and not pid:
            from app.web.draf_keluar import daftar_draf
            draf_saya = await daftar_draf(db, akun.user)
        if transaksi_id is not None:
            baris = await svc.daftar(db, transaksi_id=transaksi_id, batas=1, **customer_scope)
            if not baris:
                raise HTTPException(404, "Perintah barang keluar tidak ditemukan.")
            sebelum_berikut = None
            rec=baris[0][0]
            if rec.status in (OUT_SELESAI,OUT_BATAL) and request.query_params.get('rincian_perintah')!='1':
                from app.web.riwayat_kiriman import baca
                perjalanan=await baca(db,rec,scope=request.state.portal_scope if is_customer_read(request) else None,boleh_retur=boleh_perintah)
                return await render_laci(request,'riwayat_kiriman.html',layar='barang_keluar',perjalanan=perjalanan,
                    filter_query=urlencode({'q':q,'status':status,'sejak':sejak,**({'sebelum':sebelum} if sebelum else {})}))
        else:
            if status == OUT_PERINTAH and not is_customer_read(request):
                aktif = await svc.menunggu_muat(db, akun.user, pencarian=q,
                                               sejak=tanggal, pelanggan_jasa_id=pid)
            else:
                aktif = (await svc.daftar(db, status=(status,) if status else OUT_HIDUP,
                                      batas=500, pencarian=q, sejak=tanggal,pelanggan_jasa_id=pid, **customer_scope)
                     if not status or status in OUT_HIDUP else [])
            riwayat = (await svc.daftar(db, status=(status,) if status else (OUT_SELESAI, OUT_BATAL),
                                        batas=51, gabung_riwayat=not is_customer_read(request), sebelum_id=sebelum, pencarian=q, sejak=tanggal,pelanggan_jasa_id=pid, **customer_scope)
                       if not status or status not in OUT_HIDUP else [])
            sebelum_berikut = riwayat[49][0].id if len(riwayat) > 50 else None
            baris = aktif + riwayat[:50]
        if is_customer_read(request):
            ids = request.state.portal_scope.jasa_ids
            baris = [(r, items) for r, items in baris
                     if items and all(i.jasa_id in ids for i in items)]
        # Data timbang ditampilkan bersama detail perintah, tanpa kueri per kartu.
        from sqlalchemy import bindparam, text
        ids = [r.timbangan_transaksi_id for r, _ in baris if r.timbangan_transaksi_id and not (is_customer_read(request) and r.kiriman_id)]
        tiket_timbang = {}
        if ids:
            rows = (await db.execute(text("""
                SELECT id,kode,nomor_polisi,nama_sopir,status_tiket,
                       timbang1_kg,timbang2_kg,timbang1_waktu,timbang2_waktu,
                       netto_timbangan_kg,total_tara_kg,berat_barang_kg
                FROM timbangan_transaksi WHERE id IN :ids
            """).bindparams(bindparam("ids", expanding=True)),
                {"ids": ids})).mappings().all()
            tiket_timbang = {t["id"]: dict(t) for t in rows}
        dasar_perintah = {r.id: (await svc.ringkasan_muat(db, r))["dasar"]
                          for r, _ in baris if transaksi_id is not None and r.status in OUT_HIDUP}
        from sqlalchemy import select
        from app.penggilingan.inventory.models import ReturRincian
        retur_terkait = (await db.scalars(select(ReturRincian).where(
            ReturRincian.outgoing_record_id == transaksi_id).order_by(ReturRincian.id.desc()))).all() if transaksi_id and (boleh_perintah or is_customer_read(request)) else []
        from app.services.jasa import nama_pemilik_banyak
        pemilik_item = await nama_pemilik_banyak(db, {it.jasa_id for _, items in baris for it in items if it.jasa_id})
        nama = await _nama_barang(db, baris)
        nama_orang = await _nama_orang(db, baris)
        kiriman_bersama = {}
        if not is_customer_read(request):
            from app.models import OutgoingItem
            for rec, _ in baris:
                if not rec.kiriman_id or rec.kiriman_id in kiriman_bersama:
                    continue
                anggota = await svc.anggota_kiriman(db, rec)
                ids_anggota = [r.id for r in anggota]
                semua_item = list((await db.scalars(select(OutgoingItem).where(
                    OutgoingItem.outgoing_record_id.in_(ids_anggota)).order_by(OutgoingItem.id))).all())
                rincian = [(r, [it for it in semua_item if it.outgoing_record_id == r.id]) for r in anggota]
                nama_anggota = await _nama_barang(db, rincian)
                kiriman_bersama[rec.kiriman_id] = [dict(rec=r,
                    barang=[dict(nama=nama_anggota.get(it.id, '?'),
                        perintah=float(it.berat_perintah_kg or 0), dimuat=float(it.berat_kg or 0),
                        karung=it.jumlah_karung_perintah) for it in items],
                    perintah=sum(float(it.berat_perintah_kg or 0) for it in items),
                    dimuat=sum(float(it.berat_kg or 0) for it in items)) for r, items in rincian]

    kartu = []
    for rec, items in baris:
        bersama = kiriman_bersama.get(rec.kiriman_id, [])
        total_armada = (sum(p['dimuat'] for p in bersama if p['rec'].status != OUT_BATAL)
                        if bersama else sum(float(i.berat_kg or 0) for i in items))
        isi = []
        for it in items:
            perintah = float(it.berat_perintah_kg or 0)
            dimuat = float(it.berat_kg or 0)
            isi.append({
                "id": it.id,
                "nama": nama.get(it.id, "?"),
                "pemilik": pemilik_item.get(it.jasa_id, "Milik pabrik"),
                "kunci": f"{rec.id}|{it.id}|{dasar_perintah.get(rec.id, '')}",
                "perintah": perintah,
                "dimuat": dimuat,
                # Selisih DIHITUNG DI SINI, bukan di templat: Jinja yang
                # berhitung akan menghitung ulang angka yang sama di tiga
                # tempat, dan ketiganya harus sepakat.
                "kurang": (perintah - dimuat
                           if rec.status in (OUT_DIMUAT, OUT_SELESAI)
                           and perintah - dimuat > 0.5 else 0.0),
                "karung": it.jumlah_karung or it.jumlah_karung_perintah,
                "karung_perintah": it.jumlah_karung_perintah,
                "karung_dimuat": it.jumlah_karung,
                "sisa_perintah": max(perintah - dimuat, 0),
                "berkarung": it.item_type == "finished_goods",
            })
        kata, warna = KEADAAN.get(rec.status, (rec.status, "baru"))
        if rec.status == OUT_PERINTAH and (not rec.kiriman_id and svc.boleh_keluar_cepat(items)):
            kata = "Menunggu penyerahan · <200 kg"
        kartu.append({
            "riwayat_nama": ' · '.join(p['rec'].nama_pembeli or 'Pelanggan belum tercatat' for p in bersama) if bersama else rec.nama_pembeli,
            "riwayat_total": total_armada,
            "riwayat_jumlah": len(bersama) if bersama else 1,
            "riwayat_item": sum(len(p['barang']) for p in bersama) if bersama else len(isi),
            "boleh_ubah": boleh_perintah and rec.status in OUT_HIDUP,
            "rec": rec, "isi": isi, "keadaan": kata, "warna": warna,
            "kiriman_bersama": bersama, "total_armada_dimuat": total_armada,
            "cepat": (not rec.kiriman_id and svc.boleh_keluar_cepat(items)),
            "tiket_timbang": tiket_timbang.get(rec.timbangan_transaksi_id),
            # ── TOMBOL DI KARTUNYA SENDIRI ──
            #
            # Keluhan pemilik 29 September 2026: "dimana tombol verifikasi
            # untuk admin dan tombol dimuat untuk operator? harusnya kan ada di
            # kartu."
            #
            # Benar, dan kartu di Antrian tunggu maupun Menunggu keputusan
            # memang SELURUHNYA tombol — seluruh kartu adalah tautan yang
            # membuka lembar aksinya. Yang tidak: kartu di HALAMAN ini, yang
            # semula cuma memajang keadaan. Dan halaman inilah yang dibuka
            # orang untuk melihat muatan mana yang belum beres — menyuruhnya
            # berpindah ke layar lain demi menekan satu tombol adalah
            # perjalanan yang tak punya sebab.
            #
            # Tombolnya membuka LEMBAR AKSI YANG SAMA, terkunci pada transaksi
            # ini lewat `nilai` — jadi yang menekannya dari sini tak perlu
            # memilih ulang transaksi yang barusan ia baca.
            "tombol": _tombol(rec, boleh_perintah=boleh_perintah,
                              boleh_muat=boleh_muat, dasar=dasar_perintah.get(rec.id, ""),
                              cepat=(not rec.kiriman_id and svc.boleh_keluar_cepat(items))),
            "total_perintah": sum(x["perintah"] for x in isi),
            "batas_selisih": svc.ambang_selisih(total_armada),
            "total_dimuat": sum(x["dimuat"] for x in isi),
            "total_sisa": sum(x["sisa_perintah"] for x in isi),
            "jasa": rec.jasa_id is not None or any(it.jasa_id is not None for it in items),
            "selisih_timbang": (
                float(tiket_timbang[rec.timbangan_transaksi_id]["berat_barang_kg"])
                - total_armada
                if rec.timbangan_transaksi_id in tiket_timbang
                and tiket_timbang[rec.timbangan_transaksi_id]["berat_barang_kg"] is not None
                else None),
            # ── Jejak tiga langkahnya: SIAPA, bukan cuma kapan ──
            #
            # Keluhan pemilik 7 Oktober 2026: "diperintah siapa, dimuat
            # siapa, dan diverifikasi siapa harus jelas." Kolomnya
            # (`diperintah_oleh` dkk.) sudah ada sejak 28 September — tiga
            # FK terpisah, dengan komentar modelnya sendiri menegaskan
            # "tiga orang, tiga tanggung jawab" — tetapi templatnya cuma
            # menggambar `waktu`-nya; `oleh` (id mentah) ditarik ke dalam
            # gelung lalu tak pernah dicetak. Nama resminya diselesaikan DI
            # SINI (`_nama_orang`, satu kueri borongan), bukan di templat:
            # Jinja yang menebak `User` dari id mentah berarti satu kueri
            # per baris per kartu.
            "jejak": [
                (label, waktu, nama_orang.get(oleh))
                for label, waktu, oleh in (
                    ("Diperintah", rec.waktu_perintah, rec.diperintah_oleh),
                    ("Dimuat", rec.waktu_muat, rec.dimuat_oleh),
                    ("Diverifikasi", rec.waktu_verifikasi, rec.diverifikasi_oleh),
                ) if waktu
            ],
            "urut": (_URUT.get(rec.status, 9), -rec.id),
        })
    kartu.sort(key=lambda k: k["urut"])

    return await render_laci(
        request, "pengiriman.html", layar="barang_keluar", kartu=kartu,
        detail=transaksi_id is not None,
        retur_terkait=retur_terkait,
        pencarian=q, status_filter=status, sejak_filter=sejak, sebelum=sebelum,
        filter_query=urlencode({"q": q, "status": status, "sejak": sejak}),
        kartu_aktif=[k for k in kartu if k["rec"].status in OUT_HIDUP],
        riwayat=sorted((k for k in kartu if k["rec"].status not in OUT_HIDUP),
                       key=lambda k: -k["rec"].id),
        sebelum_berikut=sebelum_berikut,
        # ── Tombol "Buat perintah" hanya untuk yang boleh memerintah ──
        #
        # Permintaan pemilik 29 September 2026: tombolnya untuk Admin & Super
        # Admin. HALAMANNYA sendiri tetap terbuka untuk operator — ia perlu
        # tahu apa yang sudah dan akan keluar dari gudangnya, dan tugasnya
        # sendiri sampai lewat kartu di Antrian tunggu, bukan dari sini.
        #
        # Ini cuma menghindari menawarkan pintu yang akan ditolak; yang menjaga
        # sungguhan `wajib(can_see_financials(...))` di tiap rutenya.
        BOLEH_PERINTAH=boleh_perintah,
        draf_saya=draf_saya,
        BOLEH_MUAT=boleh_muat,
        # ── Lembarnya dibuka DI HALAMAN INI ──
        # Sampai 29 September tombolnya menunjuk `/aksi?buka=…`, jadi menekan
        # "Verifikasi" memindahkan orang ke Antrian tunggu — dan sesudah
        # menyimpan ia harus mencari jalan kembali. Pola yang sama dipakai
        # layar Stok sejak 26 September.
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        tiket=request.query_params.get("tiket") or "",
        # Dua syarat, bukan satu, sebab jangkauannya memang berbeda:
        #   · "Batalkan perintah" hanya untuk yang BELUM dimuat — yang truknya
        #     sudah berangkat tak bisa dibatalkan, barangnya sudah pergi;
        #   · "Tambah barang" berlaku sampai SEBELUM diverifikasi, termasuk
        #     yang sudah dimuat (keputusan pemilik 29 September 2026).
        # Borang yang dibuka lalu daftarnya kosong adalah ketukan yang hanya
        # bisa mengecewakan.
        ada_perintah=any(k["rec"].status == OUT_PERINTAH for k in kartu),
        ada_hidup=any(k["rec"].status in OUT_HIDUP for k in kartu),
        # Dua angka di kepala, dan keduanya PEKERJAAN — bukan jumlah kilogram.
        # Berapa ton yang keluar bulan ini ada di Laporan; yang dicari orang
        # saat membuka halaman ini berapa truk yang belum beres.
        STATUS_SARING=status, n_perintah=sum(1 for k in kartu if k["rec"].status == OUT_PERINTAH),
        n_dimuat=sum(1 for k in kartu if k["rec"].status == OUT_DIMUAT),
    )


def _tombol(rec, *, boleh_perintah: bool, boleh_muat: bool, dasar: str = "", cepat: bool = False) -> list[tuple]:
    """(buka, nilai, label, utama) untuk satu kartu — sesuai keadaan & peran.

    `utama` menandai tombol yang paling mungkin ditekan: yang satu itu digambar
    penuh, sisanya kecil. Tiga tombol seukuran membuat mata memilih lebih lama
    daripada mengerjakan.

    Yang TIDAK ditawarkan ke siapa pun: menambah & membatalkan pada transaksi
    yang sudah ditutup, dan memuat yang truknya sudah berangkat. Tombol yang
    ditekan lalu ditolak mengajari orang bahwa aplikasinya suka menolak.
    """
    n = str(rec.id)
    t: list[tuple] = []
    if rec.status == OUT_PERINTAH and cepat and boleh_perintah:
        t.append(("keluar_cepat", n, "Konfirmasi barang keluar", True))
    if rec.status == OUT_PERINTAH and boleh_muat:
        t.append(("muat_semua", n, "Muat semua sesuai perintah", not t))
        t.append(("muat_barang", n, "Catat per barang", False))
        t.append(("selesai_muat", n, "Selesai muat", False))
    if rec.status == OUT_DIMUAT and boleh_perintah:
        t.append(("verifikasi_keluar", n, "Verifikasi & tutup", True))
    if rec.status in OUT_HIDUP and boleh_perintah:
        t.append(("tambah_barang_keluar", n, "Tambah barang", not t))
        if not rec.timbangan_transaksi_id:
            t.append(("pilih_tiket_armada", n, "Pilih tiket armada", False))
        if rec.timbangan_transaksi_id:
            t.append(("lepas_tiket_armada", f"{n}|{rec.timbangan_transaksi_id}|{dasar}", "Lepas tiket armada", False))
    if rec.status == OUT_PERINTAH and boleh_perintah:
        t.append(("batal_perintah_keluar", n, "Batalkan", False))
    return t


async def _nama_barang(db, baris) -> dict[int, str]:
    """{id item: nama barang yang dibaca orang}.

    SATU kueri untuk seluruh halaman, bukan satu per baris: halaman ini memuat
    60 transaksi dan tiap transaksi beberapa barang, jadi menanyakannya per
    baris berarti ratusan kueri untuk satu halaman — kelas kesalahan yang sudah
    diukur QA pada kartu Stok Produk (1,77 detik, 500 kueri).
    """
    from sqlalchemy import select

    from app.models import GabahKeringLot, MillingProcess, Silo
    from app.penggilingan.inventory.models import (Brand, PackageSize, PackagingMaterial,
                                                   ProductSku, RiceQualityStandard)
    from app.services.stok import jenis_produk, nama_produk

    items = [it for _, isi in baris for it in isi]
    if not items:
        return {}

    sku_ids = {it.product_sku_id for it in items if it.product_sku_id}
    proc_ids = {it.milling_process_id for it in items if it.milling_process_id}
    silo_ids = {it.silo_id for it in items
                if it.item_type == "pk_g2" and it.silo_id is not None}
    gabah_ids = {it.gabah_kering_lot_id for it in items
                 if it.item_type == "gabah_langsung" and it.gabah_kering_lot_id}
    std_ids = {it.rice_quality_standard_id for it in items
               if it.rice_quality_standard_id}

    sku: dict[int, tuple] = {}
    # LEFT JOIN mempertahankan barang tanpa merek. Merek nonaktif tetap
    # dibaca karena identitas barang pada perintah lama tidak boleh hilang.
    if sku_ids:
        for sid, kategori, bahan, ukuran, merek in (await db.execute(
            select(ProductSku.id, ProductSku.kategori, PackagingMaterial.nama,
                   PackageSize.ukuran_kg, Brand.nama)
            .join(PackagingMaterial,
                  PackagingMaterial.id == ProductSku.packaging_material_id)
            .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
            .outerjoin(Brand, Brand.id == ProductSku.brand_id)
            .where(ProductSku.id.in_(sku_ids))
        )).all():
            sku[sid] = (kategori, bahan, int(ukuran), merek)

    mutu: dict[int, str] = {}
    if std_ids:
        mutu = {i: k for i, k in (await db.execute(
            select(RiceQualityStandard.id, RiceQualityStandard.kode)
            .where(RiceQualityStandard.id.in_(std_ids)))).all()}

    lot: dict[int, str] = {}
    if proc_ids:
        lot = {i: k for i, k in (await db.execute(
            select(MillingProcess.id, MillingProcess.kode_proses)
            .where(MillingProcess.id.in_(proc_ids)))).all()}

    silo: dict[int, str] = {}
    if silo_ids:
        silo = {i: n for i, n in (await db.execute(
            select(Silo.id, Silo.nama_silo).where(Silo.id.in_(silo_ids))
        )).all()}

    gabah_lot: dict[int, str] = {}
    if gabah_ids:
        gabah_lot = {i: k for i, k in (await db.execute(
            select(GabahKeringLot.id, GabahKeringLot.kode_lot)
            .where(GabahKeringLot.id.in_(gabah_ids))
        )).all()}

    keluar: dict[int, str] = {}
    for it in items:
        if it.item_type == "pk_langsung":
            kode = lot.get(it.milling_process_id)
            keluar[it.id] = f"PK {kode}" if kode else "PK (lot asal tidak ditemukan)"
        elif it.item_type == "pk_g2":
            tempat = silo.get(it.silo_id) if it.silo_id is not None else "tumpukan"
            keluar[it.id] = f"PK Gudang 2 · {tempat or 'silo tidak ditemukan'}"
        elif it.item_type == "gabah_langsung":
            kode = gabah_lot.get(it.gabah_kering_lot_id)
            keluar[it.id] = f"Gabah kering · {kode}" if kode else "Gabah kering (lot asal tidak ditemukan)"
        elif it.item_type == "byproduct_curah":
            keluar[it.id] = f"{nama_produk(it.jenis_byproduct or '')} (curah)"
        else:
            k = sku.get(it.product_sku_id)
            if k is None:
                keluar[it.id] = "Barang tidak dikenali (data produk tidak ditemukan)"
                continue
            kategori, bahan, ukuran, merek = k
            j = jenis_produk(kategori, mutu.get(it.rice_quality_standard_id))
            # Spasi TAK-PUTUS antara angka dan satuannya: nama barang panjang
            # ("Beras Medium · Pulenesia · Karung biasa 50 kg") melipat di 375px, dan tanpa
            # ini yang turun ke baris berikutnya cuma kata "kg" — satu suku
            # kata menggantung sendirian, rupa yang sudah dikeluhkan pemilik di
            # kartu Stok Produk.
            keluar[it.id] = f"{nama_produk(j)} · {merek or 'Tanpa merek'} · {bahan} {ukuran}\u00a0kg"
    return keluar


async def _nama_orang(db, baris) -> dict[int, str]:
    """{id user: nama} untuk ketiga langkah (diperintah/dimuat/diverifikasi).

    SATU kueri untuk seluruh halaman — pola sama `_nama_barang` di atas,
    alasan yang sama persis: 60 transaksi x tiga kemungkinan id per
    transaksi berarti sampai 180 kueri kalau ditanyakan satu per baris.
    """
    from sqlalchemy import select

    from app.models import User

    ids = {
        oleh
        for rec, _ in baris
        for oleh in (rec.diperintah_oleh, rec.dimuat_oleh, rec.diverifikasi_oleh)
        if oleh
    }
    if not ids:
        return {}
    return {i: n for i, n in (await db.execute(
        select(User.id, User.nama).where(User.id.in_(ids))
    )).all()}
