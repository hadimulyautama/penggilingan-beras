"""Rekonsiliasi TIMBANGAN ↔ INTAKE produksi (shared DB, read-only).

Menutup celah dobel/bocor + menyoroti selisih nota vs timbang riil:
  1. Tiket MASUK sudah SELESAI tapi BELUM jadi batch → gabah/PK ditimbang tapi tak tercatat.
  2. Batch tertaut dengan SELISIH nota↔timbang (kg, %, Rp) → potensi lebih bayar / kurang terima.
  3. Batch "menunggu bobot" → belum tersinkron dari timbang.
  4. Batch MANUAL (tanpa timbang) → perlu ditinjau.
  5. Batch yang TIKETNYA BERUBAH setelah tertaut → tiket dibatalkan, pemasok
     dikoreksi, komoditas diganti, atau tiket ditutup paksa.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.penggilingan.peta_jenis import PETA_MASUK

_SQL_BELUM_TERTAUT = text("""
    SELECT t.kode, t.jenis_kode, t.tanggal, t.nomor_polisi,
           t.netto_timbangan_kg, t.berat_acuan_kg,
           COALESCE(s.nama_supplier, t.pihak_nama) AS nama
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
     WHERE t.arah = 'MASUK'
       -- Tiket yang DIBATALKAN memang tak boleh jadi batch. Melaporkannya
       -- sebagai "ditimbang tapi tak tercatat" membuat daftar ini penuh
       -- pekerjaan yang justru salah bila dikerjakan — dan daftar semacam itu
       -- berhenti dibaca.
       AND t.status_transaksi = 'AKTIF'
       AND t.status_tiket IN ('SELESAI', 'DITUTUP_PAKSA')
       -- cermin bertanda: pencatatan yang dibatalkan tak menaut tiketnya
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL AND dibatalkan_pada IS NULL)
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM pk_purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL AND dibatalkan_pada IS NULL)
     ORDER BY t.tanggal DESC, t.id DESC
""")

# Batch (gabah + PK) tertaut dgn selisih nota↔timbang. UNION dua tabel intake.
_SQL_SELISIH = text("""
    SELECT kode_batch, nama, jenis, nota, timbang, selisih_kg, selisih_persen, harga FROM (
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?') AS nama, 'gabah' AS jenis,
             t.berat_acuan_kg AS nota, t.netto_timbangan_kg AS timbang,
             t.selisih_kg, t.selisih_persen, v.harga_per_kg AS harga
        FROM purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
        LEFT JOIN purchase_batch_verifications v ON v.purchase_batch_id = b.id
       WHERE b.dibatalkan_pada IS NULL
      UNION ALL
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?') AS nama, 'pk' AS jenis,
             t.berat_acuan_kg, t.netto_timbangan_kg, t.selisih_kg, t.selisih_persen,
             v.harga_per_kg
        FROM pk_purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
        LEFT JOIN pk_purchase_verifications v ON v.pk_purchase_batch_id = b.id
       WHERE b.dibatalkan_pada IS NULL
    ) x
    WHERE timbang IS NOT NULL AND COALESCE(nota,0) > 0
      AND ABS(COALESCE(selisih_kg,0)) > 0
    ORDER BY ABS(COALESCE(selisih_kg,0)) DESC
""")

_SQL_MENUNGGU = text("""
    SELECT kode_batch, 'gabah' j FROM purchase_batches
     WHERE sumber_berat='menunggu' AND dibatalkan_pada IS NULL
    UNION ALL
    SELECT kode_batch, 'pk' j FROM pk_purchase_batches
     WHERE sumber_berat='menunggu' AND dibatalkan_pada IS NULL
