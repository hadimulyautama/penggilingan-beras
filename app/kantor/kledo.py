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
NAMA_TOOL = ("tagihan_kledo", "faktur_kledo", "kontak_kledo", "akun_kledo", "neraca_kledo",
             "labarugi_kledo", "aruskas_kledo", "umur_hutang_kledo", "umur_piutang_kledo",
             "saldo_bank_kledo", "penjualan_kledo", "hutang_kontak_kledo",
             "piutang_kontak_kledo")


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


# ── util laporan (report) ────────────────────────────────────────────────
def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _periode(a: dict) -> tuple[str, str]:
    """(date_from, date_to). Default: bulan berjalan (tgl 1 → hari ini)."""
    from datetime import date
    t = date.today()
    dari = (a.get("dari") or t.replace(day=1).isoformat())
    sampai = (a.get("sampai") or t.isoformat())
    return dari, sampai


async def _json(path: str, params: dict | None, judul: str):
    """Ambil JSON Kledo → (data|None, err_str|None). Error jadi teks siap-tampil."""
    try:
        return await asyncio.to_thread(_get, path, params), None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None, "Kledo menolak (401) — cek KLEDO_API_KEY punya scope finance."
        return None, f"Kledo error {e.code} saat {judul}."
    except Exception as e:  # noqa: BLE001
        log.warning("kledo %s gagal: %s", path, e)
        return None, f"Gagal ambil {judul} dari Kledo."


async def _labarugi(a: dict) -> str:
    """Laba-Rugi (profitLoss). Angka RESMI dari objek `total` Kledo (tak dihitung ulang).
    Bucket `total`: trading_income, cost_of_sales, gross_profit, expenses, net_profit."""
    dari, sampai = _periode(a)
    d, err = await _json("/reportings/profitLoss",
                         {"date_from": dari, "date_to": sampai}, "laba-rugi")
    if err:
        return err
    tot = (((d or {}).get("data") or {}).get("total")) or {}
    if not tot:
        return f"Tak ada data laba-rugi di Kledo untuk {dari} → {sampai}."
    pend = _num(tot.get("trading_income"))
    hpp = _num(tot.get("cost_of_sales"))
    kotor = _num(tot.get("gross_profit"))
    beban = _num(tot.get("expenses"))
    bersih = _num(tot.get("net_profit"))
    tag = "laba" if bersih >= 0 else "RUGI"
    return (f"📈 Laba-Rugi Kledo ({dari} → {sampai}):\n"
            f"• Pendapatan  : {_rp(pend)}\n"
            f"• Beban Pokok : {_rp(hpp)}  (HPP)\n"
            f"• Laba Kotor  : {_rp(kotor)}\n"
            f"• Beban Usaha : {_rp(beban)}\n"
            f"• Laba Bersih : {_rp(bersih)}  ({tag})")


async def _aruskas(a: dict) -> str:
    """Arus Kas (cashFlow): kas masuk/keluar/bersih + saldo awal→akhir + per aktivitas."""
    dari, sampai = _periode(a)
    d, err = await _json("/reportings/cashFlow",
                         {"date_from": dari, "date_to": sampai}, "arus kas")
    if err:
        return err
    data = (d or {}).get("data") or {}
    groups = data.get("data") or []
    tot = data.get("total") or {}
    masuk = keluar = 0.0
    baris = []
    for g in groups:
        for sub in (g.get("data") or []):
            v = _num(sub.get("total"))
            if v >= 0:
                masuk += v
            else:
                keluar += v
        baris.append(f"• {g.get('name', '-')}: {_rp(_num(g.get('total')))}")
    bersih = _num(tot.get("net_cash_flows"))
    awal = _num(tot.get("beginning_period"))
    akhir = _num(tot.get("end_period"))
    return (f"💵 Arus Kas Kledo ({dari} → {sampai}):\n"
            f"• Kas masuk   : {_rp(masuk)}\n"
            f"• Kas keluar  : {_rp(keluar)}\n"
            f"• Arus bersih : {_rp(bersih)}\n"
            f"• Saldo awal  : {_rp(awal)} → akhir {_rp(akhir)}\n"
            "Per aktivitas:\n" + "\n".join(baris))


