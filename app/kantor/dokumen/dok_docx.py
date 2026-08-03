"""Bangun .docx surat resmi PT HMU dengan GAYA HOUSE konsisten (kop berwarna,
font & tata letak) meniru dokumen resmi (SK/Surat Tugas Cowork). python-docx.

Elemen konsisten (wrapper): kop berwarna + garis, judul berwarna + nomor, badan
justify, tabel opsional, blok tanda tangan kanan, tembusan. VARIABEL: `isi`
(badan) disusun pemanggil sesuai jenis dokumen. MURNI (tanpa IO Drive/DB).

Warna korporat (diverifikasi dari dokumen resmi 2026-08-03):
  NAVY #1F3864 (nama PT + judul + garis) · GRAY #595959 (alamat, nomor, tembusan)
"""
from __future__ import annotations

import io
from datetime import date

_NAVY = "1F3864"
_GRAY = "595959"
_FONT = "Calibri"

_BULAN = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember"]


def _tanggal_id(d: date) -> str:
    return f"Sragen, {d.day} {_BULAN[d.month]} {d.year}"


def surat_docx(
    *,
    judul: str,
    isi: str,
    nomor: str = "",
    tanggal: date | None = None,
    tembusan: list[str] | None = None,
    tabel: list[list[str]] | None = None,
    jabatan_ttd: str = "Direktur Utama",
    nama_ttd: str = "Ahmad Wahid Nurhani",
) -> bytes:
    """Rangkai .docx surat resmi bergaya house PT HMU. Kembalikan bytes .docx.

    `isi`: badan surat (multi-baris). Baris berisi hanya '[[TABEL]]' akan diganti
    dengan `tabel` (baris pertama = header, tebal). `tembusan`: daftar penerima
    tembusan (opsional). Cocok untuk semua jenis (Surat Tugas, SK, Kontrak, dll).
    """
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    navy, gray = RGBColor.from_string(_NAVY), RGBColor.from_string(_GRAY)
    doc = docx.Document()
    st = doc.styles["Normal"]
    st.font.name = _FONT
    st.font.size = Pt(11)

    def line(teks, *, size=11, bold=False, color=None, align=AL.LEFT,
             after=2, before=0, italic=False):
        p = doc.add_paragraph()
        p.alignment = align
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.space_before = Pt(before)
        if teks:
            r = p.add_run(teks)
            r.font.name = _FONT
            r.font.size = Pt(size)
            r.bold = bold
            r.italic = italic
            if color is not None:
                r.font.color.rgb = color
        return p

    # ── Kop ──
    line("PT HADI MULYA UTAMA", size=16, bold=True, color=navy, align=AL.CENTER, after=0)
    line("Penggilingan Padi dan Penyosohan Beras", size=9.5, color=gray, align=AL.CENTER, after=0)
    line("Tegalrejo RT/RW 21/07, Masaran, Sragen, Jawa Tengah", size=8.5, color=gray, align=AL.CENTER, after=0)
    kop = line("Telp. (+62) 851-7416-7950   •   Email: info@hadimulya.com",
               size=8.5, color=gray, align=AL.CENTER, after=0)
    # garis bawah kop (border navy)
    pPr = kop._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "12"), ("w:space", "4"), ("w:color", _NAVY)):
        bottom.set(qn(k), v)
    pbdr.append(bottom)
    pPr.append(pbdr)

    # ── Judul + nomor ──
    line(judul.upper(), size=13, bold=True, color=navy, align=AL.CENTER, before=10, after=0)
    if nomor:
        line(f"Nomor: {nomor}", size=10, color=gray, align=AL.CENTER, after=10)
    else:
        line("", after=6)

    # ── Isi (justify; sisipkan tabel di [[TABEL]]) ──
    def render_tabel():
        if not tabel:
            return
        t = doc.add_table(rows=0, cols=max(len(r) for r in tabel))
        t.style = "Table Grid"
        t.alignment = 1  # center
        for i, row in enumerate(tabel):
            cells = t.add_row().cells
            for j, val in enumerate(row):
                cells[j].text = ""
                pr = cells[j].paragraphs[0]
                run = pr.add_run(str(val))
                run.font.name = _FONT
                run.font.size = Pt(10)
                run.bold = (i == 0)
        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    for baris in isi.replace("\r\n", "\n").split("\n"):
        s = baris.strip()
        if s == "[[TABEL]]":                       # sisipkan tabel
            render_tabel()
        elif s.startswith("[[C]]"):                # sub-judul tengah (navy, tebal)
            line(s[5:].strip(), bold=True, color=navy, align=AL.CENTER, after=2)
        else:
            line(baris, size=11, align=AL.JUSTIFY, after=2)

    # ── Tanda tangan (kanan) ──
    d = tanggal or date.today()
    line("", before=8, after=0)
    line(_tanggal_id(d), align=AL.RIGHT, after=0)
    line("PT Hadi Mulya Utama", align=AL.RIGHT, after=0)
    line(f"{jabatan_ttd},", align=AL.RIGHT, after=0)
    line("", after=0)
    line("", after=0)
    line(nama_ttd, bold=True, align=AL.RIGHT, after=0)
    line(jabatan_ttd, size=10, color=gray, align=AL.RIGHT, after=6)

    # ── Tembusan ──
    if tembusan:
        line("Tembusan:", size=9, bold=True, color=gray, before=8, after=0)
        for i, t in enumerate(tembusan, 1):
            line(f"{i}. {t}", size=9, color=gray, after=0)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
