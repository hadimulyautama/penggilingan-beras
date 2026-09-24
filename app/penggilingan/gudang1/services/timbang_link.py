"""Jembatan baca-only ke sistem TIMBANGAN (aplikasi terpisah, DB terintegrasi).

Model `timbangan_transaksi` dimiliki repo timbangan; di sini kita hanya MEMBACA lewat
SQL mentah pada DB yang sama. Dipakai intake produksi untuk menaut batch ke tiket timbang
(operator memilih tiket aktif, bukan mengetik bobot/supplier).

Sumber kebenaran: bobot/supplier/nopol dari timbang. Bobot:
  netto_timbangan_kg = bermuatan − kosong (TRUKNYA, bukan barangnya)
  berat_barang_kg    = netto − tara karung & tara lain (BARANGNYA)
  berat_acuan_kg     = bobot NOTA/surat jalan (opsional)
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import berzona
from app.penggilingan.gudang1.services.bobot import (
    MUATAN_MAKS_X_TARA, SQL_NORM_NOPOL, SUMBER_MENUNGGU, SUMBER_PERKIRAAN,
    UMUR_TARA_HARI, norm_nopol, perkiraan)

# Tiket MASUK yang BELUM ditaut batch mana pun — apa pun status tiketnya.
#
# Dulu hanya yang berstatus TERBUKA. Itu cocok dengan alur normal: truk
# ditimbang bermuatan, operator memilih tujuannya, truk membongkar ke tujuan
# itu, lalu ditimbang lagi dan tiketnya tertutup. Pencatatan intake memang
# terjadi di antara dua penimbangan itu.
#
# Tetapi bila operator terlambat — truk sudah pergi, tiket sudah tertutup —
# tiketnya HILANG dari daftar, dan gabahnya tidak punya jalan masuk sama
# sekali sejak jalur manual dicabut. Rekonsiliasi sudah lama melaporkan tiket
# semacam itu sebagai "belum tertaut"; yang belum ada adalah cara
# menyelesaikannya dari layar operator. Sekarang ada.
#
# Yang tertutup diberi tanda `susulan` supaya di layar terlihat bahwa ini
# menambal yang terlewat, bukan pekerjaan yang sedang berjalan.
#: Syarat "tiket ini SAH dipakai produksi" — satu tempat, dipakai semua kueri.
#:
#: Kata `status_transaksi` tak pernah muncul sama sekali di kode produksi
#: sampai 11 September 2026. Akibatnya tiket yang sudah DIBATALKAN di Pos
#: Timbang tetap ditawarkan untuk ditautkan, tetap bisa jadi batch, dan
#: pollernya tetap menyalin berat notanya ke stok. Truk yang DITOLAK dan
#: tiketnya ditutup paksa pun mendorong 9.800 kg masuk pembukuan.
#:
#: Temuan QA T-02 & X-07. Ditulis sekali di sini karena syarat yang disalin
#: ke lima kueri akan tertinggal di salah satunya pada perubahan berikutnya —
#: dan yang tertinggal justru jadi satu-satunya pintu yang terbuka.
SYARAT_TIKET_SAH = """
       AND t.status_transaksi = 'AKTIF'
       AND t.status_tiket <> 'DITUTUP_PAKSA'
