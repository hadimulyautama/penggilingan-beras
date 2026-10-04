"""Tiga cacat pada JALUR-SALAH — temuan QA 25 September 2026.

Jalur-salah adalah yang paling jarang diuji dan paling sering ditempuh: orang
salah ketik satu angka, menekan tombol dua kali, atau membuka borang yang sudah
basi. Ketiga cacat di berkas ini ditemukan saat QA menyusun lembar uji untuk
tim — bukan dari kode, melainkan dari mencoba salah dengan sengaja.

Yang menyatukan ketiganya: masing-masing DITERIMA dengan kalimat yang sama
cerianya dengan keberhasilan, dan akibatnya baru terbaca di angka yang sudah
telanjur dipakai orang lain.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Gudang 1 bersilo A (10.000 kg) dan Gudang 2 bersilo A/B."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import (PurchaseBatch, Silo, SiloStorage, User, Warehouse)

    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
        await db.flush()
        s1 = Silo(nama_silo="Silo A", warehouse_id=g1.id, status="kosong")
        db.add(s1)
        g2silo = {}
        for huruf in ("A", "B"):
            s = Silo(nama_silo=f"Silo {huruf}", warehouse_id=g2.id, status="kosong")
            db.add(s)
            await db.flush()
            g2silo[huruf] = s.id
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id
        u.role = "superadmin"
        await db.flush()

        b = PurchaseBatch(kode_batch="GB-SALAH-01", supplier_id=pemasok.id,
                          berat_total_kg=10_000, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=u.id, flag_unverified=False,
                          sumber_berat="timbangan", status_batch="di_silo")
        db.add(b)
        await db.flush()
        db.add(SiloStorage(silo_id=s1.id, purchase_batch_id=b.id,
                           tipe_masuk="langsung_kering", tanggal_masuk=now_local(),
                           input_by=u.id, status="terisi"))
        s1.status = "terisi"
        await db.commit()
        return {"user": u.id, "g1_silo": s1.id, "g2": g2silo,
                "g2_wh": g2.id, "pemasok": pemasok.id}


# ═════════ 1 · Hasil giling menerima angka mustahil ═════════

async def test_rendemen_di_atas_seratus_diberitahu(pg, pabrik):
    """Salah ketik satu digit: 18.000 untuk maksud 8.000, atas bahan 10.000 kg.

    Beras tak pernah lebih berat daripada gabahnya — sekamnya terbuang. Sampai
    25 September 2026 angka itu diterima tanpa satu pun tanda, dan kartu Stok
    menggambar rendemen 180% sampai ada yang kebetulan memperhatikan.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.milling import log_progress, start_milling

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await start_milling(db, user=u, nama_silo=["A"])
        hasil = await log_progress(db, user=u, kode_proses=r.proc.kode_proses,
                                   berat_kumulatif=18_000)

    # DITERIMA — menolaknya menutup satu-satunya jalan perbaikan operator.
    assert hasil.berat_kumulatif == 18_000
    assert hasil.peringatan and "Rendemen" in hasil.peringatan
    assert "180%" in hasil.peringatan
    assert "10.000" in hasil.peringatan, "peringatannya tak menyebut bahannya"


async def test_angka_wajar_tak_diberi_peringatan(pg, pabrik):
    """Peringatan yang selalu muncul berhenti dibaca. 6.000 dari 10.000 =
    60%, rendemen yang biasa — dan ia harus lewat tanpa suara."""
    from app.models import User
    from app.penggilingan.gudang1.services.milling import log_progress, start_milling

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await start_milling(db, user=u, nama_silo=["A"])
        hasil = await log_progress(db, user=u, kode_proses=r.proc.kode_proses,
                                   berat_kumulatif=6_000)
    assert hasil.rendemen_persen == pytest.approx(60.0, abs=0.05)
    assert hasil.peringatan is None, hasil.peringatan


