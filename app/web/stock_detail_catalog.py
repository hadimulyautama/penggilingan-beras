"""Bounded exact native visible links paired with already-read DTO metadata."""
import hashlib
import json
from pathlib import Path
from functools import lru_cache
from app.web.giling_work_catalog import _visible
from app.web.stock_detail_native import SELECTOR, address, structure, Offer


@lru_cache(maxsize=1)
def aset():
    folder = Path(__file__).parent/'static'
    meta = json.loads((folder/'kerangka-stock-detail-ui.meta.json').read_text())
    if meta.get('versi') != 1 or hashlib.sha256((folder/'kerangka-stock-detail-ui.js').read_bytes()).hexdigest() != meta.get('aset_sha256'):
        raise ValueError('Stock detail structure program mismatch')
    return meta


def catalog(html, *, offers, source_address, cap, context, session):
    from bs4 import BeautifulSoup
    from urllib.parse import urlsplit
    if type(html) is not str or len(html.encode()) > 8*1024*1024 or type(source_address) is not str or len(source_address) > 4096 or not all(type(v) is str and 0 < len(v) <= 512 for v in (cap, context, session)):
        return None
    try:
        src = urlsplit(source_address)
    except ValueError:
        return None
    if src.scheme or src.netloc or src.fragment or not src.path.startswith('/'):
        return None
    doc = BeautifulSoup(html, 'html.parser')
    main = doc.select_one('#isi-halaman')
    if main is None:
        return None
    links = [link for link in main.select(SELECTOR) if _visible(link)]
    if len(links) > 100:
        return None  # Desktop/mobile duplicates may describe at most 50 targets.
    by_identity = {}
    for offer in offers:
        if not isinstance(offer, Offer) or offer.meta is None:
            continue
        old = by_identity.get(offer.identity)
        if old is not None and (old.meta, old.title, old.leaf, old.body_title) != (offer.meta, offer.title, offer.leaf, offer.body_title):
            return None
        by_identity[offer.identity] = offer
    entries = []
    seen = set()
    for link in links:
        href = link.get('href', '')
        parsed = address(href)
        if parsed is None or href in seen or link.get('target') or link.has_attr('download') or link.get('aria-disabled') == 'true':
            continue
        offer = by_identity.get(parsed['identity'])
        if offer is None:
            continue  # Neither arbitrary href nor a warehouse ID is authority.
        from app.web.stock_sosoh_chrome import stock as native_chrome
        chrome = native_chrome(href, title=offer.title or structure(offer.meta)['title'], leaf=offer.leaf or None)
        if chrome is None:
            continue
        if (offer.body_title is None) != offer.meta['variant'].startswith('warehouse-') or offer.body_title is not None and (type(offer.body_title) is not str or not 0 < len(offer.body_title) <= 512):
            continue
        entries.append(dict(alamat=href, metadata=offer.meta, chrome=chrome, body_title=offer.body_title))
        seen.add(href)
    if len(entries) > 50:
        return None
    if not entries:
        return None
    result = dict(versi=1, sumber=aset()['sumber'], cap=cap, konteks=context, sesi=session,
                  asal=source_address, asal_sha256=hashlib.sha256(source_address.encode()).hexdigest(), entries=entries)
    from jinja2.utils import htmlsafe_json_dumps
    return result if len(htmlsafe_json_dumps(result).encode()) <= 32768 else None
