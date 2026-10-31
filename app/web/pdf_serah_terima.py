"""PDF serah terima resmi: satu penyaji untuk produksi dan portal pelanggan."""
from html import escape
from app.web.qc_warna import NilaiQC, GabunganQC, paragraf, warnai_tabel
from app.services.serah_terima import waktu
from app.web.pdf_dokumen import PenyajiDokumen


def buat_pdf(data):
    if not data['siap']:
        raise ValueError('Dokumen serah terima belum tersedia.')
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
    view = PenyajiDokumen()
    p, grid = view.p, view.grid
    normal, small, bold = view.normal, view.small, view.bold
    title, centered = view.title, view.centered
    small_centered, right = view.small_centered, view.right
    total_style, section, border = view.total_style, view.section, view.border
    pale = view.pale

    story = [p(data['judul'].upper(), title),
             p('Nomor: ' + data['nomor'], centered), Spacer(1, 6 * mm)]
    fields = [('Nama pelanggan', data['pelanggan']),
              (data['label_tanggal'], data['tanggal'])] + list(data['identitas'])
    story.append(view.identitas(fields))
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
            details = GabunganQC([part for i,(k,v) in enumerate(sample['hasil']) for part in ((('\n' if i else '')+str(k)+': '),NilaiQC(k,v))], '')
            rows.append([p(label), p(waktu(sample['waktu']) + ' · ' + sample['petugas']),
                         paragraf(details, normal)])
        story.append(warnai_tabel(grid(['Putaran', 'Waktu & petugas', 'Hasil pemeriksaan'],
                          rows, [28 * mm, 48 * mm, 98 * mm])))

    return view.pdf(story, judul=data['judul'] + ' · ' + data['nomor'],
                    referensi=data['nomor'])
