"""Authorization code + PKCE. Cookie CMS dan token operator bukan sesi Console."""
import base64,hashlib,hmac,re,secrets
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from hmu_identitas import masuk,peran as P
from app.models import SesiConsole
from hmu_identitas.model import Akun


class TolakConsole(PermissionError):
    pass


def hash_(value):return hashlib.sha256(value.encode()).hexdigest()
def now():return datetime.now(timezone.utc)
def challenge(verifier):return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


async def super_aktif(db,aid,versi):
    # Jangan menerima Akun/User dari identity map yang mendahului pencabutan.
    with db.no_autoflush:
        await db.scalar(select(Akun).where(Akun.id==aid).execution_options(populate_existing=True))
        a=await masuk.akun_aktif(db,aid,versi)
    if not a or a.harus_ganti_sandi or not P.super_saja(a.user.role):raise TolakConsole('Console Center hanya untuk Super Admin aktif.')
    return a


async def terbitkan(db,*,akun_id,versi,tantangan):
    await super_aktif(db,akun_id,versi)
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',tantangan):raise ValueError('Tantangan masuk tidak valid.')
    kode=secrets.token_urlsafe(32)
    db.add(SesiConsole(akun_id=akun_id,versi=versi,kode_hash=hash_(kode),tantangan=tantangan,kode_sampai=now()+timedelta(minutes=2)))
    await db.flush();return kode


async def tukar(db,*,kode,verifier):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',kode or '') or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}',verifier or ''):
        raise TolakConsole('Kode masuk Console tidak valid atau sudah berakhir.')
    row=await db.scalar(select(SesiConsole).where(SesiConsole.kode_hash==hash_(kode)).with_for_update().execution_options(populate_existing=True))
    if not row or row.dicabut or row.ditukar_pada or row.kode_sampai<=now() or not hmac.compare_digest(row.tantangan,challenge(verifier)):
        raise TolakConsole('Kode masuk Console tidak valid atau sudah berakhir.')
    await super_aktif(db,row.akun_id,row.versi)
    token=secrets.token_urlsafe(48);row.token_hash=hash_(token);row.ditukar_pada=now();row.sesi_sampai=now()+timedelta(hours=1)
    await db.flush();return token


async def periksa(db,token):
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{64}',token):raise TolakConsole('Masuk kembali ke Console Center.')
    with db.no_autoflush:
        row=await db.scalar(select(SesiConsole).where(SesiConsole.token_hash==hash_(token)).execution_options(populate_existing=True))
    if not row or row.dicabut or not row.ditukar_pada or not row.sesi_sampai or row.sesi_sampai<=now():raise TolakConsole('Sesi Console sudah berakhir. Masuk kembali.')
    return row,await super_aktif(db,row.akun_id,row.versi)
