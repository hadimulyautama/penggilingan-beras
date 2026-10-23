"""Account administration for customer-only principals, never staff users."""
import asyncio
import re
from sqlalchemy import select, func
from app.models import Pelanggan, ProduksiAkun
from app.models.portal import PortalAccount
from app.services.activity_log import log_activity
from app.web.security import hash_sandi


def allowed(actor):
    if not actor.is_super:
        raise ValueError('Kelola akun pelanggan hanya untuk Super Admin.')


def username(value):
    value=value.strip().casefold()
    if not re.fullmatch(r'[a-z0-9_-]{3,80}',value):
        raise ValueError('Username harus 3–80 huruf/angka, tanda hubung, atau garis bawah.')
    return value


async def contact(db,pelanggan_id,kledo_id=None):
    if not 0 < pelanggan_id < 2**31 or (kledo_id is not None and not 0 < kledo_id < 2**63):
        raise ValueError('Identitas kontak tidak valid.')
    row=await db.scalar(select(Pelanggan).where(Pelanggan.id==pelanggan_id).with_for_update())
    if not row or row.status!='aktif' or row.deleted_at is not None or not row.kledo_contact_id:
        raise ValueError('Pilih pelanggan aktif yang sudah terhubung ke kontak Kledo.')
    if kledo_id is not None and row.kledo_contact_id!=kledo_id:
        raise ValueError('Tautan kontak Kledo berubah. Muat ulang dan pilih pelanggan kembali.')
    count=await db.scalar(select(func.count()).select_from(Pelanggan).where(
        Pelanggan.kledo_contact_id==row.kledo_contact_id,Pelanggan.status=='aktif',Pelanggan.deleted_at.is_(None)))
    if count!=1:raise ValueError('Kontak Kledo terhubung ke beberapa pelanggan. Periksa penautan kontak terlebih dahulu.')
    return row


async def unique(db,name,account_id=None):
    # Same namespace lock for concurrent customer account writers.
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext('portal-account:'+name))))
    exists=await db.scalar(select(PortalAccount.id).where(PortalAccount.username==name,
        PortalAccount.id!=account_id if account_id is not None else True))
    staff=await db.scalar(select(ProduksiAkun.id).where(func.lower(ProduksiAkun.username)==name))
    if exists or staff:raise ValueError('Username sudah digunakan. Pilih username lain.')


async def audit(db,account,actor,action,kind='UPDATE'):
    await log_activity(db,table_name='portal_accounts',record_id=account.id,action=kind,
        changed_by=actor.user_id,new_value=f'{action} · {account.username} · pelanggan #{account.pelanggan_id}',
        aksi='kelola_akun_portal')


async def create(db,*,actor,pelanggan_id,kledo_id,name,password,confirmation):
    allowed(actor)
    name=username(name)
    if password!=confirmation:raise ValueError('Konfirmasi kata sandi tidak sama.')
    if len(password)>512:raise ValueError('Kata sandi maksimal 512 karakter.')
    customer=await contact(db,pelanggan_id,kledo_id)
    await unique(db,name)
    hashed=await asyncio.to_thread(hash_sandi,password)
    row=PortalAccount(pelanggan_id=customer.id,username=name,password_hash=hashed,active=True,token_version=1)
    db.add(row);await db.flush();await audit(db,row,actor,'Buat akun pelanggan','INSERT')
    return row


async def edit(db,*,actor,account_id,name,password='',confirmation=''):
    allowed(actor)
    row=await db.scalar(select(PortalAccount).where(PortalAccount.id==account_id).with_for_update())
    if row is None:raise ValueError('Akun pelanggan tidak ditemukan.')
    name=username(name);await unique(db,name,row.id)
    if password!=confirmation:raise ValueError('Konfirmasi kata sandi tidak sama.')
    if len(password)>512:raise ValueError('Kata sandi maksimal 512 karakter.')
    changed=name!=row.username
    if password:
        row.password_hash=await asyncio.to_thread(hash_sandi,password);changed=True
    row.username=name
    if changed:
        row.token_version+=1
        await audit(db,row,actor,'Ubah username / kata sandi pelanggan')
    return row


async def set_active(db,*,actor,account_id,active):
    allowed(actor)
    row=await db.scalar(select(PortalAccount).where(PortalAccount.id==account_id).with_for_update())
    if row is None:raise ValueError('Akun pelanggan tidak ditemukan.')
    if active:await contact(db,row.pelanggan_id)
    if row.active!=active:
        row.active=active;row.token_version+=1
        await audit(db,row,actor,'Aktifkan akun pelanggan' if active else 'Nonaktifkan akun pelanggan')
    return row
