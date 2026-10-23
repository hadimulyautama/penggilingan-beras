"""Provision/revoke customer credentials; passwords are read only from the TTY.

Run from produksi/: .venv/bin/python -m scripts.portal_pelanggan --help
No sample account is ever created by a migration or application startup.
"""
import argparse
import asyncio
from getpass import getpass
from sqlalchemy import select
from app.database import SessionLocal,engine
from app.models import Pelanggan
from app.models.portal import PortalAccount
from app.web.security import hash_sandi


async def run(args):
    name=args.username.strip().casefold()
    if not name or len(name)>80 or not name.isascii() or not name.replace('-','').replace('_','').isalnum():
        raise ValueError('Nama pengguna wajib 1–80 huruf/angka ASCII, tanda hubung, atau garis bawah.')
    async with SessionLocal() as db:
        account=await db.scalar(select(PortalAccount).where(PortalAccount.username==name).with_for_update())
        if args.action=='buat':
            if account:raise ValueError('Nama pengguna sudah digunakan. Gunakan reset-sandi atau nonaktifkan.')
            customer=await db.get(Pelanggan,args.pelanggan_id)
            if not customer:raise ValueError('ID pelanggan tidak ditemukan.')
            print(f'Pelanggan: #{customer.id} · {customer.nama_pelanggan}')
        elif not account:raise ValueError('Akun tidak ditemukan.')
        if args.action in ('buat','reset-sandi'):
            password=getpass('Kata sandi baru (tidak ditampilkan): ')
            if password!=getpass('Ulangi kata sandi: '):raise ValueError('Kata sandi tidak sama.')
            hashed=hash_sandi(password)
            if account:
                account.password_hash=hashed;account.token_version+=1
            else:
                account=PortalAccount(username=name,pelanggan_id=customer.id,password_hash=hashed,active=True,token_version=1)
                db.add(account)
        else:
            account.active=False;account.token_version+=1
        await db.commit()
        print(f'Akun {name}: {args.action} berhasil. Identitas pelanggan tidak diubah.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['buat','reset-sandi','nonaktifkan'])
    parser.add_argument('username')
    parser.add_argument('--pelanggan-id',type=int)
    args=parser.parse_args()
    if args.action=='buat' and not args.pelanggan_id:parser.error('--pelanggan-id wajib untuk membuat akun')
    async def execute():
        try:await run(args)
        finally:await engine.dispose()
    try:asyncio.run(execute())
    except ValueError as exc:parser.exit(1,str(exc)+'\n')


if __name__=='__main__':main()