"""

#: Berapa kg BARANGNYA menurut Pos Timbang — satu tempat, dipakai semua kueri.
#:
#: `netto_timbangan_kg` adalah berat TRUKNYA (bermuatan − kosong). Tara karung
#: dan tara lain dipotong sesudah itu, dan hasilnya disimpan Pos Timbang di
#: `berat_barang_kg` (`timbangan/logic.py`: `barang = netto - total_tara`).
#: Pos Timbang pula yang membandingkan NOTA dengan BARANG, bukan dengan netto.
#:
#: Sampai 24 September 2026 produksi tak pernah membaca kolom itu sama sekali —
#: `berat_barang_kg` muncul tepat SATU kali di seluruh repo ini, di data contoh
#: mode uji. Maka 200 karung × 0,25 kg = 50 kg tara karung tidak pernah
#: dipotong: Pos Timbang menyebut 9.950 kg, produksi mencatat 10.000 kg.
#: Itulah keluhan pemilik 21 September 2026 ("di timbangan 9.950, di produksi
#: ±10.240") dan QA 24 September (c) butir 2b.
#:
#: Urutannya sama dengan yang sudah berlaku untuk nota: NOTA menang bila ada
#: (keputusan yang sudah berdiri), lalu BARANG, dan netto tinggal cadangan
#: untuk tiket lama yang belum punya snapshot barangnya. Nol berarti "tak ada
#: angkanya", bukan "nol kilo" — alasan yang sama dengan nota.
SQL_BERAT_TIKET = ("COALESCE(NULLIF(t.berat_acuan_kg, 0), "
                   "NULLIF(t.berat_barang_kg, 0), t.netto_timbangan_kg)")

_SQL_AKTIF = text("""
    SELECT t.id, t.kode, t.jenis_kode, j.nama AS jenis_nama,
           t.tanggal, t.timbang1_waktu, t.nomor_polisi, t.nama_sopir,
           t.supplier_id, s.nama_supplier, t.pihak_nama,
           t.netto_timbangan_kg, t.berat_barang_kg, t.berat_acuan_kg,
           t.selisih_kg, t.selisih_persen,
           t.timbang1_kg, t.berat_kosong_kg,
           t.status_kontrol, t.status_tiket
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
      -- Nama komoditas DIBACA dari tabel jenis, bukan diterjemahkan dari
      -- kodenya di sisi produksi. Tiket adalah kunci asing ke proses timbang,
      -- dan proses timbang sudah memegang komoditas yang disandangnya —
      -- menyusun ulang namanya di sini berarti dua sebutan untuk satu barang,
      -- dan yang di sini yang akan basi saat namanya diubah di sana.
      LEFT JOIN timbangan_jenis j ON j.kode = t.jenis_kode
     WHERE t.arah = 'MASUK'""" + SYARAT_TIKET_SAH + """
       AND t.status_tiket IN ('TERBUKA', 'SELESAI')
       -- Yang sudah ditutup hanya ditawarkan selama beberapa hari.
       --
       -- Tanpa batas ini, pabrik yang timbangannya sudah lama jalan sementara
       -- produksi belum dipakai akan menampilkan SELURUH riwayat tiketnya —
       -- dan pekerjaan hari ini terkubur di antara ratusan tiket lama.
       -- Yang benar-benar tertinggal bukan urusan layar harian: ia sudah
       -- dilaporkan rekonsiliasi sebagai "belum tertaut".
       AND (t.status_tiket = 'TERBUKA'
            OR t.tanggal >= CURRENT_DATE - CAST(:hari AS integer))
       -- cermin bertanda: pencatatan yang dibatalkan tak lagi menaut tiketnya
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL AND dibatalkan_pada IS NULL)
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM pk_purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL AND dibatalkan_pada IS NULL)
     ORDER BY (t.status_tiket = 'TERBUKA') DESC, t.tanggal DESC, t.id DESC
""")

_SQL_SATU = text("""
    SELECT t.id, t.kode, t.arah, t.jenis_kode, j.nama AS jenis_nama,
           t.tanggal, t.timbang1_waktu, t.nomor_polisi, t.nama_sopir,
           t.supplier_id, s.nama_supplier, t.pihak_nama,
           t.netto_timbangan_kg, t.berat_barang_kg, t.berat_acuan_kg,
           t.selisih_kg, t.selisih_persen,
           t.timbang1_kg, t.berat_kosong_kg,
           t.status_kontrol, t.status_tiket
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
      LEFT JOIN timbangan_jenis j ON j.kode = t.jenis_kode
     WHERE t.id = :tid""" + SYARAT_TIKET_SAH + """
