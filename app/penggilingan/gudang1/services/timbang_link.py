"""Jembatan ke sistem TIMBANGAN (aplikasi terpisah, DB terintegrasi).

Model `timbangan_transaksi` dimiliki repo timbangan; di sini kita menyentuhnya
lewat SQL mentah pada DB yang sama — dua layanan Railway terpisah, tanpa API,
cuma satu Postgres yang sama-sama dibaca. Dipakai intake produksi untuk
menaut batch ke tiket timbang (operator memilih tiket aktif, bukan mengetik
bobot/supplier).

⚠⚠ HAMPIR SELURUHNYA BACA-ONLY — dengan SATU pengecualian sengaja:
`tutup_paksa_pk_ditolak` di bagian akhir berkas ini. Timbangan adalah
OTORITAS BERAT, dan menulis ke tabelnya dari sini melangkahi batas itu;
jangan tambah penulis kedua tanpa alasan setara kuatnya.

Sumber kebenaran: bobot/supplier/nopol dari timbang. Bobot:
  netto_timbangan_kg = bermuatan − kosong (TRUKNYA, bukan barangnya)
  berat_barang_kg    = netto − tara karung & tara lain (BARANGNYA)
  berat_acuan_kg     = bobot NOTA/surat jalan (opsional)
"""
from __future__ import annotations

from dataclasses import dataclass

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
#: ── ATURAN BOBOT BAHAN — keputusan pemilik 25 September 2026 ──
#:
#: Sampai hari itu NOTA menang begitu ada, sejauh apa pun timbangan di
#: bawahnya, dan komoditasnya tak pernah dilihat. Pemilik mengubahnya:
#:
#:     real = berat BARANG menurut Pos Timbang (netto − tara karung)
#:     kurang = nota − real
#:     kurang <= toleransi  → NOTA yang dipakai
#:     kurang >  toleransi  → REAL yang dipakai
#:
#: Toleransinya PERSEN, bukan kilogram tetap. Pemilik menyebut "20 kg" lebih
#: dulu, lalu menjelaskan sebabnya: "gabah basah yang dibeli biasanya
#: ditimbang di sawah, dan dalam perjalanan bisa saja susut bobotnya. Jika
#: dari 10 ton susutnya 20 kg, itu masih batas wajar." Susut perjalanan TUMBUH
#: bersama muatan — 20 kg atas 10 ton = 0,2%, dan muatan 20 ton yang susut 40
#: kg susut sama wajarnya. Angka tetap akan menolak truk besar yang normal dan
#: memaafkan truk kecil yang tidak. Pada 10 ton keduanya sama persis.
#:
#: KELEBIHAN dijawab sendirinya: real yang lebih berat membuat `kurang`
#: negatif, jadi ia jatuh ke cabang pertama — NOTA. Nota membatasi ke ATAS.
#:
#: Angkanya di `setelan_pabrik` (bawaan 0,2) supaya Direksi bisa menggesernya
#: tanpa deploy; JENIS mana yang mendapatnya tetap di kode, sebab itu bukan
#: angka melainkan keputusan tentang komoditas.

#: Jenis yang mendapat toleransi. Yang TIDAK disebut mendapat 0 — perlakuan
#: gabah kering, yang lebih ketat. Tabel `timbangan_jenis` punya dua belas
#: jenis sementara pemilik menyebut tiga; memberi toleransi diam-diam kepada
#: komoditas yang tak ia sebut berarti memutuskan atas namanya.
JENIS_BERTOLERANSI = ("GABAH_BASAH",)

#: Bentuk SQL dari `real`: barang bila ada, netto sebagai cadangan untuk tiket
#: lama yang belum punya snapshot barangnya. Nol berarti "tak ada angkanya".
SQL_REAL_TIKET = "COALESCE(NULLIF(t.berat_barang_kg, 0), t.netto_timbangan_kg)"

#: Bentuk SQL dari toleransinya, dibangkitkan dari daftar di atas — bukan
#: diketik ulang. Daftar yang disalin ke kueri kedua akan tertinggal di salah
#: satunya pada perubahan berikutnya, dan yang tertinggal justru jadi
#: satu-satunya pintu yang terbuka.
SQL_TOLERANSI = (
    "(CASE WHEN t.jenis_kode IN ("
    + ", ".join(f"'{j}'" for j in JENIS_BERTOLERANSI)
    + ") THEN CAST(:tol_persen AS numeric) * COALESCE(t.berat_acuan_kg, 0) / 100"
    " ELSE 0 END)")

