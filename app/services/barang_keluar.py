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

from dataclasses import dataclass, field, replace
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
GUDANG_ITEM = {"finished_goods": G2, "byproduct_curah": G2, "pk_langsung": G1,
               "pk_g2": G2, "gabah_langsung": G1}


#: ── Kapan selisih timbang disebut BESAR ──
#:
#: Keputusan pemilik 30 September 2026: yang besar boleh tetap ditutup —
#: truknya sudah berangkat berjam-jam sebelumnya dan menahan penutupan tak
#: mengembalikannya — tetapi DITANDAI, dan sebabnya wajib ditulis.
#:
#: `max(…)` dari keduanya, bukan `min`. Persen saja akan menggigit muatan
#: kecil tanpa sebab: 2% dari 500 kg adalah 10 kg, dan sehelai terpal sudah
#: melewatinya. Angka mati saja akan melewatkan muatan besar: 100 kg pada
#: truk 50 ton adalah selisih yang tak berarti apa-apa. Yang ditandai harus
#: yang BENAR-BENAR janggal, sebab tanda yang terlalu sering muncul berhenti
#: dibaca — dan yang berhenti dibaca sama saja dengan tak ada.
AMBANG_SELISIH_KG = 100.0
AMBANG_SELISIH_PERSEN = 2.0


def ambang_selisih(total_kg: float) -> float:
    """Berapa kg selisih yang masih dianggap wajar untuk muatan sebesar ini."""
    return max(AMBANG_SELISIH_KG, float(total_kg) * AMBANG_SELISIH_PERSEN / 100)


#: ── Muatan kecil tak perlu tiket timbang keluar ──
#:
#: Keputusan pemilik 5 Oktober 2026. Diperiksa dulu: TIDAK ADA aturan yang
#: MEWAJIBKAN tiket — seluruh logikanya di `verifikasi()` berdiri di dalam
#: `if timbangan_transaksi_id is not None:`, dan tanpanya verifikasi menutup
#: dengan bersih. Yang berubah di sini CUMA RASA PEMAKAIAN borangnya: di
#: bawah angka ini medan "Kode timbang keluar" tak lagi DITAWARKAN sebagai
#: pilihan (`/actions/timbang-keluar-aktif?induk=<rec_id>` menjawab daftar
#: kosong), diganti satu baris keterangan.
#:
#: ⚠ BUKAN LARANGAN. Kalau muatan sekecil ini KEBETULAN ditimbang, tiketnya
#: tetap bisa ditautkan — medannya tetap `optional`, bukan disembunyikan
#: total, dan menautkan lewat jalur lain (mis. diketik manual kelak) tak
#: pernah ditolak. Yang berubah apakah app MENAWARKAN, bukan apakah ia
#: MENGIZINKAN.
#:
#: Satu angka di sini, di sebelah `ambang_selisih()`: dua ambang untuk dua
#: pertanyaan yang berbeda ("berapa selisih yang wajar" vs "muatan ini perlu
#: tiket atau tidak") tetap harus hidup berdampingan di SATU tempat, supaya
#: tak ada yang mengarang angka kedua di berkas lain suatu hari.
MUATAN_KECIL_TANPA_TIKET_KG = 200.0


class BarangKeluarError(Exception):
    """Kesalahan dengan pesan siap-tampil (args[0])."""


class VerifikasiOtomatisDitahan(BarangKeluarError):
    """Tiket perlu pemeriksaan manual; tidak ada stok atau muatan yang diubah."""


class MuatanBerubah(BarangKeluarError):
    """Cuplikan yang dikonfirmasi sudah berbeda dari keadaan terkunci."""


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
    #: Tempat asal — pk_g2 SAJA. None = TUMPUKAN (bukan "tak diisi", silo
    #: tertentu mengisi id-nya) — lihat docstring `OutgoingItem.silo_id`.
    silo_id: int | None = None               # pk_g2
    #: Lot gabah kering yang diambil — gabah_langsung SAJA.
    gabah_kering_lot_id: int | None = None   # gabah_langsung
    jumlah_karung: int | None = None
    berat_kg: float | None = None
    #: Pesanan jasa yang barangnya DIAMBIL — None untuk penjualan pabrik.
    #:
    #: DUA cara terisi, sejak 11 Oktober 2026 (dulu HANYA yang pertama):
    #:
    #:   · Diisi `buat_perintah`/`tambah_baris` dari perintahnya (`jasa_id=`
    #:     tunggal) — jalur SATU pesanan, dipakai saat pemanggil sudah tahu
    #:     persis satu `jasa_id` untuk SELURUH baris.
    #:   · Diisi PEMANGGIL langsung, per baris — jalur BANYAK pesanan, SATU
    #:     pelanggan (picker "Pengambilan barang jasa": barang dari beberapa
    #:     pesanan aktif pelanggan yang sama boleh naik satu truk sekaligus).
    #:     `buat_perintah` TAK menimpanya di jalur ini — ia memvalidasi
    #:     seluruh nilai yang sudah terisi menunjuk pesanan BERJALAN milik
    #:     SATU pelanggan yang sama, bukan menyamakannya jadi satu nilai.
    #:
    #: Yang tetap tak berubah: baris yang pemiliknya (PELANGGAN, bukan lagi
    #: nomor pesanan) berbeda dari pelanggan perintahnya adalah keadaan yang
    #: tak boleh bisa dinyatakan — lihat `buat_perintah`.
    jasa_id: int | None = None


@dataclass
class HasilPerintah:
    rec: OutgoingRecord
    baris: list[OutgoingItem] = field(default_factory=list)


def _kg(n) -> str:
    return f"{float(n or 0):,.0f}".replace(",", ".")


# ────────────────────────── Stok yang benar-benar bisa keluar ──────────────

#: Sentinel pembeda "silo_id tak ditanyakan" dari "ditanyakan, dan jawabannya
#: tumpukan (None)" — `None` sendiri adalah nilai SAH untuk tumpukan, jadi
#: pola `proc_id is not None` yang dipakai cabang lain di bawah tak bisa
#: dipakai ulang untuk `silo_id`.
_TAK_DIMINTA = object()


async def _kunci_saldo_keluar(db: AsyncSession) -> None:
    """Serialkan pemeriksaan dan perubahan saldo antar perintah berbeda.

    Kunci baris perintah hanya melindungi satu truk. Kunci transaksi ini
    mencegah dua perintah baru menjanjikan saldo yang sama; dilepas otomatis
    pada commit/rollback. SQLite hanya dipakai uji tanpa konkurensi.
    """
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(select(func.pg_advisory_xact_lock(184732901)))


async def _sudah_dipesan(db: AsyncSession, *, sku_id=None, std_id=None,
                         jenis=None, jasa_id=None, proc_id=None, silo_id=_TAK_DIMINTA,
                         gkr_id=None) -> float:
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
        q = (q.where(OutgoingItem.jasa_id.is_(None)) if jasa_id is None
             else q.where(OutgoingItem.jasa_id == jasa_id))
    elif jenis is not None:
        q = q.where(OutgoingItem.jenis_byproduct == jenis)
        q = (q.where(OutgoingItem.jasa_id.is_(None)) if jasa_id is None
             else q.where(OutgoingItem.jasa_id == jasa_id))
    elif proc_id is not None:
        q = q.where(OutgoingItem.milling_process_id == proc_id)
    elif silo_id is not _TAK_DIMINTA:
        # `item_type` WAJIB ikut disebut — `silo_id` sendiri NULL untuk
        # SELURUH jenis barang lain juga (hanya `pk_g2` yang mengisinya),
        # jadi tumpukan (`silo_id IS NULL`) tanpa syarat ini akan ikut
        # menjumlah perintah finished_goods/byproduct_curah/pk_langsung yang
        # sama sekali tak berhubungan.
        q = q.where(OutgoingItem.item_type == "pk_g2",
                    OutgoingItem.silo_id == silo_id,
                    OutgoingItem.jasa_id.is_(None) if jasa_id is None
                    else OutgoingItem.jasa_id == jasa_id)
    elif gkr_id is not None:
        q = q.where(OutgoingItem.gabah_kering_lot_id == gkr_id)
    return float((await db.execute(q)).scalar_one())


def baris_dari_item(it: OutgoingItem, *, jumlah_karung=None, berat_kg=None
                    ) -> BarisPerintah:
    """Susun ulang `BarisPerintah` dari baris perintah yang sudah tersimpan.

    ⚠ SATU TEMPAT, DAN SEBABNYA SUDAH TERBUKTI DUA KALI. Sampai 10 Oktober
    2026 `jasa_id` hidup di PERINTAHNYA (pemanggil wajib mengoper `rec.
    jasa_id` sendiri) — tiga tempat menyusun ulang baris ini melewatkannya,
    `tersedia()` lalu membaca stok PABRIK untuk barang pelanggan, dan
    pengambilan yang sah ditolak dengan kalimat yang menyuruh operator
    mencari kesalahan yang tak ada.

    Migrasi 0080 (11 Oktober 2026, truk boleh menggabung beberapa pesanan
    SATU pelanggan) menutup kelas kesalahan ini DI AKARNYA: `it.jasa_id`
    kini kolom sendiri di barisnya, jadi fungsi ini tak lagi MENERIMA
    parameter dari pemanggil sama sekali — tak ada lagi nilai yang bisa
    lupa dioper atau salah dioper (`rec.jasa_id`, yang sejak migrasi ini
    malah bisa NULL pada truk gabungan walau barisnya sendiri titipan).
    """
    return BarisPerintah(
        tipe=it.item_type, sku_id=it.product_sku_id,
        std_id=it.rice_quality_standard_id, jenis=it.jenis_byproduct,
        milling_process_id=it.milling_process_id, silo_id=it.silo_id,
        gabah_kering_lot_id=it.gabah_kering_lot_id,
        jumlah_karung=jumlah_karung, berat_kg=berat_kg,
        jasa_id=it.jasa_id)


