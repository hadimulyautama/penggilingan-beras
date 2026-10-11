"""Silo broken — satu wadah, dua arah, satu pemilik pada satu waktu.

Keputusan pemilik 6 Oktober 2026: broken (PK yang sudah disosoh, patah)
punya silonya sendiri (`Silo.jenis_isi`), supaya ia bisa disosoh ULANG
sebagai bahan baku. Berkas ini membuktikan di Postgres sungguhan: segregasi
PK/broken per silo, pewarisan pemilik lewat `broken_ke_silo`, pagar "proses
tak boleh memakan broken yang ia hasilkan sendiri", rendemen atas SELURUH
bahan (bukan PK saja), dan `sisa_jasa()` yang tidak menghitung broken dua
kali saat ia disosoh ulang.
"""
from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def dunia(pg):
    """Gudang 2: Silo A (PK) + Silo C (broken). Satu operator, satu pesanan
    jasa (Bu Sri), 10.000 kg PK milik jasa itu sudah di Silo A."""
    from app.database import now_local
    from app.models import Jasa, Pelanggan, Silo, Supplier, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import (masukkan_pk_luar,
                                                   pindah_tumpukan_ke_silo)

    async with pg() as db:
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(g2)
        await db.flush()
        silo_pk = Silo(nama_silo="Silo A", warehouse_id=g2.id, jenis_isi="pk")
        silo_broken = Silo(nama_silo="Silo C", warehouse_id=g2.id, jenis_isi="broken")
        db.add_all([silo_pk, silo_broken])
        u = User(nama="Operator Polesan", role="operator", status="aktif",
                 default_warehouse_id=g2.id)
        s = Supplier(nama_supplier="UD Sumber Rejeki")
        pel = Pelanggan(nama_pelanggan="Bu Sri")
        db.add_all([u, s, pel])
        await db.flush()
        jasa = Jasa(kode="JAS-2610-001", pelanggan_id=pel.id, status="berjalan")
        db.add(jasa)
        await db.flush()
        kini = now_local()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20261006-01", jasa_id=jasa.id, berat_total_kg=10_000,
            tanggal_pembelian=date.today(), waktu_pembelian=kini, input_by=u.id,
            status_batch="diterima", flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        await db.refresh(u)
        r = await masukkan_pk_luar(db, user=u, kode="PKB-20261006-01", tujuan="ditumpuk")
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=r.intake.id,
                                      nama_silo="A", berat=10_000)
        return {"user": u, "jasa_id": jasa.id,
                "silo_pk": silo_pk.id, "silo_broken": silo_broken.id}


# ═══════════════════════ Segregasi PK / broken ═══════════════════════

async def test_pk_tak_bisa_masuk_silo_broken(pg, dunia):
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_tumpukan_ke_silo
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.database import now_local

    u = dunia["user"]
    async with pg() as db:
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20261006-02", supplier_id=None, jasa_id=dunia["jasa_id"],
            berat_total_kg=500, tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, status_batch="diterima",
            flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        from app.penggilingan.gudang2.service import masukkan_pk_luar
        r = await masukkan_pk_luar(db, user=u, kode="PKB-20261006-02", tujuan="ditumpuk")
        with pytest.raises(Gudang2Error, match="bukan silo PK"):
            await pindah_tumpukan_ke_silo(db, user=u, intake_id=r.intake.id,
                                          nama_silo="C", berat=500)


async def test_broken_tak_bisa_masuk_silo_pk(pg, dunia):
    from app.penggilingan.inventory.finished_goods import catat_broken
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, catat_output
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_broken_ke_silo

    u = dunia["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kg=9_000)
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="broken",
                           berat_kg=900)
        await catat_broken(db, user=u, kode_pol=r.proc.kode_proses, berat_kg=900)
        from sqlalchemy import select
        from app.models import ByproductStock
        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        with pytest.raises(Gudang2Error, match="bukan silo broken"):
            await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                        nama_silo="A", berat=900)


