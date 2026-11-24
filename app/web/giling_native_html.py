"""Proposal struktur baca Giling aktif, belum dipasang pada router/registry.

Descriptor hanya label/posisi native. Ia bukan konteks proses, token rencana,
izin tindakan, atau model ORM. Pembaca dan seluruh writer native tetap utuh.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl

TAB = (
    ("ringkasan", "Ringkasan"), ("bahan", "Bahan & silo"),
    ("hasil", "Hasil PK"), ("qc", "QC"), ("riwayat", "Riwayat"),
)
_PATH = re.compile(r"/proses-aktif/giling/([A-Za-z0-9][A-Za-z0-9._-]{0,79})")
_QUERY = frozenset({
    "tab_detail", "kembali_kerja", "halaman_hasil", "halaman_qc",
    "halaman_jeda", "buka", "nilai",
})
FAKTA = ("Kode proses", "Pemilik", "Gudang", "Pesanan jasa", "Mulai",
         "Durasi proses", "Durasi efektif", "Total jeda")
STOK = ("Hasil operator tercatat", "Verifikasi Admin", "Dasar stok yang berlaku",
        "Transfer PK terkirim", "Penjualan PK langsung", "Retur diterima", "PK tersedia")


def deskripsi(path: str, query: str = "") -> dict | None:
    """Batas descriptor murni; tidak menyatakan proses/aktor tersebut sah.

    Bentuk URL di luar irisan ini tetap dilayani renderer native. Terutama
    action deep link tidak diubah menjadi panel baca yang salah.
    """
    match = _PATH.fullmatch(path)
    if match is None or len(query) > 3000:
        return None
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=12)
    except ValueError:
        return None
    params = dict(pairs)
    if len(params) != len(pairs) or set(params) - _QUERY:
        return None
    if params.get("buka") or params.get("nilai"):
        return None
    tab = params.get("tab_detail", "ringkasan")
    if tab not in dict(TAB):
        tab = "ringkasan"  # Kontrak giling-desain native untuk tab tak dikenal.
    code = match[1]
    return dict(kode=code, tab=tab, tabs=TAB, fakta=FAKTA, stok=STOK,
                alamat=path + ("?" + query if query else ""),
                data_url=path + ("?" + query if query else ""))


async def kerangka(request, akun, konteks):
    """Native positive guard dahulu; hanya status minimum, tanpa agregasi.

    Root harus memasang guard dispatcher; X-Pindah:1 tetap handler native.
    Tidak ada endpoint baru dan tidak ada POST dari shell ini.
    None berarti lanjut ke handler native, bukan mengganti hasilnya.
    """
    spec = deskripsi(request.url.path, request.url.query)
    if request.method != "GET" or spec is None or request.headers.get("X-Pindah") == "1":
        return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):
        return None
    # Fungsi izin native mencakup boleh_jenis dan row pada batas gudang user.
    # Kesalahan auth tidak diubah menjadi shell sukses/None.
    from app.web.giling_ringkas import izin
    await izin(akun.user, spec["kode"])

    from sqlalchemy import select
    from app.database import SessionLocal
    from app.models import MillingProcess
    from app.services.cakupan_fasilitas import batas
    async with SessionLocal() as db:
        status = await db.scalar(select(MillingProcess.status).where(
            MillingProcess.kode_proses == spec["kode"],
            batas(akun.user, MillingProcess)))
    if status != "proses":
        # Selesai/hilang/berubah fase tetap milik handler native. Jangan buat
        # catatan proses selesai tampak sebagai editor aktif.
        return None

    from app.web.halaman_bertahap import penanda_konteks
    from app.web.layar_pekerjaan import konteks_aman
    from app.web.tampilan import render
    spec["stamp"] = penanda_konteks(request, akun) + "|" + spec["alamat"]
    response = render(
        request, "giling_native_html.html", GILING_KERANGKA=spec,
        layar="pekerjaan",
        kembali=konteks_aman(request.query_params.get("kembali_kerja"))
                 or "/pekerjaan?tab=berjalan",
        breadcrumb_detail=spec["kode"],
        **{k: v for k, v in konteks.items()
           if k not in {"layar", "SHELL", "GILING_KERANGKA", "kembali",
                        "breadcrumb_detail"}},
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response
