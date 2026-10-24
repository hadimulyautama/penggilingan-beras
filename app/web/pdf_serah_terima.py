"""Satu penyaji PDF untuk kedua jenis serah terima produksi dan pelanggan."""
from html import escape
from io import BytesIO
from app.services.serah_terima import waktu


def buat_pdf(data):
    if not data['siap']:raise ValueError('Dokumen serah terima belum tersedia.')
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
    ink,muted,border,pale=[colors.HexColor(c) for c in ('#173042','#52636d','#dce3e6','#f3f6f7')]
    normal=ParagraphStyle('SerahBody',fontName='Helvetica',fontSize=9,leading=13,textColor=ink)
    small=ParagraphStyle('SerahSmall',parent=normal,fontSize=8,leading=11,textColor=muted)
    title=ParagraphStyle('SerahTitle',parent=normal,fontName='Helvetica-Bold',fontSize=20,leading=25)
    section=ParagraphStyle('SerahSection',parent=normal,fontName='Helvetica-Bold',fontSize=11,leading=15,spaceBefore=12,spaceAfter=7,keepWithNext=True)
    def p(value,style=normal):return Paragraph(escape(str(value)),style)
    def grid(headers,rows,widths,number=False):
        cells=[[p(v,small) for v in headers]]+[[p(v) for v in row] for row in rows]
        if number:
            for row in cells[1:]:row[-1].style=ParagraphStyle('SerahNumber',parent=normal,alignment=2)
        t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),pale),('LINEBELOW',(0,0),(-1,-1),.4,border),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        return t
    story=[p('SERAH TERIMA BARANG',small),Spacer(1,6),p(data['judul'],title),Spacer(1,8),p(data['pelanggan']),Spacer(1,12)]
    story.append(grid(['Nomor dokumen',data['label_tanggal']],[[data['nomor'],data['tanggal']]],[105*mm,69*mm]))
    if data['pesanan']:story += [Spacer(1,10),p('Nomor pesanan terkait: '+' · '.join(data['pesanan']))]
    identities=[]
    for i in range(0,len(data['identitas']),2):
        fields=list(data['identitas'][i])+ (list(data['identitas'][i+1]) if i+1<len(data['identitas']) else ['',''])
        identities.append(fields)
    goods=list(data['baris'])
    if data.get('total') is not None:goods.append([data['label_total'],'',data['total']])
    story += [p('Identitas serah terima',section),grid(['Keterangan','Data','Keterangan','Data'],identities,[34*mm,53*mm,34*mm,53*mm]),p('Barang yang diserahterimakan',section),grid(data['kolom'],goods,[97*mm,38*mm,39*mm],number=True),Spacer(1,6),p(data['catatan'],small)]
    if data['qc']:
        story.append(p('QC penerimaan',section))
        for group in data['qc']:
            story.append(p(group['kode']+' · '+group['status']))
            if group.get('catatan'):story.append(p('Alasan penutupan: '+group['catatan'],small))
        story.append(p('Rincian pemeriksaan tersedia pada lampiran QC.',small))
    signatures=Table([[p(data['serah']),p(data['terima'])],['',''],[p('Nama & tanda tangan',small),p('Nama & tanda tangan',small)]],colWidths=[87*mm,87*mm],rowHeights=[20,50,20])
    signatures.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,1),(-1,1),.4,border),('RIGHTPADDING',(0,0),(-1,-1),16)]))
    story.append(KeepTogether([p('Pengesahan serah terima',section),signatures]))
    for group in data['qc']:
        story += [PageBreak(),p('Lampiran QC penerimaan',title),Spacer(1,10),p(group['kode']+' · '+group['status']),Spacer(1,10)]
        cells=[[p(v,small) for v in ['Putaran','Waktu & petugas','Hasil pemeriksaan']]]
        for sample in group['putaran']:
            label='Pemeriksaan '+str(sample['nomor'] if sample['nomor'] is not None else 'lama')
            details='<br/>'.join(escape(str(k))+': '+escape(str(v)) for k,v in sample['hasil'])
            cells.append([p(label),p(waktu(sample['waktu'])+' · '+sample['petugas']),Paragraph(details,normal)])
        t=Table(cells,colWidths=[28*mm,48*mm,98*mm],repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),pale),('LINEBELOW',(0,0),(-1,-1),.4,border),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story.append(t)
    buffer=BytesIO();doc=SimpleDocTemplate(buffer,pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=16*mm,bottomMargin=16*mm,title=data['judul']+' · '+data['nomor'],author='PadiFlow')
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('Helvetica',8);canvas.setFillColor(muted)
        canvas.drawString(18*mm,9*mm,'PadiFlow | '+data['nomor']);canvas.drawRightString(A4[0]-18*mm,9*mm,str(doc.page));canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