#: Bobot yang dipakai HPP. Bentuk SQL dari `bobot_efektif` — keduanya WAJIB
#: menjawab sama; `tests/pg/test_bobot_nota.py` mengadu keduanya atas seluruh
#: kasus, sebab kembaran yang berpisah membuat layar dan poller menyebut angka
#: berbeda tentang truk yang sama.
SQL_BERAT_TIKET = (
    "(CASE"
    "  WHEN " + SQL_REAL_TIKET + " IS NULL THEN NULLIF(t.berat_acuan_kg, 0)"
    "  WHEN COALESCE(t.berat_acuan_kg, 0) = 0 THEN " + SQL_REAL_TIKET +
    "  WHEN t.berat_acuan_kg - " + SQL_REAL_TIKET + " <= " + SQL_TOLERANSI +
    "   THEN t.berat_acuan_kg"
    "  ELSE " + SQL_REAL_TIKET +
    " END)")

#: Dari mana angkanya datang — dihitung dari ATURAN yang sama, bukan dari "ada
#: nota atau tidak". Sesudah 25 September, ada nota tak lagi berarti nota yang
#: dipakai, dan kolom yang menjawab "nota" atas angka timbangan berbohong
#: tentang asal usul angka yang sudah masuk laporan.
SQL_SUMBER_BERAT = (
    "(CASE WHEN COALESCE(t.berat_acuan_kg, 0) > 0"
    "       AND (" + SQL_REAL_TIKET + " IS NULL"
    "            OR t.berat_acuan_kg - " + SQL_REAL_TIKET + " <= " + SQL_TOLERANSI + ")"
    "      THEN 'nota' ELSE 'timbangan' END)")

_SQL_AKTIF = text("""
    SELECT t.id, t.kode, t.jenis_kode, j.nama AS jenis_nama,
           t.tanggal, t.timbang1_waktu, t.nomor_polisi, t.nama_sopir,
           t.supplier_id, s.nama_supplier, t.pihak_nama,
           -- ── Pemilik barang, untuk tiket JASA ──
           --
           -- Sampai 1 Oktober 2026 setiap tiket MASUK punya pemasok: barangnya
           -- dibeli. Tiket jasa tidak — barangnya dititipkan, dan yang terisi
           -- `pelanggan_id`. Tanpa dua kolom ini kartunya bertanda tanya
           -- ("? · B 1234 XY"), dan tanda tanya pada kartu yang menyuruh orang
           -- menerima barang adalah kartu yang tak bisa dikerjakan.
           t.pelanggan_id, pl.nama_pelanggan, t.jasa_id, ja.kode AS jasa_kode,
           -- ⚠ `t.jasa` PENENTU UTAMA sejak migrasi 0066 — lihat `adalah_jasa()`.
           t.jasa,
           t.netto_timbangan_kg, t.berat_barang_kg, t.berat_acuan_kg,
           t.selisih_kg, t.selisih_persen,
           t.timbang1_kg, t.berat_kosong_kg,
           t.status_kontrol, t.status_tiket
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
      LEFT JOIN pelanggan pl ON pl.id = t.pelanggan_id
      LEFT JOIN jasa ja ON ja.id = t.jasa_id
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
           -- Pemilik barang untuk tiket jasa — lihat catatan di `_SQL_AKTIF`.
           t.pelanggan_id, pl.nama_pelanggan, t.jasa_id, ja.kode AS jasa_kode,
           -- ⚠ `t.jasa` PENENTU UTAMA sejak migrasi 0066 — lihat `adalah_jasa()`.
           t.jasa,
           t.netto_timbangan_kg, t.berat_barang_kg, t.berat_acuan_kg,
           t.selisih_kg, t.selisih_persen,
           t.timbang1_kg, t.berat_kosong_kg,
           t.status_kontrol, t.status_tiket
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
      LEFT JOIN pelanggan pl ON pl.id = t.pelanggan_id
      LEFT JOIN jasa ja ON ja.id = t.jasa_id
      LEFT JOIN timbangan_jenis j ON j.kode = t.jenis_kode
     WHERE t.id = :tid""" + SYARAT_TIKET_SAH + """
""")