# ═══════════════════════ Stok silo broken ═══════════════════════

async def test_stok_silo_broken_masuk_dikurangi_terpakai(pg, dunia):
    """Broken dicatat curah, dipindah ke silo C, lalu disosoh ulang — stok
    silo C bertambah saat dipindah dan berkurang saat ditutup (terpakai)."""
    from sqlalchemy import select

    from app.models import ByproductStock
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     selesai_penyosohan)
    from app.penggilingan.gudang2.service import (hitung_stok_silo,
                                                   pindah_broken_ke_silo)
    from app.penggilingan.inventory.finished_goods import catat_broken

    u = dunia["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kg=9_000)
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="broken",
                           berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=r.proc.kode_proses, berat_kg=1_000)
        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)

        m = await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                        nama_silo="C", berat=600)
        assert m.berat_kg == 600
        assert m.sisa_broken == 400
        assert await hitung_stok_silo(db, dunia["silo_broken"]) == 600

        # Sosoh ulang: mulai dari silo C, tutup dengan sisa 100 → terpakai 500.
        r2 = await mulai_penyosohan(db, user=u, nama_silos=["C"])
        assert r2.berat_awal_total == 600
        await catat_output(db, user=u, kode=r2.proc.kode_proses, jenis="premium",
                           berat_kg=400)
        await selesai_penyosohan(db, user=u, kode=r2.proc.kode_proses,
                                 nama_silo="C", sisa_kg=100)
        assert await hitung_stok_silo(db, dunia["silo_broken"]) == 100


# ═══════════════════════ Pemilik & pagar ═══════════════════════

async def test_broken_jasa_mewarisi_pemilik_ke_silo_dan_sosoh_ulang(pg, dunia):
    """PK milik jasa → broken yang keluar tetap milik jasa (keputusan
    pemilik 12: broken KEMBALI) → silo broken ikut bertuan → sosoh ulang
    tetap atas nama jasa yang sama."""
    from sqlalchemy import select

    from app.models import ByproductStock
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     selesai_penyosohan)
    from app.penggilingan.gudang2.service import pindah_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import catat_broken
    from app.services.jasa import pemilik_silo_g2

    u = dunia["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        assert r.proc.jasa_id == dunia["jasa_id"]
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kg=9_000)
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="broken",
                           berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=r.proc.kode_proses, berat_kg=1_000)
        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        assert row.jasa_id == dunia["jasa_id"]
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)

        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                    nama_silo="C", berat=1_000)
        assert await pemilik_silo_g2(db, dunia["silo_broken"]) == {dunia["jasa_id"]}

        r2 = await mulai_penyosohan(db, user=u, nama_silos=["C"])
        assert r2.proc.jasa_id == dunia["jasa_id"]


async def test_silo_broken_menolak_pemilik_campur(pg, dunia):
    """Silo broken berisi broken Bu Sri — broken pabrik tak boleh dituang
    ke sana sampai silonya kosong lagi."""
    from sqlalchemy import select

    from app.models import ByproductStock
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     selesai_penyosohan)
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import catat_broken

    u = dunia["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kg=9_000)
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="broken",
                           berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=r.proc.kode_proses, berat_kg=1_000)
        row_jasa = (await db.execute(select(ByproductStock)
                                     .where(ByproductStock.jenis_produk == "broken"))
                   ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row_jasa.id,
                                    nama_silo="C", berat=1_000)

        # Broken PABRIK (proses tanpa jasa) — bikin lewat silo A yang sudah
        # kosong lagi (pabrik), lalu catat broken-nya.
        from app.models import PkPurchaseBatch, Supplier
        from app.database import now_local
        s = Supplier(nama_supplier="Pabrik Sendiri")
        db.add(s)
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20261006-99", supplier_id=s.id, berat_total_kg=5_000,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        from app.penggilingan.gudang2.service import (masukkan_pk_luar,
                                                       pindah_tumpukan_ke_silo)
        ri = await masukkan_pk_luar(db, user=u, kode="PKB-20261006-99", tujuan="ditumpuk")
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=ri.intake.id,
                                      nama_silo="A", berat=5_000)
        r3 = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        assert r3.proc.jasa_id is None
        await catat_output(db, user=u, kode=r3.proc.kode_proses, jenis="premium",
                           berat_kg=4_500)
        await catat_output(db, user=u, kode=r3.proc.kode_proses, jenis="broken",
                           berat_kg=400)
        await catat_broken(db, user=u, kode_pol=r3.proc.kode_proses, berat_kg=400)
        row_pabrik = (await db.execute(
            select(ByproductStock).where(ByproductStock.jenis_produk == "broken",
                                         ByproductStock.source_id == r3.proc.id))
                     ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r3.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)

        with pytest.raises(Gudang2Error, match="tidak boleh digabung"):
            await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row_pabrik.id,
                                        nama_silo="C", berat=400)


