"""Rekonsiliasi TIMBANGAN ↔ INTAKE produksi (shared DB, read-only).

Menutup celah dobel/bocor + menyoroti selisih nota vs timbang riil:
  1. Tiket MASUK sudah SELESAI tapi BELUM jadi batch → gabah/PK ditimbang tapi tak tercatat.
  2. Batch tertaut dengan SELISIH nota↔timbang (kg, %, Rp) → potensi lebih bayar / kurang terima.
  3. Batch "menunggu bobot" → belum tersinkron dari timbang.
  4. Batch MANUAL (tanpa timbang) → perlu ditinjau.
  5. Batch yang TIKETNYA BERUBAH setelah tertaut → tiket dibatalkan, pemasok
     dikoreksi, komoditas diganti, atau tiket ditutup paksa.
  6. (QA P6, 21 September 2026) Batch yang masih berdiri di atas PERKIRAAN
     tara; perkiraan yang ternyata MELESET dari netto sungguhan (per nomor
     polisi — menguji anggapan "tara stabil" dari data); dan giling yang
     SELESAI dengan bobot masuk belum final (rendemennya belum bisa dipercaya).
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.penggilingan.gudang1.services.bobot import SQL_NORM_NOPOL
# Basis bobot tiket (nota → barang → netto) DIIMPOR, tak disusun ulang di sini:
# rekonsiliasi yang memakai basis lain akan melaporkan seluruh tiket bertara
# karung sebagai "bobot tiket berubah" — ribuan baris palsu pada hari pertama.
from app.penggilingan.gudang1.services.timbang_link import SQL_BERAT_TIKET
from app.penggilingan.peta_jenis import PETA_MASUK

_SQL_BELUM_TERTAUT = text("""
    SELECT t.kode, t.jenis_kode, t.tanggal, t.nomor_polisi,
           t.netto_timbangan_kg, t.berat_barang_kg, t.berat_acuan_kg,
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
             t.berat_acuan_kg AS nota,
             -- BARANG, bukan netto: `selisih_kg` di tiket dihitung Pos Timbang
             -- sebagai barang − nota, jadi netto di sebelahnya membuat dua
             -- angka yang selisihnya tak sama dengan selisih yang tertulis.
             COALESCE(NULLIF(t.berat_barang_kg, 0), t.netto_timbangan_kg) AS timbang,
             t.selisih_kg, t.selisih_persen, v.harga_per_kg AS harga
        FROM purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
        LEFT JOIN purchase_batch_verifications v ON v.purchase_batch_id = b.id
       WHERE b.dibatalkan_pada IS NULL
      UNION ALL
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?') AS nama, 'pk' AS jenis,
             t.berat_acuan_kg,
             COALESCE(NULLIF(t.berat_barang_kg, 0), t.netto_timbangan_kg),
             t.selisih_kg, t.selisih_persen,
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
             """ + SQL_BERAT_TIKET + """ AS tiket_now,
             b.status_batch AS status, (NOT b.flag_unverified) AS terverifikasi
        FROM purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
       WHERE b.sumber_berat IN ('nota','timbangan') AND b.dibatalkan_pada IS NULL
      UNION ALL
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?'), 'pk',
             b.berat_total_kg, """ + SQL_BERAT_TIKET + """,
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

#: Selisih perkiraan ↔ netto sungguhan yang dianggap "meleset". 2 %: di atas
#: itu tara truknya patut dicurigai bergeser (terpal, bak, sopir kedua) —
#: bukan sekadar pembulatan timbangan. Usulan QA P6, belum dikunci pemilik.
AMBANG_PERKIRAAN_PERSEN = 2.0

# Batch yang MASIH berdiri di atas perkiraan tara (truknya belum ditimbang kedua).
_SQL_PERKIRAAN = text("""
    SELECT kode_batch, 'gabah' AS jenis, no_polisi_truk AS nomor_polisi, berat_total_kg AS perkiraan
      FROM purchase_batches WHERE sumber_berat = 'perkiraan' AND dibatalkan_pada IS NULL
    UNION ALL
    SELECT kode_batch, 'pk', no_polisi_truk, berat_total_kg
      FROM pk_purchase_batches WHERE sumber_berat = 'perkiraan' AND dibatalkan_pada IS NULL
    ORDER BY kode_batch
""")

# Perkiraan yang SUDAH diganti netto sungguhan dan ternyata meleset. Dikelompokkan
# per nomor polisi (dinormalkan) supaya truk yang taranya tidak stabil ketahuan
# dari data, bukan dari rendemen yang aneh berminggu-minggu kemudian.
_SQL_PERKIRAAN_MELESET = text(f"""
    SELECT kode_batch, jenis, nomor_polisi, perkiraan, sungguhan, selisih_kg, selisih_persen FROM (
      SELECT b.kode_batch, 'gabah' AS jenis,
             {SQL_NORM_NOPOL.format(kolom='b.no_polisi_truk')} AS nomor_polisi,
             b.berat_perkiraan_kg AS perkiraan, b.berat_total_kg AS sungguhan,
             b.berat_total_kg - b.berat_perkiraan_kg AS selisih_kg,
             (b.berat_total_kg - b.berat_perkiraan_kg) / b.berat_perkiraan_kg * 100 AS selisih_persen
        FROM purchase_batches b
       WHERE b.berat_perkiraan_kg IS NOT NULL AND b.berat_perkiraan_kg > 0
         AND b.sumber_berat IN ('nota', 'timbangan') AND b.dibatalkan_pada IS NULL
      UNION ALL
      SELECT b.kode_batch, 'pk',
             {SQL_NORM_NOPOL.format(kolom='b.no_polisi_truk')},
             b.berat_perkiraan_kg, b.berat_total_kg,
             b.berat_total_kg - b.berat_perkiraan_kg,
             (b.berat_total_kg - b.berat_perkiraan_kg) / b.berat_perkiraan_kg * 100
        FROM pk_purchase_batches b
       WHERE b.berat_perkiraan_kg IS NOT NULL AND b.berat_perkiraan_kg > 0
         AND b.sumber_berat IN ('nota', 'timbangan') AND b.dibatalkan_pada IS NULL
    ) x
    WHERE ABS(selisih_persen) > :ambang
    ORDER BY nomor_polisi, ABS(selisih_persen) DESC
""")

