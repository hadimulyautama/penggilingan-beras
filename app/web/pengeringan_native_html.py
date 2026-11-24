"""Struktur dua fase dryer; otoritas dan angka tetap pembaca native.

Tidak ada model palsu, agregasi hasil, atau writer. Caller harus memakai row
DryingLot yang baru dibaca setelah guard native dan pengalihan fase selesai.
Katalog klik pertama hanya membaca baris Pekerjaan yang sudah dirender sah.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[2]
FASE = ("pengeringan", "pendinginan")
TAB = (("ringkasan", "Ringkasan"), ("bahan", "Bahan"),
       ("pengukuran", "Pengukuran"), ("riwayat", "Riwayat"))
POLA = re.compile(r"/proses-aktif/(pengeringan|pendinginan)/([A-Za-z0-9][A-Za-z0-9._-]{0,79})")
PARAMETER = frozenset(("tab_detail", "kembali_kerja", "halaman_ukur", "halaman_dingin", "halaman_jeda"))


def deskripsi(path, query=""):
    match = POLA.fullmatch(path)
    if not match or len(query) > 3000 or re.search(r"%(?![0-9a-fA-F]{2})", query):
        return None
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=8, errors="strict")
    except (ValueError, UnicodeError):
        return None
    q = dict(pairs)
    # Termasuk buka/nilai kosong: deep-link tindakan tetap renderer native.
    if len(q) != len(pairs) or set(q) - PARAMETER:
        return None
    selected = q.get("tab_detail")
    if selected not in dict(TAB):
        selected = ("pengukuran" if q.get("halaman_ukur") else "riwayat"
                    if q.get("halaman_dingin") or q.get("halaman_jeda") else "ringkasan")
    for key in ("halaman_ukur", "halaman_dingin", "halaman_jeda"):
        if key in q and not re.fullmatch(r"[1-9][0-9]{0,8}", q[key]):
            return None  # Kasus invalid/legacy tetap kontrak native, bukan normalisasi baru.
    address = path + ("?" + query if query else "")
    return dict(fase=match[1], kode=match[2], tab=selected, tabs=TAB,
                alamat=address, data_url=address)


def fase_aktif(fase, status, selesai_pendinginan, dryer_id):
    return (fase in FASE and dryer_id is not None and selesai_pendinginan is None
            and status == ("proses" if fase == "pengeringan" else "selesai"))


@lru_cache(maxsize=1)
def metadata():
    """Hanya konstanta label/kolom dari source; tidak memanggil penyusun data."""
    paths = [ROOT / "app/services/proses_aktif.py",
             ROOT / "app/web/templates/detail_pengeringan.html",
             ROOT / "app/web/templates/detail_pendinginan_aktif.html"]
    texts = [p.read_text() for p in paths]
    tree = ast.parse(texts[0])
    tables = {}
    wanted = {"Asal bahan gabah", "Riwayat pengukuran kadar air", "Catatan pendinginan"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in {"_bagian", "_log"}:
            continue
        for i, arg in enumerate(node.args[:-1]):
            if isinstance(arg, ast.Constant) and arg.value in wanted:
                columns = ast.literal_eval(node.args[i + 1])
                if not isinstance(columns, list) or not all(type(x) is str for x in columns):
                    raise ValueError("Kolom native dryer berubah")
                tables[arg.value] = columns
    if set(tables) != wanted:
        raise ValueError("Bagian native dryer berubah")
    for text, fase in zip(texts[1:], FASE):
        if f"<h1>{fase.title()} aktif</h1>" not in text:
            raise ValueError("Judul fase native berubah")
        for key, label in TAB:
            if f"('{key}','{label}')" not in text:
                raise ValueError("Tab native dryer berubah")
    facts = ("Kode lot", "Pemilik bahan", "Mesin pengering", "Mode dryer", "Berat bahan",
             "Mulai proses", "Mulai fase ini", "Dicatat oleh", "Waktu berlalu", "Selesai pengeringan")
    if any(label not in "\n".join(texts) for label in facts):
        raise ValueError("Label fakta dryer native berubah")
    return dict(tables=tables, fakta=facts,
                inputs={str(p.relative_to(ROOT)): hashlib.sha256(t.encode()).hexdigest()
                        for p, t in zip(paths, texts)})


async def kerangka(request, akun, *, jenis, lot, db):
    """Caller native tetap pemilik row/redirect; guard positif diperiksa ulang.

    Tidak menerima scope, status atau aktor dari query/header. Row ini milik
    transaksi baca caller, bukan snapshot yang dikirim browser.
    """
    spec = deskripsi(request.url.path, request.url.query)
    if (request.method != "GET" or request.headers.get("X-Pindah") == "1"
            or spec is None or jenis != spec["fase"]
            or not (request.headers.get("X-Kerangka-Halaman") == "1"
                    or request.headers.get("Sec-Fetch-Mode") == "navigate"
                    and request.headers.get("Sec-Fetch-Dest") in {"document", "empty"})):
        return None
    from app.web.portal.scope import is_customer_read
    if (is_customer_read(request) or getattr(request.state, "portal_scope", None) is not None
            or akun is None or getattr(request.state, "akun", None) is not akun
            or getattr(akun, "harus_ganti_sandi", None) is not False
            or lot.kode_lot != spec["kode"]
            or not fase_aktif(jenis, lot.status, lot.waktu_selesai_pendinginan, lot.dryer_id)):
        return None
    from app.web.api import _is_drying_operator
    from fastapi import HTTPException
    if not await _is_drying_operator(akun.user, kode_lot=spec["kode"]):
        raise HTTPException(403, "Proses ini berada di gudang lain. Pilih gudang kerja yang sesuai.")
    if jenis == "pendinginan":
        # Sama dengan syarat _lot(pendinginan_selesai=False). Jangan memberi
        # shell aktif pada sumber yang telah berpindah keluar dari dryer.
        from sqlalchemy import exists, select
        from app.models import SiloStorage
        if await db.scalar(select(exists().where(SiloStorage.drying_lot_id == lot.id))):
            return None
    from app.web.halaman_bertahap import konteks_kerangka, penanda_konteks
    from app.web.layar_pekerjaan import konteks_aman
    from app.web.tampilan import render
    context = await konteks_kerangka(request, akun)
    spec.update(metadata())
    spec["stamp"] = penanda_konteks(request, akun) + "|" + spec["alamat"]
    response = render(request, "pengeringan_native_html.html", **{
        **context, "DRYER_KERANGKA": spec, "layar": "pekerjaan",
        "kembali": konteks_aman(request.query_params.get("kembali_kerja")) or "/pekerjaan?tab=berjalan",
        "breadcrumb_detail": spec["kode"],
    })
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"
    return response


@lru_cache(maxsize=1)
def aset():
    folder = ROOT / "app/web/static"
    value = json.loads((folder / "kerangka-pengeringan-ui.meta.json").read_text())
    if (value.get("versi") != 1 or value.get("variants") != list(FASE)
            or hashlib.sha256((folder / "kerangka-pengeringan-ui.js").read_bytes()).hexdigest() != value.get("aset_sha256")):
        raise ValueError("Paket struktur dryer tidak cocok")
    return value


def katalog(html, *, source_address, cap, context, session):
    """Baca DOM Work yang sudah sah; tidak query per baris atau menebak ID."""
    from app.web.giling_work_catalog import _visible
    from bs4 import BeautifulSoup
    if (type(html) is not str or len(html.encode()) > 8 * 1024 * 1024
            or not all(type(v) is str and 0 < len(v) <= 512 for v in (cap, context, session))
            or type(source_address) is not str or len(source_address) > 4096):
        return None
    try:
        source = urlsplit(source_address)
    except ValueError:
        return None
    if source.scheme or source.netloc or source.fragment or source.path not in {"/pekerjaan", "/berjalan"}:
        return None
    doc = BeautifulSoup(html, "html.parser")
    rows = [r for r in doc.select('section[data-blok][aria-label="Proses aktif"] .proses-aktif-list > .proses-aktif-list__row') if _visible(r)]
    if len(rows) > 50:
        return None
    entries, seen = [], set()
    for row in rows:
        phase = row.get("data-proses")
        strong = row.find("strong")
        if phase not in FASE or strong is None or not _visible(strong):
            continue
        code = strong.get_text(strip=True)
        links = [row] if row.name == "a" else row.select("a.proses-aktif-list__detail[href]")
        for link in links:
            if (not _visible(link) or link.has_attr("target") or link.has_attr("download")
                    or link.get("aria-disabled") == "true"):
                continue
            href = link.get("href", "")
            if not isinstance(href, str) or not href.startswith("/") or href.startswith("//"):
                continue
            try:
                address = urlsplit(href)
                spec = None if address.scheme or address.netloc or address.fragment else deskripsi(address.path, address.query)
            except ValueError:
                spec = None
            if spec is None or spec["kode"] != code or spec["fase"] != phase or href in seen:
                continue
            seen.add(href)
            entries.append(dict(alamat=href, kode=code, fase=phase, label=phase.title() + " aktif"))
            break
    return dict(versi=1, cap=cap, konteks=context, sesi=session, sumber=aset()["sumber"],
                sumber_sha256=hashlib.sha256(source_address.encode()).hexdigest(), entries=entries)
