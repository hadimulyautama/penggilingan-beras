"""Ringkasan pengemasan beras baca saja; tidak membuat SKU atau catatan stok."""
import math
from sqlalchemy import select
from app.models import PolishingProcess, Jasa
from app.penggilingan.inventory import finished_goods as bj, packaging as kms
from app.services.stok import BERAS_JENIS, kategori_dan_mutu, nama_produk
from app.services.jasa import pemilik_hasil_proses, nama_pemilik
from app.services.angka import angka_wajar


async def rincian(db, sumber, kemasan='', merk='', jumlah=''):
    bagian = (sumber or '').split('|')
    if len(bagian) != 2 or not bagian[0].strip():
        raise ValueError('Pilih produk yang dikemas.')
    kode, jenis = bagian[0].strip(), bagian[1].strip().lower()
    # Packing hasil samping tetap memakai tampilan dan kontrak lama.
    if jenis not in BERAS_JENIS:
        return dict(beras=False)
    proc = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == kode))
    if proc is None:
        raise ValueError('Proses sumber tidak ditemukan.')
    kategori, mutu = kategori_dan_mutu(jenis)
    std = await kms.get_standard(db, mutu) if mutu else None
    saldo = await bj.saldo_packing(db, proc, kategori, mutu, std.id if std else None)
    owner = await pemilik_hasil_proses(db, proc.jasa_id, jenis)
    out = dict(beras=True, kode=kode, jenis=jenis, produk=nama_produk(jenis),
               pemilik=await nama_pemilik(db, owner) if owner else 'Milik pabrik',
               jasa_id=owner, status=proc.status, saldo=saldo, kemasan=None,
               karung=None, maksimal=None, rencana=None, pesan='')
    if not kemasan:
        return out
    try:
        material, ukuran = kemasan.split('|')
        if not ukuran.isdigit(): raise ValueError('Pilih karung dan ukurannya.')
        ukuran = int(ukuran)
        kms._validate_kemasan(kategori, material, ukuran)
        mat, size = await kms.get_material(db, material), await kms.get_size(db, ukuran)
        if mat is None or size is None: raise ValueError('Kemasan tidak terdaftar.')
        brand = await kms.get_brand(db, merk) if merk else None
        if merk and brand is None: raise ValueError('Merek tidak ditemukan.')
        jasa = await db.get(Jasa, owner) if owner else None
        stok = await kms.hitung_stok_kemasan(db, mat.id, size.id, brand.id if brand else None,
                                           pelanggan_id=jasa.pelanggan_id if jasa else None)
        out.update(kemasan=dict(material=mat.nama, ukuran=ukuran, merek=brand.nama if brand else 'Tanpa merek'),
                   karung=stok, maksimal=max(0, math.floor(saldo['tersedia']/ukuran)))
        if str(jumlah).strip() == '': return out
        n = angka_wajar(jumlah, 'Jumlah karung')
        if not n.is_integer(): raise ValueError('Jumlah karung wajib bilangan bulat lebih dari nol.')
        berat = n * ukuran
        if berat > saldo['tersedia'] + 0.000001:
            raise ValueError('Jumlah melebihi saldo hasil yang dapat dikemas. Periksa jumlah karung.')
        out['rencana'] = dict(jumlah=int(n), berat=berat, sisa=saldo['tersedia']-berat, sisa_karung=stok-int(n))
    except (ValueError, kms.InventoryError) as e:
        out['pesan'] = str(e)
    return out
