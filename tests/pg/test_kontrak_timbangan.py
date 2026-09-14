"""Produksi hanya memakai tiket timbang yang SAH, dan tahu saat tiket berubah.

Lima temuan QA 11 September 2026 di perbatasan dua aplikasi.

**T-02 / X-07.** Kata `status_transaksi` tak muncul sama sekali di kode
produksi. Tiket yang sudah DIBATALKAN di Pos Timbang tetap ditawarkan untuk
ditautkan, tetap bisa jadi batch, dan pollernya tetap menyalin berat notanya.
Truk yang ditolak dan tiketnya ditutup paksa pun mendorong 9.800 kg ke stok.

**X-13.** Satu tiket bisa jadi batch GABAH sekaligus batch PK: uniknya
dipasang per tabel, jadi tak ada yang melarang tiket yang sama dipakai dua
kali di dua tabel berbeda. Barang yang sama terhitung dua kali.

**X-08.** Rekonsiliasi hanya membandingkan ANGKA. Tiket yang dibatalkan,
pemasoknya dikoreksi, komoditasnya diganti, atau ditutup paksa sesudah
ditautkan — tak satu pun terlihat di mana pun.

**X-06.** `float(kg)` pada berat NULL — yaitu batch yang masih menunggu bobot
dari jembatan. Beranda kosong DIAM-DIAM, dan `/internal/produksi/operasional`
menjawab 500 sehingga briefing Kantor berkata "sistem produksi bermasalah".
Satu truk yang ditautkan sebelum bobot finalnya turun cukup untuk itu.

Tiketnya dibuat DI SINI lewat SQL mentah, bukan lewat model timbangan:
produksi memang tak memiliki tabel itu, dan uji yang mengimpor modelnya akan
diam-diam membuat produksi bergantung pada repo sebelah.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES
        (:kode, :tanggal, 'MASUK', :jenis, 'DUA_KALI', :supplier_id, :pihak,
         :nopol, 12000, :waktu, :netto, :nota, :status_tiket, :status_trx)
    RETURNING id
""")


async def _tiket(db, kode, *, jenis="GABAH_KERING", supplier_id=None, netto=9800,
                 nota=0, status_tiket="SELESAI", status_trx="AKTIF", pihak="Pak Uji",
                 nopol="B 1234 UJ"):
    """Satu tiket timbang MASUK, apa adanya seperti yang ditulis Pos Timbang."""
    from app.database import now_local

    return (await db.execute(_SQL_TIKET, {
        "kode": kode, "tanggal": now_local().date(), "jenis": jenis,
        "supplier_id": supplier_id, "pihak": pihak, "nopol": nopol,
        "waktu": datetime.now(timezone.utc), "netto": netto, "nota": nota,
        "status_tiket": status_tiket, "status_trx": status_trx,
    })).scalar_one()


@pytest_asyncio.fixture
async def staf(pg):
    """Jalur PK luar hanya terbuka untuk staf ke atas.

    Perannya diambil dari `PERAN_ADMIN_KEATAS`, bukan diketik: daftar itulah
    yang menentukan siapa yang boleh, dan uji yang mengetik namanya sendiri
    akan tetap lulus pada hari daftarnya berubah.
    """
    from app.models import User
    from app.peran import PERAN_ADMIN_KEATAS

    async with pg() as db:
        u = User(nama="Staf Uji", role=PERAN_ADMIN_KEATAS[-1], status="aktif")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


# ─────────────────────────── X-06 ───────────────────────────

