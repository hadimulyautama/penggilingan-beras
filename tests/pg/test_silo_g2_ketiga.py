"""Silo Gudang 2 KETIGA — ada di master, dan bisa dipakai sungguhan.

Sampai 24 September 2026 `silo_a`/`silo_b` bukan tulisan di layar melainkan
NILAI yang tersimpan: di `pk_gudang2_intakes.tujuan`, di
`internal_transfers.lokasi_tujuan`, dan di dua tabel proyeksi berikut CHECK-nya.
Kosakata seperti itu tak bisa tumbuh. Akibatnya silo ketiga bisa dibuat di
master, muncul di borang penyosohan — dan tak bisa menerima satu kilogram pun
lewat jalan mana pun. Operator yang membacanya akan mengira aplikasinya rusak,
dan ia tidak salah. Temuan QA 24 September.

Yang dijaga berkas ini: KETIGA jalan masuk PK ke silo bekerja untuk silo yang
namanya tak pernah diketik di kode, angkanya terhitung, kalimatnya menyebut
nama yang benar — dan kosakata LAMA tetap diterima, sebab halaman di ponsel
operator berumur panjang dan baris lama tetap harus terbaca.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Gudang 2 dengan TIGA silo — A, B, dan C yang lahir belakangan."""
    from sqlalchemy import select

    from app.models import Silo, User, Warehouse

    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
            await db.flush()
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
            await db.flush()
        silo = {}
        for huruf in ("A", "B", "C"):
            s = (await db.execute(select(Silo).where(
                Silo.nama_silo == f"Silo {huruf}",
                Silo.warehouse_id == g2.id))).scalars().first()
            if s is None:
                s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=g2.id, status="kosong")
                db.add(s)
                await db.flush()
            silo[huruf] = s.id
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g2.id
        u.role = "superadmin"      # satu orang menempuh semua jalan di uji ini
        await db.commit()
        return {"silo": silo, "user": u.id, "g1": g1.id, "g2": g2.id,
                "pemasok": pemasok.id}


