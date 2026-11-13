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
    from hmu_identitas.ruang_data import RuangData
    ruang=RuangData.lingkungan()
    if ruang:
        lama=await db.scalar(text("SELECT nilai FROM setelan_pabrik WHERE kunci='organisasi_perusahaan_lama'"))
        warisan=bool(lama and json.loads(lama).get('company_id')==ruang.company_id)
        if not warisan:
            data=json.loads(nilai) if nilai else {}
            if not isinstance(data.get('nama'),str) or not data['nama'].strip():
                raise ValueError('Identitas dokumen perusahaan ini belum diatur.')
            # Nilai kosong memang kosong; kontak/logo HMU tidak diwariskan.
            return Perusahaan(**{k:data.get(k,'') for k in Perusahaan.__dataclass_fields__})
    return dari_json(nilai)
