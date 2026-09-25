"""ATURAN BOBOT BAHAN — keputusan pemilik 25 September 2026.

    real = berat BARANG menurut Pos Timbang (netto − tara karung)
    kurang = nota − real
    kurang <= toleransi  → NOTA      · toleransi = 0,2% nota untuk GABAH BASAH
    kurang >  toleransi  → REAL      ·             0      untuk selainnya

Sampai hari itu NOTA menang begitu ada, sejauh apa pun timbangan di bawahnya,
dan komoditasnya tak pernah dilihat. Arah kesalahannya SELALU sama: mencatat
gabah lebih banyak daripada yang turun dari truk — stok tercatat lebih besar
daripada isi silo, dan rendemen lot itu tercatat lebih rendah daripada yang
sebenarnya, sebab penyebutnya digelembungkan.

Yang dijaga berkas ini tiga hal:
  · kelima belas kasus QA menjawab seperti yang dihitung di kertas;
  · batas toleransinya tepat di angkanya — 20 kg lewat, 21 kg tidak;
  · bentuk PYTHON dan bentuk SQL menjawab SAMA. Keduanya kembar, dan kembar
    yang berpisah membuat layar dan poller menyebut angka berbeda tentang truk
    yang sama.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

#: (nama, jenis, nota, real, harus_kg, harus_sumber) — tabel QA 25 Sep 2026.
KASUS = [
    ("BASAH kurang 10 kg",            "GABAH_BASAH",  10_000,  9_990, 10_000, "nota"),
    ("BASAH kurang 20 kg (pas)",      "GABAH_BASAH",  10_000,  9_980, 10_000, "nota"),
    ("BASAH kurang 21 kg (lewat)",    "GABAH_BASAH",  10_000,  9_979,  9_979, "timbangan"),
    ("BASAH kurang 300 kg",           "GABAH_BASAH",  10_000,  9_700,  9_700, "timbangan"),
    ("BASAH real LEBIH 50 kg",        "GABAH_BASAH",  10_000, 10_050, 10_000, "nota"),
    ("BASAH 20 ton kurang 35 kg",     "GABAH_BASAH",  20_000, 19_965, 20_000, "nota"),
    ("BASAH 20 ton kurang 45 kg",     "GABAH_BASAH",  20_000, 19_955, 19_955, "timbangan"),
    ("BASAH 2 ton kurang 5 kg",       "GABAH_BASAH",   2_000,  1_995,  1_995, "timbangan"),
    ("KERING kurang 10 kg",           "GABAH_KERING", 10_000,  9_990,  9_990, "timbangan"),
    ("KERING kurang 1 kg",            "GABAH_KERING", 10_000,  9_999,  9_999, "timbangan"),
    ("KERING sama persis",            "GABAH_KERING", 10_000, 10_000, 10_000, "nota"),
    ("KERING kurang 200 kg",          "GABAH_KERING", 10_000,  9_800,  9_800, "timbangan"),
    ("PK kurang 50 kg",               "BERAS_PK",      9_000,  8_950,  8_950, "timbangan"),
    ("PK sama persis",                "BERAS_PK",      9_000,  9_000,  9_000, "nota"),
    ("TANPA NOTA",                    "GABAH_KERING",       0,  9_950,  9_950, "timbangan"),
]


@pytest.mark.parametrize("nama,jenis,nota,real,harus,sumber", KASUS,
                         ids=[k[0] for k in KASUS])
async def test_aturan_python(nama, jenis, nota, real, harus, sumber):
    """Bentuk Python — yang dipakai layar saat operator memilih tiketnya."""
    from app.penggilingan.gudang1.services.timbang_link import bobot_efektif

    b = bobot_efektif(nota=nota, barang=real, netto=None, jenis_kode=jenis,
                      tol_persen=0.2)
    assert b.kg == harus, f"{nama}: {b.kg} bukan {harus}"
    assert b.sumber == sumber, f"{nama}: sumbernya {b.sumber}"


async def test_bentuk_sql_menjawab_sama_dengan_python(pg):
    """SATU-SATUNYA cara memastikan kembarannya tidak berpisah.

    `SQL_BERAT_TIKET` dipakai poller dan rekonsiliasi; `bobot_efektif` dipakai
    layar. Kalau keduanya berbeda satu kasus saja, angka yang dilihat operator
    saat mencatat akan berbeda dari angka yang akhirnya tersimpan — dan yang
    menang adalah yang menulis paling akhir, tanpa satu pun tanda.
    """
    from sqlalchemy import text

    from app.penggilingan.gudang1.services.timbang_link import (
        SQL_BERAT_TIKET, SQL_SUMBER_BERAT, bobot_efektif)

    # Kasusnya diadu langsung, tanpa menyentuh tabel: nilai-nilainya
    # dipasangkan sebagai satu baris "t" — bentuk yang sama dengan yang dilihat
    # kueri sungguhan.
    sql = text(f"""
        SELECT {SQL_BERAT_TIKET} AS kg, {SQL_SUMBER_BERAT} AS sumber
          FROM (SELECT CAST(:nota AS numeric) AS berat_acuan_kg,
                       CAST(:real AS numeric) AS berat_barang_kg,
                       CAST(NULL AS numeric)  AS netto_timbangan_kg,
                       CAST(:jenis AS text)   AS jenis_kode) t
    """)
    async with pg() as db:
        for nama, jenis, nota, real, harus, sumber in KASUS:
            r = (await db.execute(sql, {"nota": nota, "real": real,
                                        "jenis": jenis, "tol_persen": 0.2})).first()
            py = bobot_efektif(nota=nota, barang=real, netto=None,
                               jenis_kode=jenis, tol_persen=0.2)
            assert float(r.kg) == float(py.kg) == harus, (
                f"{nama}: SQL {r.kg}, Python {py.kg}, seharusnya {harus}")
            assert r.sumber == py.sumber == sumber, (
                f"{nama}: SQL '{r.sumber}', Python '{py.sumber}'")


async def test_batas_diuji_tepat_di_angkanya():
    """Pagar yang meleset satu kilogram tak akan pernah ketahuan dari layar."""
    from app.penggilingan.gudang1.services.timbang_link import bobot_efektif

    def pakai(kurang):
        return bobot_efektif(nota=10_000, barang=10_000 - kurang, netto=None,
                             jenis_kode="GABAH_BASAH", tol_persen=0.2).sumber

    assert pakai(19.9) == "nota"
    assert pakai(20) == "nota", "batasnya sendiri harus MASUK"
    assert pakai(20.1) == "timbangan"
    assert pakai(21) == "timbangan"


async def test_jenis_yang_tak_disebut_pemilik_tak_diberi_toleransi():
    """Tabel jenis punya dua belas; pemilik menyebut tiga. Memberi toleransi
    diam-diam kepada komoditas yang tak ia sebut berarti memutuskan atas
    namanya."""
    from app.penggilingan.gudang1.services.timbang_link import (
        JENIS_BERTOLERANSI, bobot_efektif)

    assert JENIS_BERTOLERANSI == ("GABAH_BASAH",)
    for jenis in ("BERAS_MASUK", "BROKEN_MASUK", "JAGUNG", None):
        b = bobot_efektif(nota=10_000, barang=9_999, netto=None,
                          jenis_kode=jenis, tol_persen=0.2)
        assert b.sumber == "timbangan", f"{jenis} diberi toleransi diam-diam"


async def test_kalimat_sebab_menyebut_angka_yang_dipakai_menelepon_pemasok():
    """Tanpa ini selisih 300 kg cuma jadi angka yang tak seorang pun tahu
    asalnya."""
    from app.penggilingan.gudang1.services.timbang_link import bobot_efektif

    b = bobot_efektif(nota=10_000, barang=9_700, netto=None,
                      jenis_kode="GABAH_BASAH", tol_persen=0.2)
    assert "nota 10.000 kg" in b.sebab
    assert "kurang 300 kg" in b.sebab
    assert "batas 20 kg" in b.sebab
    # Dan saat nota MENANG tak ada yang perlu dijelaskan.
    assert bobot_efektif(nota=10_000, barang=9_990, netto=None,
                         jenis_kode="GABAH_BASAH", tol_persen=0.2).sebab == ""


async def test_setelan_menggeser_batasnya_tanpa_deploy(pg, pemakai):
    """Angkanya di `setelan_pabrik` atas usul QA: penalaran "susut tumbuh
    bersama muatan" adalah tafsir atas kalimat pemilik, bukan kalimatnya."""
    from app.models import User
    from app.services.setelan import (TOL_NOTA_BAWAAN, set_toleransi_nota_persen,
                                      toleransi_nota_persen)

    async with pg() as db:
        assert await toleransi_nota_persen(db) == TOL_NOTA_BAWAAN == 0.2
        u = await db.get(User, pemakai.id)
        await set_toleransi_nota_persen(db, 0.5, user=u)
    async with pg() as db:
        assert await toleransi_nota_persen(db) == 0.5
        # Nol pun sah: nota selalu kalah begitu barangnya kurang.
        u = await db.get(User, pemakai.id)
        await set_toleransi_nota_persen(db, 0, user=u)
    async with pg() as db:
        assert await toleransi_nota_persen(db) == 0.0


