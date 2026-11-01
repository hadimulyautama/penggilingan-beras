"""Lencana tampilan selama maksimal dua detik, terpisah per pengguna/cakupan.

Ini bukan cache izin atau stok transaksi. Setiap rute tetap memeriksa akun
dan peran. Perubahan melalui aplikasi mengosongkan cache sebelum GET hasil
simpan; perubahan dari layanan lain terlihat paling lambat dua detik.
"""
from app.performa import NilaiSingkat, boleh_memo

cache = NilaiSingkat(detik=2.0)


def kunci(user):
    return (user.id, user.role, user.default_warehouse_id)


def ingat(user, nilai):
    if boleh_memo():
        cache.simpan(kunci(user), nilai)


async def ambil(user, baca):
    if not boleh_memo():
        return await baca()
    return await cache.ambil(kunci(user), baca)
