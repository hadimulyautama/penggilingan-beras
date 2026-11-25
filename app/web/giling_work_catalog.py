"""Bounded per-document Giling targets from ALREADY authorized native Work HTML.

No route discovery/DB lookup and no new authorization: root owns the native
read/permission gate and must only use exact entries in this private envelope.
Never publish this session-bound envelope as an immutable public asset.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
import importlib.util
from pathlib import Path
from urllib.parse import urlsplit

MAX_ROWS = 50
MAX_BYTES = 8 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _descriptor_function():
    # Load pure definitions only; the module imports no app/database runtime.
    spec = importlib.util.spec_from_file_location(
        "giling_native_catalog_spec", ROOT / "app/web/giling_native_html.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.deskripsi


def _descriptor(address, describe):
    value = urlsplit(address)
    if value.scheme or value.netloc or value.fragment:
        return None
    return describe(value.path, value.query)


def _visible(node):
    for current in [node, *node.parents]:
        if getattr(current, "name", None) in {"template", "noscript", "script", "style"}:
            return False
        attrs = getattr(current, "attrs", {})
        style = "".join(attrs.get("style", "").lower().split())
        if ("hidden" in attrs or "inert" in attrs
                or attrs.get("aria-hidden", "").lower() == "true"
                or "display:none" in style or "visibility:hidden" in style):
            return False
    return True


def catalog(html: str, *, source_address: str, cap: str,
            context: str, session: str) -> dict | None:
    """Root invokes ONLY after a successful authorized native Work read.

    Visibility here means DOM hidden/inert/style flags, not computed browser
    CSS. Root must prove its source is current displayed native Work markup;
    this function cannot prove caller identity, permission or computed layout.
    """
    if (not isinstance(html, str) or len(html.encode()) > MAX_BYTES
            or not all(isinstance(v, str) and 0 < len(v) <= 512
                       for v in (cap, context, session))
            or not isinstance(source_address, str) or len(source_address) > 4096):
        return None
    try:
        source = urlsplit(source_address)
    except ValueError:
        return None
    if source.scheme or source.netloc or source.fragment or source.path not in {"/pekerjaan", "/berjalan"}:
        return None
    from bs4 import BeautifulSoup
    doc = BeautifulSoup(html, "html.parser")
    rows = [node for node in doc.select(
        'section[data-blok][aria-label="Proses aktif"] .proses-aktif-list > .proses-aktif-list__row')
        if _visible(node)]
    if len(rows) > MAX_ROWS:
        return None  # No partial catalog that disguises an unexpected source.
    describe = _descriptor_function()
    entries = []
    seen = set()
    for row in rows:
        if row.get("data-proses") != "giling":
            continue
        strong = row.find("strong")
        if strong is None or not _visible(strong):
            continue
        displayed_code = strong.get_text(strip=True)
        links = [row] if row.name == "a" else row.select("a.proses-aktif-list__detail[href]")
        for link in links:
            if (not _visible(link) or link.get("target") or link.has_attr("download")
                    or link.get("aria-disabled") == "true"):
                continue
            href = link.get("href", "")
            if not isinstance(href, str) or not href.startswith("/") or href.startswith("//"):
                continue
            try:
                descriptor = _descriptor(href, describe)
            except ValueError:
                descriptor = None
            if descriptor is None or descriptor["kode"] != displayed_code or href in seen:
                continue
            seen.add(href)
            entries.append(dict(alamat=href, kode=displayed_code,
                                label="Penggilingan aktif"))
            break  # The native duplicate Detail door is not another record.
    return dict(versi=1, cap=cap, konteks=context, sesi=session,
                sumber_sha256=hashlib.sha256(source_address.encode()).hexdigest(),
                entries=entries)
