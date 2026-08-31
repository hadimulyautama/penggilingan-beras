#!/usr/bin/env python3
"""Ubah pedoman HTML menjadi PDF yang layak dibagikan dan dicetak.

    .venv/bin/python scripts/pedoman_pdf.py docs/timbangan/pedoman-admin.html

Dirender oleh Chrome headless, bukan disusun ulang dengan pustaka PDF: yang
dibagikan harus persis halaman yang sama — palet, huruf, dan penanda harga
tindakannya. Menyusunnya ulang berarti memelihara dua versi dokumen yang sama
dan menunggu keduanya berbeda.

Header dan footer bawaan peramban dimatikan. Nomor halaman dibubuhkan sendiri
di sini supaya isinya terkendali: nama dokumen dan nomor halaman saja, tanpa
tanggal cetak maupun alamat berkas. Keputusan yang sama sudah diambil untuk
bukti timbang — tanggal cetak pada dokumen yang dibaca berbulan-bulan kemudian
lebih sering menyesatkan daripada menolong.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

#: Senada dengan --faint pada pedomannya; cukup terbaca, tidak menarik mata.
WARNA_NOMOR = HexColor("#8a8478")


def judul_dokumen(html: str) -> str:
    cocok = re.search(r"<title>(.*?)</title>", html, re.S)
    return cocok.group(1).strip() if cocok else "Pedoman"


def render(sumber: Path, tujuan: Path) -> None:
    """HTML → PDF lewat Chrome headless."""
    if not Path(CHROME).exists():
        raise SystemExit(f"Chrome tidak ditemukan di {CHROME}")
    hasil = subprocess.run(
        [
            CHROME, "--headless=new", "--disable-gpu",
            "--no-pdf-header-footer",
            # Huruf diambil dari Google Fonts; tanpa jeda ini halaman bisa
            # tercetak dengan huruf cadangan.
            "--virtual-time-budget=10000",
            f"--print-to-pdf={tujuan}",
            sumber.resolve().as_uri(),
        ],
        capture_output=True, text=True,
    )
    if not tujuan.exists():
        raise SystemExit(f"Chrome gagal merender:\n{hasil.stderr}")


def bubuhi_nomor(berkas: Path, judul: str) -> int:
    """Tulis '<judul> · n / N' kecil di kaki tiap halaman."""
    asal = PdfReader(str(berkas))
    jumlah = len(asal.pages)
    tulis = PdfWriter()

    for urut, halaman in enumerate(asal.pages, start=1):
        lebar = float(halaman.mediabox.width)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(lebar, float(halaman.mediabox.height)))
        c.setFont("Helvetica", 7.5)
        c.setFillColor(WARNA_NOMOR)
        c.drawCentredString(lebar / 2, 22, f"{judul}  ·  {urut} / {jumlah}")
        c.save()
        buf.seek(0)
        halaman.merge_page(PdfReader(buf).pages[0])
        tulis.add_page(halaman)

    with berkas.open("wb") as f:
        tulis.write(f)
    return jumlah


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sumber = Path(sys.argv[1])
    if not sumber.exists():
        raise SystemExit(f"Tidak ada berkas {sumber}")
    tujuan = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        sumber.with_suffix(".pdf")

    judul = judul_dokumen(sumber.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        sementara = Path(tmp) / "mentah.pdf"
        render(sumber, sementara)
        sementara.replace(tujuan)
    jumlah = bubuhi_nomor(tujuan, judul)
    print(f"{tujuan} · {jumlah} halaman · {tujuan.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
