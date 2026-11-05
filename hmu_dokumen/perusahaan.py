"""Satu identitas tersimpan; pembacaan bersama tidak mengubah data apa pun."""
from dataclasses import dataclass, asdict
import json
from .identitas import NAMA_PERUSAHAAN, ALAMAT, KONTAK, LOGO

KUNCI = 'identitas_perusahaan'
@dataclass(frozen=True)
class Perusahaan:
    nama: str = NAMA_PERUSAHAAN
    alamat: str = '\n'.join(ALAMAT)
    telepon: str = '+62 851-7416-7950'
    email: str = 'sales@hadimulya.com'
    website: str = 'https://hadimulya.com'
    logo: str = ''
    @property
    def kontak(self):
        return '  |  '.join(v for v in [('Tel. '+self.telepon) if self.telepon else '', self.email] if v)
    def data(self):return asdict(self)

def dari_json(nilai):
    if not nilai:return Perusahaan()
    data=json.loads(nilai) if isinstance(nilai,str) else nilai
    return Perusahaan(**{k:v for k,v in data.items() if k in Perusahaan.__dataclass_fields__})

async def baca(db):
    from sqlalchemy import text
    # Pemilik dan satu-satunya penulis kunci ini adalah Pengaturan PadiFlow.
    nilai=await db.scalar(text('SELECT nilai FROM setelan_pabrik WHERE kunci = :k'), {'k':KUNCI})
    return dari_json(nilai)