@dataclass(frozen=True)
class Bobot:
    """Bobot bahan yang dipakai HPP, berikut dari mana ia datang."""

    kg: float | None
    #: 'nota' | 'timbangan' — dihitung dari ATURAN, bukan dari "ada nota".
    sumber: str
    #: Kalimat pendek saat NOTA KALAH: "nota 10.000, kurang 300 kg > batas 20
    #: kg". Kosong bila tak ada yang perlu dijelaskan.
    #:
    #: Sesudah 25 September 2026 kata "timbangan" di kartu bisa berarti dua
    #: hal yang sangat berbeda: tak ada notanya, atau ADA notanya tetapi
    #: kurangnya melewati batas. Yang kedua adalah kabar yang seseorang perlu
    #: tindak lanjuti ke pemasok, dan tanpa kalimat ini selisih 300 kg cuma
    #: jadi angka yang tak seorang pun tahu asalnya.
    sebab: str = ""


def toleransi_kg(nota: float, jenis_kode: str | None, tol_persen: float) -> float:
    """Berapa kilogram kekurangan yang masih dimaafkan untuk tiket ini."""
    return (nota * tol_persen / 100.0
            if (jenis_kode or "") in JENIS_BERTOLERANSI else 0.0)


def bobot_efektif(*, nota, barang, netto, jenis_kode: str | None,
                  tol_persen: float) -> Bobot:
    """ATURAN BOBOT BAHAN — satu-satunya tempat ia ditulis dalam Python.

    Bentuk kembarannya `SQL_BERAT_TIKET` + `SQL_SUMBER_BERAT`, dan keduanya
    wajib menjawab sama. Lihat catatan panjang di atas untuk aturannya.
    """
    n = float(nota or 0)
    real = None
    for kandidat in (barang, netto):
        v = float(kandidat) if kandidat is not None else 0.0
        if v > 0:
            real = v
            break
    # Belum ada angka timbangan sama sekali (tiket baru masuk, belum ditimbang
    # kedua): tak ada yang bisa dibandingkan, jadi nota dipakai apa adanya —
    # persis seperti sebelum aturan ini. Yang berubah adalah perbandingannya,
    # bukan keadaan "belum ada pembanding".
    if real is None:
        return Bobot(kg=(n if n > 0 else None), sumber="nota" if n > 0 else "timbangan")
    if n <= 0:
        return Bobot(kg=real, sumber="timbangan")
    kurang = n - real
    batas = toleransi_kg(n, jenis_kode, tol_persen)
    if kurang <= batas:
        # Termasuk kurang NEGATIF: real yang lebih berat daripada nota. Nota
        # membatasi ke atas (ditegaskan pemilik).
        return Bobot(kg=n, sumber="nota")
    return Bobot(
        kg=real, sumber="timbangan",
        sebab=(f"nota {_kg_teks(n)}, kurang {_kg_teks(kurang)} > batas "
               f"{_kg_teks(batas)}"),
    )


def _kg_teks(v: float) -> str:
    return f"{v:,.0f} kg".replace(",", ".")


def _row(r, tol_persen: float) -> dict:
    d = dict(r._mapping)
    # Basis bobot untuk HPP — lewat `bobot_efektif`, corong yang SAMA dengan
    # yang dipakai poller lewat bentuk SQL-nya. Dua jawaban untuk satu truk
    # berarti layar dan poller berselisih tentang barang yang sudah turun.
    b = bobot_efektif(nota=d.get("berat_acuan_kg"), barang=d.get("berat_barang_kg"),
                      netto=d.get("netto_timbangan_kg"),
                      jenis_kode=d.get("jenis_kode"), tol_persen=tol_persen)
    d["susulan"] = d.get("status_tiket") == "SELESAI"
    d["sumber_berat"] = b.sumber
    d["berat_hpp_kg"] = b.kg
    d["sebab_bobot"] = b.sebab
    return d


