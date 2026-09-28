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
    # `silo_g2`, bukan `silo`: sejak 24 September 2026 kartu Gudang 2 memakai
    # kunci fase sendiri supaya katanya benar ("Di silo bahan", bukan "Transit di
    # silo kering" — silo Gudang 2 bukan silo pengering). Temuan QA T-1.
    silo = [x for x in b.menunggu if x.fase == "silo_g2"]
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


# ── "Selesai penyosohan" tak menuntut memilih silo bila cuma ada satu ──
#
# Keluhan pemilik 24 September 2026 07:14, QA 24 Sep (c) butir 4: prosesnya
# SATU silo, tetapi borangnya tetap menuntut memilih A atau B — dan pilihan
# yang ia tawarkan datang dari daftar mati, bukan dari silo yang benar-benar
# dipakai proses itu. Menekan Silo A yang tak pernah dipakai dijawab 400
# "Sebutkan silo mana yang selesai (A/B)": pesan yang tak masuk akal bagi
# orang yang baru saja menyebutkan silonya.

async def test_satu_silo_tak_perlu_disebut(pg, gudang2):
    """Proses satu silo: `nama_silo=None` cukup — layanan yang memilihnya.

    Jalur ini sudah ada di `polishing.py` sejak lama (`elif len(usages) == 1`);
    yang menghadangnya adalah gerbang di `api.py` yang menolak silo kosong
    tanpa syarat.
    """
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, selesai_penyosohan

    u = gudang2["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])
        s = await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                     nama_silo=None, sisa_kg=0)
    assert s.silo == "B" and s.selesai


async def test_silo_yang_tak_dipakai_proses_itu_ditolak_dengan_nama_silonya(pg, gudang2):
    """Pesan yang menyebut silo mana yang DIPAKAI, bukan "A/B" tetap.

    Operator yang salah pilih harus bisa membetulkannya tanpa menebak; dan
    pabrik yang silonya kelak bernama lain tak boleh disuruh mencari "A/B".
    """
    import pytest as _pytest

    from app.penggilingan.gudang2.polishing import (Gudang2Error, mulai_penyosohan,
                                                     selesai_penyosohan)

    u = gudang2["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])
        with _pytest.raises(Gudang2Error) as e:
            await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                     nama_silo="A", sisa_kg=0)
    assert "tidak memakai Silo A" in str(e.value) and "Silo B" in str(e.value)


async def test_dua_silo_tetap_wajib_disebut_lalu_sisanya_tidak(pg, gudang2):
    """Wajib HANYA bila memang ada lebih dari satu yang bisa dimaksud.

    Dan sesudah salah satunya bersisa, yang tinggal satu itu tak perlu disebut
    lagi: pilihan yang tak punya alternatif bukan pilihan.
    """
    import pytest as _pytest

    from app.penggilingan.gudang2.polishing import (Gudang2Error, mulai_penyosohan,
                                                     selesai_penyosohan)
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo

    u = gudang2["user"]
    async with pg() as db:
        # Silo A perlu isi dulu — penyosohan menolak silo kosong.
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=gudang2["intake_tumpukan"],
                                      nama_silo="A", berat=5_000)
        r = await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])
        kode = r.proc.kode_proses
        with _pytest.raises(Gudang2Error) as e:
            await selesai_penyosohan(db, user=u, kode=kode, nama_silo=None, sisa_kg=0)
        assert "Silo A" in str(e.value) and "Silo B" in str(e.value)

        await selesai_penyosohan(db, user=u, kode=kode, nama_silo="A", sisa_kg=0)
        s = await selesai_penyosohan(db, user=u, kode=kode, nama_silo=None, sisa_kg=0)
    assert s.silo == "B" and s.selesai


