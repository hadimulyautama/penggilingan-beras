"""Unit PK giling sendiri: karung penuh 50 kg dan sisa curah.

Aturan pemilik 25 Oktober 2026. Ini memecah satu bobot yang sudah sah,
bukan menghasilkan stok atau membulatkan bobot bahan menjadi kelipatan50.
PK pembelian luar tetap memakai pembagi partainya sendiri.
"""
from decimal import Decimal

UKURAN = Decimal('50')


def bagi(berat):
    kg = Decimal(str(berat))
    if not kg.is_finite() or kg < 0:
        raise ValueError('Bobot PK harus valid dan tidak negatif.')
    n = int(kg // UKURAN)
    return n, kg - n * UKURAN


def angka(kg):
    return format(Decimal(str(kg)), ',.3f').rstrip('0').rstrip('.').replace(',', '_').replace('.', ',').replace('_', '.')


def teks(berat):
    n, c = bagi(berat)
    return f'{n} karung × 50 kg + {angka(c)} kg curah'


def pilihan(saldo, jumlah_karung=None, berat_curah_kg=None):
    """Unit yang dipilih atas saldo yang dibaca pemanggil.

    Pratinjau dan simpan memakai pemecahan yang sama. Simpan tetap membaca
    saldo lagi setelah mengunci sumber; jawaban pratinjau bukan izin stok.
    Kosong keduanya mempertahankan arti lama: seluruh saldo.
    """
    n, sisa_curah = bagi(saldo)
    try:
        k = Decimal(str(jumlah_karung)) if jumlah_karung is not None else Decimal(0 if berat_curah_kg is not None else n)
        c = Decimal(str(berat_curah_kg)) if berat_curah_kg is not None else (sisa_curah if jumlah_karung is None else Decimal(0))
        if isinstance(jumlah_karung, bool) or not k.is_finite() or k < 0 or k != k.to_integral_value() or not c.is_finite() or c < 0:
            raise ValueError
    except (ValueError, ArithmeticError):
        raise ValueError('Isi jumlah karung bulat dan berat curah yang valid, nol atau lebih.') from None
    if k > n or c > sisa_curah:
        raise ValueError(f'Tersedia {n} karung 50 kg dan {angka(sisa_curah)} kg curah. Gunakan kg hasil timbang untuk sebagian karung.')
    total = k * UKURAN + c
    if total <= 0:
        raise ValueError('Pilih karung atau curah yang akan dipindahkan; jumlahnya harus lebih dari nol.')
    return int(k), c, total
