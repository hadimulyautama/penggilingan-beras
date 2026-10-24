"""PDF rekap terstruktur dari penyusun data yang sama dengan layar."""
from html import escape
from io import BytesIO

from app.services.jasa import JUDUL_REKAP
from app.services.bahan_silo import kg_rinci


def buat_pdf(data: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

    ink, muted, border, pale = [colors.HexColor(x) for x in ('#173042','#52636d','#dce3e6','#f3f6f7')]
    body = ParagraphStyle('RekapBody', fontName='Helvetica', fontSize=9, leading=13, textColor=ink)
    small = ParagraphStyle('RekapSmall', parent=body, fontSize=8, leading=12, textColor=muted)
    title = ParagraphStyle('RekapTitle', parent=body, fontName='Helvetica-Bold', fontSize=22, leading=27)
    section = ParagraphStyle('RekapSection', parent=body, fontName='Helvetica-Bold', fontSize=11, leading=15, spaceBefore=10, spaceAfter=6)
    def p(value, style=body):
        return Paragraph(escape(str(value)), style)
    def table(headers, rows, widths):
        values = [[p(x,small) for x in headers]] + [[p(x) for x in row] for row in rows]
        t = Table(values, colWidths=widths, repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),pale),('LINEBELOW',(0,0),(-1,0),.5,border),('LINEBELOW',(0,1),(-1,-1),.4,border),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        # Angka tetap rata kanan meskipun nama/ref membungkus baris.
        for row in values[1:]:
            row[-1].style = ParagraphStyle('RekapAngka', parent=body, alignment=2)
        return t
    story = [p('PESANAN JASA',small),Spacer(1,6),p(JUDUL_REKAP,title),Spacer(1,8),p(data['pelanggan']),Spacer(1,12)]
    story.append(table(['Nomor pesanan utama','Status'],[[data['kode'],data['status']]],[112*mm,62*mm]))
    if data['pesanan_asal']:
        story += [Spacer(1,10),p('Pesanan yang digabung: '+', '.join(j['kode'] for j in data['pesanan_asal'])),p('Nomor asal tetap disimpan. Seluruh hasil dan pengambilan dihitung satu kali pada pesanan utama.',small)]
    story += [Spacer(1,12),table(['Bahan diterima','Sudah diambil'],[[kg_rinci(data['masuk_kg']),kg_rinci(data['kembali_kg'])]],[87*mm,87*mm])]
    for key, heading, labels in [('dibawa','Penerimaan bahan',['Bahan','Referensi penerimaan','Berat']),('kembali','Pengambilan hasil',['Barang','Referensi pengambilan','Berat'])]:
        rows = [[r['nama'],r['kode'],kg_rinci(r['kg'])] for r in data[key]]
        story.append(KeepTogether([p(heading,section),table(labels,rows or [['Belum ada catatan.','—','—']],[59*mm,76*mm,39*mm])]))
    rows = [[r['nama'],kg_rinci(r['kg'])] for r in data['sisa']]
    story += [p('Masih di pabrik',section),table(['Barang / tahap','Berat'],rows or [['Tidak ada sisa barang tercatat.','—']],[135*mm,39*mm]),Spacer(1,5),p('Bobot ditampilkan per tahap; saldo antar tahap tidak dijumlahkan sebagai stok siap diambil.',small)]
    rows = [['Bahan diterima',kg_rinci(data['masuk_kg'])],['Sudah diambil',kg_rinci(data['kembali_kg'])]]+rows
    if data['selisih_kg']>0:rows.append(['Selisih',kg_rinci(data['selisih_kg'])])
    story += [p('Neraca bobot',section),table(['Keterangan','Berat'],rows,[135*mm,39*mm]),Spacer(1,5),p('Susut pengeringan, sekam & susut proses tidak diukur terpisah. Bobot selama proses berlangsung belum final.',small)]
    if data['bekatul']:
        story += [p('Bekatul per proses sosoh',section),p('Informasi hasil proses. Pengambilan hanya dihitung pada bagian Pengambilan hasil.',small),Spacer(1,5),table(['Proses','Berat'],[[r['kode'],kg_rinci(r['kg'])] for r in data['bekatul']],[135*mm,39*mm])]
    output=BytesIO()
    doc=SimpleDocTemplate(output,pagesize=A4,leftMargin=18*mm,rightMargin=18*mm,topMargin=16*mm,bottomMargin=16*mm,title=JUDUL_REKAP,author='PadiFlow')
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('Helvetica',8);canvas.setFillColor(muted)
        canvas.drawString(18*mm,9*mm,'PadiFlow  |  '+data['kode']);canvas.drawRightString(A4[0]-18*mm,9*mm,str(doc.page));canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