async def _tiket(pg, kode: str, jenis: str, nota: float, barang: float) -> int:
    """Satu tiket timbang MASUK yang sudah ditutup, berikut nota & barangnya."""
    from sqlalchemy import text

    async with pg() as db:
        tid = (await db.execute(text("""
            INSERT INTO timbangan_transaksi
                (kode, tanggal, arah, jenis_kode, cara_timbang, timbang1_kg,
                 timbang2_kg, netto_timbangan_kg, berat_barang_kg, berat_acuan_kg,
                 status_tiket, status_transaksi, created_at, updated_at)
            VALUES (:k, current_date, 'MASUK', :j, 'DUA_KALI', 15000, 5000,
                    :netto, :barang, :nota, 'SELESAI', 'AKTIF', now(), now())
            RETURNING id
        """), {"k": kode, "j": jenis, "netto": barang + 50, "barang": barang,
               "nota": nota})).scalar()
        await db.commit()
        return int(tid)


@pytest.mark.parametrize("jenis,nota,barang,harus,sumber", [
    ("GABAH_BASAH", 10_000, 9_990, 10_000, "nota"),        # dalam toleransi
    ("GABAH_BASAH", 10_000, 9_700,  9_700, "timbangan"),   # lewat toleransi
    ("GABAH_KERING", 10_000, 9_990, 9_990, "timbangan"),   # tanpa toleransi
])
async def test_poller_mendarat_di_angka_yang_sama_dengan_layar(
        pg, pemakai, pemasok, jenis, nota, barang, harus, sumber):
    """Batch 'menunggu' yang bobotnya diisi poller harus mendarat di angka yang
    SAMA dengan yang dihitung saat tiketnya dipilih operator.

    Dua jalan berbeda ke satu angka: layar lewat `ambil_tiket` (Python), poller
    lewat `_SQL_SINKRON` (SQL). Yang menulis terakhir adalah poller, jadi
    perbedaan apa pun di sini berarti operator melihat satu angka lalu
    menemukan angka lain di kartunya keesokan hari.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import PurchaseBatch, User
    from app.penggilingan.gudang1.services.timbang_link import (
        ambil_tiket, sinkron_bobot_menunggu)

    kode = f"MSK-{jenis[:2]}-{int(barang)}"
    tid = await _tiket(pg, kode, jenis, nota, barang)

    async with pg() as db:
        t = await ambil_tiket(db, tid)
    assert t is not None
    assert float(t["berat_hpp_kg"]) == harus, "layar menyebut angka lain"
    assert t["sumber_berat"] == sumber

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        db.add(PurchaseBatch(
            kode_batch=f"GB-{kode}", supplier_id=pemasok.id,
            berat_total_kg=None, kondisi_gabah="kering",
            tanggal_pembelian=now_local().date(), waktu_pembelian=now_local(),
            input_by=u.id, flag_unverified=True, sumber_berat="menunggu",
            timbangan_transaksi_id=tid))
        await db.commit()

    async with pg() as db:
        n = await sinkron_bobot_menunggu(db)
    assert n >= 1, "poller tak mengisi satu baris pun"

    async with pg() as db:
        b = (await db.execute(select(PurchaseBatch).where(
            PurchaseBatch.kode_batch == f"GB-{kode}"))).scalars().one()
    assert float(b.berat_total_kg) == harus, "poller mendarat di angka lain"
    assert b.sumber_berat == sumber, (
        "kolom sumber berbohong tentang asal angkanya")
