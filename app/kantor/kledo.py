"""Integrasi Kledo (akuntansi/finance) — READ-ONLY, khusus ADMIN (domain keuangan).

Sumber data keuangan RESMI via REST Kledo (host sama dgn GajiHub). Prinsip:
bot MERANGKUM, tak menghitung ulang — angka tetap dari Kledo (anti tumpang-tindih,
lihat memori no-redundancy-kledo). Tahap awal: READ-ONLY (tak ada tool tulis).

Env:
  KLEDO_API_KEY : Personal Access Token Kledo (scope finance). WAJIB untuk aktif.
  KLEDO_BASE    : opsional, base URL (default host akun perusahaan).

Endpoint /finance/* terkonfirmasi ada via probe (2026-08): accounts, invoices,
purchaseInvoices, contacts, products, quotes. Nama field respons diverifikasi &
dirapikan saat KLEDO_API_KEY sudah diset (probe balas 401 tanpa key finance).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

_BASE = os.getenv("KLEDO_BASE", "https://pthadimulyautama.api.kledo.com/api/v1")

# tool BACA (read-only). Belum ada tool tulis (tahap awal).
NAMA_TOOL = ("tagihan_kledo", "faktur_kledo", "kontak_kledo", "akun_kledo", "neraca_kledo")


def terkonfigurasi() -> bool:
    return bool(os.getenv("KLEDO_API_KEY"))


async def _boleh(user_id: int | None, role: str | None) -> bool:
    # Data keuangan sensitif → Direksi (admin) ATAU pemegang grant baca 'keuangan'
    # (mis. Elfira, saat RBAC terisi). Selaras domain RBAC 'keuangan'.
    if (role or "").strip().lower() == "admin":
        return True
    from app.kantor import rbac
    grants = await rbac.grants_user(user_id) if user_id is not None else {}
    return rbac.boleh(grants, "keuangan", "read")


def _hdr() -> dict:
    return {"Authorization": "Bearer " + os.environ["KLEDO_API_KEY"],
            "Accept": "application/json"}


def _get(path: str, params: dict | None = None):
    url = _BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_hdr())
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def _items(d) -> list:
    """Ambil list data dari respons Kledo (bentuk umum: {data:[...]} / {data:{data:[...]}})."""
    if isinstance(d, dict):
        data = d.get("data", d)
        if isinstance(data, dict):
            data = data.get("data", [])
        if isinstance(data, list):
            return data
    return d if isinstance(d, list) else []


def _first(it: dict, *keys, default="-"):
    for k in keys:
        v = it.get(k)
        if v not in (None, "", []):
            return v
    return default


def _rp(v) -> str:
    try:
        return f"Rp {float(v):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(v)


def _baris_transaksi(it: dict) -> str:
    """Invoice/purchaseInvoice: #ref · pihak · total · sisa(LUNAS bila 0) · j.tempo."""
    ref = _first(it, "ref_number", default="-")
    c = it.get("contact")
    pihak = c.get("name", "-") if isinstance(c, dict) else "-"
    total = _first(it, "amount_after_tax", "amount", default=None)
    due = it.get("due")
    jatuh = _first(it, "due_date", default="")
    bagian = [f"#{ref}", pihak]
    if total is not None:
        bagian.append(_rp(total))
    if due is not None:
        bagian.append("LUNAS" if float(due or 0) == 0 else f"sisa {_rp(due)}")
    if jatuh:
        bagian.append(f"j.tempo {jatuh}")
    return " · ".join(str(b) for b in bagian if b and b != "-")


def _baris_kontak(it: dict) -> str:
    bagian = [it.get("name", "-")]
    if it.get("company"):
        bagian.append(str(it["company"]))
    if it.get("receivable"):
        bagian.append(f"piutang {_rp(it['receivable'])}")
    if it.get("payable"):
        bagian.append(f"utang {_rp(it['payable'])}")
    return " · ".join(str(b) for b in bagian if b and b != "-")


def _baris_akun(it: dict) -> str:
    bagian = []
    if it.get("ref_code"):
        bagian.append(f"[{it['ref_code']}]")
    bagian.append(it.get("name", "-"))
    if it.get("balance") is not None:
        bagian.append(_rp(it["balance"]))
    return " · ".join(str(b) for b in bagian if b and b != "-")


async def _ambil(path: str, judul: str, formatter, params: dict | None = None) -> str:
    try:
        d = await asyncio.to_thread(_get, path, params or {"per_page": 15})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return ("Kledo menolak (401) — cek KLEDO_API_KEY punya scope finance.")
        return f"Kledo error {e.code} saat {judul}."
    except Exception as e:  # noqa: BLE001
        log.warning("kledo %s gagal: %s", path, e)
        return f"Gagal ambil {judul} dari Kledo."
    items = _items(d)
    if not items:
        return f"Tak ada data {judul} di Kledo."
    baris = [f"• {formatter(it)}" for it in items[:15]]
    return f"📒 {judul} (Kledo, {len(items)} teratas):\n" + "\n".join(baris)


