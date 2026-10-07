"""Layar Barang Keluar — satu transaksi, beberapa macam barang, tiga langkah.

Permintaan pemilik 28 September 2026: "kita butuh satu halaman untuk transaksi
barang keluar. 1 transaksi bisa beberapa macam barang yang keluar."

Sampai halaman ini ada, barang keluar tak punya rumah sama sekali: catatannya
tersebar di kartu Stok Produk (sebagai baris "sudah keluar" per kategori) dan di
List audit (sebagai baris mentah). Tak satu pun menjawab pertanyaan yang
sebenarnya ditanyakan orang — "truk yang tadi siang itu bawa apa saja?" — sebab
keduanya menyusun menurut BARANG, bukan menurut TRUK.

PEMBAGIANNYA dengan layar yang sudah ada, dan ini yang menentukan isinya:

    Antrian tunggu     pekerjaan yang MENUNGGU tangan — kartu muat operator
    Menunggu keputusan yang menunggu keputusan Admin — kartu verifikasi
    Barang keluar      RIWAYAT & keadaan seluruh transaksi, termasuk yang sudah
                       tutup. Ia daftar, bukan antrean.

Karena itu halaman ini TIDAK berlencana: lencana menagih pekerjaan, dan
pekerjaan barang keluar sudah ditagih dua layar di atas. Lencana ketiga atas
pekerjaan yang sama membuat ketiganya berhenti dipercaya.

Yang belum selesai tetap berdiri PALING ATAS — bukan diurut waktu murni: yang
membuka halaman ini di tengah hari mencari muatan yang sedang berjalan, dan
riwayat kemarin mendorongnya ke bawah layar.
"""
from __future__ import annotations

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
async def halaman_barang_keluar(request: Request, akun=Depends(butuh_akun)):
    from app.peran import can_see_financials
    from app.web.layar import SELEPAN

    view = getattr(request.state, "view", "tamu")
    # Operator selepan tak punya urusan di sini — barang jadi berdiri di Gudang
    # 2, dan PK yang dijual keluar diperintah Admin. Pintunya sudah tak
    # ditawarkan lewat `PINTU_MATI`, tetapi pintu yang disembunyikan bukan
    # penjagaan: alamatnya bisa diketik.
    if view == SELEPAN and not can_see_financials(akun.user):
        raise HTTPException(403, "Layar ini milik Gudang 2 & Admin.")

    from app.web.api import _is_g1_operator, _is_g2_operator

    boleh_perintah = can_see_financials(akun.user)
    # ── Tombol MUAT hanya untuk yang bukan Admin, dan ini keputusan sadar ──
    #
    # `_is_g2_operator` sengaja menjawab True untuk Admin ("Admin selalu
    # boleh"), dan rutenya memang menerimanya — itu jalan darurat yang tak saya
    # tutup: sore hari tanpa operator, muatan tetap harus bisa dicatat.
    #
    # Tetapi MENAWARKANNYA di halaman ini hal lain. Seluruh sebab rantai ini
    # ada adalah pemisahan tangan: yang memerintah bukan yang memuat, dan yang
    # memuat bukan yang memverifikasi. Admin yang disodori tombol "Muat semua"
    # tepat di sebelah tombol "Verifikasi" akan menekan keduanya, dan
    # verifikasinya jadi verifikasi atas pekerjaannya sendiri — rantainya utuh
    # di basis data, kosong artinya.
    #
    # Jadi: rutenya tetap terbuka, tombolnya tidak ditawarkan.
    boleh_muat = (not boleh_perintah
                  and (await _is_g2_operator(akun.user)
                       or await _is_g1_operator(akun.user)))

    async with SessionLocal() as db:
        baris = await svc.daftar(db, batas=60)
        nama = await _nama_barang(db, baris)
        nama_orang = await _nama_orang(db, baris)

    kartu = []
    for rec, items in baris:
        isi = []
        for it in items:
            perintah = float(it.berat_perintah_kg or 0)
            dimuat = float(it.berat_kg or 0)
            isi.append({
                "nama": nama.get(it.id, "?"),
                "perintah": perintah,
                "dimuat": dimuat,
                # Selisih DIHITUNG DI SINI, bukan di templat: Jinja yang
                # berhitung akan menghitung ulang angka yang sama di tiga
                # tempat, dan ketiganya harus sepakat.
                "kurang": (perintah - dimuat
                           if rec.status in (OUT_DIMUAT, OUT_SELESAI)
                           and perintah - dimuat > 0.5 else 0.0),
                "karung": it.jumlah_karung or it.jumlah_karung_perintah,
                "berkarung": it.item_type == "finished_goods",
            })
        kata, warna = KEADAAN.get(rec.status, (rec.status, "baru"))
        kartu.append({
            "rec": rec, "isi": isi, "keadaan": kata, "warna": warna,
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
                              boleh_muat=boleh_muat),
            "total_perintah": sum(x["perintah"] for x in isi),
            "total_dimuat": sum(x["dimuat"] for x in isi),
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
        request, "barang_keluar.html", layar="barang_keluar", kartu=kartu,
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
        BOLEH_MUAT=boleh_muat,
        # ── Lembarnya dibuka DI HALAMAN INI ──
        # Sampai 29 September tombolnya menunjuk `/aksi?buka=…`, jadi menekan
        # "Verifikasi" memindahkan orang ke Antrian tunggu — dan sesudah
        # menyimpan ia harus mencari jalan kembali. Pola yang sama dipakai
        # layar Stok sejak 26 September.
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
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
        n_perintah=sum(1 for k in kartu if k["rec"].status == OUT_PERINTAH),
        n_dimuat=sum(1 for k in kartu if k["rec"].status == OUT_DIMUAT),
    )


