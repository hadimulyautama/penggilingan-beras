"""Kerangka bersama dengan identitas terbaru untuk satu permintaan PDF."""
from contextvars import ContextVar
from hmu_dokumen.document import PenyajiDokumen as PenyajiDasar
from hmu_dokumen.perusahaan import baca
from app.database import SessionLocal

_identitas=ContextVar('identitas_pdf',default=None)
class PenyajiDokumen(PenyajiDasar):
    def __init__(self):
        super().__init__(perusahaan=_identitas.get())

async def buat_pdf_terkini(pembuat, data):
    async with SessionLocal() as db:
        perusahaan=await baca(db)
    token=_identitas.set(perusahaan)
    try:return pembuat(data)
    finally:_identitas.reset(token)
