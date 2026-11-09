"""Explicit catalogue fixture for unit tests without a database.
Real master reads and custom types are covered by the PostgreSQL suite.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

def catalog(monkeypatch):
    from app.services import spesifikasi_beras as rice, jenis_hasil_samping as side
    grades = [dict(id=i,kode=code,nama=name,aktif=True) for i,(code,name) in enumerate(
        [('premium','Premium'),('medsuper','MedSuper'),('medium','Medium'),('sayur','Ekonomis')],1)]
    rows = [dict(kode=k,nama=k.title(),aktif=True,bentuk='karung',kg_karung=n) for k,n in
            [('broken',50),('menir',50),('reject',50),('bekatul',40)]]
    monkeypatch.setattr(rice,'daftar',AsyncMock(return_value=grades))
    monkeypatch.setattr(rice,'bawaan_penerimaan',AsyncMock(return_value=SimpleNamespace(**grades[2])))
    monkeypatch.setattr(rice,'jenis_untuk_proses',AsyncMock(return_value=[r['kode'] for r in grades]+[r['kode'] for r in rows]))
    async def hasil(db,**kwargs):return [r['kode'] for r in grades]+[r['kode'] for r in rows]
    monkeypatch.setattr(rice,'jenis_hasil',hasil)
    monkeypatch.setattr(side,'daftar',AsyncMock(return_value=rows))