def adalah_jasa(t: dict) -> bool:
    """Tiket ini membawa barang TITIPAN, bukan barang yang dibeli?

    Yang menentukan bukan jenis komoditasnya: cara menimbang, tara, dan ambang
    gabah jasa sama persis dengan gabah beli — yang berbeda hanya pemiliknya.
    Itu sebabnya TIDAK ada jenis timbang `GABAH_KERING_JASA`: menggandakan
    tiga jenis jadi enam berarti menggandakan aturan tara dan memberi petugas
    enam tombol berpasangan mirip untuk salah pilih.

    ⚠⚠ PENENTU UTAMA `t.jasa` (migrasi 0066/0041), BUKAN `pelanggan_id`.

    Cacat lapangan 2 Oktober 2026: sampai migrasi itu, fungsi ini membaca
    `pelanggan_id is not None` — dan itu SALAH untuk pelanggan BARU yang
    diketik bebas di pintu ketik-bebas Pos Timbang (cermin Kledo disegarkan
    mingguan, jadi pelanggan baru memang bisa belum ada): `pelanggan_id`-nya
    tetap NULL sampai `purchase.find_or_create_pelanggan` membuatnya DI SINI,
    bukan di sana. Baris tiket "jasa-pelanggan-baru" jadi IDENTIK bentuknya
    dengan "pembelian-pemasok-baru" — dan `create_purchase_batch_dari_timbang`
    membuat PEMASOK PALSU dari nama pelanggan, persis yang dilarang keras
    spek D3. Terlihat pertama kali di gudang: lot PK titipan pelanggan
    tercatat sebagai pembelian pabrik, tanpa satu pun galat.

    `pelanggan_id`/`jasa_id` tetap diperiksa sebagai KAKI KEDUA — bukan untuk
    tiket baru (`t.jasa` selalu benar untuknya), melainkan untuk tiket LAMA
    yang dibuat sebelum kolom `jasa` ada: migrasi 0066/0041 mengisinya dari
    riwayat (`jasa = pelanggan_id IS NOT NULL OR jasa_id IS NOT NULL`), tetapi
    baris yang dibaca lewat jalur lain (mis. kueri yang belum memilih kolom
    `jasa`) tetap harus terbaca benar.
    """
    return bool(t.get("jasa")) or t.get("pelanggan_id") is not None \
        or t.get("jasa_id") is not None


def nama_pihak(t: dict) -> str:
    """Nama pihak di kartu sebuah tiket — pemasok, pelanggan, atau nama bebas.

    ⚠ SATU penolong, dipanggil di semua tempat. Bentuk lamanya
    (`nama_supplier or pihak_nama or "?"`) berdiri di TIGA tempat di
    `berjalan.py`, dan tiket jasa tak punya keduanya — jadi membetulkan satu
    saja menyisakan dua kartu bertanda tanya yang baru ketahuan di lapangan,
    pada hari truk pelanggan sudah berdiri di halaman.

    Pesanannya ikut disebut bila ada: "JAS-2610-007 Pak Budi" bukan sekadar
    "Pak Budi". Pak Budi bisa punya dua pesanan berjalan, dan yang menentukan
    barang ini masuk ke mana adalah pesanannya, bukan namanya.

    ⚠ DIPERIKSA LEWAT `adalah_jasa(t)`, bukan "ada `nama_pelanggan`?" — cacat
    kembarnya `adalah_jasa` sendiri (2 Oktober 2026): pelanggan BARU yang
    diketik bebas belum punya baris `pelanggan`, jadi `nama_pelanggan` NULL
    sampai produksi menerimanya. Tanpa pembetulan ini, kartu antreannya jatuh
    ke cabang pemasok dan menampilkan nama telanjang TANPA tanda "JASA" —
    operator yang menerimanya tak diberi tahu sama sekali bahwa barang ini
    titipan, persis kebingungan yang melahirkan cacatnya.
    """
    if adalah_jasa(t):
        nama = (t.get("nama_pelanggan") or t.get("pihak_nama") or "").strip() \
            or "pelanggan"
        kode = (t.get("jasa_kode") or "").strip()
        return f"JASA · {kode} {nama}".strip() if kode else f"JASA · {nama}"
    return t.get("nama_supplier") or t.get("pihak_nama") or "?"


#: Berapa hari ke belakang tiket yang SUDAH DITUTUP masih boleh disusulkan.
#: Cukup panjang untuk menutupi akhir pekan dan libur, cukup pendek supaya
#: daftar tetap bisa dibaca sambil berdiri.
HARI_SUSULAN = 7