""")


def _row(r) -> dict:
    d = dict(r._mapping)
    # Basis bobot untuk HPP — bentuk Python dari `SQL_BERAT_TIKET`, dan
    # urutannya wajib sama: nota, lalu BARANG (netto dikurangi tara karung),
    # lalu netto sebagai cadangan. Dua urutan berbeda untuk satu pertanyaan
    # berarti layar dan poller menyebut angka berbeda tentang truk yang sama.
    nota = d.get("berat_acuan_kg")
    barang = d.get("berat_barang_kg")
    real = d.get("netto_timbangan_kg")
    ada_nota = nota is not None and float(nota or 0) > 0
    ada_barang = barang is not None and float(barang or 0) > 0
    d["susulan"] = d.get("status_tiket") == "SELESAI"
    d["sumber_berat"] = "nota" if ada_nota else "timbangan"
    if ada_nota:
        d["berat_hpp_kg"] = float(nota)
    elif ada_barang:
        d["berat_hpp_kg"] = float(barang)
    else:
        d["berat_hpp_kg"] = float(real) if real is not None else None
    return d


#: Berapa hari ke belakang tiket yang SUDAH DITUTUP masih boleh disusulkan.
#: Cukup panjang untuk menutupi akhir pekan dan libur, cukup pendek supaya
#: daftar tetap bisa dibaca sambil berdiri.
HARI_SUSULAN = 7


async def tiket_masuk_aktif(db: AsyncSession, jenis_kode: str | None = None) -> list[dict]:
    """Daftar tiket timbang MASUK yang belum tertaut, untuk dipilih operator.

    Yang masih TERBUKA selalu masuk — itu pekerjaan yang sedang berjalan.
    Yang sudah ditutup hanya beberapa hari ke belakang; selebihnya urusan
    rekonsiliasi, bukan urusan layar harian.
    """
    rows = (await db.execute(_SQL_AKTIF, {"hari": HARI_SUSULAN})).all()
    out = [_row(r) for r in rows]
    if jenis_kode:
        out = [d for d in out if d["jenis_kode"] == jenis_kode]
    return out


async def ambil_tiket(db: AsyncSession, tid: int) -> dict | None:
    """Ambil satu tiket timbang (untuk membentuk batch)."""
    r = (await db.execute(_SQL_SATU, {"tid": tid})).first()
    return _row(r) if r else None


# ── Tara truk yang sama: dasar PERKIRAAN bobot sebelum timbang kedua ──
#
# Keputusan pemilik 21 September 2026 (QA P6, Pilihan A): "tara cenderung
# stabil". Tiap tiket SELESAI menyimpan `berat_kosong_kg`; untuk truk yang
# baru ditimbang bermuatan, bobot perkiraan = timbang pertama − berat kosong
# terakhir nomor polisi yang sama. Nomor polisinya dinormalkan (huruf besar,
# tanpa spasi) karena orang mengejanya dengan spasi berbeda-beda.
#
# Truk yang belum pernah punya tara → None: bobotnya "tak diketahui", bukan
# tebakan (Pilihan B, cadangan).
#
# BATAS UMUR (QA 24 September 2026 (c) butir 2c). Sampai hari itu kueri ini
# menuntut dua hal saja — `berat_kosong_kg > 0` dan tiket SELESAI — jadi tara
# dari kapan pun dipakai apa adanya, tanpa batas umur dan tanpa batas
# kewajaran. "Tara cenderung stabil" berlaku dari muatan ke muatan; tara bulan
# lalu bukan pengetahuan tentang truk hari ini, dan tebakan yang salah di sini
# tidak terlihat salah — ia berupa angka yang masuk akal.
#
# Arahnya TIDAK diperiksa, dan itu bukan kelalaian: `berat_kosong_kg` adalah
# berat truk kosong pada arah mana pun — Pos Timbang sendiri yang memilah bruto
# dan tara menurut arah saat menyimpan (`logic.timbang_pertama_bermuatan`).
# Tiket keluar yang sudah selesai memberi tara yang sama sahnya.
_NORM_K = SQL_NORM_NOPOL.format(kolom="k.nomor_polisi")
_SQL_TARA = text(f"""
    SELECT k.berat_kosong_kg
      FROM timbangan_transaksi k
     WHERE {_NORM_K} = :nopol
       AND k.berat_kosong_kg IS NOT NULL AND k.berat_kosong_kg > 0
       AND k.status_tiket = 'SELESAI' AND k.status_transaksi = 'AKTIF'
       AND k.id <> COALESCE(:kecuali, -1)
       AND COALESCE(k.timbang2_waktu, k.timbang1_waktu)
           >= now() - make_interval(days => {UMUR_TARA_HARI})
     ORDER BY COALESCE(k.timbang2_waktu, k.timbang1_waktu) DESC NULLS LAST, k.id DESC
     LIMIT 1
