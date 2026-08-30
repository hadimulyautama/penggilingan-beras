"""Logika bisnis MURNI modul Timbangan — tanpa DB, tanpa framework.

Seluruh rumus kontrol perusahaan ada di sini dan HANYA di sini, sehingga bisa
diuji terpisah dan dipakai ulang saat modul disambungkan ke agen AI.

LINGKUP: modul ini MURNI TIMBANGAN. Tidak ada harga, nilai transaksi, maupun
potongan mutu di mana pun — semuanya milik pembelian & keuangan. Operator pos
timbang tidak boleh mengetahui harga.

RUMUS INTI (sama untuk semua arah, hanya urutan timbang yang terbalik)

    Netto Timbangan = berat bermuatan - berat kosong
    Total Tara      = SUM(jumlah karung x tara per karung) + tara lain
    Berat Barang    = Netto Timbangan - Total Tara
    Selisih         = Berat Barang - Berat Acuan (nota / surat jalan)

Yang membedakan komoditas hanyalah ATURAN-nya (tara, jenis ambang, arah
ambang), dan aturan itu hidup sebagai data di master jenis timbang — bukan
sebagai cabang if di dalam kode.

Rujukan: SOP Internal Kontrol Pembelian Gabah, Sistem Tara & Pembelian Beras
PK, dan arahan Direksi 25 Agustus 2026 (gabah kering, barang keluar, jasa
timbang). Lihat docs/timbangan/RANCANGAN.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import pstdev

# ─────────────────────────── Konstanta ───────────────────────────
from app.timbangan import format as fmt

#: Kapasitas jembatan timbang perusahaan. Di atas ini angka mustahil.
KAPASITAS_JEMBATAN_KG = 20_000.0

#: Pembulatan tera: pembacaan selalu kelipatan 10 kg.
KELIPATAN_TERA_KG = 10.0

# Arah pergerakan barang
MASUK = "MASUK"
KELUAR = "KELUAR"
BEBAS = "BEBAS"

# Dari mana tara per karung berasal
TARA_TETAP = "TETAP"          # angka pasti per komoditas (gabah 0,25)
TARA_SAMPLING = "SAMPLING"    # hasil sampling per pihak x komoditas (PK)
TARA_MANUAL = "MANUAL"        # diisi operator, bawaan 0 (jasa timbang)

# Bagaimana batas wajar dihitung
AMBANG_PER_TON = "PER_TON"        # sekian kg per ton berat acuan
AMBANG_PER_KARUNG = "PER_KARUNG"  # sekian kg per karung
AMBANG_TETAP = "TETAP"            # angka kg tetap
AMBANG_TIDAK_ADA = "TIDAK_ADA"    # jasa timbang

# Sisi mana yang dipersoalkan
ARAH_SIMETRIS = "SIMETRIS"                    # kurang & lebih sama-sama diperiksa
ARAH_KURANG_SAJA = "KURANG_SAJA"              # kelebihan dibiarkan (gabah kering, PK)
ARAH_TIDAK_BOLEH_KURANG = "TIDAK_BOLEH_KURANG"  # barang keluar

# Acuan pembanding
ACUAN_NOTA = "NOTA"
ACUAN_SURAT_JALAN = "SURAT_JALAN"
ACUAN_TIDAK_ADA = "TIDAK_ADA"

# Status kontrol
NORMAL = "NORMAL"
PERLU_PEMERIKSAAN = "PERLU_PEMERIKSAAN"
INVESTIGASI = "INVESTIGASI"
KURANG = "KURANG"              # barang keluar: di bawah surat jalan
KELEBIHAN = "KELEBIHAN"        # barang keluar: di atas batas wajar
TANPA_KONTROL = "TANPA_KONTROL"  # jasa timbang

STATUS_LABEL = {
    NORMAL: "NORMAL",
    PERLU_PEMERIKSAAN: "PERLU PEMERIKSAAN",
    INVESTIGASI: "INVESTIGASI",
    KURANG: "KURANG DARI SURAT JALAN",
    KELEBIHAN: "KELEBIHAN MUATAN",
    TANPA_KONTROL: "JASA TIMBANG",
}

#: Status yang mewajibkan lembar pemeriksaan SOP dibuka.
STATUS_WAJIB_PERIKSA = {PERLU_PEMERIKSAAN, INVESTIGASI, KELEBIHAN}


class ValidasiError(ValueError):
    """Angka timbangan tidak masuk akal secara fisik."""


# ─────────────────────────── Aturan per jenis ───────────────────────────

@dataclass(frozen=True)
class AturanJenis:
    """Aturan kontrol satu komoditas — salinan baris master jenis timbang.

    Disalin ke setiap transaksi saat disimpan, sehingga revisi aturan di
    kemudian hari tidak pernah mengubah status transaksi lama.
    """

    kode: str
    nama: str
    arah: str                      # MASUK / KELUAR / BEBAS
    acuan: str                     # ACUAN_*
    sumber_tara: str               # TARA_*
    tara_tetap_kg: float = 0.0     # dipakai bila sumber_tara = TETAP
    tara_bawaan_kg: float = 0.0    # dipakai bila SAMPLING tapi belum disampling
    ambang_jenis: str = AMBANG_TIDAK_ADA
    ambang_nilai: float = 0.0
    ambang_arah: str = ARAH_SIMETRIS
    ambang_investigasi_nilai: float | None = None
    rahasia: bool = True           # hasil kontrol tidak keluar ke pihak lawan
    cetak_bukti: bool = False      # bukti timbang diserahkan ke pihak lawan
    masa_berlaku_tara_hari: int = 90

    def tara_default(self) -> float:
        """Tara yang dipakai bila tidak ada tara standar untuk pihak ini."""
        if self.sumber_tara == TARA_TETAP:
            return self.tara_tetap_kg
        if self.sumber_tara == TARA_SAMPLING:
            return self.tara_bawaan_kg
        return 0.0


#: Isi awal master jenis timbang. Nilai-nilai ini bisa diubah lewat master
#: tanpa menyentuh kode — didefinisikan di sini hanya sebagai bibit seed.
JENIS_AWAL: tuple[AturanJenis, ...] = (
    AturanJenis(
        kode="GABAH_BASAH", nama="Gabah Basah", arah=MASUK, acuan=ACUAN_NOTA,
        sumber_tara=TARA_TETAP, tara_tetap_kg=0.25,
        ambang_jenis=AMBANG_PER_TON, ambang_nilai=2.0,
        ambang_arah=ARAH_SIMETRIS, ambang_investigasi_nilai=5.0,
        rahasia=True, cetak_bukti=True,
    ),
    AturanJenis(
        # Batas PROPORSIONAL 0,5 kg per ton — ditegaskan Direksi 30 Agustus
        # 2026 setelah ditimbang ulang terhadap alternatif 5 kg tetap.
        #
        # Konsekuensinya diukur, bukan dikira: simulasi 200.000 transaksi jujur
        # memberi ~13% tetap ditandai perlu diperiksa. Penyebabnya bukan aturan
        # ini, melainkan alat — pembacaan dibulatkan ke kelipatan 10 kg pada
        # DUA kali penimbangan, sehingga netto punya galat bawaan. Batas 5 kg
        # tetap menghasilkan angka yang praktis sama (~12%), jadi pilihan
        # antara keduanya tidak menentukan. Yang menurunkannya secara berarti
        # hanya menaikkan batas: 1,0 kg/ton → ~1%.
        kode="GABAH_KERING", nama="Gabah Kering", arah=MASUK, acuan=ACUAN_NOTA,
        sumber_tara=TARA_TETAP, tara_tetap_kg=0.25,
        ambang_jenis=AMBANG_PER_TON, ambang_nilai=0.5,
        ambang_arah=ARAH_KURANG_SAJA,
        rahasia=True, cetak_bukti=True,
    ),
    AturanJenis(
        kode="BERAS_PK", nama="Beras PK", arah=MASUK, acuan=ACUAN_NOTA,
        sumber_tara=TARA_SAMPLING, tara_bawaan_kg=0.1,
        ambang_jenis=AMBANG_PER_KARUNG, ambang_nilai=0.05,
        ambang_arah=ARAH_KURANG_SAJA,
        rahasia=False, cetak_bukti=True,
    ),
    AturanJenis(
        kode="BROKEN_MASUK", nama="Broken", arah=MASUK, acuan=ACUAN_NOTA,
        sumber_tara=TARA_TETAP, tara_tetap_kg=0.07,
        ambang_jenis=AMBANG_PER_KARUNG, ambang_nilai=0.05,
        ambang_arah=ARAH_KURANG_SAJA,
        rahasia=False, cetak_bukti=True,
    ),
    # Beras masuk mengikuti aturan beras PK — ditetapkan Direksi 30 Agustus
    # 2026. Keduanya sengaja identik di kedua belas kolomnya, termasuk nota
    # yang diberikan kepada pengirim beserta angka selisihnya.
    AturanJenis(
        kode="BERAS_MASUK", nama="Beras", arah=MASUK, acuan=ACUAN_NOTA,
        sumber_tara=TARA_SAMPLING, tara_bawaan_kg=0.1,
        ambang_jenis=AMBANG_PER_KARUNG, ambang_nilai=0.05,
        ambang_arah=ARAH_KURANG_SAJA,
        rahasia=False, cetak_bukti=True,
    ),
    AturanJenis(
        kode="BERAS", nama="Beras", arah=KELUAR, acuan=ACUAN_SURAT_JALAN,
        sumber_tara=TARA_TETAP, tara_tetap_kg=0.05,
        ambang_jenis=AMBANG_PER_KARUNG, ambang_nilai=0.07,
        ambang_arah=ARAH_TIDAK_BOLEH_KURANG,
        rahasia=True, cetak_bukti=True,
    ),
    AturanJenis(
        kode="BROKEN", nama="Broken", arah=KELUAR, acuan=ACUAN_SURAT_JALAN,
        sumber_tara=TARA_TETAP, tara_tetap_kg=0.07,
        ambang_jenis=AMBANG_PER_KARUNG, ambang_nilai=0.07,
        ambang_arah=ARAH_TIDAK_BOLEH_KURANG,
        rahasia=True, cetak_bukti=True,
    ),
    AturanJenis(
        kode="MENIR", nama="Menir", arah=KELUAR, acuan=ACUAN_SURAT_JALAN,
        sumber_tara=TARA_TETAP, tara_tetap_kg=0.05,
        ambang_jenis=AMBANG_PER_KARUNG, ambang_nilai=0.07,
        ambang_arah=ARAH_TIDAK_BOLEH_KURANG,
        rahasia=True, cetak_bukti=True,
    ),
    AturanJenis(
        kode="BEKATUL", nama="Bekatul", arah=KELUAR, acuan=ACUAN_SURAT_JALAN,
        sumber_tara=TARA_TETAP, tara_tetap_kg=0.05,
        ambang_jenis=AMBANG_PER_KARUNG, ambang_nilai=0.07,
        ambang_arah=ARAH_TIDAK_BOLEH_KURANG,
        rahasia=True, cetak_bukti=True,
    ),
    AturanJenis(
        kode="REJECT", nama="Reject", arah=KELUAR, acuan=ACUAN_SURAT_JALAN,
        sumber_tara=TARA_TETAP, tara_tetap_kg=0.05,
        ambang_jenis=AMBANG_PER_KARUNG, ambang_nilai=0.07,
        ambang_arah=ARAH_TIDAK_BOLEH_KURANG,
        rahasia=True, cetak_bukti=True,
    ),
    AturanJenis(
        kode="BEBAS", nama="Timbang Bebas", arah=BEBAS, acuan=ACUAN_TIDAK_ADA,
        sumber_tara=TARA_MANUAL,
        ambang_jenis=AMBANG_TIDAK_ADA,
        rahasia=False, cetak_bukti=True,
    ),
)

JENIS_PETA: dict[str, AturanJenis] = {j.kode: j for j in JENIS_AWAL}


# ─────────────────────────── Masukan ───────────────────────────

@dataclass
class BarisMuatan:
    """Satu baris muatan. Barang masuk selalu satu baris; pengiriman bisa
    beberapa, masing-masing dengan tara dan surat jalannya sendiri."""

    jenis_kode: str
    jumlah_karung: int = 0
    tara_per_karung_kg: float = 0.0
    berat_acuan_kg: float = 0.0      # berat nota / surat jalan
    nomor_acuan: str | None = None

    @property
    def tara_kg(self) -> float:
        return round(self.jumlah_karung * self.tara_per_karung_kg, 4)


# ─────────────────────────── Hasil ───────────────────────────

@dataclass(frozen=True)
class Hasil:
    """Seluruh angka turunan satu transaksi timbang."""

    berat_bermuatan_kg: float
    berat_kosong_kg: float
    netto_timbangan_kg: float
    jumlah_karung: int
    total_tara_kg: float
    berat_barang_kg: float
    berat_acuan_kg: float
    selisih_kg: float
    selisih_persen: float
    batas_bawah_kg: float | None     # None = tidak dibatasi di sisi itu
    batas_atas_kg: float | None
    status: str
    keterangan: str

    @property
    def status_label(self) -> str:
        return STATUS_LABEL[self.status]

    @property
    def wajib_diperiksa(self) -> bool:
        return self.status in STATUS_WAJIB_PERIKSA

    def as_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["status_label"] = self.status_label
        d["wajib_diperiksa"] = self.wajib_diperiksa
        return d


def _r(nilai: float, digit: int = 3) -> float:
    """Bulatkan HANYA untuk menghilangkan galat biner float."""
    return round(float(nilai), digit)


# ─────────────────────────── Perhitungan ───────────────────────────

def hitung(
    *,
    aturan: AturanJenis,
    berat_bermuatan_kg: float,
    berat_kosong_kg: float | None = None,
    muatan: list[BarisMuatan] | None = None,
    tara_lain_kg: float = 0.0,
    kapasitas_kg: float | None = None,
) -> Hasil:
    """Hitung seluruh angka turunan satu transaksi.

    `berat_kosong_kg` boleh None pada jasa timbang sekali — netto sama dengan
    berat yang tertimbang, dan tidak ada kontrol apa pun.

    Angka timbangan disimpan APA ADANYA. Sistem tidak pernah membulatkan;
    pembulatan tera sudah dikerjakan timbangan resmi sebelum angka diketik.
    """
    bermuatan = float(berat_bermuatan_kg)
    kosong = float(berat_kosong_kg) if berat_kosong_kg is not None else 0.0
    baris = list(muatan or [])

    if bermuatan <= 0:
        raise ValidasiError("Berat timbang harus lebih dari 0 kg.")
    # Dibaca saat dipanggil, bukan saat fungsi didefinisikan — supaya
    # config.py bisa menyetel kapasitas alat dari environment.
    kapasitas_kg = KAPASITAS_JEMBATAN_KG if kapasitas_kg is None else kapasitas_kg
    if bermuatan > kapasitas_kg:
        raise ValidasiError(
            f"Melebihi kapasitas jembatan timbang "
            f"({kapasitas_kg:.0f} kg) — angka ini tidak mungkin."
        )
    if berat_kosong_kg is not None:
        if kosong <= 0:
            raise ValidasiError("Berat truk kosong harus lebih dari 0 kg.")
        if kosong >= bermuatan:
            raise ValidasiError(
                "Berat truk kosong harus lebih kecil daripada berat bermuatan."
            )

    netto = bermuatan - kosong
    karung = sum(b.jumlah_karung for b in baris)
    total_tara = sum(b.tara_kg for b in baris) + float(tara_lain_kg or 0)
    barang = netto - total_tara
    if barang < 0:
        raise ValidasiError("Tara lebih besar daripada netto timbangan.")

    acuan = sum(b.berat_acuan_kg for b in baris)
    selisih = barang - acuan if aturan.acuan != ACUAN_TIDAK_ADA else 0.0
    persen = (selisih / acuan * 100.0) if acuan else 0.0

    batas = _batas(aturan, acuan_kg=acuan, jumlah_karung=karung)
    batas_inv = _batas_investigasi(aturan, acuan_kg=acuan, jumlah_karung=karung)
    bawah, atas, status, keterangan = _status(aturan, selisih, batas, batas_inv)

    return Hasil(
        berat_bermuatan_kg=_r(bermuatan),
        berat_kosong_kg=_r(kosong),
        netto_timbangan_kg=_r(netto),
        jumlah_karung=karung,
        total_tara_kg=_r(total_tara),
        berat_barang_kg=_r(barang),
        berat_acuan_kg=_r(acuan),
        selisih_kg=_r(selisih),
        selisih_persen=round(persen, 4),
        batas_bawah_kg=None if bawah is None else _r(bawah, 2),
        batas_atas_kg=None if atas is None else _r(atas, 2),
        status=status,
        keterangan=keterangan,
    )


def _batas(aturan: AturanJenis, *, acuan_kg: float, jumlah_karung: int) -> float:
    """Lebar batas wajar dalam kg, dihitung dari aturan jenis."""
    if aturan.ambang_jenis == AMBANG_PER_TON:
        return acuan_kg / 1000.0 * aturan.ambang_nilai
    if aturan.ambang_jenis == AMBANG_PER_KARUNG:
        return jumlah_karung * aturan.ambang_nilai
    if aturan.ambang_jenis == AMBANG_TETAP:
        return aturan.ambang_nilai
    return 0.0


def _batas_investigasi(aturan: AturanJenis, *, acuan_kg: float,
                       jumlah_karung: int) -> float | None:
    if aturan.ambang_investigasi_nilai is None:
        return None
    if aturan.ambang_jenis == AMBANG_PER_TON:
        return acuan_kg / 1000.0 * aturan.ambang_investigasi_nilai
    if aturan.ambang_jenis == AMBANG_PER_KARUNG:
        return jumlah_karung * aturan.ambang_investigasi_nilai
    return aturan.ambang_investigasi_nilai


def _status(aturan: AturanJenis, selisih: float, batas: float,
            batas_investigasi: float | None
            ) -> tuple[float | None, float | None, str, str]:
    """(batas bawah, batas atas, status, keterangan)."""
    if aturan.ambang_jenis == AMBANG_TIDAK_ADA or aturan.acuan == ACUAN_TIDAK_ADA:
        return None, None, TANPA_KONTROL, "Jasa timbang — tidak ada pembanding."

    kurang = max(0.0, -selisih)

    if aturan.ambang_arah == ARAH_TIDAK_BOLEH_KURANG:
        if selisih < 0:
            return 0.0, batas, KURANG, (
                f"Kurang {fmt.angka(kurang, 1)} kg dari surat jalan — tambah muatan, "
                "atau tutup paksa dengan alasan."
            )
        if selisih > batas:
            return 0.0, batas, KELEBIHAN, (
                f"Lebih {fmt.angka(selisih, 1)} kg, di atas batas "
                f"{fmt.angka(batas, 1)} kg."
            )
        return 0.0, batas, NORMAL, "Dalam batas kelebihan yang wajar."

    if aturan.ambang_arah == ARAH_KURANG_SAJA:
        if kurang > batas:
            return -batas, None, PERLU_PEMERIKSAAN, (
                f"Kekurangan {fmt.angka(kurang, 1)} kg melewati batas "
                f"{fmt.angka(batas, 1)} kg."
            )
        return -batas, None, NORMAL, (
            "Kekurangan masih dalam batas kewajaran; kelebihan diperbolehkan."
        )

    # ARAH_SIMETRIS — kurang dan lebih sama-sama diperiksa
    abs_selisih = abs(selisih)
    if batas_investigasi is not None and abs_selisih > batas_investigasi:
        return -batas, batas, INVESTIGASI, (
            f"Selisih {fmt.angka(abs_selisih, 1)} kg melewati batas investigasi "
            f"{fmt.angka(batas_investigasi, 1)} kg."
        )
    if abs_selisih > batas:
        return -batas, batas, PERLU_PEMERIKSAAN, (
            f"Selisih {fmt.angka(abs_selisih, 1)} kg melewati batas "
            f"{fmt.angka(batas, 1)} kg."
        )
    return -batas, batas, NORMAL, "Masih dalam batas kewajaran."


def catatan_tera(berat_kg: float) -> str | None:
    """Info (bukan blokir) bila angka bukan kelipatan 10 kg.

    Timbangan truk bertera membulatkan ke kelipatan 10; angka di luar itu
    biasanya salah salin. Sistem tidak pernah membulatkan sendiri.
    """
    if berat_kg and float(berat_kg) % KELIPATAN_TERA_KG != 0:
        return (
            "Bukan kelipatan 10 kg — pastikan angka disalin apa adanya dari "
            "display timbangan; sistem tidak membulatkan."
        )
    return None


def galat_tera_maksimum_kg() -> float:
    """Galat terbesar pada netto akibat pembulatan tera dua kali pembacaan."""
    return KELIPATAN_TERA_KG


# ─────────────────────────── Ringkasan untuk analisis ───────────────────────────

@dataclass
class TransaksiRingkas:
    """Bentuk minimal satu transaksi untuk deteksi pola & skor supplier."""

    tanggal: date
    selisih_kg: float
    selisih_persen: float = 0.0
    batas_kg: float = 0.0
    berat_barang_kg: float = 0.0
    berat_acuan_kg: float = 0.0
    nomor_polisi: str | None = None
    pihak_id: int | None = None
    pihak_nama: str = ""
    dikoreksi: bool = False
    kode: str = ""

    @property
    def melewati_batas(self) -> bool:
        return abs(self.selisih_kg) > self.batas_kg > 0


# ─────────────────────────── Deteksi pola ───────────────────────────

# NEEDS CONFIRMATION: ambang pola berikut usulan penyusun.
MIN_TRANSAKSI_POLA = 3
JENDELA_POLA = 5
RASIO_ARAH_SAMA = 0.8
RASIO_SERING_LEWAT = 0.4
MIN_TRANSAKSI_KENDARAAN = 3
MIN_TRANSAKSI_BULAN = 3

TINGKAT_INFO = "INFO"
TINGKAT_PERHATIAN = "PERHATIAN"
TINGKAT_TINGGI = "TINGGI"


@dataclass
class Pola:
    kode: str
    judul: str
    keterangan: str
    tingkat: str = TINGKAT_PERHATIAN
    data: dict = field(default_factory=dict)


def deteksi_pola(transaksi: list[TransaksiRingkas]) -> list[Pola]:
    """Cari pola berulang. Bahasa keluaran selalu netral: yang dilaporkan
    adalah POLA ANGKA, bukan penilaian atas niat pihak lawan."""
    aktif = [t for t in transaksi if t.selisih_kg is not None]
    n = len(aktif)
    if n < MIN_TRANSAKSI_POLA:
        return []

    urut = sorted(aktif, key=lambda t: t.tanggal)
    terakhir = urut[-JENDELA_POLA:]
    m = len(terakhir)
    rata_abs = sum(abs(t.selisih_kg) for t in terakhir) / m
    pola: list[Pola] = []

    negatif = [t for t in terakhir if t.selisih_kg < 0]
    positif = [t for t in terakhir if t.selisih_kg > 0]
    lewat = [t for t in urut if t.melewati_batas]

    if len(negatif) / m >= RASIO_ARAH_SAMA and any(t.melewati_batas for t in terakhir):
        pola.append(Pola(
            kode="POLA_SELISIH_NEGATIF_BERULANG",
            judul="POLA SELISIH NEGATIF BERULANG",
            keterangan=(
                f"{len(negatif)} dari {m} transaksi terakhir menghasilkan berat "
                f"di bawah dokumen, rata-rata {rata_abs:.1f} kg. Perlu diperiksa "
                "bersama pihak lawan — cara timbang di lokasi asal, susut "
                "perjalanan, atau tara karung."
            ),
            tingkat=TINGKAT_TINGGI if len(lewat) / n >= RASIO_SERING_LEWAT
            else TINGKAT_PERHATIAN,
            data={"jumlah": len(negatif), "dari": m, "rata_abs_kg": round(rata_abs, 2)},
        ))

    if len(positif) / m >= RASIO_ARAH_SAMA and any(t.melewati_batas for t in terakhir):
        pola.append(Pola(
            kode="POLA_SELISIH_POSITIF_BERULANG",
            judul="POLA SELISIH POSITIF BERULANG",
            keterangan=(
                f"{len(positif)} dari {m} transaksi terakhir menghasilkan berat "
                f"di atas dokumen, rata-rata {rata_abs:.1f} kg. Perlu diperiksa "
                "— kemungkinan salah catat dokumen atau kalibrasi."
            ),
            data={"jumlah": len(positif), "dari": m, "rata_abs_kg": round(rata_abs, 2)},
        ))

    if lewat and len(lewat) / n >= RASIO_SERING_LEWAT:
        pola.append(Pola(
            kode="SERING_MELEWATI_BATAS",
            judul="SERING MELEWATI BATAS",
            keterangan=(
                f"{len(lewat)} dari {n} transaksi melewati batas wajar "
                f"({len(lewat) / n * 100:.0f}%)."
            ),
            data={"jumlah": len(lewat), "dari": n},
        ))

    per_kendaraan: dict[str, list[TransaksiRingkas]] = {}
    for t in urut:
        if t.nomor_polisi:
            per_kendaraan.setdefault(t.nomor_polisi, []).append(t)
    for nopol, daftar in sorted(per_kendaraan.items()):
        if len(daftar) < MIN_TRANSAKSI_KENDARAAN:
            continue
        n_lewat = sum(1 for t in daftar if t.melewati_batas)
        if n_lewat / len(daftar) >= RASIO_SERING_LEWAT:
            rata = sum(abs(t.selisih_kg) for t in daftar) / len(daftar)
            pola.append(Pola(
                kode="POLA_KENDARAAN",
                judul=f"POLA PADA KENDARAAN {nopol}",
                keterangan=(
                    f"{n_lewat} dari {len(daftar)} transaksi dengan {nopol} "
                    f"melewati batas, rata-rata selisih {rata:.1f} kg."
                ),
                data={"nomor_polisi": nopol, "transaksi": len(daftar),
                      "melewati": n_lewat, "rata_abs_kg": round(rata, 2)},
            ))

    per_bulan: dict[str, list[TransaksiRingkas]] = {}
    for t in urut:
        per_bulan.setdefault(f"{t.tanggal:%Y-%m}", []).append(t)
    for bulan, daftar in sorted(per_bulan.items()):
        if len(daftar) < MIN_TRANSAKSI_BULAN:
            continue
        n_lewat = sum(1 for t in daftar if t.melewati_batas)
        if n_lewat / len(daftar) >= RASIO_SERING_LEWAT:
            pola.append(Pola(
                kode="POLA_BULANAN",
                judul=f"POLA PADA BULAN {bulan}",
                keterangan=(
                    f"{n_lewat} dari {len(daftar)} transaksi pada {bulan} "
                    "melewati batas."
                ),
                tingkat=TINGKAT_INFO,
                data={"bulan": bulan, "transaksi": len(daftar), "melewati": n_lewat},
            ))

    return pola


# ─────────────────────────── Skor pihak ───────────────────────────

# Bobot indikator. Spesifikasi awal memuat 6 indikator; "harga terhadap pasar"
# dihapus karena modul ini tidak mengenal harga. Sisa 90% dinormalkan ke 100%
# dengan proporsi yang sama, sehingga urutan kepentingannya tidak berubah.
# NEEDS CONFIRMATION: bobot hasil normalisasi ini.
BOBOT_SKOR = {
    "konsistensi_berat": 0.33,
    "frekuensi_lewat_batas": 0.28,
    "konsistensi_dokumen": 0.17,
    "riwayat_koreksi": 0.11,
    "konsistensi_armada": 0.11,
}

SKALA_KONSISTENSI_PCT = 1.0     # rata-rata |selisih%| 0 -> 100, 1% -> 0
SKOR_NETRAL_DATA_TIPIS = 75.0


@dataclass
class SkorPihak:
    jumlah_transaksi: int
    komponen: dict[str, float]
    skor_total: float
    kategori: str
    rata_selisih_kg: float
    rata_abs_selisih_kg: float
    total_selisih_kg: float
    rata_selisih_persen: float
    stdev_selisih_kg: float
    melewati_batas: int
    total_kg: float
    data_cukup: bool


def kategori_skor(skor: float) -> str:
    if skor >= 90:
        return "A"
    if skor >= 75:
        return "B"
    if skor >= 60:
        return "C"
    return "D"


def _clamp(nilai: float, bawah: float = 0.0, atas: float = 100.0) -> float:
    return max(bawah, min(atas, nilai))


def hitung_skor_pihak(transaksi: list[TransaksiRingkas]) -> SkorPihak | None:
    """Skor monitoring 0–100 dari riwayat. INDIKATOR PEMANTAUAN, bukan tuduhan:
    skor rendah berarti angka pihak ini butuh perhatian, bukan bersalah."""
    aktif = list(transaksi)
    n = len(aktif)
    if n == 0:
        return None

    selisih = [t.selisih_kg for t in aktif]
    abs_selisih = [abs(s) for s in selisih]
    rata_abs = sum(abs_selisih) / n
    rata_pct = sum(abs(t.selisih_persen) for t in aktif) / n
    lewat = sum(1 for t in aktif if t.melewati_batas)
    cukup = n >= MIN_TRANSAKSI_POLA

    # 1. Konsistensi berat (33%) — relatif terhadap batas yang berlaku, bukan
    #    angka mutlak, agar adil antar-komoditas dengan ambang berbeda.
    rasio = [
        abs(t.selisih_kg) / t.batas_kg for t in aktif if t.batas_kg > 0
    ]
    if rasio:
        rata_rasio = sum(rasio) / len(rasio)
        k_berat = _clamp(100.0 - rata_rasio * 50.0)  # 1x batas -> 50, 2x -> 0
    else:
        k_berat = SKOR_NETRAL_DATA_TIPIS

    # 2. Frekuensi melewati batas (28%)
    k_frekuensi = _clamp(100.0 - (lewat / n * 100.0)) if cukup else SKOR_NETRAL_DATA_TIPIS

    # 3. Konsistensi dokumen (17%)
    k_dokumen = _clamp(100.0 - (rata_pct / SKALA_KONSISTENSI_PCT) * 100.0)

    # 4. Riwayat koreksi (11%)
    if cukup:
        pct_koreksi = sum(1 for t in aktif if t.dikoreksi) / n * 100.0
        k_koreksi = _clamp(100.0 - pct_koreksi * 2.0)
    else:
        k_koreksi = SKOR_NETRAL_DATA_TIPIS

    # 5. Konsistensi armada (11%)
    nopol = [t.nomor_polisi for t in aktif if t.nomor_polisi]
    if cukup and nopol:
        rasio_unik = len(set(nopol)) / len(nopol) * 100.0
        k_armada = _clamp(100.0 - max(0.0, rasio_unik - 20.0) * 1.25)
    else:
        k_armada = SKOR_NETRAL_DATA_TIPIS

    komponen = {
        "konsistensi_berat": round(k_berat, 2),
        "frekuensi_lewat_batas": round(k_frekuensi, 2),
        "konsistensi_dokumen": round(k_dokumen, 2),
        "riwayat_koreksi": round(k_koreksi, 2),
        "konsistensi_armada": round(k_armada, 2),
    }
    total = sum(komponen[k] * BOBOT_SKOR[k] for k in BOBOT_SKOR)

    return SkorPihak(
        jumlah_transaksi=n,
        komponen=komponen,
        skor_total=round(total, 2),
        kategori=kategori_skor(total),
        rata_selisih_kg=round(sum(selisih) / n, 2),
        rata_abs_selisih_kg=round(rata_abs, 2),
        total_selisih_kg=round(sum(selisih), 2),
        rata_selisih_persen=round(sum(t.selisih_persen for t in aktif) / n, 4),
        stdev_selisih_kg=round(pstdev(selisih), 2) if n > 1 else 0.0,
        melewati_batas=lewat,
        total_kg=round(sum(t.berat_barang_kg for t in aktif), 2),
        data_cukup=cukup,
    )


def status_pihak_disarankan(skor: SkorPihak | None, pola: list[Pola]) -> str:
    """Usulan status monitoring — keputusan akhir tetap di tangan manusia."""
    if skor is None:
        return "ACTIVE"
    if any(p.tingkat == TINGKAT_TINGGI for p in pola) or skor.kategori == "D":
        return "INVESTIGASI"
    if pola or skor.kategori == "C":
        return "MONITORING"
    return "ACTIVE"
