"""A portal token cannot be used as a staff token, even with a renamed cookie."""
from dataclasses import dataclass
import hashlib
import hmac
from fastapi import HTTPException, Request
from sqlalchemy import select
from app.database import SessionLocal
from app.models.portal import PortalAccount
from hmu_identitas import token
from app.web.security import _kunci

COOKIE = 'pelanggan_sesi'
SESSION_SECONDS = 12 * 3600


def key():
    return hmac.new(_kunci(), b'customer-portal-v1', hashlib.sha256).digest()


def issue(account):
    return token.buat_token(key(), akun_id=account.id, versi=account.token_version,
                            umur_detik=SESSION_SECONDS, ekstra={'pid': account.pelanggan_id})


@dataclass(frozen=True)
class CustomerReader:
    account_id: int
    pelanggan_id: int
    nama: str
    # No production staff user ID or elevated role is ever assigned.
    role: str = 'pelanggan'


async def require_customer(request: Request):
    value = token.baca_token(key(), request.cookies.get(COOKIE))
    if not value:
        raise HTTPException(401, 'Silakan masuk ke portal pelanggan.')
    from app.models import Pelanggan
    async with SessionLocal() as db:
        row = (await db.execute(select(PortalAccount, Pelanggan.nama_pelanggan)
            .join(Pelanggan, Pelanggan.id == PortalAccount.pelanggan_id)
            .where(PortalAccount.id == value['akun_id'],
                   PortalAccount.active.is_(True), PortalAccount.token_version == value['versi']))).first()
    if row is None or value.get('pid') != row[0].pelanggan_id:
        raise HTTPException(401, 'Sesi portal tidak berlaku.')
    return CustomerReader(row[0].id, row[0].pelanggan_id, row[1])
