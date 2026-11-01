"""Angka proses saja. Tidak menentukan ulang kelompok operasional kartu."""
from collections import Counter


def status_proses(b):
    if getattr(b,'status_proses',None):
        return b.status_proses
    # Kompatibilitas kartu/fixture lama, berdasarkan tindakan tahap yang sah.
    if getattr(b,'fase',None)=='dryer' and getattr(b,'aksi',None)=='selesai_pendinginan':return 'Pendinginan'
    return 'Berjalan'


def ringkasan_proses(proses):
    unik={}
    for b in proses:
        # Kode proses + keluarga adalah identitas layanan lama; batch/silo
        # yang membentuk kartu tidak ikut menambah angka proses.
        key=(getattr(b,'fase',None),b.kode) if getattr(b,'kode',None) else ('baris',id(b))
        unik.setdefault(key,b)
    counts=Counter(status_proses(b) for b in unik.values())
    return dict(jumlah=len(unik),status=[(s,counts[s]) for s in ('Berjalan','Dijeda','Pendinginan') if counts[s]])
