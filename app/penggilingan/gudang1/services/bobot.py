"""Bobot batch SEKARANG, dan seberapa pasti — satu jawaban untuk semua tempat.

QA P6 (21 September 2026) menemukan satu pola di sekitar 14 tempat:

    float(b.berat_total_kg or 0)

"Belum diketahui" diperlakukan sebagai NOL. Nol itu MENOLAK di tempat yang
menuntut > 0 (giling, PK luar masuk Gudang 2 — CHECK berat_positif) dan
MELOLOSKAN di tempat yang menuntut ≤ kapasitas (pengering). Basis datanya
sendiri sudah membedakan keduanya: `CHECK (berat_kg IS NULL OR berat_kg > 0)`
di migrasi 0040 mengizinkan NULL. Kodenya yang tidak.

Jawabannya TIGA keadaan, bukan dua:

  pasti          — nota, netto timbangan, atau diketik (batch manual);
  perkiraan      — truk baru ditimbang bermuatan; bobot = timbang pertama −
                   berat kosong terakhir truk yang SAMA (keputusan pemilik
                   21 September: Pilihan A, "tara cenderung stabil");
  tak diketahui  — belum ditimbang kedua DAN truknya belum pernah punya tara
                   (Pilihan B, cadangan): NULL, bukan nol dan bukan tebakan.

Perkiraan disimpan di `berat_total_kg` juga (dengan `sumber_berat =
'perkiraan'` dan salinannya di `berat_perkiraan_kg`), supaya semua penjumlah
— termasuk SQL — otomatis memakainya, dan poller menggantinya dengan netto
sungguhan lewat jalur yang sama dengan 'menunggu'. Yang membutuhkan
KEPASTIAN — rupiah, verifikasi output giling — membaca `Bobot.pasti`, bukan
angkanya.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

PASTI = "pasti"
PERKIRAAN = "perkiraan"
TAK_DIKETAHUI = "tak_diketahui"

#: Nilai `sumber_berat` pada batch (gabah & PK).
SUMBER_MENUNGGU = "menunggu"
SUMBER_PERKIRAAN = "perkiraan"
#: Sumber yang berarti angkanya PASTI. "manual" diketik orang dari nota di
#: tangannya — bukan tebakan sistem.
SUMBER_PASTI = ("nota", "timbangan", "manual")


def _fmt(kg: float) -> str:
    return f"{float(kg):,.0f}".replace(",", ".")


@dataclass(frozen=True)
class Bobot:
    """Berapa kg SEKARANG, dan seberapa pasti angka itu.

    `kg` None = tak ada satu angka pun yang diketahui. Untuk jumlah beberapa
    batch, `kg` adalah bagian yang DIKETAHUI dan `tak_diketahui` menyebut
    berapa batch yang belum punya angka — supaya layar bisa berkata
    "≥ 11.300 kg · 1 truk belum ditimbang", bukan "11.300 kg".
    """

    kg: float | None
    keadaan: str
    tak_diketahui: int = 0
    #: Untuk PERKIRAAN saja — dari mana angkanya: "tara" (berat kosong
    #: terakhir truk yang sama, tebakan) atau "tiket" (timbang kedua hari
    #: ini yang tiketnya belum ditutup — angka timbangan, bukan tebakan).
    asal: str = ""

    @property
    def pasti(self) -> bool:
        return self.keadaan == PASTI

    @property
    def diketahui(self) -> bool:
        return self.kg is not None

    def angka(self) -> float:
        """Bagian yang diketahui, sebagai angka — untuk jumlah, pagar, dan
        laporan yang memang hanya bisa menjumlahkan apa yang ada. Yang butuh
        kepastian membaca `pasti`, bukan ini."""
        return float(self.kg or 0.0)

    def teks(self) -> str:
        """Kalimat untuk layar. Tak pernah "0 kg" untuk yang belum diketahui:
        angka nol itulah yang membuat semua orang mengira datanya salah."""
        if self.keadaan == PASTI:
            return f"{_fmt(self.angka())} kg"
        if self.keadaan == PERKIRAAN:
            if self.asal == "tiket":
                return f"{_fmt(self.angka())} kg · tiket belum ditutup"
            return f"± {_fmt(self.angka())} kg" + (" (dari tara lama)" if self.asal == "tara" else "")
        if self.kg is None:
            return "menunggu timbang" + (
                f" · {self.tak_diketahui} truk" if self.tak_diketahui > 1 else "")
        n = self.tak_diketahui
        return f"≥ {_fmt(self.kg)} kg · {n} truk belum ditimbang"

    def angka_teks(self) -> str | None:
        """Angka besar kartu (tanpa satuan) — None bila tak ada angkanya."""
        if self.kg is None:
            return None
        if self.keadaan == PASTI:
            return _fmt(self.kg)
        if self.keadaan == PERKIRAAN:
            return f"± {_fmt(self.kg)}"
        return f"≥ {_fmt(self.kg)}"

    def __add__(self, lain: "Bobot") -> "Bobot":
        return jumlah((self, lain))


NOL = Bobot(0.0, PASTI)


def jumlah(items: Iterable[Bobot]) -> Bobot:
    """Jumlah beberapa bobot. Keadaannya yang paling tak pasti di antaranya."""
    kg: float | None = None
    keadaan = PASTI
    tak = 0
    for b in items:
        if b.kg is not None:
            kg = (kg or 0.0) + float(b.kg)
        tak += b.tak_diketahui
        if b.keadaan == TAK_DIKETAHUI:
            keadaan = TAK_DIKETAHUI
        elif b.keadaan == PERKIRAAN and keadaan == PASTI:
            keadaan = PERKIRAAN
    if keadaan == PASTI and kg is None:
        kg = 0.0
    return Bobot(kg, keadaan, tak)


def dari_nilai(berat, sumber_berat: str | None, berat_perkiraan=None) -> Bobot:
    """Dari kolom batch: `berat_total_kg`, `sumber_berat`, dan (untuk membedakan
    dua jenis perkiraan) `berat_perkiraan_kg`.

    Perkiraan yang SAMA dengan `berat_perkiraan_kg` berasal dari tara lama;
    yang berbeda (atau tanpa tara sama sekali) berasal dari timbang kedua hari
    ini pada tiket yang belum ditutup — QA 21 September 2026 (d).
    """
    if berat is None:
        return Bobot(None, TAK_DIKETAHUI, 1)
    if sumber_berat == SUMBER_PERKIRAAN:
        dari_tara = (berat_perkiraan is not None
                     and abs(float(berat) - float(berat_perkiraan)) < 0.005)
        return Bobot(float(berat), PERKIRAAN, asal="tara" if dari_tara else "tiket")
    return Bobot(float(berat), PASTI)


def dari_batch(b) -> Bobot:
    """Bobot sebuah batch gabah / PK luar (atau None → tak diketahui)."""
    if b is None:
        return Bobot(None, TAK_DIKETAHUI, 1)
    return dari_nilai(getattr(b, "berat_total_kg", None), getattr(b, "sumber_berat", None),
                      getattr(b, "berat_perkiraan_kg", None))


def dari_batches(bs: Iterable) -> Bobot:
    return jumlah(dari_batch(b) for b in bs)


#: Umur maksimal tara yang masih boleh dipakai menebak (hari).
#:
#: "Tara cenderung stabil" (pemilik, 21 September 2026) berlaku dari muatan ke
#: muatan, bukan sepanjang tahun: terpal dipasang, bak diganti, alat naik, sopir
#: kedua ikut. Tara dari bulan lalu bukan pengetahuan tentang truk hari ini —
#: dan tebakan yang salah di sini tidak terlihat salah, sebab ia berupa angka
#: yang masuk akal.
UMUR_TARA_HARI = 30

#: Batas kewajaran: muatan tak boleh lebih dari sekian kali tara truknya.
#:
#: Bukan angka teknis melainkan pagar akal sehat. Truk mereka: tara ±3 ton,
#: muatan ±10 ton — rasio 3,3. Trailer besar: tara 9 ton, muatan 30 ton — 3,3
#: juga. Yang keluar jauh di atas itu hampir pasti tara milik kendaraan LAIN
#: (atau salah ketik): QA 24 September 2026 (c) butir 2c menanam tara 1.000 kg
#: pada truk yang sebenarnya 3.000 kg, dan perkiraannya keluar 12.000 kg untuk
#: muatan 10.000 kg — meleset 2 ton KE ATAS, dan kartunya tetap bisa digiling.
#:
#: Yang melampaui batas ini TIDAK ditebak: bobotnya "menunggu timbang"
#: (Pilihan B), sebab angka yang salah lebih mahal daripada angka yang belum ada.
MUATAN_MAKS_X_TARA = 4.0


def perkiraan(timbang1_kg, berat_kosong_kg) -> float | None:
    """Timbang pertama − tara terakhir truk yang sama; None bila tak masuk akal.

    "Tak masuk akal" ada dua: hasilnya nol atau minus (tara lebih berat
    daripada truk bermuatan), dan muatan yang terlalu besar untuk truk
    setara itu (`MUATAN_MAKS_X_TARA`). Umur taranya dijaga di kuerinya
    (`timbang_link.UMUR_TARA_HARI`), sebab hanya kueri yang tahu kapan tara itu
    ditimbang.
    """
    if timbang1_kg is None or berat_kosong_kg is None:
        return None
    tara = float(berat_kosong_kg)
    hasil = float(timbang1_kg) - tara
    if hasil <= 0:
        return None
    if tara > 0 and hasil > MUATAN_MAKS_X_TARA * tara:
        return None
    return hasil


_NOPOL = re.compile(r"[^A-Z0-9]")


def norm_nopol(nopol: str | None) -> str:
    """Nomor polisi yang sama dieja orang dengan spasi berbeda-beda. Huruf
    besar, hanya huruf & angka — "ad 1234 xy" dan "AD1234XY" satu truk."""
    return _NOPOL.sub("", (nopol or "").upper())


#: Bentuk SQL dari `norm_nopol`, dipakai kueri yang mencari tara truk.
SQL_NORM_NOPOL = "regexp_replace(upper(COALESCE({kolom}, '')), '[^A-Z0-9]', '', 'g')"