async def _pk_luar(pg, pabrik, kode: str, kg: float, tujuan: str):
    """Satu batch PK luar → masuk ke `tujuan`. → IntakeResult."""
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        db.add(PkPurchaseBatch(
            kode_batch=kode, supplier_id=pabrik["pemasok"], berat_total_kg=kg,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        return await masukkan_pk_luar(db, user=u, kode=kode, tujuan=tujuan)


# ─────────────── Jalan 1 · PK luar langsung ke silo ketiga ───────────────

async def test_pk_luar_masuk_silo_ketiga(pg, pabrik):
    from sqlalchemy import select

    from app.penggilingan.gudang2.models import PkGudang2Intake
    from app.penggilingan.gudang2.service import hitung_stok_silo

    r = await _pk_luar(pg, pabrik, "PKB-C-01", 5_000, "C")
    assert r.lokasi_label == "Silo C", "kalimatnya menyebut nama yang salah"

    async with pg() as db:
        baris = (await db.execute(select(PkGudang2Intake).where(
            PkGudang2Intake.silo_id == pabrik["silo"]["C"]))).scalars().all()
        assert len(baris) == 1
        # Yang disimpan JENIS tempatnya; silo MANA jadi rujukan.
        assert baris[0].tujuan == "silo" and baris[0].silo_id == pabrik["silo"]["C"]
        # ⚠ Inilah yang paling halus: seandainya stoknya disaring dengan kata
        # tujuannya, silo ini berisi tetapi terbaca 0 — lalu hilang dari borang
        # tanpa satu pun galat di mana pun.
        assert await hitung_stok_silo(db, pabrik["silo"]["C"]) == 5_000


async def test_kosakata_lama_tetap_diterima(pg, pabrik):
    """Halaman di ponsel operator berumur panjang, dan baris lama menyimpan
    kata itu. Yang berhenti dipakai adalah MENULISNYA, bukan membacanya."""
    from sqlalchemy import select

    from app.penggilingan.gudang2.models import PkGudang2Intake
    from app.penggilingan.gudang2.service import hitung_stok_silo

    r = await _pk_luar(pg, pabrik, "PKB-A-01", 2_000, "silo_a")
    assert r.lokasi_label == "Silo A"
    async with pg() as db:
        baris = (await db.execute(select(PkGudang2Intake).where(
            PkGudang2Intake.silo_id == pabrik["silo"]["A"]))).scalars().one()
        assert baris.tujuan == "silo", "kata lama ikut DITULIS lagi"
        assert await hitung_stok_silo(db, pabrik["silo"]["A"]) == 2_000


async def test_tujuan_yang_tak_ada_ditolak_tanpa_menyebut_dua_silo(pg, pabrik):
    """Kalimatnya tak boleh menyebut daftar silo: daftar itu berubah menurut
    master, dan kalimat yang menyebut dua silo akan keliru begitu ada yang
    ketiga — persis kesalahan yang diperbaiki di sini."""
    from app.penggilingan.gudang2.service import Gudang2Error

    with pytest.raises(Gudang2Error) as e:
        await _pk_luar(pg, pabrik, "PKB-Z-01", 1_000, "Z")
    assert "daftar" in str(e.value).lower()
    assert "Silo A" not in str(e.value) and "Silo B" not in str(e.value)


# ─────────────── Jalan 2 · Transfer Gudang 1 → silo ketiga ───────────────

async def test_transfer_g1_ke_silo_ketiga(pg, pabrik):
    """`internal_transfers` belum punya rujukan silo sebelum migrasi 0057 —
    identitas silonya cuma ada di teks `lokasi_tujuan`."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import (InternalTransfer, MillingProcess, MillingProgressLog,
                            PurchaseBatch, Silo, User)
    from app.penggilingan.gudang2.service import hitung_stok_silo
    from app.services.transfer import create_internal_transfer

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        silo_g1 = Silo(nama_silo="Silo Selepan", warehouse_id=pabrik["g1"])
        db.add(silo_g1)
        await db.flush()
        b = PurchaseBatch(kode_batch="GB-TRF-C", supplier_id=pabrik["pemasok"],
                          berat_total_kg=10_000, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=u.id, flag_unverified=False, sumber_berat="timbangan")
        db.add(b)
        await db.flush()
        p = MillingProcess(kode_proses="LOT-TRF-C", status="selesai", silo_id=silo_g1.id,
                           berat_gabah_masuk_kg=10_000, waktu_mulai=now_local(),
                           waktu_selesai=now_local(), created_by=u.id,
                           purchase_batch_id=b.id)
        db.add(p)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=p.id, berat_kumulatif_kg=6_000,
                                  waktu_update=now_local(), input_by=u.id))
        await db.commit()

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await create_internal_transfer(db, user=u, kode_proses="LOT-TRF-C",
                                           lokasi_tujuan="C", berat=6_000)
    assert r.lokasi_label == "Silo C"

    async with pg() as db:
        t = (await db.execute(select(InternalTransfer))).scalars().one()
        assert t.lokasi_tujuan == "silo" and t.silo_id == pabrik["silo"]["C"]
        assert await hitung_stok_silo(db, pabrik["silo"]["C"]) == 6_000


# ─────────────── Jalan 3 · Tumpukan → silo ketiga ───────────────

async def test_pindah_tumpukan_ke_silo_ketiga(pg, pabrik):
    from app.models import User
    from app.penggilingan.gudang2.service import (hitung_stok_silo,
                                                  pindah_tumpukan_ke_silo)

    r = await _pk_luar(pg, pabrik, "PKB-TUMPUK-01", 8_000, "ditumpuk")
    assert r.lokasi_label == "tumpukan"
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        p = await pindah_tumpukan_ke_silo(db, user=u, intake_id=r.intake.id,
                                          nama_silo="C", berat=3_000)
        assert p.sisa_tumpukan_intake == 5_000
        assert await hitung_stok_silo(db, pabrik["silo"]["C"]) == 3_000


# ─────────────── Ujungnya · disosoh, dan dibatalkan ───────────────

async def test_silo_ketiga_bisa_disosoh(pg, pabrik):
    from app.models import User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.web.api import silo_bahan_g2

    await _pk_luar(pg, pabrik, "PKB-C-02", 4_000, "C")
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
    daftar = [x["value"] for x in await silo_bahan_g2(user=u)]
    assert daftar == ["C"], daftar
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await mulai_penyosohan(db, user=u, nama_silos=["C"])
    assert r.berat_awal_total == 4_000


async def test_pembatalan_menyebut_nama_silo_yang_benar(pg, pabrik):
    """Kamus lama menjawab `.get(tujuan, tujuan)` — jadi kalimat pembatalan
    berbunyi "dimasukkan ke silo_c", kata mentah dari basis data."""
    from app.models import User
    from app.services import undo

    await _pk_luar(pg, pabrik, "PKB-C-03", 1_500, "C")
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=u.id)
        pesan = await undo.undo_last(db, actor=u, cakupan=c)
        await db.commit()
    assert "Silo C" in pesan, pesan
    assert "silo_c" not in pesan


# ─────────────── Dua sesi, seperti aturan repo untuk jalur peristiwa ───────────────

async def test_dua_sesi_kunci_kiriman_sama_hanya_satu_baris(pg, pabrik):
    """Aturan repo: tiap aksi di jalur peristiwa wajib punya uji Postgres dua
    sesi. Kiriman yang diulang — tombol ditekan dua kali, jaringan terputus di
    tengah — tak boleh melahirkan dua pemasukan."""
    import asyncio

    from sqlalchemy import select

    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PkGudang2Intake, PkPurchaseBatch
    from app.penggilingan.gudang2.service import hitung_stok_silo, masukkan_pk_luar

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        db.add(PkPurchaseBatch(
            kode_batch="PKB-C-KEMBAR", supplier_id=pabrik["pemasok"],
            berat_total_kg=7_000, tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, status_batch="diterima",
            flag_unverified=True, sumber_berat="manual"))
        await db.commit()

    async def kirim():
        async with pg() as db:
            u = await db.get(User, pabrik["user"])
            try:
                r = await masukkan_pk_luar(db, user=u, kode="PKB-C-KEMBAR",
                                           tujuan="C", kunci_kiriman="uji-kembar-01")
                return r.lokasi_label
            except Exception as e:                      # noqa: BLE001
                return f"tolak: {type(e).__name__}: {e}"

    hasil = await asyncio.gather(kirim(), kirim())
    async with pg() as db:
        baris = (await db.execute(select(PkGudang2Intake).where(
            PkGudang2Intake.silo_id == pabrik["silo"]["C"]))).scalars().all()
        assert len(baris) == 1, f"kiriman kembar melahirkan dua baris: {hasil}"
        assert await hitung_stok_silo(db, pabrik["silo"]["C"]) == 7_000
    # Yang kalah pun menjawab dengan nama silo, bukan dengan galat mentah.
    assert all("Silo C" in x or x.startswith("tolak:") for x in hasil), hasil
