"""Laporan penerimaan A4 dari pembaca lama; layout tidak menghitung transaksi."""
from io import BytesIO
from html import escape
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
    Table, TableStyle, Spacer, KeepTogether, CondPageBreak)

from app.database import berzona
from app.web.pdf_dokumen import PenyajiDokumen
from app.web.identitas_dokumen import NAMA_PERUSAHAAN

JUDUL='Laporan Penerimaan Barang'


def angka(v, digit=2):
    if v is None:return 'Belum tercatat'
    return f'{float(v):,.{digit}f}'.replace(',','X').replace('.',',').replace('X','.')


def kg(v):
    if v is None:return 'Belum tercatat'
    n=Decimal(str(v))
    digit=max(2,-n.normalize().as_tuple().exponent)
    return format(n,f',.{digit}f').replace(',','X').replace('.',',').replace('X','.')+' kg'


def waktu(v, pendek=False):
    return berzona(v).strftime('%H:%M' if pendek else '%d/%m/%Y %H:%M') if v else 'Tidak tercatat'


class Laporan(PenyajiDokumen):
    def __init__(self,d):
        super().__init__()
        self.d=d
        self.ink=colors.HexColor('#21332b')
        self.green=colors.HexColor('#32694b')
        self.pale=colors.HexColor('#eff4ee')
        self.border=colors.HexColor('#d1ded3')
        self.normal=ParagraphStyle('TerimaIsi',fontName='Helvetica',fontSize=8.2,
            leading=10.5,textColor=self.ink,splitLongWords=True)
        self.small=ParagraphStyle('TerimaKecil',parent=self.normal,fontSize=7.6,
            leading=10,textColor=colors.HexColor('#596f64'))
        self.bold=ParagraphStyle('TerimaTebal',parent=self.normal,fontName='Helvetica-Bold')
        self.head=ParagraphStyle('TerimaKepalaTabel',parent=self.bold,textColor=colors.white)
        self.section=ParagraphStyle('TerimaBagian',parent=self.bold,fontSize=9.5,
            leading=12,textColor=self.green,keepWithNext=True)
        self.width=182*mm

    def p(self,value,style=None):
        # Label/data tidak ditafsirkan sebagai markup, termasuk catatan lab.
        teks=str(value).replace('\u2011','-').replace('–','-').replace('—','-')
        return Paragraph(escape(teks).replace('\n','<br/>'),style or self.normal)

    def bagian(self,nama):
        t=Table([[self.p(nama,self.section)]],colWidths=[self.width],hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),self.pale),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        t.keepWithNext=True
        return t

    def tabel(self,headers,rows,widths,*,rata=False,spans=()):
        data=[[self.p(h,self.head) for h in headers]]+[
            [self.p(c,self.bold if rata and i==len(rows)-1 else self.normal) for c in row]
            for i,row in enumerate(rows)]
        t=Table(data,colWidths=[w*self.width for w in widths],repeatRows=1,
            splitByRow=1,splitInRow=1,hAlign='LEFT')
        style=[('BACKGROUND',(0,0),(-1,0),self.green),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
            ('LINEBELOW',(0,1),(-1,-1),.35,self.border)]
        if rata:
            style += [('BACKGROUND',(0,-1),(-1,-1),self.pale),('LINEABOVE',(0,-1),(-1,-1),.6,self.green)]
        style += [('SPAN',a,b) for a,b in spans]
        t.setStyle(TableStyle(style))
        return t

    def kop(self,c,doc):
        c.saveState();w,h=A4;left=14*mm
        c.setFillColor(self.green);c.rect(0,h-2*mm,w,2*mm,fill=1,stroke=0)
        c.setFont('Helvetica-Bold',11);c.drawString(left,h-11*mm,NAMA_PERUSAHAAN)
        c.setFillColor(self.ink);c.setFont('Helvetica-Bold',20)
        c.drawString(left,h-22*mm,JUDUL)
        p=self.p(self.d['tiket']['kode'],self.bold);_,ph=p.wrap(self.width*.55,100)
        p.drawOn(c,left,h-29*mm-ph+8)
        label=self.d['status'].upper()+' | '+('TIMBANG FINAL' if self.d['final'] else 'BELUM FINAL')
        c.setFont('Helvetica-Bold',8);c.setFillColor(self.green if self.d['final'] else colors.HexColor('#9b4c24'))
        c.drawRightString(w-left,h-29*mm,label)
        c.setStrokeColor(self.border);c.line(left,h-33*mm,w-left,h-33*mm)
        c.restoreState()

    def footer(self,c,n,total):
        c.saveState();left=14*mm
        c.setStrokeColor(self.border);c.line(left,15*mm,A4[0]-left,15*mm)
        stamp=waktu(self.d['dibuat'])+' '+(berzona(self.d['dibuat']).tzname() or '')
        p=self.p('PadiFlow | Dibuat '+stamp+' | '+self.d['pembuat'],self.small)
        _,h=p.wrap(155*mm,40);p.drawOn(c,left,13*mm-h)
        c.setFillColor(self.small.textColor);c.setFont('Helvetica',7.6)
        c.drawRightString(A4[0]-left,10*mm,f'{n} / {total}')
        c.restoreState()

    def pdf(self,story):
        penyaji=self
        class Halaman(Canvas):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);self.halaman=[]
            def showPage(self):
                self.halaman.append(dict(self.__dict__));self._startPage()
            def save(self):
                total=len(self.halaman)
                for state in self.halaman:
                    self.__dict__.update(state)
                    penyaji.footer(self,self._pageNumber,total)
                    super().showPage()
                super().save()
        out=BytesIO()
        doc=BaseDocTemplate(out,pagesize=A4,leftMargin=14*mm,rightMargin=14*mm,
            topMargin=37*mm,bottomMargin=20*mm,title=JUDUL,author=self.d['pembuat'])
        frame=Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,
            leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        doc.addPageTemplates(PageTemplate(id='penerimaan',frames=[frame],onPage=self.kop))
        doc.build(story,canvasmaker=Halaman)
        return out.getvalue()


