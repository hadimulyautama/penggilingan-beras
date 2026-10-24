"""Kop, tipografi, tabel dan halaman bersama untuk dokumen resmi perusahaan."""
from html import escape
from io import BytesIO
from app.web.identitas_dokumen import NAMA_PERUSAHAAN, ALAMAT, KONTAK, LOGO


class PenyajiDokumen:
    def __init__(self):
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        self.ink, self.muted, self.border, self.pale = [colors.HexColor(c) for c in
            ('#24343a', '#546168', '#cbd2d5', '#f1f3f4')]
        self.normal = ParagraphStyle('DokumenBody', fontName='Helvetica', fontSize=9,
                                      leading=13, textColor=self.ink)
        self.small = ParagraphStyle('DokumenSmall', parent=self.normal, fontSize=8,
                                     leading=11, textColor=self.muted)
        self.bold = ParagraphStyle('DokumenBold', parent=self.normal, fontName='Helvetica-Bold')
        self.title = ParagraphStyle('DokumenTitle', parent=self.bold, fontSize=15,
                                     leading=20, alignment=1)
        self.centered = ParagraphStyle('DokumenCentered', parent=self.normal, alignment=1)
        self.small_centered = ParagraphStyle('DokumenSmallCentered', parent=self.small, alignment=1)
        self.small_right = ParagraphStyle('DokumenSmallRight', parent=self.small, alignment=2)
        self.right = ParagraphStyle('DokumenNumber', parent=self.normal, alignment=2)
        self.total_style = ParagraphStyle('DokumenTotal', parent=self.right, fontName='Helvetica-Bold')
        self.section = ParagraphStyle('DokumenSection', parent=self.bold, fontSize=10,
                                       leading=14, spaceBefore=12, spaceAfter=7,
                                       keepWithNext=True)

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

    def pdf(self, story, *, judul, referensi):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
        output = BytesIO()
        doc = BaseDocTemplate(output, pagesize=A4, leftMargin=18 * mm,
                              rightMargin=18 * mm, topMargin=50 * mm,
                              bottomMargin=18 * mm, title=judul, author=NAMA_PERUSAHAAN)
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates(PageTemplate(id='dokumen-perusahaan', frames=frame,
            onPage=lambda canvas, document: self.kop_dan_footer(canvas, document, referensi)))
        doc.build(story)
        return output.getvalue()

    def kop_dan_footer(self, canvas, doc, referensi):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        canvas.saveState()
        left, top, width = 18 * mm, A4[1] - 15 * mm, 174 * mm
        canvas.drawImage(str(LOGO), left, top - 24 * mm, width=24 * mm,
                         height=24 * mm, preserveAspectRatio=True, mask='auto')
        x = left + 30 * mm
        canvas.setFillColor(self.ink)
        canvas.setFont('Helvetica-Bold', 15)
        canvas.drawString(x, top - 4 * mm, NAMA_PERUSAHAAN)
        canvas.setFont('Helvetica', 8.5)
        for i, line in enumerate(ALAMAT + (KONTAK,)):
            canvas.drawString(x, top - (10 + i * 4.5) * mm, line)
        canvas.setStrokeColor(self.ink)
        canvas.setLineWidth(.9)
        canvas.line(left, top - 29 * mm, left + width, top - 29 * mm)
        canvas.setLineWidth(.3)
        canvas.line(left, top - 30 * mm, left + width, top - 30 * mm)
        canvas.setStrokeColor(self.border)
        canvas.line(left, 15 * mm, left + width, 15 * mm)
        canvas.setFillColor(self.muted)
        canvas.setFont('Helvetica', 7.5)
        canvas.drawString(left, 10 * mm, 'PadiFlow | ' + referensi)
        canvas.drawRightString(A4[0] - left, 10 * mm, 'Halaman ' + str(doc.page))
        canvas.restoreState()
