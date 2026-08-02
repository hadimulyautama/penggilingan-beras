"""Peta kategori arsip baku PT HMU — dikodekan dari Pedoman Kearsipan Digital
(PDM/KA-DIG/PT-HMU/01). MURNI (tanpa DB/IO).

Dipakai arsip manager untuk: (a) tahu file harus masuk kategori mana,
(b) deteksi file "nyasar" (di root / salah kategori), (c) klasifikasi awal
berbasis kata kunci sebelum dibantu AI untuk kasus ambigu.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TRANSIT = "_TRANSIT"   # inbox file baru
ARSIP_LAMA = "99"      # "karantina": inaktif/duplikat/kedaluwarsa


@dataclass(frozen=True)
class Kategori:
    kode: str
    nama: str
    isi: str
    subfolder: tuple[str, ...] = ()
    # kata kunci untuk klasifikasi awal (lowercase, cocok substring nama/isi file)
    kunci: tuple[str, ...] = field(default=())


# Urutan = urutan tampil folder (kode menentukan urutan).
KATEGORI: tuple[Kategori, ...] = (
    Kategori(TRANSIT, "INBOX — File Baru",
             "Kotak masuk sementara. Semua file baru masuk sini dulu."),
    Kategori("00", "Legalitas & Sekretariat",
             "Akta, dokumen PT, merek/HAKI, halal, SOP korporat, keputusan direktur, kontrak korporat, berita acara, sengketa.",
             ("AKTA", "Berita Acara", "Dokumen PT", "Halal", "Keputusan Direktur",
              "Kerja Sama Hukum", "Kontrak", "Merek", "Sengketa", "SOP",
              "Surat Kuasa", "Surat Perjanjian"),
             ("akta", "notaris", "merek", "haki", "halal", "izin", "legalitas",
              "keputusan direktur", "surat kuasa", "sengketa", "perkara")),
    Kategori("01", "Korespondensi",
             "Surat masuk & keluar umum, buku agenda surat.",
             (), ("surat masuk", "surat keluar", "undangan", "korespondensi", "agenda surat")),
    Kategori("02", "Keuangan & Pajak",
             "Laporan keuangan, rekening koran, faktur pajak, SPT, NPWP, tagihan/piutang.",
             (), ("faktur", "pajak", "spt", "npwp", "rekening", "tagihan", "invoice",
                  "nota", "kwitansi", "laporan keuangan", "piutang", "pembukuan", "ppn")),
    Kategori("03", "SDM & Umum (HRGA)",
             "Data karyawan, kontrak kerja, SK, jobdesk, rekrutmen, payroll/BPJS, kinerja, PHK.",
             ("00 Kebijakan & SOP HR", "01 Data & Identitas Karyawan",
              "02 Kontrak Kerja", "03 SK & Pengangkatan", "04 Jobdesk",
              "05 Rekrutmen", "06 Non-Aktif & PHK", "07 Payroll BPJS & Benefit",
              "08 Kinerja & Pengembangan", "09 Kedisiplinan & Hub. Industrial",
              "10 Arsip Surat Umum"),
             ("karyawan", "kontrak kerja", "jobdesk", "job desk", "rekrutmen",
              "payroll", "gaji", "bpjs", "phk", "pengunduran diri", "resign",
              "sk pengangkatan", "cuti", "absensi", "surat peringatan", "ktp")),
    Kategori("04", "Operasional & Gudang",
             "Produksi, stok/gudang, sawah/gabah, lab/mutu, borongan, data harian.",
             (), ("produksi", "gudang", "stok", "gabah", "beras", "giling",
                  "penyosohan", "selepan", "borongan", "mutu", "laboratorium")),
    Kategori("05", "Penjualan & Pemasaran",
             "Pelanggan, marketing/branding, sistem harga, sales order, kontrak penjualan, LPJ sales.",
             (), ("pelanggan", "marketing", "branding", "harga", "sales", "penjualan",
                  "sales order", "lpj", "promosi")),
    Kategori("06", "Pengadaan & Pemasok",
             "Vendor/pemasok, SPK pengadaan, kerjasama pemasok/kelompok tani.",
             (), ("vendor", "pemasok", "supplier", "pengadaan", "spk", "po",
                  "purchase order", "kelompok tani")),
    Kategori("07", "Aset & Pemeliharaan",
             "Mesin & kendaraan, kartu pemeliharaan, disposal aset, vendor teknisi.",
             ("Mesin", "Truck"),
             ("aset", "mesin", "kendaraan", "truck", "truk", "pemeliharaan",
              "maintenance", "servis", "perbaikan", "kartu pemeliharaan")),
    Kategori("08", "IT & Sistem",
             "Sistem informasi, akun/aplikasi, dokumentasi teknis IT.",
             (), ("it", "sistem", "akun", "aplikasi", "software", "database",
                  "backup", "server", "password", "email perusahaan")),
    Kategori("09", "Proyek",
             "Dokumen proyek (pembangunan pabrik/gedung), seleksi kontraktor, kontrak proyek.",
             (), ("proyek", "pembangunan", "kontraktor", "gedung", "konstruksi", "rab")),
    Kategori("10", "CSR & Kegiatan",
             "Kebijakan/SOP CSR, register & pengajuan CSR, laporan kegiatan, event.",
             ("00 Kebijakan & SOP", "01 Register", "02 Pengajuan", "03 Laporan", "Events"),
             ("csr", "bantuan", "sumbangan", "kegiatan", "event", "halal bihalal",
              "karangtaruna", "donasi")),
    Kategori("11", "Tata Kelola & Kearsipan",
             "Pedoman kearsipan (fisik & digital), tata naskah, berita acara penataan/pemusnahan, retensi.",
             (), ("pedoman", "kearsipan", "tata kelola", "tata naskah", "retensi",
                  "disposisi", "pemusnahan")),
    Kategori(ARSIP_LAMA, "Arsip Lama",
             "Arsip inaktif, kedaluwarsa, salinan/duplikat, file lama belum dimusnahkan.",
             (), ("arsip lama", "lama", "duplikat", "salinan", "inaktif")),
)

_BY_KODE = {k.kode: k for k in KATEGORI}
# Kategori tempat file bisa "diarahkan" (bukan _TRANSIT sbg tujuan disposisi).
_TUJUAN = tuple(k for k in KATEGORI if k.kode not in (TRANSIT,))


def kategori(kode: str) -> Kategori | None:
    return _BY_KODE.get(kode)


def semua() -> tuple[Kategori, ...]:
    return KATEGORI


def tebak_kategori(nama_file: str, isi_ringkas: str = "") -> list[tuple[str, int]]:
    """Klasifikasi awal berbasis kata kunci → daftar (kode, skor) urut menurun.

    Deterministik & murah (tanpa AI). Untuk kasus kosong/ambigu (skor 0 atau
    seri di puncak), organizer akan minta bantuan AI + baca isi dokumen.
    Skor = jumlah kata kunci yang cocok pada nama + isi ringkas.
    """
    teks = f"{nama_file} {isi_ringkas}".lower()
    skor: list[tuple[str, int]] = []
    for kat in _TUJUAN:
        if kat.kode == ARSIP_LAMA:
            continue  # 99 bukan hasil klasifikasi isi, tapi keputusan retensi
        n = sum(1 for kw in kat.kunci if kw in teks)
        if n:
            skor.append((kat.kode, n))
    skor.sort(key=lambda t: t[1], reverse=True)
    return skor