def buat_pdf(d):
    v=Laporan(d);p=v.p;story=[];t=d['timbang'] or {};ticket=d['tiket']
    jenis=ticket.get('jenis_nama') or {'gabah_basah':'Gabah basah','gabah_kering':'Gabah kering','pk':'PK','beras':'Beras','broken':'Broken'}.get(d['jenis'],'Jenis belum tercatat')
    muatan=t.get('muatan',[])
    nota=list(dict.fromkeys(m['nomor_acuan'] for m in muatan if m.get('nomor_acuan')))
    tanggal=list(dict.fromkeys(berzona(c['waktu']).strftime('%d/%m/%Y') for c in d['catatan'] if c['waktu']))
    if not tanggal and ticket.get('timbang1_waktu'):
        tanggal=[berzona(ticket['timbang1_waktu']).strftime('%d/%m/%Y')+' (tiket)']
    banyak_pihak=len(d['pihak'])>1
    fields=[(d['label_pihak']+': '+(next(iter(d['pihak'].values())) if not banyak_pihak else 'Lihat masing-masing catatan penerimaan'),
             'Tanggal: '+(' · '.join(tanggal) or 'Belum tercatat')),
            ('Jenis barang: '+jenis,'Armada / sopir: '+('Partai kecil' if t.get('cara_timbang')=='PARTAI' else ticket.get('nomor_polisi') or 'Belum tercatat')+' / '+(ticket.get('nama_sopir') or 'Belum tercatat')),
            ('Pesanan jasa: '+(' · '.join(d['pesanan']) or 'Tidak berlaku'),
             'Nota/acuan: '+(' · '.join(nota) or 'Belum tercatat'))]
    identitas=Table([[p(a),p(b)] for a,b in fields],colWidths=[v.width/2]*2,hAlign='LEFT')
    identitas.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),8)]))
    story += [identitas,Spacer(1,4)]
    packs=[]
    for m in muatan:
        packs.append((f"{m['jumlah_karung']} karung" if m.get('jumlah_karung') is not None else 'Jumlah karung belum tercatat')+
            (' | '+m['kemasan'] if m.get('kemasan') else '')+
            (' | '+angka(m['ukuran_kg'])+' kg/kemasan' if m.get('ukuran_kg') is not None else '')+
            '\nTara kemasan: '+(kg(m['tara_per_karung_kg'])+'/karung' if m.get('tara_per_karung_kg') is not None else 'Belum tercatat'))
    if not packs and t.get('jumlah_karung') is not None:
        packs.append(str(t['jumlah_karung'])+' karung\nRincian kemasan/tara historis belum tercatat')
    total=Table([[p('Diterima: '+(kg(d['berat']) if d['berat'] is not None else d['keterangan_berat'] or 'Belum diterima'),
        ParagraphStyle('TerimaTotal',parent=v.bold,fontSize=13,leading=16,textColor=v.green)),p('\n'.join(packs) or 'Kemasan: tidak tercatat',v.small)]],colWidths=[v.width*.5]*2)
    total.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),v.pale),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    story += [total,Spacer(1,8)]
    statuses=[ticket.get('status_tiket'),t.get('status_transaksi')]
    if ticket.get('status_tiket')=='DITUTUP_PAKSA' or t.get('status_transaksi') not in (None,'AKTIF'):
        story.append(p('Status tiket/transaksi: '+' / '.join(x for x in statuses if x)+'. '+(t.get('tutup_paksa_alasan') or t.get('void_alasan') or t.get('keterangan') or t.get('catatan') or 'Alasan tidak tercatat.'),v.bold))
    story.append(v.bagian('01  Penerimaan'))
    cols=['Batch','Bobot diterima','Waktu','Pencatat'];widths=[.29,.22,.23,.26]
    if banyak_pihak:cols+=['Pihak'];widths=[.2,.18,.2,.2,.22]
    rows=[]
    for c in d['catatan']:
        values=[c['kode'],('Ditolak: ' if c['status']=='ditolak' else '')+kg(c['berat']),waktu(c['waktu']),c['pencatat']]
        if banyak_pihak:values.append(c['pihak']+('\nPesanan: '+c['pesanan'] if c.get('pesanan') else ''))
        rows.append(values)
    story.append(v.tabel(cols,rows or [['Belum ada catatan penerimaan','Belum diterima','-','-']+(['-'] if banyak_pihak else [])],widths))
    for c in d['catatan']:
        if c.get('alasan_penolakan'):story.append(p('Alasan penolakan '+c['kode']+': '+c['alasan_penolakan'],v.bold))
    story += [Spacer(1,6),v.bagian('02  Data timbang')]
    if t.get('cara_timbang')=='PARTAI':
        rows=[[str(x['urutan']),kg(x['berat_kg']),waktu(x['waktu']),x.get('petugas') or 'Tidak tercatat'] for x in t['penimbangan']]
        story.append(v.tabel(['Partai','Bobot','Waktu','Petugas'],rows or [['Rincian partai belum tersedia','-','-','-']],[.25,.23,.25,.27]))
        for x in t['penimbangan']:
            if x.get('catatan'):story.append(p(f"Catatan partai {x['urutan']}: {x['catatan']}",v.small))
    else:
        rows=[['Pertama',kg(t.get('timbang1_kg')),waktu(t.get('timbang1_waktu')),t.get('petugas1') or 'Tidak tercatat'],
              ['Kedua',kg(t.get('timbang2_kg')),waktu(t.get('timbang2_waktu')),t.get('petugas2') or 'Tidak tercatat']]
        story.append(v.tabel(['Penimbangan','Bobot','Waktu','Petugas'],rows,[.25,.23,.25,.27]))
        story.append(p('Bruto kendaraan: '+kg(t.get('berat_bermuatan_kg'))+' | Tara kendaraan: '+kg(t.get('berat_kosong_kg')),v.small))
    lines=['Netto timbangan: '+kg(t.get('netto_timbangan_kg'))+' | Total potongan tara: '+kg(t.get('total_tara_kg'))+' (tara lain '+kg(t.get('tara_lain_kg'))+')',
        'Berat barang setelah tara: '+kg(t.get('berat_barang_kg'))+' | Berat nota/acuan: '+kg(t.get('berat_acuan_kg')),
        'Selisih: '+kg(t.get('selisih_kg'))+' / '+(angka(t['selisih_persen'])+'%' if t.get('selisih_persen') is not None else 'Belum tercatat')+' | Kontrol: '+(t.get('status_kontrol') or 'Belum tersedia')]
    story += [Spacer(1,3),p('\n'.join(lines),v.small)]
    for label,key in [('Keterangan tiket','keterangan'),('Catatan tiket','catatan')]:
        if t.get(key):story.append(p(label+': '+t[key],v.small))
    for m in muatan:
        if m.get('catatan'):story.append(p('Catatan muatan '+str(m['urutan'])+': '+m['catatan'],v.small))
    story += [Spacer(1,7),v.bagian('03  QC lengkap dan rata-rata seluruh putaran')]
    if not d['qc']:
        kosong=('Belum ada batch penerimaan untuk pemeriksaan QC.' if d['jenis'] in ('gabah_basah','gabah_kering','pk') else
                'Pencatatan QC penerimaan jenis barang ini belum tersedia. Catatan produksi tidak dianggap QC.')
        story.append(p(kosong,v.small))
    for g in d['qc']:
        story += [CondPageBreak(45*mm),p('Batch '+g['kode']+' | '+g['status'],v.bold)]
        if not g['putaran']:
            story += [p('Belum diperiksa. Tidak digabung dengan QC batch lain.',v.small),Spacer(1,6)];continue
        qc_ke_tabel(story,v,g)
    story += [Spacer(1,5),p('Rata-rata memakai seluruh isian per komponen menurut aturan QC yang berlaku; isian kosong tidak dianggap nol. Bobot diterima bukan saldo stok terkini.',v.small),Spacer(1,10)]
    tanda=Table([[p('Penyerah/sopir',v.bold),'',p('Penerima',v.bold)],['','',''],
        [p('Nama / tanda tangan',v.small),'',p('Nama / tanda tangan',v.small)]],
        colWidths=[v.width*.47,v.width*.06,v.width*.47],rowHeights=[14,38,13])
    tanda.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
        ('LINEABOVE',(0,2),(0,2),.5,v.border),('LINEABOVE',(2,2),(2,2),.5,v.border)]))
    story.append(KeepTogether([tanda]))
    return v.pdf(story)


