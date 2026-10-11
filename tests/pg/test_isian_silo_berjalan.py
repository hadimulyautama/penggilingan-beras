"""Daftar asal kartu silo G2 hanya menyebut ISIAN YANG SEDANG BERJALAN.

Galat yang dilaporkan pemilik 23 September 2026 21:33 dan diukur QA
(`QA/alat/p17/v_riwayat_silo.py`, lihat QA-2026-09-23-silo-g2-LANJUTAN.md):
Silo A · Gudang 2 berjudul 3.416 kg tetapi masih mendaftar tiga lot dari isian
sebelumnya yang sudah habis disosoh.

`_asal_pk` tak punya batas waktu sama sekali — ia mengambil seluruh
`pk_gudang2_intakes` dan `PkTumpukanToSilo` untuk silo itu sejak kapan pun.

Bedanya dengan temuan siang hari itu penting: DI DALAM satu isian, judul lebih
kecil dari jumlah daftar memang wajar (sebagian sudah masuk mesin) — itu soal
label. SESUDAH silo kosong, lot lama bukan "sebagian terpakai" lagi melainkan
HABIS, dan menyebutnya sebagai asal isi silo sekarang adalah keterangan yang
SALAH.

Yang TIDAK diubah, dan tetap benar: sisa per lot tak dihitung dan tak dikarang.
Stok silo satu jumlah, bukan lapisan. Yang diperbaiki cakupan waktunya.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def silo(pg, pemakai):
    """Satu silo Gudang 2, dan orang yang mencatat."""
    from app.models import Silo, Warehouse

    async with pg() as db:
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(g2)
        await db.flush()
        s = Silo(nama_silo="Silo A", warehouse_id=g2.id)
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def _masuk(pg, silo_id, pemakai, pemasok, *, kode_batch, kg, jam):
    """Satu PK luar masuk langsung ke silo, pada waktu tertentu."""
    from app.models import PkGudang2Intake
    from app.penggilingan.gudang2.models import PkPurchaseBatch

    async with pg() as db:
        b = PkPurchaseBatch(kode_batch=kode_batch, supplier_id=pemasok.id,
                            berat_total_kg=kg,
                            tanggal_pembelian=(T0 + timedelta(hours=jam)).date(),
                            waktu_pembelian=T0 + timedelta(hours=jam),
                            status_batch="diterima", input_by=pemakai.id)
        db.add(b)
        await db.flush()
        db.add(PkGudang2Intake(
            sumber_tipe="pk_luar", pk_purchase_batch_id=b.id, tujuan="silo_a",
            silo_id=silo_id, berat_kg=kg, tanggal_masuk=(T0 + timedelta(hours=jam)).date(),
            waktu_masuk=T0 + timedelta(hours=jam), input_by=pemakai.id))
        await db.commit()


async def _sosoh(pg, silo_id, pemakai, *, kg, jam, selesai=True):
    """Satu penyosohan yang MENGURANGI silo — hanya bila berat_akhir terisi."""
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage

    async with pg() as db:
        pr = PolishingProcess(
            kode_proses=f"POL-{jam:04d}", waktu_mulai=T0 + timedelta(hours=jam),
            waktu_selesai=(T0 + timedelta(hours=jam, minutes=30)) if selesai else None,
            status="selesai" if selesai else "proses", created_by=pemakai.id)
        db.add(pr)
        await db.flush()
        db.add(PolishingSiloUsage(
            polishing_process_id=pr.id, silo_id=silo_id, berat_awal_kg=kg,
            berat_akhir_kg=(0 if selesai else None),
            berat_terpakai_kg=(kg if selesai else None)))
        await db.commit()


async def _daftar(pg, silo_id):
    from app.penggilingan.gudang2.service import hitung_stok_silo
    from app.services.berjalan import _isian_silo

    async with pg() as db:
        isian = await _isian_silo(db, silo_id)
        return isian, float(await hitung_stok_silo(db, silo_id))


async def test_tiga_lot_masuk_judul_sama_dengan_daftar(pg, silo, pemakai, pemasok):
    """Langkah 1 tabel QA: belum ada penyosohan, jadi tak ada yang dibatasi."""
    for n, kg in enumerate((10_000, 3_000, 10_000), start=1):
        await _masuk(pg, silo, pemakai, pemasok, kode_batch=f"PKB-A{n}", kg=kg, jam=n)

    isian, stok = await _daftar(pg, silo)
    assert len(isian.baris) == 3
    assert isian.masuk_kg == 23_000 and stok == 23_000
    assert isian.disosoh_kg == 0
    # Selisih nol → tak ada kalimat yang perlu ditampilkan.
    from app.services.berjalan import _nota_isian
    assert _nota_isian(isian) is None


async def test_sesudah_silo_kosong_isian_lama_tak_didaftar(pg, silo, pemakai, pemasok):
    """Langkah 2 & 3 — inti galatnya.

    Pada 3802ae8 daftar tetap 3 baris / 23.000 kg saat silo KOSONG, lalu 4 baris
    / 26.416 kg sesudah diisi 3.416 kg. Itu persis layar pemilik 21:33.
    """
    for n, kg in enumerate((10_000, 3_000, 10_000), start=1):
        await _masuk(pg, silo, pemakai, pemasok, kode_batch=f"PKB-B{n}", kg=kg, jam=n)
    await _sosoh(pg, silo, pemakai, kg=23_000, jam=10)          # seluruhnya

    isian, stok = await _daftar(pg, silo)
    assert stok == 0, "silo harus kosong"
    assert isian.baris == [], "isian yang sudah habis masih didaftar"

    # Diisi lagi: hanya lot BARU yang boleh terdaftar, dan judul = beratnya.
    await _masuk(pg, silo, pemakai, pemasok, kode_batch="PKB-BARU", kg=3_416, jam=20)
    isian, stok = await _daftar(pg, silo)
    assert stok == 3_416
    assert len(isian.baris) == 1, f"masih menyebut isian lama: {isian.baris}"
    assert "PKB-BARU" in isian.baris[0][0]
    assert isian.masuk_kg == 3_416 and isian.disosoh_kg == 0


async def test_snapshot_asal_lot_proses_tetap_ada_setelah_silo_dikosongkan(
    pg, silo, pemakai, pemasok,
):
    """Kartu proses tetap dapat membaca asal input dari saat proses dimulai."""
    await _masuk(pg, silo, pemakai, pemasok,
                 kode_batch="PKB-SNAPSHOT", kg=871, jam=1)
    mulai_proses = T0 + timedelta(hours=2)
    await _sosoh(pg, silo, pemakai, kg=871, jam=10)

    from app.services.berjalan import _isian_silo

    async with pg() as db:
        sekarang = await _isian_silo(db, silo)
        snapshot = await _isian_silo(db, silo, sampai=mulai_proses)

    assert sekarang.baris == [], "isian silo saat ini memang sudah habis"
    assert len(snapshot.baris) == 1
    assert "PKB-SNAPSHOT" in snapshot.baris[0][0]
    assert snapshot.baris[0][1] == "871 kg"


async def test_penyosohan_sebagian_seluruh_isian_tetap_terdaftar(pg, silo, pemakai, pemasok):
    """Silo yang tak pernah nol: seluruh isian berjalan tetap disebut — dan
    selisihnya kini PUNYA NAMA, bukan dibiarkan terbaca sebagai salah jumlah."""
    await _masuk(pg, silo, pemakai, pemasok, kode_batch="PKB-C1", kg=20_000, jam=1)
    await _masuk(pg, silo, pemakai, pemasok, kode_batch="PKB-C2", kg=3_000, jam=2)
    await _sosoh(pg, silo, pemakai, kg=13_000, jam=5)           # sebagian

    isian, stok = await _daftar(pg, silo)
    assert stok == 10_000
    assert len(isian.baris) == 2, "penyosohan sebagian tak boleh memotong daftar"
    assert isian.masuk_kg == 23_000 and isian.disosoh_kg == 13_000

    from app.services.berjalan import _nota_isian
    nota = _nota_isian(isian)
    assert "23.000 kg masuk" in nota and "13.000 kg sudah disosoh" in nota


async def test_sebagian_lalu_masuk_lagi_memuat_keduanya(pg, silo, pemakai, pemasok):
    """Silo tak pernah mencapai nol → isian berjalan mencakup keduanya."""
    await _masuk(pg, silo, pemakai, pemasok, kode_batch="PKB-D1", kg=20_000, jam=1)
    await _sosoh(pg, silo, pemakai, kg=13_000, jam=5)
    await _masuk(pg, silo, pemakai, pemasok, kode_batch="PKB-D2", kg=5_000, jam=9)

    isian, stok = await _daftar(pg, silo)
    assert stok == 12_000
    assert len(isian.baris) == 2
    assert {"PKB-D1", "PKB-D2"} <= {b[0].split(" · ")[-1] for b in isian.baris}


async def test_lot_giling_sama_masuk_dua_kali_tetap_dua_baris(pg, silo, pemakai):
    """Satu lot giling bisa dikirim ke silo DUA KALI, dan keduanya benar.

    Yang dilarang `uq_pk_gudang2_intakes_transfer` adalah TRANSFER yang sama
    masuk dua kali — bukan lot yang sama. Dua pengiriman dari satu lot adalah
    dua peristiwa, dan meringkasnya jadi satu baris menyembunyikan salah satu
    pengiriman. (Batasan `uq_pk_gudang2_intakes_batch` menutup jalur PK luar
    dengan cara yang sama; di sana satu batch memang hanya sekali masuk.)
    """
    from app.models import InternalTransfer, PkGudang2Intake, Silo, Warehouse
    from app.penggilingan.gudang1.models.milling import MillingProcess

    async with pg() as db:
        # Lot giling lahir di Gudang 1, jadi ia perlu silo G1 sebagai asalnya.
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        db.add(g1)
        await db.flush()
        s1 = Silo(nama_silo="Silo G1", warehouse_id=g1.id)
        db.add(s1)
        await db.flush()
        pr = MillingProcess(kode_proses="LOT-20260911-01", silo_id=s1.id,
                            waktu_mulai=T0, created_by=pemakai.id)
        db.add(pr)
        await db.flush()
        for n, (jam, kg) in enumerate(((1, 4_000), (3, 5_000)), start=1):
            trf = InternalTransfer(
                kode_transfer=f"TRF-{n:03d}", milling_process_id=pr.id, berat_kg=kg,
                lokasi_tujuan="gudang2", waktu=T0 + timedelta(hours=jam),
                created_by=pemakai.id)
            db.add(trf)
            await db.flush()
            db.add(PkGudang2Intake(
                sumber_tipe="giling", internal_transfer_id=trf.id, tujuan="silo_a",
                silo_id=silo, berat_kg=kg,
                tanggal_masuk=(T0 + timedelta(hours=jam)).date(),
                waktu_masuk=T0 + timedelta(hours=jam), input_by=pemakai.id))
        await db.commit()

    isian, stok = await _daftar(pg, silo)
    assert stok == 9_000
    assert len(isian.baris) == 2, "dua pengiriman satu lot diringkas jadi satu baris"
    # Keduanya menyebut lot yang sama — itulah benang ke gabah & pemasoknya.
    assert all("LOT-20260911-01" in b[0] for b in isian.baris)
    # Dan waktunya yang membedakan keduanya di layar.
    assert isian.baris[0][2] != isian.baris[1][2] or isian.baris[0][1] != isian.baris[1][1]


async def test_penyosohan_belum_selesai_belum_mengurangi(pg, silo, pemakai, pemasok):
    """Patokan yang SAMA dengan `hitung_stok_silo`: hanya penyosohan yang
    `berat_akhir_kg`-nya sudah terisi. Proses yang masih jalan belum mengurangi
    apa pun, jadi ia tak boleh memotong daftar."""
    await _masuk(pg, silo, pemakai, pemasok, kode_batch="PKB-F1", kg=8_000, jam=1)
    await _sosoh(pg, silo, pemakai, kg=8_000, jam=4, selesai=False)

    isian, stok = await _daftar(pg, silo)
    assert stok == 8_000, "proses berjalan tak boleh mengurangi stok"
    assert len(isian.baris) == 1


async def test_belum_pernah_disosoh_tak_ada_yang_berubah(pg, silo, pemakai, pemasok):
    """Silo yang belum pernah disosoh: daftarnya seluruh riwayat, seperti dulu."""
    for n in range(1, 4):
        await _masuk(pg, silo, pemakai, pemasok, kode_batch=f"PKB-G{n}", kg=1_000 * n, jam=n)

    isian, _ = await _daftar(pg, silo)
    assert len(isian.baris) == 3 and isian.disosoh_kg == 0


async def test_lebih_dari_enam_asal_jumlahnya_disebut(pg, silo, pemakai, pemasok):
    """`BATAS_ASAL` tetap, tetapi yang terpotong TIDAK didiamkan — kartu yang
    memotong tanpa memberi tahu membuat orang mengira itulah seluruhnya."""
    from app.services.berjalan import BATAS_ASAL, _nota_isian

    for n in range(1, BATAS_ASAL + 3):
        await _masuk(pg, silo, pemakai, pemasok, kode_batch=f"PKB-H{n}", kg=1_000, jam=n)

    isian, _ = await _daftar(pg, silo)
    assert len(isian.baris) == BATAS_ASAL
    assert isian.lebih == 2
    assert "+2 asal lagi" in _nota_isian(isian)


# ══════ Kartu Penyosohan gabungan silo — "yang tercatat hanya 5" ══════
#
# Laporan lapangan 6 Oktober 2026: "silo ditambahkan lagi beberapa, tetapi
# tidak tercatat, yang tercatat hanya 5 kali awal masukan pk." Bukan
# kegagalan MENCATAT — PK-nya tetap masuk database dan tetap dihitung ke
# fakta "Ditambah" — tetapi `_kartu_penyosohan_g2` memangkas daftar asalnya
# DUA KALI (sekali per silo di dalam `_isian_silo`, sekali lagi menggabung
# dua silo) tanpa sepatah kata pun, berbeda dari kartu silo tunggal yang
# sudah menyebutnya lewat `_nota_isian`.

async def test_kartu_sosoh_gabungan_menyebut_baris_yang_terpotong(pg, pemakai, pemasok):
    from app.models import Silo, Warehouse
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage
    from app.services.berjalan import BATAS_ASAL, untuk_gudang2

    async with pg() as db:
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(g2)
        await db.flush()
        silo_a = Silo(nama_silo="Silo A", warehouse_id=g2.id)
        silo_b = Silo(nama_silo="Silo B", warehouse_id=g2.id)
        db.add_all([silo_a, silo_b])
        await db.flush()
        silo_a_id, silo_b_id = silo_a.id, silo_b.id
        await db.commit()

    # Delapan kali masuk per silo — DUA kali lebih banyak daripada
    # `BATAS_ASAL`, persis bentuk keluhannya: "ditambahkan lagi beberapa".
    for n in range(1, 9):
        await _masuk(pg, silo_a_id, pemakai, pemasok, kode_batch=f"PKB-A{n}", kg=1_000, jam=n)
        await _masuk(pg, silo_b_id, pemakai, pemasok, kode_batch=f"PKB-B{n}", kg=1_000, jam=n)

    async with pg() as db:
        pr = PolishingProcess(
            kode_proses="POL-GAB-01", waktu_mulai=T0, status="proses",
            created_by=pemakai.id)
        db.add(pr)
        await db.flush()
        # `berat_masuk_kg` TERPISAH dari baris `pk_gudang2_intakes` di atas —
        # inilah yang dibaca fakta "Ditambah", dan ia TIDAK BOLEH terpengaruh
        # oleh potongan tampilan daftar asalnya.
        db.add_all([
            PolishingSiloUsage(polishing_process_id=pr.id, silo_id=silo_a_id,
                              berat_awal_kg=0, berat_masuk_kg=8_000),
            PolishingSiloUsage(polishing_process_id=pr.id, silo_id=silo_b_id,
                              berat_awal_kg=0, berat_masuk_kg=8_000),
        ])
        await db.commit()

    async with pg() as db:
        b = await untuk_gudang2(db)
    baris = next(x for x in b.berjalan if x.kode == "POL-GAB-01")

    # Fakta "Ditambah" tetap benar — dijumlah dari SELURUH baris, bukan dari
    # daftar yang dipotong untuk tampilan.
    fakta = dict(baris.fakta)
    assert fakta["Ditambah"] == "16.000 kg"

    # Daftarnya sendiri dibatasi (kartu tak boleh tak berhingga panjangnya)
    # — tetapi potongannya WAJIB disebut, bukan didiamkan.
    assert len(baris.anak) <= 10
    # 8 per silo − BATAS_ASAL(6) tersisa di dalam `_isian_silo` = 2 per
    # silo yang bahkan tak sempat digabung (asal_lebih = 4), ditambah
    # potongan gabungan terakhir di `[:10]`.
    assert baris.nota is not None and "baris lagi tak ditampilkan" in baris.nota
    lebih = int(baris.nota.split("+")[1].split(" ")[0])
    # 2 per silo terpotong DI DALAM `_isian_silo` (8 − BATAS_ASAL) + 2 lagi
    # terpotong saat 12 baris asal gabungan dijejalkan ke batas kartu [:10].
    assert lebih == 2 * (8 - BATAS_ASAL) + 2 == 6
