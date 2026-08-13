"""Pemetaan RESOURCE → DOMAIN (Tahap 1). Menghubungkan sumber nyata (folder Drive,
kotak email, data GajiHub) ke domain RBAC, agar scope-checker bisa memutuskan izin.

Prinsip: domain PALING SPESIFIK menang. Sub-folder sensitif (payroll, sengketa, IT)
mengoverride domain induknya karena dicek lebih dulu di rantai folder (leaf→root).

Sumber kebenaran = folder ID (stabil walau nama berubah). Perbarui bila struktur
Drive berubah. Domain 'pribadi' TAK punya grant di seed → hanya Direksi ('*').
"""
from __future__ import annotations

# folder_id → domain. Sensitif dulu agar override saat rantai dicek.
DRIVE_FOLDER_DOMAIN: dict[str, str] = {
    # ── sub-folder SENSITIF (override induk) ──
    "1WwfbsrET_FAl54YHiL3SLyEeGWanzhwT": "gaji",        # 03/07 Payroll, BPJS & Benefit
    "1v6H72z1tp7-NkI6vd84bDqEIM_xiAxl5": "sengketa",    # 10 - Sengketa
    "1l6ITHWr3eRPIhquRtW5aOxbJ_qOLttZg": "sengketa",    # PT. RAJAWALI (bukti sengketa)
    "12n4jOMrbS-krWekH6yJODu8RV4Pg7slO": "folder_it",   # IT Accounts (kredensial)
    "1DZ6WiAx7n6PwSs8jiAyEmXVeI3fP1cao": "folder_it",   # Kebijakan & SOP IT
    # ── top-level ──
    "1vzYJcDEAg5UgwgLIvige8C8VYMq7i-3y": "legal",        # 00 Legalitas & Sekretariat
    "1TLm-ZI2JRICobaA7oUV5M8Sh_f9I7hbD": "sekretaris",   # 01 Korespondensi
    "1x-VKFIDRAnoyV0rPk1KDEbZZejWg0B2m": "keuangan",     # 02 Keuangan & Pajak
    "1LG642_fjj2N-E7uFdxQLUarZRURkRxRJ": "hr",           # 03 SDM & Umum (HRGA)
    "1TvUujgnI3b2knPUo1Pc-SNoYgZte8Eu9": "operasional",  # 04 Operasional & Gudang
    "1LCN9ikKoFFZYiVS7ROdl2wuCx1SkdEgX": "penjualan",    # 05 Penjualan & Pemasaran
    "1sX5ae8DglQahT6PDrSUe5lwRKLL7hgdv": "operasional",  # 06 Pengadaan & Pemasok
    "1wbOiBBhwgSCjBZzvSljChpznIJ7MG5p0": "operasional",  # 07 Aset & Pemeliharaan
    "1OtrKmw0txv3GQYv_ily6nDuj8ED4eXM5": "folder_it",    # 08 IT & Sistem
    "1bp3QqXp7FaIsPZen8EZEn4MYe3HzvdAD": "operasional",  # 09 Proyek
    "11sqnfhw09HkNAR6Bp2_d305YvYiSr7D4": "sekretaris",   # 10 CSR & Kegiatan
    "1SkqOl6CpbokEH5Uh_rcHpDfnZyuRL1Fe": "arsip",        # 11 Tata Kelola & Kearsipan
    "1VYBdoyZXAicxrdC_DrijzKneeRwAS2iR": "arsip",        # 99 Arsip Lama
    "1ATYirexrYy8TWkdfBOzpRwKvEHuPSsCE": "arsip",        # _TRANSIT (inbox)
}

# mailbox → domain. 'pribadi' = hanya Direksi (tak ada grant di seed selain '*').
MAILBOX_DOMAIN: dict[str, str] = {
    "finance@hadimulya.com": "keuangan",
    "admin@hadimulya.com": "sekretaris",
    "wahidnurhani@hadimulya.com": "pribadi",
    "wahidnurhani20@gmail.com": "pribadi",
    "wahidnurhani@gmail.com": "pribadi",
}

# jenis data GajiHub → domain (payroll/slip = gaji; presensi/cuti/lembur = hr)
GAJIHUB_DOMAIN: dict[str, str] = {
    "payroll": "gaji", "gaji": "gaji", "slip": "gaji",
    "presensi": "hr", "cuti": "hr", "lembur": "hr",
    "karyawan": "hr", "pengajuan": "hr",
}


def domain_folder(rantai_folder_id: list[str]) -> str | None:
    """rantai = id folder dari file MENUJU root (leaf→root). Return domain paling
    spesifik (kecocokan pertama). None bila tak terpetakan."""
    for fid in rantai_folder_id:
        d = DRIVE_FOLDER_DOMAIN.get(fid)
        if d:
            return d
    return None


def domain_mailbox(mailbox: str) -> str | None:
    return MAILBOX_DOMAIN.get((mailbox or "").strip().lower())


def domain_gajihub(jenis: str) -> str:
    return GAJIHUB_DOMAIN.get((jenis or "").strip().lower(), "hr")
