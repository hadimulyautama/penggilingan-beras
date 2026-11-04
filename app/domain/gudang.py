"""Identitas gudang dan buku bagian PK yang masih bebas.

Pemilik berbeda dapat memiliki bagian dari satu sumber fisik. Mengganti
pemilik tidak mengubah proses asal, tiket timbang, lokasi, atau total fisik.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


class PersediaanError(ValueError):
    pass


def kg(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise PersediaanError('Bobot tidak sah.') from exc
    if not result.is_finite() or result < 0 or result != result.quantize(Decimal('.01')):
        raise PersediaanError('Bobot harus positif atau nol, maksimal dua desimal kg.')
    return result


@dataclass(frozen=True, slots=True)
class Gudang:
    id: int
    nama: str
    aktif: bool = True

    def __post_init__(self):
        if isinstance(self.id,bool) or not isinstance(self.id,int) or self.id<=0 or not self.nama.strip():
            raise PersediaanError('Gudang harus mempunyai ID tersimpan dan nama yang sah.')

    @classmethod
    def dari_model(cls, model):
        return cls(id=model.id, nama=model.nama_gudang, aktif=model.aktif)

    def pastikan_aktif(self):
        if not self.aktif:
            raise PersediaanError('Gudang tidak aktif; pengalihan tidak dapat dicatat.')

    async def persediaan_pk(self, db):
        from app.services.pk_persediaan import baca
        return await baca(db, warehouse_id=self.id)

    def tempatkan_pk(self, sumber: str, pemilik_id: int | None, berat_kg,
                     *, bebas: bool = True) -> StokPK:
        self.pastikan_aktif()
        nilai = Decimal(str(berat_kg))
        if not nilai.is_finite() or nilai < 0:
            raise PersediaanError("Saldo awal PK tidak sah.")
        return StokPK(self, sumber, [BagianPK(pemilik_id, nilai, 0)], bebas)


@dataclass(slots=True)
class BagianPK:
    pemilik_id: int | None
    berat_kg: Decimal
    transaksi_id: int = 0


@dataclass(slots=True)
class StokPK:
    gudang: Gudang
    sumber: str
    bagian: list[BagianPK] = field(default_factory=list)
    bebas: bool = True

    @property
    def fisik_kg(self):
        return sum((b.berat_kg for b in self.bagian), Decimal(0))

    def saldo(self, pemilik_id, *, transaksi_id=None):
        return sum((b.berat_kg for b in self.bagian
                    if b.pemilik_id == pemilik_id
                    and (transaksi_id is None or b.transaksi_id == transaksi_id)), Decimal(0))

    def ambil(self, pemilik_id, berat_kg, *, transaksi_id=None):
        jumlah = Decimal(str(berat_kg))
        if not jumlah.is_finite() or jumlah <= 0:
            raise PersediaanError('Bobot harus lebih dari nol.')
        if jumlah > self.saldo(pemilik_id, transaksi_id=transaksi_id):
            raise PersediaanError('Bagian bebas sumber PK tidak mencukupi; bagian yang sudah dipakai tidak dapat diambil kembali.')
        sisa = jumlah
        for b in self.bagian:
            if b.pemilik_id != pemilik_id or transaksi_id is not None and b.transaksi_id != transaksi_id:
                continue
            ambil = min(b.berat_kg, sisa)
            b.berat_kg -= ambil
            sisa -= ambil
            if not sisa:
                break

    def alihkan(self, dari_id, ke_id, berat_kg, *, transaksi_id: int,
                sumber_transaksi_id=None, _historis=False):
        if not _historis:
            self.gudang.pastikan_aktif()
        if not self.bebas and not _historis:
            raise PersediaanError('PK di silo atau proses tidak dapat dialihkan kepemilikannya.')
        if dari_id == ke_id:
            raise PersediaanError('Pilih pemilik tujuan yang berbeda.')
        # Alur yang diizinkan: pabrik ↔ jasa. Jasa → jasa bukan penggabungan
        # administratif dan memerlukan aturan bisnis tersendiri.
        if dari_id is not None and ke_id is not None:
            raise PersediaanError('Pengalihan PK hanya antara pabrik dan pemilik jasa.')
        fisik = self.fisik_kg
        jumlah = kg(berat_kg)
        self.ambil(dari_id, jumlah, transaksi_id=sumber_transaksi_id)
        self.bagian.append(BagianPK(ke_id, jumlah, transaksi_id))
        assert self.fisik_kg == fisik
