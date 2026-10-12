"""Kontrak proses operasional bersama untuk Produksi dan Timbangan.

Ini adalah model data lintas aplikasi (nilai/API), bukan tabel super yang
menggantikan tabel rinci proses. Masing-masing proses tetap menyimpan data
khususnya di domain asal; kontrak ini menyamakan identitas, status, pemilik,
pelaksana, waktu, serta arus bahan/hasil ketika data dipertukarkan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from hmu_core.komoditas import Kemasan, Produk


class JenisProses(str, Enum):
    PENERIMAAN = "penerimaan"
    PENGERINGAN = "pengeringan"
    PENDINGINAN = "pendinginan"
    PENGGILINGAN = "penggilingan"
    TRANSFER = "transfer"
    PENYOSOHAN = "penyosohan"
    PEMINDAHAN_SILO = "pemindahan_silo"
    PENGEMASAN = "pengemasan"
    BARANG_KELUAR = "barang_keluar"
    PENGOLAHAN_ULANG = "pengolahan_ulang"
    PERPINDAHAN_KEPEMILIKAN = "perpindahan_kepemilikan"
    PENIMBANGAN = "penimbangan"
    INSPEKSI_MUTU = "inspeksi_mutu"
    PEMELIHARAAN_MESIN = "pemeliharaan_mesin"


class StatusProses(str, Enum):
    MENUNGGU = "menunggu"
    BERJALAN = "berjalan"
    DIHENTIKAN = "dihentikan"
    SELESAI = "selesai"
    DIBATALKAN = "dibatalkan"


class JenisPemilik(str, Enum):
    PABRIK = "pabrik"
    JASA = "jasa"
    SUPPLIER = "supplier"
    PELANGGAN = "pelanggan"


@dataclass(frozen=True)
class PemilikProses:
    jenis: JenisPemilik
    id: int | None = None
    nama: str | None = None

    def __post_init__(self) -> None:
        if self.jenis is JenisPemilik.PABRIK and self.id is not None:
            raise ValueError("Pemilik pabrik tidak memakai id pihak")
        if self.jenis is not JenisPemilik.PABRIK and self.id is None:
            raise ValueError("Pemilik selain pabrik harus memiliki id")


@dataclass(frozen=True)
class ArusProses:
    """Satu baris bahan masuk atau hasil keluar proses."""

    produk: Produk
    berat_kg: Decimal
    referensi: str | None = None
    lokasi_id: int | None = None

    def __post_init__(self) -> None:
        if self.berat_kg < 0:
            raise ValueError("Berat arus proses tidak boleh negatif")

    def ke_dict(self) -> dict:
        kemasan = self.produk.kemasan
        return {
            "produk": {
                "komoditas": self.produk.komoditas,
                "atribut": dict(self.produk.atribut),
                "merek_produk": self.produk.merek_produk,
                "kemasan": ({
                    "jenis_karung": kemasan.jenis_karung,
                    "ukuran_kg": kemasan.ukuran_kg,
                    "tara_per_karung_kg": kemasan.tara_per_karung_kg,
                    "merek_karung": kemasan.merek_karung,
                } if kemasan else None),
            },
            "berat_kg": str(self.berat_kg),
            "referensi": self.referensi,
            "lokasi_id": self.lokasi_id,
        }

    @classmethod
    def dari_dict(cls, data: dict) -> "ArusProses":
        p = data["produk"]
        kemasan = p.get("kemasan")
        return cls(
            produk=Produk(
                komoditas=p["komoditas"], atribut=p.get("atribut", {}),
                merek_produk=p.get("merek_produk"),
                kemasan=Kemasan(**kemasan) if kemasan else None,
            ),
            berat_kg=Decimal(str(data["berat_kg"])),
            referensi=data.get("referensi"), lokasi_id=data.get("lokasi_id"),
        )


@dataclass(frozen=True)
class ProsesOperasional:
    """Representasi umum sebuah proses tanpa menghapus detail domain asal."""

    aplikasi: str
    id: int | str
    kode: str
    jenis: JenisProses
    status: StatusProses
    pemilik: PemilikProses
    waktu_mulai: datetime | None = None
    waktu_selesai: datetime | None = None
    pelaksana_id: int | None = None
    bahan: tuple[ArusProses, ...] = field(default_factory=tuple)
    hasil: tuple[ArusProses, ...] = field(default_factory=tuple)
    referensi_asal: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.aplikasi.strip() or not self.kode.strip():
            raise ValueError("Aplikasi dan kode proses wajib diisi")
        if (self.waktu_mulai is not None and self.waktu_selesai is not None
                and self.waktu_selesai < self.waktu_mulai):
            raise ValueError("Waktu selesai tidak boleh sebelum waktu mulai")

    def ke_dict(self) -> dict:
        """Bentuk stabil untuk API antar aplikasi (enum dan waktu jadi teks)."""
        return {
            "aplikasi": self.aplikasi,
            "id": self.id,
            "kode": self.kode,
            "jenis": self.jenis.value,
            "status": self.status.value,
            "pemilik": {"jenis": self.pemilik.jenis.value,
                        "id": self.pemilik.id, "nama": self.pemilik.nama},
            "waktu_mulai": self.waktu_mulai.isoformat() if self.waktu_mulai else None,
            "waktu_selesai": self.waktu_selesai.isoformat() if self.waktu_selesai else None,
            "pelaksana_id": self.pelaksana_id,
            "bahan": [arus.ke_dict() for arus in self.bahan],
            "hasil": [arus.ke_dict() for arus in self.hasil],
            "referensi_asal": list(self.referensi_asal),
        }

    @classmethod
    def dari_dict(cls, data: dict) -> "ProsesOperasional":
        """Baca kontrak yang sama dari payload aplikasi lain."""
        pemilik = data["pemilik"]
        return cls(
            aplikasi=data["aplikasi"], id=data["id"], kode=data["kode"],
            jenis=JenisProses(data["jenis"]), status=StatusProses(data["status"]),
            pemilik=PemilikProses(
                jenis=JenisPemilik(pemilik["jenis"]), id=pemilik.get("id"),
                nama=pemilik.get("nama"),
            ),
            waktu_mulai=(datetime.fromisoformat(data["waktu_mulai"])
                         if data.get("waktu_mulai") else None),
            waktu_selesai=(datetime.fromisoformat(data["waktu_selesai"])
                           if data.get("waktu_selesai") else None),
            pelaksana_id=data.get("pelaksana_id"),
            bahan=tuple(ArusProses.dari_dict(x) for x in data.get("bahan", ())),
            hasil=tuple(ArusProses.dari_dict(x) for x in data.get("hasil", ())),
            referensi_asal=tuple(data.get("referensi_asal", ())),
        )