async def tersedia(db: AsyncSession, b: BarisPerintah,
                   *, abaikan_pesanan: bool = False) -> tuple[float, str]:
    """(kg yang benar-benar bisa keluar, nama barangnya).

    `abaikan_pesanan` dipakai langkah MUAT: barisnya sendiri sudah termasuk
    "dipesan", jadi menguranginya lagi akan menolak muatan yang justru sedang
    dikerjakan sesuai perintahnya.
    """
    from app.penggilingan.inventory.finished_goods import (hitung_stok_byproduct_total,
                                                           hitung_stok_finished_goods)
    from app.services.stok import nama_produk
    from app.services.transfer import pending_transfer_kg

    if b.tipe == "finished_goods":
        # Milik siapa yang dihitung mengikuti perintahnya: penjualan pabrik
        # membaca stok pabrik, pengambilan jasa membaca barang pesanan itu.
        # Satu rumus, dua pertanyaan — lihat `hitung_stok_finished_goods`.
        stok = await hitung_stok_finished_goods(db, b.sku_id, b.std_id,
                                                jasa_id=b.jasa_id)
        ada, nama = float(stok["kg"]), await _nama_sku(db, b.sku_id, b.std_id)
        dipesan = 0.0 if abaikan_pesanan else await _sudah_dipesan(
            db, sku_id=b.sku_id, std_id=b.std_id, jasa_id=b.jasa_id)
    elif b.tipe == "byproduct_curah":
        # ⚠ DULU SELALU `hitung_stok_bekatul(db)`, apa pun `b.jenis`-nya —
        # "tersedia('menir')" menjawab stok BEKATUL berlabel "Menir" (pesan
        # kerja 11 butir 1). `hitung_stok_byproduct_curah` berparameter
        # jenis, dan pemiliknya diturunkan dari perintahnya sama seperti
        # `finished_goods` di atas — bukan cuma cacat jenisnya yang
        # dibetulkan, saringan pemiliknya pun baru ada sejak di sini.
        ada = float(await hitung_stok_byproduct_total(db, b.jenis or "",
                                                       jasa_id=b.jasa_id))
        nama = nama_produk(b.jenis or "")
        dipesan = (0.0 if abaikan_pesanan else
                   await _sudah_dipesan(db, jenis=b.jenis, jasa_id=b.jasa_id))
    elif b.tipe == "pk_langsung":
        from app.models import MillingProcess
        from app.services.jasa import nama_pemilik

        p = await db.get(MillingProcess, b.milling_process_id)
        # ⚠ PENJAGA, bukan saringan tampilan. Borang barang keluar menerima kode
        # lot yang DIKETIK, dan daftar pilihannya (`aksi_inventory`) sudah
        # menyembunyikan lot jasa — tetapi daftar yang menyaring tanpa penjaga di
        # belakangnya hanya menyaring yang patuh. Yang terjadi kalau ia lolos
        # bukan angka yang salah: PK pelanggan keluar pabrik sebagai penjualan,
        # dan tak ada pembetulan pembukuan yang mengembalikannya.
        # ⚠ Dua arah, dan keduanya perlu. PK pesanan lain tak boleh keluar atas
        # perintah ini — baik sebagai penjualan pabrik (`b.jasa_id` None) maupun
        # sebagai pengambilan oleh pesanan yang BUKAN pemiliknya. Yang kedua
        # itulah yang menyerahkan barang ke orang yang salah.
        if p is not None and p.jasa_id != b.jasa_id:
            milik = await nama_pemilik(db, p.jasa_id)
            raise BarangKeluarError(
                f"PK {p.kode_proses} "
                + (f"milik {milik}" if milik else "milik pabrik")
                + (" — barang jasa tidak dijual pabrik; pengambilannya lewat "
                   "perintah atas nama pesanannya."
                   if b.jasa_id is None else
                   " — bukan barang pesanan ini. Periksa lagi pilihannya."))
        ada = float(await pending_transfer_kg(db, b.milling_process_id))
        nama = f"PK {p.kode_proses}" if p else "PK"
        dipesan = 0.0 if abaikan_pesanan else await _sudah_dipesan(
            db, proc_id=b.milling_process_id)
    elif b.tipe == "pk_g2":
        from app.penggilingan.gudang2.service import (hitung_stok_silo,
                                                       hitung_stok_tumpukan,
                                                       label_tujuan)
        from app.services.jasa import (nama_pemilik, pemilik_silo_g2,
                                       pemilik_tumpukan_g2)

        nama_tempat = await label_tujuan(db, None, b.silo_id)
        pemilik_ids = (await pemilik_silo_g2(db, b.silo_id) if b.silo_id is not None
                       else set())
        # ⚠ Dua arah, sama bentuknya dengan `pk_langsung` di atas. Himpunan
        # HAMPA berarti tempatnya kosong — bukan "bertuan" — jadi tak ada yang
        # ditolak di sini; `ada` di bawah akan menjawab 0 kg dengan sendirinya.
        if b.silo_id is not None and pemilik_ids and b.jasa_id not in pemilik_ids:
            milik = await nama_pemilik(db, next(iter(pemilik_ids)))
            raise BarangKeluarError(
                f"PK Gudang 2 ({nama_tempat}) "
                + (f"milik {milik}" if milik else "milik pabrik")
                + (" — barang jasa tidak dijual pabrik; pengambilannya lewat "
                   "perintah atas nama pesanannya."
                   if b.jasa_id is None else
                   " — bukan barang pesanan ini. Periksa lagi pilihannya."))
        pemilik_pagar = "pabrik" if b.jasa_id is None else "jasa"
        ada = float(await (hitung_stok_silo(db, b.silo_id, pemilik=pemilik_pagar)
                           if b.silo_id is not None
                           else hitung_stok_tumpukan(db, jasa_id=b.jasa_id)))
        nama = f"PK Gudang 2 ({nama_tempat})"
        dipesan = 0.0 if abaikan_pesanan else await _sudah_dipesan(
            db, silo_id=b.silo_id, jasa_id=b.jasa_id)
    elif b.tipe == "gabah_langsung":
        from app.models import GabahKeringLot
        from app.penggilingan.gudang1.services.gabah_kering import (
            pending_gabah_kering_kg)
        from app.services.jasa import nama_pemilik

        lot = await db.get(GabahKeringLot, b.gabah_kering_lot_id)
        # ⚠ Dua arah, sama bentuknya dengan `pk_langsung`: gabah kering
        # pesanan lain tak boleh keluar atas perintah ini, baik sebagai
        # penjualan pabrik maupun pengambilan oleh pesanan yang BUKAN
        # pemiliknya.
        if lot is not None and lot.jasa_id != b.jasa_id:
            milik = await nama_pemilik(db, lot.jasa_id)
            raise BarangKeluarError(
                f"Gabah kering {lot.kode_lot} "
                + (f"milik {milik}" if milik else "milik pabrik")
                + (" — barang jasa tidak dijual pabrik; pengambilannya lewat "
                   "perintah atas nama pesanannya."
                   if b.jasa_id is None else
                   " — bukan barang pesanan ini. Periksa lagi pilihannya."))
        ada = (await pending_gabah_kering_kg(db, b.gabah_kering_lot_id)
              if lot is not None else 0.0)
        nama = f"Gabah kering {lot.kode_lot}" if lot else "Gabah kering"
        dipesan = 0.0 if abaikan_pesanan else await _sudah_dipesan(
            db, gkr_id=b.gabah_kering_lot_id)
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
        if not float(b.jumlah_karung).is_integer():
            raise BarangKeluarError("Jumlah karung wajib bilangan bulat.")
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
    if b.tipe in ("pk_langsung", "pk_g2"):
        return float(b.berat_kg), ceil(float(b.berat_kg) / 50)
    # `gabah_langsung` SENGAJA tak ikut baris di atas: gabah tak punya
    # ukuran karung baku (pesan kerja 12/12A) — menurunkan jumlah karung
    # dari kg÷50 akan mengarang ukuran yang tak pernah ada.
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
                 oleh, ringkas: str, medan: str | None = None,
                 lama: str | None = None, alasan: str | None = None) -> None:
    """Satu baris audit per langkah — penyegaran, audit, DAN jalan kembali.

    Penanda `/api/keadaan` yang menerbitkan pil "ada perubahan baru" adalah
    `max(activity_logs.id)`. Langkah yang tak menulis baris audit tak terlihat
    olehnya — bukan telat, tak pernah datang. Rantai permintaan PK menderita
    persis itu sampai 28 September 2026; rantai ini lahir sudah membawanya.

    `medan` & `lama` adalah CUPLIKAN KEADAAN SEBELUM langkah ini, dan itulah
    yang membuat langkahnya bisa dibatalkan (29 September 2026). Tanpa
    cuplikan, pembatalan harus menebak keadaan sebelumnya — dan tebakan yang
    paling menggoda, "kembalikan saja ke nol", salah justru pada keadaan yang
    paling sering: baris yang sudah dicatat sebagian oleh operator, lalu
    ditutup dengan satu ketukan "dimuat semua". Yang kembali ke nol di sana
    adalah barang yang sebenarnya sudah di atas truk.
    """
    await log_activity(
        db, table_name="outgoing_records", record_id=rec.id, action="UPDATE",
        aksi=f"barang_keluar_{langkah}", changed_by=getattr(oleh, "id", None),
        field_name=medan, old_value=lama, new_value=ringkas[:200], alasan=alasan)


# ─────────────────────── LANGKAH 1 · Admin memerintah ───────────────────────

async def _pembeli(db: AsyncSession, pelanggan_id: int | None) -> tuple[str, int]:
    """(nama yang dicatat, id pelanggan Kledo) — satu aturan, di satu tempat.

    NAMANYA DISALIN DARI MASTER, bukan dari yang diketik — borangnya hanya
    memilih dari daftar Kledo (permintaan pemilik 11 Oktober 2026, menutup
    kotak ketik-bebas yang dulu ada di sini): "Toko Makmur", "toko makmur",
    dan "TK Makmur" untuk satu pembeli pernah membuat laporan tak bisa
    menjumlahkannya.

    Namanya tetap DISIMPAN di baris perintahnya meski sudah ada tautannya: ia
    cuplikan hari itu. Kledo tidak punya "merge" — kontak ganda dirapikan
    dengan memindahkan transaksinya lalu menghapus yang ganda — jadi tautan
    saja tak cukup untuk menyebut pembeli sebuah surat jalan tahun lalu.
    """
    from app.models import Pelanggan

    if not pelanggan_id:
        raise BarangKeluarError(
            "Pilih pembelinya dari daftar pelanggan Kledo. Pelanggan baru "
            "didaftarkan dulu di Kledo sebelum bisa dipilih di sini — "
            "penyegaran kontaknya mingguan.")
    p = await db.get(Pelanggan, int(pelanggan_id))
    # Syaratnya sama dengan yang dipakai daftar pilihannya — yang
    # ditawarkan dan yang diterima harus himpunan yang sama, kalau tidak
    # ada pilihan yang bisa dipilih lalu ditolak.
    if p is None or p.deleted_at is not None or p.status != "aktif":
        raise BarangKeluarError(
            "Pelanggan itu sudah tidak ada di daftar — pilih yang lain.")
    return (p.nama_pelanggan or "").strip(), p.id


async def koreksi_plat(db: AsyncSession, *, user, rec_id: int,
                       no_polisi: str, alasan: str) -> OutgoingRecord:
    """Koreksi identitas truk sebelum diverifikasi, tanpa mengubah muatan."""
    from hmu_core import normalisasi_nomor_polisi

    plat = normalisasi_nomor_polisi(no_polisi)
    if not plat or len(plat) > 20:
        raise BarangKeluarError("Isi nomor polisi, maksimal 20 karakter.")
    sebab = (alasan or "").strip()
    if not sebab or len(sebab) > 300:
        raise BarangKeluarError("Isi alasan koreksi, maksimal 300 karakter.")
    rec = (await db.execute(select(OutgoingRecord).where(
        OutgoingRecord.id == rec_id).with_for_update())).scalar_one_or_none()
    if rec is None:
        raise BarangKeluarError("Perintah pengiriman tidak ditemukan.")
    if rec.status not in (OUT_PERINTAH, OUT_DIMUAT):
        raise BarangKeluarError("Plat hanya bisa dikoreksi sebelum pengiriman diverifikasi.")
    if rec.timbangan_transaksi_id is not None:
        raise BarangKeluarError("Pengiriman sudah tertaut tiket timbang; koreksi harus menjaga kesesuaian tiketnya.")
    if rec.no_polisi == plat:
        return rec
    lama = rec.no_polisi
    rec.no_polisi = plat
    await log_activity(db, table_name="outgoing_records", record_id=rec.id,
        action="UPDATE", changed_by=getattr(user, "id", None), field_name="no_polisi",
        old_value=lama, new_value=plat, alasan=sebab, aksi="koreksi_plat_pengiriman")
    await db.commit()
    return rec


