"""Pembebasan silo per-silo di Gudang 1 — `tutup_silo_giling`.

Keputusan pemilik 5 Oktober 2026: *"silo yang kosong langsung diisi gabah
lagi walau tidak langsung diproses."* Giling dari beberapa silo sering tak
menghabiskan semuanya bersamaan, dan sampai hari ini silo yang sudah habis
tak bisa dibebaskan sebelum SELURUH proses selesai.

Diperiksa dulu: Gudang 2 sudah punya persis ini (`selesai_penyosohan`/
`polishing_silo_usage`). Berkas ini membuktikan TIGA BEDA struktural yang
sengaja tak meniru mentah — lihat docstring `milling.tutup_silo_giling` —
dan terutama JEBAKAN TERBESARNYA: silo yang dibebaskan lalu diisi gabah baru
TIDAK boleh diam-diam terdaftar sebagai bahan tambahan lot LAMA.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def dunia(pg, pemakai, pemasok):
    """Gudang 1, Silo A (10.000 kg) + Silo B (6.000 kg), satu giling dari
    keduanya sekaligus — satu lot, 16.000 kg masuk."""
    from app.database import now_local
    from app.models import PurchaseBatch, Silo, SiloStorage, User, Warehouse
    from app.penggilingan.gudang1.services.milling import start_milling

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
            await db.flush()
        silo = {}
        for huruf in ("A", "B"):
            s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=g1.id, status="kosong")
            db.add(s)
            await db.flush()
            silo[huruf] = s

        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id    # `_is_g1_operator` di rute-rute katalog
        for huruf, kg in (("A", 10_000), ("B", 6_000)):
            b = PurchaseBatch(
                kode_batch=f"GB-PEMBEBASAN-{huruf}", supplier_id=pemasok.id,
                berat_total_kg=kg, kondisi_gabah="kering",
                tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                input_by=u.id, flag_unverified=False, sumber_berat="timbangan",
                status_batch="di_silo")
            db.add(b)
            await db.flush()
            db.add(SiloStorage(silo_id=silo[huruf].id, purchase_batch_id=b.id,
                               tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                               input_by=u.id, status="terisi"))
            silo[huruf].status = "terisi"
        await db.commit()
        await db.refresh(u)
        r = await start_milling(db, user=u, nama_silo=["A", "B"])
        return {"user": u.id, "silo": {h: s.id for h, s in silo.items()},
                "pemasok": pemasok.id, "kode_proses": r.proc.kode_proses}


async def test_bebaskan_satu_silo_tak_menutup_proses(pg, dunia):
    """⭐ Inti permintaan: silo bisa habis duluan sementara gabahnya MASIH DI
    MESIN — "silo kosong" bukan "giling selesai"."""
    from app.models import MillingProcess, MillingProcessSource, Silo, SiloStorage, User
    from app.penggilingan.gudang1.services.milling import tutup_silo_giling

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        hasil = await tutup_silo_giling(
            db, user=u, kode_proses=dunia["kode_proses"], nama_silo="A", sisa_kg=0)
    assert hasil.nama_silo == "A"
    assert hasil.sisa_kg == 0 and hasil.terpakai_kg == 10_000

    async with pg() as db:
        proc = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == dunia["kode_proses"]))).scalars().one()
        assert proc.status == "proses", "proses ikut tertutup — hanya silo A yang dibebaskan"

        silo_a = await db.get(Silo, dunia["silo"]["A"])
        assert silo_a.status == "kosong"
        silo_b = await db.get(Silo, dunia["silo"]["B"])
        assert silo_b.status == "terisi", "silo B tak ikut tersentuh"

        sumber = (await db.execute(select(MillingProcessSource)
                 .where(MillingProcessSource.milling_process_id == proc.id))).scalars().all()
        for s in sumber:
            st = await db.get(SiloStorage, s.silo_storage_id)
            if st.silo_id == dunia["silo"]["A"]:
                assert float(s.berat_terpakai_kg) == 10_000
                assert float(s.berat_akhir_kg) == 0
                assert st.status == "kosong" and st.milling_process_id is None
            else:
                assert s.berat_akhir_kg is None, "silo B masih harus terikat"


async def test_silo_dibebaskan_boleh_diisi_ulang_tanpa_masuk_lot_lama(pg, dunia):
    """⭐⭐ JEBAKAN TERBESAR (brief bagian 2a). Tanpa syarat 'belum dibebaskan'
    di `giling_berjalan_untuk_silo`, gabah baru di Silo A akan terdaftar
    sebagai bahan TAMBAHAN lot lama — bobot masuknya membengkak dan
    rendemennya anjlok diam-diam. Lalu giling dari Silo B tetap ditutup
    dengan bobot akhir & pagar rendemennya bekerja seperti biasa."""
    from app.database import now_local
    from app.models import MillingProcess, MillingProcessSource, PurchaseBatch, SiloStorage, User
    from app.penggilingan.gudang1.services.milling import (MillingError, finish_milling,
                                                           tutup_silo_giling)
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        await tutup_silo_giling(db, user=u, kode_proses=dunia["kode_proses"],
                                nama_silo="A", sisa_kg=0)

    async with pg() as db:
        proc_sebelum = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == dunia["kode_proses"]))).scalars().one()
        masuk_sebelum = float(proc_sebelum.berat_gabah_masuk_kg)
        proc_id = proc_sebelum.id
        jumlah_sumber_sebelum = len((await db.execute(select(MillingProcessSource.id).where(
            MillingProcessSource.milling_process_id == proc_id))).scalars().all())

    # Gabah BARU dituang ke Silo A — baru saja dibebaskan, belum tentu
    # langsung digiling (keadaan yang pemilik sebutkan sendiri).
    async with pg() as db:
        u = await db.get(User, dunia["user"])
        db.add(PurchaseBatch(
            kode_batch="GB-ISI-ULANG-A", supplier_id=dunia["pemasok"], berat_total_kg=4_000,
            kondisi_gabah="kering", tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, flag_unverified=False,
            sumber_berat="timbangan", status_batch="kering"))
        await db.commit()
        r = await masuk_silo(db, user=u, nama_silo="A", kode_lot=None,
                             kode_batch="GB-ISI-ULANG-A")
    # Jawaban LANGSUNG dari `masuk_silo` sendiri: tak ada giling berjalan
    # untuk silo ini — persis pertanyaan yang `giling_berjalan_untuk_silo`
    # jawab salah tanpa perbaikan ini.
    assert r.giling_berjalan is None, \
        "gabah baru terdaftar sebagai tambahan giling yang sudah dibebaskan"

    async with pg() as db:
        baris_baru = (await db.execute(select(SiloStorage).where(
            SiloStorage.purchase_batch_id ==
            (await db.execute(select(PurchaseBatch.id).where(
                PurchaseBatch.kode_batch == "GB-ISI-ULANG-A"))).scalar_one()
        ))).scalars().one()
        assert baris_baru.milling_process_id is None, \
            "SiloStorage baru ikut terklaim proses lama"
        assert baris_baru.status == "terisi"

        # Gabah baru TIDAK terdaftar sebagai sumber lot lama.
        proc_sesudah = await db.get(MillingProcess, proc_id)
        assert float(proc_sesudah.berat_gabah_masuk_kg) == masuk_sebelum, \
            "bobot masuk lot lama ikut bertambah — gabah baru termakan lot lama"
        jumlah_sumber_sesudah = len((await db.execute(select(MillingProcessSource.id).where(
            MillingProcessSource.milling_process_id == proc_id))).scalars().all())
        assert jumlah_sumber_sesudah == jumlah_sumber_sebelum, \
            "ada baris sumber baru ditambahkan ke lot lama"

    # Giling tetap bisa ditutup dari Silo B — pagar rendemen (bagian 1
    # brief) masih bekerja: tepat 100% (16.000 dari bahan 16.000) ditolak.
    async with pg() as db:
        u = await db.get(User, dunia["user"])
        with pytest.raises(MillingError):
            await finish_milling(db, user=u, kode_proses=dunia["kode_proses"],
                                 berat_akhir=16_000)
    async with pg() as db:
        u = await db.get(User, dunia["user"])
        hasil = await finish_milling(db, user=u, kode_proses=dunia["kode_proses"],
                                     berat_akhir=9_000)
    assert hasil.produced == 9_000
    assert hasil.nama_silo == "B", "pesan penutupan tak boleh menyebut Silo A lagi"

    async with pg() as db:
        # Dan Silo A yang sudah terisi ulang TIDAK ikut dikosongkan oleh
        # penutupan proses lama ini.
        baris_baru = await db.get(SiloStorage, baris_baru.id)
        assert baris_baru.status == "terisi", \
            "finish_milling proses lama mengosongkan ulang silo yang sudah terisi gabah baru"


async def test_bebaskan_butuh_sebut_silo_jika_lebih_dari_satu_terbuka(pg, dunia):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import MillingError, tutup_silo_giling

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        with pytest.raises(MillingError) as e:
            await tutup_silo_giling(db, user=u, kode_proses=dunia["kode_proses"],
                                    nama_silo=None, sisa_kg=0)
    assert "lebih dari satu" in str(e.value)


async def test_bebaskan_tanpa_nama_otomatis_pilih_satu_satunya_terbuka(pg, dunia):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import tutup_silo_giling

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        await tutup_silo_giling(db, user=u, kode_proses=dunia["kode_proses"],
                                nama_silo="A", sisa_kg=0)
    async with pg() as db:
        u = await db.get(User, dunia["user"])
        hasil = await tutup_silo_giling(db, user=u, kode_proses=dunia["kode_proses"],
                                        nama_silo=None, sisa_kg=0)
    assert hasil.nama_silo == "B"


async def test_tak_bisa_dibebaskan_dua_kali(pg, dunia):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import MillingError, tutup_silo_giling

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        await tutup_silo_giling(db, user=u, kode_proses=dunia["kode_proses"],
                                nama_silo="A", sisa_kg=500)
    async with pg() as db:
        u = await db.get(User, dunia["user"])
        with pytest.raises(MillingError) as e:
            await tutup_silo_giling(db, user=u, kode_proses=dunia["kode_proses"],
                                    nama_silo="A", sisa_kg=0)
    assert "sudah ditandai bebas" in str(e.value) and "500" in str(e.value)


async def test_sisa_melebihi_isi_ditolak(pg, dunia):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import MillingError, tutup_silo_giling

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        with pytest.raises(MillingError) as e:
            await tutup_silo_giling(db, user=u, kode_proses=dunia["kode_proses"],
                                    nama_silo="A", sisa_kg=10_001)
    assert "melebihi" in str(e.value)


async def test_sisa_dibagi_terlama_habis_duluan(pg, dunia):
    """Silo A dengan DUA baris sumber (dua pengisian terpisah, keadaan yang
    normal di Gudang 1 — beda dari Gudang 2 yang satu baris per silo).

    Silo A: baris lama 10.000 kg, baris baru (dituang selagi giling
    berjalan) 2.000 kg — total 12.000 kg. Sisa diketik 2.500 kg, jadi yang
    terpakai 9.500 kg. Konvensinya baris TERLAMA dipenuhi dulu dari budget
    terpakai: 9.500 kg seluruhnya cukup diserap baris lama sendiri
    (isinya 10.000 kg), jadi baris baru sama sekali tak tersentuh — dan
    baris lama menyisakan 500 kg dari isinya sendiri.
    """
    from app.database import now_local
    from app.models import MillingProcess, MillingProcessSource, PurchaseBatch, SiloStorage, User
    from app.penggilingan.gudang1.services.milling import tutup_silo_giling
    from app.penggilingan.gudang1.services.silo import masuk_silo

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        db.add(PurchaseBatch(
            kode_batch="GB-TAMBAH-A", supplier_id=dunia["pemasok"], berat_total_kg=2_000,
            kondisi_gabah="kering", tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, flag_unverified=False,
            sumber_berat="timbangan", status_batch="kering"))
        await db.commit()
        r = await masuk_silo(db, user=u, nama_silo="A", kode_lot=None,
                             kode_batch="GB-TAMBAH-A")
    assert r.giling_berjalan is not None, "tambahan semestinya ikut giling yang berjalan"

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        hasil = await tutup_silo_giling(db, user=u, kode_proses=dunia["kode_proses"],
                                        nama_silo="A", sisa_kg=2_500)
    assert hasil.terpakai_kg == 9_500          # (10.000 + 2.000) - 2.500

    async with pg() as db:
        proc_id = (await db.execute(select(MillingProcess.id).where(
            MillingProcess.kode_proses == dunia["kode_proses"]))).scalar_one()
        sumber = (await db.execute(select(MillingProcessSource)
                 .where(MillingProcessSource.milling_process_id == proc_id))).scalars().all()
        baris_a = []
        for s in sumber:
            st = await db.get(SiloStorage, s.silo_storage_id)
            if st.silo_id == dunia["silo"]["A"]:
                baris_a.append(s)
        baris_a.sort(key=lambda s: s.id)
        lama, baru = baris_a[0], baris_a[1]
        assert float(lama.berat_kg) == 10_000 and float(baru.berat_kg) == 2_000

        # Jumlahnya tetap tepat sama dengan sisa yang diketik, berapa pun
        # baris yang ditutup — itu yang WAJIB benar, apa pun urutannya.
        assert (float(lama.berat_terpakai_kg) + float(baru.berat_terpakai_kg)) == 9_500
        assert (float(lama.berat_akhir_kg) + float(baru.berat_akhir_kg)) == 2_500
        # Konvensi TERLAMA-habis-duluan: budget 9.500 seluruhnya ke baris
        # lama (isinya 10.000, cukup), baris baru sama sekali tak tersentuh.
        assert float(lama.berat_terpakai_kg) == 9_500 and float(lama.berat_akhir_kg) == 500
        assert float(baru.berat_terpakai_kg) == 0 and float(baru.berat_akhir_kg) == 2_000


# ═══════════════ Jalur sungguhan: katalog → rute → layanan ═══════════════

async def test_picker_silo_terbuka_induk_dan_rute_terpasang(pg, dunia):
    """⭐ Bukti jalur UTUH, bukan cuma layanannya: picker
    `/actions/silo-giling-terbuka?induk=` menjumlah seluruh baris terbuka
    per silo, dan rute `act_tutup_silo_giling` benar-benar memanggil
    `tutup_silo_giling` lewat `aksi.js`/katalog — pola yang sama dengan
    "Selesai penyosohan" Gudang 2."""
    from app.models import User
    from app.web.api import TutupSiloGilingReq, act_tutup_silo_giling, silo_giling_terbuka

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        opsi = await silo_giling_terbuka(induk=dunia["kode_proses"], user=u)
    assert {o["value"] for o in opsi} == {"A", "B"}
    label_a = next(o["label"] for o in opsi if o["value"] == "A")
    assert "10.000" in label_a or "10000" in label_a

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        hasil = await act_tutup_silo_giling(
            TutupSiloGilingReq(kode_proses=dunia["kode_proses"], silo="A", sisa=0),
            user=u)
    assert hasil["ok"] is True and "A" in hasil["pesan"]

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        opsi_sesudah = await silo_giling_terbuka(induk=dunia["kode_proses"], user=u)
    assert {o["value"] for o in opsi_sesudah} == {"B"}, \
        "silo yang sudah dibebaskan masih ditawarkan picker"


async def test_picker_tanpa_induk_daftar_kosong(pg, dunia):
    """Tanpa `induk`, daftar kosong — menjawab tanpa tahu prosesnya berarti
    menawarkan silo yang tak pernah dipakainya."""
    from app.models import User
    from app.web.api import silo_giling_terbuka

    async with pg() as db:
        u = await db.get(User, dunia["user"])
        assert await silo_giling_terbuka(induk="", user=u) == []
