"""Pure, data-free metadata for seven native history lists; no app boot/DB."""
from __future__ import annotations

import ast
from functools import lru_cache
from html import unescape
from pathlib import Path
import re
from urllib.parse import parse_qsl

from jinja2 import Environment, nodes

APP_DIR = Path(__file__).resolve().parents[1]
PROCESS = {
    '/riwayat-giling': ('giling', 'penggilingan', 'riwayat_giling.html'),
    '/riwayat-sosoh': ('sosoh', 'penyosohan', 'riwayat_sosoh.html'),
    '/riwayat-pengeringan': ('pengeringan', 'pengeringan', 'riwayat_pengeringan.html'),
}
QC = frozenset(('gabah-basah', 'gabah-kering', 'pk-luar', 'pk-hasil-giling'))
MESSAGES = {
    'loading': 'Memuat catatan. Ringkasan dan jumlah belum dibaca.',
    'empty': 'Belum ada catatan pada daftar ini.',
    'filtered-empty': 'Tidak ada catatan yang cocok dengan pilihan halaman ini.',
    'error': 'Catatan belum dapat dibaca. Coba lagi hanya membaca data.',
}


def alamat(path: str, query: str = '') -> str | None:
    if path not in PROCESS and path not in {'/riwayat-qc/' + q for q in QC}:
        return None
    pairs = parse_qsl(query, keep_blank_values=True)
    # Daftar QC native tidak mempunyai filter query. Cursor proses dipertahankan
    # persis; arti valid/invalid cursor tetap diputuskan handler asli.
    if len(query) > 2048 or (query and (path not in PROCESS or len(pairs) != 1 or pairs[0][0] != 'sebelum')):
        return None
    return path + ('?' + query if query else '')


def keadaan(status: str) -> dict:
    if status not in MESSAGES:
        raise ValueError('Keadaan daftar harus eksplisit; missing bukan kosong.')
    return dict(status=status, pesan=MESSAGES[status], sibuk=status == 'loading', retry=status == 'error')


def _head(source, pattern):
    match = re.search(pattern, source, re.S)
    if not match:
        raise ValueError('Kepala daftar native berubah; review diperlukan.')
    html = match.group(0)
    if any(token in html for token in ('{{', '{%', '<a ', '<button', '<form', '<input')):
        raise ValueError('Kepala daftar bukan metadata statis.')
    names = [unescape(re.sub('<[^>]+>', '', value)).strip()
             for value in re.findall(r'<(?:th|span)\b[^>]*>(.*?)</(?:th|span)>', html, re.S)]
    return html, names


@lru_cache(maxsize=7)
def metadata(path: str) -> dict:
    """Only source labels/markup; never render original template with fake rows."""
    if path in PROCESS:
        kind, guard, name = PROCESS[path]
        source = (APP_DIR/'web/templates'/name).read_text()
        parsed = Environment().parse(source)
        calls = [n for n in parsed.find_all(nodes.Call) if isinstance(n.node, nodes.Getattr)
                 and n.node.attr == 'header' and isinstance(n.node.node, nodes.Name)
                 and n.node.node.name == 'rh']
        if len(calls) != 1 or not all(isinstance(a, nodes.Const) for a in calls[0].args[:3]):
            raise ValueError('Header ringkasan native berubah.')
        header = calls[0]
        stats = []
        for item in header.args[3].items:
            if not isinstance(item, nodes.Tuple) or not isinstance(item.items[2], nodes.Const):
                raise ValueError('Label ringkasan bukan metadata statis.')
            # Never consume the value expression or format a record/number.
            stats.append((item.items[0].value, '—', item.items[2].value))
        if kind == 'giling':
            head, labels = _head(source, r'<thead>.*?</thead>')
        else:
            head, labels = _head(source, r'<div class="riwayat-desktop-grid[^"\n]*riwayat-desktop-head"[^>]*>.*?</div>')
        return dict(family='proses', kind=kind, guard=guard, title=header.args[1].value,
                    label=header.args[0].value, description=header.args[2].value,
                    stats=stats, header=head, columns=labels, source_template=name)
    kind = path.removeprefix('/riwayat-qc/')
    if kind not in QC or path != '/riwayat-qc/' + kind:
        raise ValueError('Keluarga daftar tidak didukung.')
    source = (APP_DIR/'web/templates/riwayat_qc.html').read_text()
    head, labels = _head(source, r'<div class="tabel-standar__kepala"[^>]*>.*?</div>')
    module = ast.parse((APP_DIR/'web/layar_riwayat.py').read_text())
    titles = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'QC_PAGES' for t in n.targets))
    return dict(family='qc', kind=kind, title=titles[kind][0], header=head,
                columns=labels, source_template='riwayat_qc.html')