# Giling yang SELESAI sementara bahannya belum final: rendemen & HPP-nya
# berdiri di atas bobot yang kurang sampai poller melengkapinya.
_SQL_GILING_BELUM_FINAL = text("""
    SELECT m.kode_proses, m.berat_gabah_masuk_kg, m.waktu_selesai
      FROM milling_process m
     WHERE m.status = 'selesai' AND m.bobot_masuk_final = false
     ORDER BY m.id DESC
""")

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
    perkiraan = [dict(r._mapping) for r in (await db.execute(_SQL_PERKIRAAN)).all()]
    meleset = [dict(r._mapping) for r in (await db.execute(
        _SQL_PERKIRAAN_MELESET, {"ambang": AMBANG_PERKIRAAN_PERSEN})).all()]
    giling_belum_final = [dict(r._mapping)
                          for r in (await db.execute(_SQL_GILING_BELUM_FINAL)).all()]
    # Korban lama P6-03 ATAU revisi tiket yang disengaja — keduanya tampak
    # sama dari data, jadi disebut, bukan dibetulkan (QA pra-deploy P6).
    from app.penggilingan.gudang1.services.koreksi_bobot import giling_tak_cocok
    tak_cocok = await giling_tak_cocok(db)
    return {"belum_tertaut": belum, "selisih": selisih, "revisi": revisi,
            "menunggu": menunggu, "jumlah_manual": int(n_manual or 0),
            "menyimpang": menyimpang,
            "stok_negatif": await _stok_pk_negatif(db),
            "perkiraan": perkiraan, "perkiraan_meleset": meleset,
            "giling_belum_final": giling_belum_final,
            "giling_tak_cocok": tak_cocok}


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
        b = (t.get("berat_acuan_kg") or t.get("berat_barang_kg")
             or t.get("netto_timbangan_kg"))
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
    perk = d.get("perkiraan", [])
    if perk:
        baris.append(f"\n⑧ Batch masih di atas PERKIRAAN tara (truk belum ditimbang kedua): {len(perk)}")
        for x in perk[:10]:
            baris.append(f"   • {x['kode_batch']} ({x['jenis']}) · {x.get('nomor_polisi') or '?'} "
                         f"· ± {_kg(x['perkiraan'])} kg")
    meleset = d.get("perkiraan_meleset", [])
    if meleset:
        baris.append(f"\n⑨ PERKIRAAN MELESET > {AMBANG_PERKIRAAN_PERSEN:g}% dari netto sungguhan: "
                     f"{len(meleset)} batch — tara truknya patut diperiksa")
        per_truk: dict[str, list] = {}
        for x in meleset:
            per_truk.setdefault(x.get("nomor_polisi") or "?", []).append(x)
        for nopol, xs in list(per_truk.items())[:10]:
            baris.append(f"   • {nopol}: {len(xs)} batch")
            for x in xs[:5]:
                baris.append(f"       {x['kode_batch']}: perkiraan {_kg(x['perkiraan'])} → "
                             f"sungguhan {_kg(x['sungguhan'])} kg "
                             f"({float(x['selisih_persen']):+.1f}%)")
    gbf = d.get("giling_belum_final", [])
    if gbf:
        baris.append(f"\n⑩ GILING SELESAI DENGAN BOBOT MASUK BELUM FINAL: {len(gbf)} proses "
                     "— rendemennya belum bisa dipercaya sampai truknya ditimbang")
        for x in gbf[:10]:
            baris.append(f"   • {x['kode_proses']}: bahan tercatat {_kg(x['berat_gabah_masuk_kg'])} kg "
                         "(bagian yang diketahui saja)")
    tc = d.get("giling_tak_cocok", [])
    if tc:
        baris.append(f"\n⑪ GILING SELESAI YANG BOBOT MASUKNYA TAK COCOK DENGAN BAHANNYA SEKARANG: "
                     f"{len(tc)} proses — korban lama P6-03, ATAU tiket yang direvisi "
                     "sengaja. Baca satu per satu; yang korban dibetulkan lewat aksi "
                     "\"Betulkan bobot masuk giling\", yang revisi sengaja dibiarkan.")
        for x in tc[:10]:
            baris.append(f"   • {x['kode_proses']}: tercatat {_kg(x['tercatat_kg'])} kg, "
                         f"bahannya kini {_kg(x['seharusnya_kg'])} kg "
                         f"({float(x['kurang_persen'] or 0):+.1f}%)")
    if (not belum and not sel and not rev and not neg and not menyimpang
            and not d["menunggu"] and not perk and not meleset and not gbf and not tc):
        baris.append("\n✅ Bersih — semua timbang tertaut & tak ada selisih.")
    return "\n".join(baris)
