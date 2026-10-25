"""Unit PK giling sendiri: karung penuh 50 kg dan sisa curah.

Aturan pemilik 25 Oktober 2026. Ini memecah satu bobot yang sudah sah,
bukan menghasilkan stok atau membulatkan bobot bahan menjadi kelipatan50.
PK pembelian luar tetap memakai pembagi partainya sendiri.
"""
from decimal import Decimal, ROUND_HALF_UP

UKURAN = Decimal('50')


def bagi(berat):
    kg = Decimal(str(berat))
    if not kg.is_finite() or kg < 0:
        raise ValueError('Bobot PK harus valid dan tidak negatif.')
    n = int(kg // UKURAN)
    return n, kg - n * UKURAN


def bagi_tersimpan(berat, desimal):
    """Rincian unit mengikuti Numeric PostgreSQL, tanpa mengubah bobotnya.

    asyncpg mengode float sebagai Decimal(float), bukan Decimal(str(float)).
    Keduanya berbeda tepat di setengah satuan: ketikan1.005 sudah menjadi
    float sedikit di bawah1.005 dan tetap tersimpan1.00 oleh jalur lama.
    Mengubah bobot utama untuk merapikan unit akan mengubah stok lama.
    """
    nilai = Decimal(berat) if isinstance(berat, float) else Decimal(str(berat))
    return bagi(nilai.quantize(Decimal(1).scaleb(-desimal), rounding=ROUND_HALF_UP))


def angka(kg):
    return format(Decimal(str(kg)), ',.3f').rstrip('0').rstrip('.').replace(',', '_').replace('.', ',').replace('_', '.')


def teks(berat):
    n, c = bagi(berat)
    return f'{n} karung × 50 kg + {angka(c)} kg curah'


def bobot_isian(*, berat=None, jumlah_karung=None, berat_curah_kg=None,
                 cara=None):
    """Ubah satu pilihan unit menjadi kg, tanpa membaca atau menulis stok.

    Permintaan dan pengiriman tetap lewat layanan empat langkah yang lama.
    Cara kg mempertahankan pemanggil lama, termasuk berat kosong pada kirim.
    Angka curah juga boleh merupakan bagian karung hasil timbang: jangan
    menambah batas curah atau batas saldo per komponen di pintu konversi ini.
    """
    unit = jumlah_karung is not None or berat_curah_kg is not None
    if cara not in (None, 'karung', 'kg'):
        raise ValueError('Pilih cara pengisian karung atau kg hasil timbang.')
    if (berat is not None and unit) or (cara == 'kg' and unit) or (cara == 'karung' and berat is not None):
        raise ValueError('Gunakan karung dan curah, atau bobot kg; jangan mengirim keduanya.')
    if not unit and cara != 'karung':
        return berat
    try:
        k = Decimal(str(jumlah_karung)) if jumlah_karung is not None else Decimal(0)
        c = Decimal(str(berat_curah_kg)) if berat_curah_kg is not None else Decimal(0)
        if isinstance(jumlah_karung, bool) or not k.is_finite() or k < 0 or k != k.to_integral_value():
            raise ValueError('Jumlah karung harus bilangan bulat, nol atau lebih.')
        if not c.is_finite() or c < 0:
            raise ValueError('Bobot curah harus valid, nol atau lebih.')
        total = float(k * UKURAN + c)
    except (ArithmeticError, TypeError):
        raise ValueError('Isi jumlah karung dan bobot curah yang valid.') from None
    from math import isfinite
    if not isfinite(total) or total <= 0:
        raise ValueError('Isi karung atau curah dengan total lebih dari nol.')
    return total


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