async def _armada_dari_tiket(db: AsyncSession, tid: int, pelanggan_id: int,
                            *, rec_id: int | None = None):
    """Kunci satu tiket armada agar tidak dipilih dua pengiriman sekaligus."""
    from sqlalchemy import text
    tiket = (await db.execute(text("""
        SELECT id,kode,arah,status_transaksi,status_tiket,nomor_polisi,
               pelanggan_id,pihak_nama,timbang1_kg
        FROM timbangan_transaksi WHERE id=:id FOR UPDATE
    """), {"id": tid})).mappings().first()
    if (not tiket or tiket["arah"] != "KELUAR"
            or tiket["status_transaksi"] != "AKTIF"
            or tiket["status_tiket"] not in ("TERBUKA", "SELESAI")):
        raise BarangKeluarError("Pilih tiket timbang keluar yang masih aktif.")
    if not tiket["nomor_polisi"] or tiket["timbang1_kg"] is None:
        raise BarangKeluarError("Tiket armada belum memiliki plat dan timbang pertama.")
    if tiket["pelanggan_id"] is not None and tiket["pelanggan_id"] != pelanggan_id:
        raise BarangKeluarError("Pelanggan pada tiket armada berbeda dari pengiriman ini.")
    q = select(OutgoingRecord.id).where(
        OutgoingRecord.timbangan_transaksi_id == tid, OutgoingRecord.status != OUT_BATAL)
    if rec_id is not None:
        q = q.where(OutgoingRecord.id != rec_id)
    if (await db.execute(q.limit(1))).first():
        raise BarangKeluarError("Tiket armada sudah dipilih pengiriman lain.")
    # Identitas pelanggan berasal dari perintah, setelah tiket dipastikan bebas.
    await db.execute(text("""
        UPDATE timbangan_transaksi
        SET pelanggan_id=:pid, pihak_nama=(
            SELECT nama_pelanggan FROM pelanggan WHERE id=:pid)
        WHERE id=:tid
    """), {"pid": pelanggan_id, "tid": tid})
    return tiket


async def pilih_tiket_armada(db: AsyncSession, *, user, rec_id: int,
                            tiket_id: int) -> OutgoingRecord:
    """Perintah boleh dibuat dahulu; armada dipilih setelah datang ke timbang."""
    import json
    from sqlalchemy import text
    rec = await _kunci_hidup(db, rec_id)
    if rec.timbangan_transaksi_id not in (None, tiket_id):
        lama = (await db.execute(text("SELECT status_tiket FROM timbangan_transaksi WHERE id=:id FOR UPDATE"),
                                {"id": rec.timbangan_transaksi_id})).scalar_one_or_none()
        if lama != "TERBUKA":
            raise BarangKeluarError("Tiket lama sudah selesai; pasangan pengiriman tidak boleh diganti.")
    tiket = await _armada_dari_tiket(db, tiket_id, rec.pelanggan_id, rec_id=rec.id)
    sebelum = {"tiket_id": rec.timbangan_transaksi_id, "no_polisi": rec.no_polisi}
    rec.timbangan_transaksi_id = tiket_id
    rec.no_polisi = tiket["nomor_polisi"]
    await log_activity(db, table_name="outgoing_records", record_id=rec.id,
        action="UPDATE", changed_by=getattr(user, "id", None), aksi="pilih_tiket_armada",
        old_value=json.dumps(sebelum),
        new_value=f"{rec.kode} → {tiket['kode']} · {rec.no_polisi}")
    await db.commit()
    return rec


async def lepas_tiket_armada(db: AsyncSession, *, user, rec_id: int,
                             tiket_id: int, alasan: str, dasar: str | None = None) -> OutgoingRecord:
    """Lepaskan hubungan dalam kunci; jangan mengubah hasil timbang atau muatan.

    Tiket yang dilihat saat membuka formulir wajib masih sama. Jika petugas
    lain sudah mengganti armada, formulir lama tidak boleh melepas tiket baru.
    """
    from sqlalchemy import text
    if not alasan.strip():
        raise BarangKeluarError("Isi alasan melepas tiket armada.")
    rec = await _kunci_hidup(db, rec_id)
    if dasar is not None and (await ringkasan_muat(db, rec))["dasar"] != dasar:
        raise BarangKeluarError("Perintah atau armada berubah. Muat ulang detail dan periksa kembali.")
    if rec.timbangan_transaksi_id != tiket_id:
        raise BarangKeluarError("Tiket armada berubah atau sudah dilepas. Muat ulang detail dan periksa kembali.")
    tiket = (await db.execute(text(
        "SELECT id,kode FROM timbangan_transaksi WHERE id=:id FOR UPDATE"
    ), {"id": tiket_id})).mappings().first()
    if tiket is None:
        raise BarangKeluarError("Tiket timbang tidak ditemukan. Muat ulang detail.")
    import json
    sebelum = json.dumps({"tiket_id": tiket_id, "no_polisi": rec.no_polisi})
    rec.timbangan_transaksi_id = None
    rec.no_polisi = None
    await _jejak(db, rec, langkah="lepas_tiket_armada", oleh=user,
                 ringkas=f"{rec.kode} melepas {tiket['kode']} · muatan aktual tetap",
                 medan="timbangan_transaksi_id", lama=sebelum, alasan=alasan.strip())
    await _kabar(db, rec, untuk="operator",
                 pesan=f"Tiket armada {tiket['kode']} dilepas dari {rec.kode}. Periksa armada sebelum melanjutkan.")
    await db.commit()
    return rec


