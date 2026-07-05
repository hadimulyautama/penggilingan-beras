"""Pre-router DETERMINISTIK (0 panggilan LLM) — pemangkas latency.

Sebelum memanggil router LLM (Sonnet ~3s), coba tebak domain dari POLA yang
PASTI (kode transaksi + kata kunci kuat). Bila yakin → kembalikan domain →
bot lewati router LLM (hemat 1 panggilan). Bila RAGU → kembalikan None → jatuh
ke router LLM (akurasi terjaga). Prinsip: lebih baik None daripada SALAH —
jangan pernah menebak domain yang keliru.

Domain sama persis dengan app.ai.router.DOMAINS.
"""
from __future__ import annotations

import re

# (regex, domain). Diperiksa berurutan; match pertama menang. Semua IGNORECASE
# & dicocokkan ke teks ASLI. Hanya pola BER-KEYAKINAN TINGGI; yang ambigu sengaja
# TIDAK dimasukkan (→ None).
_I = re.IGNORECASE
_RULES: list[tuple[re.Pattern, str]] = [
    # ── Kode transaksi (paling andal) ──
    (re.compile(r"\bMIL-\d", _I), "milling"),
    (re.compile(r"\bPOL-\d", _I), "penyosohan"),
    (re.compile(r"\bTRF-\d", _I), "transfer_pk"),
    (re.compile(r"\bPKB-\d", _I), "gudang2"),
    (re.compile(r"\bPKP-\d", _I), "kemasan"),
    (re.compile(r"\bOUT-\d", _I), "barang_keluar"),
    # ── Kata kunci kuat, tabrakan rendah ──
    (re.compile(r"\b(penyosohan|sosoh|nyosoh)\b", _I), "penyosohan"),
    (re.compile(r"\bpacking\b|\bbekatul\b", _I), "barang_jadi"),
    (re.compile(r"\b(giling|menggiling|pecah kulit)\b", _I), "milling"),
    (re.compile(r"\b(keringkan|pengeringan|jemur)\b", _I), "pengeringan"),
    (re.compile(r"\bbeli\s+karung\b|\bkarung\b.*\blembar\b", _I), "kemasan"),
    (re.compile(r"\bgabah\b.*\b(masuk|beli|datang|dibeli)\b|\bbeli\s+gabah\b", _I),
     "pembelian_gabah"),
    (re.compile(r"\bpindah\s+tumpukan\b", _I), "gudang2"),
    (re.compile(r"\bbeli\s+(beras\s+)?pk\b", _I), "gudang2"),
    (re.compile(r"\bstok\s+(gudang\s*2|g2)\b", _I), "gudang2"),
    (re.compile(r"\bjual\s+pk\b", _I), "barang_keluar"),
]

# Kode yang perlu KONTEKS tambahan (jangan sembarang) → tangani khusus.
_LOT = re.compile(r"\bLOT-\d", _I)
_GB = re.compile(r"\bGB-\d", _I)
_MENTIONS_SILO = re.compile(r"\bsilo\b", _I)
_MENTIONS_KERING = re.compile(r"\bkering", _I)
_MENTIONS_HARGA = re.compile(r"\b(harga|juta|ribu|rp\b|/kg|per kg)\b", _I)
_MENTIONS_VERIF = re.compile(r"\bverif", _I)


def fast_domain(text: str, valid: set[str] | None = None) -> str | None:
    """Tebak domain dari pola pasti; None bila ragu (→ pakai router LLM).

    `valid`: bila diberikan, hanya kembalikan domain yang ada di set itu
    (domain relevan untuk bot pemanggil) — selain itu None.
    """
    dom: str | None = None
    for rx, d in _RULES:
        if rx.search(text):
            dom = d
            break

    if dom is None:
        # Kode kondisional
        if _LOT.search(text):
            if _MENTIONS_SILO.search(text):
                dom = "silo_g1"
            elif _MENTIONS_KERING.search(text):
                dom = "pengeringan"
        elif _GB.search(text) and (_MENTIONS_HARGA.search(text) or _MENTIONS_VERIF.search(text)):
            dom = "verifikasi_harga_gabah"

    if dom is None:
        return None
    if valid is not None and dom not in valid:
        return None
    return dom