async def _umur(path: str, judul: str, pihak: str) -> str:
    """Umur hutang/piutang (agedPayable/agedReceivable).

    Bentuk `due` per kontak: {'-2': belum jatuh tempo, '-1': TOTAL telat (=Σ 0..4),
    '0'..'4': umur telat per bulan}. Jadi total = due['-2'] + due['-1'] (jangan
    jumlahkan '-1' bersama 0..4 — nanti dobel)."""
    from datetime import date
    hari = date.today().isoformat()
    d, err = await _json(path, {"date": hari, "per_page": 200}, judul.lower())
    if err:
        return err
    items = _items(d)
    if not items:
        return f"✅ Tidak ada {judul.lower()} di Kledo per {hari}."
    belum = sum(_num((i.get("due") or {}).get("-2")) for i in items)
    telat = sum(_num((i.get("due") or {}).get("-1")) for i in items)
    top = sorted((i for i in items if _num((i.get("due") or {}).get("-1")) > 0),
                 key=lambda i: _num(i["due"].get("-1")), reverse=True)[:5]
    baris = [f"• {i.get('name', '-')} · telat {_rp(_num(i['due'].get('-1')))}"
             for i in top]
    body = (f"\n{pihak} telat teratas:\n" + "\n".join(baris)) if baris \
        else "\n(Tidak ada yang telat — semua belum jatuh tempo.)"
    return (f"📅 {judul} Kledo per {hari}:\n"
            f"• Belum jatuh tempo : {_rp(belum)}\n"
            f"• Sudah jatuh tempo : {_rp(telat)}  (telat)\n"
            f"• Total             : {_rp(belum + telat)}"
            + body)


async def _saldo_bank() -> str:
    """Saldo kas & bank per rekening (/finance/bank/balances)."""
    d, err = await _json("/finance/bank/balances", None, "saldo bank")
    if err:
        return err
    items = _items(d)
    if not items:
        return "Tak ada data rekening kas/bank di Kledo."
    items = sorted(items, key=lambda i: _num(i.get("balance")), reverse=True)
    total = sum(_num(i.get("balance")) for i in items)
    baris = []
    for i in items:
        code = i.get("ref_code")
        tag = f"[{code}] " if code else ""
        baris.append(f"• {tag}{i.get('name', '-')}: {_rp(_num(i.get('balance')))}")
    return (f"🏦 Saldo Kas & Bank Kledo ({len(items)} rekening):\n"
            + "\n".join(baris) + f"\nTotal: *{_rp(total)}*")


async def _penjualan(a: dict) -> str:
    """Penjualan per produk (salesPerProduct): total + top produk. Tanpa data sensitif
    (harga pokok/margin tak ditampilkan) — cukup nama, qty, nilai."""
    dari, sampai = _periode(a)
    d, err = await _json("/reportings/salesPerProduct",
                         {"date_from": dari, "date_to": sampai}, "penjualan")
    if err:
        return err
    data = (d or {}).get("data") or {}
    items = data.get("data") or []
    ts = data.get("total_sales")
    total = _num(ts.get("amount_after_tax")) if isinstance(ts, dict) else _num(ts)
    if not items:
        return f"Tak ada penjualan pada {dari} → {sampai} di Kledo."
    items = sorted(items, key=lambda i: _num(i.get("amount_after_tax")),
                   reverse=True)[:10]
    baris = []
    for i in items:
        p = i.get("product_with_price") or {}
        qty = f"{_num(i.get('qty_net')):,.0f}".replace(",", ".")
        baris.append(f"• {p.get('name', '-')} · {qty} unit · "
                     f"{_rp(_num(i.get('amount_after_tax')))}")
    return (f"🛒 Penjualan per Produk Kledo ({dari} → {sampai}):\n"
            f"Total penjualan: *{_rp(total)}*\nTop produk:\n" + "\n".join(baris))


