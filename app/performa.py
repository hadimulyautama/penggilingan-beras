"""Penghematan pembacaan, terbatas permintaan GET dan penanda tanpa data bisnis.

Saldo untuk transaksi selalu dihitung ulang. Memo hanya hidup selama satu
halaman dirender; POST dan pekerja latar tidak memakainya. Cache lintas
permintaan hanya untuk snapshot tampilan singkat; transaksi dan pemeriksaan
identitas tetap membaca keadaan baru.
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import time
from dataclasses import fields, is_dataclass
from contextvars import ContextVar
from functools import wraps

_konteks: ContextVar[dict | None] = ContextVar("pembacaan_halaman", default=None)
log = logging.getLogger("performa")
_pembersih = []


def _kunci_nilai(nilai):
    if nilai is None or isinstance(nilai,(str,int,float,bool,bytes)):
        return nilai
    if is_dataclass(nilai) and not isinstance(nilai, type):
        if hasattr(type(nilai),'kunci_performa'):
            return nilai.kunci_performa
        return (type(nilai), tuple((f.name, _kunci_nilai(getattr(nilai, f.name))) for f in fields(nilai)))
    if isinstance(nilai, dict):
        return frozenset((_kunci_nilai(k), _kunci_nilai(v)) for k, v in nilai.items())
    if isinstance(nilai, (tuple, list)):
        return tuple(_kunci_nilai(v) for v in nilai)
    if isinstance(nilai, (set, frozenset)):
        return frozenset(_kunci_nilai(v) for v in nilai)
    return nilai


def baca_sekali(fungsi):
    """Memo hasil nilai murni, bukan objek ORM, hanya dalam GET yang sama."""
    tanda = inspect.signature(fungsi)

    @wraps(fungsi)
    async def baca(*args, **kwargs):
        konteks = _konteks.get()
        db = args[0] if args else kwargs.get("db")
        if (konteks is None or not konteks["boleh_memo"]
                or any(getattr(db, n, ()) for n in ("new", "dirty", "deleted"))):
            return await fungsi(*args, **kwargs)
        nilai = tanda.bind(*args, **kwargs)
        nilai.apply_defaults()
        # Semua pembeda (pemilik, silo, gudang, dsb.) ikut kunci. Hanya sesi
        # DB yang dilewati; hasil yang diizinkan di sini tidak membawa ORM.
        kunci = (fungsi, tuple((k, _kunci_nilai(v)) for k, v in nilai.arguments.items() if k != "db"))
        try:
            hash(kunci)
        except TypeError:
            return await fungsi(*args, **kwargs)
        memo = konteks["memo"]
        if kunci not in memo:
            memo[kunci] = await fungsi(*args, **kwargs)
        return copy.deepcopy(memo[kunci])

    return baca


def baca_sesi(fungsi):
    """Daftar ORM hanya dibagi dalam sesi yang sama, bukan lintas sesi."""
    tanda = inspect.signature(fungsi)

    @wraps(fungsi)
    async def baca(db, *args, **kwargs):
        aktif = _konteks.get()
        if (aktif is None or not aktif["boleh_memo"]
                or db.new or db.dirty or db.deleted):
            return await fungsi(db, *args, **kwargs)
        nilai = tanda.bind(db, *args, **kwargs)
        nilai.apply_defaults()
        kunci = (fungsi, db, tuple((k, v) for k, v in nilai.arguments.items() if k != "db"))
        memo = aktif["memo"]
        if kunci not in memo:
            memo[kunci] = await fungsi(db, *args, **kwargs)
        hasil = memo[kunci]
        return list(hasil) if isinstance(hasil, list) else hasil

    return baca


def tampilan_singkat(fungsi):
    """Snapshot tampilan 2 detik; transaksi/pekerja selalu membaca langsung.

    Pembaca memakai sesi pemanggil. Tidak membuka koneksi kedua atau
    meninggalkan tugas pembaca setelah permintaan putus.
    """
    tanda = inspect.signature(fungsi)
    nilai = {}
    keadaan = dict(loop=None, locks={}, generasi=0)

    def hapus():
        nilai.clear()
        keadaan['generasi'] += 1

    _pembersih.append(hapus)

    @wraps(fungsi)
    async def baca(db, *args, **kwargs):
        def langsung():
            return not boleh_memo() or any(
                getattr(db, n, ()) for n in ('new', 'dirty', 'deleted'))

        _segarkan_lintas_proses()
        if langsung():
            return await fungsi(db, *args, **kwargs)
        loop = asyncio.get_running_loop()
        if keadaan['loop'] is not loop:
            hapus()
            keadaan.update(loop=loop, locks={})
        bound = tanda.bind(db, *args, **kwargs)
        bound.apply_defaults()
        kunci = (db.get_bind(), tuple((k, _kunci_nilai(v))
            for k, v in bound.arguments.items() if k != 'db'))
        lama = nilai.get(kunci)
        if lama is not None and time.monotonic() - lama[0] < 2:
            return copy.deepcopy(lama[1])
        # Miliki koneksi sebelum memegang lock. Jika waiter memenuhi pool
        # sementara pembaca belum punya koneksi, keduanya akan saling tunggu.
        await db.connection()
        entry = keadaan['locks'].setdefault(kunci, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                if langsung():
                    return await fungsi(db, *args, **kwargs)
                lama = nilai.get(kunci)
                if lama is not None and time.monotonic() - lama[0] < 2:
                    return copy.deepcopy(lama[1])
                generasi = keadaan['generasi']
                hasil = await fungsi(db, *args, **kwargs)
                if generasi == keadaan['generasi']:
                    if len(nilai) >= 8:
                        nilai.pop(next(iter(nilai)))
                    nilai[kunci] = (time.monotonic(), copy.deepcopy(hasil))
                return hasil
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                keadaan['locks'].pop(kunci, None)

    return baca


class NilaiSingkat:
    """Gabungkan pembacaan bersamaan; kegagalan dan pembatalan tidak disimpan."""

    def __init__(self, detik=1.0, batas=256):
        self.detik, self.batas = detik, batas
        self._nilai, self._tugas = {}, {}
        self._loop = None
        self._generasi = 0
        _pembersih.append(self.hapus)

    def hapus(self):
        self._generasi += 1
        self._nilai.clear()
        self._tugas.clear()

    def simpan(self, kunci, nilai):
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self.hapus()
            self._loop = loop
        if len(self._nilai) >= self.batas:
            self._nilai.clear()
        self._nilai[kunci] = (time.monotonic(), copy.deepcopy(nilai))

    async def ambil(self, kunci, baca):
        _segarkan_lintas_proses()
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self.hapus()
            self._loop = loop
        kini = time.monotonic()
        lama = self._nilai.get(kunci)
        if lama is not None and kini - lama[0] < self.detik:
            return copy.deepcopy(lama[1])
        if kunci not in self._tugas:
            generasi = self._generasi

            async def muat():
                try:
                    hasil = await baca()
                    if generasi == self._generasi:
                        if len(self._nilai) >= self.batas:
                            self._nilai.clear()
                        self._nilai[kunci] = (time.monotonic(), hasil)
                    return hasil
                finally:
                    if generasi == self._generasi:
                        self._tugas.pop(kunci, None)

            tugas = asyncio.create_task(muat())
            # Klien putus tidak membatalkan pembacaan yang dipakai klien lain.
            # Ambil exception juga bila semua klien sudah pergi.
            tugas.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            self._tugas[kunci] = tugas
        return copy.deepcopy(await asyncio.shield(self._tugas[kunci]))


def _segarkan_lintas_proses():
    from app.cache_epoch import berubah
    if berubah():lupakan_cache()


def lupakan_cache():
    for bersihkan in _pembersih:
        bersihkan()


# Pekerja latar juga menulis melalui Session. Invalidasi sesudah COMMIT,
# bukan sesudah SELECT/rollback pembacaan, agar cache tidak dibuang terus.
from sqlalchemy import event as _event
from sqlalchemy.orm import Session as _Session


@_event.listens_for(_Session, "after_commit")
def _sesudah_commit(session):
    aktif = _konteks.get()
    if aktif is not None:
        aktif["memo"].clear()
    lupakan_cache()
    from app.cache_epoch import catat
    catat()


def pasang_penghitung(engine):
    """Hitung SQL tanpa mencatat isi kueri, parameter, token, atau data orang."""
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def hitung(conn, cursor, statement, parameters, context, executemany):
        aktif = _konteks.get()
        if aktif is not None:
            aktif["sql"] += 1
            if context.isinsert or context.isupdate or context.isdelete:
                aktif["memo"].clear()


def boleh_memo():
    aktif = _konteks.get()
    return aktif is not None and aktif["boleh_memo"]


def dalam(db, kolom, nilai):
    """Keanggotaan ID yang sama, satu parameter array pada PostgreSQL.

    IN dengan ribuan ID membuat SQLAlchemy membangun ribuan placeholder
    pada setiap pembacaan. ARRAY/ANY menjaga nilai tetap terikat parameter;
    SQLite untuk uji memakai IN biasa dengan semantik yang sama.
    """
    if db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy import any_, bindparam
        from sqlalchemy.dialects.postgresql import ARRAY
        return kolom == any_(bindparam(None, list(nilai), type_=ARRAY(kolom.type)))
    return kolom.in_(nilai)


class PerformaMiddleware:
    """ASGI langsung: tidak menahan body/aliran dan tidak menambah sesi DB."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path, metode = scope["path"], scope["method"]
        ringan = path.startswith(("/static/", "/timbangan/static/", "/health")) or path.endswith("/aliran")
        konteks = {"memo": {}, "sql": 0, "boleh_memo": metode in ("GET", "HEAD")} if not ringan else None
        token = _konteks.set(konteks)
        mulai = time.perf_counter()

        async def kirim(message):
            if message["type"] == "http.response.start" and konteks is not None:
                message = {**message, "headers": list(message.get("headers", []))}
                ms = (time.perf_counter() - mulai) * 1000
                message["headers"].extend([
                    (b"server-timing", f"app;dur={ms:.1f}".encode()),
                    (b"x-sql-count", str(konteks["sql"]).encode()),
                ])
                if ms > 1000 or konteks["sql"] > 100:
                    route = scope.get("route")
                    log.info("Halaman %s: %.0f ms, %s SQL", getattr(route, "path", "?"), ms, konteks["sql"])
            await send(message)

        try:
            await self.app(scope, receive, kirim)
        finally:
            _konteks.reset(token)
            if metode not in ("GET", "HEAD", "OPTIONS"):
                lupakan_cache()