async def test_kumulatif_boleh_mundur_untuk_membetulkan(pg, pabrik):
    """Begitulah salah ketik tadi dibetulkan: mengetik angka yang benar.
    Menutup jalan ini berarti menghukum kesalahan yang wajar."""
    from app.models import User
    from app.penggilingan.gudang1.services.milling import log_progress, start_milling

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await start_milling(db, user=u, nama_silo=["A"])
        await log_progress(db, user=u, kode_proses=r.proc.kode_proses,
                           berat_kumulatif=18_000)
        betul = await log_progress(db, user=u, kode_proses=r.proc.kode_proses,
                                   berat_kumulatif=8_000)
    assert betul.berat_kumulatif == 8_000 and betul.peringatan is None


# ═════════ 2 · Silo penyosohan ditutup dua kali ═════════

async def _isi_silo_g2(pg, pabrik, kode: str, kg: float, tujuan: str):
    """PK masuk tumpukan dulu, lalu dipindah ke silo — PK baru tak lagi boleh
    langsung ke silo (keputusan pemilik 4 Oktober 2026, Aturan 1)."""
    from app.database import now_local
    from app.models import User
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar, pindah_tumpukan_ke_silo

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        db.add(PkPurchaseBatch(
            kode_batch=kode, supplier_id=pabrik["pemasok"], berat_total_kg=kg,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        r = await masukkan_pk_luar(db, user=u, kode=kode, tujuan="ditumpuk")
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=r.intake.id,
                                      nama_silo=tujuan, berat=kg)


async def test_silo_yang_sudah_bersisa_tak_bisa_ditutup_lagi(pg, pabrik):
    """Menandai dua kali MENIMPA sisa yang sudah dicatat operator pertama, dan
    selisihnya berpindah diam-diam dari stok ke "terpakai" — penyebut rendemen.
    500 jadi 100 menggeser 400 kg tanpa jejak di layar mana pun."""
    from sqlalchemy import select

    from app.models import User
    from app.penggilingan.gudang2.models import PolishingSiloUsage
    from app.penggilingan.gudang2.polishing import (Gudang2Error, catat_output,
                                                    mulai_penyosohan,
                                                    selesai_penyosohan)

    await _isi_silo_g2(pg, pabrik, "PKB-SALAH-A", 4_000, "A")
    await _isi_silo_g2(pg, pabrik, "PKB-SALAH-B", 6_000, "B")
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kumulatif=3_000)
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=500)

        with pytest.raises(Gudang2Error) as e:
            await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                     nama_silo="A", sisa_kg=100)

    pesan = str(e.value)
    # Kalimatnya menyebut sisa yang SUDAH tercatat: yang menekan tombol kedua
    # kalinya biasanya tak tahu yang pertama sudah masuk.
    assert "sudah ditandai selesai" in pesan and "500" in pesan, pesan

    async with pg() as db:
        pakai = (await db.execute(select(PolishingSiloUsage).where(
            PolishingSiloUsage.silo_id == pabrik["g2"]["A"]))).scalars().one()
    assert float(pakai.berat_akhir_kg) == 500, "sisanya tertimpa"
    assert float(pakai.berat_terpakai_kg) == 3_500