#: Tiket KELUAR yang belum tertaut transaksi barang keluar mana pun.
#:
#: Cerminan `_SQL_AKTIF` di sisi masuk, dan bedanya cuma dua: arahnya KELUAR,
#: dan yang diperiksa "sudah dipakai belum" adalah `outgoing_records` — bukan
#: kedua tabel batch. Tiket yang transaksinya DIBATALKAN muncul lagi di sini,
#: sama seperti indeks parsialnya mengizinkannya: truk yang salah dicatat harus
#: punya jalan pulang.
#:
#: `SYARAT_TIKET_SAH` ikut, dan itu bukan salinan berlebih: tiket yang
#: dibatalkan atau ditutup paksa di Pos Timbang pernah tetap mendorong 9.800 kg
#: ke pembukuan lewat sisi masuk.
_SQL_KELUAR_AKTIF = text("""
    SELECT t.id, t.kode, t.jenis_kode, j.nama AS jenis_nama,
           t.tanggal, t.timbang1_waktu, t.nomor_polisi, t.status_tiket,
           """ + SQL_REAL_TIKET + """ AS berat_kg,
           -- Pelanggan di TENGAH, bukan di ujung: pada tiket KELUAR lawan
           -- transaksinya memang pelanggan, dan `pihak_nama` cuma nama bebas
           -- yang diketik petugas. Tanpa kaki ini, tiket keluar yang pembelinya
           -- dipilih dari daftar Kledo berdiri tanpa nama di borang verifikasi.
           COALESCE(s.nama_supplier, pl.nama_pelanggan, t.pihak_nama) AS pihak
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
      LEFT JOIN pelanggan pl ON pl.id = t.pelanggan_id
      LEFT JOIN timbangan_jenis j ON j.kode = t.jenis_kode
     WHERE t.arah = 'KELUAR'""" + SYARAT_TIKET_SAH + """
       AND NOT EXISTS (
             SELECT 1 FROM outgoing_records o
              WHERE o.timbangan_transaksi_id = t.id
                AND o.status <> 'batal')
     ORDER BY t.id DESC
     LIMIT 60
""")


async def tiket_keluar_aktif(db: AsyncSession) -> list[dict]:
    """Tiket timbang KELUAR yang belum tertaut, untuk ditempel Admin saat
    verifikasi barang keluar.

    ⚠ URUTAN WAKTUNYA TERBALIK DARI SISI MASUK, dan itu yang menentukan kapan
    daftar ini dipakai: truk masuk KOSONG, dimuat, lalu ditimbang bermuatan saat
    keluar. Tiketnya baru lengkap SESUDAH barangnya naik — jadi daftar ini
    ditawarkan di langkah verifikasi, bukan saat perintah dibuat.
    """
    from app.penggilingan.peta_jenis import keluar_dari_jenis

    out = []
    for r in (await db.execute(_SQL_KELUAR_AKTIF)).mappings().all():
        d = dict(r)
        d["kategori"] = keluar_dari_jenis(d.get("jenis_kode") or "")
        out.append(d)
    return out


async def tiket_masuk_aktif(db: AsyncSession, jenis_kode: str | None = None) -> list[dict]:
    """Daftar tiket timbang MASUK yang belum tertaut, untuk dipilih operator.

    Yang masih TERBUKA selalu masuk — itu pekerjaan yang sedang berjalan.
    Yang sudah ditutup hanya beberapa hari ke belakang; selebihnya urusan
    rekonsiliasi, bukan urusan layar harian.
    """
    from app.services.setelan import toleransi_nota_persen

    tol = await toleransi_nota_persen(db)
    rows = (await db.execute(_SQL_AKTIF, {"hari": HARI_SUSULAN})).all()
    out = [_row(r, tol) for r in rows]
    if jenis_kode:
        out = [d for d in out if d["jenis_kode"] == jenis_kode]
    return out


async def ambil_tiket(db: AsyncSession, tid: int) -> dict | None:
    """Ambil satu tiket timbang (untuk membentuk batch)."""
    from app.services.setelan import toleransi_nota_persen

    r = (await db.execute(_SQL_SATU, {"tid": tid})).first()
    return _row(r, await toleransi_nota_persen(db)) if r else None


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
        -- Dari ATURAN yang sama, bukan dari "ada nota": sesudah 25
        -- September 2026 ada nota tak lagi berarti nota yang dipakai.
        sumber_berat   = """ + SQL_SUMBER_BERAT + """
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
    from app.services.setelan import toleransi_nota_persen

    tol = await toleransi_nota_persen(db)
    total = 0
    for tbl in ("purchase_batches", "pk_purchase_batches"):
        res = await db.execute(text(_SQL_SINKRON.format(tbl=tbl)), {"tol_persen": tol})
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
    # Kedua kueri memakai `SQL_BERAT_TIKET IS NULL` sebagai saringan "tiketnya
    # belum punya bobot sama sekali" — dan sejak 25 September 2026 rumus itu
    # memuat toleransinya, jadi angkanya wajib ikut dikirim. Tanpa ini
    # kuerinya gagal dengan "bind parameter tak terisi", dan poller berhenti
    # diam-diam: batch tetap 'menunggu' tanpa satu pun tanda di layar.
    from app.services.setelan import toleransi_nota_persen

    tol = await toleransi_nota_persen(db)
    total = 0
    for tbl in ("purchase_batches", "pk_purchase_batches"):
        res = await db.execute(text(_SQL_PERKIRAAN.format(tbl=tbl)),
                               {"tol_persen": tol})
        total += res.rowcount or 0
        res = await db.execute(text(_SQL_PERKIRAAN_TIKET.format(tbl=tbl)),
                               {"tol_persen": tol})
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
        -- Dari ATURAN yang sama, bukan dari "ada nota": sesudah 25
        -- September 2026 ada nota tak lagi berarti nota yang dipakai.
        sumber_berat   = """ + SQL_SUMBER_BERAT + """
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
    from app.services.setelan import toleransi_nota_persen

    tol = await toleransi_nota_persen(db)
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
        res = await db.execute(text(_SQL_RESINKRON.format(tbl=tbl, extra=extra)),
                                    {"tol_persen": tol})
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