async def _kontak_saldo(a: dict, jenis: str) -> str:
    """Hutang/piutang ke satu kontak. Tampilkan DUA angka bila beda: saldo buku besar
    (finance/contacts payable/receivable) DAN umur (aged) — karakter data Kledo, tak
    boleh pilih satu (mis. Mas Catur: ledger 300jt vs aged bila ada bagian belum-jt)."""
    nama = (a.get("nama") or "").strip()
    if not nama:
        return ("Sebutkan nama kontak, mis. "
                f"{'hutang' if jenis == 'hutang' else 'piutang'}_kontak_kledo "
                "nama='Mas Catur'.")
    field = "payable" if jenis == "hutang" else "receivable"
    aged_path = "/reportings/agedPayable" if jenis == "hutang" \
        else "/reportings/agedReceivable"
    label = "Hutang ke" if jenis == "hutang" else "Piutang dari"
    # 1) saldo buku besar per kontak
    d, err = await _json("/finance/contacts", {"search": nama}, "kontak")
    if err:
        return err
    kontak = _items(d)
    ledger = None
    nm_match = nama
    if kontak:
        k = kontak[0]
        nm_match = k.get("name", nama)
        ledger = _num(k.get(field))
    # 2) umur (aged) — filter baris yang namanya cocok
    from datetime import date
    hari = date.today().isoformat()
    d2, err2 = await _json(aged_path, {"date": hari, "per_page": 200}, "umur")
    rows = []
    if not err2:
        low = nama.lower()
        for i in _items(d2):
            nm = (i.get("name") or "").lower()
            comp = (str(i.get("company") or "")).lower()
            if low in nm or (comp and low in comp):
                rows.append(i)
    belum = sum(_num(i["due"].get("-2")) for i in rows)
    telat = sum(_num(i["due"].get("-1")) for i in rows)
    aged_total = belum + telat
    if ledger is None and not rows:
        return f"Kontak '{nama}' tak ditemukan di Kledo."
    out = [f"🔎 {label} \"{nm_match}\" (Kledo):"]
    if ledger is not None:
        out.append(f"• Buku besar ({field}) : {_rp(ledger)}")
    if rows:
        out.append(f"• Umur (aged) total    : {_rp(aged_total)}  "
                   f"(belum jt {_rp(belum)} + telat {_rp(telat)})")
    else:
        out.append("• Umur (aged)          : tak ada faktur ber-jatuh-tempo")
    if ledger is not None and rows and abs(ledger - aged_total) > 1:
        out.append("⚠️ Dua angka beda (wajar di Kledo): 'buku besar' = saldo akun "
                   "kontak; 'aged' = faktur ber-jatuh-tempo. Sampaikan KEDUANYA.")
    if len(kontak) > 1:
        out.append(f"(Ada {len(kontak)} kontak cocok; ditampilkan '{nm_match}'.)")
    return "\n".join(out)


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
    if nama_tool == "labarugi_kledo":
        return await _labarugi(a)
    if nama_tool == "aruskas_kledo":
        return await _aruskas(a)
    if nama_tool == "umur_hutang_kledo":
        return await _umur("/reportings/agedPayable", "Umur Hutang", "Pemasok")
    if nama_tool == "umur_piutang_kledo":
        return await _umur("/reportings/agedReceivable", "Umur Piutang", "Pelanggan")
    if nama_tool == "saldo_bank_kledo":
        return await _saldo_bank()
    if nama_tool == "penjualan_kledo":
        return await _penjualan(a)
    if nama_tool == "hutang_kontak_kledo":
        return await _kontak_saldo(a, "hutang")
    if nama_tool == "piutang_kontak_kledo":
        return await _kontak_saldo(a, "piutang")
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
    {"name": "labarugi_kledo", "description":
        "LABA-RUGI (profit & loss) Kledo: pendapatan, HPP, laba kotor, beban usaha, "
        "laba bersih. Default periode BULAN BERJALAN. READ-ONLY, Direksi saja. Pakai "
        "untuk 'laba bulan ini', 'rugi/untung berapa', 'kinerja/omzet', 'laba-rugi'. "
        "Angka RESMI dari Kledo.",
     "input_schema": {"type": "object", "properties": {
         "dari": {"type": "string", "description": "Tanggal mulai YYYY-MM-DD (opsional)."},
         "sampai": {"type": "string", "description": "Tanggal akhir YYYY-MM-DD (opsional)."}}}},
    {"name": "aruskas_kledo", "description":
        "ARUS KAS (cash flow) Kledo: kas masuk, kas keluar, arus bersih, saldo awal→akhir, "
        "rincian per aktivitas (operasional/investasi/pendanaan). Default BULAN BERJALAN. "
        "READ-ONLY, Direksi saja. Pakai untuk 'arus kas', 'uang masuk keluar', 'cashflow'.",
     "input_schema": {"type": "object", "properties": {
         "dari": {"type": "string", "description": "Tanggal mulai YYYY-MM-DD (opsional)."},
         "sampai": {"type": "string", "description": "Tanggal akhir YYYY-MM-DD (opsional)."}}}},
    {"name": "umur_hutang_kledo", "description":
        "UMUR HUTANG (aged payable) Kledo per hari ini: total belum jatuh tempo vs sudah "
        "telat + pemasok telat teratas. READ-ONLY, Direksi saja. Pakai untuk 'hutang "
        "telat', 'yang jatuh tempo', 'umur hutang', 'tunggakan ke pemasok'.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "umur_piutang_kledo", "description":
        "UMUR PIUTANG (aged receivable) Kledo per hari ini: total belum jatuh tempo vs "
        "telat + pelanggan telat teratas. READ-ONLY, Direksi saja. Pakai untuk 'piutang "
        "telat', 'pelanggan nunggak', 'umur piutang', 'tagihan macet'.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "saldo_bank_kledo", "description":
        "SALDO KAS & BANK Kledo per rekening + total. READ-ONLY, Direksi saja. Pakai "
        "untuk 'saldo kas', 'uang di bank', 'saldo rekening', 'posisi kas'.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "penjualan_kledo", "description":
        "PENJUALAN per produk Kledo: total + produk terlaris (nama, qty, nilai). Default "
        "BULAN BERJALAN. READ-ONLY, Direksi saja. Pakai untuk 'produk terlaris', "
        "'penjualan bulan ini', 'top produk', 'omzet per produk'.",
     "input_schema": {"type": "object", "properties": {
         "dari": {"type": "string", "description": "Tanggal mulai YYYY-MM-DD (opsional)."},
         "sampai": {"type": "string", "description": "Tanggal akhir YYYY-MM-DD (opsional)."}}}},
    {"name": "hutang_kontak_kledo", "description":
        "HUTANG ke SATU pemasok/kontak (Kledo). Beri DUA angka bila beda: saldo buku besar "
        "(payable) DAN umur (aged) — keduanya benar dari sudut berbeda, jangan pilih satu. "
        "READ-ONLY, Direksi saja. Pakai untuk 'hutang ke <nama>', 'utang kita ke <nama>'.",
     "input_schema": {"type": "object", "properties": {
         "nama": {"type": "string", "description": "Nama pemasok/kontak (wajib)."}},
         "required": ["nama"]}},
    {"name": "piutang_kontak_kledo", "description":
        "PIUTANG dari SATU pelanggan/kontak (Kledo). Beri DUA angka bila beda: saldo buku "
        "besar (receivable) DAN umur (aged). READ-ONLY, Direksi saja. Pakai untuk 'piutang "
        "dari <nama>', 'berapa <nama> masih ngutang'.",
     "input_schema": {"type": "object", "properties": {
         "nama": {"type": "string", "description": "Nama pelanggan/kontak (wajib)."}},
         "required": ["nama"]}},
]