async def test_proses_tak_boleh_memakan_broken_sendiri(pg, dunia):
    """Pagar 6a: broken yang KELUAR dari proses P2 tak bisa dipindah ke silo
    yang SEDANG dipakai P2 sendiri sebelum prosesnya ditutup.

    Disiapkan: proses P1 (Silo A) menghasilkan 500 kg broken, dipindah ke
    Silo C. Proses P2 lalu MULAI dari Silo C (berisi 500 kg) — kini P2
    sedang memakai Silo C. P2 sendiri menghasilkan broken baru; broken itu
    TAK BOLEH dipindah ke Silo C selagi P2 masih memakainya — fisiknya
    mustahil, broken itu baru keluar dari mesin yang sama yang sedang
    menyosoh Silo C.
    """
    from sqlalchemy import select

    from app.models import ByproductStock
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     selesai_penyosohan)
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import catat_broken

    u = dunia["user"]
    async with pg() as db:
        r1 = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r1.proc.kode_proses, jenis="premium",
                           berat_kg=9_500)
        await catat_output(db, user=u, kode=r1.proc.kode_proses, jenis="broken",
                           berat_kg=500)
        await catat_broken(db, user=u, kode_pol=r1.proc.kode_proses, berat_kg=500)
        row1 = (await db.execute(select(ByproductStock)
                                 .where(ByproductStock.jenis_produk == "broken"))
               ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r1.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row1.id,
                                   nama_silo="C", berat=500)

        r2 = await mulai_penyosohan(db, user=u, nama_silos=["C"])
        await catat_output(db, user=u, kode=r2.proc.kode_proses, jenis="broken",
                           berat_kg=50)
        await catat_broken(db, user=u, kode_pol=r2.proc.kode_proses, berat_kg=50)
        row2 = (await db.execute(
            select(ByproductStock).where(ByproductStock.jenis_produk == "broken",
                                         ByproductStock.source_id == r2.proc.id))
               ).scalars().one()

        with pytest.raises(Gudang2Error, match="SEDANG memakai"):
            await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row2.id,
                                        nama_silo="C", berat=50)


# ═══════════════════════ Rendemen atas seluruh bahan ═══════════════════════