async def buat_perintah(
    db: AsyncSession, *, user, baris: list[BarisPerintah],
    pelanggan_id: int | None = None,
    jasa_id: int | None = None, tiket_armada_id: int | None = None,
    metode: str | None = None,
    no_polisi: str | None = None, nama_ekspedisi: str | None = None,
    catatan: str | None = None, tanggal=None, jam=None, simpan: bool = True,
) -> HasilPerintah:
    """Admin menerbitkan satu perintah muat. STOK BELUM BERKURANG.

    SATU TRUK SATU PERINTAH (keputusan pemilik): dua truk berarti dua perintah.
    Surat jalannya memang per truk, dan tiket timbangnya satu per truk — satu
    perintah yang dimuat dua truk akan membuat tautan tiketnya satu-ke-banyak,
    dan "sudah selesai belum?" jadi pertanyaan yang tak punya jawaban tunggal.

    Tiap baris diperiksa terhadap stok yang BENAR-BENAR bisa keluar — stok
    sekarang dikurangi yang sudah diperintahkan orang lain dan belum dimuat.
    Ditolak dengan menyebut angkanya.

    PEMBELINYA DITAUTKAN ke master `pelanggan` (keputusan pemilik 29 September
    2026: "nama pembeli di barang keluar sinkronkan dengan pelanggan di
    kledo"). `pelanggan_id` kini WAJIB — kotak ketik-bebas untuk pembeli yang
    belum ada di Kledo dicabut 11 Oktober 2026, lihat `_pembeli`.

    PENGAMBILAN JASA, DUA JALUR — keputusan pemilik 11 Oktober 2026 menambah
    jalur kedua, sesudah laporan lapangan: Pak Pras punya PK di Gudang 1
    *dan* Gudang 2, dua pesanan yang tak pernah bertemu fisik jadi tak
    tergabung otomatis (`pastikan_satu_pemilik`), dan "filter menurut
    pesanan hapus saja... sekali kiriman saya mau kirim semuanya":

      · `jasa_id=` (SATU nilai) — jalur lama, dipakai saat pemanggil sudah
        tahu persis satu pesanan untuk SELURUH baris (mis. `ambil-jasa`
        versi sebelumnya, atau pemanggil lain yang sengaja membatasi satu
        pesanan). Diturunkan ke SELURUH baris, menimpa apa pun yang sudah
        ada di sana.
      · Baris yang SUDAH membawa `jasa_id` masing-masing (picker "Barang
        yang diambil" yang baru — satu pelanggan, lintas pesanan) — TAK
        ditimpa. Divalidasi di sini: tiap `jasa_id` yang dipakai harus
        pesanan BERJALAN, dan SELURUHNYA harus pelanggan yang SAMA (barang
        dua pelanggan sekaligus tetap DITOLAK keras, cuma pemisahnya kini
        pelanggan — bukan lagi nomor pesanan — sejalan `pastikan_satu_
        pemilik`). `tersedia()` per baris TETAP memeriksa `jasa_id` baris
        itu terhadap pemilik SEBENARNYA sumbernya (silo/proses/dll) —
        tak berubah, dan itulah yang membuat jalur ini aman tanpa
        perubahan di sana.

    `outgoing_records.jasa_id` jadi NULL kalau barisnya menggabung lebih
    dari satu pesanan (satu nilai tak lagi cukup); `pelanggan_id` TETAP
    satu nilai selalu. `outgoing_items.jasa_id` (migrasi 0080) membawa
    kepemilikan SEBENARNYA per baris — itulah yang dibaca `sisa_jasa()`.
    """
    await _kunci_saldo_keluar(db)
    if not baris:
        raise BarangKeluarError(
            "Perintah tanpa satu pun barang tak bisa dikerjakan siapa pun.")
    if any(b.tipe == "pk_g2" and b.silo_id is not None for b in baris):
        raise BarangKeluarError(
            "PK di silo adalah bahan proses, bukan stok yang bisa dikirim langsung. "
            "Gunakan PK itu sebagai bahan penyosohan, lalu kirim hasil "
            "prosesnya dari stok produk.")
    from app.models import Jasa
    from app.models.jasa import BERJALAN

    if jasa_id is not None:
        # Jalur SATU pesanan — tak berubah dari sebelumnya.
        pesanan = await db.get(Jasa, int(jasa_id))
        if pesanan is None:
            raise BarangKeluarError("Pesanan jasa tidak ditemukan.")
        if pesanan.status != BERJALAN:
            raise BarangKeluarError(
                f"Pesanan {pesanan.kode} sudah {pesanan.status} — tak bisa "
                "mengambil barang lagi.")
        # Pembelinya PEMILIKNYA, dan tak perlu ditanya: barang titipan kembali
        # kepada yang menitipkannya.
        pelanggan_id = pesanan.pelanggan_id
        baris = [replace(b, jasa_id=int(jasa_id)) for b in baris]
    elif any(b.jasa_id is not None for b in baris):
        # Jalur BANYAK pesanan, SATU pelanggan — baris sudah membawa
        # `jasa_id` masing-masing dari picker, divalidasi (bukan ditimpa).
        dipakai = {b.jasa_id for b in baris if b.jasa_id is not None}
        ditemukan = {j.id: j for j in (await db.execute(
            select(Jasa).where(Jasa.id.in_(dipakai)))).scalars().all()}
        hilang = dipakai - ditemukan.keys()
        if hilang:
            raise BarangKeluarError(
                f"Pesanan jasa {sorted(hilang)} tidak ditemukan.")
        tak_jalan = [j for j in ditemukan.values() if j.status != BERJALAN]
        if tak_jalan:
            daftar = ", ".join(f"{j.kode} ({j.status})" for j in tak_jalan)
            raise BarangKeluarError(
                f"Pesanan sudah tak berjalan, tak bisa diambil lagi: {daftar}.")
        pelanggan_set = {j.pelanggan_id for j in ditemukan.values()}
        if len(pelanggan_set) > 1:
            from app.models import Pelanggan
            nama = dict((await db.execute(
                select(Pelanggan.id, Pelanggan.nama_pelanggan)
                .where(Pelanggan.id.in_(pelanggan_set)))).all())
            raise BarangKeluarError(
                "Barang ini milik pelanggan yang berbeda-beda — tak bisa "
                "naik satu truk yang sama: "
                + ", ".join(nama.get(p, f"#{p}") for p in sorted(pelanggan_set)) + ".")
        pelanggan_id = pelanggan_set.pop()
    nama_pembeli, pelanggan_id = await _pembeli(db, pelanggan_id)

    if tiket_armada_id is not None:
        tiket_armada = await _armada_dari_tiket(db, tiket_armada_id, pelanggan_id)
        no_polisi = tiket_armada["nomor_polisi"]

    dihitung: list[tuple[BarisPerintah, float, int | None]] = []
    dicadangkan: dict[tuple, float] = {}
    for b in baris:
        berat, karung = await _berat_baris(db, b)
        if berat <= 0:
            raise BarangKeluarError("Jumlah barang harus lebih dari nol.")
        ada, nama = await tersedia(db, b)
        # Baris berulang dalam satu formulir memakai saldo yang sama juga.
        sumber = ((b.sku_id, b.std_id) if b.tipe == "finished_goods" else
                  (b.jenis,) if b.tipe == "byproduct_curah" else
                  (b.silo_id,) if b.tipe == "pk_g2" else
                  (b.gabah_kering_lot_id,) if b.tipe == "gabah_langsung" else
                  (b.milling_process_id,))
        kunci = (b.tipe, b.jasa_id, *sumber)
        ada -= dicadangkan.get(kunci, 0.0)
        if berat > ada + 0.5:
            raise BarangKeluarError(
                f"{nama} tinggal {_kg(ada)} kg yang bisa keluar — tak bisa "
                f"memerintahkan {_kg(berat)} kg. (Yang sudah diperintahkan "
                "keluar tetapi belum dimuat ikut dikurangkan.)")
        dicadangkan[kunci] = dicadangkan.get(kunci, 0.0) + berat
        dihitung.append((b, berat, karung))

    # `rec.jasa_id`: satu nilai kalau SELURUH baris kebetulan satu pesanan
    # (termasuk jalur banyak-pesanan yang kebetulan cuma dipakai satu — tetap
    # ingin tampilannya sama persis dengan jalur lama), NULL kalau menggabung
    # lebih dari satu. `pelanggan_id` di atas TETAP satu nilai selalu.
    jasa_id_terpakai = {b.jasa_id for b in baris if b.jasa_id is not None}
    now = input_time(tanggal, jam)
    rec = OutgoingRecord(
        kode=await next_outgoing_code(db, now.date()),
        nama_pembeli=nama_pembeli, pelanggan_id=pelanggan_id,
        jasa_id=(jasa_id_terpakai.pop() if len(jasa_id_terpakai) == 1 else None),
        metode=metode, no_polisi=no_polisi,
        timbangan_transaksi_id=tiket_armada_id,
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
            silo_id=b.silo_id, gabah_kering_lot_id=b.gabah_kering_lot_id,
            # Kepemilikan SEBENARNYA baris ini — migrasi 0080. BUKAN
            # `rec.jasa_id` (yang bisa NULL kalau transaksinya menggabung
            # beberapa pesanan): `sisa_jasa()` membaca kolom ini.
            jasa_id=b.jasa_id,
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
    if simpan:
        await db.commit()
        await db.refresh(rec)
    return HasilPerintah(rec=rec, baris=items)


def _item_sama(it: OutgoingItem, b: BarisPerintah) -> bool:
    """Baris ini barang yang SAMA dengan yang hendak ditambahkan?

    Yang menentukan sama-tidaknya bukan namanya di layar melainkan apa yang
    menunjuk BARANGNYA: SKU + standar mutu untuk barang jadi (Premium 25 kg
    laminasi berbeda barang dari Premium 50 kg biasa), jenisnya untuk curah,
    dan lot asalnya untuk PK mentah — PK dari dua lot berbeda tak boleh
    digabung, sebab ketelusurannya ke pemasok lewat lot itu.

    ⚠ `jasa_id` ikut dibandingkan sejak migrasi 0080 (truk boleh menggabung
    beberapa pesanan SATU pelanggan) — tanpanya "menir curah" atau "PK
    tumpukan" dari DUA pesanan berbeda (silo/jenisnya sama persis, cuma
    pemiliknya beda) akan terbaca sebagai baris yang sama dan DIGABUNG,
    menghapus jejak milik pesanan mana sebagian dari kg itu sesungguhnya.
    """
    if it.item_type != b.tipe or it.jasa_id != b.jasa_id:
        return False
    if b.tipe == "finished_goods":
        return (it.product_sku_id == b.sku_id
                and it.rice_quality_standard_id == b.std_id)
    if b.tipe == "byproduct_curah":
        return (it.jenis_byproduct or "") == (b.jenis or "")
    if b.tipe == "pk_g2":
        # ⚠ BUKAN `milling_process_id` (selalu None di sini, pada KEDUA sisi) —
        # tempatnya `silo_id`, dan None di situ berarti TUMPUKAN, bukan "tak
        # diisi". Membiarkannya jatuh ke baris di bawah akan menyamakan silo
        # manapun dengan tumpukan (None == None) selama `milling_process_id`
        # keduanya None — yang selalu benar untuk pk_g2.
        return it.silo_id == b.silo_id
    if b.tipe == "gabah_langsung":
        return it.gabah_kering_lot_id == b.gabah_kering_lot_id
    return it.milling_process_id == b.milling_process_id


async def tambah_baris(db: AsyncSession, *, user, rec_id: int,
                       baris: BarisPerintah,
                       jasa_id: int | None = None, simpan: bool = True) -> HasilPerintah:
    """Ubah perintah saja; muatan aktual tetap dicatat operator.

    Perubahan setelah selesai muat membuka kembali antrean agar tambahan
    diperiksa operator sebelum Admin boleh memverifikasi truk yang sama.

    ⚠⚠ `baris.jasa_id` WAJIB diturunkan dari pemilik transaksi SEBENARNYA di
    SINI — tanpanya `tersedia()` selalu memeriksa `jasa_id=None` (pabrik) apa
    pun pemilik transaksinya, dua arah sekaligus: PK/gabah kering milik
    pesanan yang SAMA dengan transaksinya malah DITOLAK (pagar dua-arahnya
    membandingkan terhadap `None`, bukan pemilik transaksi yang sesungguhnya);
    produk jadi/curah malah LOLOS memakai stok PABRIK untuk transaksi yang
    sebenarnya pengambilan jasa. Laporan lapangan 10 Oktober 2026.

    ⚠ Sejak migrasi 0080 (truk boleh menggabung beberapa pesanan SATU
    pelanggan, lihat `buat_perintah`), `rec.jasa_id` SENDIRI tak lagi cukup
    jadi penentu: NULL berarti salah satu dari DUA keadaan — penjualan
    pabrik biasa, atau truk jasa gabungan yang justru PUNYA pemilik, cuma
    tak satu nilai. Dibedakan lewat ADA-TIDAKNYA baris ber-`jasa_id` yang
    sudah tercatat di transaksi ini: kalau ada, barang BARU wajib menyebut
    `jasa_id=` sendiri (pesanan mana, milik pelanggan transaksi yang sama)
    — DITOLAK kalau tidak, bukan diam-diam dianggap pabrik.
    """
    if baris.tipe == "pk_g2" and baris.silo_id is not None:
        raise BarangKeluarError(
            "PK di silo adalah bahan proses dan tidak bisa ditambahkan ke barang "
            "keluar. Gunakan PK itu sebagai bahan penyosohan, lalu kirim "
            "hasil prosesnya dari stok produk.")
    rec = await _kunci_hidup(db, rec_id)
    sudah_selesai_muat = rec.status == OUT_DIMUAT
    ada_baris_jasa = (await db.execute(
        select(OutgoingItem.id).where(
            OutgoingItem.outgoing_record_id == rec.id,
            OutgoingItem.jasa_id.isnot(None)).limit(1))).first()
    pesanan_id = jasa_id or baris.jasa_id or rec.jasa_id
    if rec.jasa_id is not None or ada_baris_jasa:
        from app.models import Jasa
        from app.models.jasa import BERJALAN
        if pesanan_id is None:
            raise BarangKeluarError("Sebutkan pesanan jasa asal barang tambahan ini.")
        pesanan = await db.get(Jasa, int(pesanan_id))
        if pesanan is None or pesanan.status != BERJALAN:
            raise BarangKeluarError("Pesanan jasa tidak ditemukan atau sudah tak berjalan.")
        if pesanan.pelanggan_id != rec.pelanggan_id:
            raise BarangKeluarError("Pesanan itu bukan milik pelanggan transaksi ini.")
        baris = replace(baris, jasa_id=int(pesanan_id))
    elif pesanan_id is not None:
        raise BarangKeluarError("Barang jasa tidak boleh ditambahkan ke perintah milik pabrik.")
    else:
        baris = replace(baris, jasa_id=None)

    berat, karung = await _berat_baris(db, baris)
    if berat <= 0:
        raise BarangKeluarError("Jumlah barang harus lebih dari nol.")

    # Yang ditambah hanya target. Pesanan lain tetap dicadangkan agar
    # perubahan perintah tidak menjanjikan stok yang sama ke dua truk.
    ada, nama = await tersedia(db, baris, abaikan_pesanan=False)
    if berat > ada + 0.5:
        raise BarangKeluarError(
            f"{nama} tinggal {_kg(ada)} kg yang bisa keluar — tak bisa "
            f"menambahkan {_kg(berat)} kg. "
            "Yang sudah diperintahkan keluar tetapi belum dimuat ikut dikurangkan.")

    items = list((await db.execute(
        select(OutgoingItem).where(OutgoingItem.outgoing_record_id == rec.id)
    )).scalars().all())
    lama = next((i for i in items if _item_sama(i, baris)), None)

    if lama is not None:
        lama.berat_perintah_kg = float(lama.berat_perintah_kg or 0) + berat
        if karung is not None:
            lama.jumlah_karung_perintah = (lama.jumlah_karung_perintah or 0) + karung
        jadi = float(lama.berat_perintah_kg)
    else:
        db.add(OutgoingItem(
            outgoing_record_id=rec.id, item_type=baris.tipe,
            product_sku_id=baris.sku_id, rice_quality_standard_id=baris.std_id,
            jenis_byproduct=baris.jenis,
            milling_process_id=baris.milling_process_id, silo_id=baris.silo_id,
            gabah_kering_lot_id=baris.gabah_kering_lot_id,
            jasa_id=baris.jasa_id,
            berat_perintah_kg=berat, jumlah_karung_perintah=karung,
            berat_kg=0, jumlah_karung=None))
        jadi = berat

    pemilik = {i.jasa_id for i in items} | {baris.jasa_id}
    rec.jasa_id = next(iter(pemilik)) if len(pemilik) == 1 else None
    kabar = (f"{rec.kode} + {nama} {_kg(berat)} kg pada perintah"
             + (f" (jadi {_kg(jadi)} kg)" if lama is not None else "")
             + " · muatan aktual tetap")
    if sudah_selesai_muat:
        # Reservasi lama sudah dilepas saat selesai muat. Sisa seluruh barang
        # perlu dicadangkan ulang, bukan hanya tambahan yang baru diminta.
        await db.flush()
        for i in list((await db.execute(select(OutgoingItem).where(
                OutgoingItem.outgoing_record_id == rec.id))).scalars().all()):
            sisa = max(float(i.berat_perintah_kg or 0) - float(i.berat_kg or 0), 0)
            if sisa:
                ada_sisa, nama_sisa = await tersedia(db, baris_dari_item(i))
                if sisa > ada_sisa + 0.5:
                    raise BarangKeluarError(f"{nama_sisa} tidak cukup untuk membuka kembali sisa perintah.")
        rec.status = OUT_PERINTAH
        rec.dimuat_oleh, rec.waktu_muat = None, None
    await _kabar(db, rec, untuk="operator",
                 pesan=f"🟡 Perintah {rec.kode} berubah: {nama} bertambah "
                       f"{_kg(berat)} kg. Periksa sisa dan catat muatan aktual.")
    await _jejak(db, rec, langkah="tambah", oleh=user, ringkas=kabar)
    await db.flush()
    if simpan:
        await db.commit()
        await db.refresh(rec)
    items = list((await db.execute(
        select(OutgoingItem).where(OutgoingItem.outgoing_record_id == rec.id)
    )).scalars().all())
    return HasilPerintah(rec=rec, baris=items)


async def ubah_baris_perintah(db: AsyncSession, *, user, rec_id: int,
                              item_id: int, dasar: str, jumlah: float | None,
                              alasan: str, hapus: bool = False) -> OutgoingRecord:
    """Mengubah target dalam kunci saldo; aktual tidak pernah ikut berubah.

    Cuplikan seluruh perintah menahan formulir basi, termasuk bila operator
    mencatat muatan ketika Admin sedang memperbaiki targetnya.
    """
    import math
    if not alasan.strip():
        raise BarangKeluarError("Isi alasan perubahan perintah.")
    rec = await _kunci_hidup(db, rec_id)
    ringkas = await ringkasan_muat(db, rec)
    if not dasar or ringkas["dasar"] != dasar:
        raise BarangKeluarError(
            "Perintah atau muatan berubah. Tutup formulir, muat ulang detail, "
            "dan periksa kembali. Tidak ada perubahan yang disimpan.")
    items = list((await db.execute(select(OutgoingItem).where(
        OutgoingItem.outgoing_record_id == rec.id))).scalars().all())
    it = next((i for i in items if i.id == item_id), None)
    if it is None:
        raise BarangKeluarError("Barang ini tidak ada pada perintah tersebut.")
    nama = await _nama_baris(db, it)
    sebelumnya = float(it.berat_perintah_kg or 0)
    if hapus:
        if float(it.berat_kg or 0) > 0 or (it.jumlah_karung or 0) > 0:
            raise BarangKeluarError(
                "Barang sudah dimuat. Periksa dan koreksi muatan aktual dahulu; "
                "menghapus item tidak boleh menghapus barang yang masih di truk.")
        if len(items) == 1:
            raise BarangKeluarError(
                "Ini barang terakhir. Gunakan Batalkan perintah untuk membatalkan pengiriman.")
        await db.delete(it)
        pemilik = {i.jasa_id for i in items if i.id != item_id}
        rec.jasa_id = next(iter(pemilik)) if len(pemilik) == 1 else None
        pesan = f"{nama} dihapus dari perintah ({_kg(sebelumnya)} kg)"
    else:
        if jumlah is None or not math.isfinite(jumlah) or jumlah <= 0:
            raise BarangKeluarError("Total perintah harus lebih dari nol.")
        b = baris_dari_item(it, jumlah_karung=jumlah, berat_kg=jumlah)
        if b.tipe == "pk_g2" and b.silo_id is not None:
            raise BarangKeluarError("PK di silo adalah bahan proses, bukan stok yang bisa diambil.")
        berat, karung = await _berat_baris(db, b)
        # Saldo sudah dikurangi reservasi lama baris ini. Hanya kenaikan
        # sisa target yang membutuhkan reservasi tambahan.
        aktual = float(it.berat_kg or 0)
        tambahan = max(berat - aktual, 0) - (
            max(sebelumnya - aktual, 0) if rec.status == OUT_PERINTAH else 0)
        if tambahan > 0:
            ada, _ = await tersedia(db, b, abaikan_pesanan=False)
            if tambahan > ada + 0.5:
                raise BarangKeluarError(f"{nama} tinggal {_kg(ada)} kg yang belum dicadangkan.")
        it.berat_perintah_kg, it.jumlah_karung_perintah = berat, karung
        pesan = f"{nama}: target {_kg(sebelumnya)} → {_kg(berat)} kg"
    if rec.status == OUT_DIMUAT:
        # Sisa target baris lain sudah tidak dicadangkan setelah selesai
        # muat. Membuka kembali pesanan harus mencadangkannya lagi juga.
        for lain in items:
            if lain.id == item_id:
                continue
            sisa = max(float(lain.berat_perintah_kg or 0) - float(lain.berat_kg or 0), 0)
            if sisa:
                ada, nama_lain = await tersedia(db, baris_dari_item(lain))
                if sisa > ada + 0.5:
                    raise BarangKeluarError(f"{nama_lain} tidak cukup untuk membuka kembali sisa perintah.")
        rec.status = OUT_PERINTAH
        rec.dimuat_oleh, rec.waktu_muat = None, None
    await _jejak(db, rec, langkah="hapus_item_perintah" if hapus else "ubah_item_perintah",
                 oleh=user, ringkas=f"{rec.kode} · {pesan} · aktual tetap",
                 alasan=alasan.strip())
    await _kabar(db, rec, untuk="operator",
                 pesan=f"Perintah {rec.kode} berubah: {pesan}. Periksa muatan aktual kembali.")
    await db.commit()
    return rec


# ─────────────────────── LANGKAH 2 · Operator memuat ───────────────────────

async def _kunci_hidup(db: AsyncSession, rec_id: int) -> OutgoingRecord:
    """Ambil barisnya terkunci selama ia BELUM DIVERIFIKASI — `perintah` atau
    `dimuat`.

    Dipakai penambahan barang, yang berlaku di kedua keadaan itu (keputusan
    pemilik 29 September 2026). Yang SUDAH ditutup tidak: menambah barang ke
    transaksi yang angkanya sudah diakui Admin berarti mengubah angka yang
    sudah jadi dasar keputusan, tanpa siapa pun melihatnya lagi.
    """
    from app.penggilingan.inventory.models import OUT_HIDUP

    await _kunci_saldo_keluar(db)
    rec = (await db.execute(
        select(OutgoingRecord).where(OutgoingRecord.id == rec_id).with_for_update()
        .execution_options(populate_existing=True)
    )).scalars().first()
    if rec is None:
        raise BarangKeluarError("Transaksi itu sudah tidak ada.")
    if rec.status not in OUT_HIDUP:
        raise BarangKeluarError(await _kalimat_keadaan(db, rec, OUT_PERINTAH))
    return rec


async def _kunci(db: AsyncSession, rec_id: int, *, keadaan: str) -> OutgoingRecord:
    """Ambil barisnya TERKUNCI, lalu pastikan keadaannya masih yang diharap.

    `FOR UPDATE` membuat penekan kedua MENUNGGU yang pertama commit, lalu
    membaca ulang keadaannya — kini sudah berubah — dan ditolak dengan kalimat
    yang menyebut siapa yang mendahuluinya. Memeriksa lebih dulu tanpa kunci
    membuat dua-duanya lolos: dua operator, dua HP, satu detik.
    """
    await _kunci_saldo_keluar(db)
    rec = (await db.execute(
        select(OutgoingRecord).where(OutgoingRecord.id == rec_id).with_for_update()
        .execution_options(populate_existing=True)
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
                       berat_kg: float | None = None, dasar: str | None = None,
                       rec_id: int | None = None) -> tuple[OutgoingRecord, str]:
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
    if rec_id is not None and rec.id != rec_id:
        raise BarangKeluarError("Barang itu bukan bagian dari perintah yang dipilih.")
    await _periksa_dasar_muat(db, rec, dasar)
    # Item dapat dibaca sebelum menunggu kunci perintah. Baca ulang sesudah
    # kunci diperoleh agar cuplikan undo tidak mengambil angka milik transaksi lama.
    await db.refresh(it)
    if jumlah_karung is not None and not float(jumlah_karung).is_integer():
        raise BarangKeluarError("Total yang sudah dimuat dalam karung wajib bilangan bulat.")
    if it.item_type == "pk_g2" and it.silo_id is not None:
        raise BarangKeluarError("PK di silo adalah bahan proses, bukan stok yang bisa diambil.")
    b = baris_dari_item(it, jumlah_karung=jumlah_karung, berat_kg=berat_kg)
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
    karung_lama = it.jumlah_karung
    it.berat_kg = berat
    it.jumlah_karung = karung
    # Cuplikannya diambil dari `sudah`/`karung_lama` — angka SEBELUM ketukan
    # ini, bukan nol. Baris yang dicatat 300 karung lalu diperbaiki jadi 280
    # harus bisa kembali ke 300; yang dikembalikan ke nol akan menaikkan stok
    # atas 300 karung yang masih tertulis di catatan.
    await _jejak(db, rec, langkah="muat_baris", oleh=user,
                 ringkas=f"{rec.kode} · {nama} {_kg(berat)} kg",
                 medan=f"item:{it.id}",
                 lama=f"{sudah:.2f}|{'' if karung_lama is None else karung_lama}")
    await db.commit()
    await db.refresh(rec)
    kurang = perintah - berat
    return rec, (f"✓ {nama} {_kg(berat)} kg dicatat"
                 + (f" — kurang {_kg(kurang)} kg dari perintah."
                    if kurang > 0.5 else "."))


async def ringkasan_muat(db: AsyncSession, rec: OutgoingRecord) -> dict:
    """Cuplikan yang dilihat operator dan dibandingkan lagi di dalam kunci.

    Hash mencakup target, aktual, pemilik, armada, serta jejak perintah. Bahkan
    perubahan yang kembali ke angka semula tetap meminta pemeriksaan ulang.
    """
    import hashlib
    import json
    items = list((await db.execute(select(OutgoingItem).where(
        OutgoingItem.outgoing_record_id == rec.id).order_by(OutgoingItem.id)
        .execution_options(populate_existing=True))).scalars().all())
    from app.models import ActivityLog
    jejak = (await db.execute(select(func.max(ActivityLog.id)).where(
        ActivityLog.table_name == "outgoing_records", ActivityLog.record_id == rec.id)
    )).scalar_one_or_none()
    dasar = [rec.id, rec.status, rec.no_polisi, rec.nama_pembeli, jejak]
    baris = []
    for it in items:
        _, nama = await tersedia(db, baris_dari_item(it), abaikan_pesanan=True)
        karung = it.item_type == "finished_goods"
        target = float(it.jumlah_karung_perintah or 0) if karung else float(it.berat_perintah_kg or 0)
        aktual = float(it.jumlah_karung or 0) if karung else float(it.berat_kg or 0)
        baris.append({"id": it.id, "nama": nama, "perintah": target,
                      "dimuat": aktual, "sisa": max(target - aktual, 0),
                      "satuan": "karung" if karung else "kg"})
        dasar.append([it.id, it.item_type, it.jasa_id, str(it.berat_perintah_kg),
                      it.jumlah_karung_perintah, str(it.berat_kg), it.jumlah_karung])
    token = hashlib.sha256(json.dumps(dasar, ensure_ascii=False).encode()).hexdigest()
    teks = f"{rec.kode} · {rec.nama_pembeli or '—'} · {rec.no_polisi or 'tanpa plat'}"
    for b in baris:
        teks += (f"\n{b['nama']}: perintah {b['perintah']:g} {b['satuan']} · "
                 f"sudah dimuat {b['dimuat']:g} · sisa {b['sisa']:g} {b['satuan']}")
    return {"dasar": token, "teks": teks, "baris": baris}


async def _periksa_dasar_muat(db, rec, dasar):
    if dasar is not None:
        silo = (await db.execute(select(OutgoingItem.id).where(
            OutgoingItem.outgoing_record_id == rec.id,
            OutgoingItem.item_type == "pk_g2", OutgoingItem.silo_id.isnot(None))
        )).first()
        if silo:
            raise BarangKeluarError("PK di silo adalah bahan proses, bukan stok yang bisa diambil.")
    if dasar is not None and (await ringkasan_muat(db, rec))["dasar"] != dasar:
        raise MuatanBerubah(
            "Perintah atau muatan berubah sejak diperiksa. Kembali, periksa "
            "ringkasan terbaru, lalu konfirmasi ulang. Tidak ada muatan yang diubah.")


async def muat_semua(db: AsyncSession, *, user, rec_id: int,
                     tanggal=None, jam=None, dasar: str | None = None) -> HasilPerintah:
    """Seluruh baris dimuat PERSIS seperti diperintahkan — satu ketukan.

    Ini keadaan yang paling sering, dan borang yang menuntut operator mengetik
    ulang angka yang sudah tertulis di kartunya akan diketik asal-asalan.
    Keputusan pemilik 18 Oktober 2026: yang baru dicatat 80 dari perintah 100
    dilengkapi menjadi 100. Selisih stok hanya 20, bukan memotong 100 lagi.
    """
    rec = await _kunci(db, rec_id, keadaan=OUT_PERINTAH)
    await _periksa_dasar_muat(db, rec, dasar)
    items = list((await db.execute(
        select(OutgoingItem).where(OutgoingItem.outgoing_record_id == rec.id)
    )).scalars().all())
    # Cuplikan angka sebelumnya memastikan pembatalan mengembalikan tambahan
    # ketukan ini saja: 80 → 100 dibatalkan menjadi 80, bukan nol.
    diisi: list[int] = []
    cuplikan: dict[int, tuple[float, int | None]] = {}
    for it in items:
        sudah = float(it.berat_kg or 0)
        b = baris_dari_item(it, jumlah_karung=it.jumlah_karung_perintah,
                            berat_kg=float(it.berat_perintah_kg or 0))
        berat, karung = await _berat_baris(db, b)
        ada, nama = await tersedia(db, b, abaikan_pesanan=True)
        tambahan = berat - sudah
        if tambahan < -0.5:
            raise BarangKeluarError(
                f"{nama} sudah dimuat {_kg(sudah)} kg, melebihi perintah "
                f"{_kg(berat)} kg. Periksa perubahan perintah dengan Admin; "
                "muatan aktual tidak dikurangi otomatis.")
        if tambahan > ada + 0.5:
            raise BarangKeluarError(
                f"{nama} tinggal {_kg(ada)} kg sekarang — tak cukup untuk "
                f"tambahan {_kg(tambahan)} kg. Catat yang benar-benar dimuat "
                "per barang, lalu nyatakan selesai.")
        if sudah != berat or it.jumlah_karung != karung:
            cuplikan[it.id] = (sudah, it.jumlah_karung)
            diisi.append(it.id)
            it.berat_kg, it.jumlah_karung = berat, karung
    return await _tutup_muatan(db, user=user, rec=rec, items=items,
                               tanggal=tanggal, jam=jam, diisi=diisi,
                               cuplikan=cuplikan)


async def selesai_muat(db: AsyncSession, *, user, rec_id: int,
                       tanggal=None, jam=None, dasar: str | None = None,
                       sebab: str = "") -> HasilPerintah:
    """Operator menyatakan truknya berangkat. Sisa perintah yang tak dimuat HANGUS.

    Bukan menggantung, dan itu keputusan yang disengaja: perintah yang tersisa
    separuh akan berdiri di antrean sampai seseorang mengingatnya, lalu dimuat
    seminggu kemudian ke truk yang salah. Selisihnya terbaca berdampingan di
    kartu verifikasi Admin — di situlah ia jadi pertanyaan, bukan jadi tugas.
    """
    rec = await _kunci(db, rec_id, keadaan=OUT_PERINTAH)
    await _periksa_dasar_muat(db, rec, dasar)
    items = list((await db.execute(
        select(OutgoingItem).where(OutgoingItem.outgoing_record_id == rec.id)
    )).scalars().all())
    if not any(float(i.berat_kg or 0) > 0.5 for i in items):
        raise BarangKeluarError(
            f"{rec.kode} belum punya satu pun barang yang tercatat dimuat. "
            "Catat muatannya dulu — atau kalau tak jadi berangkat, mintakan "
            "Admin membatalkan perintahnya.")
    kurang = sum(max(float(i.berat_perintah_kg or 0) - float(i.berat_kg or 0), 0)
                 for i in items)
    if kurang > 0.5 and not sebab.strip():
        raise BarangKeluarError("Muatan kurang dari perintah. Tulis alasan barang tidak terkirim.")
    # `diisi` kosong dengan sengaja: ketukan ini tak mengisi satu angka pun —
    # angkanya sudah dicatat operator per baris lebih dulu. Yang dibatalkan
    # nanti cuma PENUTUPANNYA, dan angka per barisnya tetap berdiri.
    return await _tutup_muatan(db, user=user, rec=rec, items=items,
                               tanggal=tanggal, jam=jam, diisi=[], sebab=sebab)


async def _tutup_muatan(db: AsyncSession, *, user, rec: OutgoingRecord,
                        items: list[OutgoingItem], tanggal=None,
                        jam=None, diisi: list[int] | None = None,
                        cuplikan: dict[int, tuple[float, int | None]] | None = None,
                        sebab: str = "") -> HasilPerintah:
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
    # Jejak lama cukup menyebut id untuk baris yang sebelumnya nol. Ketika
    # melengkapi muatan parsial, pembatalan harus kembali ke 80, bukan nol.
    import json
    parsial = cuplikan and any(berat > 0 for berat, _ in cuplikan.values())
    await _jejak(db, rec, langkah="muat", oleh=user,
                 ringkas=f"{rec.kode} dimuat {_kg(total)} kg"
                         + (f" — tidak terkirim: {sebab.strip()}" if sebab.strip() else ""),
                 medan="muatan_lama" if parsial else "diisi",
                 lama=(json.dumps(cuplikan) if parsial else
                       ",".join(str(i) for i in (diisi or []))),
                 alasan=sebab.strip() or None)
    await db.commit()
    await db.refresh(rec)
    return HasilPerintah(rec=rec, baris=items)


# ─────────────────── LANGKAH 3 · Admin verifikasi & menutup ───────────────────

async def verifikasi(db: AsyncSession, *, user, rec_id: int,
                     timbangan_transaksi_id: int | None = None,
                     sebab_selisih: str | None = None,
                     tanggal=None, jam=None, otomatis: bool = False) -> tuple[OutgoingRecord, str]:
    """Admin menutup memakai tiket armada yang sudah dipilih. → (rec, catatan)

    Perintah dan kedatangan armada tidak saling menunggu. Tiket boleh dipilih
    sejak timbang pertama, atau menyusul setelah perintah dibuat. Verifikasi
    tetap menunggu timbang kedua selesai dan memakai tiket yang sudah dipilih.

    Beda bobot TIDAK menolak apa pun. Muatan sungguhan memang berselisih dari
    timbangan — karung tak persis 25,0 kg, dan truk membawa terpal. Yang
    dikerjakan cuma MENYEBUTKAN selisihnya, dan satu kalimat itulah yang membuat
    tautan ini berguna alih-alih sekadar ada.

    ⭐ SATU TRUK, BANYAK MACAM BARANG — dan inilah jawaban atas pertanyaan
    operator 30 September 2026 ("beras dan broken keluar jadi 1 mobil,
    bagaimana cara menimbangnya"). Jawabannya: TIDAK ADA angka timbangan yang
    dibagi ke tiap barang. Tiap baris punya angkanya sendiri dari karung yang
    dimuat; tiket memberi SATU angka untuk seluruh bak; yang dibandingkan
    TOTAL lawan TOTAL.

    ⚠ Dan yang TIDAK BOLEH dikerjakan, sekarang maupun kelak: membagi selisih
    timbangan ke tiap baris secara proporsional supaya "jumlahnya cocok". Itu
    membuat angka per jenis terlihat pasti padahal ditebak — dan angka itulah
    yang dipakai menghitung stok.

    SELISIH BESAR wajib bersebab (keputusan pemilik 30 September 2026): boleh
    tetap ditutup, tetapi ditandai. Ambangnya `ambang_selisih()`.
    """
    rec = await _kunci(db, rec_id, keadaan=OUT_DIMUAT)
    total = float((await db.execute(
        select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .where(OutgoingItem.outgoing_record_id == rec.id))).scalar_one())

    if rec.timbangan_transaksi_id is not None:
        if timbangan_transaksi_id not in (None, rec.timbangan_transaksi_id):
            raise BarangKeluarError("Tiket berbeda dari armada yang sudah dipilih.")
        timbangan_transaksi_id = rec.timbangan_transaksi_id
    if otomatis and (timbangan_transaksi_id is None or total <= 0):
        raise VerifikasiOtomatisDitahan("Verifikasi otomatis memerlukan tiket armada dan muatan aktual lebih dari nol.")
    catatan = ""
    sebab_selisih = (sebab_selisih or "").strip()
    if timbangan_transaksi_id is not None:
        berat_tiket, kode_tiket = await _tiket_keluar(db, timbangan_transaksi_id)
        if otomatis:
            from sqlalchemy import text
            from decimal import Decimal
            tiket = (await db.execute(text("SELECT berat_barang_kg,timbang2_kg,total_tara_kg FROM timbangan_transaksi WHERE id=:id FOR UPDATE"),
                                      {"id": timbangan_transaksi_id})).mappings().one()
            if any(tiket[k] is None for k in ("berat_barang_kg", "timbang2_kg", "total_tara_kg")):
                raise VerifikasiOtomatisDitahan("Berat timbang kedua setelah tara belum lengkap; periksa manual.")
            nyata = Decimal(str(tiket["berat_barang_kg"]))
            target = Decimal(str(total))
            batas = target * Decimal("0.002")
            if not nyata.is_finite() or not target.is_finite() or nyata <= 0 or Decimal(str(tiket["timbang2_kg"])) <= 0 or Decimal(str(tiket["total_tara_kg"])) < 0:
                raise VerifikasiOtomatisDitahan("Berat timbang atau tara tidak sah; periksa manual.")
            if abs(nyata - target) > batas:
                raise VerifikasiOtomatisDitahan(
                    f"Selisih {abs(nyata-target):g} kg melewati batas verifikasi otomatis {batas:g} kg (±0,2% dari muatan aktual). Periksa manual.")
            berat_tiket = float(nyata)
        rec.timbangan_transaksi_id = int(timbangan_transaksi_id)
        beda = berat_tiket - total
        catatan = (f"Timbangan {_kg(berat_tiket)} kg · dimuat menurut catatan "
                   f"{_kg(total)} kg")
        catatan += (" · sama persis." if abs(beda) < 0.5
                    else f" · beda {_kg(abs(beda))} kg "
                         f"({'timbangan lebih' if beda > 0 else 'catatan lebih'}).")
        catatan = f"{kode_tiket}: {catatan}"
        ambang = ambang_selisih(total)
        if abs(beda) > ambang:
            # DITOLAK SEKARANG, bukan diterima lalu ditandai diam-diam: satu-
            # satunya orang yang masih tahu sebabnya adalah yang sedang
            # memegang layarnya. Besok pagi tanda tanpa sebab cuma jadi
            # pekerjaan menelusur untuk orang yang tak pernah melihat truknya.
            if not sebab_selisih:
                raise BarangKeluarError(
                    f"Beda {_kg(abs(beda))} kg melewati batas wajar "
                    f"{_kg(ambang)} kg untuk muatan {_kg(total)} kg. "
                    "Boleh tetap ditutup — tulis sebabnya, dan kartunya akan "
                    "ditandai.")
            rec.sebab_selisih = sebab_selisih[:300]
            catatan += f" ⚠ Selisih besar — {rec.sebab_selisih}"
        elif sebab_selisih:
            # Sebab yang ditulis padahal selisihnya wajar TETAP DISIMPAN.
            # Admin yang repot-repot menuliskannya sedang menyebutkan sesuatu;
            # membuangnya karena "tak wajib" berarti membuang satu-satunya
            # keterangan yang pernah ada tentang truk itu.
            rec.sebab_selisih = sebab_selisih[:300]

    now = input_time(tanggal, jam)
    rec.status = OUT_SELESAI
    rec.diverifikasi_oleh, rec.waktu_verifikasi = user.id, now
    await _jejak(db, rec, langkah="verifikasi", oleh=user,
                 ringkas=f"{rec.kode} ditutup {_kg(total)} kg"
                         + (" + tiket timbang" if timbangan_transaksi_id else "")
                         + (" · otomatis ±0,2% setelah tara" if otomatis else ""),
                 alasan="Verifikasi otomatis: selisih setelah tara dalam ±0,2% muatan aktual." if otomatis else None)
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


@dataclass
class HasilAutoTaut:
    tertaut: list[str] = field(default_factory=list)
    dilewati: list[str] = field(default_factory=list)

    @property
    def ringkas(self) -> str:
        bagian = [f"{len(self.tertaut)} tertaut"]
        if self.dilewati:
            bagian.append(f"{len(self.dilewati)} dilewati")
        return ", ".join(bagian)


async def auto_tautkan(db: AsyncSession, *, user) -> HasilAutoTaut:
    """Tautkan otomatis tiket timbang keluar yang menganggur ke pesanan yang
    menunggu verifikasi — HANYA bila pasangannya tak ambigu.

    Permintaan pemilik 4 Oktober 2026, untuk membereskan tiket lama yang
    terlanjur menumpuk tanpa pasangan (lihat `_kartu_tiket_keluar_menganggur`
    di `berjalan.py`). Dasar pencocokannya SENGAJA bukan nomor urut kode —
    kode timbang (`KLR-tanggal-PERANGKAT-urutan`, bernomor per ALAT per hari)
    dan kode pesanan (`OUT-tanggal-urutan`, bernomor platform per hari) dua
    penghitung yang sama sekali tak berhubungan; mencocokkan nomornya akan
    menautkan pasangan yang kebetulan sama angkanya, bukan yang benar
    berpasangan. Dasarnya PEMBELI + TANGGAL + BERAT, dan ambang beratnya
    maksimal ±0,2% muatan aktual setelah tara (20 kg per 10 ton).
    Ambang verifikasi manual tetap terpisah.

    TAK PERNAH menebak: satu tiket yang cocok dengan lebih dari satu pesanan
    (atau sebaliknya) DILEWATI, bukan ditautkan ke salah satunya — falsafah
    yang sama dengan nama kembar di `hmu_core.kledo_kontak`. Dipanggil lewat
    satu tombol (bukan terjadwal tanpa pengawas): orang yang menekannya
    tercatat sebagai yang memverifikasi, persis seperti tautan manual.
    """
    from app.penggilingan.gudang1.services.timbang_link import tiket_keluar_aktif

    def kunci(nama: str | None) -> str:
        return " ".join((nama or "").lower().split())

    tiket = await tiket_keluar_aktif(db)
    pesanan = await daftar(db, status=(OUT_DIMUAT,), batas=200)

    hasil = HasilAutoTaut()
    for t in tiket:
        berat_tiket = float(t.get("berat_kg") or 0)
        tanggal_tiket = t.get("tanggal")
        nama_tiket = kunci(t.get("pihak"))
        if not nama_tiket or tanggal_tiket is None:
            continue

        cocok = []
        for rec, items in pesanan:
            if kunci(rec.nama_pembeli) != nama_tiket:
                continue
            if rec.tanggal != tanggal_tiket:
                continue
            dimuat = sum(float(i.berat_kg or 0) for i in items)
            if abs(berat_tiket - dimuat) > dimuat * 0.002:
                continue
            cocok.append(rec)

        if len(cocok) > 1:
            hasil.dilewati.append(
                f"{t['kode']}: cocok dengan {len(cocok)} pesanan sekaligus — ambigu")
            continue
        if len(cocok) == 0:
            continue

        try:
            rec2, _catatan = await verifikasi(
                db, user=user, rec_id=cocok[0].id, timbangan_transaksi_id=t["id"], otomatis=True)
            hasil.tertaut.append(f"{t['kode']} -> {rec2.kode}")
        except BarangKeluarError as e:
            hasil.dilewati.append(f"{t['kode']}: {e}")
    return hasil


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

    status = (await db.execute(text("SELECT status_tiket FROM timbangan_transaksi WHERE id=:id FOR UPDATE"),
                               {"id": int(tid)})).scalar_one_or_none()
    if status != "SELESAI":
        raise BarangKeluarError("Armada belum selesai timbang kedua; pengiriman belum bisa diverifikasi.")

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
    pergi.

    Yang begitu dibetulkan lewat PEMBATALAN INPUT TERAKHIR, satu langkah pada
    satu ketukan — lihat `balik_muat` & `balik_verifikasi` di bawah. Kalimat
    ini pernah menunjuk pintu yang belum ada: sampai 29 September 2026
    pembatalan input terakhir tak mengenal tabel ini sama sekali, jadi operator
    yang salah menekan "dimuat" atas dua ratus karung tak punya jalan mana pun.
    """
    sebab = (sebab or "").strip()
    if not sebab:
        raise BarangKeluarError(
            "Tulis sebabnya — perintah yang hilang tanpa kabar akan ditanyakan "
            "operator sepanjang hari.")
    rec = await _kunci(db, rec_id, keadaan=OUT_PERINTAH)
    dimuat = (await db.execute(select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .where(OutgoingItem.outgoing_record_id == rec.id))).scalar_one()
    if float(dimuat or 0) > 0.5:
        raise BarangKeluarError("Sudah ada barang dimuat. Batalkan pencatatan muatan dulu sebelum membatalkan perintah.")
    rec.status = OUT_BATAL
    rec.sebab_batal = sebab[:300]
    await _kabar(db, rec, untuk="operator", prioritas="merah",
                 pesan=f"🔴 Perintah muat {rec.kode} DIBATALKAN Admin — {sebab}")
    await _jejak(db, rec, langkah="batal", oleh=user,
                 ringkas=f"{rec.kode} dibatalkan — {sebab}")
    await db.commit()
    await db.refresh(rec)
    return rec


# ────────────── Jalan kembali: pembatalan input terakhir ──────────────
#
# SATU KETUKAN, SATU LANGKAH KEMBALI — dan ini bukan kenyamanan melainkan
# syarat rantainya. Seluruh sebab pemilik meminta langkah verifikasi Admin
# adalah supaya kesalahan TERTANGKAP; rantai yang bisa menangkap kesalahan
# tetapi tak bisa membetulkannya hanya memindahkan kekesalan dari gudang ke
# meja. Sampai 29 September 2026 memang begitu: `batalkan` menolak yang sudah
# dimuat (dan benar menolaknya — barangnya di atas truk), docstring-nya
# menunjuk pembatalan input terakhir, dan pembatalan input terakhir tak
# mengenal tabel ini sama sekali.
#
# SATU LANGKAH, BUKAN SELURUH TRANSAKSI. Tiap fungsi di sini membatalkan satu
# ketukan; yang hendak kembali dari `selesai` ke `perintah` menekannya dua
# kali, dan di antara dua ketukan itu ia melihat keadaan yang sesungguhnya.
# Satu tombol yang melompat langsung ke awal berarti pekerjaan tiga orang
# terhapus sekaligus, sementara yang menekan cuma membaca kalimat terakhirnya.
#
# TAK SATU PUN COMMIT DI SINI. Mereka dipanggil dari dalam transaksi
# pembatalan, yang pada ketukan yang sama menandai jejaknya `dibatalkan_pada`.
# Commit di tengah akan menutup separuh pekerjaan lalu membiarkan separuhnya
# menggantung ketika sisanya gagal.
#
# STOK TIDAK PERNAH DISENTUH LANGSUNG. Ia dihitung dari
# `outgoing_items.berat_kg`, jadi yang mengembalikan stok adalah angka baris
# itu — bukan satu pun penambahan di tabel stok. Sama seperti di jalur maju,
# dan justru itu yang membuat keduanya tak bisa berselisih.

#: Urutan langkah maju. Dipakai penolakan untuk tahu apakah yang diminta
#: BELUM waktunya (masih ada langkah di atasnya) atau SUDAH terlewat.
_URUT_LANGKAH = {OUT_PERINTAH: 0, OUT_DIMUAT: 1, OUT_SELESAI: 2}

#: Langkah yang harus dibatalkan lebih dulu, dalam kata yang dipakai layar.
_SEBUT_LANGKAH = {OUT_DIMUAT: "pencatatan muatnya", OUT_SELESAI: "verifikasinya"}


async def _kunci_untuk_balik(db: AsyncSession, rec_id: int, *, keadaan: str,
                             apa: str) -> OutgoingRecord:
    """Barisnya terkunci, dan keadaannya masih yang hendak dibatalkan.

    Kalimat penolakannya SENGAJA bukan `_kalimat_keadaan`. Yang dipakai langkah
    maju menyebut siapa yang mendahului ("sudah dimuat Rusdi"), sebab langkah
    berikutnya memang menanyai orang itu. Di sini pertanyaannya lain — "lalu
    saya harus apa" — jadi yang disebut adalah LANGKAH yang harus dibatalkan
    lebih dulu. Tanpa itu orang menekan tombol yang sama berkali-kali.
    """
    await _kunci_saldo_keluar(db)
    rec = (await db.execute(
        select(OutgoingRecord).where(OutgoingRecord.id == rec_id).with_for_update()
        .execution_options(populate_existing=True)
    )).scalars().first()
    if rec is None:
        raise BarangKeluarError("Transaksi barang keluar itu sudah tidak ada.")
    if rec.status == keadaan:
        return rec
    kini, minta = _URUT_LANGKAH.get(rec.status), _URUT_LANGKAH.get(keadaan)
    if kini is not None and minta is not None and kini > minta:
        raise BarangKeluarError(
            f"{rec.kode} sudah maju ke langkah berikutnya — batalkan "
            f"{_SEBUT_LANGKAH[rec.status]} dulu, baru {apa} bisa dibatalkan.")
    if kini is not None and minta is not None and kini < minta:
        raise BarangKeluarError(
            f"{rec.kode} sudah berada di langkah sebelumnya — {apa} "
            "sepertinya sudah dibatalkan.")
    if rec.status == OUT_BATAL:
        raise BarangKeluarError(
            f"{rec.kode} sudah dibatalkan"
            + (f" — {rec.sebab_batal}" if rec.sebab_batal else "") + ".")
    raise BarangKeluarError(
        f"{rec.kode} sudah tidak pada langkah itu — {apa} tak bisa "
        "dibatalkan lagi.")


async def _nama_baris(db: AsyncSession, it: OutgoingItem) -> str:
    """Nama barang satu baris, memakai ATURAN PENAMAAN YANG SAMA dengan layar.

    Lewat `tersedia()` meski stoknya tak dibutuhkan: nama barang yang disusun
    ulang di sini akan berbeda dari yang tertulis di kartunya, dan pesan
    pembatalan yang menyebut nama lain dari yang dilihat orang membuat orang
    itu ragu barang mana yang barusan ia kembalikan.
    """
    return (await tersedia(db, baris_dari_item(it),
                           abaikan_pesanan=True))[1]


async def balik_perintah(db: AsyncSession, *, rec_id: int) -> str:
    """Tarik penerbitan perintahnya.

    Stok tak pernah berkurang di langkah ini, jadi tak ada angka yang perlu
    dipulihkan. Yang perlu adalah operator TAHU tugasnya hangus — perintah yang
    lenyap dari antrean tanpa kabar akan ditanyakan sepanjang hari, dan
    ditanyakan kepada orang yang tak menekan apa pun.

    Barisnya ditandai `batal`, TIDAK dihapus. Ia sudah pernah terlihat di layar
    operator dan sudah pernah berkabar; menghapusnya berarti kabar yang merujuk
    transaksi yang tak ada lagi.
    """
    rec = await _kunci_untuk_balik(db, rec_id, keadaan=OUT_PERINTAH,
                                   apa="penerbitan perintahnya")
    rec.status = OUT_BATAL
    rec.sebab_batal = "Penerbitannya ditarik lewat pembatalan input terakhir."
    await _kabar(db, rec, untuk="operator", prioritas="merah",
                 pesan=f"🔴 Perintah muat {rec.kode} DITARIK — penerbitannya "
                       "dibatalkan lewat pembatalan input terakhir. Jangan "
                       "dimuat.")
    return (f"✓ Dibatalkan: penerbitan perintah {rec.kode} — belum dimuat, "
            "jadi stok tak berubah sedikit pun.")


async def balik_muat_baris(db: AsyncSession, *, rec_id: int, item_id: int,
                           berat_lama: float, karung_lama: int | None) -> str:
    """Kembalikan satu baris ke angka SEBELUM ketukan itu.

    Ke angka sebelumnya, bukan ke nol — lihat cuplikan di `_jejak`. Baris yang
    dicatat 300 karung lalu diperbaiki jadi 280 harus kembali ke 300.
    """
    rec = await _kunci_untuk_balik(db, rec_id, keadaan=OUT_PERINTAH,
                                   apa="pencatatan baris itu")
    it = await db.get(OutgoingItem, item_id)
    if it is None or it.outgoing_record_id != rec.id:
        raise BarangKeluarError(
            "Baris barang itu sudah tidak ada di perintahnya.")
    nama = await _nama_baris(db, it)
    it.berat_kg = berat_lama
    it.jumlah_karung = karung_lama
    return (f"✓ Dibatalkan: pencatatan muat {nama} pada {rec.kode} — "
            f"kembali ke {_kg(berat_lama)} kg, stoknya pulih.")


async def balik_muat(db: AsyncSession, *, rec_id: int, diisi: list[int],
                     cuplikan: dict | None = None) -> str:
    """Buka kembali transaksi yang barusan dinyatakan DIMUAT.

    Dua hal dikembalikan, dan yang kedua paling mudah terlewat:

      · keadaannya → `perintah`, siapa-kapan memuatnya → kosong. Kartunya
        kembali berdiri di antrean operator;
      · baris yang DIISI OLEH KETUKAN ITU → nol lagi, sehingga stoknya pulih.
        Yang sudah dicatat operator per baris lebih dulu TIDAK disentuh: itu
        ketukan lain dengan jalan kembalinya sendiri, dan menol-kannya di sini
        berarti satu pembatalan menghapus dua pencatatan yang berbeda — yang
        kedua tanpa diminta siapa pun.

    Karena itu `diisi` datang dari jejaknya, bukan dihitung ulang di sini: saat
    pembatalan dijalankan, kedua macam baris sama-sama berisi angka, dan tak
    ada cara membedakannya lagi selain cuplikan yang ditulis saat itu.
    """
    rec = await _kunci_untuk_balik(db, rec_id, keadaan=OUT_DIMUAT,
                                   apa="pencatatan muatnya")
    rec.status = OUT_PERINTAH
    rec.dimuat_oleh, rec.waktu_muat = None, None
    n = 0
    for item_id in diisi:
        it = await db.get(OutgoingItem, item_id)
        if it is None or it.outgoing_record_id != rec.id:
            continue
        berat, karung = (cuplikan or {}).get(str(item_id), (0, None))
        it.berat_kg, it.jumlah_karung = berat, karung
        n += 1
    await _kabar(db, rec, untuk="admin",
                 pesan=f"🔁 {rec.kode} dibuka lagi — pencatatan muatnya "
                       "dibatalkan, dan kartunya kembali ke antrean operator.")
    return ("✓ Dibatalkan: pencatatan muat " + rec.kode
            + (f" — {n} baris kembali ke jumlah sebelumnya, stoknya pulih."
               if n else " — kembali ke antrean muat; angka per barisnya "
                         "tetap, sebab bukan ketukan ini yang mengisinya."))


async def balik_verifikasi(db: AsyncSession, *, rec_id: int) -> str:
    """Buka kembali transaksi yang sudah diverifikasi Admin.

    STOK TAK BERGERAK SEDIKIT PUN di sini, dan itu bukan kelalaian: barangnya
    berpindah saat DIMUAT, bukan saat diverifikasi. Yang dikembalikan keadaan
    dan tautan tiketnya.

    TIKETNYA DILEPAS, sebab ketukan verifikasi itulah yang menempelkannya.
    Membiarkannya menempel pada transaksi yang keadaannya sudah bukan
    `selesai` membuat tiket itu tetap terhitung terpakai oleh indeks uniknya —
    jadi tiket yang benar tak bisa ditempel ke transaksi mana pun, dan tak ada
    satu layar yang bisa menjelaskan sebabnya.
    """
    rec = await _kunci_untuk_balik(db, rec_id, keadaan=OUT_SELESAI,
                                   apa="verifikasinya")
    rec.status = OUT_DIMUAT
    rec.diverifikasi_oleh, rec.waktu_verifikasi = None, None
    ada_tiket = rec.timbangan_transaksi_id is not None
    rec.timbangan_transaksi_id = None
    # Tanda selisih besar ikut dicabut: ia lahir dari perbandingan dengan
    # tiket yang barusan dilepas. Tanda yang tertinggal tanpa tiketnya adalah
    # tuduhan atas selisih yang tak bisa ditunjukkan lagi kepada siapa pun.
    rec.sebab_selisih = None
    await _kabar(db, rec, untuk="admin",
                 pesan=f"🔁 Verifikasi {rec.kode} dibatalkan — kartunya kembali "
                       "menunggu verifikasi"
                       + (", dan kode timbangnya dilepas." if ada_tiket else "."))
    return (f"✓ Dibatalkan: verifikasi {rec.kode} — kembali menunggu "
            "verifikasi Admin"
            + (", kode timbangnya dilepas dan bisa dipakai lagi."
               if ada_tiket else ", stok tak berubah."))


async def balik_batal(db: AsyncSession, *, rec_id: int) -> str:
    """Hidupkan kembali perintah yang barusan dibatalkan.

    Kembali ke `perintah`, sebab `batalkan` hanya berlaku dari sana — tak ada
    keadaan lain yang perlu ditebak.

    SATU PENOLAKAN, dan sebabnya di luar transaksi ini: kalau tiketnya sudah
    dipakai transaksi lain yang hidup, menghidupkan yang ini akan membuat satu
    tiket timbang dipakai dua transaksi. Indeks uniknya memang akan menolak,
    tetapi penolakan di tingkat basis data sampai ke orang sebagai galat tanpa
    sebab; yang ditolak di sini menyebut kode yang memakainya.
    """
    rec = await _kunci_untuk_balik(db, rec_id, keadaan=OUT_BATAL,
                                   apa="pembatalannya")
    if rec.timbangan_transaksi_id is not None:
        bentrok = (await db.execute(
            select(OutgoingRecord.kode).where(
                OutgoingRecord.timbangan_transaksi_id
                == rec.timbangan_transaksi_id,
                OutgoingRecord.status != OUT_BATAL,
                OutgoingRecord.id != rec.id).limit(1))).scalars().first()
        if bentrok:
            raise BarangKeluarError(
                f"Kode timbang pada {rec.kode} kini dipakai {bentrok} — "
                "pembatalannya tak bisa ditarik tanpa membuat satu tiket "
                "timbang dipakai dua transaksi.")
    rec.status = OUT_PERINTAH
    rec.sebab_batal = None
    await _kabar(db, rec, untuk="operator",
                 pesan=f"🟡 Perintah muat {rec.kode} HIDUP LAGI — "
                       "pembatalannya ditarik. Kartunya kembali di Antrian "
                       "tunggu.")
    return (f"✓ Dibatalkan: pembatalan perintah {rec.kode} — kembali ke "
            "antrean muat operator.")


# ────────────────────────────── Pembacaan ──────────────────────────────

async def daftar(db: AsyncSession, *, status: tuple[str, ...] | None = None,
                 batas: int = 50, transaksi_id: int | None = None,
                 sebelum_id: int | None = None, pencarian: str = "", sejak=None) -> list[tuple[OutgoingRecord, list[OutgoingItem]]]:
    """Transaksi barang keluar beserta isinya — untuk halaman & kartunya."""
    q = select(OutgoingRecord).order_by(OutgoingRecord.id.desc()).limit(batas)
    if pencarian:
        from sqlalchemy import or_
        pola = "%" + pencarian.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.where(or_(*(kol.ilike(pola, escape="\\") for kol in
                          (OutgoingRecord.kode, OutgoingRecord.nama_pembeli, OutgoingRecord.no_polisi))))
    if sejak:
        from datetime import datetime, time
        q = q.where(OutgoingRecord.waktu_perintah >= datetime.combine(sejak, time.min))
    if status:
        q = q.where(OutgoingRecord.status.in_(status))
    if transaksi_id is not None:
        q = q.where(OutgoingRecord.id == transaksi_id)
    if sebelum_id is not None:
        q = q.where(OutgoingRecord.id < sebelum_id)
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