async def test_dua_hp_menutup_silo_yang_sama_bersamaan(pg, pabrik):
    """Dua operator Gudang 2 di dua HP adalah keadaan sehari-hari, jadi ini
    bukan kasus tepi. Pemeriksaan di depan dilewati keduanya; yang memutuskan
    kunci baris di basis data."""
    from sqlalchemy import select

    from app.models import User
    from app.penggilingan.gudang2.models import PolishingSiloUsage
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                    selesai_penyosohan)

    await _isi_silo_g2(pg, pabrik, "PKB-BALAP-A", 4_000, "A")
    await _isi_silo_g2(pg, pabrik, "PKB-BALAP-B", 6_000, "B")
    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium",
                           berat_kumulatif=3_000)
    kode = r.proc.kode_proses

    async def tutup(sisa: float):
        async with pg() as db:
            u = await db.get(User, pabrik["user"])
            try:
                await selesai_penyosohan(db, user=u, kode=kode, nama_silo="A",
                                         sisa_kg=sisa)
                return f"ok:{sisa:.0f}"
            except Exception as e:                       # noqa: BLE001
                return f"tolak: {e}"

    hasil = await asyncio.gather(tutup(500), tutup(100))
    menang = [x for x in hasil if x.startswith("ok:")]
    assert len(menang) == 1, hasil

    async with pg() as db:
        pakai = (await db.execute(select(PolishingSiloUsage).where(
            PolishingSiloUsage.silo_id == pabrik["g2"]["A"]))).scalars().one()
    # Yang tercatat adalah angka PEMENANGNYA, bukan campuran keduanya.
    assert f"ok:{float(pakai.berat_akhir_kg):.0f}" == menang[0], (
        f"sisa {pakai.berat_akhir_kg} tak cocok dengan pemenang {menang}")


# ═════════ 3 · Pembatalan mengenai pekerjaan orang lain ═════════

async def test_undo_tak_bisa_mengenai_input_orang_lain(pg, pabrik):
    """Semakin KOSONG lingkup seseorang, semakin bebas ia membatalkan pekerjaan
    orang lain — akibat terbalik dari yang masuk akal.

    Pagar satu-satunya adalah perbandingan dengan "yang terbaru dalam lingkup
    ini", DAN pagar itu dilewati ketika lingkupnya kosong. Operator yang belum
    mencatat apa pun hari ini adalah yang paling leluasa.
    """
    from sqlalchemy import select

    from app.models import ActivityLog, User
    from app.penggilingan.gudang1.services.milling import start_milling
    from app.services import undo

    async with pg() as db:
        u1 = await db.get(User, pabrik["user"])
        r = await start_milling(db, user=u1, nama_silo=["A"])
        lain = User(nama="Operator Lain", role="operator", status="aktif")
        db.add(lain)
        await db.commit()
        await db.refresh(lain)
        log_id = (await db.execute(
            select(ActivityLog.id).where(ActivityLog.changed_by == u1.id)
            .order_by(ActivityLog.id.desc()).limit(1))).scalars().first()
    assert log_id is not None

    async with pg() as db:
        orang_lain = await db.get(User, lain.id)
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=orang_lain.id)
        # Daftarnya memang kosong — dan dulu itulah yang membuka pintunya.
        with pytest.raises(undo.UndoError) as e:
            await undo.undo_last(db, actor=orang_lain, cakupan=c, log_id=log_id)

    pesan = str(e.value)
    assert "bukan input Anda" in pesan
    # Dan kalimatnya tak membocorkan isi catatan orang lain.
    assert r.proc.kode_proses not in pesan and "Operator" not in pesan

    # Gilingnya masih berdiri — tak ada yang terbatalkan.
    from app.penggilingan.gudang1.services.milling import get_process_by_kode

    async with pg() as db:
        assert await get_process_by_kode(db, r.proc.kode_proses) is not None


async def test_pemiliknya_sendiri_tetap_bisa_membatalkan(pg, pabrik):
    """Pagar yang menolak segalanya bukan pagar, ia kerusakan."""
    from sqlalchemy import select

    from app.models import ActivityLog, User
    from app.penggilingan.gudang1.services.milling import (get_process_by_kode,
                                                           start_milling)
    from app.services import undo

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        r = await start_milling(db, user=u, nama_silo=["A"])
        log_id = (await db.execute(
            select(ActivityLog.id).where(ActivityLog.changed_by == u.id)
            .order_by(ActivityLog.id.desc()).limit(1))).scalars().first()

    async with pg() as db:
        u = await db.get(User, pabrik["user"])
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=u.id)
        pesan = await undo.undo_last(db, actor=u, cakupan=c, log_id=log_id)
        await db.commit()
    assert "Dibatalkan" in pesan

    async with pg() as db:
        assert await get_process_by_kode(db, r.proc.kode_proses) is None
