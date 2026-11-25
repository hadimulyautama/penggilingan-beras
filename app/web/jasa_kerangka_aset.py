"""Aset native stabil untuk kerangka Jasa lokal, tanpa unduhan saat klik.

Cache proses ini hanya kode CSS/JS build, tidak pernah HTML, aktor, saldo,
filter atau draf. Template dan sumber aset tetap satu; tidak ada salinan kode
editable kedua. Kegagalan paket hanya menonaktifkan frame Jasa opsional.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ASET = (
    ('jasa-pelanggan.css', 'hmu_tampilan/static/jasa-pelanggan.css', 'style'),
    ('jasa-bertahap.css', 'app/web/static/jasa-bertahap.css', 'style'),
    ('jasa-kontrol.css', 'hmu_tampilan/static/jasa-kontrol.css', 'style'),
    ('jasa-kontrol.js', 'hmu_tampilan/static/jasa-kontrol.js', 'script'),
    ('jasa-bertahap.js', 'app/web/static/jasa-bertahap.js', 'script'),
)


@lru_cache(maxsize=1)
def _kode_aset() -> tuple[tuple[str, str, str], ...]:
    hasil = []
    total = 0
    for nama, relative, tag in ASET:
        source = (ROOT / relative).resolve()
        if not source.is_relative_to(ROOT) or not source.is_file():
            raise ValueError('Sumber aset kerangka Jasa tidak tersedia.')
        code = source.read_text(encoding='utf-8')
        total += len(code.encode('utf-8'))
        if not code or total > 131072 or f'</{tag}' in code.lower():
            raise ValueError('Bentuk aset kerangka Jasa tidak sesuai.')
        # Aset klik pertama harus utuh; impor/URL relatif tidak boleh berubah
        # makna ketika CSS native disisipkan pada dokumen tujuan.
        if tag == 'style' and re.search(r'@import|url\s*\(', code, re.I):
            raise ValueError('Kerangka Jasa memerlukan aset CSS tambahan.')
        hasil.append((nama, code, tag))
    return tuple(hasil)


def paket_lokal(body: bytes) -> bytes:
    html = body.decode('utf-8')
    for nama, code, tag in _kode_aset():
        path = re.escape(nama)
        if tag == 'style':
            pattern = r'<link rel="stylesheet" href="/static/' + path + r'\?[^"<>]+">'
        else:
            pattern = r'<script src="/static/' + path + r'\?[^"<>]+" defer></script>'
        replacement = f'<{tag} data-jasa-aset-native="{nama}">{code}</{tag}>'
        html, count = re.subn(pattern, lambda _: replacement, html)
        if count != 1:
            raise ValueError('Referensi aset kerangka Jasa tidak tunggal.')
    return html.encode('utf-8')
