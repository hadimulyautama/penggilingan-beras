"""Perilaku Gudang 2 menurut pemilik — dibuktikan di Postgres, bukan dibaca.

Empat aturan yang berbeda dari produksi sebelum 12 September 2026:
silo yang sedang dipoles MENERIMA PK dan mencatatnya sebagai bahan proses;
sisa saat menutup silo dibandingkan dengan awal + ditambah; penyosohan bisa
berhenti sementara dan jedanya ikut ditutup saat proses selesai; tumpukan
tak berbatas. Ditambah bentuk layar operator: antrean = stok PK.
"""
from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def gudang2(pg):
    """Gudang 2 + Silo A/B, satu operator Gudang 2, satu pemasok, dua batch
    PK luar: satu ditumpuk (15.000 kg), satu langsung ke Silo B (9.800 kg)."""
    from app.database import now_local
    from app.models import Silo, Supplier, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar

    async with pg() as db:
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(g2)
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=g2.id),
                    Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        u = User(nama="Operator Polesan", role="operator", status="aktif",
                 default_warehouse_id=g2.id)
        s = Supplier(nama_supplier="UD Sumber Rejeki")
        db.add_all([u, s])
        await db.flush()
        kini = now_local()
        for kode, kg in (("PKB-20260912-01", 15_000), ("PKB-20260912-02", 9_800)):
            db.add(PkPurchaseBatch(
                kode_batch=kode, supplier_id=s.id, berat_total_kg=kg,
                tanggal_pembelian=date.today(), waktu_pembelian=kini, input_by=u.id,
                status_batch="diterima", flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        await db.refresh(u)
        r1 = await masukkan_pk_luar(db, user=u, kode="PKB-20260912-01", tujuan="ditumpuk")
        await masukkan_pk_luar(db, user=u, kode="PKB-20260912-02", tujuan="silo_b")
        return {"user": u, "intake_tumpukan": r1.intake.id}


async def test_pk_dituang_ke_silo_yang_dipoles_jadi_bahan_proses(pg, gudang2):
    """Awal 9.800 di Silo B, mulai penyosohan, tuang 1.000 dari tumpukan →
    berat_masuk 1.000; tutup dengan sisa 800 → terpakai 10.000, bukan 9.000."""
    from sqlalchemy import select

    from app.penggilingan.gudang2.models import PolishingSiloUsage
    from app.penggilingan.gudang2.polishing import (Gudang2Error, catat_output,
                                                     mulai_penyosohan, selesai_penyosohan)
    from app.penggilingan.gudang2.service import hitung_stok_silo, pindah_tumpukan_ke_silo

    u = gudang2["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])
        assert r.berat_awal_total == 9_800

        p = await pindah_tumpukan_ke_silo(db, user=u, intake_id=gudang2["intake_tumpukan"],
                                          nama_silo="B", berat=1_000)
        assert p.ke_proses == r.proc.kode_proses
        assert p.sisa_tumpukan_intake == 14_000
        usage = (await db.execute(select(PolishingSiloUsage))).scalars().one()
        assert float(usage.berat_masuk_kg) == 1_000
        assert float(usage.berat_awal_kg) == 9_800          # snapshot tak berubah

        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kumulatif=6_500)
        with pytest.raises(Gudang2Error) as e:
            await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                     nama_silo="B", sisa_kg=10_801)
        assert "ditambah 1000" in str(e.value)
        s = await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                     nama_silo="B", sisa_kg=800)
        assert s.selesai and s.terpakai_silo == 10_000
        assert round(s.rendemen, 1) == 65.0
        # Stok silo sesudahnya = sisa yang diketik: 9.800 + 1.000 − 10.000.
        silo_b = usage.silo_id
        assert await hitung_stok_silo(db, silo_b) == 800


async def test_penyosohan_berhenti_sementara_dan_jeda_tertutup_saat_selesai(pg, gudang2):
    from sqlalchemy import select

    from app.models import JedaProses
    from app.penggilingan.gudang1.services.jeda import (JedaError, hentikan, jeda_terbuka,
                                                         lanjutkan)
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, selesai_penyosohan
    from app.services.berjalan import untuk_operator_gudang2

    u = gudang2["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])
        kode = r.proc.kode_proses
        with pytest.raises(JedaError):
            await hentikan(db, user=u, jenis="penyosohan", kode=kode, sebab="Lainnya",
                           sebab_lain="")
        j = await hentikan(db, user=u, jenis="penyosohan", kode=kode, sebab="Listrik padam")
        assert j.kali == 1
        baris = (await db.execute(select(JedaProses))).scalars().one()
        assert baris.jenis == "penyosohan" and baris.polishing_process_id == r.proc.id
        with pytest.raises(JedaError):
            await hentikan(db, user=u, jenis="penyosohan", kode=kode, sebab="Jam kerja habis")

        # Kartu operator berubah rupa selagi berhenti.
        b = await untuk_operator_gudang2(db)
        kartu = next(x for x in b.berjalan if x.kode == kode)
        assert kartu.judul == "Penyosohan dijeda" and kartu.nota_jenis == "hati"
        assert kartu.pilihan[0][0] == "lanjutkan_penyosohan"

        lj = await lanjutkan(db, user=u, jenis="penyosohan", kode=kode)
        assert lj.tertahan_detik is not None
        assert await jeda_terbuka(db, "penyosohan", r.proc.id) is None

        # Berhenti lagi, lalu proses ditutup → jedanya ikut tertutup (P-K-17).
        await hentikan(db, user=u, jenis="penyosohan", kode=kode, sebab="Mesin sosoh rusak")
        await selesai_penyosohan(db, user=u, kode=kode, nama_silo="B", sisa_kg=0)
        assert await jeda_terbuka(db, "penyosohan", r.proc.id) is None


async def test_antrean_operator_adalah_tumpukan_dan_silo(pg, gudang2):
    from app.services.berjalan import untuk_operator_gudang2

    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    tumpuk = [x for x in b.menunggu if x.kelompok == "tumpukan"]
    silo = [x for x in b.menunggu if x.fase == "silo"]
    assert len(tumpuk) == 1 and tumpuk[0].nilai == str(gudang2["intake_tumpukan"])
    assert tumpuk[0].judul == "UD Sumber Rejeki" and tumpuk[0].utama[0] == "15.000"
    assert tumpuk[0].pilihan[0][0] == "pindah_tumpukan_silo"
    assert len(silo) == 1 and silo[0].kode == "Silo B" and silo[0].aksi == "mulai_penyosohan"
    assert b.transit == [] and b.meja == []
    assert b.jumlah_menunggu == 2


async def test_tumpukan_tanpa_batas_kecuali_disetel(pg, gudang2, monkeypatch):
    from app.config import settings
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_pk_luar
    from app.database import now_local

    u = gudang2["user"]
    async with pg() as db:
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20260912-03", supplier_id=1, berat_total_kg=80_000,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(), input_by=u.id,
            status_batch="diterima", flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        monkeypatch.setattr(settings, "g2_tumpukan_maks_kg", 60_000)
        with pytest.raises(Gudang2Error) as e:
            await masukkan_pk_luar(db, user=u, kode="PKB-20260912-03", tujuan="ditumpuk")
        assert "penuh" in str(e.value)
        await db.rollback()
        monkeypatch.setattr(settings, "g2_tumpukan_maks_kg", 0)
        r = await masukkan_pk_luar(db, user=u, kode="PKB-20260912-03", tujuan="ditumpuk")
        assert r.lokasi_label == "tumpukan"