async def test_daftar_silo_hanya_milik_proses_itu_dan_yang_belum_selesai(pg, gudang2):
    """Daftar yang ditawarkan layar = silo yang benar-benar dipakai proses itu.

    Inilah yang menggantikan daftar mati A/B: tanpa `induk`, borangnya tak tahu
    silo mana yang dipakai proses yang barusan dipilih.
    """
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, selesai_penyosohan
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
    from app.web.api import sosoh_silo

    u = gudang2["user"]
    async with pg() as db:
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=gudang2["intake_tumpukan"],
                                      nama_silo="A", berat=5_000)
        r = await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])
        kode = r.proc.kode_proses

    assert [x["value"] for x in await sosoh_silo(induk=kode, user=u)] == ["A", "B"]
    # Tanpa induk tak ada jawaban — bukan seluruh silo pabrik.
    assert await sosoh_silo(induk="", user=u) == []
    assert await sosoh_silo(induk="POL-TIDAK-ADA", user=u) == []

    async with pg() as db:
        await selesai_penyosohan(db, user=u, kode=kode, nama_silo="A", sisa_kg=0)
    # Yang sudah bersisa tak ditawarkan lagi: menandainya dua kali menimpa
    # angka yang sudah dicatat operator.
    assert [x["value"] for x in await sosoh_silo(induk=kode, user=u)] == ["B"]


# ── Silo yang SEDANG disosoh tak berdiri di Antrian tunggu ──
#
# Laporan pemilik 24 September 2026 13:57: "Silo A · Gudang 2 · 2.000 kg · PK
# menunggu disosoh" berdiri di blok "Bisa dikerjakan sekarang" sementara
# penyosohan atas Silo A sedang berjalan. PK yang sama tergambar DUA KALI
# dengan dua cerita yang bertentangan.
#
# Sebabnya satu bendera GLOBAL di `_kartu_silo_g2` — "adakah penyosohan
# berjalan?" — yang tak tahu silo MANA yang dipakai. Tombolnya dicabut untuk
# semua silo, kartunya tetap dipancarkan untuk semua silo.

async def test_silo_yang_sedang_disosoh_tak_ada_di_antrean(pg, gudang2):
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
    from app.services.berjalan import untuk_operator_gudang2

    u = gudang2["user"]
    async with pg() as db:
        # Silo A benar-benar menunggu; Silo B (9.800) masuk mesin.
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=gudang2["intake_tumpukan"],
                                      nama_silo="A", berat=2_000)
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])

    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    antre = {x.kode for x in b.menunggu}
    assert "Silo B" not in antre, "silo yang sedang disosoh masih berdiri di antrean"
    assert "Silo A" in antre, "silo yang benar-benar menunggu ikut hilang"

    # Dan tak tergambar di dua layar sekaligus.
    jalan = {x.kode for x in b.berjalan}
    assert r.proc.kode_proses in jalan
    assert not (antre & jalan)

    # Silo yang menunggu tetap TANPA tombol — mesinnya satu.
    kartu_a = next(x for x in b.menunggu if x.kode == "Silo A")
    assert kartu_a.aksi is None and kartu_a.pilihan == []
    assert "mesin sosoh sedang dipakai" in kartu_a.keadaan


async def test_proses_dua_silo_menghapus_keduanya_dari_antrean(pg, gudang2):
    """"Mulai penyosohan" menerima A / B / AB — jadi yang dipakai HIMPUNAN,
    bukan satu nilai."""
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
    from app.services.berjalan import untuk_operator_gudang2

    u = gudang2["user"]
    async with pg() as db:
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=gudang2["intake_tumpukan"],
                                      nama_silo="A", berat=2_000)
        await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])

    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    antre = {x.kode for x in b.menunggu}
    assert "Silo A" not in antre and "Silo B" not in antre


async def test_silo_kembali_ke_antrean_sesudah_penyosohan_ditutup(pg, gudang2):
    """Sisa yang masih ada kembali jadi pekerjaan — lengkap dengan tombolnya."""
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, selesai_penyosohan
    from app.services.berjalan import untuk_operator_gudang2

    u = gudang2["user"]
    async with pg() as db:
        r = await mulai_penyosohan(db, user=u, nama_silos=["B"])
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="B", sisa_kg=1_500)

    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    kartu = next((x for x in b.menunggu if x.kode == "Silo B"), None)
    assert kartu is not None, "sisa di silo tak kembali jadi pekerjaan"
    assert kartu.aksi == "mulai_penyosohan" and kartu.pilihan


