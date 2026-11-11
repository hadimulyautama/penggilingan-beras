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
    cols=data.get('kolom',[])
    page=landscape(A3 if len(cols)>12 or any(c.get('subkelompok') for c in cols) else A4)
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
    styles['KepalaPeriode'].alignment=1
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
            ('GRID',(0,0),(-1,-1),.4,colors.HexColor('#b4c5b9')),
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
    groups=data.get('ringkasan_kelompok',[dict(nama='Ringkasan',rincian=data['ringkasan'])])
    by_name={g['nama']:g for g in groups}
    berdampingan='Bahan' in by_name and 'Hasil' in by_name
    for grup in groups:
        if grup['nama']=='Aktivitas':
            story.extend([p(' · '.join(r['nama']+': '+r['nilai'] for r in grup['rincian']),'SubPeriode'),Spacer(1,2*mm)])
            continue
        if berdampingan and grup['nama'] in ('Hasil','Evaluasi proses'):
            continue
        if berdampingan and grup['nama']=='Bahan':
            # Baris biasa (bukan tabel bersarang) tetap dapat dipaginasi bila
            # master memiliki banyak jenis hasil. Celah putih memisahkan
            # setiap tabel ringkasan, tanpa mengubah rincian transaksi.
            def bagian_ringkas(items):
                result=[];bagian=None
                for r in items:
                    if r.get('bagian') and r['bagian']!=bagian:
                        bagian=r['bagian'];result.append(dict(judul=bagian))
                    result.append(r)
                return result
            kiri=bagian_ringkas(grup['rincian'])
            hasil=by_name['Hasil']['rincian']
            tiga_tabel=data.get('kode')=='penyosohan'
            if tiga_tabel:
                kiri += [r for r in hasil if not r.get('bagian')]
            if 'Evaluasi proses' in by_name:
                kiri += [dict(judul='Evaluasi proses',utama=True)]+by_name['Evaluasi proses']['rincian']
            kolom_ringkas=[('Bahan',kiri)]
            if tiga_tabel:
                for nama in ('Beras','Hasil samping'):
                    items=[r for r in hasil if r.get('bagian')==nama]
                    if not items:items=[dict(nama='Belum tercatat' if data['rincian'] else 'Tidak ada transaksi',nilai='')]
                    kolom_ringkas.append((nama,items))
            else:kolom_ringkas.append(('Hasil',bagian_ringkas(hasil)))
            n=len(kolom_ringkas)
            counts=[3 if tiga_tabel and j>0 else 2 for j in range(n)]
            starts=[];pos=0
            for count in counts:starts.append(pos);pos+=count+1
            ncols=pos-1
            rows=[['']*ncols];spans=[]
            for j,(nama,_) in enumerate(kolom_ringkas):
                col=starts[j]
                if tiga_tabel:
                    rows[0][col:col+counts[j]]=[nama,'Bobot']+(['% bahan baku'] if counts[j]==3 else [])
                else:
                    rows[0][col]=nama;spans.append(('SPAN',(col,0),(col+1,0)))
            for i in range(max(len(items) for _,items in kolom_ringkas)):
                row=['']*ncols
                for j,(_,items) in enumerate(kolom_ringkas):
                    col=starts[j];last=col+counts[j]-1
                    if i>=len(items):
                        spans.append(('BACKGROUND',(col,i+1),(last,i+1),colors.white))
                        spans.extend([('LINEBEFORE',(col,i+1),(last,i+1),.4,colors.white),
                                      ('LINEAFTER',(last,i+1),(last,i+1),.4,colors.white),
                                      ('LINEBELOW',(col,i+1),(last,i+1),.4,colors.white)])
                        continue
                    item=items[i]
                    if 'judul' in item:
                        row[col]=p(item['judul'],'KepalaPeriode' if item.get('utama') else 'BagianPeriode')
                        spans.extend([('SPAN',(col,i+1),(last,i+1)),('BACKGROUND',(col,i+1),(last,i+1),green if item.get('utama') else colors.HexColor('#e1ece5'))])
                    elif item['nama']=='Total hasil tercatat' and tiga_tabel:
                        pct=escape(item.get('persen_bahan','Belum dapat dihitung'))
                        suffix=' bahan baku' if pct.endswith('%') else ''
                        nilai=Paragraph(escape(item['nilai'])+'<br/><font size="7">'+pct+suffix+'</font>',styles['BagianPeriode'])
                        row[col:col+2]=[p(item['nama'],'BagianPeriode'),nilai]
                    else:row[col:col+2]=[item['nama'],item['nilai']]
                    if counts[j]==2 and item.get('persen_bahan') and item['nama']!='Total hasil tercatat':
                        pct=escape(item['persen_bahan']);suffix=' bahan baku' if pct.endswith('%') else ''
                        row[col+1]=Paragraph(escape(item['nilai'])+'<br/><font size="7">'+pct+suffix+'</font>',styles['IsiPeriode'])
                    if counts[j]==3:row[col+2]=item.get('persen_bahan','')
                rows.append(row)
            gap=.03 if tiga_tabel else .04
            part=(1-gap*(n-1))/n; widths=[]
            for j in range(n):
                ratios=[.46,.29,.25] if counts[j]==3 else [.60,.40]
                widths += [lebar*part*r for r in ratios]
                if j<n-1:
                    col=starts[j]+counts[j];widths.append(lebar*gap)
                    spans.extend([('BACKGROUND',(col,0),(col,-1),colors.white),
                                  ('LINEBELOW',(col,0),(col,-1),.5,colors.white),
                                  ('LINEABOVE',(col,0),(col,0),.5,colors.white)])
            story.extend([tabel(rows,widths,spans=spans),Spacer(1,2*mm)])
            continue
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
        from app.services.laporan_kepala import susun
        kepala=data.get('kepala_tabel') or susun(cols)
        spans=[];headers=len(kepala);rows=[['']*len(cols) for _ in kepala]
        for i,cells in enumerate(kepala):
            for c in cells:
                col=c['mulai'];rows[i][col]=c['nama']
                if c['kolom']>1 or c['baris']>1:
                    spans.append(('SPAN',(col,i),(col+c['kolom']-1,i+c['baris']-1)))
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
