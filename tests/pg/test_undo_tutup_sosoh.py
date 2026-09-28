"""Satu ketukan tak sengaja pada "selesai penyosohan" punya jalan kembali.

Laporan operator Gudang 2, 28 September 2026 — dua keluhan, satu kalimat:
"jika operator tidak sengaja terpencet selesai penyosohan, tetapi belum
memasukkan hasil beras dll, hasilnya akan hilang."

Yang pertama dijawab PAGAR: penutupan tanpa satu pun catatan hasil ditolak.
Yang kedua dijawab berkas ini. Pagar tak menolong penutupan yang hasilnya sudah
dicatat tetapi sisanya salah, atau silonya salah — dan sampai hari itu SELURUH
penutupan penyosohan tak punya jalan kembali sama sekali, sementara penutupan
GILING sudah punya sejak lama. Dua gudang mengerjakan hal serupa dengan
kemampuan yang berbeda, dan orangnya berpindah antar gudang.

Yang dijaga di sini bukan cuma "bisa dibatalkan", melainkan bahwa pembatalannya
mengembalikan SELURUH keadaan dan MENOLAK saat hilirnya sudah berdiri di atas
penutupan itu. Pembatalan yang mengembalikan separuh keadaan lebih buruk
daripada pembatalan yang menolak: tak ada satu pun layar yang menyebut separuh
mana yang tertinggal.
"""
from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def sosoh(pg):
    """Gudang 2, Silo A & B, satu operator; Silo B berisi 9.800 kg PK luar."""
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
        db.add(PkPurchaseBatch(
            kode_batch="PKB-U-01", supplier_id=s.id, berat_total_kg=9_800,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        await db.refresh(u)
        await masukkan_pk_luar(db, user=u, kode="PKB-U-01", tujuan="silo_b")
        return {"user_id": u.id}


async def _tutup(pg, uid, *, sisa=800.0, silo="B"):
    """Mulai satu penyosohan Silo B, catat hasil, lalu tutup. → kode proses."""
    from app.models import User
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                    selesai_penyosohan)
    async with pg() as db:
        u = await db.get(User, uid)
        r = await mulai_penyosohan(db, user=u, nama_silos=[silo])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="medium",
                           berat_kg=6_000)
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo=silo, sisa_kg=sisa)
        return r.proc.kode_proses


async def _undo(pg, uid):
    from app.models import User
    from app.services import undo
    async with pg() as db:
        u = await db.get(User, uid)
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=u.id)
        pesan = await undo.undo_last(db, actor=u, cakupan=c)
        await db.commit()
        return pesan


async def _proc(pg, kode):
    from sqlalchemy import select

    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage
    async with pg() as db:
        p = (await db.execute(select(PolishingProcess).where(
            PolishingProcess.kode_proses == kode))).scalars().one()
        us = (await db.execute(select(PolishingSiloUsage).where(
            PolishingSiloUsage.polishing_process_id == p.id))).scalars().all()
        return p, list(us)


async def test_tombol_undo_menawarkan_penutupan_penyosohan(pg, sosoh):
    """Yang ditawarkan tombol adalah PENUTUPAN SILO, dan itu bukan detail.

    Penutupan mencatat DUA baris audit saat seluruh silo bersisa: satu pada
    `polishing_process` ("prosesnya selesai") dan satu pada
    `polishing_silo_usage` ("silo ini bersisa segini"). Hanya yang kedua bisa
    dibatalkan — yang pertama `record_id`-nya prosesnya, jadi pada proses dua
    silo pembatalan tak punya cara mengetahui silo mana yang barusan ditutup.

    Pratinjau undo memilih baris TERBARU apa pun tabelnya, jadi yang menentukan
    tombolnya benar adalah URUTAN penulisannya. Uji ini menjaga urutan itu:
    sekali tertukar, tombolnya menolak dengan "belum bisa di-undo" pada
    pekerjaan yang sebetulnya sudah bisa.
    """
    from app.models import User
    from app.services import undo

    await _tutup(pg, sosoh["user_id"])
    async with pg() as db:
        u = await db.get(User, sosoh["user_id"])
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=u.id)
        pra = await undo.pratinjau_terakhir(db, cakupan=c)
    assert pra is not None, "tak ada tindakan terakhir yang bisa dilihat"
    assert pra.tabel == "polishing_silo_usage", (
        f"yang ditawarkan {pra.tabel} — pembatalan takkan tahu silo mana")
    assert pra.didukung, "penutupan penyosohan masih dianggap tak bisa dibatalkan"
    assert "penyosohan" in pra.label.lower(), pra.label


async def test_pembatalan_membuka_silo_DAN_prosesnya_kembali(pg, sosoh):
    """Seluruh keadaan, bukan separuhnya: sisa, terpakai, status proses, waktu
    selesai, dan stok silonya."""
    from app.penggilingan.gudang2.service import hitung_stok_silo

    kode = await _tutup(pg, sosoh["user_id"], sisa=800)
    p, us = await _proc(pg, kode)
    assert p.status == "selesai" and float(us[0].berat_terpakai_kg) == 9_000

    pesan = await _undo(pg, sosoh["user_id"])
    # Kalimatnya menyebut SILO MANA dan LOT MANA: yang membatalkan berdiri di
    # gudang dengan dua silo, dan "penutupan dibatalkan" tanpa keduanya menuntut
    # ia membuka layar lain untuk tahu apa yang barusan ia ubah.
    assert "Silo B" in pesan and kode in pesan, pesan

    p, us = await _proc(pg, kode)
    assert p.status == "proses", "prosesnya tetap tertutup"
    assert p.waktu_selesai is None, "waktu selesai tertinggal"
    assert us[0].berat_akhir_kg is None, "sisanya tertinggal"
    assert us[0].berat_terpakai_kg is None, "terpakainya tertinggal"
    async with pg() as db:
        # Stok silo kembali SELURUH bahannya — 9.800, bukan sisa 800: PK-nya
        # kembali dianggap belum terpakai, sebab prosesnya belum selesai.
        assert await hitung_stok_silo(db, us[0].silo_id) == 9_800