""")

# Batch tertaut yang bobot tersimpannya BEDA dari tiket SAAT INI (tiket direvisi)
# TAPI sudah terverifikasi harga / (gabah) sudah digiling → TIDAK di-auto-resync
# (nilai finansial/rendemen beku). Perlu ditinjau manual.
_SQL_REVISI = text("""
    SELECT kode_batch, nama, jenis, tersimpan, tiket_now, status, terverifikasi FROM (
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?') AS nama, 'gabah' AS jenis,
             b.berat_total_kg AS tersimpan,
             COALESCE(NULLIF(t.berat_acuan_kg,0), t.netto_timbangan_kg) AS tiket_now,
             b.status_batch AS status, (NOT b.flag_unverified) AS terverifikasi
        FROM purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
       WHERE b.sumber_berat IN ('nota','timbangan') AND b.dibatalkan_pada IS NULL
      UNION ALL
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?'), 'pk',
             b.berat_total_kg, COALESCE(NULLIF(t.berat_acuan_kg,0), t.netto_timbangan_kg),
             b.status_batch, (NOT b.flag_unverified)
        FROM pk_purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
       WHERE b.sumber_berat IN ('nota','timbangan') AND b.dibatalkan_pada IS NULL
    ) x
    WHERE tiket_now IS NOT NULL
      AND tersimpan IS DISTINCT FROM tiket_now
      AND (terverifikasi = true OR status = 'digiling')
    ORDER BY ABS(COALESCE(tersimpan,0) - tiket_now) DESC
""")


# ── Tiket yang BERUBAH setelah batch-nya dibuat ─────────────────────────────
#
# Sampai 11 September 2026 rekonsiliasi hanya membandingkan ANGKA: berapa kg di
# nota, berapa kg di timbangan. Semua yang lain diam-diam dianggap tak pernah
# berubah. Padahal tiket bisa dibatalkan, pemasoknya dikoreksi, dan
# komoditasnya diganti — semuanya SESUDAH produksi menaut batch padanya, dan
# tak satu pun meninggalkan jejak di layar produksi.
#
# Empat keadaan di bawah karenanya bukan "selisih" melainkan "kontrak yang
# putus": batch masih menunjuk tiket, tetapi tiket sudah bukan yang dulu.
# Pesannya ditulis lengkap di SQL supaya yang membaca layar tahu apa yang
# harus dilakukan, bukan sekadar bahwa ada yang salah.
_SQL_MENYIMPANG = """
      SELECT b.kode_batch, '{jenis}' AS jenis, t.kode AS kode_tiket,
             '{tag}' AS masalah, {pesan} AS pesan
        FROM {tbl} b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers sb ON sb.id = b.supplier_id
        LEFT JOIN suppliers st ON st.id = t.supplier_id
       WHERE b.dibatalkan_pada IS NULL AND ({syarat})