async def test_beranda_tak_jatuh_karena_batch_menunggu_bobot(pg, pemakai, pemasok):
    """Batch yang menunggu bobot beratnya NULL — dan itu keadaan yang SAH,
    bukan data rusak: tiket sudah ditautkan, timbangan keduanya belum."""
    from app.models import PurchaseBatch
    from app.services import dashboard

    async with pg() as db:
        db.add(PurchaseBatch(
            kode_batch="GB-MENUNGGU-01", supplier_id=pemasok.id,
            tanggal_pembelian=_hari(), waktu_pembelian=datetime.now(timezone.utc),
            berat_total_kg=None, kondisi_gabah="basah", input_by=pemakai.id))
        await db.commit()
        hasil = await dashboard._gabah_hari_ini(db, _hari())

    assert hasil["batch"] == 1
    assert hasil["total_kg"] == 0.0
    # Yang menunggu disebut TERPISAH — kalau ikut dijumlahkan sebagai nol, ia
    # hilang dari pandangan justru saat ia perlu ditindak.
    assert hasil.get("menunggu_bobot") == 1


async def test_satu_bagian_galat_tak_mengosongkan_beranda(pg, monkeypatch):
    """Satu bagian yang meledak tak boleh mengosongkan seluruh halaman —
    apalagi diam-diam. Kantor membaca halaman yang sama lewat /internal."""
    from app.services import dashboard

    async def _meledak(*a, **k):
        raise RuntimeError("bagian ini rusak")

    monkeypatch.setattr(dashboard, "_gabah_hari_ini", _meledak)

    async with pg() as db:
        d = await dashboard.dashboard_data(db)

    # Bagian lain tetap terisi, dan yang gagal DISEBUT — bukan ditelan.
    assert isinstance(d, dict)
    assert d.get("galat"), "bagian yang gagal tak dilaporkan"


# ─────────────────────── T-02 / X-07 ───────────────────────

async def test_tiket_batal_tak_ditawarkan_di_antrean(pg, pemasok):
    """Tiket VOID dan tiket TUTUP PAKSA hilang dari daftar pilihan."""
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif

    async with pg() as db:
        await _tiket(db, "TM-SAH-01", supplier_id=pemasok.id)
        await _tiket(db, "TM-VOID-01", supplier_id=pemasok.id, status_trx="VOID")
        await _tiket(db, "TM-PAKSA-01", supplier_id=pemasok.id,
                     status_tiket="DITUTUP_PAKSA")
        await db.commit()
        daftar = await tiket_masuk_aktif(db)

    assert [t["kode"] for t in daftar] == ["TM-SAH-01"]


@pytest.mark.parametrize("keadaan", [
    {"status_trx": "VOID"},
    {"status_tiket": "DITUTUP_PAKSA"},
])
async def test_tiket_batal_tak_bisa_diambil_satuan(pg, pemasok, keadaan):
    """Bukan cuma hilang dari daftar — id-nya yang diketik langsung pun ditolak.
    Daftar yang menyaring hanya menentukan apa yang MUDAH dipilih."""
    from app.penggilingan.gudang1.services.timbang_link import ambil_tiket

    async with pg() as db:
        tid = await _tiket(db, "TM-X-01", supplier_id=pemasok.id, **keadaan)
        await db.commit()
        assert await ambil_tiket(db, tid) is None


@pytest.mark.parametrize("keadaan", [
    {"status_trx": "VOID"},
    {"status_tiket": "DITUTUP_PAKSA"},
])
async def test_batch_tak_bisa_dibuat_dari_tiket_batal(pg, pemakai, pemasok, keadaan):
    """Truk yang DITOLAK tak boleh mendorong 9.800 kg masuk pembukuan."""
    from app.penggilingan.gudang1.services.purchase import (
        create_purchase_batch_dari_timbang,
    )

    async with pg() as db:
        tid = await _tiket(db, "TM-TOLAK-01", supplier_id=pemasok.id, **keadaan)
        await db.commit()
        with pytest.raises(ValueError):
            await create_purchase_batch_dari_timbang(
                db, user=pemakai, timbangan_transaksi_id=tid)


