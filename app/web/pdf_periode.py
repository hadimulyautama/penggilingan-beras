"""PDF landscape laporan periode; isi sama dengan cuplikan yang disajikan layar."""
from html import escape
from io import BytesIO


def buat_pdf(data, *, contoh=False):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, A3, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, CondPageBreak

    stream = BytesIO()
    page=landscape(A3 if len(data.get('kolom',[]))>12 else A4)
    lebar=page[0]-34*mm
    doc = SimpleDocTemplate(stream, pagesize=page, rightMargin=17*mm, leftMargin=17*mm,
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
    def tabel(rows, widths, *, headers=1, spans=(), belum_selesai=()):
        table = Table([[c if isinstance(c,Paragraph) else p(c, 'KepalaPeriode' if i < headers else 'IsiPeriode') for c in r] for i,r in enumerate(rows)],
                      colWidths=widths, repeatRows=headers, hAlign='LEFT')
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,headers-1),green), ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('ROWBACKGROUNDS',(0,headers),(-1,-1),[colors.white,colors.HexColor('#f1f5f2')]),
            ('LEFTPADDING',(0,0),(-1,-1),7), ('RIGHTPADDING',(0,0),(-1,-1),7),
            ('TOPPADDING',(0,0),(-1,-1),5), ('BOTTOMPADDING',(0,0),(-1,-1),5),
            ('LINEBELOW',(0,0),(-1,0),.5,green),
        ]))
        if spans: table.setStyle(TableStyle(list(spans)))
        for i in belum_selesai:
            table.setStyle(TableStyle([('BACKGROUND',(0,i),(-1,i),colors.HexColor('#fff3cd'))]))
        return table
    story = [p('PADIFLOW / PT HADI MULYA UTAMA','SubPeriode')]
    if contoh:
        story.append(p('CONTOH TAMPILAN - DATA SIMULASI','BagianPeriode'))
    story += [p(data['nama'],'JudulPeriode'),
              p('Periode: '+data['periode'],'SubPeriode'),
              p('Dasar periode: '+data['dasar']+' (WIB)','SubPeriode'), Spacer(1,4*mm)]
    from itertools import groupby
    for grup in data.get('ringkasan_kelompok',[dict(nama='Ringkasan',rincian=data['ringkasan'])]):
        rows=[[grup['nama'],'','','']];spans=[('SPAN',(0,0),(3,0))]
        for bagian,items in groupby(grup['rincian'],key=lambda r:r.get('bagian')):
            if bagian:
                i=len(rows);rows.append([p(bagian,'BagianPeriode'),'','',''])
                spans.extend([('SPAN',(0,i),(3,i)),('BACKGROUND',(0,i),(3,i),colors.HexColor('#e1ece5'))])
            items=list(items)
            for i in range(0,len(items),2):
                pair=items[i:i+2]
                rows.append([pair[0]['nama'],pair[0]['nilai']]+([pair[1]['nama'],pair[1]['nilai']] if len(pair)>1 else ['','']))
        story.extend([tabel(rows,[lebar*.32,lebar*.18,lebar*.32,lebar*.18],spans=spans),Spacer(1,2*mm)])
    story += [Spacer(1,5*mm), CondPageBreak(50*mm), p('Rincian transaksi','BagianPeriode')]
    if data['rincian']:
        cols=data['kolom']
        spans=[];headers=1
        if any(c.get('kelompok') for c in cols):
            headers=2;top=['']*len(cols);sub=['']*len(cols);i=0
            while i<len(cols):
                c=cols[i];kelompok=c.get('kelompok')
                if not kelompok:
                    top[i]=c['nama'];spans.append(('SPAN',(i,0),(i,1)));i+=1;continue
                j=i+1
                while j<len(cols) and cols[j].get('kelompok')==kelompok:j+=1
                top[i]=kelompok;spans.append(('SPAN',(i,0),(j-1,0)))
                spans.append(('ALIGN',(i,0),(j-1,0),'CENTER'))
                for k in range(i,j):sub[k]=cols[k]['nama']
                i=j
            rows=[top,sub]
        else:rows=[[c['nama'] for c in cols]]
        for r in data['rincian']:
            cells=[]
            for c in cols:
                key=c['kunci'];value=r.get(key,'Belum tercatat')
                if key=='kode' and r.get('tiket','-')!='-':value += ' / '+r['tiket']
                if key=='nota' and r.get('sumber_nota')=='Mengikuti timbangan':value += ' (Mengikuti timbangan)'
                if key=='kode':
                    value=Paragraph(escape(str(value))+'<br/><font size="6" color="#52635a">'+escape(r['tanggal'])+'</font>',styles['IsiPeriode'])
                cells.append(value)
            rows.append(cells)
        weights=[2.2 if c['kunci'] in ('asal','bahan_jenis','produk','produk_asal','hasil_beras','hasil_samping','rincian_muatan','alasan','mitra') else 1.5 if c['kunci']=='kode' else 1.4 if c['kunci']=='tanggal' else 1.2 if c['kunci']=='rendemen' else 1 for c in cols]
        story.append(tabel(rows,[lebar*w/sum(weights) for w in weights],headers=headers,spans=spans,
                           belum_selesai=[headers+i for i,r in enumerate(data['rincian']) if r.get('belum_selesai')]))
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