def _tombol(rec, *, boleh_perintah: bool, boleh_muat: bool) -> list[tuple]:
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
    if rec.status == OUT_PERINTAH and boleh_muat:
        t.append(("muat_semua", n, "Muat semua sesuai perintah", True))
        t.append(("muat_barang", "", "Catat per barang", False))
        t.append(("selesai_muat", n, "Selesai muat", False))
    if rec.status == OUT_DIMUAT and boleh_perintah:
        t.append(("verifikasi_keluar", n, "Verifikasi & tutup", True))
    if rec.status in OUT_HIDUP and boleh_perintah:
        t.append(("tambah_barang_keluar", n, "Tambah barang", not t))
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

    from app.models import MillingProcess
    from app.penggilingan.inventory.models import (PackageSize, PackagingMaterial,
                                                   ProductSku, RiceQualityStandard)
    from app.services.stok import jenis_produk, nama_produk

    items = [it for _, isi in baris for it in isi]
    if not items:
        return {}

    sku_ids = {it.product_sku_id for it in items if it.product_sku_id}
    proc_ids = {it.milling_process_id for it in items if it.milling_process_id}
    std_ids = {it.rice_quality_standard_id for it in items
               if it.rice_quality_standard_id}

    sku: dict[int, tuple] = {}
    if sku_ids:
        for sid, kategori, bahan, ukuran in (await db.execute(
            select(ProductSku.id, ProductSku.kategori, PackagingMaterial.nama,
                   PackageSize.ukuran_kg)
            .join(PackagingMaterial,
                  PackagingMaterial.id == ProductSku.packaging_material_id)
            .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
            .where(ProductSku.id.in_(sku_ids))
        )).all():
            sku[sid] = (kategori, bahan, int(ukuran))

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

    keluar: dict[int, str] = {}
    for it in items:
        if it.item_type == "pk_langsung":
            keluar[it.id] = f"PK {lot.get(it.milling_process_id, '?')}"
        elif it.item_type == "byproduct_curah":
            keluar[it.id] = f"{nama_produk(it.jenis_byproduct or '')} (curah)"
        else:
            k = sku.get(it.product_sku_id)
            if k is None:
                keluar[it.id] = "?"
                continue
            kategori, bahan, ukuran = k
            j = jenis_produk(kategori, mutu.get(it.rice_quality_standard_id))
            # Spasi TAK-PUTUS antara angka dan satuannya: nama barang panjang
            # ("Beras Medium · Karung biasa 50 kg") melipat di 375px, dan tanpa
            # ini yang turun ke baris berikutnya cuma kata "kg" — satu suku
            # kata menggantung sendirian, rupa yang sudah dikeluhkan pemilik di
            # kartu Stok Produk.
            keluar[it.id] = f"{nama_produk(j)} · {bahan} {ukuran}\u00a0kg"
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
