"""Kontak sintetis yang mewakili cermin Kledo sah, tanpa memanggil Kledo.

Pemanggil memilih helper ini secara eksplisit. Pelanggan tanpa tautan tetap
bisa dibuat dengan model biasa untuk menguji penolakan; tidak ada autouse
atau listener yang menyulap semua kontak pengujian menjadi kontak sah.
"""
from itertools import count
from app.models import Pelanggan

_id_kledo = count(900_000_000)


def pelanggan_kledo(**fields):
    return Pelanggan(kledo_contact_id=next(_id_kledo), **fields)
