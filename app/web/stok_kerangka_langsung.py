"""Prototype struktur Stok berizin, tanpa saldo, baris atau cache transaksi."""
from fastapi import Request


async def susun(request: Request, akun, *, navigasi):
    from hmu_tampilan import CAP_ASET
    from app.database import SessionLocal
    from app.services.cakupan_fasilitas import (
        boleh_baca_stok, pilihan_filter_stok, pilihan_gudang,
    )
    from app.services.transfer_lokasi import daftar as daftar_lokasi
    from app.web import csrf
    from app.web.halaman_bertahap import kerangka, penanda_konteks
    from app.web.kerangka_langsung import kemas_frame
    from app.web.security import NAMA_COOKIE, baca_token

    async with SessionLocal() as db:
        boleh_produk = await boleh_baca_stok(db, akun.user)
        bahan = await pilihan_filter_stok(db, akun.user)
        lainnya = tuple((w.kode_fungsi or 'wh:' + str(w.id), w.nama_gudang, '')
                        for w in await pilihan_gudang(db, akun.user))
        metadata = await daftar_lokasi(db)
    state = dict(request.scope.get('state', {}))
    state.update(menyusun_kerangka_langsung=True, frame_kerangka_langsung=True)
    frames = {}
    for tab in ('bahan', 'produk', 'karung') if boleh_produk else ('bahan',):
        native = Request({**request.scope, 'path': '/stok', 'raw_path': b'/stok',
                          'query_string': ('tab=' + tab + '&pemilik=semua').encode(),
                          'state': dict(state)})
        # Metadata hanya dipakai pada tiga prototype dalam permintaan ini.
        # Penjaga kerangka native tetap dijalankan; ini bukan cache izin.
        response = await kerangka(native, akun, 'stok', navigasi=navigasi,
                                  stok_lokasi=(bahan if tab == 'bahan' else lainnya, metadata))
        if response.status_code != 200:
            return None
        frames[tab] = response.body.decode('utf-8')
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    return dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)),
                                    request.cookies.get('produksi_lihat', '')),
                **kemas_frame(frames))
