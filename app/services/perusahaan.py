"""Pengaturan identitas penerbit dokumen; transaksi historis tidak ditulis ulang."""
import base64, hashlib, json, re
from io import BytesIO
from urllib.parse import urlsplit
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from app.models import SetelanPabrik
from app.services.activity_log import log_activity
from hmu_dokumen.perusahaan import Perusahaan, KUNCI, baca

BATAS_LOGO=2*1024*1024

def validasi(data):
    hasil={}
    for k,batas in [('nama',120),('alamat',500),('telepon',80),('email',150),('website',200)]:
        v=str(data.get(k,'')).strip()
        if len(v)>batas:raise ValueError(f'{k.capitalize()} maksimal {batas} karakter.')
        if any(ord(c)<32 and c not in ('\n','\r','\t') for c in v):raise ValueError('Teks mengandung karakter yang tidak sah.')
        hasil[k]=v
    if not hasil['nama'] or not hasil['alamat']:raise ValueError('Nama dan alamat perusahaan wajib diisi.')
    if hasil['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',hasil['email']):raise ValueError('Alamat email belum valid.')
    if hasil['website']:
        u=urlsplit(hasil['website'])
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:
            raise ValueError('Website harus berupa alamat http:// atau https:// yang valid.')
    return hasil

def logo_png(raw):
    if len(raw)>BATAS_LOGO:raise ValueError('Logo maksimal 2 MB.')
    try:
        with Image.open(BytesIO(raw)) as im:
            if im.format not in ('PNG','JPEG') or im.width>2048 or im.height>2048:
                raise ValueError('Gunakan logo PNG/JPEG maksimal 2048 × 2048 piksel.')
            im.load()
            buf=BytesIO();im.convert('RGBA').save(buf,format='PNG')
            if len(buf.getvalue())>BATAS_LOGO:raise ValueError('Logo hasil konversi maksimal 2 MB.')
            return base64.b64encode(buf.getvalue()).decode('ascii')
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as e:
        raise ValueError('Berkas logo bukan gambar PNG/JPEG yang dapat dibaca.') from e

def ringkas(data):
    d=dict(data)
    if d.get('logo'):d['logo']='sha256:'+hashlib.sha256(d['logo'].encode()).hexdigest()
    return json.dumps(d,ensure_ascii=False)

async def simpan(db, data, *, logo=None, logo_bawaan=False, user):
    fields=validasi(data)
    row=await db.scalar(select(SetelanPabrik).where(SetelanPabrik.kunci==KUNCI).with_for_update())
    lama=await baca(db)
    gambar='' if logo_bawaan else lama.logo
    if logo is not None:gambar=logo_png(logo)
    baru=Perusahaan(**fields,logo=gambar)
    nilai=json.dumps(baru.data(),ensure_ascii=False)
    if row:row.nilai=nilai;row.diubah_oleh=user.id
    else:db.add(SetelanPabrik(kunci=KUNCI,nilai=nilai,diubah_oleh=user.id))
    await log_activity(db,table_name='setelan_pabrik',record_id=0,action='UPDATE',
        changed_by=user.id,field_name=KUNCI,old_value=ringkas(lama.data()),new_value=ringkas(baru.data()))
    await db.commit()
    return baru