""")


async def tara_terakhir(db: AsyncSession, nopol: str | None, *, kecuali: int | None = None) -> float | None:
    """Berat kosong terakhir truk bernomor polisi ini (tiket selesai mana pun)."""
    n = norm_nopol(nopol)
    if not n:
        return None
    v = (await db.execute(_SQL_TARA, {"nopol": n, "kecuali": kecuali})).scalar()
    return float(v) if v is not None else None


async def bobot_awal_dari_tiket(db: AsyncSession, tiket: dict) -> tuple[float | None, str, float | None]:
    """(berat, sumber_berat, berat_perkiraan) untuk batch yang lahir dari tiket.

    Tiga keadaan, bukan dua: nota/netto → pasti; belum ditimbang kedua tetapi
    truknya punya tara → perkiraan (disimpan di keduanya, supaya selisihnya
    kelak bisa diuji); selebihnya → menunggu, bobot NULL.
    """
    b = tiket.get("berat_hpp_kg")
    if b is not None and float(b) > 0:
        return float(b), tiket["sumber_berat"], None
    tara = await tara_terakhir(db, tiket.get("nomor_polisi"), kecuali=tiket.get("id"))
    p = perkiraan(tiket.get("timbang1_kg"), tara)
    if p is not None:
        return p, SUMBER_PERKIRAAN, p
    return None, SUMBER_MENUNGGU, None


async def berat_kotor_tiket(db: AsyncSession, tid: int | None) -> float | None:
    """Timbang pertama (truk bermuatan) — batas ATAS bobot barangnya. Dipakai
    pagar kapasitas untuk truk yang belum ditimbang kedua: yang muat dengan
    berat kotornya pasti muat dengan nettonya (QA P6-04)."""
    if tid is None:
        return None
    v = (await db.execute(text(
        "SELECT timbang1_kg FROM timbangan_transaksi WHERE id = :tid"), {"tid": tid})).scalar()
    return float(v) if v is not None else None


# Isi bobot batch yang MASIH 'menunggu' dari tiket-nya, begitu tiket punya bobot
# (nota atau netto timbang). Bobot efektif = nota bila ada, selain itu netto real.
_SQL_SINKRON = """
    UPDATE {tbl} b SET
        berat_total_kg = """ + SQL_BERAT_TIKET + """,
        sumber_berat   = CASE WHEN COALESCE(t.berat_acuan_kg, 0) > 0
                              THEN 'nota' ELSE 'timbangan' END
      FROM timbangan_transaksi t
     WHERE b.timbangan_transaksi_id = t.id
       AND b.dibatalkan_pada IS NULL          -- cermin bertanda
       -- 'perkiraan' ikut: netto sungguhan mengganti perkiraan lewat jalur
       -- yang SAMA dengan 'menunggu'. `berat_perkiraan_kg` tak disentuh —
       -- selisihnya itulah yang kelak menguji anggapan "tara stabil".
       AND b.sumber_berat IN ('menunggu', 'perkiraan')
""" + SYARAT_TIKET_SAH + """       AND """ + SQL_BERAT_TIKET + """ IS NOT NULL
"""


async def sinkron_bobot_menunggu(db: AsyncSession) -> int:
    """Isi bobot semua batch (gabah & PK) yang 'menunggu' dari tiket timbang-nya.
    → jumlah baris terisi. Idempoten: yang sudah terisi tak disentuh."""
    total = 0
    for tbl in ("purchase_batches", "pk_purchase_batches"):
        res = await db.execute(text(_SQL_SINKRON.format(tbl=tbl)))
        total += res.rowcount or 0
    await db.commit()
    return total


# Isi PERKIRAAN untuk batch yang masih 'menunggu' tetapi truknya punya tara.
# Berlaku juga untuk batch yang sudah ada sebelum perbaikan ini (mis. truk
# yang sedang antre timbang saat kode ini terpasang) — tak ada yang perlu
# dicatat ulang. Sama dengan `bobot_awal_dari_tiket`, dalam bentuk himpunan.
_NORM_T = SQL_NORM_NOPOL.format(kolom="t.nomor_polisi")
_SQL_PERKIRAAN = """
    UPDATE {tbl} b SET
        berat_total_kg     = t.timbang1_kg - k.berat_kosong_kg,
        berat_perkiraan_kg = t.timbang1_kg - k.berat_kosong_kg,
        sumber_berat       = 'perkiraan'
      FROM timbangan_transaksi t
      JOIN LATERAL (
            SELECT k.berat_kosong_kg
              FROM timbangan_transaksi k
             WHERE """ + _NORM_K + """ = """ + _NORM_T + """
               AND k.id <> t.id
               AND k.berat_kosong_kg IS NOT NULL AND k.berat_kosong_kg > 0
               AND k.status_tiket = 'SELESAI' AND k.status_transaksi = 'AKTIF'
               -- Batas umur & kewajaran yang SAMA dengan `bobot.perkiraan` dan
               -- `_SQL_TARA`. Poller yang lebih longgar akan menambal kembali
               -- perkiraan yang baru saja ditolak jalur satu-satu — dan yang
               -- menang adalah yang menulis paling akhir.
               AND COALESCE(k.timbang2_waktu, k.timbang1_waktu)
                   >= now() - make_interval(days => 30)
             ORDER BY COALESCE(k.timbang2_waktu, k.timbang1_waktu) DESC NULLS LAST, k.id DESC
             LIMIT 1) k ON true
     WHERE b.timbangan_transaksi_id = t.id
       AND b.dibatalkan_pada IS NULL          -- cermin bertanda
       AND b.sumber_berat = 'menunggu'
