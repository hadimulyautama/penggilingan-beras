"""Kontrak baca penerimaan kembali, bukan pembelian/retur pelanggan baru.

Belum ada writer penerimaan kembali supplier dengan relasi item keluar di
aplikasi ini. Karena itu pemanggil tidak boleh menganggap pilihan operator
atau transaksi Barang Masuk yang mirip namanya sebagai stok kembali.
"""
from decimal import Decimal as D


def rekap(rec,items,efektif,rows):
    """Validasi per item untuk adapter penerimaan sah saat tersedia.

    Tidak menerima payload HTTP. Setiap baris harus berasal dari catatan
    penerimaan beserta identitas mutasi masuk yang sudah tercatat.
    """
    asli={i.id:i for i in items};hasil={i.id:D(0) for i in items};seen=set()
    for x in rows:
        if x['status']!='diterima':continue
        i=asli.get(x['item_id'])
        if not i or x['retur_supplier_id']!=rec.id or x['pemilik_id'] is not None or x['warehouse_id']!=i.warehouse_id:
            raise ValueError('Hubungan penerimaan kembali tidak sesuai retur, item, pemilik atau gudang.')
        if not x.get('mutasi_id'):raise ValueError('Penerimaan belum memiliki mutasi masuk yang sah.')
        key=(x['mutasi_id'],x['item_id'])
        if key in seen:raise ValueError('Dokumen mutasi penerimaan kembali terhitung ganda.')
        seen.add(key);n=D(str(x['bobot_kg']))
        if not n.is_finite() or n<=0:raise ValueError('Bobot penerimaan kembali tidak sah.')
        hasil[i.id]+=n
    if any(hasil[i]>efektif[i]['bobot_kg'] for i in hasil):raise ValueError('Penerimaan kembali melebihi jumlah keluar efektif pada item asal.')
    return dict(tersedia=True,jumlah=hasil,sisa={i:efektif[i]['bobot_kg']-hasil[i] for i in hasil},dokumen=sorted(seen),lengkap=all(hasil[i]==efektif[i]['bobot_kg'] for i in hasil))


async def baca(db,rec,items,efektif):
    return dict(tersedia=False,jumlah=None,sisa=None,dokumen=[],lengkap=False,
        alasan='Alur penerimaan kembali khusus Retur ke Supplier belum tersedia. Barang yang kembali belum dapat diakui sebagai stok melalui halaman ini.')
