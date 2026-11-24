"""Prototype struktur Stok berizin, tanpa saldo, baris atau cache transaksi."""
from fastapi import Request

MAX_JSON_BYTES = 1572864


def sah_descriptor(data):
    """Batas biaya struktur opsional; bukan pemeriksaan otorisasi."""
    from jinja2.utils import htmlsafe_json_dumps
    if (not isinstance(data, dict)
            or set(data) != {'versi', 'cap', 'konteks', 'sesi', 'penyandian', 'potongan', 'frames'}
            or data['versi'] != 1 or data['penyandian'] != 'baris-1'
            or not all(isinstance(data[k], str) and data[k] for k in ('cap', 'konteks', 'sesi'))):
        return False
    frames, pieces = data['frames'], data['potongan']
    if (not isinstance(frames, dict) or set(frames) not in ({'bahan'}, {'bahan', 'produk', 'karung'})
            or not isinstance(pieces, list) or not 0 < len(pieces) <= 16384
            or not all(isinstance(s, str) and s for s in pieces)):
        return False
    for refs in frames.values():
        if (not isinstance(refs, list) or not 0 < len(refs) <= 16384
                or not all(type(i) is int and 0 <= i < len(pieces) for i in refs)
                or sum(len(pieces[i].encode('utf-8')) for i in refs) > 524288):
            return False
    return len(htmlsafe_json_dumps(data).encode('utf-8')) <= MAX_JSON_BYTES


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
        if len(response.body) > 524288:
            return None
        frames[tab] = response.body.decode('utf-8')
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)),
                                    request.cookies.get('produksi_lihat', '')),
                **kemas_frame(frames))
    return result if sah_descriptor(result) else None
