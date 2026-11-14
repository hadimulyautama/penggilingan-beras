"""Login sandi Console memakai identitas lama, tanpa cookie aplikasi harian.

Hanya metadata sesi Console dan waktu masuk yang ditulis. Snapshot hash/versi
sebelum verifikasi dibandingkan lagi setelah kunci akun diperoleh: sandi lama
yang benar tidak boleh mendapat sesi baru bila sandinya baru saja diganti.
"""
import hmac,secrets
from sqlalchemy import select
from hmu_identitas import masuk as identitas,peran as P
from hmu_identitas.model import Akun
from app.services import console_auth as auth


class Ditolak(Exception):
    def __init__(self,status,kode):self.status=status;self.kode=kode


async def masuk(db,username,sandi):
    try:a=await identitas.periksa_kredensial(db,username,sandi)
    except identitas.Tolak as e:raise Ditolak(e.kode,'kredensial' if e.kode==401 else 'nonaktif') from None
    snapshot=(a.password_hash,int(a.token_version or 1),a.username)
    a=await db.scalar(select(Akun).where(Akun.id==a.id).with_for_update(of=Akun).execution_options(populate_existing=True))
    if not a or not hmac.compare_digest(a.password_hash,snapshot[0]) or (int(a.token_version or 1),a.username)!=snapshot[1:]:
        raise Ditolak(401,'kredensial')
    if not a.aktif:raise Ditolak(403,'nonaktif')
    if not P.super_saja(a.peran):raise Ditolak(403,'peran')
    if a.harus_ganti_sandi:raise Ditolak(403,'wajib_sandi')
    # Model sesi dan seluruh pemeriksaan pencabutannya sama dengan SSO lama.
    verifier=secrets.token_urlsafe(48)
    code=await auth.terbitkan(db,akun_id=a.id,versi=a.token_version,tantangan=auth.challenge(verifier))
    token=await auth.tukar(db,kode=code,verifier=verifier)
    a.terakhir_login=auth.now()
    await db.flush()
    return dict(token=token,nama=a.nama,berlaku_detik=3600)
