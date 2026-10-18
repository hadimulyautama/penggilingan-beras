"""Uji yang menyentuh Postgres sungguhan.

Suite ini sampai 11 September 2026 tak punya satu pun uji ber-Postgres, dan
akibatnya satu kelas kesalahan tak pernah terlihat sama sekali: BALAPAN. Dua
operator yang menekan simpan pada detik yang sama, atau satu pembatalan yang
menggeser hitungan — keduanya hanya muncul bila dua transaksi sungguhan
memperebutkan baris yang sama. SQLite tak menirukannya.

Berjalan HANYA bila `UJI_PG_URL` disetel; tanpa itu dilewati, dengan alasan
yang disebutkan di layar. Uji yang dilewati diam-diam adalah uji yang tak
menjaga apa pun.

    createdb uji_produksi
    UJI_PG_URL=postgresql+asyncpg://postgres:pw@127.0.0.1:5432/uji_produksi \\
        .venv/bin/python -m pytest -q tests/pg
"""
from __future__ import annotations

import os
import pathlib

import pytest
import pytest_asyncio


def _url() -> str | None:
    """Alamat Postgres uji — berpagar, bukan sekadar dibaca.

    Dua syarat, dan keduanya perlu. Host wajib loopback: uji ini MEMBANGUN dan
    MENJATUHKAN skema, dan basis data di mesin lain bisa saja basis data yang
    sedang dipakai orang. Namanya wajib berawalan "uji_": satu salah ketik
    pada alamat loopback pun masih bisa mengenai basis data pengembangan yang
    isinya dipakai orang lain di kantor.

    Gagal keras, bukan dilewati: alamat yang salah bentuk adalah kekeliruan
    yang harus diperbaiki, bukan keadaan yang boleh didiamkan.
    """
    url = os.environ.get("UJI_PG_URL", "").strip()
    if not url:
        return None
    if not ("127.0.0.1" in url or "localhost" in url):
        pytest.fail(f"UJI_PG_URL bukan loopback: {url.rsplit('@', 1)[-1]}")
    nama = url.rsplit("/", 1)[-1].split("?")[0]
    if not nama.startswith("uji_"):
        pytest.fail(f"nama basis data uji wajib berawalan 'uji_', bukan '{nama}'")
    return url


#: Mengosongkan SELURUH tabel kecuali tabel versi migrasi. Di tingkat modul
#: supaya pola nama `alembic_version%` hanya tertulis SEKALI — pola yang disalin
#: adalah pola yang cepat atau lambat kehilangan salah satu dari empat rantai
#: migrasi yang hidup di basis data ini.
#: Seluruh tabel dikosongkan dalam SATU perintah: CASCADE per tabel akan
#: mengosongkan tabel anak berulang kali dan mendominasi waktu 800+ uji.
_KOSONGKAN = """
    DO $$
    DECLARE tabel text;
    BEGIN
      SELECT string_agg(format('%I.%I', schemaname, tablename), ', ')
        INTO tabel FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename NOT LIKE 'alembic\\_version%' ESCAPE '\\';
      IF tabel IS NOT NULL THEN
        EXECUTE 'TRUNCATE TABLE ' || tabel || ' RESTART IDENTITY CASCADE';
      END IF;
    END $$;
"""


