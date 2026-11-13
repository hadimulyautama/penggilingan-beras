"""Administrasi master organisasi; tidak menulis penempatan atau transaksi."""
import hashlib
import json
import re
from datetime import timezone
from sqlalchemy import select
from hmu_core import Perusahaan, LokasiPabrik, KeanggotaanPerusahaan, PenempatanGudang, User
from hmu_identitas import peran as P
from app.services.activity_log import log_activity


class OrganisasiError(ValueError):
    pass


def potret(row):
    fields=('id','kode','nama','aktif') + (('company_id','alamat') if isinstance(row,LokasiPabrik) else ())
    data={k:getattr(row,k) for k in fields}
    t=row.updated_at
    data['diubah']=t.astimezone(timezone.utc).isoformat() if t and t.tzinfo else str(t)
    return data


def sidik(row):
    return hashlib.sha256(json.dumps(potret(row),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


async def pengelola(db,user_id):
    u=await db.get(User,user_id)
    if not u or not P.super_saja(u.role) or (u.status or '').lower()!='aktif':
        raise PermissionError('Master perusahaan dan lokasi hanya dapat dikelola Super Admin.')


def teks(nilai,nama,batas,minimum=0,multibaris=False):
    v=str(nilai or '').strip()
    if not minimum<=len(v)<=batas or any(ord(c)<32 and not (multibaris and c in '\r\n\t') for c in v):
        raise OrganisasiError(f'{nama} harus {minimum}–{batas} karakter yang valid.')
    return v


async def simpan(db,*,user_id,objek,nama,kode,aktif,alasan,identitas=None,bukti='',company_id=None,alamat=''):
    await pengelola(db,user_id)
    if identitas is not None and (type(identitas) is not int or identitas<=0):
        raise OrganisasiError('Identitas master tidak valid.')
    if type(aktif) is not bool:raise OrganisasiError('Status master tidak valid.')
    model={'perusahaan':Perusahaan,'lokasi':LokasiPabrik}.get(objek)
    if model is None:raise OrganisasiError('Master tidak dikenal.')
    nama=teks(nama,'Nama',200,2)
    alasan=teks(alasan,'Alasan perubahan',500,5)
    alamat=teks(alamat,'Alamat',1000,multibaris=True) if model is LokasiPabrik else None
    # Satu urutan kunci untuk Console, Pengaturan perusahaan, dan penetapan:
    # perusahaan -> lokasi -> gudang. Pembacaan awal hanya menentukan induk.
    if model is LokasiPabrik:
        awal=await db.get(LokasiPabrik,identitas) if identitas else None
        if awal:company_id=awal.company_id
        await db.scalar(select(Perusahaan).where(Perusahaan.id==company_id).with_for_update(key_share=True).execution_options(populate_existing=True))
    row=await db.scalar(select(model).where(model.id==identitas).with_for_update(key_share=True).execution_options(populate_existing=True)) if identitas else None
    if identitas and (row is None or sidik(row)!=bukti):
        raise OrganisasiError('Data sudah berubah. Buka kembali rincian sebelum menyimpan.')
    if row:
        if str(kode).strip()!=row.kode:raise OrganisasiError('Kode tetap untuk menjaga identitas. Nama dapat diperbarui.')
        if model is LokasiPabrik and company_id is not None and company_id!=row.company_id:
            raise OrganisasiError('Perusahaan pada lokasi yang sudah tercatat tidak dapat dipindahkan.')
        company_id=row.company_id if model is LokasiPabrik else None
        kode=row.kode
    else:
        kode=str(kode or '').strip().lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,49}',kode):
            raise OrganisasiError('Kode harus 2–50 huruf kecil, angka, tanda - atau _.')
    # Perubahan lokasi dan penonaktifan induk memakai kunci perusahaan yang sama.
    induk=None
    if model is LokasiPabrik:
        induk=await db.scalar(select(Perusahaan).where(Perusahaan.id==company_id).with_for_update(key_share=True).execution_options(populate_existing=True))
        if not induk:raise OrganisasiError('Pilih perusahaan yang tersedia.')
        if aktif and not induk.aktif:raise OrganisasiError('Aktifkan perusahaan sebelum mengaktifkan lokasi pabrik.')
    q=select(model.id).where(model.kode==kode,model.id!=(identitas or 0))
    if model is LokasiPabrik:q=q.where(model.company_id==company_id)
    if await db.scalar(q):raise OrganisasiError('Kode sudah digunakan. Gunakan kode lain.')
    if row and not aktif:
        if model is Perusahaan:
            terpakai=await db.scalar(select(LokasiPabrik.id).where(LokasiPabrik.company_id==row.id,LokasiPabrik.aktif.is_(True)).limit(1))
            terpakai=terpakai or await db.scalar(select(KeanggotaanPerusahaan.id).where(KeanggotaanPerusahaan.company_id==row.id,KeanggotaanPerusahaan.aktif.is_(True)).limit(1))
            terpakai=terpakai or await db.scalar(select(PenempatanGudang.warehouse_id).where(PenempatanGudang.company_id==row.id).limit(1))
        else:
            terpakai=await db.scalar(select(PenempatanGudang.warehouse_id).where(PenempatanGudang.lokasi_pabrik_id==row.id).limit(1))
        if terpakai:raise OrganisasiError('Master masih digunakan. Periksa lokasi, gudang, atau keanggotaan terkait sebelum menonaktifkan.')
    if row and row.nama==nama and row.aktif==aktif and (model is Perusahaan or (row.alamat or '')==alamat):
        return row
    sebelum=potret(row) if row else None
    if row is None:
        row=model(kode=kode,nama=nama,aktif=aktif)
        if model is LokasiPabrik:row.company_id=company_id;row.alamat=alamat
        db.add(row)
    else:
        row.nama=nama;row.aktif=aktif
        if model is LokasiPabrik:row.alamat=alamat
    await db.flush();await db.refresh(row)
    sesudah=potret(row)
    await log_activity(db,table_name=model.__tablename__,record_id=row.id,
        action='UPDATE' if sebelum else 'INSERT',changed_by=user_id,
        field_name='master_organisasi',old_value=json.dumps(sebelum,ensure_ascii=False) if sebelum else None,
        new_value=json.dumps(sesudah,ensure_ascii=False),alasan=alasan,aksi='master_organisasi')
    return row


async def baca(db):
    """Data pengaturan; tidak memakai nama atau kode gudang untuk menebak organisasi."""
    with db.no_autoflush:
        companies=list(await db.scalars(select(Perusahaan).order_by(Perusahaan.nama,Perusahaan.id)))
        sites=list(await db.scalars(select(LokasiPabrik).order_by(LokasiPabrik.nama,LokasiPabrik.id)))
        bindings=list(await db.scalars(select(PenempatanGudang)))
    return companies,sites,bindings