async def test_stok_silo_tak_berubah_selama_disosoh(pg, gudang2):
    """Yang berubah cuma ANTREAN. Barangnya memang masih di silo sampai
    prosesnya ditutup dan sisanya dicatat — jangan 'memperbaiki' ini dengan
    mengurangi stok saat proses dimulai."""
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import get_g2_silo, hitung_stok_silo
    from app.services.stok import pk_gudang2

    async with pg() as db:
        silo_b = await get_g2_silo(db, "B")
        sebelum = float(await hitung_stok_silo(db, silo_b.id))
        await mulai_penyosohan(db, user=gudang2["user"], nama_silos=["B"])

    async with pg() as db:
        sesudah = float(await hitung_stok_silo(db, silo_b.id))
        tempat = await pk_gudang2(db)
    assert sesudah == sebelum == 9_800
    assert any(t.tersedia == 9_800 for t in tempat), "layar Stok ikut berubah"


async def test_kartu_tumpukan_tetap_bisa_ditekan_selagi_menyosoh(pg, gudang2):
    """Keputusan pemilik 12 September: silo yang sedang dipoles boleh menerima
    tambahan. Perbaikan antrean tak boleh ikut mencabut jalan masuknya."""
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.services.berjalan import untuk_operator_gudang2

    async with pg() as db:
        await mulai_penyosohan(db, user=gudang2["user"], nama_silos=["B"])

    async with pg() as db:
        b = await untuk_operator_gudang2(db)
    tump = [x for x in b.menunggu if x.kelompok == "tumpukan"]
    assert tump, "kartu tumpukan hilang"
    assert any(p[0] == "pindah_tumpukan_silo" for p in tump[0].pilihan)


# ──────── Silo yang sisanya SUDAH dicatat, sementara silo lain berputar ────────

async def test_silo_yang_sisanya_sudah_dicatat_tetap_berkartu(pg, gudang2):
    """Temuan QA 24 September 2026, sekeluarga dengan silo Gudang 1 yang kedua.

    Satu penyosohan boleh memakai dua silo, dan sisanya dicatat SATU PER SATU.
    Sampai temuan ini, seluruh silo milik proses yang berjalan disembunyikan
    dari antrean tanpa memeriksa apakah sisanya sudah dicatat — jadi operator
    yang menutup Silo A dengan sisa 500 kg melihat 500 kg itu LENYAP dari
    layarnya, sementara barangnya berdiri di silo. Yang hilang dari layar adalah
    yang tak dikerjakan siapa pun.

    Yang benar: berkartu (sebab ia memang menunggu giliran berikutnya), TANPA
    tombol (sebab mesinnya masih dipakai), dan keterangannya menyebut keadaan
    itu apa adanya.
    """
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, selesai_penyosohan
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from app.services.berjalan import untuk_operator_gudang2
    from app.database import now_local
    from app.models import Supplier
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from sqlalchemy import select

    u = gudang2["user"]
    async with pg() as db:
        sup = (await db.execute(select(Supplier.id))).scalars().first()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20260924-03", supplier_id=sup, berat_total_kg=4_000,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(), input_by=u.id,
            status_batch="diterima", flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        await masukkan_pk_luar(db, user=u, kode="PKB-20260924-03", tujuan="silo_a")

        r = await mulai_penyosohan(db, user=u, nama_silos=["A", "B"])
        # Selagi KEDUANYA di dalam mesin, tak satu pun berkartu antrean.
        b = await untuk_operator_gudang2(db)
        assert [x for x in b.menunggu if x.fase == "silo_g2"] == [], \
            "silo yang di dalam mesin masih berkartu antrean"

        # Silo A ditutup dengan sisa 500 kg; Silo B masih berputar.
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=500)
        b2 = await untuk_operator_gudang2(db)

    kartu = [x for x in b2.menunggu if x.kode == "Silo A"]
    assert len(kartu) == 1, f"sisa 500 kg lenyap dari antrean: {b2.menunggu}"
    k = kartu[0]
    assert k.aksi is None, "mesinnya masih dipakai, tombolnya tak boleh ada"
    assert "sisanya sudah dicatat" in k.keadaan, k.keadaan
    # Silo B masih di dalam mesin — ia tetap tanpa kartu antrean.
    assert not any(x.kode == "Silo B" for x in b2.menunggu)
    # Lencana == kartu yang digambar. Dua tempat yang menghitungnya
    # sendiri-sendiri akan berselisih, dan yang salah adalah yang lebih jarang
    # dibaca.
    assert b2.jumlah_menunggu == len(b2.menunggu)
    assert b2.lencana()["MENUNGGU"] == len(b2.menunggu)