@pytest.fixture(scope="session")
def _skema_head():
    """Menjalankan `alembic upgrade head` SEKALI untuk seluruh sesi pytest.

    Dulu ini di dalam `pg()`, jadi tiap satu dari 150+ uji menjalankan
    `alembic upgrade head` sebagai SUBPROCESS baru — proses Python baru,
    mengimpor ulang seluruh `app` (lewat `migrations/env.py`), lalu membuka
    koneksi asyncpg sendiri hanya untuk membaca `alembic_version` dan
    mendapati skemanya SUDAH di head. Itulah yang membuat suite ini puluhan
    menit: bukan migrasinya yang lambat, melainkan menyalakan satu proses
    Python penuh 150+ kali untuk sesuatu yang, sesudah uji PERTAMA, selalu
    berakhir sebagai no-op.

    Yang dijaga tetap sama: skema tiap sesi uji tetap dibangun dari MIGRASI
    sungguhan (bukan `Base.metadata.create_all`), jadi migrasi penghitung
    kode dkk. tetap benar-benar berjalan — sekali, bukan nol kali. Kalau
    repo ini mendapat migrasi baru sejak basis data `uji_*` terakhir
    disentuh, panggilan SEKALI ini di awal sesi tetap akan menerapkannya
    (atau gagal keras kalau migrasinya rusak) — persis seperti sebelumnya.

    Yang TIDAK lagi dijaga ulang tiap uji: kalau sebuah uji mengubah baris
    `alembic_version` lalu TAK mengembalikannya (`test_versi_pg.py` sengaja
    melakukan ini sebentar, dan mengembalikannya di `finally`), `pg()` yang
    lama akan mencoba menjalankan ulang migrasi terakhir di tengah sesi dan
    gagal keras — sinyal cepat kalau ujinya lupa mengembalikan. Sesi ini
    tak lagi memberi sinyal itu di tengah jalan; `test_versi_pg.py` sendiri
    sudah menjaga baris itu lewat `finally` sebagai gantinya.
    """
    url = _url()
    if url is None:
        pytest.skip("UJI_PG_URL kosong — uji Postgres dilewati")

    import subprocess

    akar = pathlib.Path(__file__).resolve().parents[2]
    lingk = {**os.environ, "DATABASE_URL": url}
    hasil = subprocess.run(
        [str(akar / ".venv/bin/python"), "-m", "alembic", "upgrade", "head"],
        cwd=akar, env=lingk, capture_output=True, text=True, timeout=300,
    )
    if hasil.returncode != 0:
        pytest.fail(f"alembic upgrade head gagal:\n{hasil.stderr[-2000:]}")
    return url


@pytest_asyncio.fixture
async def pg(_skema_head):
    """Basis data kosong dengan skema dari MIGRASI, bukan dari metadata.

    Fixture gudang harus mengisi `kode_fungsi="g1"/"g2"` secara eksplisit.
    Nama gudang boleh diubah operator; layanan mengenalinya lewat kode stabil.
    TRUNCATE menghapus master hasil migrasi juga, sehingga membuat nama saja
    di fixture tidak lagi mewakili gudang operasional yang sah.

    Skemanya sendiri (lewat `alembic upgrade head`) dibangun SEKALI per sesi
    di `_skema_head` di atas — lihat docstring-nya untuk kenapa. Yang masih
    terjadi di SETIAP uji, persis seperti sebelumnya, cuma mengosongkan
    (TRUNCATE) tabelnya.
    """
    url = _skema_head

    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    mesin = create_async_engine(url)
    Sesi = async_sessionmaker(mesin, expire_on_commit=False)

    # Layanannya memakai `SessionLocal` modulnya sendiri; diarahkan ke mesin
    # uji supaya yang diuji benar-benar kode yang dipakai, bukan salinannya.
    #
    # Modul yang menulis `from app.database import SessionLocal` memegang
    # SALINAN referensinya sejak diimpor, jadi mengganti yang di `app.database`
    # saja tak menyentuh mereka: mereka tetap memakai mesin aplikasi yang
    # terikat event loop lain, dan galatnya berbunyi "another operation is in
    # progress" — kalimat yang terbacanya seperti kerusakan asyncpg, bukan
    # seperti uji yang salah pasang.
    import sys

    from app import database

    asli = database.SessionLocal
    database.SessionLocal = Sesi
    #
    # Dipindai TIAP uji, dan yang lama disimpan apa adanya — bukan dianggap
    # selalu sama dengan referensi aslinya. Modul yang baru diimpor DI TENGAH
    # uji sebelumnya (impor malas di dalam fungsi) menangkap sessionmaker
    # milik uji itu, dan mesinnya sudah dibuang saat uji berikutnya berjalan.
    disalin = [
        (m, m.SessionLocal) for m in list(sys.modules.values())
        if getattr(m, "__name__", "").startswith("app.")
        and hasattr(m, "SessionLocal")
    ]
    for m, _ in disalin:
        m.SessionLocal = Sesi

    # ── Dikosongkan SEBELUM tiap uji, bukan sesudah ──
    #
    # Dulu sesudah, dan itu meninggalkan satu lubang yang justru paling sulit
    # dibaca: uji PERTAMA sebuah lintasan mewarisi isi basis data dari lintasan
    # SEBELUMNYA — lintasan yang dihentikan di tengah, yang gagal, atau yang
    # dijalankan dengan env berbeda. Ia menjatuhkan uji yang tak bersalah
    # (`test_acuan_hanya_nama_daftar_mingguan`, 23 September 2026: satu pemasok
    # sisa membuat `daftar["Pemasok"] == ["Pak Tani"]` gagal), lalu HILANG di
    # lintasan berikutnya — kegagalan yang datang dan pergi menuntun orang
    # menyalahkan ujinya, bukan harness-nya. Temuan QA 24 September 2026.
    #
    # Mengosongkan di muka menjadikannya sifat yang tak bergantung apa pun:
    # tiap uji dimulai dari basis data kosong, apa pun yang terjadi sebelumnya.
    #
    # SELURUH tabel versi migrasi dipertahankan: mengosongkannya membuat
    # `alembic upgrade head` berikutnya mencoba membangun dari awal di atas
    # skema yang sudah ada.
    async with mesin.begin() as conn:
        await conn.execute(sa_text(_KOSONGKAN))

    try:
        yield Sesi
    finally:
        database.SessionLocal = asli
        for m, _lama in disalin:
            m.SessionLocal = asli
        # Tidak dikosongkan lagi di sini: sekali per uji cukup, dan basis data
        # yang tertinggal berisi justru berguna — ia bisa dibuka orang untuk
        # melihat keadaan saat uji terakhir gagal.
        await mesin.dispose()


