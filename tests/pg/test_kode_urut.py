"""Kode harian: tak bertabrakan, dan tanggalnya tanggal Jakarta.

Tiga temuan QA 11 September 2026, semuanya bermuara di `codegen.py`.

**P-K-01 (Kritis).** Kode dibentuk dari `jumlah baris hari ini + 1`, sementara
Undo MENGHAPUS baris. Sesudah Budi membatalkan GB-01, truk berikutnya
menghitung GB-02 — yang sudah ada — lalu jatuh dengan IntegrityError, yang
oleh `purchase.py` dilabeli "Tiket timbang ini sudah ditautkan ke batch lain".
Pesannya menyesatkan dua kali: sebabnya bukan tiket, dan masalahnya tak hilang
sampai besok. Berlaku juga untuk PGR, LOT, TRF, PKB, POL, PTS.

Dua operator yang menyimpan bersamaan memicu hal yang persis sama: keduanya
menghitung angka yang sama sebelum salah satunya sempat menyimpan.

**P-K-03 & X-09.** Tanggal di kode diambil dari `date.today()`, yaitu jam
kontainer — dan kontainer Railway ber-UTC. Antara 00:00 dan 07:00 WIB,
tanggalnya masih tanggal kemarin.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio


async def test_undo_lalu_catat_lagi_tidak_macet(pg, pemakai, pemasok):
    """Skenario r13: batalkan yang pertama, lalu catat truk berikutnya.

    Pada kode lama truk berikutnya DITOLAK, dan tetap ditolak sepanjang hari.
    """
    from app.services.codegen import next_purchase_batch_code
    from app.models import PurchaseBatch

    async with pg() as db:
        kode1 = await next_purchase_batch_code(db)
        db.add(PurchaseBatch(
            kode_batch=kode1, supplier_id=pemasok.id, tanggal_pembelian=_hari_ini(),
            waktu_pembelian=datetime.now(timezone.utc), berat_total_kg=1000,
            kondisi_gabah="basah", input_by=pemakai.id))
        await db.commit()

        # Budi membatalkan — barisnya benar-benar hilang.
        await db.execute(text("DELETE FROM purchase_batches WHERE kode_batch = :k"),
                         {"k": kode1})
        await db.commit()

        kode2 = await next_purchase_batch_code(db)
        assert kode2 != kode1, (
            f"nomor diterbitkan ulang sesudah pembatalan: {kode2}")
        db.add(PurchaseBatch(
            kode_batch=kode2, supplier_id=pemasok.id, tanggal_pembelian=_hari_ini(),
            waktu_pembelian=datetime.now(timezone.utc), berat_total_kg=2000,
            kondisi_gabah="basah", input_by=pemakai.id))
        await db.commit()          # tak boleh IntegrityError


async def test_dua_operator_bersamaan_dapat_kode_berbeda(pg, pemakai):
    """Skenario r06. Keduanya harus sukses — bukan satu sukses satu ditolak."""
    from app.services.codegen import next_purchase_batch_code

    async def ambil():
        async with pg() as db:
            kode = await next_purchase_batch_code(db)
            await db.commit()
            return kode

    hasil = await asyncio.gather(*[ambil() for _ in range(20)])
    assert len(set(hasil)) == 20, f"tabrakan: {len(hasil) - len(set(hasil))} kode kembar"


async def test_tanggal_kode_mengikuti_jakarta_bukan_utc(pg, pemakai, monkeypatch):
    """Skenario r05: pukul 03:00 WIB, kontainer ber-UTC.

    Jam UTC-nya masih 20:00 tanggal KEMARIN, jadi kode lama memakai tanggal
    kemarin sementara seluruh hitungan hari di aplikasi memakai Jakarta.
    """
    import datetime as _dt

    from app.services import codegen

    # 03:00 WIB tanggal 11 = 20:00 UTC tanggal 10.
    wib = timezone(timedelta(hours=7))
    dini_hari = _dt.datetime(2026, 9, 11, 3, 0, tzinfo=wib)

    class _HariUTC(_dt.date):
        """Jam kontainer: UTC, jadi `date.today()` masih tanggal KEMARIN.

        Dipalsukan supaya ujinya tak lulus karena kebetulan tanggal hari ini
        sama dengan yang diharapkan — uji yang lulus karena tanggal berjalan
        akan gagal sendiri besok, atau lebih buruk, lulus terus tanpa menguji.
        """
        @classmethod
        def today(cls):
            return _dt.date(2026, 9, 10)

    monkeypatch.setattr(codegen, "now_local", lambda: dini_hari)
    monkeypatch.setattr(codegen, "date", _HariUTC)

    async with pg() as db:
        kode = await codegen.next_purchase_batch_code(db)
    assert kode.startswith("GB-20260911-"), (
        f"kode memakai tanggal UTC, bukan Jakarta: {kode}")


async def test_tiket_dini_hari_dibukukan_ke_hari_itu(pg, pemakai):
    """X-09: truk yang ditimbang 05:30 WIB 11 Sep dibukukan GB-20260910-01.

    `timbang1_waktu` datang dari asyncpg sebagai UTC; `.date()` langsung
    memberikan tanggal kemarin.
    """
    from app.services.codegen import next_purchase_batch_code
    from app.penggilingan.gudang1.services import purchase

    # 05:30 WIB 11 Sep = 22:30 UTC 10 Sep.
    utc = datetime(2026, 9, 10, 22, 30, tzinfo=timezone.utc)
    assert purchase.tanggal_lokal(utc) == _tanggal(2026, 9, 11), (
        "waktu tiket tak dikonversi ke Asia/Jakarta sebelum diambil tanggalnya")


def _hari_ini():
    from app.database import now_local
    return now_local().date()


def _tanggal(y, m, d):
    from datetime import date
    return date(y, m, d)


async def test_galat_basis_data_tak_lagi_semuanya_soal_tiket(pg, pemakai, pemasok):
    """P-K-07. Tiap IntegrityError dilabeli "Tiket timbang ini sudah ditautkan
    ke batch lain" — apa pun sebabnya.

    Itu menutupi dua hal sekaligus. Tabrakan kode harian muncul sebagai
    kalimat tentang tiket, jadi operator mencari masalah di tempat yang salah
    seharian; dan pelanggaran lain jadi tak terlihat sama sekali.
    """
    from sqlalchemy.exc import IntegrityError

    from app.penggilingan.gudang1.services.purchase import _pesan_integritas

    class _Asli(Exception):
        def __init__(self, teks):
            self.constraint_name = teks

    def _galat(nama):
        return IntegrityError("stmt", {}, _Asli(nama))

    # Tautan tiket — dan HANYA ini yang boleh berbunyi soal tiket.
    pesan = _pesan_integritas(_galat("uq_purchase_batches_timbangan"),
                              "purchase_batches", "GB-20260911-01")
    assert "ditautkan" in pesan

    # Tabrakan nomor — pesannya menyebut nomor, dan menyuruh mencoba lagi.
    pesan = _pesan_integritas(_galat("purchase_batches_kode_batch_key"),
                              "purchase_batches", "GB-20260911-01")
    assert "ditautkan" not in pesan
    assert "GB-20260911-01" in pesan

    # Apa pun yang lain — jujur bahwa ia tak dikenali, bukan menebak.
    pesan = _pesan_integritas(_galat("fk_entah_apa"), "purchase_batches", "")
    assert "ditautkan" not in pesan
    assert "aturan basis data" in pesan


async def test_migrasi_mengisi_penghitung_dari_kode_yang_sudah_ada(pg, pemakai, pemasok):
    """Nilai awal dibaca dari NOMOR TERTINGGI di kode, bukan dari jumlah baris.

    Membaca jumlah baris akan mengulangi kekeliruan yang sama: baris yang
    sudah dibatalkan tak lagi terhitung, dan penghitungnya lahir langsung
    dengan angka yang bentrok.
    """
    import pathlib

    berkas = (pathlib.Path(__file__).resolve().parents[2]
              / "migrations/versions/0038_kode_urut.py").read_text()
    assert "max(CAST(split_part" in berkas
    # `count(*)` memang dipakai — untuk memeriksa TABELNYA ada, bukan untuk
    # menghitung nomor. Yang diperiksa di sini perintah pengisiannya saja;
    # menolak katanya di seluruh berkas akan menghukum pemakaian yang benar.
    pengisi = berkas[berkas.index("INSERT INTO kode_urut"):berkas.index("ON CONFLICT")]
    assert "count(" not in pengisi, "nilai awal dihitung dari jumlah baris"
    # Dan yang menang saat bentrok adalah yang TERBESAR — bukan yang terakhir.
    assert "greatest(" in berkas
