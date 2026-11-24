"""Katalog privat dari tautan/kode native yang sudah berizin, tanpa DB per row."""
import hashlib
from urllib.parse import parse_qsl, urlsplit

from app.web.giling_work_catalog import _visible
from app.web.riwayat_detail_native import QC, PROSES, aset, deskripsi


def katalog(html, *, source_address, cap, context, session,
            boleh_koreksi=False, boleh_catat_qc=False):
    if (type(html) is not str or len(html.encode()) > 8 * 1024 * 1024
            or type(source_address) is not str or len(source_address) > 4096
            or not all(type(v) is str and 0 < len(v) <= 512 for v in (cap, context, session))
            or type(boleh_koreksi) is not bool or type(boleh_catat_qc) is not bool):
        return None
    try:
        source = urlsplit(source_address)
    except ValueError:
        return None
    histories = {'/riwayat-' + kind for kind in PROSES}
    checks = {'/riwayat-qc/' + kind for kind in QC}
    if source.scheme or source.netloc or source.fragment or source.path not in histories | checks:
        return None
    params = parse_qsl(source.query, keep_blank_values=True)
    if len(source.query) > 2048 or (source.query and (source.path not in histories or len(params) != 1 or params[0][0] != 'sebelum')):
        return None
    from bs4 import BeautifulSoup
    doc = BeautifulSoup(html, 'html.parser')
    entries, seen = [], set()
    history = source.path in histories
    selector = '[data-daftar-riwayat-proses] a[href]' if history else '[data-riwayat-qc] a[href]'
    for link in doc.select(selector):
        if (not _visible(link) or link.has_attr('target') or link.has_attr('download')
                or link.get('aria-disabled') == 'true'):
            continue
        href = link.get('href', '')
        if not href.startswith('/') or href.startswith('//'):
            continue
        try:
            address = urlsplit(href)
        except ValueError:
            continue
        if address.scheme or address.netloc or address.fragment or not address.path.startswith(source.path + '/'):
            continue
        try:
            spec = deskripsi(address.path, address.query)
        except (ValueError, SyntaxError, StopIteration, OSError):
            return None
        if spec is None or href in seen:
            continue
        if history:
            row = link.find_parent(['article', 'tr', 'details'])
            if row is None or not (row.has_attr('data-rg-proses') or
                    {'padat', 'riwayat-desktop-row'} & set(row.get('class', []))):
                continue
            if not (link.find_parent(class_='padat__nama--kode')
                    or link.find_parent(class_='riwayat-desktop-lot')
                    or 'rg-kode' in link.get('class', [])):
                continue
            code = link.get_text(strip=True)
            # Hanya pintu kode, bukan tombol Detail/PDF atau target di laci.
            if not code or not _visible(row) or any(ch.isspace() for ch in code) or len(code) > 80:
                continue
        elif spec['jenis'] == 'beras-hasil-sosoh':
            if not link.find_parent('h2') or not link.find_parent(attrs={'data-rqd-beras': True}):
                continue
            code = link.get_text(strip=True)
            if code != spec['referensi']:
                continue
        else:
            if 'tabel-standar__baris' not in link.get('class', []):
                continue
            label = link.select_one('.tabel-standar__kode')
            if label is None or label.get_text(strip=True) != spec['referensi']:
                continue
            code = label.get_text(strip=True)
        seen.add(href)
        entries.append(dict(alamat=href, kode=code, variant=spec['variant'],
                            boleh_koreksi=bool(history and spec['jenis'] in ('giling', 'sosoh') and boleh_koreksi)))
    if len(entries) > (30 if history else 200):
        return None  # Tidak memotong diam-diam halaman native yang tak setara.
    return dict(versi=1, sumber=aset()['sumber'], cap=cap, konteks=context, sesi=session,
                sumber_sha256=hashlib.sha256(source_address.encode()).hexdigest(),
                batas=30 if history else 200, boleh_catat_qc=boleh_catat_qc, entries=entries)