async def test_poller_tak_menyalin_bobot_tiket_batal(pg, pemakai, pemasok):
    """Batch dibuat saat tiketnya masih sah, lalu tiketnya dibatalkan. Bobot
    notanya TIDAK boleh menyusul masuk lewat poller."""
    from app.models import PurchaseBatch
    from app.penggilingan.gudang1.services.timbang_link import sinkron_bobot_menunggu

    async with pg() as db:
        tid = await _tiket(db, "TM-SUSUL-01", supplier_id=pemasok.id, netto=9800)
        db.add(PurchaseBatch(
            kode_batch="GB-SUSUL-01", supplier_id=pemasok.id,
            tanggal_pembelian=_hari(), waktu_pembelian=datetime.now(timezone.utc),
            berat_total_kg=None, sumber_berat="menunggu", kondisi_gabah="kering",
            input_by=pemakai.id, timbangan_transaksi_id=tid))
        await db.execute(
            text("UPDATE timbangan_transaksi SET status_transaksi='VOID' WHERE id=:i"),
            {"i": tid})
        await db.commit()

    async with pg() as db:
        assert await sinkron_bobot_menunggu(db) == 0

    async with pg() as db:
        berat = (await db.execute(text(
            "SELECT berat_total_kg FROM purchase_batches WHERE kode_batch='GB-SUSUL-01'"
        ))).scalar_one()
    assert berat is None, "bobot tiket batal tetap masuk"


# ─────────────────────────── X-13 ───────────────────────────

async def test_satu_tiket_tak_bisa_jadi_dua_batch(pg, pemakai, staf, pemasok):
    """Uniknya dipasang PER TABEL, jadi tiket yang sama bisa dipakai di
    `purchase_batches` DAN `pk_purchase_batches`. Barang yang sama terhitung
    dua kali, dan tak ada satu constraint pun yang melarangnya.

    Komoditas tiketnya sengaja DIUBAH di tengah jalan — persis yang bisa
    dilakukan Pos Timbang. Tanpa itu, yang menolak permintaan kedua adalah
    pemeriksaan komoditas, dan pemeriksaan silang antar-tabel tak pernah
    benar-benar diuji.
    """
    from app.penggilingan.gudang1.services.purchase import (
        create_purchase_batch_dari_timbang,
    )
    from app.penggilingan.gudang2.service import create_pk_purchase_dari_timbang

    async with pg() as db:
        tid = await _tiket(db, "TM-DOBEL-01", jenis="BERAS_PK", supplier_id=pemasok.id)
        await db.commit()
        await create_pk_purchase_dari_timbang(
            db, user=staf, timbangan_transaksi_id=tid, jenis_pk="ks")

    async with pg() as db:
        await db.execute(
            text("UPDATE timbangan_transaksi SET jenis_kode='GABAH_KERING' "
                 "WHERE id=:i"), {"i": tid})
        await db.commit()

    async with pg() as db:
        with pytest.raises(ValueError):
            await create_purchase_batch_dari_timbang(
                db, user=pemakai, timbangan_transaksi_id=tid)

    async with pg() as db:
        n = (await db.execute(text(
            "SELECT count(*) FROM purchase_batches"))).scalar_one()
    assert n == 0, "satu tiket jadi batch PK sekaligus batch gabah"


async def test_komoditas_diperiksa_di_layanan_bukan_hanya_di_daftar(pg, pemakai,
                                                                    pemasok):
    """Tiket PK yang id-nya dikirim ke jalur gabah ditolak di LAYANAN."""
    from app.penggilingan.gudang1.services.purchase import (
        create_purchase_batch_dari_timbang,
    )

    async with pg() as db:
        tid = await _tiket(db, "TM-PK-01", jenis="BERAS_PK", supplier_id=pemasok.id)
        await db.commit()
        with pytest.raises(ValueError):
            await create_purchase_batch_dari_timbang(
                db, user=pemakai, timbangan_transaksi_id=tid)


# ─────────────────────────── X-08 ───────────────────────────

