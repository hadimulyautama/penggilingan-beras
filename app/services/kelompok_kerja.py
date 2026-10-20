"""Pengelompokan layar saja. Kartu, izin dan transaksi tetap milik penyusun lama.

`bahan` bukan sinonim penerimaan: pindah_tumpukan dan masukkan_pk sudah
memiliki catatan masuk. Memindahkan grup itu utuh menawarkan penerimaan ulang.
"""
from dataclasses import dataclass

PENERIMAAN = frozenset({
    'gabah_masuk', 'catat_pk_luar', 'catat_beras_timbang_masuk',
    'catat_broken_timbang_masuk',
})
JENIS_BARANG = (
    ('gabah_basah', 'Gabah basah'), ('gabah_kering', 'Gabah kering'),
    ('pk', 'PK'), ('beras', 'Beras'), ('broken', 'Broken'),
    ('lain', 'Jenis belum dikenal'),
)
JENIS_KERJA = (
    ('penempatan', 'Penempatan bahan'), ('pengeringan', 'Pengeringan'),
    ('giling', 'Giling'), ('sosoh', 'Sosoh'), ('transfer', 'Transfer PK'),
    ('packing', 'Packing'), ('muat', 'Muat'), ('qc', 'QC'),
    ('keputusan', 'Keputusan'), ('lain', 'Lainnya'),
)


def penerimaan(b):
    # Tiket PK operator dan tiket asing sengaja kartu informasi. Tiket yang
    # sudah diterima juga membawa tiket_kode, jadi kolom itu saja tidak cukup.
    return b.aksi in PENERIMAAN or (b.kelompok == 'tiket' and not b.aksi)


def dapat_ditindak(b):
    if b.tombol:
        return any(not t.mati for t in b.tombol)
    return bool(b.aksi or b.pilihan)


def jenis_kerja(b):
    from app.services.keputusan import AKSI_MUTU
    a = b.aksi or ''
    if a in AKSI_MUTU:
        return 'qc'
    if a in ('acc_permintaan_pk', 'tutup_permintaan_pk', 'betulkan_bobot_giling'):
        return 'keputusan'
    if b.kelompok == 'permintaan' or a in ('kirim_permintaan_pk', 'minta_pk_g1'):
        return 'transfer'
    if b.kelompok == 'produk' or a.startswith('catat_packing'):
        return 'packing'
    if b.kelompok == 'keluar':
        return 'muat'
    if a in ('pindah_tumpukan', 'masukkan_pk', 'pindah_tumpukan_silo', 'pindah_silo'):
        return 'penempatan'
    if b.fase == 'dryer':
        return 'pengeringan'
    if b.fase in ('silo', 'giling'):
        return 'giling'
    if b.fase in ('silo_g2', 'sosoh'):
        return 'sosoh'
    return 'lain'


@dataclass
class Kelompok:
    masuk: list
    tindakan: list
    berjalan: list
    informasi: list


def bagi(b):
    masuk, tindakan, informasi = [], [], []
    for kartu in b.menunggu:
        if penerimaan(kartu):
            masuk.append(kartu)
        elif dapat_ditindak(kartu):
            tindakan.append(kartu)
        else:
            informasi.append(kartu)
    # Transit yang siap dikerjakan tetap memakai tindakan dan kondisi lama.
    # Mesin aktif/pendinginan menunggu waktu tetap di Berjalan, meski kartunya
    # menyediakan pencatatan hasil atau pernyataan selesai.
    for kartu in b.transit:
        (tindakan if dapat_ditindak(kartu) else informasi).append(kartu)
    tindakan.extend(b.meja)
    return Kelompok(masuk, tindakan, list(b.berjalan), informasi)
