"""PDF A4 laporan periode; isi sama dengan cuplikan yang disajikan layar."""
from html import escape
from io import BytesIO


def buat_pdf(data, *, contoh=False):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, CondPageBreak

    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=landscape(A4), rightMargin=17*mm, leftMargin=17*mm,
                            topMargin=14*mm, bottomMargin=18*mm,
                            title=f"Laporan {data['nama']} - {data['periode']}", author='PT Hadi Mulya Utama')
    green = colors.HexColor('#226442')
    styles = getSampleStyleSheet()
    for name, size, leading, bold, color in [
        ('JudulPeriode', 18, 22, True, green), ('SubPeriode', 8.5, 11, False, colors.HexColor('#52635a')),
        ('BagianPeriode', 10, 13, True, green), ('IsiPeriode', 7.5, 10, False, colors.HexColor('#243b30')),
        ('KepalaPeriode', 7.5, 10, True, colors.white)]:
        styles.add(ParagraphStyle(name, fontName='Helvetica-Bold' if bold else 'Helvetica',
                                 fontSize=size, leading=leading, textColor=color, spaceAfter=5, keepWithNext=False))
    def p(value, style='IsiPeriode'):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])
    def tabel(rows, widths):
        table = Table([[p(c, 'KepalaPeriode' if i == 0 else 'IsiPeriode') for c in r] for i,r in enumerate(rows)],
                      colWidths=widths, repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),green), ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f1f5f2')]),
            ('LEFTPADDING',(0,0),(-1,-1),7), ('RIGHTPADDING',(0,0),(-1,-1),7),
            ('TOPPADDING',(0,0),(-1,-1),5), ('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LINEBELOW',(0,0),(-1,0),.5,green),
        ]))
        return table
    ringkas = [['Ringkasan', 'Nilai', 'Ringkasan', 'Nilai']]
    for i in range(0, len(data['ringkasan']), 2):
        pasangan = data['ringkasan'][i:i+2]
        ringkas.append([pasangan[0]['nama'],pasangan[0]['nilai']] + ([pasangan[1]['nama'],pasangan[1]['nilai']] if len(pasangan)>1 else ['','']))
    story = [p('PADIFLOW / PT HADI MULYA UTAMA','SubPeriode')]
    if contoh:
        story.append(p('CONTOH TAMPILAN - DATA SIMULASI','BagianPeriode'))
    story += [p(data['nama'],'JudulPeriode'),
              p('Periode: '+data['periode'],'SubPeriode'),
              p('Dasar periode: '+data['dasar']+' (WIB)','SubPeriode'), Spacer(1,4*mm),
              tabel(ringkas,[68*mm,63*mm,68*mm,64*mm])]
    if data['status']:
        story += [Spacer(1,4*mm),p('Status transaksi','BagianPeriode'),
                  tabel([['Status','Jumlah']]+[[r['nama'],r['nilai']] for r in data['status']],[132*mm,131*mm])]
    story += [Spacer(1,5*mm), CondPageBreak(50*mm), p('Rincian transaksi','BagianPeriode')]
    if data['rincian']:
        cols=data['kolom']
        rows=[[c['nama'] for c in cols]]
        for r in data['rincian']:
            cells=[]
            for c in cols:
                key=c['kunci'];value=r.get(key,'Belum tercatat')
                if key=='kode' and r.get('tiket','-')!='-':value += ' / '+r['tiket']
                if key=='nota' and r.get('sumber_nota')=='Mengikuti timbangan':value += ' (Mengikuti timbangan)'
                cells.append(value)
            rows.append(cells)
        weights=[2.2 if c['kunci'] in ('asal','produk','produk_asal','hasil_beras','hasil_samping','rincian_muatan','alasan','mitra') else 1.5 if c['kunci']=='kode' else 1.4 if c['kunci']=='tanggal' else 1.2 if c['kunci']=='rendemen' else 1 for c in cols]
        story.append(tabel(rows,[263*mm*w/sum(weights) for w in weights]))
    else:
        story.append(p('Tidak ada transaksi pada periode ini.'))
    story += [Spacer(1,5*mm),CondPageBreak(20*mm),p('Keterangan','BagianPeriode')]+[p(c) for c in data['catatan']]
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#ccd9ce'))
        canvas.line(17*mm,15*mm,doc.pagesize[0]-17*mm,15*mm)
        canvas.setFont('Helvetica',8)
        canvas.setFillColor(colors.HexColor('#52635a'))
        canvas.drawString(17*mm,10*mm,'Padiflow | '+('Data simulasi' if contoh else 'Laporan aktivitas per periode'))
        canvas.drawRightString(doc.pagesize[0]-17*mm,10*mm,f'Halaman {doc.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return stream.getvalue()