async def test_rendemen_proses_campuran_pk_dan_broken_atas_seluruh_bahan(pg, dunia):
    """Satu proses sosoh dari Silo A (PK) + Silo C (broken) — penyebut
    rendemen = PK terpakai + broken terpakai, bukan PK saja."""
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     rendemen_proses, selesai_penyosohan)
    from app.penggilingan.gudang2.service import pindah_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import catat_broken
    from sqlalchemy import select
    from app.models import ByproductStock

    u = dunia["user"]
    async with pg() as db:
        # Lahirkan 1.000 kg broken (masih milik jasa Bu Sri — Silo A di
        # `dunia` jasa-owned) dari proses terpisah, taruh di Silo C.
        r0 = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r0.proc.kode_proses, jenis="premium",
                           berat_kg=8_000)
        await catat_output(db, user=u, kode=r0.proc.kode_proses, jenis="broken",
                           berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=r0.proc.kode_proses, berat_kg=1_000)
        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r0.proc.kode_proses,
                                 nama_silo="A", sisa_kg=1_000)
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                    nama_silo="C", berat=1_000)

        # Isi ulang Silo A dengan PK baru — SAMA jasanya (Silo A masih
        # bersisa 1.000 kg jasa, jadi tambahan ini WAJIB sepemilik juga;
        # `pastikan_satu_pemilik` tetap menolak pabrik masuk ke silo berisi
        # barang titipan — itu bukan soal pelanggan sama, batasan itu TAK
        # dicabut 10 Oktober 2026, hanya digabung-otomatis-kan untuk
        # pelanggan yang sama).
        from app.models import PkPurchaseBatch
        from app.database import now_local
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20261006-77", jasa_id=dunia["jasa_id"],
            berat_total_kg=4_000, tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, status_batch="diterima",
            flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        from app.penggilingan.gudang2.service import (masukkan_pk_luar,
                                                       pindah_tumpukan_ke_silo)
        ri = await masukkan_pk_luar(db, user=u, kode="PKB-20261006-77", tujuan="ditumpuk")
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=ri.intake.id,
                                      nama_silo="A", berat=4_000)

        # Proses campuran: Silo A (sisa 1.000 + baru 4.000 = 5.000 kg PK) +
        # Silo C (1.000 kg broken) — keduanya milik jasa yang sama.
        r = await mulai_penyosohan(db, user=u, nama_silos=["A", "C"])
        assert r.berat_awal_total == 5_000 + 1_000
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kg=5_000)
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=600)
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="C", sisa_kg=0)
        rend = await rendemen_proses(db, r.proc.id)
        # bahan = PK terpakai (5.000 - 600 = 4.400) + broken terpakai
        # (1.000 - 0 = 1.000) = 5.400 — BUKAN 4.400 (PK saja), yang akan
        # membuat rendemen terbaca "bagus" semata karena sebagian bahannya
        # sudah pernah disosoh.
        assert rend == pytest.approx(5_000 / 5_400 * 100)


# ═══════════════════════ sisa_jasa() — tak dihitung dua kali ═══════════════════════

async def test_sisa_jasa_broken_tak_dihitung_dua_kali_saat_disosoh_ulang(pg, dunia):
    """Broken jasa tercatat curah → sisa_jasa().broken_kg > 0. Dipindah ke
    silo → tetap > 0 (belum disosoh). Disosoh ulang & ditutup → broken_kg
    kembali ke 0 (bukan dua kali terhitung bersama hasil barunya)."""
    from sqlalchemy import select

    from app.models import ByproductStock
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     selesai_penyosohan)
    from app.penggilingan.gudang2.service import pindah_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import catat_broken
    from app.services.jasa import sisa_jasa

    u = dunia["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kg=9_000)
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="broken",
                           berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=r.proc.kode_proses, berat_kg=1_000)
        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)

        sisa = await sisa_jasa(db, dunia["jasa_id"])
        assert sisa.broken_kg == pytest.approx(1_000)

        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                    nama_silo="C", berat=1_000)
        sisa = await sisa_jasa(db, dunia["jasa_id"])
        assert sisa.broken_kg == pytest.approx(1_000)   # masih ada, belum disosoh

        r2 = await mulai_penyosohan(db, user=u, nama_silos=["C"])
        await catat_output(db, user=u, kode=r2.proc.kode_proses, jenis="menir",
                           berat_kg=900)
        await selesai_penyosohan(db, user=u, kode=r2.proc.kode_proses,
                                 nama_silo="C", sisa_kg=0)

        sisa = await sisa_jasa(db, dunia["jasa_id"])
        assert sisa.broken_kg == pytest.approx(0)
        # Hasil BARUNYA (menir) belum dikemas — bukan bagian pagar ini (gap
        # yang sudah ada untuk SELURUH output sebelum packing, lihat
        # `barang_jadi_kg`), tapi total tak boleh diam-diam dobel di broken.


