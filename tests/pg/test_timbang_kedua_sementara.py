"""Timbang kedua "Simpan sementara" di Pos Timbang — QA 21 September 2026 (d).

Laporan pemilik 21:00: truk Catur sudah ditimbang kedua (netto 9.950), tetapi
di Pos Produksi batch-nya tetap "± 10.240 kg" dan gilingnya tetap "belum
final". Sebabnya: Pos Timbang punya DUA tombol timbang kedua untuk barang
masuk. "Simpan sementara" (jumlah karung belum diketahui) menyimpan
`timbang2_kg` tetapi sengaja TIDAK menghitung netto dan tiketnya tetap
TERBUKA — sampai bongkar rampung, berjam-jam. Produksi lalu memegang
perkiraan dari tara LAMA (atau NULL untuk truk baru) padahal berat kosong
truk HARI INI sudah ditimbang.

Yang benar: perkiraan dihitung dari timbang kedua hari itu — bermuatan −
kosong, rumus netto Pos Timbang sendiri (`logic.hitung`: tara karung dan
tara lain masuk ke berat_barang, BUKAN ke netto). Tetap 'perkiraan' dan tetap
belum final: tiketnya memang belum ditutup. `berat_perkiraan_kg` (dari tara)
TIDAK ditimpa — dialah yang menguji anggapan "tara stabil" di butir ⑨.

Dibuktikan GAGAL di 951b566 sebelum diperbaiki.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from tests.pg.test_bobot_belum_final import (  # noqa: F401 — fixture & pembantu
    _baca_batch, _batch_gabah, _ke_silo, _poller, _tiket, _timbang_kedua, pabrik)

pytestmark = pytest.mark.asyncio


async def _simpan_sementara(db, tid, *, timbang2):
    """Persis yang ditulis tombol "Simpan sementara": timbang2 ada, netto
    tidak dihitung, tiket tetap TERBUKA."""
    await db.execute(text("""
        UPDATE timbangan_transaksi
           SET timbang2_kg = :k, timbang2_waktu = now()
         WHERE id = :i"""), {"k": timbang2, "i": tid})


async def _giling(pg, pemakai, silo="B"):
    from app.models import MillingProcess, User
    from app.penggilingan.gudang1.services.milling import start_milling

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kode = (await start_milling(db, user=u, nama_silo=silo)).proc.kode_proses

    async def baca():
        async with pg() as db:
            return (await db.execute(
                select(MillingProcess).where(MillingProcess.kode_proses == kode))).scalars().one()
    return baca


async def test_simpan_sementara_memperbarui_perkiraan_dari_timbang_kedua_hari_ini(
        pg, pemakai, pemasok, pabrik):
    """Skenario (a) persis tangkapan layar: Catur perkiraan 10.240 dari tara
    lama + Widiyanto 10.640 → giling 20.880 belum final."""
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        await _tiket(db, "T-LAMA", nopol="AD 30 CT", t1=17500, netto=10740, kosong=6760,
                     supplier_id=pemasok.id, hari_lalu=5)
        t_catur = await _tiket(db, "T-CATUR", nopol="AD 30 CT", t1=17000, supplier_id=pemasok.id)
        t_widi = await _tiket(db, "T-WIDI", nopol="AD 31 WD", t1=19000, netto=10640, kosong=8360,
                              supplier_id=pemasok.id)
        await db.commit()
    k_catur = await _batch_gabah(pg, pemakai, t_catur)
    k_widi = await _batch_gabah(pg, pemakai, t_widi)
    b = await _baca_batch(pg, k_catur)
    assert (float(b.berat_total_kg), b.sumber_berat) == (17000 - 6760, "perkiraan")
    await _ke_silo(pg, pemakai, k_catur, "B")
    await _ke_silo(pg, pemakai, k_widi, "B")
    baca = await _giling(pg, pemakai, "B")
    p = await baca()
    assert float(p.berat_gabah_masuk_kg) == 10240 + 10640 and p.bobot_masuk_final is False

    # (a) Simpan sementara: timbang2 = 7.050, netto belum dihitung, TERBUKA.
    async with pg() as db:
        await _simpan_sementara(db, t_catur, timbang2=7050)
        await db.commit()
    await _poller(pg)
    b = await _baca_batch(pg, k_catur)
    assert float(b.berat_total_kg) == 17000 - 7050 == 9950
    assert b.sumber_berat == "perkiraan", "tiketnya belum ditutup"
    assert float(b.berat_perkiraan_kg) == 10240, "perkiraan dari tara TIDAK ditimpa"
    p = await baca()
    assert float(p.berat_gabah_masuk_kg) == 9950 + 10640 == 20590
    assert p.bobot_masuk_final is False

    # (b) Selesai: netto dihitung, tiket SELESAI.
    async with pg() as db:
        await _timbang_kedua(db, t_catur, netto=9950, kosong=7050)
        await db.commit()
    await _poller(pg)
    b = await _baca_batch(pg, k_catur)
    assert (float(b.berat_total_kg), b.sumber_berat) == (9950, "timbangan")
    p = await baca()
    assert float(p.berat_gabah_masuk_kg) == 20590 and p.bobot_masuk_final is True
    async with pg() as db:
        d = await rekonsiliasi(db)
    meleset = {x["nomor_polisi"]: float(x["selisih_persen"]) for x in d["perkiraan_meleset"]}
    assert "AD30CT" in meleset and abs(meleset["AD30CT"] - (-2.8)) < 0.1


async def test_truk_baru_tanpa_tara_dapat_angka_dari_timbang_kedua_hari_ini(
        pg, pemakai, pemasok, pabrik):
    """Truk baru: batch NULL 'menunggu'. Sesudah simpan sementara ia punya
    angka — 'perkiraan', berat_perkiraan_kg tetap NULL (tak ada tara lama
    yang diuji), giling ikut naik, tetap belum final."""
    async with pg() as db:
        t_baru = await _tiket(db, "T-BARU", nopol="B 77 ZZ", t1=17000, supplier_id=pemasok.id)
        t_widi = await _tiket(db, "T-WIDI2", nopol="AD 32 WD", t1=19000, netto=10640, kosong=8360,
                              supplier_id=pemasok.id)
        await db.commit()
    k_baru = await _batch_gabah(pg, pemakai, t_baru)
    k_widi = await _batch_gabah(pg, pemakai, t_widi)
    assert (await _baca_batch(pg, k_baru)).berat_total_kg is None
    await _ke_silo(pg, pemakai, k_baru, "A")
    await _ke_silo(pg, pemakai, k_widi, "A")
    baca = await _giling(pg, pemakai, "A")
    assert float((await baca()).berat_gabah_masuk_kg) == 10640

    async with pg() as db:
        await _simpan_sementara(db, t_baru, timbang2=7050)
        await db.commit()
    await _poller(pg)
    b = await _baca_batch(pg, k_baru)
    assert (float(b.berat_total_kg), b.sumber_berat) == (9950, "perkiraan")
    assert b.berat_perkiraan_kg is None
    p = await baca()
    assert float(p.berat_gabah_masuk_kg) == 20590 and p.bobot_masuk_final is False


async def test_tiket_partai_dan_sekali_tidak_terpengaruh(pg, pemakai, pemasok, pabrik):
    """Hanya tiket DUA KALI yang punya arti "timbang kedua = truk kosong".
    Partai menjumlah karung; sekali tak punya timbang kosong sama sekali."""
    async with pg() as db:
        t_partai = await _tiket(db, "T-PARTAI", nopol="AD 33 PP", t1=1200, supplier_id=pemasok.id)
        t_sekali = await _tiket(db, "T-SEKALI", nopol="AD 34 SS", t1=17000, supplier_id=pemasok.id)
        await db.execute(text("UPDATE timbangan_transaksi SET cara_timbang = 'PARTAI', "
                              "timbang2_kg = 70 WHERE id = :i"), {"i": t_partai})
        await db.execute(text("UPDATE timbangan_transaksi SET cara_timbang = 'SEKALI', "
                              "timbang2_kg = 5000 WHERE id = :i"), {"i": t_sekali})
        await db.commit()
    kp = await _batch_gabah(pg, pemakai, t_partai)
    ks = await _batch_gabah(pg, pemakai, t_sekali)
    await _poller(pg)
    for k in (kp, ks):
        b = await _baca_batch(pg, k)
        assert b.berat_total_kg is None and b.sumber_berat == "menunggu", k


async def test_layar_membedakan_dua_jenis_perkiraan(pg, pemakai, pemasok, pabrik):
    from app.penggilingan.gudang1.services.bobot import dari_batch

    async with pg() as db:
        await _tiket(db, "T-L5", nopol="AD 35 QQ", t1=17500, netto=10740, kosong=6760,
                     supplier_id=pemasok.id, hari_lalu=2)
        tid = await _tiket(db, "T-Q5", nopol="AD 35 QQ", t1=17000, supplier_id=pemasok.id)
        await db.commit()
    kode = await _batch_gabah(pg, pemakai, tid)
    assert dari_batch(await _baca_batch(pg, kode)).teks() == "± 10.240 kg (dari tara lama)"
    async with pg() as db:
        await _simpan_sementara(db, tid, timbang2=7050)
        await db.commit()
    await _poller(pg)
    assert dari_batch(await _baca_batch(pg, kode)).teks() == "9.950 kg · tiket belum ditutup"