# ──────── Penyosohan dari beberapa silo, lewat BORANGNYA ────────

async def test_borang_penyosohan_membaca_master_bukan_tupel(pg, gudang2):
    """Daftar silo bahan datang dari MASTER, dan saringannya sama dengan pagar
    layanannya.

    Layanan `mulai_penyosohan` sudah menerima berapa pun silo sejak 12
    September 2026; yang mengurungnya jadi tiga kemungkinan adalah daftar
    pilihan "A / B / A+B" yang diketik di kode. Borang yang membaca master ikut
    melihat silo yang ditambahkan lewat Pengaturan → Alat.

    Yang TIDAK ditawarkan sama pentingnya: silo kosong, dan silo yang sedang di
    dalam mesin. Borang yang menawarkan silo yang kemudian ditolak layanannya
    membuat orang mengira aplikasinya rusak, padahal keduanya benar
    sendiri-sendiri.
    """
    from sqlalchemy import select

    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.web.api import silo_bahan_g2

    u = gudang2["user"]
    async with pg() as db:
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        # Silo yang ditambahkan belakangan lewat Pengaturan → Alat.
        db.add(Silo(nama_silo="Silo C", warehouse_id=g2.id, status="kosong"))
        await db.commit()
        uu = await db.get(User, u.id)

    daftar = await silo_bahan_g2(user=uu)
    nilai = [x["value"] for x in daftar]
    assert nilai == ["B"], f"yang ditawarkan bukan hanya silo berisi: {daftar}"
    assert any("9.800" in x["label"] for x in daftar), "isinya tak disebut"

    # Sesudah B masuk mesin, ia tak ditawarkan lagi — sama seperti pagar
    # layanannya, yang menolak silo yang sedang dipakai proses berjalan.
    async with pg() as db:
        uu = await db.get(User, u.id)
        await mulai_penyosohan(db, user=uu, nama_silos=["B"])
    assert await silo_bahan_g2(user=uu) == []