# ═══════════════════════ Stok curah — tiga suku ═══════════════════════

async def test_hitung_stok_broken_curah_tiga_suku(pg, dunia):
    from app.penggilingan.gudang2.polishing import catat_output, mulai_penyosohan
    from app.penggilingan.gudang2.service import pindah_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import (catat_broken,
                                                           hitung_stok_broken_curah)
    from sqlalchemy import select
    from app.models import ByproductStock

    u = dunia["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="broken",
                           berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=r.proc.kode_proses, berat_kg=1_000)
        assert await hitung_stok_broken_curah(db, jasa_id=dunia["jasa_id"]) == 1_000

        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                    nama_silo="C", berat=400)
        # masuk 1.000 - terpakai(dipindah) 400 = 600.
        assert await hitung_stok_broken_curah(db, jasa_id=dunia["jasa_id"]) == 600


# ═══════════════ Silo broken sebagai bahan TAMBAHAN mid-proses ═══════════════
#
# Laporan lapangan 11 Oktober 2026: operator menyosoh dengan kadar broken
# rendah, dan ingin menambahkan broken yang SUDAH ada di silo (hasil proses
# lain yang sudah selesai) sebagai campuran bahan ke proses yang SEDANG
# berjalan — jalurnya `tambah_silo_penyosohan`, BUKAN "Masukkan broken ke
# silo" (itu untuk MENYIMPAN hasil broken, bukan menambahkannya sebagai
# bahan). `silo-bahan-g2` dan `tambah_silo_penyosohan` SUDAH silo-agnostic
# (`PolishingSiloUsage` tak peduli isi silonya) — berkas ini membuktikannya
# lewat jalur mid-proses secara eksplisit, plus pagar baru "proses tak boleh
# memakan broken hasil dirinya sendiri" yang BELUM ada sebelumnya di arah ini.

async def test_picker_silo_bahan_g2_menawarkan_silo_broken_berisi(pg, dunia):
    """`/api/actions/silo-bahan-g2` TIDAK menyaring `jenis_isi` — silo broken
    berisi stok dan belum dipakai proses berjalan WAJIB ikut tertawar, sama
    seperti silo PK. Laporan lapangan sempat menduga picker ini hanya
    menawarkan silo PK; buktinya dari jalur HTTP langsung, bukan tebakan."""
    from sqlalchemy import select

    from app.models import ByproductStock, User
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     selesai_penyosohan)
    from app.penggilingan.gudang2.service import pindah_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import catat_broken
    from app.web.api import silo_bahan_g2

    u = dunia["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kg=9_500)
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="broken",
                           berat_kg=500)
        await catat_broken(db, user=u, kode_pol=r.proc.kode_proses, berat_kg=500)
        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                    nama_silo="C", berat=500)

    async with pg() as db:
        uu = await db.get(User, u.id)
        daftar = await silo_bahan_g2(user=uu)
    assert "C" in [x["value"] for x in daftar], \
        f"Silo C (broken, berisi) hilang dari picker: {daftar}"


