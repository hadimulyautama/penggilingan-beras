"""Pencocokan bobot retur; tidak menulis stok atau mengubah data timbang.

Tara hanya menjadi toleransi, sehingga berat rincian tetap utuh saat akhirnya
diterima. Semua pemanggil (pengajuan, koreksi, dan pekerja latar) harus memakai
aturan yang sama. Keabsahan hubungan asal dan tiket diperiksa oleh layanan
transaksi sebelum memanggil pemeriksaan bobot ini.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass(frozen=True)
class BarisBobot:
    berat_kg: Decimal
    jumlah_karung: int
    # None berarti master belum lengkap, bukan tara nol. Barang curah tanpa
    # karung tidak memerlukan tara kemasan.
    tara_per_karung_kg: Decimal | None


@dataclass(frozen=True)
class HasilPemeriksaan:
    status: str
    alasan: str
    berat_rincian_kg: Decimal
    selisih_kg: Decimal | None
    toleransi_kg: Decimal | None
    wajib_manual: bool


def _desimal(nilai, nama):
    try:
        hasil = Decimal(str(nilai))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f'{nama} tidak sah.') from exc
    if not hasil.is_finite() or hasil < 0:
        raise ValueError(f'{nama} tidak sah.')
    return hasil


def periksa_bobot(baris: Iterable[BarisBobot], *, tiket_selesai: bool,
                  berat_tiket_kg: Decimal | None,
                  pernah_selisih_besar: bool = False) -> HasilPemeriksaan:
    """Batas inklusif ±jumlah tara, tanpa lantai 2 kg/persentase tersembunyi.

    Riwayat selisih besar bersifat melekat: setelah data sesuai, hasil hanya
    boleh menjadi calon verifikasi manual. Layanan transaksi tetap wajib
    membuktikan koreksi tersimpan dan izin pelaku sebelum penerimaan manual.
    """
    baris = list(baris)
    if not baris:
        raise ValueError('Isi minimal satu barang retur.')
    total = Decimal('0')
    toleransi = Decimal('0')
    tara_lengkap = True
    for item in baris:
        berat = _desimal(item.berat_kg, 'Berat rincian')
        if berat <= 0:
            raise ValueError('Berat rincian harus lebih dari nol.')
        if (not isinstance(item.jumlah_karung, int)
                or isinstance(item.jumlah_karung, bool) or item.jumlah_karung < 0):
            raise ValueError('Jumlah karung harus bilangan bulat tidak negatif.')
        total += berat
        if item.jumlah_karung:
            if item.tara_per_karung_kg is None:
                tara_lengkap = False
            else:
                try:
                    tara = _desimal(item.tara_per_karung_kg, 'Tara kemasan')
                except ValueError:
                    tara = Decimal('0')
                if tara <= 0:
                    tara_lengkap = False
                else:
                    toleransi += item.jumlah_karung * tara
    batas = toleransi if tara_lengkap else None
    if not tiket_selesai:
        return HasilPemeriksaan('menunggu_timbang', 'Menunggu timbang kedua.',
                               total, None, batas, pernah_selisih_besar)
    if berat_tiket_kg is None:
        return HasilPemeriksaan('tertahan', 'Bobot tiket belum tersedia.',
                               total, None, batas, pernah_selisih_besar)
    bobot = _desimal(berat_tiket_kg, 'Berat tiket')
    if bobot <= 0:
        return HasilPemeriksaan('tertahan', 'Bobot tiket belum sah.',
                               total, None, batas, pernah_selisih_besar)
    selisih = bobot - total
    if not tara_lengkap:
        return HasilPemeriksaan('tertahan', 'Data tara kemasan belum lengkap atau tidak sah.',
                               total, selisih, None, pernah_selisih_besar)
    if abs(selisih) > toleransi:
        return HasilPemeriksaan('perlu_koreksi', 'Selisih melampaui toleransi tara karung.',
                               total, selisih, toleransi, True)
    return HasilPemeriksaan(
        'calon_manual' if pernah_selisih_besar else 'sesuai',
        'Memerlukan verifikasi manual setelah koreksi.' if pernah_selisih_besar
        else 'Bobot sesuai toleransi tara karung.',
        total, selisih, toleransi, pernah_selisih_besar)
