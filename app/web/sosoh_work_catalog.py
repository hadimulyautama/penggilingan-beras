"""Sosoh links from one already authorized native Work DOM, never free IDs."""
from __future__ import annotations
import hashlib
from urllib.parse import urlsplit
from app.web.giling_work_catalog import _visible, MAX_BYTES, MAX_ROWS
from app.web.sosoh_native_html import deskripsi


def catalog(html, *, source_address, cap, context, session):
    if (not isinstance(html, str) or len(html.encode()) > MAX_BYTES
            or not isinstance(source_address, str) or len(source_address) > 4096
            or not all(type(v) is str and 0 < len(v) <= 512 for v in (cap, context, session))):
        return None
    try:
        source = urlsplit(source_address)
    except ValueError:
        return None
    if source.scheme or source.netloc or source.fragment or source.path not in {'/pekerjaan', '/berjalan'}:
        return None
    from bs4 import BeautifulSoup
    doc = BeautifulSoup(html, 'html.parser')
    rows = [row for row in doc.select('section[data-blok][aria-label="Proses aktif"] .proses-aktif-list > .proses-aktif-list__row') if _visible(row)]
    if len(rows) > MAX_ROWS:
        return None
    entries, seen = [], set()
    for row in rows:
        if row.get('data-proses') != 'sosoh':
            continue
        strong = row.find('strong')
        if strong is None or not _visible(strong):
            continue
        code = strong.get_text(strip=True)
        links = [row] if row.name == 'a' else row.select('a.proses-aktif-list__detail[href]')
        for link in links:
            href = link.get('href', '')
            if (not _visible(link) or link.get('target') or link.has_attr('download')
                    or link.get('aria-disabled') == 'true' or not isinstance(href, str)
                    or not href.startswith('/') or href.startswith('//')):
                continue
            try:
                u = urlsplit(href)
                spec = None if u.scheme or u.netloc or u.fragment else deskripsi(u.path, u.query)
            except ValueError:
                spec = None
            if spec is None or spec['kode'] != code or href in seen:
                continue
            from app.web.stock_sosoh_chrome import sosoh as native_chrome
            chrome = native_chrome(href, code)
            if chrome is None:
                continue
            entries.append(dict(alamat=href, kode=code, label='Penyosohan aktif', chrome=chrome))
            seen.add(href)
            break
    return dict(versi=1, cap=cap, konteks=context, sesi=session,
                sumber_sha256=hashlib.sha256(source_address.encode()).hexdigest(), entries=entries)