async def test_tambah_silo_penyosohan_terima_broken_sebagai_campuran(pg, dunia):
    """Proses P1 (Silo A) menghasilkan broken, dipindah ke Silo C, SELESAI.
    Silo A diisi ulang (jasa sama). Proses P2 BARU mulai dari Silo A saja,
    lalu `tambah_silo_penyosohan` menambahkan Silo C (broken) sebagai bahan
    MID-PROSES — stok yang ditambahkan dan rendemen atas SELURUH bahan
    (PK + broken) wajib benar."""
    from datetime import date as _date

    from sqlalchemy import func, select

    from app.database import now_local
    from app.models import ByproductStock, PkPurchaseBatch
    from app.penggilingan.gudang2.models import PolishingSiloUsage
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     rendemen_proses,
                                                     selesai_penyosohan,
                                                     tambah_silo_penyosohan)
    from app.penggilingan.gudang2.service import (masukkan_pk_luar,
                                                   pindah_broken_ke_silo,
                                                   pindah_tumpukan_ke_silo)
    from app.penggilingan.inventory.finished_goods import catat_broken

    u = dunia["user"]
    async with pg() as db:
        # P1: habiskan Silo A (10.000 kg), hasilkan 1.000 kg broken, pindah
        # ke Silo C, lalu tutup.
        r1 = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r1.proc.kode_proses, jenis="premium",
                           berat_kg=9_000)
        await catat_output(db, user=u, kode=r1.proc.kode_proses, jenis="broken",
                           berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=r1.proc.kode_proses, berat_kg=1_000)
        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r1.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                    nama_silo="C", berat=1_000)

        # Isi ulang Silo A — sepemilik (Bu Sri), sama pola dengan
        # `test_rendemen_proses_campuran_pk_dan_broken_atas_seluruh_bahan`.
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20261011-01", jasa_id=dunia["jasa_id"],
            berat_total_kg=4_000, tanggal_pembelian=_date.today(),
            waktu_pembelian=now_local(), input_by=u.id, status_batch="diterima",
            flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        ri = await masukkan_pk_luar(db, user=u, kode="PKB-20261011-01", tujuan="ditumpuk")
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=ri.intake.id,
                                      nama_silo="A", berat=4_000)

        # P2: mulai HANYA dari Silo A (PK) — Silo C belum jadi bahannya.
        r2 = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        assert r2.berat_awal_total == 4_000

        # Mid-proses: tambahkan Silo C (broken, 1.000 kg) sebagai campuran.
        r2b = await tambah_silo_penyosohan(db, user=u, kode=r2.proc.kode_proses,
                                           nama_silos=["C"])
        assert r2b.berat_awal_total == 1_000

        total = (await db.execute(
            select(func.coalesce(func.sum(PolishingSiloUsage.berat_awal_kg), 0))
            .where(PolishingSiloUsage.polishing_process_id == r2.proc.id)
        )).scalar_one()
        assert float(total) == 5_000

        await catat_output(db, user=u, kode=r2.proc.kode_proses, jenis="premium",
                           berat_kg=4_000)
        await selesai_penyosohan(db, user=u, kode=r2.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)
        await selesai_penyosohan(db, user=u, kode=r2.proc.kode_proses,
                                 nama_silo="C", sisa_kg=200)

        rend = await rendemen_proses(db, r2.proc.id)
        # bahan = PK terpakai (4.000 - 0) + broken terpakai (1.000 - 200)
        #       = 4.000 + 800 = 4.800 — BUKAN 4.000 (PK saja).
        assert rend == pytest.approx(4_000 / 4_800 * 100)


async def test_picker_nama_broken_tetap_ditemukan_setelah_normalisasi(pg, dunia):
    """Nilai picker dinormalisasi jadi uppercase; nama silo broken title-case.

    PK memakai nama huruf tunggal (A/B), jadi mismatch kapitalisasi ini baru
    tampak saat picker mengirim "BROKEN" untuk master "Silo Broken".
    """
    from sqlalchemy import update

    from app.models import Silo
    from app.penggilingan.gudang2.service import get_g2_silo

    async with pg() as db:
        await db.execute(update(Silo).where(Silo.id == dunia["silo_broken"])
                         .values(nama_silo="Silo Broken"))
        await db.flush()

        silo = await get_g2_silo(db, "BROKEN")

        assert silo is not None
        assert silo.id == dunia["silo_broken"]