# ⚠⚠ SATU-SATUNYA PENULIS di berkas ini — lihat peringatan di kepala berkas.
#
# Timbangan sendiri MENOLAK menutup paksa tiket hanya karena muatannya
# ditolak (`service.tutup_paksa`, Temuan QA T-15 di repo timbangan):
#
#   "Muatan yang DITOLAK bukan alasan melewatkan timbang keluar. Truk yang
#   ditolak tetap keluar dari pabrik, dan tanpa angka keluarnya tak ada
#   kontrol masuk−keluar sama sekali — truk bisa pergi membawa lebih banyak
#   daripada yang ia bawa masuk, dan tak ada satu angka pun yang bisa
#   menunjukkannya. Yang benar untuk muatan ditolak adalah menyelesaikan
#   timbang keduanya seperti biasa."
#
# Keputusan pemilik 4 Oktober 2026 MENGESAMPINGKAN pagar itu KHUSUS untuk PK
# luar yang ditolak produksi: tiket ditutup paksa otomatis, alasannya dari
# produksi, tanpa menunggu timbang kedua. Ini sadar melepas kontrol
# masuk-keluar T-15 untuk kasus ini — keputusan pemilik, bukan QA, dan bukan
# kelonggaran yang menular ke kasus lain.
#
# Tak lewat `service.tutup_paksa` (tak bisa — proses Python berbeda, DB yang
# sama), jadi efeknya DITIRU di sini: status + alasan + `_kosongkan_hasil`
# timbangan sendiri (lihat definisinya di sana). `pastikan_bebas_tautan` di
# timbangan SENGAJA tak ikut ditiru — pagar itu menolak menutup tiket yang
# SUDAH ditaut batch produksi, dan baris penolakan inilah justru PENYEBAB
# tiket ini ditutup; menjalankan pagar itu di sini akan menolak tindakan yang
# sedang dikerjakannya sendiri.
_SQL_TUTUP_PAKSA_PK_DITOLAK = text("""
    UPDATE timbangan_transaksi
       SET status_tiket = 'DITUTUP_PAKSA',
           tutup_paksa_alasan = :alasan,
           netto_timbangan_kg = NULL,
           berat_barang_kg = NULL,
           selisih_kg = 0,
           selisih_persen = 0,
           batas_bawah_kg = NULL,
           batas_atas_kg = NULL,
           status_kontrol = NULL,
           keterangan = NULL
     WHERE id = :tid AND status_tiket = 'TERBUKA'
""")


async def tutup_paksa_pk_ditolak(db: AsyncSession, *, tid: int, alasan: str) -> bool:
    """Tutup paksa tiket timbang karena PK-nya DITOLAK di produksi.

    Dipanggil DI DALAM transaksi yang sama dengan `create_pk_rejection_dari_
    timbang` — baris tiketnya sudah terkunci `FOR UPDATE` oleh `kunci_tiket_
    untuk_ditaut` di awal fungsi itu, jadi tak ada kunci baru di sini.

    → False bila tiketnya SUDAH tak berstatus TERBUKA (sudah selesai timbang
    kedua secara normal, atau sudah ditutup lebih dulu) — pemanggil tak
    perlu memperlakukan itu sebagai galat, PK-nya tetap tercatat ditolak di
    produksi; cuma tiketnya tak perlu (dan tak boleh) ditutup ulang.
    """
    res = await db.execute(_SQL_TUTUP_PAKSA_PK_DITOLAK, {
        "tid": tid,
        "alasan": f"PK ditolak di produksi: {alasan.strip()}",
    })
    return res.rowcount > 0
