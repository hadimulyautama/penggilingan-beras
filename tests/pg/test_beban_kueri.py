"""Berapa KUERI yang dikeluarkan tiap layar, dan apakah angkanya tetap sama.

Temuan QA P-S-02, 11 September 2026. Dengan data setahun, QA mengukur:

    /                              7.482 kueri   5,2 detik
    /api/dashboard             6.633 kueri   4,5 detik
    /stok                          6.261 kueri   4,3 detik
    /berjalan                     ±3.657 kueri
    /internal/produksi/operasional 3.670 kueri

Bukan satu kueri yang lambat, melainkan ribuan kueri yang masing-masing
cepat: pola `select(MillingProcess)` tanpa saringan, lalu tiga panggilan per
proses di dalam gelung.

Yang diuji di sini JUMLAH KUERI, bukan waktu. Waktu berubah menurut mesin dan
beban; jumlah kueri adalah sifat kodenya sendiri, dan itulah yang bisa dijaga
sejak sekarang — sebelum datanya menumpuk.

Uji kedua sama pentingnya: hasilnya harus SAMA PERSIS dengan cara lama.
Percepatan yang mengubah angka bukan percepatan, melainkan bug baru yang
lebih cepat.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio

#: Banyaknya proses giling sintetis. Cukup untuk membuat N+1 terlihat jelas
#: (30 proses × 4 kueri = 120), masih cukup ringan untuk dijalankan tiap kali.
JUMLAH_PROSES = 30

#: Langit-langit kueri per layar. Bukan angka keramat: ia sekadar cukup jauh
#: di bawah "satu kueri per proses" sehingga N+1 yang kembali masuk pasti
#: menembusnya, dan cukup longgar untuk perubahan wajar.
BATAS = 50


def _rinci(n) -> str:
    """Pesan gagal yang menunjukkan kueri MANA yang berulang.

    "76 kueri" saja memindahkan pekerjaan mencari ke orang yang membaca
    kegagalannya; yang ia butuhkan adalah nama tabel yang ditanya berkali-kali.
    """
    import collections

    per = collections.Counter(p[:70] for p in n.perintah)
    baris = [f"{v:4}× {k}" for k, v in per.most_common(12)]
    return f"{n.jumlah} kueri:\n" + "\n".join(baris)


async def _semai(pg) -> list[int]:
    """Sebuah pabrik dengan riwayat: 30 proses giling, berikut isi & hasilnya."""
    from app.models import (
        InternalTransfer, MillingProcess, MillingProcessSource,
        MillingProgressLog, PurchaseBatch, Silo, SiloStorage, Supplier, User,
        Warehouse,
    )

    async with pg() as db:
        orang = User(nama="Operator Uji", role="operator", status="aktif")
        pemasok = Supplier(nama_supplier="H. Uji")
        gudang = Warehouse(nama_gudang="Gudang 1 Uji", kode_fungsi="g1")
        db.add_all([orang, pemasok, gudang])
        await db.flush()
        silo = Silo(nama_silo="Silo Uji", warehouse_id=gudang.id,
                    kapasitas_ton=100)
        db.add(silo)
        await db.flush()

        ids = []
        for i in range(JUMLAH_PROSES):
            batch = PurchaseBatch(
                kode_batch=f"GB-UJI-{i:03d}", supplier_id=pemasok.id,
                tanggal_pembelian=datetime.now(timezone.utc).date(),
                waktu_pembelian=datetime.now(timezone.utc),
                berat_total_kg=10_000, kondisi_gabah="basah" if i % 2 else "kering",
                input_by=orang.id, status_batch="digiling")
            db.add(batch)
            await db.flush()

            proc = MillingProcess(
                kode_proses=f"ML-UJI-{i:03d}", status="selesai", silo_id=silo.id,
                berat_gabah_masuk_kg=10_000,
                waktu_mulai=datetime.now(timezone.utc) - timedelta(days=i + 1),
                waktu_selesai=datetime.now(timezone.utc) - timedelta(days=i),
                created_by=orang.id)
            db.add(proc)
            await db.flush()

            isi = SiloStorage(
                silo_id=silo.id, purchase_batch_id=batch.id,
                tipe_masuk="gabah_kering",
                tanggal_masuk=datetime.now(timezone.utc),
                input_by=orang.id, status="digiling")
            db.add(isi)
            await db.flush()
            db.add(MillingProcessSource(
                milling_process_id=proc.id, silo_storage_id=isi.id,
                purchase_batch_id=batch.id, berat_kg=10_000))
            db.add(MillingProgressLog(
                milling_process_id=proc.id, berat_kumulatif_kg=6_000 + i,
                waktu_update=datetime.now(timezone.utc), input_by=orang.id))
            if i % 3 == 0:
                db.add(InternalTransfer(
                    kode_transfer=f"TR-UJI-{i:03d}",
                    milling_process_id=proc.id, berat_kg=1_000,
                    lokasi_tujuan="gudang2",
                    status="terkirim", created_by=orang.id,
                    waktu=datetime.now(timezone.utc)))
            ids.append(proc.id)
        await db.commit()
        return ids


# ─────────────────── Hasilnya harus sama persis ───────────────────

async def test_pk_breakdown_banyak_sama_dengan_satuan(pg):
    """Percepatan yang mengubah angka bukan percepatan."""
    from app.penggilingan.gudang1.services import milling as m

    ids = await _semai(pg)
    async with pg() as db:
        satuan = {i: await m._pk_breakdown(db, i) for i in ids}
        banyak = await m.pk_breakdown_banyak(db, ids)

    assert set(satuan) == set(banyak)
    for i in ids:
        assert satuan[i].produced == banyak[i].produced, i
        assert satuan[i].transferred == banyak[i].transferred, i
        assert satuan[i].tersedia == banyak[i].tersedia, i


async def test_pk_jenis_banyak_sama_dengan_satuan(pg):
    from sqlalchemy import select

    from app.models import MillingProcess
    from app.penggilingan.gudang1.services import milling as m

    ids = await _semai(pg)
    async with pg() as db:
        procs = list((await db.execute(
            select(MillingProcess).where(MillingProcess.id.in_(ids)))).scalars())
        satuan = {p.id: await m.pk_jenis(db, p) for p in procs}
        banyak = await m.pk_jenis_banyak(db, procs)

    assert satuan == banyak


async def test_progress_banyak_sama_dengan_satuan(pg):
    from app.penggilingan.gudang1.services import milling as m

    ids = await _semai(pg)
    async with pg() as db:
        satuan = {i: await m._latest_progress(db, i) for i in ids}
        banyak = await m.progress_banyak(db, ids)

    assert satuan == banyak


# ─────────────────── Berapa kueri yang keluar ───────────────────

async def test_stok_pk_tak_lagi_satu_kueri_per_proses(pg, hitung_kueri):
    """Inilah yang terburuk: `select(MillingProcess)` TANPA saringan apa pun,
    lalu tiga panggilan per proses di dalam gelungnya."""
    from app.services import dashboard

    await _semai(pg)
    async with pg() as db:
        async with hitung_kueri() as n:
            await dashboard._stok_pk(db)
    assert n.jumlah < BATAS, _rinci(n)


async def test_dashboard_utuh_di_bawah_batas(pg, hitung_kueri):
    """Halaman yang dibaca Beranda, /api/dashboard, dan briefing Kantor."""
    from app.services import dashboard

    await _semai(pg)
    async with pg() as db:
        async with hitung_kueri() as n:
            await dashboard.dashboard_data(db)
    assert n.jumlah < BATAS, _rinci(n)


async def test_batch_helper_jumlah_kueri_tetap_walau_prosesnya_bertambah(pg,
                                                                         hitung_kueri):
    """Sifat yang sebenarnya dijaga: jumlah kueri tak bergantung pada jumlah
    baris. Batas angka bisa diperdebatkan; sifat ini tidak."""
    from app.penggilingan.gudang1.services import milling as m

    ids = await _semai(pg)
    async with pg() as db:
        async with hitung_kueri() as sedikit:
            await m.pk_breakdown_banyak(db, ids[:3])
        async with hitung_kueri() as banyak:
            await m.pk_breakdown_banyak(db, ids)
    assert sedikit.jumlah == banyak.jumlah


async def test_stok_pk_gudang1_di_bawah_batas(pg, hitung_kueri):
    """Layar /stok membaca SETIAP giling yang pernah ada."""
    from app.services import stok

    await _semai(pg)
    async with pg() as db:
        async with hitung_kueri() as n:
            await stok.pk_gudang1(db)
    assert n.jumlah < BATAS, _rinci(n)


async def test_laporan_pk_siap_transfer_di_bawah_batas(pg, hitung_kueri):
    from app.services import transfer

    await _semai(pg)
    async with pg() as db:
        async with hitung_kueri() as n:
            await transfer.laporan_pk_siap_transfer(db)
    assert n.jumlah < BATAS, _rinci(n)


async def test_bahan_banyak_sama_dengan_satuan(pg):
    """Isi laporan harus identik — termasuk urutan barisnya."""
    from sqlalchemy import select

    from app.models import MillingProcess
    from app.services import stok

    ids = await _semai(pg)
    async with pg() as db:
        procs = list((await db.execute(
            select(MillingProcess).where(MillingProcess.id.in_(ids))
            .order_by(MillingProcess.id))).scalars())
        satuan = {p.id: await stok._bahan(db, p) for p in procs}
        banyak = await stok._bahan_banyak(db, procs)

    assert satuan == banyak


async def test_mutu_banyak_tetap_satu_kueri(pg, hitung_kueri):
    """Pagar ini semula membandingkan versi satuan dengan versi banyak.

    Sejak rata-rata QC punya SATU sumber (`milling.qc_rata_banyak`, keputusan
    pemilik 24 September 2026), `_mutu` cuma memanggil `_mutu_banyak` untuk satu
    id — perbandingannya jadi benar dengan sendirinya dan tak menjaga apa pun.
    Yang masih bisa rusak, dan yang justru dijaga berkas ini, adalah JUMLAH
    KUERINYA: layar Stok membaca setiap giling yang pernah ada.
    """
    from app.services import stok

    ids = await _semai(pg)
    async with pg() as db:
        async with hitung_kueri() as n:
            peta = await stok._mutu_banyak(db, ids)

    assert set(peta) == set(ids)
    assert n.jumlah == 1, _rinci(n)