@pytest_asyncio.fixture
async def pemakai(pg):
    """Satu orang yang mencatat — operator Gudang 1."""
    from sqlalchemy import select

    from app.models import User

    async with pg() as db:
        u = (await db.execute(select(User).limit(1))).scalars().first()
        if u is None:
            u = User(nama="Uji", role="operator", status="aktif")
            db.add(u)
            await db.commit()
            await db.refresh(u)
        return u


@pytest_asyncio.fixture
async def pemasok(pg):
    """Satu pemasok — `purchase_batches.supplier_id` wajib isi."""
    from sqlalchemy import select

    from app.models import Supplier

    async with pg() as db:
        s = (await db.execute(select(Supplier).limit(1))).scalars().first()
        if s is None:
            s = Supplier(nama_supplier="Pemasok Uji")
            db.add(s)
            await db.commit()
            await db.refresh(s)
        return s


@pytest.fixture
def hitung_kueri():
    """Hitung berapa KUERI yang dikeluarkan sepotong kode.

    Bukan berapa lama ia berjalan: waktu berubah-ubah menurut mesin dan
    beban, sedangkan jumlah kueri adalah sifat kodenya sendiri. N+1 tak
    pernah terlihat sebagai "lambat" di laptop dengan tiga baris data — ia
    baru muncul setelah setahun data menumpuk, di tempat yang tak bisa
    dicoba ulang. Angka inilah yang bisa dijaga sejak sekarang.

        async with hitung_kueri() as n:
            await sesuatu()
        assert n.jumlah < 50
    """
    from contextlib import asynccontextmanager

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    class _Hitung:
        def __init__(self):
            self.jumlah = 0
            self.perintah: list[str] = []

    @asynccontextmanager
    async def _pakai():
        h = _Hitung()

        def _catat(conn, cursor, statement, parameters, context, executemany):
            h.jumlah += 1
            h.perintah.append(statement.split("\n")[0][:120])

        event.listen(Engine, "before_cursor_execute", _catat)
        try:
            yield h
        finally:
            event.remove(Engine, "before_cursor_execute", _catat)

    return _pakai
