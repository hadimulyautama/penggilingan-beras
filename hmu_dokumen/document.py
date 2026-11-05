"""Kop, tipografi, tabel dan halaman bersama untuk dokumen resmi perusahaan."""
from html import escape
from io import BytesIO
from .identitas import NAMA_PERUSAHAAN, ALAMAT, KONTAK, LOGO


from . import tema
from .perusahaan import Perusahaan
from reportlab.lib.utils import ImageReader
import base64


class PenyajiDokumen:
    def __init__(self, tema_pdf=None, perusahaan=None):
        self.perusahaan = perusahaan or Perusahaan()
        self.tema = tema_pdf or tema.TEMA
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        self.ink, self.muted, self.border, self.pale = [colors.HexColor(c) for c in
            (self.tema.tinta, self.tema.redup, self.tema.garis, self.tema.latar)]
        self.green = colors.HexColor(self.tema.utama)
        self.normal = ParagraphStyle('DokumenBody', fontName=self.tema.font, fontSize=self.tema.ukuran_isi,
                                      leading=self.tema.ukuran_isi * 1.3, textColor=self.ink)
        self.small = ParagraphStyle('DokumenSmall', parent=self.normal, fontSize=self.tema.ukuran_kecil,
                                     leading=self.tema.ukuran_kecil * 1.3, textColor=self.muted)
        self.bold = ParagraphStyle('DokumenBold', parent=self.normal, fontName=self.tema.font_tebal)
        self.title = ParagraphStyle('DokumenTitle', parent=self.bold, fontSize=self.tema.ukuran_judul,
                                     leading=20, alignment=1)
        self.centered = ParagraphStyle('DokumenCentered', parent=self.normal, alignment=1)
        self.small_centered = ParagraphStyle('DokumenSmallCentered', parent=self.small, alignment=1)
        self.small_right = ParagraphStyle('DokumenSmallRight', parent=self.small, alignment=2)
        self.right = ParagraphStyle('DokumenNumber', parent=self.normal, alignment=2)
        self.total_style = ParagraphStyle('DokumenTotal', parent=self.right, fontName=self.tema.font_tebal)
        self.section = ParagraphStyle('DokumenSection', parent=self.bold, fontSize=10,
                                       leading=14, textColor=self.green, spaceBefore=12, spaceAfter=7,
                                       keepWithNext=True)
        self.table_section = ParagraphStyle('DokumenTableSection', parent=self.section,
                                            keepWithNext=False)

    def p(self, value, style=None):
        from reportlab.platypus import Paragraph
        return Paragraph(escape(str(value)), style or self.normal)

    def grid(self, headers, rows, widths, numeric=False):
        from reportlab.platypus import Table, TableStyle
        heading = [self.p(v, self.small_right if numeric and i == len(headers) - 1 else self.small)
                   for i, v in enumerate(headers)]
        table = Table([heading] + rows, colWidths=widths, repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.pale),
            ('LINEBELOW', (0, 0), (-1, 0), .7, self.border),
            ('LINEBELOW', (0, 1), (-1, -1), .35, self.border),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        return table

    def identitas(self, fields):
        from reportlab.lib.units import mm
        from reportlab.platypus import Table, TableStyle
        rows = []
        for i in range(0, len(fields), 2):
            pairs = list(fields[i]) + (list(fields[i + 1]) if i + 1 < len(fields) else ['', ''])
            rows.append([self.p(v, self.small if j % 2 == 0 else self.normal)
                         for j, v in enumerate(pairs)])
        table = Table(rows, colWidths=[31 * mm, 56 * mm, 31 * mm, 56 * mm], hAlign='LEFT')
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        return table

    def bagian_tabel(self, heading, table, first_row_height):
        """Sisakan judul + header + satu baris; tabel panjang boleh membelah halaman."""
        from reportlab.lib.units import mm
        from reportlab.platypus import CondPageBreak
        label = self.p(heading, self.table_section)
        label_height = label.wrap(174 * mm, 100000)[1]
        minimum = label_height + label.getSpaceBefore() + label.getSpaceAfter() + first_row_height
        return [CondPageBreak(minimum), label, table]

    def pdf(self, story, *, judul, referensi):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
        output = BytesIO()
        doc = BaseDocTemplate(output, pagesize=A4, leftMargin=self.tema.margin_mm * mm,
                              rightMargin=self.tema.margin_mm * mm, topMargin=self.tema.atas_mm * mm,
                              bottomMargin=self.tema.bawah_mm * mm, title=judul, author=self.perusahaan.nama)
        kop_tinggi = self.isi_kop().wrap(doc.width - 30*mm, 10000)[1]
        doc.topMargin = max(doc.topMargin, 15*mm + max(24*mm, kop_tinggi) + 12*mm)
        doc.height = A4[1] - doc.topMargin - doc.bottomMargin
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates(PageTemplate(id='dokumen-perusahaan', frames=frame,
            onPage=lambda canvas, document: self.kop_dan_footer(canvas, document, referensi)))
        from reportlab.pdfgen.canvas import Canvas
        penyaji = self
        class Halaman(Canvas):
            # Nomor total dihitung setelah layout, tanpa mengecilkan isi tabel.
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.halaman = []
            def showPage(self):
                self.halaman.append(dict(self.__dict__))
                self._startPage()
            def save(self):
                total = len(self.halaman)
                for state in self.halaman:
                    self.__dict__.update(state)
                    self.saveState()
                    self.setFont(penyaji.tema.font, 7.5)
                    self.setFillColor(penyaji.muted)
                    self.drawRightString(A4[0]-doc.rightMargin, 10*mm,
                        f'Halaman {self._pageNumber} | {self._pageNumber} / {total}')
                    self.restoreState()
                    super().showPage()
                super().save()
        doc.build(story, canvasmaker=Halaman)
        return output.getvalue()

    def isi_kop(self):
        from reportlab.platypus import Paragraph
        from reportlab.lib.styles import ParagraphStyle
        identitas = self.perusahaan
        gaya = ParagraphStyle('KopPerusahaan', fontName=self.tema.font,
            fontSize=8.5, leading=11, textColor=self.ink)
        isi = '<font size="15"><b>'+escape(identitas.nama)+'</b></font><br/>'
        isi += '<br/>'.join(escape(x) for x in identitas.alamat.splitlines() if x)
        isi += '<br/>'+escape(identitas.kontak)
        if identitas.website:isi += '<br/>'+escape(identitas.website)
        return Paragraph(isi, gaya)

    def kop_dan_footer(self, canvas, doc, referensi):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        canvas.saveState()
        left, top, width = doc.leftMargin, A4[1] - 15 * mm, doc.width
        logo = ImageReader(BytesIO(base64.b64decode(self.perusahaan.logo))) if self.perusahaan.logo else str(LOGO)
        canvas.drawImage(logo, left, top - 24 * mm, width=24 * mm,
                         height=24 * mm, preserveAspectRatio=True, mask='auto')
        kop = self.isi_kop()
        _, tinggi = kop.wrap(width - 30*mm, 10000)
        kop.drawOn(canvas, left + 30*mm, top - tinggi)
        garis = top - max(24*mm, tinggi) - 5*mm
        canvas.setStrokeColor(self.green)
        canvas.setLineWidth(.9)
        canvas.line(left, garis, left + width, garis)
        canvas.setLineWidth(.3)
        canvas.line(left, garis-mm, left + width, garis-mm)
        canvas.setStrokeColor(self.border)
        canvas.line(left, 15 * mm, left + width, 15 * mm)
        canvas.setFillColor(self.muted)
        canvas.setFont(self.tema.font, 7.5)
        canvas.drawString(left, 10 * mm, 'PadiFlow | ' + referensi)
        canvas.restoreState()
