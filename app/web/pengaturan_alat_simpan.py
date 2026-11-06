"""Tanda terima simpan alat, atomik bersama writer lama. Tanpa tabel baru."""
import hashlib
import inspect
import json
import logging
from functools import wraps
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.models import AuditFasilitas
from app.web.security import butuh_super

router = APIRouter()
log = logging.getLogger(__name__)
OBJEK = 'operasi_alat'
FIELD = '_operasi_alat'


def token_baru():
    return str(uuid4())


def json_diminta(request):
    return request.headers.get('X-Pengaturan-Alat') == '1'


class KonflikOperasi(ValueError):
    pass


def token_valid(nilai):
    try:
        return str(UUID(nilai))
    except (ValueError, TypeError, AttributeError):
        raise KonflikOperasi('Identitas penyimpanan tidak valid. Muat ulang formulir.')


def kunci(user_id, token):
    return int.from_bytes(hashlib.sha256(f'alat:{user_id}:{token}'.encode()).digest()[:8], 'big', signed=True)


async def _lock(db, nilai, *, coba=False):
    if db.bind.dialect.name != 'postgresql':
        return True  # Kompatibilitas uji SQLite; konkurensi diuji pada PostgreSQL.
    fungsi = 'pg_try_advisory_xact_lock' if coba else 'pg_advisory_xact_lock'
    return await db.scalar(text(f'SELECT {fungsi}(:k)'), {'k': nilai})


async def _receipt(db, user_id, token):
    return await db.scalar(select(AuditFasilitas).where(
        AuditFasilitas.objek == OBJEK, AuditFasilitas.user_id == user_id,
        AuditFasilitas.sesudah['operasi_id'].as_string() == token))


async def _identitas(request, akun):
    form = await request.form()
    raw = form.get(FIELD)
    if not raw:
        if json_diminta(request):
            raise KonflikOperasi('Identitas penyimpanan belum tersedia. Muat ulang formulir.')
        return None, None  # URL/formulir lama tetap kompatibel.
    token = token_valid(raw)
    isi = {k: form.getlist(k) for k in sorted(form) if k not in ('_csrf', FIELD)}
    cap = hashlib.sha256(json.dumps([request.url.path, isi], sort_keys=True).encode()).hexdigest()
    return token, cap


async def mulai(db, request, akun):
    """Kunci operasi lebih dahulu; hasil replay dikembalikan tanpa menulis ulang."""
    token, cap = await _identitas(request, akun)
    if token:
        await _lock(db, kunci(akun.user.id, token))
        ada = await _receipt(db, akun.user.id, token)
        if ada:
            if ada.sesudah['payload_sha256'] != cap:
                raise KonflikOperasi('Operasi ini sudah disimpan dengan isian berbeda. Periksa hasilnya dahulu.')
            return ada.sesudah['hasil_url']
    # Keempat writer berbagi kunci, termasuk form lama tanpa token. Pemeriksaan
    # nama dan penulisan tidak dapat dilampaui dua tab pada saat yang sama.
    await _lock(db, kunci(0, 'writer-dryer-silo'))
    return None


async def catat_sukses(db, request, akun, objek_id, hasil_url):
    token, cap = await _identitas(request, akun)
    if token:
        from app.web.fasilitas import tujuan
        from urllib.parse import parse_qs, urlsplit, quote
        pesan = parse_qs(urlsplit(hasil_url).query)['pesan'][0]
        hasil_url = await tujuan(await request.form()) + '?pesan=' + quote(pesan)
        db.add(AuditFasilitas(user_id=akun.user.id, objek=OBJEK, objek_id=objek_id,
            sebelum=None, sesudah=dict(operasi_id=token, payload_sha256=cap,
                aksi=request.url.path, hasil_url=hasil_url)))
        await db.flush()


def aman_simpan(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        request = kwargs.get('request') or args[0]
        try:
            return await fn(*args, **kwargs)
        except KonflikOperasi as exc:
            if json_diminta(request):
                return JSONResponse({'status': 'konflik', 'pesan': str(exc)}, status_code=409)
            from app.web.pengaturan import _balik_alat
            from urllib.parse import quote
            return await _balik_alat(request, kwargs['akun'], '/pengaturan/alat?err_teks=' + quote(str(exc)))
        except SQLAlchemyError:
            # Konteks SessionLocal writer telah keluar/rollback sebelum sampai
            # sini. Jangan menyatakan gagal pasti: COMMIT bisa kehilangan balasan.
            log.exception('Penyimpanan alat belum dapat dikonfirmasi: %s', request.url.path)
            if json_diminta(request):
                return JSONResponse({'status': 'belum_pasti', 'pesan':
                    'Hasil penyimpanan belum dapat dipastikan. Periksa status sebelum mencoba lagi.'}, status_code=503)
            raise
    # FastAPI harus membaca anotasi dari modul fungsi asal, bukan modul decorator.
    wrapped.__signature__ = inspect.signature(fn, eval_str=True)
    return wrapped


@router.get('/pengaturan/alat/status-simpan/{operasi_id}')
async def status_simpan(operasi_id: str, request: Request, akun=Depends(butuh_super)):
    try:
        token = token_valid(operasi_id)
    except KonflikOperasi as exc:
        raise HTTPException(422, str(exc))
    try:
        async with SessionLocal() as db:
            if not await _lock(db, kunci(akun.user.id, token), coba=True):
                data = {'status': 'diproses', 'pesan': 'Penyimpanan masih diproses. Periksa status lagi.'}
            else:
                ada = await _receipt(db, akun.user.id, token)
                data = ({'status': 'tersimpan', 'url': ada.sesudah['hasil_url'],
                         'pesan': 'Penyimpanan sudah berhasil. Buka hasil; jangan kirim ulang.'}
                        if ada else {'status': 'belum_tersimpan', 'pesan':
                            'Belum ada penyimpanan untuk operasi ini. Isian tetap terjaga; Anda dapat mencoba lagi.'})
    except SQLAlchemyError:
        data = {'status': 'belum_pasti', 'pesan': 'Status belum dapat dibaca. Jangan kirim ulang; periksa status lagi.'}
    return JSONResponse(data, headers={'Cache-Control': 'no-store'})
