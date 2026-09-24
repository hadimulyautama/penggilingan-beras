"""Token CSRF — pola double-submit cookie.

Cookie sesi sudah bertanda `SameSite=Lax`, dan itu memang menahan sebagian
besar pengiriman formulir dari situs lain. Tetapi ia menahannya di PERAMBAN:
yang menjaga adalah pengaturan di sisi pengunjung, bukan pemeriksaan di sisi
kita. Peramban lama, konteks yang dianggap "same-site" padahal bukan, dan
navigasi tingkat atas yang kebetulan memenuhi syarat — semuanya lolos.
Temuan QA P-S-15.

Pola double-submit: satu nilai acak disimpan di cookie DAN ikut dikirim di
dalam formulir (atau sebagai header, untuk permintaan JSON). Situs lain bisa
membuat peramban mengirim cookie, tetapi tak bisa MEMBACA isinya, jadi ia tak
bisa menyertakan nilai yang sama di badan permintaannya.

Halaman masuk ikut dipagari. Tanpa itu, situs lain bisa memaksa peramban
seseorang masuk sebagai akun milik penyerang — dan pekerjaan yang ia catat
sesudahnya tercatat atas nama orang lain.
"""
from __future__ import annotations

import hmac
import secrets

NAMA_COOKIE = "produksi_csrf"
NAMA_FIELD = "_csrf"
NAMA_HEADER = "x-csrf-token"

#: Metode yang tidak mengubah apa pun, jadi tak perlu dipagari.
METODE_AMAN = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Jalur yang dipanggil mesin, bukan peramban — tak punya cookie dan memang
#: tak seharusnya punya. Memagarinya berarti mematikan pemeriksaan kesehatan
#: Railway, dan layanan yang dianggap mati akan dimulai ulang terus-menerus.
JALUR_BEBAS = ("/health", "/internal/")


def terbitkan_baru() -> str:
    return secrets.token_urlsafe(32)


def cocok(a: str | None, b: str | None) -> bool:
    """Bandingkan konstan-waktu; kosong tak pernah cocok dengan apa pun."""
    if not a or not b:
        return False
    return hmac.compare_digest(str(a), str(b))


def perlu_periksa(metode: str, jalur: str) -> bool:
    if (metode or "").upper() in METODE_AMAN:
        return False
    return not any((jalur or "").startswith(p) for p in JALUR_BEBAS)

