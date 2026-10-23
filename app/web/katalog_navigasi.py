"""Alihkan pintasan lama hanya bila konteksnya dapat dibuktikan, tanpa menulis data."""
from urllib.parse import urlencode
from app.database import SessionLocal
from app.models import Jasa


async def tujuan_duplikat(buka, nilai, params):
    if buka in ('tutup_jasa', 'batalkan_jasa'):
        if nilai.isascii() and nilai.isdecimal() and len(nilai) <= 10 and 0 < int(nilai) < 2**31:
            async with SessionLocal() as db:
                pesanan = await db.get(Jasa, int(nilai))
                if pesanan:
                    q = dict(params)
                    q.update(tab='ringkasan', buka=buka, nilai=str(pesanan.id))
                    return (f'/jasa/pelanggan/{pesanan.pelanggan_id}?' + urlencode(q)
                            + f'#pesanan-{pesanan.id}', '', '', '')
        return '', 'Pilih pesanan yang sesuai pada Pesanan Jasa. Konteks pesanan belum lengkap atau tidak ditemukan.', '/jasa', 'Buka Pesanan Jasa'
    if buka == 'masukkan_beras_silo':
        from app.services.stok import BERAS_JENIS
        bagian = nilai.split('|')
        # Jenis/pemilik adalah format medan lama. Titipan tanpa nomor pesanan
        # tidak boleh dipetakan ke stok pelanggan tertentu berdasarkan tebakan.
        # Token sumber lama membawa nomor pesanan; verifikasi ke data aslinya.
        if len(bagian) == 2 and bagian[0] in BERAS_JENIS and bagian[1] == 'pabrik':
            q = dict(params)
            q.update(jenis=bagian[0], pemilik='pabrik', buka=buka, nilai=nilai)
            return '/stok-produk/detail?' + urlencode(q), '', '', ''
        if len(bagian) == 2 and bagian[0] in BERAS_JENIS and bagian[1] == 'jasa':
            token = params.get('sumber_stok', '').rsplit('|', 1)[-1]
            if token.isascii() and token.isdecimal() and len(token) <= 10 and 0 < int(token) < 2**31:
                async with SessionLocal() as db:
                    pesanan = await db.get(Jasa, int(token))
                    if pesanan:
                        q = dict(params)
                        q.update(jenis=bagian[0], pelanggan_id=pesanan.pelanggan_id, buka=buka, nilai=nilai)
                        return '/stok-produk-jasa/detail?' + urlencode(q), '', '', ''
        return '', 'Pilih stok beras dan pemilik yang sesuai di Stok untuk memasukkannya ke silo. Konteks stok belum lengkap.', '/stok?tab=produk', 'Buka Stok'
    return '', '', '', ''