""" + SYARAT_TIKET_SAH + """       AND """ + SQL_BERAT_TIKET + """ IS NULL
       AND t.timbang1_kg - k.berat_kosong_kg > 0
       AND t.timbang1_kg - k.berat_kosong_kg
           <= 4.0 * k.berat_kosong_kg
"""


# ── Timbang kedua HARI INI pada tiket yang belum ditutup ──
#
# QA 21 September 2026 (d), laporan pemilik 21:00. Pos Timbang punya dua
# tombol timbang kedua untuk barang masuk: "Simpan sementara" (jumlah karung
# belum diketahui — `timbang2_kg` disimpan, netto sengaja TIDAK dihitung,
# tiket tetap TERBUKA, bisa berjam-jam sampai bongkar rampung) dan "Selesai".
# Selama itu produksi memegang perkiraan dari tara LAMA (atau NULL untuk truk
# baru) padahal berat kosong truk HARI INI sudah ditimbang.
#
# Angkanya = bermuatan − kosong: rumus netto Pos Timbang sendiri
# (`logic.hitung`; tara karung & tara lain masuk ke berat_barang, BUKAN ke
# netto), jadi sama persis dengan `netto_timbangan_kg` yang kelak dihasilkan
# tombol Selesai. Untuk tiket MASUK / TRANSFER / RETUR_MASUK timbang pertama
# yang bermuatan (`logic.timbang_pertama_bermuatan`); batch intake hanya
# lahir dari tiket MASUK, dan syaratnya ditulis eksplisit supaya tiket
# keluar tak pernah terbalik dihitung.
#
# Tetap 'perkiraan' dan tetap belum final: tiketnya memang belum ditutup dan
# masih bisa dikoreksi. `berat_perkiraan_kg` (dari tara) TIDAK ditimpa —
# dialah yang menguji anggapan "tara stabil" di rekonsiliasi butir ⑨.
# Hanya DUA_KALI: partai menjumlah karung, sekali tak punya timbang kosong.
_SQL_PERKIRAAN_TIKET = """
    UPDATE {tbl} b SET
        berat_total_kg = t.timbang1_kg - t.timbang2_kg,
        sumber_berat   = 'perkiraan'
      FROM timbangan_transaksi t
     WHERE b.timbangan_transaksi_id = t.id
       AND b.dibatalkan_pada IS NULL          -- cermin bertanda
       AND b.sumber_berat IN ('menunggu', 'perkiraan')
""" + SYARAT_TIKET_SAH + """       AND t.status_tiket = 'TERBUKA'
       AND t.arah IN ('MASUK', 'TRANSFER', 'RETUR_MASUK')
       AND t.cara_timbang = 'DUA_KALI'
       AND t.timbang2_kg IS NOT NULL
       AND """ + SQL_BERAT_TIKET + """ IS NULL
       AND t.timbang1_kg - t.timbang2_kg > 0
       AND b.berat_total_kg IS DISTINCT FROM (t.timbang1_kg - t.timbang2_kg)