async def test_rekonsiliasi_menangkap_tiket_batal(pg, pemakai, pemasok):
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        tid = await _tiket(db, "TM-R1", supplier_id=pemasok.id)
        await _batch(db, "GB-R1", tid, pemakai, pemasok)
        await db.execute(
            text("UPDATE timbangan_transaksi SET status_transaksi='VOID' WHERE id=:i"),
            {"i": tid})
        await db.commit()
        d = await rekonsiliasi(db)

    assert _tag(d, "tiket_batal") == ["GB-R1"]


async def test_rekonsiliasi_menangkap_pemasok_dikoreksi(pg, pemakai, pemasok):
    from app.models import Supplier
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        lain = Supplier(nama_supplier="Pemasok Lain")
        db.add(lain)
        await db.flush()
        tid = await _tiket(db, "TM-R2", supplier_id=pemasok.id)
        await _batch(db, "GB-R2", tid, pemakai, pemasok)
        # Pos Timbang membetulkan pemasoknya SESUDAH batch dibuat.
        await db.execute(
            text("UPDATE timbangan_transaksi SET supplier_id=:s WHERE id=:i"),
            {"s": lain.id, "i": tid})
        await db.commit()
        d = await rekonsiliasi(db)

    assert _tag(d, "pemasok_beda") == ["GB-R2"]


async def test_rekonsiliasi_menangkap_komoditas_diubah(pg, pemakai, pemasok):
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        tid = await _tiket(db, "TM-R3", supplier_id=pemasok.id)
        await _batch(db, "GB-R3", tid, pemakai, pemasok)
        await db.execute(
            text("UPDATE timbangan_transaksi SET jenis_kode='BERAS_PK' WHERE id=:i"),
            {"i": tid})
        await db.commit()
        d = await rekonsiliasi(db)

    assert _tag(d, "komoditas_beda") == ["GB-R3"]


async def test_rekonsiliasi_menangkap_tutup_paksa_setelah_tertaut(pg, pemakai,
                                                                  pemasok):
    """Batch yang menunggu bobot dari tiket yang ditutup paksa akan menunggu
    SELAMANYA — dan tak ada satu layar pun yang mengatakannya."""
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        tid = await _tiket(db, "TM-R4", supplier_id=pemasok.id, netto=None,
                           status_tiket="TERBUKA")
        await _batch(db, "GB-R4", tid, pemakai, pemasok, berat=None,
                     sumber="menunggu")
        await db.execute(
            text("UPDATE timbangan_transaksi SET status_tiket='DITUTUP_PAKSA' "
                 "WHERE id=:i"), {"i": tid})
        await db.commit()
        d = await rekonsiliasi(db)

    assert _tag(d, "tutup_paksa") == ["GB-R4"]


async def test_tiket_batal_tak_dituntut_sebagai_belum_tertaut(pg, pemasok):
    """Tiket yang memang dibatalkan bukan "ditimbang tapi tak tercatat".
    Daftar tugas yang isinya pekerjaan keliru berhenti dibaca orang."""
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        await _tiket(db, "TM-R5", supplier_id=pemasok.id, status_trx="VOID")
        await db.commit()
        d = await rekonsiliasi(db)

    assert d["belum_tertaut"] == []


# ─────────────────────────── bantu ───────────────────────────

async def _batch(db, kode, tid, pemakai, pemasok, *, berat=9800.0, sumber="timbangan"):
    from app.models import PurchaseBatch

    db.add(PurchaseBatch(
        kode_batch=kode, supplier_id=pemasok.id, tanggal_pembelian=_hari(),
        waktu_pembelian=datetime.now(timezone.utc), berat_total_kg=berat,
        sumber_berat=sumber, kondisi_gabah="kering", input_by=pemakai.id,
        timbangan_transaksi_id=tid))
    await db.flush()


def _tag(d: dict, tag: str) -> list[str]:
    return [x["kode_batch"] for x in d.get("menyimpang", []) if x["masalah"] == tag]


def _hari():
    from app.database import now_local
    return now_local().date()
