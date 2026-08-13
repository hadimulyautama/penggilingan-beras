"""Router domain untuk agen Kantor — pilih bundel tool per permintaan.

DETERMINISTIK (0 token LLM) = paling murah & andal: cocokkan kata kunci → domain.
Ambigu/tak cocok → 'umum' (bundel PENUH = perilaku sekarang, aman).

Tujuan utama: KETAJAMAN (tool sedikit → agen tak bingung → keputusan lebih baik).
CATATAN biaya: dengan prompt-caching, membundel tak selalu lebih murah (memecah
cache bila domain sering berganti) — jadi nilai utamanya AKURASI, bukan input-cost.
Karena itu diaktifkan lewat flag `router_aktif` (default OFF) agar bisa di-A/B.
"""
from __future__ import annotations

# domain → kata kunci pemicu (lowercase, substring).
_KUNCI: dict[str, list[str]] = {
    "produksi": ["hpp", "milling", "selepan", "penyosohan", "gabah", "beras",
                 "silo", "rendemen", "pengeringan", "produksi", "giling",
                 "batch", "lot", "gudang 1", "gudang 2", "tonase"],
    "email": ["email", "surat masuk", "surel", "inbox", "kirim ke", "balas email",
              "gmail", "kotak masuk"],
    "arsip": ["file", "folder", "drive", "dokumen", "arsip", "upload", "taruh di",
              "cari file", "rename", "pindah file", "sheet", "spreadsheet"],
    "keuangan": ["tagihan", "utang", "piutang", "faktur", "kledo", "invoice",
                 "akun", "keuangan", "pemasok", "supplier", "bayar", "arus kas",
                 "laba", "rugi", "neraca", "penjualan", "cashflow", "cash flow",
                 "saldo", "kas", "omzet", "jatuh tempo", "terlaris"],
    "hr": ["karyawan", "cuti", "lembur", "presensi", "gaji", "payroll",
           "pengajuan", "gajihub", "absensi"],
    "sekretaris": ["kalender", "agenda", "jadwal", "acara", "rapat",
                   "surat tugas", "meeting", "notula"],
}

# Selalu tersedia (lintas domain).
SHARED: set[str] = {"cari_pengetahuan", "simpan_pengetahuan", "status_biaya"}

# domain → nama tool yang masuk bundelnya.
DOMAIN_TOOLS: dict[str, set[str]] = {
    "produksi": {"simulasi_hpp", "tanya_produksi"},
    "keuangan": {"tagihan_kledo", "faktur_kledo", "kontak_kledo", "akun_kledo", "neraca_kledo",
                 "labarugi_kledo", "aruskas_kledo", "umur_hutang_kledo", "umur_piutang_kledo",
                 "saldo_bank_kledo", "penjualan_kledo", "hutang_kontak_kledo",
                 "piutang_kontak_kledo"},
    "email": {"baca_email", "cari_email", "baca_email_isi", "draft_email",
              "kirim_email", "atur_email", "lihat_aturan_email",
              "batalkan_arsip_email", "arsip_email", "tandai_dibaca_email",
              "label_email"},
    "arsip": {"panduan_arsip", "cek_nama_file", "daftar_transit", "daftar_folder",
              "buka_folder", "cari_file", "baca_dokumen", "baca_gambar",
              "daftar_tab_sheet", "baca_sheet", "audit_draft_nyasar", "pindah_item",
              "rename_item", "hapus_item", "buat_folder", "buat_dokumen",
              "buat_sheet", "update_sheet", "tambah_baris_sheet", "edit_google_docs"},
    "hr": {"karyawan_gajihub", "payroll_gajihub", "cuti_gajihub",
           "pengajuan_gajihub", "setujui_pengajuan", "tolak_pengajuan"},
    "sekretaris": {"siapkan_surat_tugas", "daftar_kalender", "lihat_agenda",
                   "buat_acara", "ubah_acara", "hapus_acara"},
}


def pilih_domain(text: str) -> set[str]:
    """Domain relevan dari kata kunci. {'umum'} bila tak ada yang cocok (→ bundel penuh)."""
    t = (text or "").lower()
    hit = {d for d, kws in _KUNCI.items() if any(k in t for k in kws)}
    return hit or {"umum"}


def bundel(domains: set[str], semua_tool: list[dict]) -> list[dict]:
    """Saring `semua_tool` ke SHARED + tool domain terpilih. 'umum' → semua tool."""
    if "umum" in domains or not domains:
        return semua_tool
    boleh = set(SHARED)
    for d in domains:
        boleh |= DOMAIN_TOOLS.get(d, set())
    dipilih = [t for t in semua_tool if t.get("name") in boleh]
    return dipilih or semua_tool  # jaga-jaga: jangan pernah kirim kosong
