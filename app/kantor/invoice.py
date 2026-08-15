"""Otak PEMROSES INVOICE/LANGGANAN (Phase 1) — ekstrak dokumen → USULAN 2 aksi:
  (a) Arsip: taruh file di folder yang benar,
  (b) IT Management: perbarui biaya/renewal/catatan layanan terkait.

Fase ini murni MENGHASILKAN USULAN (tak menulis, tak mengeksekusi). Pemasangan gerbang
konfirmasi + poller auto-watch = increment berikutnya. Ekstraksi pakai Haiku (murah),
teks PDF diambil pypdf dulu (gratis); OCR vision hanya bila tak ada teks.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from app.ai import guard
from app.config import settings

log = logging.getLogger("kantor.invoice")

# Tujuan FINAL dokumen langganan (kategori resmi 08/03).
KATEGORI_LANGGANAN = "08 - IT & Sistem / 03 - Lisensi & Langganan"
LANGGANAN_FOLDER_ID = "1_IVqi1Nk56Jb8HywsSfTF3EHkiWUbyVJ"
# Auto-arsip HANYA memproses folder ini — file yang sudah dinyatakan SIAP oleh petugas
# (tahap 00/01/02 = dikelola manusia: pilah, cetak, scan). Bot tak menyentuhnya.
STAGE_FINAL_ID = "1Apex3m9QnH3bCnkq_9xLK9c4MFTStYJe"   # 03 - Siap Arsip Final
_ID_BULAN = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep",
             "Okt", "Nov", "Des"]

_TOOL = [{
    "name": "ekstrak_invoice",
    "description": "Ekstrak data dari dokumen invoice/tagihan/kwitansi/langganan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "jenis": {"type": "string",
                      "enum": ["invoice", "kwitansi", "faktur_pajak", "kontrak", "lainnya"],
                      "description": "Jenis dokumen. 'faktur_pajak' hanya untuk Faktur "
                                     "Pajak resmi (ada NSFP/QR pajak)."},
            "langganan": {"type": "boolean",
                          "description": "true bila ini langganan/lisensi software/layanan "
                                         "BERULANG (SaaS, hosting, domain, GPS, dll)."},
            "vendor": {"type": "string", "description": "Nama penerbit/penjual."},
            "layanan": {"type": "string",
                        "description": "Nama produk/layanan, mis. 'Kledo Elite', 'GajiHub'."},
            "no_invoice": {"type": "string"},
            "tanggal": {"type": "string",
                        "description": "Tanggal dokumen YYYY-MM-DD dari isi. JANGAN mengarang."},
            "total": {"type": "string", "description": "Nominal total, mis. 'Rp 4.659.333'."},
            "lunas": {"type": "boolean", "description": "true bila tertulis sudah dibayar/lunas."},
            "siklus": {"type": "string", "enum": ["bulanan", "tahunan", "sekali", "tak jelas"]},
            "perlu_fisik": {"type": "boolean",
                            "description": "true bila dokumen BERNILAI HUKUM & perlu salinan "
                                           "fisik: ada tanda tangan basah, materai, sertifikat, "
                                           "kontrak/surat resmi ditandatangani. Invoice/nota/"
                                           "kwitansi digital biasa (dokumen kerja) → false."},
            "keyakinan": {"type": "string", "enum": ["tinggi", "sedang", "rendah"]},
        },
        "required": ["jenis", "vendor", "keyakinan"],
    },
}]

_SYS = (
    "Kamu pengekstrak dokumen keuangan/langganan untuk arsip perusahaan PT Hadi Mulya "
    "Utama. Isi tool 'ekstrak_invoice' dari isi dokumen. JUJUR & jangan mengarang: bila "
    "sebuah field tak ada di dokumen, kosongkan. 'tanggal' WAJIB format YYYY-MM-DD dari "
    "dokumen. 'langganan'=true hanya untuk langganan/lisensi berulang (software/SaaS/"
    "hosting/domain/GPS). 'perlu_fisik'=true HANYA untuk dokumen bernilai hukum (tanda "
    "tangan basah/materai/sertifikat/kontrak resmi ditandatangani); invoice/nota/kwitansi "
    "digital biasa → false. Bila dokumen jelas bukan invoice/tagihan → jenis='lainnya'."
)


async def ekstrak(teks: str, nama: str = "") -> dict:
    """Ekstrak field terstruktur dari teks dokumen (Haiku, forced-tool)."""
    isi = f"Nama file: {nama}\n\n{(teks or '')[:6000]}"
    resp = await guard.panggil(
        pemanggil="invoice",
        model=settings.miniapp_model,  # Haiku (murah)
        max_tokens=400,
        system=_SYS,
        tools=_TOOL,
        tool_choice={"type": "tool", "name": "ekstrak_invoice"},
        messages=[{"role": "user", "content": isi}],
    )
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use" and b.name == "ekstrak_invoice":
            return b.input or {}
    return {}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def cocok_layanan(vendor: str, layanan: str, services: list[list]) -> tuple[str, int] | None:
    """Cocokkan vendor/layanan ekstrak → baris Services (nama, indeks). None bila tak ada.
    `services` = baris tab Services (kolom B=nama di indeks 1)."""
    kandidat = f"{_norm(vendor)} {_norm(layanan)}"
    kata = {k for k in kandidat.split() if len(k) >= 3}
    for i, r in enumerate(services):
        nama = r[1] if len(r) > 1 else ""
        tok = {k for k in _norm(nama).split() if len(k) >= 3}
        if tok and (tok & kata):
            return nama, i
    return None


def _tgl_id(iso: str) -> tuple[date | None, str]:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return None, ""
    try:
        d = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None, ""
    return d, f"{d.day} {_ID_BULAN[d.month]} {d.year}"


def susun_usulan(data: dict, nama_file: str, services: list[list]) -> dict:
    """Bangun USULAN (deterministik) dari hasil ekstrak. Tak menulis apa pun.
    → {invoice, langganan, layanan_cocok, folder, nama_file, it_updates, ringkas}."""
    jenis = (data.get("jenis") or "lainnya").lower()
    langganan = bool(data.get("langganan"))
    vendor = data.get("vendor", "")
    layanan = data.get("layanan", "")
    no_inv = data.get("no_invoice", "")
    total = data.get("total", "")
    lunas = bool(data.get("lunas"))
    siklus = (data.get("siklus") or "").lower()
    perlu_fisik = bool(data.get("perlu_fisik"))
    d, tgl_str = _tgl_id(data.get("tanggal", ""))

    invoice = jenis in ("invoice", "kwitansi")
    cocok = cocok_layanan(vendor, layanan, services) if services else None
    svc_nama = cocok[0] if cocok else ""
    svc_idx = cocok[1] if cocok else -1

    # (a) Arsip FINAL — auto-arsip hanya jalan dari '03 - Siap Arsip Final' (sudah divet
    # petugas: cetak/scan selesai). Bot memindahkan file ke kategori resmi.
    folder, folder_id = KATEGORI_LANGGANAN, LANGGANAN_FOLDER_ID
    status = "LUNAS" if lunas else "BELUM LUNAS"
    label = svc_nama or layanan or vendor or "Dokumen"
    bagian = [label]
    if no_inv:
        bagian.append(f"Invoice {no_inv.replace('/', '-')}")
    if tgl_str:
        bagian.append(tgl_str)
    if invoice:
        bagian.append(status)
    nama_usul = " - ".join(bagian) + ".pdf"

    # (b) IT Management (hanya bila cocok layanan & ini langganan/invoice)
    it_updates: list[tuple[str, str]] = []
    if cocok and (langganan or invoice):
        if total:
            suf = {"bulanan": "/bln", "tahunan": "/thn", "sekali": ""}.get(siklus, "")
            it_updates.append(("biaya", f"{total}{suf}"))
        if siklus in ("bulanan", "tahunan", "sekali"):
            it_updates.append(("siklus", siklus))
        if siklus == "tahunan" and d:
            nxt = date(d.year + 1, d.month, d.day)
            it_updates.append(("renewal", f"{nxt.day} {_ID_BULAN[nxt.month]} {nxt.year}"))
        if no_inv:
            it_updates.append(("catatan_tambah",
                               f"Invoice {no_inv} ({tgl_str or data.get('tanggal','')}) {status}."))

    return {
        "invoice": invoice, "langganan": langganan, "jenis": jenis,
        "keyakinan": data.get("keyakinan", ""), "perlu_fisik": perlu_fisik,
        "layanan_cocok": svc_nama, "layanan_idx": svc_idx, "vendor": vendor,
        "folder": folder, "folder_id": folder_id,
        "nama_file": nama_usul, "it_updates": it_updates,
    }


# field → kolom Services (untuk resolusi sel konkret saat menyusun payload gerbang).
_COL = {"biaya": "J", "siklus": "N", "renewal": "K", "paket": "I", "status": "M"}


def resolve_updates(services: list[list], idx: int,
                    it_updates: list[tuple[str, str]]) -> list[list[str]]:
    """it_updates (field,nilai) → [[range_sel, nilai], ...] konkret. `catatan_tambah`
    di-append ke catatan lama (kolom L) tanpa duplikat. Deterministik, mudah diuji."""
    if idx < 0:
        return []
    row = idx + 2
    lama_catatan = services[idx][11] if len(services[idx]) > 11 else ""
    out: list[list[str]] = []
    for field, nilai in it_updates:
        if field == "catatan_tambah":
            inti = nilai.strip(". ")
            if inti and inti in (lama_catatan or ""):
                continue
            baru = (f"{lama_catatan} | {nilai}").strip(" |") if lama_catatan else nilai
            out.append([f"Services!L{row}", baru])
        elif field in _COL:
            out.append([f"Services!{_COL[field]}{row}", nilai])
    return out


async def usul_dari_file(file_id: str, mime: str, nama: str,
                         asal_id: str | None = None) -> int | None:
    """Baca dokumen di Drive → ekstrak → bila LANGGANAN, ajukan gerbang gabungan
    (arsip + update IT). → id pending, atau None bila dilewati (bukan invoice/tak yakin/
    tak bisa dibaca). Phase 1: hanya dokumen langganan (folder 08/03)."""
    import asyncio
    import os

    from app.kantor.drive.client import DriveClient
    c = DriveClient()
    teks = await asyncio.to_thread(c.unduh_teks, file_id, mime)
    if not (teks or "").strip():
        return None  # gambar/scan tanpa teks → lewati (OCR vision = increment lain)
    data = await ekstrak(teks, nama)
    if data.get("keyakinan") == "rendah":
        return None
    sid = os.getenv("IT_ACCOUNTS_SHEET_ID", "1BxcGg1GitQmjTwbKRHmXUdiU2c2Z1yXt9TGK7kIOLY0")
    services = await asyncio.to_thread(c.sheet_baca, sid, "Services!A2:N300")
    u = susun_usulan(data, nama, services)
    if not u["langganan"]:  # Phase 1: hanya dokumen langganan
        return None
    sheet_updates = resolve_updates(services, u["layanan_idx"], u["it_updates"])
    from app.kantor import persetujuan as pst
    aid = await pst.buat_pending(
        jenis="invoice_proses", ringkasan=ringkas_usulan(u),
        payload={"file_id": file_id, "folder_id": u["folder_id"], "asal_id": asal_id,
                 "nama_file": u["nama_file"], "folder_label": u["folder"],
                 "sheet_id": sid, "sheet_updates": sheet_updates},
        diminta_oleh="poller-invoice")
    return aid


def ringkas_usulan(u: dict) -> str:
    """Teks usulan untuk ditinjau (dry-run / pratinjau gerbang)."""
    if not (u.get("invoice") or u.get("langganan")):
        return (f"Dokumen ini terklasifikasi '{u.get('jenis')}' (bukan invoice/langganan; "
                f"keyakinan {u.get('keyakinan')}). Tak ada usulan otomatis.")
    baris = [f"📄 Terdeteksi {'LANGGANAN' if u['langganan'] else 'invoice'} "
             f"— {u.get('vendor') or '?'} (keyakinan {u.get('keyakinan')})"]
    baris.append("\n① ARSIP (dari '03 - Siap Arsip Final' → kategori resmi):")
    baris.append(f"   • Simpan sebagai: {u['nama_file']}")
    baris.append(f"   • Ke: {u['folder']}")
    if u.get("perlu_fisik"):
        baris.append("   • ⚠️ Bernilai hukum — pastikan salinan FISIK sudah diarsip")
    if u["layanan_cocok"] and u["it_updates"]:
        baris.append(f"\n② IT MANAGEMENT — perbarui '{u['layanan_cocok']}':")
        for field, nilai in u["it_updates"]:
            f = "catatan (+)" if field == "catatan_tambah" else field
            baris.append(f"   • {f}: {nilai}")
    elif not u["layanan_cocok"]:
        baris.append("\n② IT MANAGEMENT: layanan tak cocok dengan database — dilewati.")
    return "\n".join(baris)
