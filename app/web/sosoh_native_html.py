"""Sosoh active structure; native data and writers remain authoritative."""
from __future__ import annotations

from functools import lru_cache
from html import unescape
from pathlib import Path
import re
from urllib.parse import parse_qsl

TABS = (("ringkasan", "Ringkasan"), ("bahan", "Bahan & silo"),
        ("hasil", "Hasil"), ("qc", "QC"), ("riwayat", "Riwayat"))
_PATH = re.compile(r"/proses-aktif/sosoh/([A-Za-z0-9][A-Za-z0-9._-]{0,79})")
_QUERY = {"tab_detail", "kembali_kerja", "halaman_hasil", "halaman_qc", "halaman_jeda", "buka", "nilai"}
FACTS = ("Kode proses", "Pemilik", "Gudang", "Mulai", "Durasi proses", "Durasi efektif", "Total jeda")


def deskripsi(path: str, query: str = "") -> dict | None:
    match = _PATH.fullmatch(path)
    if match is None or len(query) > 3000:
        return None
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=12)
    except ValueError:
        return None
    params = dict(pairs)
    if len(params) != len(pairs) or set(params) - _QUERY or params.get("buka") or params.get("nilai"):
        return None
    tab = params.get("tab_detail", "ringkasan")
    if tab not in dict(TABS):
        tab = "ringkasan"
    address = path + ("?" + query if query else "")
    return dict(kode=match[1], tab=tab, tabs=TABS, alamat=address, data_url=address, fakta=FACTS)


def active_schema(active, historical, labels, rice):
    """Validate ordered reference metadata; common active schema has no tail.

    This helper never supplies values or decides whether a kind is writable.
    A caller with historical keys must first obtain the native display order.
    """
    active = tuple(active)
    if (not active or not all(type(code) is str and code for code in active)
            or len(active) != len(set(active))
            or any(code not in active for code in historical)):
        return None
    if any(type(labels.get(code)) is not str or not labels[code] for code in active):
        return None
    rice = set(rice)
    return tuple(dict(jenis=code, nama=labels[code], beras=code in rice) for code in active)


def layout_schema(schema, operator: bool):
    if type(operator) is not bool or schema is None:
        raise ValueError("Native layout/schema must be explicit")
    main = tuple(row for row in schema if row["beras"]) if operator else tuple(schema[:6])
    more = tuple(row for row in schema if row not in main)
    return dict(layout="operator" if operator else "admin", hasil_utama=main, hasil_lain=more)


async def baca_schema_aktif(db):
    """Current native reference labels only; no process/stock/owner identifiers."""
    from app.penggilingan.gudang2.polishing import jenis_hasil, adalah_spek
    from app.services.stok import nama_produk
    active = await jenis_hasil(db)
    return active_schema(active, (), {kind: nama_produk(kind) for kind in active},
                         {kind for kind in active if adalah_spek(kind) or kind == "beras_b"})


async def baca_schema_hasil(db, process_id):
    """Direct document only: reuse the actual native aggregate's key order.

    form_selesai_penyosohan.ringkasan reads output_sosoh FIRST, then active
    kinds, then displays active kinds plus historical-only keys in that
    reader's iteration order. Do exactly that; do not add SQL/order policy.
    Quantities are read internally by the original aggregate but are NEVER
    returned here. Full native fresh data alone supplies boleh_catat/values.
    The common first-click active schema above never invokes this reader.
    """
    from app.penggilingan.gudang2 import polishing as p
    from app.services.stok import output_sosoh, nama_produk

    historical = await output_sosoh(db, process_id)
    active = await p.jenis_hasil(db)
    ordered = [*active, *(kind for kind in historical if kind not in active)]
    return active_schema(ordered, (), {kind: nama_produk(kind) for kind in ordered},
                         {kind for kind in ordered if p.adalah_spek(kind) or kind == "beras_b"})


@lru_cache(maxsize=1)
def qc_headers():
    """Immutable native table headers, without rendering QC data or forms."""
    source = (Path(__file__).parent / "templates/_qc_sosoh.html").read_text()
    heads = re.findall(r"<thead>.*?</thead>", source, re.S)
    titles = ("Total hasil timbang per jenis", "Estimasi waktu dan hasil tiap garapan",
              "Riwayat sampel dan hasil QC")
    if len(heads) != len(titles):
        raise ValueError("Native QC table structure requires review")
    result = []
    for title, header in zip(titles, heads):
        if "<h2>" + title + "</h2>" not in source or any(token in header for token in ("{{", "{%", "<input", "<button", "<a ")):
            raise ValueError("QC header must remain immutable source metadata")
        columns = [unescape(re.sub("<[^>]+>", "", label)).strip()
                   for label in re.findall(r"<th\b[^>]*>(.*?)</th>", header, re.S)]
        result.append(dict(title=title, header=header, columns=columns))
    return tuple(result)


def memakai_dokumen(request):
    document = (request.method == "GET" and request.headers.get("X-Pindah") != "1"
            and deskripsi(request.url.path, request.url.query) is not None
            and (request.headers.get("X-Kerangka-Halaman") == "1"
                 or request.headers.get("Sec-Fetch-Mode") == "navigate"
                 and request.headers.get("Sec-Fetch-Dest") in {"document", "empty"}))
    if not document:
        return False
    from app.web.portal.scope import is_customer_read
    return not is_customer_read(request) and getattr(request.state, "portal_scope", None) is None


async def kerangka(request, akun, konteks):
    """Positive native permission precedes scoped process/direct-schema reads.

    None means original renderer for unsupported negotiation/status/metadata.
    Direct historical fields use the original aggregate's key order only.
    The aggregate reads quantities internally; only reference metadata leaves.
    X-Pindah:1 is always full native GET; this module registers no route.
    """
    spec = deskripsi(request.url.path, request.url.query)
    if not memakai_dokumen(request) or spec is None:
        return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request) or getattr(request.state, "portal_scope", None) is not None:
        return None
    from app.web.sosoh_ringkas import izin
    await izin(akun.user, spec["kode"])

    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import PolishingProcess
    from app.services.cakupan_fasilitas import batas
    async with SessionLocal() as db:
        process = (await db.execute(select(PolishingProcess.id, PolishingProcess.status).where(
            PolishingProcess.kode_proses == spec["kode"],
            batas(akun.user, PolishingProcess)))).one_or_none()
        if process is None or process.status != "proses":
            return None
        schema = await baca_schema_hasil(db, process.id)
    if schema is None:
        return None
    try:
        qc = qc_headers()
    except ValueError:
        return None

    from hmu_identitas import peran as P
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.layar_pekerjaan import konteks_aman
    from app.web.tampilan import render
    spec.update(layout_schema(schema, P.operator_saja(akun.user.role)))
    spec.update(qc=qc, stamp=penanda_konteks(request, akun) + "|" + spec["alamat"])
    response = render(request, "sosoh_native_html.html", SOSOH_KERANGKA=spec,
                      layar="pekerjaan", breadcrumb_detail=spec["kode"],
                      kembali=konteks_aman(request.query_params.get("kembali_kerja"))
                               or "/pekerjaan?tab=berjalan",
                      **{k: v for k, v in konteks.items()
                         if k not in {"layar", "SHELL", "SOSOH_KERANGKA", "kembali", "breadcrumb_detail"}})
    response.headers["Cache-Control"] = "private, no-store"
    return response