"""


async def sinkron_perkiraan(db: AsyncSession) -> int:
    """Beri bobot perkiraan pada batch yang belum punya netto sungguhan.

    Dua sumber, dan urutannya berarti: TARA truk yang sama untuk yang masih
    'menunggu', lalu TIMBANG KEDUA HARI INI menimpa keduanya bila tiketnya
    sudah punya `timbang2_kg` tetapi belum ditutup — angka timbangan menang
    atas tebakan. → jumlah baris. Dijalankan SEBELUM `sinkron_bobot_menunggu`
    di poller: yang sudah punya netto tak pernah sampai ke sini (IS NULL),
    dan yang barusan diberi perkiraan langsung boleh diganti netto di langkah
    berikutnya.
    """
    total = 0
    for tbl in ("purchase_batches", "pk_purchase_batches"):
        res = await db.execute(text(_SQL_PERKIRAAN.format(tbl=tbl)))
        total += res.rowcount or 0
        res = await db.execute(text(_SQL_PERKIRAAN_TIKET.format(tbl=tbl)))
        total += res.rowcount or 0
    await db.commit()
    return total


# RE-SINKRON saat tiket DIREVISI (mis. petugas timbang mengoreksi bobot setelah batch
# dibuat & tersinkron). AMAN hanya bila batch BELUM diverifikasi harga (flag_unverified
# → tak ada nilai finansial beku) DAN (gabah) belum digiling (rendemen giling memakai
# snapshot bobot sendiri, jadi tak terpengaruh). Batch yang SUDAH terverifikasi / digiling
# TIDAK diubah otomatis — dilaporkan di rekonsiliasi ("bobot tiket berubah") untuk ditinjau.
_SQL_RESINKRON = """
    UPDATE {tbl} b SET
        berat_total_kg = """ + SQL_BERAT_TIKET + """,
        sumber_berat   = CASE WHEN COALESCE(t.berat_acuan_kg, 0) > 0
                              THEN 'nota' ELSE 'timbangan' END
      FROM timbangan_transaksi t
     WHERE b.timbangan_transaksi_id = t.id
       AND b.dibatalkan_pada IS NULL          -- cermin bertanda
       AND b.sumber_berat IN ('nota', 'timbangan')     -- sudah pernah sinkron dari timbang
""" + SYARAT_TIKET_SAH + """       -- Satu-satunya yang MEMBEKUKAN bobot: harga sudah diverifikasi.
       -- Sesudah itu ada angka rupiah yang berdiri di atas bobot ini, dan
       -- mengubahnya diam-diam membuat nilai pembelian tak lagi cocok dengan
       -- apa pun. Yang begitu diperbaiki lewat verifikasi ulang, bukan lewat
       -- poller.
       --
       -- Status prosesnya TIDAK lagi membekukan. Dulu batch yang sedang
       -- digiling dilewati, dan akibatnya persis kebalikan dari yang
       -- diinginkan: justru muatan yang sedang dikerjakan itulah yang paling
       -- sering direvisi notanya, dan revisinya tak pernah sampai.
       AND b.flag_unverified = true                     -- belum ada harga → tak ada nilai beku
       {extra}
       AND """ + SQL_BERAT_TIKET + """ IS NOT NULL
       AND b.berat_total_kg IS DISTINCT FROM
           """ + SQL_BERAT_TIKET + """
