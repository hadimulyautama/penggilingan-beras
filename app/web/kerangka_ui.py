"""Pilihan struktur UI per dokumen; asetnya tidak berisi sesi atau data."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path


VARIANTS=['pengiriman-admin','pengiriman-operator','jasa-admin','akun-pribadi']+[
    f'stok-{tab}-{int(mutu)}-{int(owner)}'
    for tab in ('bahan','produk','karung') for mutu in (False,True) for owner in (False,True)]+['laporan-katalog','giling-proses']


@lru_cache(maxsize=1)
def aset():
    # Cache hanya metadata berkas program yang tetap untuk proses rilis ini.
    folder=Path(__file__).parent/'static'
    data=json.loads((folder/'kerangka-ui.meta.json').read_text())
    if (data.get('versi')!=1 or data.get('variants')!=VARIANTS
            or hashlib.sha256((folder/'kerangka-ui.js').read_bytes()).hexdigest()!=data.get('aset_sha256')):
        raise ValueError('Paket kerangka UI tidak cocok')
    return data


async def susun(request,akun,registry,*,navigasi,stok):
    from app.web.pengiriman_bertahap import boleh_baca
    from app.peran import can_see_financials
    varians={}
    if await boleh_baca(akun.user):
        varians['pengiriman']='pengiriman-admin' if can_see_financials(akun.user) else 'pengiriman-operator'
    if can_see_financials(akun.user):
        varians['jasa']='jasa-admin'
    if getattr(akun,'harus_ganti_sandi',None) is False:
        varians['akun']='akun-pribadi'
    if stok is None:
        # Hanya flag dari predicate native. Nama/ID/opsi gudang tidak dibawa
        # keluar dari allowlist descriptor privat yang sudah diaudit.
        from app.database import SessionLocal
        from app.services.cakupan_fasilitas import boleh_baca_stok
        async with SessionLocal() as db:
            produk=await boleh_baca_stok(db,akun.user)
        mutu=navigasi.get('MUTU_AKTIF')
        if type(mutu) is not bool:raise ValueError('Flag kolom Stok belum tersedia')
        tabs=('bahan','produk','karung') if produk else ('bahan',)
        owner=can_see_financials(akun.user)
        varians['stok']={tab:f'stok-{tab}-{int(mutu)}-{int(owner)}' for tab in tabs}
    from app.web.api import _is_jenis_operator
    if await _is_jenis_operator(akun.user,'penggilingan'):
        varians['giling']='giling-proses'
    if not varians:
        return None
    data=aset()
    from app.web.laporan import daftar_untuk
    if [l.kode for l in daftar_untuk(akun.user)]==data.get('laporan_codes'):
        varians['laporan']='laporan-katalog'
    return dict(versi=1,sumber=data['sumber'],
        konteks=registry['konteks'],cap=registry['cap'],sesi=registry['sesi'],
        varians=varians)
