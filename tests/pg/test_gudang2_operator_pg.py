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