async def test_pembatalan_membuka_kembali_jeda_yang_ikut_ditutup(pg, sosoh):
    """P-K-17 berlaku dua arah.

    Penutupan menutup jeda yang masih berjalan supaya jam tertahan tak terus
    bertambah untuk mesin yang sudah selesai. Kalau pembatalan membiarkannya
    tertutup, prosesnya kembali berjalan sambil kehilangan catatan bahwa ia
    sedang berhenti — dan operator yang menekan "lanjutkan" akan ditolak dengan
    kalimat yang menyebut tak ada jeda terbuka.
    """
    from app.models import User
    from app.penggilingan.gudang1.services.jeda import hentikan, jeda_terbuka
    from app.penggilingan.gudang2.polishing import (catat_output, mulai_penyosohan,
                                                    selesai_penyosohan)

    uid = sosoh["user_id"]
    async with pg() as db:
        u = await db.get(User, uid)
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])
        kode = r.proc.kode_proses
        await catat_output(db, user=u, kode=kode, jenis="medium", berat_kg=6_000)
        await hentikan(db, user=u, jenis="penyosohan", kode=kode,
                       sebab="mesin_utama")
        await selesai_penyosohan(db, user=u, kode=kode, nama_silo="B", sisa_kg=800)
        assert await jeda_terbuka(db, "penyosohan", r.proc.id) is None

    await _undo(pg, uid)
    async with pg() as db:
        assert await jeda_terbuka(db, "penyosohan", r.proc.id) is not None, \
            "jeda tetap tertutup — jam tertahan berhenti mencatat"


async def test_menolak_bila_hasilnya_sudah_dikemas(pg, sosoh):
    """Beras yang sudah jadi karung tak bisa kembali jadi proses yang belum
    selesai: pengemasannya sendiri tidak ikut terbatalkan, jadi yang tersisa
    adalah karung tanpa asal."""
    from app.database import now_local
    from app.models import User
    from app.penggilingan.inventory.models import FinishedGoodsStock
    from app.services import undo

    kode = await _tutup(pg, sosoh["user_id"])
    p, _ = await _proc(pg, kode)
    async with pg() as db:
        from sqlalchemy import select

        from app.models import PackageSize, PackagingMaterial, ProductSku
        sku = (await db.execute(select(ProductSku).limit(1))).scalars().first()
        if sku is None:
            # SKU dirakit di sini, bukan lewat `seed_master`: yang diuji
            # PENOLAKANNYA, dan SKU mana pun sama saja bagi penolakan itu.
            bahan = PackagingMaterial(kode="PP25", nama="Karung PP 25 kg")
            ukuran = PackageSize(ukuran_kg=25)
            db.add_all([bahan, ukuran])
            await db.flush()
            sku = ProductSku(kategori="beras", packaging_material_id=bahan.id,
                             package_size_id=ukuran.id)
            db.add(sku)
            await db.flush()
        db.add(FinishedGoodsStock(
            product_sku_id=sku.id, source_type="polishing", source_id=p.id,
            jumlah_karung=10, berat_total_kg=250, waktu=now_local(),
            input_by=sosoh["user_id"]))
        await db.commit()

    with pytest.raises(undo.UndoError) as e:
        await _undo(pg, sosoh["user_id"])
    assert "dikemas" in str(e.value), str(e.value)


async def test_menolak_bila_silonya_sudah_dipakai_penyosohan_lain(pg, sosoh):
    """`mulai_penyosohan` menolak silo yang sedang dipoles. Membuka yang ini
    akan menghasilkan dua proses terbuka pada satu silo — keadaan yang tak satu
    pun layar bisa menggambar, dan yang stoknya terhitung dua kali."""
    from app.models import User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.services import undo

    uid = sosoh["user_id"]
    kode = await _tutup(pg, uid)
    _, us = await _proc(pg, kode)
    async with pg() as db:
        u = await db.get(User, uid)
        await mulai_penyosohan(db, user=u, nama_silos=["B"])   # silonya direbut

    # Penangannya dipanggil LANGSUNG, dengan baris yang dimaksud. Lewat
    # `undo_last` yang terpilih adalah pembukaan proses kedua — ia tindakan yang
    # lebih baru, dan itu memang benar. Yang diuji di sini penolakannya; yang
    # menjaga pemilihan barisnya `test_tombol_undo_menawarkan_penutupan_penyosohan`.
    async with pg() as db:
        with pytest.raises(undo.UndoError) as e:
            await undo._undo_tutup_silo_sosoh(db, us[0].id)
    assert "dipakai penyosohan" in str(e.value), str(e.value)


async def test_dua_ketukan_tak_membuka_silo_kedua(pg, sosoh):
    """Yang sudah dibatalkan ditolak dengan kalimatnya sendiri, bukan diam-diam
    membuka silo lain atau menulis `berat_terpakai` negatif."""
    from app.services import undo

    uid = sosoh["user_id"]
    kode = await _tutup(pg, uid)
    await _undo(pg, uid)
    p, us = await _proc(pg, kode)

    from app.models import User
    async with pg() as db:
        u = await db.get(User, uid)
        with pytest.raises(undo.UndoError) as e:
            await undo._undo_tutup_silo_sosoh(db, us[0].id)
    assert "sudah terbuka" in str(e.value), str(e.value)
