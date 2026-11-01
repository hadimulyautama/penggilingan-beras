"""A portal token cannot be used as a staff token, even with a renamed cookie."""
from dataclasses import dataclass
import hashlib
import hmac
import os
import time
from fastapi import HTTPException, Request
from sqlalchemy import select
from app.database import SessionLocal
from app.models.portal import PortalAccount
from hmu_identitas import token
from app.web.security import _kunci

COOKIE = 'pelanggan_sesi'
SESSION_SECONDS = 30 * 24 * 3600
RENEW_SECONDS = 7 * 24 * 3600


def secure_cookie(request):
    # Railway terminates TLS before the application connection; production
    # sessions must remain Secure even when the ASGI scheme is internal HTTP.
    return request.url.scheme == 'https' or bool(os.environ.get('RAILWAY_ENVIRONMENT_ID'))


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
    # Hanya sesi yang sudah diverifikasi terhadap akun aktif di DB yang
    # boleh diperpanjang. Token usang/dinonaktifkan tidak pernah dihidupkan.
    request.state.portal_account = row[0]
    request.state.portal_expiry = value['exp']
    return CustomerReader(row[0].id, row[0].pelanggan_id, row[1])


class PortalSessionMiddleware:
    """Perpanjang sesi pribadi yang masih sah saat mendekati akhir masa sesi."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope['type'] != 'http' or scope['method'] != 'GET'
                or not (scope['path'] == '/pelanggan' or scope['path'].startswith('/pelanggan/'))):
            return await self.app(scope, receive, send)

        async def kirim(message):
            if message['type'] == 'http.response.start' and message['status'] < 400:
                state = scope.get('state', {})
                account = state.get('portal_account')
                expiry = state.get('portal_expiry', 0)
                headers = list(message.get('headers', []))
                diurus = any(k.lower() == b'set-cookie' and v.startswith((COOKIE + '=').encode())
                              for k, v in headers)
                if account is not None and expiry - time.time() < RENEW_SECONDS and not diurus:
                    from starlette.responses import Response
                    response = Response()
                    response.set_cookie(COOKIE, issue(account), max_age=SESSION_SECONDS,
                        httponly=True, secure=secure_cookie(Request(scope)),
                        samesite='lax', path='/pelanggan')
                    headers.extend((k, v) for k, v in response.raw_headers if k == b'set-cookie')
                    message = {**message, 'headers': headers}
            await send(message)

        await self.app(scope, receive, kirim)