async def _ringkas_transaksi(path: str, judul: str) -> str:
    """Total 'due'>0 (belum lunas) di SEMUA halaman + daftar teratas (jatuh tempo
    terdekat dulu). Menjawab 'berapa total tagihan/piutang belum dibayar'."""
    def fetch(page: int):
        return _get(path, {"per_page": 100, "page": page}).get("data", {})
    try:
        first = await asyncio.to_thread(fetch, 1)
    except urllib.error.HTTPError as e:
        return ("Kledo menolak (401) — cek scope KLEDO_API_KEY." if e.code == 401
                else f"Kledo error {e.code}.")
    except Exception:  # noqa: BLE001
        return f"Gagal ambil {judul} dari Kledo."
    last = int(first.get("last_page", 1) or 1)
    total = 0.0
    belum: list[dict] = []
    for page in range(1, min(last, 80) + 1):
        meta = first if page == 1 else await asyncio.to_thread(fetch, page)
        for it in meta.get("data", []):
            due = float(it.get("due") or 0)
            if due > 0:
                total += due
                belum.append(it)
    if not belum:
        return f"✅ Tidak ada {judul} yang belum lunas — semua sudah dibayar."
    belum.sort(key=lambda it: it.get("due_date") or "9999")
    baris = [f"• {_baris_transaksi(it)}" for it in belum[:10]]
    sisa = f"\n… +{len(belum) - 10} lagi" if len(belum) > 10 else ""
    return (f"📒 {judul} — BELUM LUNAS: *{_rp(total)}* dari {len(belum)} transaksi "
            f"(jatuh tempo terdekat dulu):\n" + "\n".join(baris) + sisa)


async def _neraca() -> str:
    """Ringkas Neraca (Balance Sheet) Kledo: total aset, HUTANG (liabilitas), modal.
    Jawaban RESMI untuk 'total hutang', 'total aset', 'posisi keuangan'."""
    from datetime import date
    hari = date.today().isoformat()
    try:
        d = await asyncio.to_thread(_get, "/reportings/balanceSheet", {"date": hari})
    except urllib.error.HTTPError as e:
        return f"Kledo error {e.code} saat ambil neraca."
    except Exception:  # noqa: BLE001
        return "Gagal ambil neraca dari Kledo."
    data = d.get("data", d)
    period = data.get(hari) if isinstance(data, dict) else None
    if not isinstance(period, dict):
        period = next((v for v in data.values() if isinstance(v, dict)), {}) if isinstance(data, dict) else {}
    aset = hutang = modal = 0.0
    for bagian, isi in period.items():
        if not isinstance(isi, dict):
            continue
        if "asset" in bagian.lower() or "aset" in (isi.get("name", "").lower()):
            aset = float(isi.get("total") or 0)
        for v in (isi.get("data") or {}).values():
            if not (isinstance(v, dict) and v.get("total") is not None):
                continue
            nm = (v.get("name") or "").lower()
            if "liabilit" in nm or "hutang" in nm:
                hutang += float(v["total"])
            elif "modal" in nm or "equity" in nm or "ekuitas" in nm:
                modal += float(v["total"])
    return (f"📊 Neraca Kledo per {hari}:\n"
            f"• Total Aset   : {_rp(aset)}\n"
            f"• Total Hutang : {_rp(hutang)}  (liabilitas)\n"
            f"• Total Modal  : {_rp(modal)}  (ekuitas)")


async def jalankan(nama_tool: str, args: dict, user_id: int | None = None,
                   role: str = "staff") -> str:
    if not terkonfigurasi():
        return "Integrasi Kledo belum aktif — set KLEDO_API_KEY (PAT finance) dulu."
    if not await _boleh(user_id, role):
        return "Data keuangan Kledo hanya untuk Direksi / pemegang akses keuangan."
    a = args or {}
    n = int(a.get("maks", 15) or 15)
    par = {"per_page": max(1, min(n, 50))}
    if nama_tool == "tagihan_kledo":
        return await _ringkas_transaksi("/finance/purchaseInvoices", "Tagihan/utang ke pemasok")
    if nama_tool == "faktur_kledo":
        return await _ringkas_transaksi("/finance/invoices", "Faktur/piutang dari pelanggan")
    if nama_tool == "kontak_kledo":
        return await _ambil("/finance/contacts", "Kontak (pelanggan/pemasok)",
                            _baris_kontak, par)
    if nama_tool == "akun_kledo":
        return await _ambil("/finance/accounts", "Daftar akun (chart of accounts)",
                            _baris_akun, par)
    if nama_tool == "neraca_kledo":
        return await _neraca()
    return f"(tool Kledo '{nama_tool}' tak dikenal)"


TOOLS = [
    {"name": "tagihan_kledo", "description":
        "TAGIHAN/utang ke pemasok dari Kledo: beri TOTAL yang belum lunas + daftar "
        "(jatuh tempo terdekat dulu). READ-ONLY, Direksi saja. Pakai untuk 'total "
        "utang', 'berapa tagihan belum dibayar', 'yang jatuh tempo'.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "faktur_kledo", "description":
        "FAKTUR/piutang dari pelanggan (Kledo): beri TOTAL yang belum tertagih + "
        "daftar. READ-ONLY, Direksi saja. Pakai untuk 'total piutang', 'faktur belum "
        "dibayar pelanggan'.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "kontak_kledo", "description":
        "Lihat KONTAK Kledo (pelanggan & pemasok). READ-ONLY, Direksi saja.",
     "input_schema": {"type": "object", "properties": {
         "maks": {"type": "integer", "description": "Jumlah maks (default 15)."}}}},
    {"name": "akun_kledo", "description":
        "Lihat DAFTAR AKUN / chart of accounts Kledo. READ-ONLY, Direksi saja.",
     "input_schema": {"type": "object", "properties": {
         "maks": {"type": "integer", "description": "Jumlah maks (default 15)."}}}},
    {"name": "neraca_kledo", "description":
        "NERACA (Balance Sheet) Kledo — total ASET, HUTANG (liabilitas), MODAL "
        "(ekuitas) resmi per hari ini. READ-ONLY, Direksi saja. Pakai untuk 'total "
        "hutang', 'total aset', 'posisi/kondisi keuangan', 'modal berapa'. Ini "
        "sumber RESMI total hutang (bukan sekadar tagihan invoice).",
     "input_schema": {"type": "object", "properties": {}}},
]
