"""Satu basis data operasional untuk satu perusahaan, tanpa rute dari payload.

Registry Console boleh berisi banyak perusahaan. Gudang/transaksi di koneksi
ini hanya milik perusahaan yang ditetapkan operator sistem saat penyediaan.
Modul ini tidak mengimpor ORM pada saat import.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from uuid import UUID

KUNCI = 'ruang_data_perusahaan'
PESAN = 'Ruang data perusahaan tidak cocok. Hubungi pengelola sistem.'


class RuangDataTidakCocok(PermissionError):
    pass


@dataclass(frozen=True)
class RuangData:
    company_id: int
    ruang_id: str
    sesi_lama_sampai: int = 0

    def __post_init__(self):
        if type(self.company_id) is not int or not 0 < self.company_id <= 2147483647:
            raise ValueError('HMU_COMPANY_ID wajib berupa ID perusahaan yang sah.')
        if str(UUID(self.ruang_id)) != self.ruang_id:
            raise ValueError('HMU_RUANG_DATA wajib berupa UUID kanonis.')
        if type(self.sesi_lama_sampai) is not int or self.sesi_lama_sampai < 0:
            raise ValueError('Batas sesi lama tidak sah.')

    @classmethod
    def lingkungan(cls, *, wajib=False):
        cid, rid = os.getenv('HMU_COMPANY_ID', ''), os.getenv('HMU_RUANG_DATA', '')
        if not cid and not rid and not wajib:
            return None  # hanya pengembangan/pengujian tanpa perusahaan
        try:
            return cls(int(cid), rid, int(os.getenv('HMU_SESI_LAMA_SAMPAI', '0')))
        except (ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError('Identitas ruang perusahaan belum dikonfigurasi dengan benar.') from exc

    def klaim(self):
        return {'company_id': self.company_id, 'ruang_id': self.ruang_id}

    def menerima(self, data):
        if not isinstance(data, dict):
            return False
        if 'company_id' in data or 'ruang_id' in data:
            return (type(data.get('company_id')) is int and
                    data.get('company_id') == self.company_id and
                    data.get('ruang_id') == self.ruang_id)
        return int(datetime.now(timezone.utc).timestamp()) < self.sesi_lama_sampai

    def cocokkan(self, nilai):
        try:
            data = json.loads(nilai)
            if (type(data['company_id']) is not int or data['company_id'] != self.company_id
                    or data['ruang_id'] != self.ruang_id
                    or data.get('sesi_lama_sampai', 0) != self.sesi_lama_sampai):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise RuangDataTidakCocok(PESAN) from None

    def pastikan_perusahaan(self, company_id):
        if type(company_id) is not int or company_id != self.company_id:
            raise RuangDataTidakCocok('Gudang dan akses operasional perusahaan lain harus dikelola pada ruang datanya sendiri.')


def klaim_sesi():
    ruang = RuangData.lingkungan()
    return ruang.klaim() if ruang else {}


def sesi_sah(data):
    ruang = RuangData.lingkungan()
    return data is not None and (ruang.menerima(data) if ruang else
        not ('company_id' in data or 'ruang_id' in data))


def pasang_pagar(engine, *, wajib=False):
    """Periksa SETIAP transaksi koneksi sebelum SQL aplikasi/pekerja berjalan.

    Tidak memakai ContextVar atau pilihan perusahaan dari request. Koneksi
    raw SQL, ORM, pekerja dan laporan melewati gerbang yang sama. Migrasi
    memiliki engine tersendiri dan dijalankan sebelum aplikasi dinyalakan.
    """
    from sqlalchemy import event, text
    ruang = RuangData.lingkungan(wajib=wajib)
    if ruang is None:
        return

    @event.listens_for(engine.sync_engine, 'begin')
    def periksa(conn):
        nilai = conn.execute(text('SELECT nilai FROM setelan_pabrik WHERE kunci=:k'), {'k': KUNCI}).scalar_one_or_none()
        ruang.cocokkan(nilai)


def pastikan_perusahaan(company_id):
    ruang = RuangData.lingkungan()
    if ruang:
        ruang.pastikan_perusahaan(company_id)


def header_integrasi():
    ruang = RuangData.lingkungan()
    return ({'X-HMU-Company': str(ruang.company_id), 'X-HMU-Ruang': ruang.ruang_id} if ruang else {})


def integrasi_sah(headers):
    ruang = RuangData.lingkungan()
    cid, rid = headers.get('x-hmu-company'), headers.get('x-hmu-ruang')
    if ruang is None:
        return cid is None and rid is None
    if cid is None and rid is None:
        # Token layanan lama HMU tetap bekerja; perusahaan baru wajib header.
        # Kredensial layanan tetap diperiksa oleh endpoint pemanggil.
        return ruang.sesi_lama_sampai > 0
    return cid == str(ruang.company_id) and rid == ruang.ruang_id