def qc_ke_tabel(story,v,g):
    rounds=[dict(x,asal_lama=x['nomor'] in g.get('putaran_lama',[])) for x in g['putaran']];p=v.p
    petugas={x['petugas'] for x in rounds}
    dates={berzona(x['waktu']).strftime('%d/%m/%Y') if x['waktu'] else None for x in rounds}
    same_day=len(dates)==1 and None not in dates
    meta=(next(iter(dates))+' | ' if same_day else '')
    if len(petugas)==1:meta+='Pencatat seluruh putaran: '+next(iter(petugas))
    if meta:story.append(p(meta,v.small))
    pk=g['jenis']=='pk';basah=g['jenis']=='gabah_basah'
    if not pk and all(x['nomor'] is None for x in rounds):
        fields=[]
        for x in rounds:
            story.append(p('Catatan lama | '+waktu(x['waktu'])+' | '+x['petugas'],v.small))
            fields.extend([label,value] for label,value in x['hasil'])
        fields.append(['Rata-rata seluruh putaran','Rincian pengukuran asli tidak tersedia; nilai tersimpan di atas dipertahankan.'])
        story.append(v.tabel([g['kode']+' - parameter','Hasil historis'],fields,[.4,.6],rata=True))
        story += [p('Data QC historis tanpa rincian putaran; pembacaan, pencatat, atau waktu yang tidak tersimpan tidak direka.',v.small),Spacer(1,7)]
        return
    headers=['QC / waktu','Kadar air','Broken','Susut uji','Butir kuning','Gabah','Merang'] if pk else ['QC / waktu','KA 1','KA 2','Biji hijau','Densiti']+(['Lamur / sak'] if basah else [])
    widths=[.22,.13,.12,.13,.15,.12,.13] if pk else ([.25,.12,.12,.19,.16,.16] if basah else [.26,.14,.14,.24,.22])
    labels=['Kadar air','Broken','Susut uji','Butir kuning','Gabah','Merang'] if pk else ['Kadar air 1','Kadar air 2','Biji hijau','Densiti']+(['Lamur'] if basah else [])
    rows=[]
    for x in rounds:
        name=('Catatan lama' if x.get('asal_lama') or x['nomor'] is None else str(x['nomor']))+' / '+waktu(x['waktu'],same_day)
        if len(petugas)>1:name+='\n'+x['petugas']
        fields=dict(x['hasil']);rows.append([name]+[fields.get(k,'Belum tercatat') for k in labels])
    spans=[]
    if g['rata']:
        if pk:
            rows.append(['Rata-rata']+[x['hasil'] for x in g['rata']['rows']])
        else:
            r=g['rata']
            rows.append(['Rata-rata',(angka(r['air'])+'%' if r['air'] is not None else 'Belum dinilai')+'\n'+str(r['n_air'])+' pembacaan','',
                         'Terakhir: '+r['hijau'],'Terakhir: '+r['densiti']]+
                         ([('Pernah lamur' if r['lamur'] else 'Tidak lamur')+' / '+str(r['sak'])+' sak' if r['lamur'] is not None and r['sak'] is not None else 'Belum tercatat'] if basah else []))
            spans=[((1,-1),(2,-1))]
    # Identitas batch juga diulang bersama kepala tabel pada halaman lanjutan.
    headers[0]=g['kode']+'\n'+headers[0]
    story.append(v.tabel(headers,rows,widths,rata=bool(g['rata']),spans=spans))
    if pk and g['rata']:
        q=g['rata']
        hitungan=('Jumlah pengukuran asli tidak tersedia pada snapshot historis.' if all(x.get('asal_lama') or x['nomor'] is None for x in rounds) else
            'Pengukuran per komponen: '+'; '.join(r['label']+': '+str(r['n']) for r in q['rows'])+'.')
        story.append(p('Nilai kualitas: '+(angka(q['nilai'])+' / 100 ('+q['kelas']+')' if q['nilai'] is not None else 'Belum dinilai')+'. '+hitungan,v.small))
        notes=[]
        for x in rounds:
            note=dict(x['hasil']).get('Catatan lab','Belum dicatat')
            notes.append(('lama' if x['nomor'] is None or x.get('asal_lama') else str(x['nomor']))+': '+note)
        # Catatan pendek mengikuti susunan ringkas desain. Catatan panjang
        # tetap utuh, dengan identitas batch/kepala berulang pada lanjutan.
        isi=['; '.join(notes)] if len(notes)<=10 and all(len(n)<90 for n in notes) else notes
        lab=Table([[p('Catatan lab tiap putaran - '+g['kode'],v.small)]]+
                  [[p(n,v.small)] for n in isi],colWidths=[v.width],repeatRows=1,
                  splitByRow=1,splitInRow=1,hAlign='LEFT')
        lab.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
            ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]))
        story.append(lab)
    if any(x.get('asal_lama') or x['nomor'] is None for x in rounds):
        story.append(p('Data QC historis: rincian putaran asli tidak tersedia. Angka yang tersimpan dipertahankan; petugas/waktu yang tidak tersimpan tidak direka.',v.small))
    story.append(Spacer(1,7))
