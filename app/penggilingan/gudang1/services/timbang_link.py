"""Jembatan baca-only ke sistem TIMBANGAN (aplikasi terpisah, DB terintegrasi).

Model `timbangan_transaksi` dimiliki repo timbangan; di sini kita hanya MEMBACA lewat
SQL mentah pada DB yang sama. Dipakai intake produksi untuk menaut batch ke tiket timbang
(operator memilih tiket aktif, bukan mengetik bobot/supplier).

Sumber kebenaran: bobot/supplier/nopol dari timbang. Bobot:
  netto_timbangan_kg = bobot TIMBANG (real, wajib)
  berat_acuan_kg     = bobot NOTA/surat jalan (opsional)
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import berzona

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

_SQL_AKTIF = text("""
    SELECT t.id, t.kode, t.jenis_kode, j.nama AS jenis_nama,
           t.tanggal, t.timbang1_waktu, t.nomor_polisi, t.nama_sopir,
           t.supplier_id, s.nama_supplier, t.pihak_nama,
           t.netto_timbangan_kg, t.berat_acuan_kg, t.selisih_kg, t.selisih_persen,
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
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL)
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM pk_purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL)
     ORDER BY (t.status_tiket = 'TERBUKA') DESC, t.tanggal DESC, t.id DESC
""")

_SQL_SATU = text("""
    SELECT t.id, t.kode, t.arah, t.jenis_kode, j.nama AS jenis_nama,
           t.tanggal, t.timbang1_waktu, t.nomor_polisi, t.nama_sopir,
           t.supplier_id, s.nama_supplier, t.pihak_nama,
           t.netto_timbangan_kg, t.berat_acuan_kg, t.selisih_kg, t.selisih_persen,
           t.status_kontrol, t.status_tiket
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
      LEFT JOIN timbangan_jenis j ON j.kode = t.jenis_kode
     WHERE t.id = :tid""" + SYARAT_TIKET_SAH + """
""")


def _row(r) -> dict:
    d = dict(r._mapping)
    # Basis bobot untuk HPP: nota bila ada, selain itu real timbang.
    nota = d.get("berat_acuan_kg")
    real = d.get("netto_timbangan_kg")
    ada_nota = nota is not None and float(nota or 0) > 0
    d["susulan"] = d.get("status_tiket") == "SELESAI"
    d["sumber_berat"] = "nota" if ada_nota else "timbangan"
    d["berat_hpp_kg"] = float(nota) if ada_nota else (float(real) if real is not None else None)
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


# Isi bobot batch yang MASIH 'menunggu' dari tiket-nya, begitu tiket punya bobot
# (nota atau netto timbang). Bobot efektif = nota bila ada, selain itu netto real.
_SQL_SINKRON = """
    UPDATE {tbl} b SET
        berat_total_kg = COALESCE(NULLIF(t.berat_acuan_kg, 0), t.netto_timbangan_kg),
        sumber_berat   = CASE WHEN COALESCE(t.berat_acuan_kg, 0) > 0
                              THEN 'nota' ELSE 'timbangan' END
      FROM timbangan_transaksi t
     WHERE b.timbangan_transaksi_id = t.id
       AND b.sumber_berat = 'menunggu'
""" + SYARAT_TIKET_SAH + """       AND COALESCE(NULLIF(t.berat_acuan_kg, 0), t.netto_timbangan_kg) IS NOT NULL
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


# RE-SINKRON saat tiket DIREVISI (mis. petugas timbang mengoreksi bobot setelah batch
# dibuat & tersinkron). AMAN hanya bila batch BELUM diverifikasi harga (flag_unverified
# → tak ada nilai finansial beku) DAN (gabah) belum digiling (rendemen giling memakai
# snapshot bobot sendiri, jadi tak terpengaruh). Batch yang SUDAH terverifikasi / digiling
# TIDAK diubah otomatis — dilaporkan di rekonsiliasi ("bobot tiket berubah") untuk ditinjau.
_SQL_RESINKRON = """
    UPDATE {tbl} b SET
        berat_total_kg = COALESCE(NULLIF(t.berat_acuan_kg, 0), t.netto_timbangan_kg),
        sumber_berat   = CASE WHEN COALESCE(t.berat_acuan_kg, 0) > 0
                              THEN 'nota' ELSE 'timbangan' END
      FROM timbangan_transaksi t
     WHERE b.timbangan_transaksi_id = t.id
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
       AND COALESCE(NULLIF(t.berat_acuan_kg, 0), t.netto_timbangan_kg) IS NOT NULL
       AND b.berat_total_kg IS DISTINCT FROM
           COALESCE(NULLIF(t.berat_acuan_kg, 0), t.netto_timbangan_kg)
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
       WHERE b.timbangan_transaksi_id = :tid
      UNION ALL
      SELECT 'PK', b.kode_batch, u.nama, b.waktu_pembelian
        FROM pk_purchase_batches b
        LEFT JOIN users u ON u.id = b.input_by
       WHERE b.timbangan_transaksi_id = :tid
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