async def test_penyosohan_beberapa_silo_lewat_pintu(pg, gudang2):
    """Ujung ke ujung lewat pintu HTTP-nya, bukan cuma layanannya: yang dulu
    menerjemahkan pilihan jadi silo adalah peta "A"/"B"/"AB" di pintu itu."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Supplier, User
    from app.penggilingan.gudang2.models import PkPurchaseBatch, PolishingSiloUsage
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from app.web.api import MulaiPenyosohanReq, act_mulai_penyosohan

    u = gudang2["user"]
    async with pg() as db:
        sup = (await db.execute(select(Supplier.id))).scalars().first()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-20260924-05", supplier_id=sup, berat_total_kg=4_000,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=u.id, status_batch="diterima", flag_unverified=True,
            sumber_berat="manual"))
        await db.commit()
        await masukkan_pk_luar(db, user=u, kode="PKB-20260924-05", tujuan="silo_a")
        uu = await db.get(User, u.id)

    hasil = await act_mulai_penyosohan(MulaiPenyosohanReq(silo=["A", "B"]), user=uu)
    assert hasil["ok"]
    assert "13800" in hasil["pesan"].replace(".", ""), hasil["pesan"]  # 4.000 + 9.800
    async with pg() as db:
        n = (await db.execute(select(PolishingSiloUsage))).scalars().all()
    assert len(n) == 2, "tak semua silo tercatat sebagai bahan prosesnya"


async def test_bentuk_tunggal_dari_kartu_tetap_diterima(pg, gudang2):
    """Kartu silo mengirim satu huruf apa adanya. Pintu yang cuma menerima
    daftar akan mematikan jalan yang paling sering dipakai."""
    from app.models import User
    from app.web.api import MulaiPenyosohanReq, act_mulai_penyosohan

    async with pg() as db:
        uu = await db.get(User, gudang2["user"].id)
    hasil = await act_mulai_penyosohan(MulaiPenyosohanReq(silo="B"), user=uu)
    assert hasil["ok"] and "9800" in hasil["pesan"].replace(".", "")


async def test_pilihan_lama_ab_dijawab_dengan_kalimat_yang_menolong(pg, gudang2):
    """Halaman di ponsel operator berumur panjang.

    Sebelum 24 September 2026 borangnya menawarkan A / B / A+B, dan "AB" satu
    nilai. Yang belum memuat ulang masih mengirimkannya, dan jawaban apa adanya
    — "Silo AB Gudang 2 tidak ditemukan" — menyebut nama silo yang tak pernah
    ada, seolah pabriknya yang kehilangan silo. Temuan QA 24 September.
    """
    from app.models import User
    from app.penggilingan.gudang2.polishing import Gudang2Error, mulai_penyosohan

    async with pg() as db:
        u = await db.get(User, gudang2["user"].id)
        with pytest.raises(Gudang2Error) as e:
            await mulai_penyosohan(db, user=u, nama_silos=["AB"])
    pesan = str(e.value)
    assert "Muat ulang" in pesan and "daftar" in pesan, pesan
    assert "Silo AB" not in pesan, "masih menyebut silo yang tak pernah ada"

    # Huruf tunggal yang memang tak ada tetap dijawab apa adanya: itu bukan
    # borang basi, melainkan silo yang belum dibuat di master.
    async with pg() as db:
        u = await db.get(User, gudang2["user"].id)
        with pytest.raises(Gudang2Error) as e2:
            await mulai_penyosohan(db, user=u, nama_silos=["Z"])
    assert "Silo Z" in str(e2.value)


async def test_status_silo_g2_tak_pernah_berbohong(pg, gudang2):
    """Temuan QA 28 September 2026: silo Gudang 2 yang berisi PK tetap tercap
    `kosong`.

    Sebabnya lebih luas daripada satu cap yang salah — Gudang 2 TAK PERNAH
    menulis `Silo.status`, jadi seluruh silonya membeku pada nilai yang ditanam
    seed. Silo B fixture ini berisi 9.800 kg sejak awal dan tetap berkata
    "kosong".

    Diuji sebagai PERILAKU, bukan dengan membaca sumber: sesudah TIAP operasi
    yang mengubah isi silo, status wajib sama dengan "stoknya di atas nol".
    Pagar yang menegaskan "corong X memanggil fungsi Y" pecah pada tiap
    perapian kode dan tak menangkap corong KEEMPAT yang lahir kemudian; yang
    ini menangkapnya, sebab yang dijaga aturannya.
    """
    from sqlalchemy import select

    from app.models import Silo, User
    from app.penggilingan.gudang2.polishing import (mulai_penyosohan,
                                                    selesai_penyosohan)
    from app.penggilingan.gudang2.service import (hitung_stok_silo,
                                                  pindah_tumpukan_ke_silo)

    async def selaras(kapan):
        async with pg() as db:
            for huruf in ("A", "B"):
                sid = (await db.execute(select(Silo.id).where(
                    Silo.nama_silo == f"Silo {huruf}"))).scalars().one()
                silo = await db.get(Silo, sid)
                stok = await hitung_stok_silo(db, sid)
                harus = "terisi" if stok > 0.001 else "kosong"
                assert silo.status == harus, (
                    f"{kapan} · Silo {huruf}: stok {stok:.0f} kg, status "
                    f"'{silo.status}' — seharusnya '{harus}'")

    # 1 · PK luar masuk langsung ke silo — corong `_add_intake`, dan keadaan
    #     yang dulu berbohong: Silo B berisi 9.800 kg, statusnya "kosong".
    await selaras("sesudah PK luar masuk")

    # 2 · Tumpukan dipindah ke silo — corong `_catat_pindah`.
    async with pg() as db:
        u = await db.get(User, gudang2["user"].id)
        await pindah_tumpukan_ke_silo(db, user=u,
                                      intake_id=gudang2["intake_tumpukan"],
                                      nama_silo="A", berat=2_000)
    await selaras("sesudah tumpukan dipindah ke Silo A")

    # 3 · Penyosohan menghabiskan Silo A, lalu silonya dibebaskan — corong
    #     `selesai_penyosohan`. Inilah langkah yang difoto QA.
    async with pg() as db:
        u = await db.get(User, gudang2["user"].id)
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
    async with pg() as db:
        u = await db.get(User, gudang2["user"].id)
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses,
                                 nama_silo="A", sisa_kg=0)
    await selaras("sesudah Silo A dibebaskan")