"""


async def resinkron_bobot_berubah(db: AsyncSession) -> int:
    """Perbarui bobot batch yang tiketnya DIREVISI di aplikasi timbangan.

    Berlaku pada batch yang masih DALAM PROSES — di dryer, di silo, dan pada
    giling yang sedang berjalan. Timbangan yang menimbang, jadi timbangan pula
    yang membetulkan; satu angka yang bisa berbeda di dua tempat membuat
    pertanyaan "yang mana yang benar" tak punya jawaban lagi.

    Dua hal membekukannya, dan keduanya berarti "sudah terlanjur dipakai":
    harga yang sudah diverifikasi (ada rupiah berdiri di atasnya), dan gabah
    yang sudah tergiling (beratnya kini riwayat, dan angkanya sudah masuk
    laporan).

    Idempoten (`IS DISTINCT FROM`), jadi aman dijalankan tiap tiga menit.
    """
    total = 0
    # Dua hal saja yang MEMBEKUKAN bobot, dan keduanya berarti "sudah
    # terlanjur dipakai":
    #   · harga sudah diverifikasi — ada angka rupiah berdiri di atasnya;
    #   · gabahnya sudah TERGILING — beratnya kini riwayat, dan proses giling
    #     yang sudah ditutup angkanya sudah masuk laporan (alasan yang sama
    #     dengan batas 48 jam pada pembatalan).
    #
    # Yang TIDAK lagi membekukan: sedang di dryer, sedang di silo, dan sedang
    # digiling. Dulu ketiganya ikut terhalang, dan akibatnya persis kebalikan
    # dari yang diinginkan — justru muatan yang sedang dikerjakan itulah yang
    # paling sering direvisi notanya, dan revisinya tak pernah sampai.
    for tbl, extra in (("purchase_batches", "AND b.status_batch <> 'digiling'"),
                       ("pk_purchase_batches", "")):
        res = await db.execute(text(_SQL_RESINKRON.format(tbl=tbl, extra=extra)))
        total += res.rowcount or 0
    await db.commit()
    return total


class TiketSudahDipakai(Exception):
    """Tiket timbang sudah ditaut batch lain (gabah atau PK)."""


_SQL_KUNCI_TIKET = text("SELECT id FROM timbangan_transaksi WHERE id = :tid FOR UPDATE")

#: Siapa, kapan, dan jadi batch apa. Ketiganya ikut ke pesan penolakan.
#:
#: "Tiket ini sudah ditautkan ke batch lain" benar tetapi tak menolong: yang
#: ingin diketahui orang yang baru saja ditolak adalah apakah rekannya sudah
#: mencatatnya — dan kalau ya, ke mana. Tanpa itu ia akan membuka tiketnya
#: lagi, atau bertanya lewat telepon. Temuan QA UI-02.
_SQL_PEMAKAI_TIKET = text("""
    SELECT lingkup, kode_batch, oleh, waktu FROM (
      SELECT 'gabah' AS lingkup, b.kode_batch, u.nama AS oleh,
             b.waktu_pembelian AS waktu
        FROM purchase_batches b
        LEFT JOIN users u ON u.id = b.input_by
       WHERE b.timbangan_transaksi_id = :tid AND b.dibatalkan_pada IS NULL
      UNION ALL
      SELECT 'PK', b.kode_batch, u.nama, b.waktu_pembelian
        FROM pk_purchase_batches b
        LEFT JOIN users u ON u.id = b.input_by
       WHERE b.timbangan_transaksi_id = :tid AND b.dibatalkan_pada IS NULL
    ) x
""")


async def kunci_tiket_untuk_ditaut(db: AsyncSession, tid: int) -> None:
    """Kunci tiket lalu pastikan belum dipakai batch mana pun. → `TiketSudahDipakai`.

    UNIQUE pada `timbangan_transaksi_id` hanya berlaku DI DALAM satu tabel.
    Tiket yang sama karenanya bisa jadi batch gabah DAN batch PK sekaligus:
    dua operator memilih tiket yang sama pada detik yang sama, masing-masing
    di layarnya sendiri, dan dua-duanya lolos. Satu truk terhitung dua kali.

    Kunci barisnya dipasang di TIKET, bukan di salah satu tabel batch, karena
    tiketlah satu-satunya benda yang sama-sama dilihat kedua jalur. `FOR UPDATE`
    di sini tidak mengubah apa pun di tabel milik timbangan — ia hanya membuat
    pemeriksaan "sudah dipakai?" dan penulisan batch-nya tak bisa disisipi.
    """
    await db.execute(_SQL_KUNCI_TIKET, {"tid": tid})
    baris = (await db.execute(_SQL_PEMAKAI_TIKET, {"tid": tid})).first()
    if baris is not None:
        lingkup, kode_batch, oleh, waktu = baris
        siapa = f" oleh {oleh}" if oleh else ""
        jam = f" pukul {berzona(waktu):%H:%M}" if waktu else ""
        raise TiketSudahDipakai(
            f"Sudah dicatat{siapa}{jam} sebagai batch {lingkup} "
            f"{kode_batch or '(tanpa kode)'}. Daftar tiketnya sudah diperbarui."
        )
