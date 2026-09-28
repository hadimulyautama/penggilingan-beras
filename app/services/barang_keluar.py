"""Barang keluar berperintah: Admin memerintah · operator memuat · Admin verifikasi.

Permintaan pemilik 28 September 2026: "admin yang bisa membuat perintah barang
keluar, operator menerima tugas. lalu kembali diverifikasi oleh admin saat
selesai."

TIGA LANGKAH, bukan empat. Rantai permintaan PK punya empat karena yang meminta
dan yang menyetujui adalah dua orang; di sini Admin sendiri yang memerintah,
jadi langkah "setujui" tak punya isi.

    permintaan PK          barang keluar
    ─────────────────      ──────────────────────
    Gudang 2 MINTA         Admin MEMERINTAH
    Admin ACC + tujuan     (tak ada — Admin sendiri yang memerintah)
    Gudang 1 MUAT          Operator MUAT
    Admin TUTUP            Admin VERIFIKASI

⭐ BARANGNYA BERPINDAH SAAT DIMUAT — bukan saat diperintah, bukan saat
diverifikasi. Sama dengan keputusan pemilik 25 September untuk PK, dan sengaja
tidak berbeda: dua alur serupa dengan titik-pindah berbeda membuat orang yang
mengerjakan keduanya salah menebak, dan yang ditebak adalah angka stok.

Teknisnya sederhana dan itu yang membuatnya aman: stok barang jadi DIHITUNG
dari `outgoing_items.berat_kg` (masuk dikurangi keluar), bukan disimpan. Maka
baris perintah lahir dengan `berat_kg = 0` dan tak mengurangi apa pun; langkah
muat mengisinya dengan yang benar-benar naik ke truk. Tak ada saklar "sudah
dipotong belum" yang bisa salah.

PELAJARAN RANTAI PK YANG DIPAKAI UTUH DI SINI:
  · dua angka berdampingan — yang DIPERINTAHKAN dan yang DIMUAT. Yang kedua
    tak pernah menimpa yang pertama;
  · tiap langkah BERKABAR. Rantai tanpa kabar sudah pernah jadi keluhan
    pemilik, dan yang mengeluh benar: kartu hanya terbaca oleh orang yang
    kebetulan sedang membuka layar itu;
  · tiap penolakan MENYEBUT ANGKANYA. Yang ditolak tanpa angka akan mencoba
    lagi dengan tebakan;
  · barisnya DIKUNCI sebelum dibaca. Dua operator di dua HP adalah keadaan
    sehari-hari, bukan kasus tepi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hmu_identitas.peran import G1, G2

from app.database import input_time, now_local
from app.models import OutgoingItem, OutgoingRecord
from app.penggilingan.inventory.models import (OUT_BATAL, OUT_DIMUAT, OUT_PERINTAH,
                                               OUT_SELESAI)
from app.services.activity_log import log_activity
from app.services.codegen import next_outgoing_code

#: Satu `tipe` untuk seluruh rantai, supaya eskalasi dan pembacanya nanti bisa
#: mengambilnya dengan satu syarat.
TIPE_KABAR = "barang_keluar"

#: Gudang ASAL tiap jenis barang. Menentukan layar operator mana yang menerima
#: tugasnya — dihitung aplikasi, BUKAN dipilih Admin (usul QA, dan benar):
#: perintah yang mendarat di layar yang salah akan berdiri di sana sampai
#: seseorang menelepon.
GUDANG_ITEM = {"finished_goods": G2, "byproduct_curah": G2, "pk_langsung": G1}


class BarangKeluarError(Exception):
    """Kesalahan dengan pesan siap-tampil (args[0])."""


@dataclass(frozen=True)
class BarisPerintah:
    """Satu macam barang di dalam satu perintah.

    `jumlah_karung` untuk yang berkarung, `berat_kg` untuk yang curah. Salah
    satunya saja yang diisi; yang lain diturunkan — ukuran karung tahu beratnya,
    dan curah tak punya karung.
    """

    tipe: str
    sku_id: int | None = None
    std_id: int | None = None
    jenis: str | None = None                 # byproduct_curah
    milling_process_id: int | None = None    # pk_langsung
    jumlah_karung: int | None = None
    berat_kg: float | None = None


@dataclass
class HasilPerintah:
    rec: OutgoingRecord
    baris: list[OutgoingItem] = field(default_factory=list)


def _kg(n) -> str:
    return f"{float(n or 0):,.0f}".replace(",", ".")


# ────────────────────────── Stok yang benar-benar bisa keluar ──────────────

async def _sudah_dipesan(db: AsyncSession, *, sku_id=None, std_id=None,
                         jenis=None, proc_id=None) -> float:
    """Berapa kg barang ini sudah DIPERINTAHKAN keluar tetapi belum dimuat.

    Tanpa ini, Admin bisa menerbitkan dua perintah atas 2.000 kg yang sama:
    keduanya lolos pemeriksaan stok, dan yang kedua baru gagal berjam-jam
    kemudian — di tangan operator, di depan truk yang sudah datang. Yang
    ditolak sebaiknya Admin di mejanya, bukan operator di halaman.
    """
    # SISA pesanannya, bukan seluruh perintahnya: baris yang sudah dimuat
    # sebagian sudah mengurangi stok lewat `berat_kg`, dan menghitung perintah
    # penuhnya lagi berarti barang yang sama dikurangkan dua kali — stok
    # terbaca lebih kecil daripada yang berdiri di gudang, lalu perintah
    # berikutnya ditolak tanpa sebab yang bisa dilihat siapa pun.
    #
    # `case`, BUKAN `func.greatest`: GREATEST tidak ada di SQLite, dan sebagian
    # besar uji berjalan di sana. Ia akan lolos di Postgres lalu mati di suite
    # yang paling sering dijalankan orang — kelas kesalahan yang persis sama
    # dengan indeks yang lupa `sqlite_where`.
    _sisa = (func.coalesce(OutgoingItem.berat_perintah_kg, 0)
             - func.coalesce(OutgoingItem.berat_kg, 0))
    sisa_pesan = case((_sisa < 0, 0), else_=_sisa)
    q = (select(func.coalesce(func.sum(sisa_pesan), 0))
         .join(OutgoingRecord,
               OutgoingRecord.id == OutgoingItem.outgoing_record_id)
         .where(OutgoingRecord.status == OUT_PERINTAH))
    if sku_id is not None:
        q = q.where(OutgoingItem.product_sku_id == sku_id)
        q = (q.where(OutgoingItem.rice_quality_standard_id.is_(None))
             if std_id is None
             else q.where(OutgoingItem.rice_quality_standard_id == std_id))
    elif jenis is not None:
        q = q.where(OutgoingItem.jenis_byproduct == jenis)
    elif proc_id is not None:
        q = q.where(OutgoingItem.milling_process_id == proc_id)
    return float((await db.execute(q)).scalar_one())


async def tersedia(db: AsyncSession, b: BarisPerintah,
                   *, abaikan_pesanan: bool = False) -> tuple[float, str]:
    """(kg yang benar-benar bisa keluar, nama barangnya).

    `abaikan_pesanan` dipakai langkah MUAT: barisnya sendiri sudah termasuk
    "dipesan", jadi menguranginya lagi akan menolak muatan yang justru sedang
    dikerjakan sesuai perintahnya.
    """
    from app.penggilingan.inventory.finished_goods import (hitung_stok_bekatul,
                                                           hitung_stok_finished_goods)
    from app.services.stok import nama_produk
    from app.services.transfer import pending_transfer_kg

    if b.tipe == "finished_goods":
        stok = await hitung_stok_finished_goods(db, b.sku_id, b.std_id)
        ada, nama = float(stok["kg"]), await _nama_sku(db, b.sku_id, b.std_id)
        dipesan = 0.0 if abaikan_pesanan else await _sudah_dipesan(
            db, sku_id=b.sku_id, std_id=b.std_id)
    elif b.tipe == "byproduct_curah":
        ada, nama = float(await hitung_stok_bekatul(db)), nama_produk(b.jenis or "")
        dipesan = 0.0 if abaikan_pesanan else await _sudah_dipesan(db, jenis=b.jenis)
    elif b.tipe == "pk_langsung":
        from app.models import MillingProcess

        p = await db.get(MillingProcess, b.milling_process_id)
        ada = float(await pending_transfer_kg(db, b.milling_process_id))
        nama = f"PK {p.kode_proses}" if p else "PK"
        dipesan = 0.0 if abaikan_pesanan else await _sudah_dipesan(
            db, proc_id=b.milling_process_id)
    else:
        raise BarangKeluarError(f"Jenis barang tak dikenal: {b.tipe}.")
    return ada - dipesan, nama


async def _nama_sku(db: AsyncSession, sku_id: int | None, std_id: int | None) -> str:
    from app.penggilingan.inventory.models import (PackageSize, PackagingMaterial,
                                                   ProductSku, RiceQualityStandard)
    from app.services.stok import jenis_produk, nama_produk

    baris = (await db.execute(
        select(ProductSku.kategori, RiceQualityStandard.kode,
               PackagingMaterial.nama, PackageSize.ukuran_kg)
        .join(PackagingMaterial,
              PackagingMaterial.id == ProductSku.packaging_material_id)
        .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
        .join(RiceQualityStandard, RiceQualityStandard.id == std_id, isouter=True)
        .where(ProductSku.id == sku_id)
    )).first()
    if baris is None:
        return f"SKU #{sku_id}"
    kategori, mutu, bahan, ukuran = baris
    return f"{nama_produk(jenis_produk(kategori, mutu))} · {bahan} {int(ukuran)} kg"


async def _berat_baris(db: AsyncSession, b: BarisPerintah) -> tuple[float, int | None]:
    """(kg, karung) sebuah baris — satu aturan untuk perintah maupun muatan.

    Yang berkarung dihitung `karung × ukuran`; yang curah memakai kg apa adanya;
    PK langsung dijual per kg dan karungnya diturunkan (CEIL ÷ 50), sama seperti
    jalur lamanya — mengubahnya di sini akan membuat laporan lama dan baru
    menyebut jumlah karung berbeda untuk muatan yang sama.
    """
    if b.tipe == "finished_goods":
        if not b.jumlah_karung:
            raise BarangKeluarError("Sebutkan jumlah karungnya.")
        from app.penggilingan.inventory.models import PackageSize, ProductSku

        ukuran = (await db.execute(
            select(PackageSize.ukuran_kg)
            .join(ProductSku, ProductSku.package_size_id == PackageSize.id)
            .where(ProductSku.id == b.sku_id))).scalar_one_or_none()
        if ukuran is None:
            raise BarangKeluarError("Kemasan barang itu tak ditemukan.")
        return float(b.jumlah_karung) * float(ukuran), int(b.jumlah_karung)
    if not b.berat_kg:
        raise BarangKeluarError("Sebutkan beratnya (kg).")
    if b.tipe == "pk_langsung":
        return float(b.berat_kg), ceil(float(b.berat_kg) / 50)
    return float(b.berat_kg), None


# ────────────────────────────── Kabar ──────────────────────────────

async def _kabar(db: AsyncSession, rec: OutgoingRecord, *, pesan: str,
                 untuk: str, prioritas: str = "kuning") -> None:
    """Satu langkah rantai mengabarkan dirinya.

    Alasannya sama dengan rantai permintaan PK, dan sudah dibayar sekali:
    kartu hanya terbaca oleh orang yang kebetulan sedang membuka layar itu.
    Perintah yang terbit pukul tujuh pagi dan baru dilihat pukul sebelas
    adalah truk yang menunggu empat jam di halaman.
    """
    from app.services.notification import create_notification

    await create_notification(
        db, tipe=TIPE_KABAR, pesan=pesan, target_role=untuk,
        prioritas=prioritas, table_name="outgoing_records", record_id=rec.id)


async def _jejak(db: AsyncSession, rec: OutgoingRecord, *, langkah: str,
                 oleh, ringkas: str) -> None:
    """Satu baris audit per langkah — dan ini soal PENYEGARAN, bukan audit.

    Penanda `/api/keadaan` yang menerbitkan pil "ada perubahan baru" adalah
    `max(activity_logs.id)`. Langkah yang tak menulis baris audit tak terlihat
    olehnya — bukan telat, tak pernah datang. Rantai permintaan PK menderita
    persis itu sampai 28 September 2026; rantai ini lahir sudah membawanya.
    """
    await log_activity(
        db, table_name="outgoing_records", record_id=rec.id, action="UPDATE",
        aksi=f"barang_keluar_{langkah}", changed_by=getattr(oleh, "id", None),
        new_value=ringkas[:200])


# ─────────────────────── LANGKAH 1 · Admin memerintah ───────────────────────

async def buat_perintah(
    db: AsyncSession, *, user, baris: list[BarisPerintah],
    nama_pembeli: str | None = None, metode: str | None = None,
    no_polisi: str | None = None, nama_ekspedisi: str | None = None,
    catatan: str | None = None, tanggal=None, jam=None,
) -> HasilPerintah:
    """Admin menerbitkan satu perintah muat. STOK BELUM BERKURANG.

    SATU TRUK SATU PERINTAH (keputusan pemilik): dua truk berarti dua perintah.
    Surat jalannya memang per truk, dan tiket timbangnya satu per truk — satu
    perintah yang dimuat dua truk akan membuat tautan tiketnya satu-ke-banyak,
    dan "sudah selesai belum?" jadi pertanyaan yang tak punya jawaban tunggal.

    Tiap baris diperiksa terhadap stok yang BENAR-BENAR bisa keluar — stok
    sekarang dikurangi yang sudah diperintahkan orang lain dan belum dimuat.
    Ditolak dengan menyebut angkanya.
    """
    if not baris:
        raise BarangKeluarError(
            "Perintah tanpa satu pun barang tak bisa dikerjakan siapa pun.")
    if not (nama_pembeli or "").strip():
        raise BarangKeluarError(
            "Tulis pembelinya — surat jalan tanpa nama tak bisa diantar, dan "
            "yang memuat perlu tahu muatan ini milik siapa.")

    dihitung: list[tuple[BarisPerintah, float, int | None]] = []
    for b in baris:
        berat, karung = await _berat_baris(db, b)
        if berat <= 0:
            raise BarangKeluarError("Jumlah barang harus lebih dari nol.")
        ada, nama = await tersedia(db, b)
        if berat > ada + 0.5:
            raise BarangKeluarError(
                f"{nama} tinggal {_kg(ada)} kg yang bisa keluar — tak bisa "
                f"memerintahkan {_kg(berat)} kg. (Yang sudah diperintahkan "
                "keluar tetapi belum dimuat ikut dikurangkan.)")
        dihitung.append((b, berat, karung))

    now = input_time(tanggal, jam)
    rec = OutgoingRecord(
        kode=await next_outgoing_code(db, now.date()),
        nama_pembeli=nama_pembeli.strip(), metode=metode, no_polisi=no_polisi,
        nama_ekspedisi=nama_ekspedisi, tanggal=now.date(), waktu=now,
        input_by=user.id, catatan_perintah=(catatan or "").strip()[:300] or None,
        status=OUT_PERINTAH, diperintah_oleh=user.id, waktu_perintah=now,
    )
    db.add(rec)
    await db.flush()

    items: list[OutgoingItem] = []
    for b, berat, karung in dihitung:
        it = OutgoingItem(
            outgoing_record_id=rec.id, item_type=b.tipe,
            product_sku_id=b.sku_id, rice_quality_standard_id=b.std_id,
            jenis_byproduct=b.jenis, milling_process_id=b.milling_process_id,
            berat_perintah_kg=berat, jumlah_karung_perintah=karung,
            # Nol, bukan `berat`: stok dihitung dari kolom ini, dan perintah
            # yang belum dimuat tak boleh mengurangi satu kilogram pun.
            berat_kg=0, jumlah_karung=None)
        db.add(it)
        items.append(it)
    await db.flush()

    macam = len(items)
    await _kabar(db, rec, untuk="operator",
                 pesan=f"🟡 Perintah muat {rec.kode} — {macam} macam barang "
                       f"untuk {rec.nama_pembeli}"
                       + (f", {rec.no_polisi}" if rec.no_polisi else "")
                       + ". Kartunya di Antrian tunggu.")
    await _jejak(db, rec, langkah="perintah", oleh=user,
                 ringkas=f"{rec.kode} · {macam} macam · {rec.nama_pembeli}")
    await db.commit()
    await db.refresh(rec)
    return HasilPerintah(rec=rec, baris=items)


async def tambah_baris(db: AsyncSession, *, user, rec_id: int,
                       baris: BarisPerintah) -> HasilPerintah:
    """Satu macam barang lagi ke perintah yang BELUM dimuat.

    ⭐ INI YANG MEMBUAT "satu transaksi banyak barang" jadi nyata. Skemanya
    memang sudah satu-ke-banyak sejak awal; yang tak pernah memakainya adalah
    layarnya, dan akibatnya satu truk berisi beras + broken + menir melahirkan
    tiga kode OUT- yang berbeda — tiga baris di kartu Stok Produk, dan tiga
    pencocokan untuk satu tiket timbang.

    Hanya selama masih `perintah`: menambah barang ke muatan yang truknya sudah
    berangkat berarti mengarang barang yang tak pernah naik.
    """
    rec = await _kunci(db, rec_id, keadaan=OUT_PERINTAH)
    berat, karung = await _berat_baris(db, baris)
    if berat <= 0:
        raise BarangKeluarError("Jumlah barang harus lebih dari nol.")
    ada, nama = await tersedia(db, baris)
    if berat > ada + 0.5:
        raise BarangKeluarError(
            f"{nama} tinggal {_kg(ada)} kg yang bisa keluar — tak bisa "
            f"menambahkan {_kg(berat)} kg. (Yang sudah diperintahkan keluar "
            "tetapi belum dimuat ikut dikurangkan.)")
    db.add(OutgoingItem(
        outgoing_record_id=rec.id, item_type=baris.tipe,
        product_sku_id=baris.sku_id, rice_quality_standard_id=baris.std_id,
        jenis_byproduct=baris.jenis, milling_process_id=baris.milling_process_id,
        berat_perintah_kg=berat, jumlah_karung_perintah=karung,
        berat_kg=0, jumlah_karung=None))
    await _jejak(db, rec, langkah="tambah", oleh=user,
                 ringkas=f"{rec.kode} + {nama} {_kg(berat)} kg")
    await db.commit()
    items = list((await db.execute(
        select(OutgoingItem).where(OutgoingItem.outgoing_record_id == rec.id)
    )).scalars().all())
    return HasilPerintah(rec=rec, baris=items)


# ─────────────────────── LANGKAH 2 · Operator memuat ───────────────────────

async def _kunci(db: AsyncSession, rec_id: int, *, keadaan: str) -> OutgoingRecord:
    """Ambil barisnya TERKUNCI, lalu pastikan keadaannya masih yang diharap.

    `FOR UPDATE` membuat penekan kedua MENUNGGU yang pertama commit, lalu
    membaca ulang keadaannya — kini sudah berubah — dan ditolak dengan kalimat
    yang menyebut siapa yang mendahuluinya. Memeriksa lebih dulu tanpa kunci
    membuat dua-duanya lolos: dua operator, dua HP, satu detik.
    """
    rec = (await db.execute(
        select(OutgoingRecord).where(OutgoingRecord.id == rec_id).with_for_update()
    )).scalars().first()
    if rec is None:
        raise BarangKeluarError("Perintah itu sudah tidak ada.")
    if rec.status != keadaan:
        raise BarangKeluarError(await _kalimat_keadaan(db, rec, keadaan))
    return rec


async def _kalimat_keadaan(db: AsyncSession, rec: OutgoingRecord,
                           diharap: str) -> str:
    """Kenapa langkahnya ditolak, dengan menyebut SIAPA yang mendahului.

    "Statusnya bukan `perintah`" tak menolong siapa pun yang sedang berdiri di
    samping truk. Yang menolong adalah nama orangnya, sebab langkah berikutnya
    memang menanyainya.
    """
    from app.models import User

    async def nama(uid):
        u = await db.get(User, uid) if uid else None
        return u.nama if u else "orang lain"

    if rec.status == OUT_DIMUAT and diharap == OUT_PERINTAH:
        return (f"{rec.kode} sudah dimuat {await nama(rec.dimuat_oleh)} — "
                "tinggal menunggu verifikasi Admin.")
    if rec.status == OUT_SELESAI:
        return (f"{rec.kode} sudah ditutup "
                f"{await nama(rec.diverifikasi_oleh)}.")
    if rec.status == OUT_BATAL:
        return (f"{rec.kode} sudah dibatalkan"
                + (f" — {rec.sebab_batal}" if rec.sebab_batal else "") + ".")
    if rec.status == OUT_PERINTAH and diharap == OUT_DIMUAT:
        return f"{rec.kode} belum dimuat siapa pun."
    return f"{rec.kode} sudah tidak pada langkah itu lagi."


async def catat_muatan(db: AsyncSession, *, user, item_id: int,
                       jumlah_karung: int | None = None,
                       berat_kg: float | None = None) -> tuple[OutgoingRecord, str]:
    """Operator mencatat SATU baris yang benar-benar naik ke truk.

    ⭐ DI SINILAH STOK BERKURANG, dan itu memang saat karungnya naik — bukan
    saat diperintah, bukan saat diverifikasi. Sama dengan keputusan pemilik 25
    September untuk PK; dua alur serupa dengan titik-pindah berbeda membuat
    orang yang mengerjakan keduanya salah menebak, dan yang ditebak angka stok.

    Per BARIS, bukan sekaligus seluruh perintah, sebab muatan sungguhan tak
    selesai serentak: karung Premium naik duluan, bekatulnya menyusul setengah
    jam kemudian. Operator yang harus menunggu seluruh truk penuh sebelum boleh
    mencatat apa pun akan mencatatnya dari ingatan.

    Recordnya TETAP berstatus `perintah` sampai operator menyatakan selesai —
    lihat `selesai_muat`.
    """
    it = await db.get(OutgoingItem, item_id)
    if it is None:
        raise BarangKeluarError("Baris perintah itu sudah tidak ada.")
    rec = await _kunci(db, it.outgoing_record_id, keadaan=OUT_PERINTAH)
    b = BarisPerintah(
        tipe=it.item_type, sku_id=it.product_sku_id,
        std_id=it.rice_quality_standard_id, jenis=it.jenis_byproduct,
        milling_process_id=it.milling_process_id,
        jumlah_karung=jumlah_karung, berat_kg=berat_kg)
    berat, karung = await _berat_baris(db, b)
    perintah = float(it.berat_perintah_kg or 0)
    if berat > perintah + 0.5:
        _, nama = await tersedia(db, b, abaikan_pesanan=True)
        raise BarangKeluarError(
            f"{nama} diperintahkan {_kg(perintah)} kg — tak bisa memuat "
            f"{_kg(berat)} kg. Muatan yang melebihi perintah berarti barang "
            "keluar tanpa yang memerintahkan; mintakan perintah baru ke Admin.")
    # ── Diperiksa ULANG terhadap stok, sebab stok berubah di antaranya ──
    # Perintah terbit pagi, muatnya sore, dan di antaranya ada penjualan lain.
    # Yang diperiksa di langkah 1 adalah keadaan pagi itu.
    sudah = float(it.berat_kg or 0)
    ada, nama = await tersedia(db, b, abaikan_pesanan=True)
    if berat - sudah > ada + 0.5:
        raise BarangKeluarError(
            f"{nama} tinggal {_kg(ada)} kg sekarang — tak cukup untuk "
            f"{_kg(berat - sudah)} kg lagi. Stoknya berubah sejak perintah "
            "dibuat; muat yang ada dulu, atau mintakan koreksi ke Admin.")
    it.berat_kg = berat
    it.jumlah_karung = karung
    await _jejak(db, rec, langkah="muat_baris", oleh=user,
                 ringkas=f"{rec.kode} · {nama} {_kg(berat)} kg")
    await db.commit()
    await db.refresh(rec)
    kurang = perintah - berat
    return rec, (f"✓ {nama} {_kg(berat)} kg dicatat"
                 + (f" — kurang {_kg(kurang)} kg dari perintah."
                    if kurang > 0.5 else "."))


async def muat_semua(db: AsyncSession, *, user, rec_id: int,
                     tanggal=None, jam=None) -> HasilPerintah:
    """Seluruh baris dimuat PERSIS seperti diperintahkan — satu ketukan.

    Ini keadaan yang paling sering, dan borang yang menuntut operator mengetik
    ulang angka yang sudah tertulis di kartunya akan diketik asal-asalan. Yang
    berselisih dicatat per baris lewat `catat_muatan` lebih dulu; sisanya ikut
    ketukan ini.
    """
    rec = await _kunci(db, rec_id, keadaan=OUT_PERINTAH)
    items = list((await db.execute(
        select(OutgoingItem).where(OutgoingItem.outgoing_record_id == rec.id)
    )).scalars().all())
    for it in items:
        if float(it.berat_kg or 0) > 0.5:
            continue                       # sudah dicatat sendiri, jangan ditimpa
        b = BarisPerintah(
            tipe=it.item_type, sku_id=it.product_sku_id,
            std_id=it.rice_quality_standard_id, jenis=it.jenis_byproduct,
            milling_process_id=it.milling_process_id,
            jumlah_karung=it.jumlah_karung_perintah,
            berat_kg=float(it.berat_perintah_kg or 0))
        berat, karung = await _berat_baris(db, b)
        ada, nama = await tersedia(db, b, abaikan_pesanan=True)
        if berat > ada + 0.5:
            raise BarangKeluarError(
                f"{nama} tinggal {_kg(ada)} kg sekarang — tak cukup untuk "
                f"{_kg(berat)} kg. Catat yang benar-benar dimuat per barang, "
                "lalu nyatakan selesai.")
        it.berat_kg, it.jumlah_karung = berat, karung
    return await _tutup_muatan(db, user=user, rec=rec, items=items,
                               tanggal=tanggal, jam=jam)


async def selesai_muat(db: AsyncSession, *, user, rec_id: int,
                       tanggal=None, jam=None) -> HasilPerintah:
    """Operator menyatakan truknya berangkat. Sisa perintah yang tak dimuat HANGUS.

    Bukan menggantung, dan itu keputusan yang disengaja: perintah yang tersisa
    separuh akan berdiri di antrean sampai seseorang mengingatnya, lalu dimuat
    seminggu kemudian ke truk yang salah. Selisihnya terbaca berdampingan di
    kartu verifikasi Admin — di situlah ia jadi pertanyaan, bukan jadi tugas.
    """
    rec = await _kunci(db, rec_id, keadaan=OUT_PERINTAH)
    items = list((await db.execute(
        select(OutgoingItem).where(OutgoingItem.outgoing_record_id == rec.id)
    )).scalars().all())
    if not any(float(i.berat_kg or 0) > 0.5 for i in items):
        raise BarangKeluarError(
            f"{rec.kode} belum punya satu pun barang yang tercatat dimuat. "
            "Catat muatannya dulu — atau kalau tak jadi berangkat, mintakan "
            "Admin membatalkan perintahnya.")
    return await _tutup_muatan(db, user=user, rec=rec, items=items,
                               tanggal=tanggal, jam=jam)


async def _tutup_muatan(db: AsyncSession, *, user, rec: OutgoingRecord,
                        items: list[OutgoingItem], tanggal=None,
                        jam=None) -> HasilPerintah:
    now = input_time(tanggal, jam)
    rec.status = OUT_DIMUAT
    rec.dimuat_oleh, rec.waktu_muat = user.id, now
    total = sum(float(i.berat_kg or 0) for i in items)
    kurang = sum(max(float(i.berat_perintah_kg or 0) - float(i.berat_kg or 0), 0)
                 for i in items)
    await _kabar(db, rec, untuk="admin",
                 pesan=f"🟡 {rec.kode} sudah dimuat {_kg(total)} kg untuk "
                       f"{rec.nama_pembeli}"
                       + (f" — kurang {_kg(kurang)} kg dari perintah"
                          if kurang > 0.5 else "")
                       + ". Tinggal diverifikasi Admin (tempelkan kode timbang "
                         "keluarnya).")
    await _jejak(db, rec, langkah="muat", oleh=user,
                 ringkas=f"{rec.kode} dimuat {_kg(total)} kg")
    await db.commit()
    await db.refresh(rec)
    return HasilPerintah(rec=rec, baris=items)


# ─────────────────── LANGKAH 3 · Admin verifikasi & menutup ───────────────────

async def verifikasi(db: AsyncSession, *, user, rec_id: int,
                     timbangan_transaksi_id: int | None = None,
                     tanggal=None, jam=None) -> tuple[OutgoingRecord, str]:
    """Admin menutup, sambil menempelkan kode timbang keluarnya. → (rec, catatan)

    ⚠ TIKETNYA DITEMPEL DI SINI, bukan lebih awal, dan urutan waktunya yang
    menentukan: truk masuk KOSONG, dimuat, lalu ditimbang bermuatan saat keluar.
    Tiketnya baru lengkap sesudah barangnya naik. Sisi MASUK justru dimulai dari
    tiketnya — menirunya mentah-mentah di sini akan membuat perintah tak bisa
    dibuat sebelum truknya datang.

    Beda bobot TIDAK menolak apa pun. Muatan sungguhan memang berselisih dari
    timbangan — karung tak persis 25,0 kg, dan truk membawa terpal. Yang
    dikerjakan cuma MENYEBUTKAN selisihnya, dan satu kalimat itulah yang membuat
    tautan ini berguna alih-alih sekadar ada.
    """
    rec = await _kunci(db, rec_id, keadaan=OUT_DIMUAT)
    total = float((await db.execute(
        select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .where(OutgoingItem.outgoing_record_id == rec.id))).scalar_one())

    catatan = ""
    if timbangan_transaksi_id is not None:
        berat_tiket, kode_tiket = await _tiket_keluar(db, timbangan_transaksi_id)
        rec.timbangan_transaksi_id = int(timbangan_transaksi_id)
        beda = berat_tiket - total
        catatan = (f"Timbangan {_kg(berat_tiket)} kg · dimuat menurut catatan "
                   f"{_kg(total)} kg")
        catatan += (" · sama persis." if abs(beda) < 0.5
                    else f" · beda {_kg(abs(beda))} kg "
                         f"({'timbangan lebih' if beda > 0 else 'catatan lebih'}).")
        catatan = f"{kode_tiket}: {catatan}"

    now = input_time(tanggal, jam)
    rec.status = OUT_SELESAI
    rec.diverifikasi_oleh, rec.waktu_verifikasi = user.id, now
    await _jejak(db, rec, langkah="verifikasi", oleh=user,
                 ringkas=f"{rec.kode} ditutup {_kg(total)} kg"
                         + (" + tiket timbang" if timbangan_transaksi_id else ""))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise BarangKeluarError(
            "Kode timbang itu sudah tertaut ke transaksi barang keluar lain. "
            "Satu tiket timbang hanya boleh dipakai satu transaksi — periksa "
            "lagi kode yang ditempel.") from None
    await db.refresh(rec)
    return rec, catatan


async def _tiket_keluar(db: AsyncSession, tid: int) -> tuple[float, str]:
    """(berat barang menurut tiket, kodenya). Menolak tiket yang bukan KELUAR.

    Arahnya diperiksa, dan itu bukan kehati-hatian berlebih: daftar yang
    ditawarkan layar memang sudah menyaring, tetapi rutenya bisa dipanggil
    dengan id apa pun, dan tiket MASUK yang tertempel di barang keluar akan
    membuat satu truk gabah terhitung sebagai penjualan beras.
    """
    from sqlalchemy import text

    from app.penggilingan.gudang1.services.timbang_link import (SQL_REAL_TIKET,
                                                                SYARAT_TIKET_SAH)

    # Rumus beratnya TIDAK ditulis ulang di sini. `berat_barang_kg` sudah
    # memotong tara karung; `netto_timbangan_kg` belum. Menyalin rumusnya ke
    # kueri keempat berarti satu di antaranya akan tertinggal pada perubahan
    # berikutnya — dan yang tertinggal jadi satu-satunya pintu yang terbuka.
    # Syarat "tiket sah" ikut dari sana pula: tiket yang DIBATALKAN atau
    # DITUTUP PAKSA di Pos Timbang pernah tetap mendorong 9.800 kg ke pembukuan.
    baris = (await db.execute(text(
        f"SELECT t.kode, t.arah, {SQL_REAL_TIKET}"
        "   FROM timbangan_transaksi t WHERE t.id = :id"), {"id": int(tid)})).first()
    if baris is None:
        raise BarangKeluarError("Kode timbang itu tidak ditemukan.")
    kode, arah, berat = baris
    if (arah or "").upper() != "KELUAR":
        raise BarangKeluarError(
            f"Tiket {kode} arahnya {arah}, bukan KELUAR — yang ditempel di "
            "barang keluar harus tiket timbang keluar.")
    sah = (await db.execute(text(
        "SELECT 1 FROM timbangan_transaksi t WHERE t.id = :id"
        + SYARAT_TIKET_SAH), {"id": int(tid)})).first()
    if sah is None:
        raise BarangKeluarError(
            f"Tiket {kode} sudah dibatalkan atau ditutup paksa di Pos Timbang — "
            "ia tak boleh jadi dasar barang keluar.")
    return float(berat or 0), kode


# ────────────────────────────── Pembatalan ──────────────────────────────

async def batalkan(db: AsyncSession, *, user, rec_id: int,
                   sebab: str) -> OutgoingRecord:
    """Batalkan perintah yang BELUM dimuat. Sebabnya wajib.

    Yang sudah dimuat tidak dibatalkan lewat sini: barangnya sudah di atas truk,
    dan menghapus catatannya membuat stok kembali naik atas beras yang sudah
    pergi. Yang begitu dibetulkan lewat pembatalan input terakhir, yang memang
    memeriksa hilirnya.
    """
    sebab = (sebab or "").strip()
    if not sebab:
        raise BarangKeluarError(
            "Tulis sebabnya — perintah yang hilang tanpa kabar akan ditanyakan "
            "operator sepanjang hari.")
    rec = await _kunci(db, rec_id, keadaan=OUT_PERINTAH)
    rec.status = OUT_BATAL
    rec.sebab_batal = sebab[:300]
    await _kabar(db, rec, untuk="operator", prioritas="merah",
                 pesan=f"🔴 Perintah muat {rec.kode} DIBATALKAN Admin — {sebab}")
    await _jejak(db, rec, langkah="batal", oleh=user,
                 ringkas=f"{rec.kode} dibatalkan — {sebab}")
    await db.commit()
    await db.refresh(rec)
    return rec


# ────────────────────────────── Pembacaan ──────────────────────────────

async def daftar(db: AsyncSession, *, status: tuple[str, ...] | None = None,
                 batas: int = 50) -> list[tuple[OutgoingRecord, list[OutgoingItem]]]:
    """Transaksi barang keluar beserta isinya — untuk halaman & kartunya."""
    q = select(OutgoingRecord).order_by(OutgoingRecord.id.desc()).limit(batas)
    if status:
        q = q.where(OutgoingRecord.status.in_(status))
    recs = list((await db.execute(q)).scalars().all())
    if not recs:
        return []
    isi: dict[int, list[OutgoingItem]] = {}
    for it in (await db.execute(
        select(OutgoingItem)
        .where(OutgoingItem.outgoing_record_id.in_([r.id for r in recs]))
        .order_by(OutgoingItem.id)
    )).scalars().all():
        isi.setdefault(it.outgoing_record_id, []).append(it)
    return [(r, isi.get(r.id, [])) for r in recs]


def gudang_perintah(items: list[OutgoingItem]) -> set[str]:
    """Gudang mana saja yang harus melihat perintah ini.

    Dihitung dari BARANGNYA, bukan dipilih Admin: barang jadi ada di Gudang 2,
    PK di Gudang 1, dan perintah yang mendarat di layar yang salah akan berdiri
    di sana sampai seseorang menelepon.
    """
    return {GUDANG_ITEM[i.item_type] for i in items if i.item_type in GUDANG_ITEM}