"""

# (tag, syarat, pesan) — pesan dirakit di SQL agar memuat nama/kode sebenarnya.
_ATURAN_MENYIMPANG = (
    (
        "tiket_batal",
        "t.status_transaksi <> 'AKTIF'",
        "'Tiket ' || t.kode || ' DIBATALKAN di Pos Timbang setelah batch ini dibuat. "
        "Batalkan batch-nya, atau minta Pos Timbang memulihkan tiket bila "
        "pembatalannya keliru.'",
    ),
    (
        # Dibandingkan lewat supplier_id, bukan nama: nama pemasok di batch bisa
        # saja hasil "cari atau buat" dari `pihak_nama`, dan dua ejaan nama yang
        # sama akan terus-menerus dilaporkan sebagai selisih yang tak ada.
        "pemasok_beda",
        "t.status_transaksi = 'AKTIF' AND t.supplier_id IS NOT NULL "
        "AND t.supplier_id IS DISTINCT FROM b.supplier_id",
        "'Pemasok tiket ' || t.kode || ' kini ' || COALESCE(st.nama_supplier, '?') "
        "|| ', sedangkan batch tercatat atas ' || COALESCE(sb.nama_supplier, '?') "
        "|| '. Samakan sebelum harga diverifikasi.'",
    ),
    (
        "komoditas_beda",
        "t.status_transaksi = 'AKTIF' AND t.jenis_kode NOT IN :jenis_sah",
        "'Komoditas tiket ' || t.kode || ' kini ' || t.jenis_kode "
        "|| ', tidak lagi cocok dengan jenis batch ini. Batch salah tabel — "
        "batalkan dan catat ulang lewat jalur yang benar.'",
    ),
    (
        "tutup_paksa",
        "t.status_transaksi = 'AKTIF' AND t.status_tiket = 'DITUTUP_PAKSA' "
        "AND b.sumber_berat = 'menunggu'",
        "'Tiket ' || t.kode || ' DITUTUP PAKSA sebelum sempat punya bobot, "
        "jadi batch ini akan menunggu bobot selamanya. Isi bobotnya dari nota, "
        "atau batalkan batch.'",
    ),
)


def _rakit_menyimpang() -> str:
    """Rakit satu kueri UNION: empat aturan × dua tabel intake.

    Dirakit, bukan diketik delapan kali, karena aturan kelima nanti hanya akan
    ditambahkan di satu tempat — dan cabang yang terlupa pada penambahan
    berikutnya justru jadi satu-satunya lubang yang tersisa.
    """
    bagian = []
    for tbl, jenis, sah in (
        ("purchase_batches", "gabah", "gabah"),
        ("pk_purchase_batches", "pk", "pk"),
    ):
        for tag, syarat, pesan in _ATURAN_MENYIMPANG:
            kode_sah = tuple(k for k, v in PETA_MASUK.items() if v.model == sah)
            s = syarat.replace(
                ":jenis_sah",
                "(" + ", ".join(f"'{k}'" for k in kode_sah) + ")",
            )
            bagian.append(
                _SQL_MENYIMPANG.format(tbl=tbl, jenis=jenis, tag=tag,
                                       pesan=pesan, syarat=s)
            )
    return "UNION ALL".join(bagian) + "     ORDER BY masalah, kode_batch\n"


_SQL_TIKET_MENYIMPANG = text(_rakit_menyimpang())

_SQL_MANUAL = text("""
    SELECT count(*) FROM (
      SELECT id FROM purchase_batches WHERE sumber_berat='manual' AND dibatalkan_pada IS NULL
      UNION ALL SELECT id FROM pk_purchase_batches WHERE sumber_berat='manual' AND dibatalkan_pada IS NULL
    ) z
