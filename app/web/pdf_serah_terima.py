"""PDF serah terima resmi: satu penyaji untuk produksi dan portal pelanggan."""
from html import escape
from io import BytesIO
from app.services.serah_terima import waktu
from app.web.identitas_dokumen import NAMA_PERUSAHAAN, ALAMAT, KONTAK, LOGO


def buat_pdf(data):
    if not data['siap']:
        raise ValueError('Dokumen serah terima belum tersedia.')
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate,
                                    Paragraph, Spacer, Table, TableStyle,
                                    PageBreak, KeepTogether)

    ink, muted, border, pale = [colors.HexColor(c) for c in
                               ('#24343a', '#546168', '#cbd2d5', '#f1f3f4')]
    width = 174 * mm
    normal = ParagraphStyle('SerahBody', fontName='Helvetica', fontSize=9,
                            leading=13, textColor=ink)
    small = ParagraphStyle('SerahSmall', parent=normal, fontSize=8, leading=11,
                           textColor=muted)
    bold = ParagraphStyle('SerahBold', parent=normal, fontName='Helvetica-Bold')
    title = ParagraphStyle('SerahTitle', parent=bold, fontSize=15, leading=20,
                           alignment=1)
    centered = ParagraphStyle('SerahCentered', parent=normal, alignment=1)
    small_centered = ParagraphStyle('SerahSmallCentered', parent=small, alignment=1)
    small_right = ParagraphStyle('SerahSmallRight', parent=small, alignment=2)
    right = ParagraphStyle('SerahNumber', parent=normal, alignment=2)
    total_style = ParagraphStyle('SerahTotal', parent=right, fontName='Helvetica-Bold')
    section = ParagraphStyle('SerahSection', parent=bold, fontSize=10,
                             leading=14, spaceBefore=12, spaceAfter=7,
                             keepWithNext=True)

    def p(value, style=normal):
        return Paragraph(escape(str(value)), style)

    def grid(headers, rows, widths, numeric=False):
        heading = [p(v, small_right if numeric and i == len(headers) - 1 else small)
                   for i, v in enumerate(headers)]
        table = Table([heading] + rows,
                      colWidths=widths, repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), pale),
            ('LINEBELOW', (0, 0), (-1, 0), .7, border),
            ('LINEBELOW', (0, 1), (-1, -1), .35, border),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        return table

    story = [p(data['judul'].upper(), title),
             p('Nomor: ' + data['nomor'], centered), Spacer(1, 6 * mm)]
    fields = [('Nama pelanggan', data['pelanggan']),
              (data['label_tanggal'], data['tanggal'])] + list(data['identitas'])
    identities = []
    for i in range(0, len(fields), 2):
        pairs = list(fields[i]) + (list(fields[i + 1]) if i + 1 < len(fields) else ['', ''])
        identities.append([p(v, small if j % 2 == 0 else normal)
                           for j, v in enumerate(pairs)])
    identity = Table(identities, colWidths=[31 * mm, 56 * mm, 31 * mm, 56 * mm],
                     hAlign='LEFT')
    identity.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(identity)
    if data['pesanan']:
        story += [Spacer(1, 3 * mm), p('Nomor pesanan terkait: ' + ' · '.join(data['pesanan']), small)]
    story.append(p('Rincian barang yang diserahterimakan', section))
    goods = [[p(i, small_centered), p(row[0]), p(row[1]), p(row[2], right)]
             for i, row in enumerate(data['baris'], 1)]
    if data.get('total') is not None:
        goods.append(['', p(data['label_total'], bold), '', p(data['total'], total_style)])
    items = grid(['No.'] + data['kolom'], goods,
                 [8 * mm, 88 * mm, 39 * mm, 39 * mm], numeric=True)
    items.setStyle(TableStyle([('LEFTPADDING', (0, 0), (0, -1), 3),
                              ('RIGHTPADDING', (0, 0), (0, -1), 3)]))
    if data.get('total') is not None:
        items.setStyle(TableStyle([
            ('SPAN', (1, -1), (2, -1)),
            ('BACKGROUND', (0, -1), (-1, -1), pale),
            ('LINEABOVE', (0, -1), (-1, -1), .7, border),
        ]))
    story += [items, Spacer(1, 3 * mm), p('Keterangan: ' + data['catatan'], small)]
    if data['qc']:
        story.append(p('QC penerimaan', section))
        for group in data['qc']:
            story.append(p(group['kode'] + ' · ' + group['status']))
            if group.get('catatan'):
                story.append(p('Alasan penutupan: ' + group['catatan'], small))
        story.append(p('Rincian pemeriksaan tercantum pada lampiran QC dokumen ini.', small))

    signatures = Table([
        [p(data['serah'], centered), '', p(data['terima'], centered)],
        ['', '', ''],
        [p('Nama & tanda tangan', small_centered), '', p('Nama & tanda tangan', small_centered)],
    ], colWidths=[75 * mm, 24 * mm, 75 * mm], rowHeights=[18, 64, 18])
    signatures.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('LINEBELOW', (0, 1), (0, 1), .4, border),
        ('LINEBELOW', (2, 1), (2, 1), .4, border),
    ]))
    story.append(KeepTogether([p('Pengesahan serah terima', section), signatures]))

    for group in data['qc']:
        story += [PageBreak(), p('LAMPIRAN QC PENERIMAAN', title),
                  p(data['nomor'] + ' · ' + data['pelanggan'], centered),
                  Spacer(1, 6 * mm), p(group['kode'] + ' · ' + group['status'], bold)]
        if group.get('catatan'):
            story.append(p('Alasan penutupan: ' + group['catatan'], small))
        story.append(Spacer(1, 4 * mm))
        rows = []
        for sample in group['putaran']:
            label = 'Pemeriksaan ' + str(sample['nomor'] if sample['nomor'] is not None else 'lama')
            details = '<br/>'.join(escape(str(k)) + ': ' + escape(str(v))
                                   for k, v in sample['hasil'])
            rows.append([p(label), p(waktu(sample['waktu']) + ' · ' + sample['petugas']),
                         Paragraph(details, normal)])
        story.append(grid(['Putaran', 'Waktu & petugas', 'Hasil pemeriksaan'],
                          rows, [28 * mm, 48 * mm, 98 * mm]))

    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=50 * mm,
                            bottomMargin=18 * mm,
                            title=data['judul'] + ' · ' + data['nomor'],
                            author=NAMA_PERUSAHAAN)

    def kop_dan_footer(canvas, doc):
        canvas.saveState()
        left, top = 18 * mm, A4[1] - 15 * mm
        canvas.drawImage(str(LOGO), left, top - 24 * mm, width=24 * mm,
                         height=24 * mm, preserveAspectRatio=True, mask='auto')
        x = left + 30 * mm
        canvas.setFillColor(ink)
        canvas.setFont('Helvetica-Bold', 15)
        canvas.drawString(x, top - 4 * mm, NAMA_PERUSAHAAN)
        canvas.setFont('Helvetica', 8.5)
        for i, line in enumerate(ALAMAT + (KONTAK,)):
            canvas.drawString(x, top - (10 + i * 4.5) * mm, line)
        canvas.setStrokeColor(ink)
        canvas.setLineWidth(.9)
        canvas.line(left, top - 29 * mm, left + width, top - 29 * mm)
        canvas.setLineWidth(.3)
        canvas.line(left, top - 30 * mm, left + width, top - 30 * mm)
        canvas.setStrokeColor(border)
        canvas.line(left, 15 * mm, left + width, 15 * mm)
        canvas.setFillColor(muted)
        canvas.setFont('Helvetica', 7.5)
        canvas.drawString(left, 10 * mm, 'PadiFlow | ' + data['nomor'])
        canvas.drawRightString(A4[0] - left, 10 * mm, 'Halaman ' + str(doc.page))
        canvas.restoreState()

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id='serah-terima', frames=frame,
                                      onPage=kop_dan_footer))
    doc.build(story)
    return buffer.getvalue()