async def test_tambah_silo_penyosohan_broken_pemilik_beda_ditolak(pg, dunia):
    """Silo C berisi broken milik jasa Bu Sri. Proses PABRIK (tanpa jasa)
    tak boleh menambahkannya sebagai bahan — pagar satu-pemilik yang sama
    dengan silo PK, kini dibuktikan untuk silo broken juga."""
    from datetime import date as _date

    from sqlalchemy import select

    from app.database import now_local
    from app.models import ByproductStock, PkPurchaseBatch, Silo, Supplier
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     selesai_penyosohan,
                                                     tambah_silo_penyosohan)
    from app.penggilingan.gudang2.service import (Gudang2Error, masukkan_pk_luar,
                                                   pindah_broken_ke_silo,
                                                   pindah_tumpukan_ke_silo)
    from app.penggilingan.inventory.finished_goods import catat_broken

    u = dunia["user"]
    async with pg() as db:
        r1 = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r1.proc.kode_proses, jenis="premium",
                           berat_kg=9_000)
        await catat_output(db, user=u, kode=r1.proc.kode_proses, jenis="broken",
                           berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=r1.proc.kode_proses, berat_kg=1_000)
        row = (await db.execute(select(ByproductStock)
                                .where(ByproductStock.jenis_produk == "broken"))
              ).scalars().one()
        await selesai_penyosohan(db, user=u, kode=r1.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row.id,
                                    nama_silo="C", berat=1_000)

        # Silo B (PK), baru, pabrik.
        silo_a = await db.get(Silo, dunia["silo_pk"])
        silo_b = Silo(nama_silo="Silo B", warehouse_id=silo_a.warehouse_id, jenis_isi="pk")
        db.add(silo_b)
        s = Supplier(nama_supplier="Pabrik Sendiri")
        db.add(s)
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20261011-02", supplier_id=s.id, berat_total_kg=5_000,
            tanggal_pembelian=_date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        ri = await masukkan_pk_luar(db, user=u, kode="PKB-20261011-02", tujuan="ditumpuk")
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=ri.intake.id,
                                      nama_silo="B", berat=5_000)

        r2 = await mulai_penyosohan(db, user=u, nama_silos=["B"])
        assert r2.proc.jasa_id is None

        with pytest.raises(Gudang2Error):
            await tambah_silo_penyosohan(db, user=u, kode=r2.proc.kode_proses,
                                         nama_silos=["C"])


async def test_tambah_silo_penyosohan_menolak_broken_hasil_sendiri(pg, dunia):
    """Pagar BARU: proses P2 memindahkan brokennya SENDIRI ke Silo C
    (Silo C belum jadi bahan P2 saat itu, jadi pagar `pindah_broken_ke_silo`
    diam), lalu mencoba menambahkan Silo C ke P2 sendiri lewat
    `tambah_silo_penyosohan` — DITOLAK. Arah terbalik dari
    `test_proses_tak_boleh_memakan_broken_sendiri` di atas, tapi pagar yang
    sama: fisiknya mustahil P2 menyosoh ulang hasil brokennya sendiri selagi
    P2 masih berjalan."""
    from sqlalchemy import select

    from app.models import ByproductStock
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                     tambah_silo_penyosohan)
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_broken_ke_silo
    from app.penggilingan.inventory.finished_goods import catat_broken

    u = dunia["user"]
    async with pg() as db:
        r2 = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r2.proc.kode_proses, jenis="broken",
                           berat_kg=300)
        await catat_broken(db, user=u, kode_pol=r2.proc.kode_proses, berat_kg=300)
        row2 = (await db.execute(
            select(ByproductStock).where(ByproductStock.jenis_produk == "broken",
                                         ByproductStock.source_id == r2.proc.id))
               ).scalars().one()
        # Silo C belum jadi sumber P2 — pagar `pindah_broken_ke_silo` tak
        # menghadang pemindahan ini.
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row2.id,
                                    nama_silo="C", berat=300)

        with pytest.raises(Gudang2Error, match="sendiri"):
            await tambah_silo_penyosohan(db, user=u, kode=r2.proc.kode_proses,
                                         nama_silos=["C"])