""")


async def rekonsiliasi(db: AsyncSession) -> dict:
    belum = [dict(r._mapping) for r in (await db.execute(_SQL_BELUM_TERTAUT)).all()]
    selisih = [dict(r._mapping) for r in (await db.execute(_SQL_SELISIH)).all()]
    revisi = [dict(r._mapping) for r in (await db.execute(_SQL_REVISI)).all()]
    menunggu = [dict(r._mapping) for r in (await db.execute(_SQL_MENUNGGU)).all()]
    menyimpang = [dict(r._mapping)
                  for r in (await db.execute(_SQL_TIKET_MENYIMPANG)).all()]
    n_manual = (await db.execute(_SQL_MANUAL)).scalar_one()
    return {"belum_tertaut": belum, "selisih": selisih, "revisi": revisi,
            "menunggu": menunggu, "jumlah_manual": int(n_manual or 0),
            "menyimpang": menyimpang,
            "stok_negatif": await _stok_pk_negatif(db)}


async def _stok_pk_negatif(db: AsyncSession) -> list[dict]:
    """Proses giling yang PK-nya terkirim LEBIH BANYAK daripada yang dihasilkan.

    Layar operator memotong saldo di nol — dan pemotongan itu tepat untuk
    layar: angka negatif di "stok siap kirim" akan dibaca sebagai kerusakan
    aplikasi, bukan sebagai selisih yang perlu ditelusuri, dan yang
    menelusurinya bukan operator.

    Tetapi yang dipotong di layar tak boleh ikut hilang dari pembukuan. Temuan
    QA P-K-06: 6 ton PK terkirim 12 ton, dan yang terbaca di mana pun "0".
    Selisih yang tak muncul di satu layar pun tak akan pernah diperiksa siapa
    pun — jadi ia muncul DI SINI, di tempat orang memang datang untuk mencari
    selisih.
    """
    from app.models import MillingProcess
    from app.services.transfer import saldo_pk

    proses = (await db.execute(
        select(MillingProcess.id, MillingProcess.kode_proses)
        .where(MillingProcess.status == "selesai")
        .order_by(MillingProcess.id.desc()).limit(200)
    )).all()
    keluar = []
    for pid, kode in proses:
        saldo = await saldo_pk(db, pid)
        if saldo < -0.5:          # ambang: pembulatan timbangan bukan selisih
            keluar.append({"kode_proses": kode, "kurang_kg": abs(saldo)})
    return keluar


def _kg(v) -> str:
    return f"{float(v or 0):,.0f}".replace(",", ".")


def format_rekonsiliasi(d: dict) -> str:
    baris = ["🔎 Rekonsiliasi Timbangan ↔ Intake"]
    belum = d["belum_tertaut"]
    baris.append(f"\n① Timbang MASUK selesai tapi BELUM jadi batch: {len(belum)}")
    for t in belum[:10]:
        b = t.get("berat_acuan_kg") or t.get("netto_timbangan_kg")
        baris.append(f"   • {t['kode']} · {t.get('nama') or '?'} · {t['jenis_kode']} · {_kg(b)} kg")
    sel = d["selisih"]
    baris.append(f"\n② Selisih nota ↔ timbang riil: {len(sel)} batch")
    for x in sel[:10]:
        rp = (float(x.get("selisih_kg") or 0) * float(x["harga"])) if x.get("harga") else None
        rps = f" ≈ Rp {_kg(rp)}" if rp is not None else ""
        baris.append(f"   • {x['kode_batch']} ({x['nama']}): nota {_kg(x['nota'])} vs timbang "
                     f"{_kg(x['timbang'])} → selisih {_kg(x['selisih_kg'])} kg "
                     f"({float(x.get('selisih_persen') or 0):.1f}%){rps}")
    rev = d.get("revisi", [])
    baris.append(f"\n③ Bobot tiket BERUBAH setelah verifikasi/giling (perlu tinjau): {len(rev)}")
    for x in rev[:10]:
        tag = "terverifikasi" if x.get("terverifikasi") else str(x.get("status") or "")
        baris.append(f"   • {x['kode_batch']} ({x['nama']}): tersimpan {_kg(x['tersimpan'])} kg "
                     f"→ tiket kini {_kg(x['tiket_now'])} kg [{tag}] — tak diubah otomatis")
    baris.append(f"\n④ Batch menunggu bobot: {len(d['menunggu'])}"
                 + (" — " + ", ".join(m['kode_batch'] for m in d['menunggu'][:10]) if d['menunggu'] else ""))
    baris.append(f"⑤ Batch manual (tanpa timbang): {d['jumlah_manual']}")
    neg = d.get("stok_negatif", [])
    if neg:
        baris.append(f"\n⑥ PK TERKIRIM MELEBIHI YANG DIHASILKAN: {len(neg)} proses")
        for x in neg[:10]:
            baris.append(f"   • {x['kode_proses']}: kelebihan {_kg(x['kurang_kg'])} kg "
                         "— layar operator memotongnya di 0, jadi hanya terlihat di sini")
    menyimpang = d.get("menyimpang", [])
    if menyimpang:
        baris.append(f"\n⑦ TIKET BERUBAH SETELAH TERTAUT: {len(menyimpang)}")
        # Pesannya sudah lengkap dari kueri — di sini tak dipendekkan, karena
        # yang membaca baris ini justru perlu tahu apa yang harus dilakukan.
        for x in menyimpang[:20]:
            baris.append(f"   • {x['kode_batch']} ({x['jenis']}) — {x['pesan']}")
    if (not belum and not sel and not rev and not neg and not menyimpang
            and not d["menunggu"]):
        baris.append("\n✅ Bersih — semua timbang tertaut & tak ada selisih.")
    return "\n".join(baris)
