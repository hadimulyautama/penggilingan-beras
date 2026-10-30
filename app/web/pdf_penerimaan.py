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


def potongan_kemasan(t):
    """Memisahkan total tersimpan, tidak menghitung ulang tara/harga/kontrol."""
    total,lain=t.get('total_tara_kg'),t.get('tara_lain_kg')
    if total is None or lain is None:return None
    total,lain=Decimal(str(total)),Decimal(str(lain))
    return total-lain if total>=lain>=0 else None


def kalimat_selisih(t, ada_nota=False):
    """Menerjemahkan tanda/status tersimpan; tidak menilai ulang batas."""
    status=t.get('status_kontrol')
    hasil={'NORMAL':'masih dalam batas kontrol','DALAM_BATAS':'masih dalam batas kontrol',
        'PERLU_PEMERIKSAAN':'perlu pemeriksaan','INVESTIGASI':'memerlukan investigasi',
        'KURANG':'kurang dari acuan menurut kontrol tersimpan',
        'KELEBIHAN':'kelebihan muatan menurut kontrol tersimpan',
        'TANPA_KONTROL':'tanpa kontrol pembanding'}.get(status,
        'hasil kontrol belum tersedia' if not status else 'status kontrol tersimpan: '+status.replace('_',' '))
    acuan=t.get('berat_acuan_kg');delta=t.get('selisih_kg');persen=t.get('selisih_persen')
    if status=='TANPA_KONTROL' or acuan is None or Decimal(str(acuan))<=0:
        kontrol=('status kontrol tersimpan: '+status.replace('_',' ') if status and status!='TANPA_KONTROL' else hasil)
        return 'Pembanding nota/acuan belum tersedia; '+kontrol+'.'
    if delta is None:return 'Selisih terhadap nota/acuan belum tercatat; '+hasil+'.'
    delta=Decimal(str(delta));basis='nota' if ada_nota else 'acuan tiket'
    arah='Lebih ringan' if delta<0 else 'Lebih berat' if delta>0 else 'Sama dengan'
    nilai=(' '+kg(abs(delta))) if delta else ''
    if persen is not None:
        pct=Decimal(str(persen))
        # Nilai historis yang tandanya tidak konsisten tidak dibetulkan.
        nilai+=(' ('+angka(abs(pct))+'%)' if delta*pct>=0 else
                ' (persentase tersimpan '+angka(pct)+'%)')
    else:nilai+=' (persentase belum tercatat)'
    return (arah+nilai+' dari '+basis if delta else arah+' '+basis+nilai)+'; '+hasil+'.'


def tanggal_bersama(values):
    dates={berzona(v).strftime('%d/%m/%Y') for v in values if v}
    return next(iter(dates)) if len(dates)==1 else None


def status_qc(d):
    groups=d['qc']
    if not groups:return 'Belum diperiksa' if d['jenis'] in ('pk','gabah_basah','gabah_kering') else 'QC belum tersedia'
    if not any(g['putaran'] for g in groups):return 'Belum diperiksa'
    if any(not g['putaran'] for g in groups):return 'Sebagian belum diperiksa'
    if any('Berjalan' in g['status'] for g in groups):return 'QC masih berjalan'
    return 'Catatan QC tersedia'


def kesimpulan(d):
    awal=('Barang diterima '+kg(d['berat']) if d['berat'] is not None else
          'Berat barang diterima: '+(d.get('keterangan_berat') or 'belum tercatat'))+'.'
    isi=[]
    for g in d['qc']:
        if not g['putaran']:
            isi.append(g['kode']+' belum diperiksa.');continue
        lama=any(x['nomor'] is None or x['nomor'] in g.get('putaran_lama',[]) for x in g['putaran'])
        n=len(g['putaran'])
        teks=g['kode']+(' memiliki catatan QC historis; jumlah putaran asli tidak lengkap' if lama else f' memiliki {n} pemeriksaan QC')
        r=g.get('rata')
        if r:
            mean=r['rows'][0]['hasil'] if g['jenis']=='pk' else (angka(r['air'])+'%' if r['air'] is not None else 'Belum dinilai')
            teks+=('; kadar air tersimpan ' if lama else '; rata-rata kadar air ')+mean
        isi.append(teks+'.')
    if not isi:isi.append('Belum ada catatan QC penerimaan.' if d['jenis'] in ('pk','gabah_basah','gabah_kering') else 'QC penerimaan jenis ini belum tersedia.')
    return awal+' '+' '.join(isi)


class Laporan(PenyajiDokumen):
    def __init__(self,d):
        super().__init__()
        self.d=d
        self.ink=colors.HexColor('#21332b')
        self.green=colors.HexColor('#32694b')
        self.pale=colors.HexColor('#eff4ee')
        self.border=colors.HexColor('#d1ded3')
        self.normal=ParagraphStyle('TerimaIsi',fontName='Helvetica',fontSize=8.5,
            leading=10.6,textColor=self.ink,splitLongWords=True)
        self.small=ParagraphStyle('TerimaKecil',parent=self.normal,fontSize=7.8,
            leading=9.8,textColor=colors.HexColor('#596f64'))
        self.bold=ParagraphStyle('TerimaTebal',parent=self.normal,fontName='Helvetica-Bold')
        self.head=ParagraphStyle('TerimaKepalaTabel',parent=self.bold,textColor=colors.white)
        self.section=ParagraphStyle('TerimaBagian',parent=self.bold,fontSize=9.5,
            leading=12,textColor=self.green,keepWithNext=True)
        self.width=182*mm

    def p(self,value,style=None):
        # Label/data tidak ditafsirkan sebagai markup, termasuk catatan lab.
        teks=str(value).replace('\u2011','-').replace('–','-').replace('—','-')
        return Paragraph(escape(teks).replace('\n','<br/>'),style or self.normal)

    def fakta(self,label,value,style=None):
        return Paragraph('<b>'+escape(label)+':</b> '+escape(str(value)).replace('\n','<br/>'),style or self.normal)

    def bagian(self,nama):
        t=Table([[self.p(nama,self.section)]],colWidths=[self.width],hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),self.pale),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
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
            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
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
        p=self.p('Tiket TeraFlow: '+self.d['tiket']['kode'],self.bold);_,ph=p.wrap(self.width*.55,100)
        p.drawOn(c,left,h-29*mm-ph+8)
        label='PENERIMAAN: '+self.d['status'].upper()+('' if self.d['final'] else ' | BELUM FINAL')
        c.setFont('Helvetica-Bold',8);c.setFillColor(self.green if self.d['final'] else colors.HexColor('#9b4c24'))
        c.drawRightString(w-left,h-29*mm,label)
        c.setStrokeColor(self.border);c.line(left,h-33*mm,w-left,h-33*mm)
        c.restoreState()

    def footer(self,c,n,total):
        c.saveState();left=14*mm
        if total>1:
            c.setFillColor(colors.HexColor('#9b4c24'));c.setFont('Helvetica-Bold',7)
            c.drawString(left,A4[1]-36*mm,'MELEBIHI SATU HALAMAN - seluruh catatan tetap dicetak lengkap')
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
            topMargin=37*mm,bottomMargin=17*mm,title=JUDUL,author=self.d['pembuat'])
        frame=Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,
            leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        doc.addPageTemplates(PageTemplate(id='penerimaan',frames=[frame],onPage=self.kop))
        doc.build(story,canvasmaker=Halaman)
        return out.getvalue()


def buat_pdf(d):
    v=Laporan(d);p=v.p;story=[];t=d['timbang'] or {};ticket=d['tiket']
    jenis=ticket.get('jenis_nama') or {'gabah_basah':'Gabah basah','gabah_kering':'Gabah kering','pk':'PK','beras':'Beras','broken':'Broken'}.get(d['jenis'],'Jenis belum tercatat')
    if d['jenis']=='pk' and 'pecah kulit' not in jenis.lower():jenis+=' (beras pecah kulit)'
    muatan=t.get('muatan',[])
    nota=list(dict.fromkeys(m['nomor_acuan'] for m in muatan if m.get('nomor_acuan')))
    tanggal=list(dict.fromkeys(berzona(c['waktu']).strftime('%d/%m/%Y') for c in d['catatan'] if c['waktu']))
    if not tanggal and ticket.get('timbang1_waktu'):
        tanggal=[berzona(ticket['timbang1_waktu']).strftime('%d/%m/%Y')+' (tiket)']
    banyak_pihak=len(d['pihak'])>1
    pihak=next(iter(d['pihak'].values())) if not banyak_pihak else 'Lihat masing-masing catatan penerimaan'
    fields=[(v.fakta(d['label_pihak'],pihak),v.fakta('Tanggal',' · '.join(tanggal) or 'Belum tercatat')),
            (v.fakta('Jenis barang',jenis),v.fakta('Kendaraan / sopir',('Partai kecil' if t.get('cara_timbang')=='PARTAI' else ticket.get('nomor_polisi') or 'Belum tercatat')+' / '+(ticket.get('nama_sopir') or 'Belum tercatat')))]
    if d['pesanan']:
        fields.append((v.fakta('Pesanan jasa',' · '.join(d['pesanan'])),v.fakta('Nota',' · '.join(nota) or 'Belum tercatat')))
    else:
        fields.append((v.fakta('Nota supplier',' · '.join(nota) or 'Belum tercatat'),
                       v.fakta('Berat pada nota/acuan',kg(t.get('berat_acuan_kg')) if t.get('berat_acuan_kg') else 'Belum tercatat')))
    identitas=Table(fields,colWidths=[v.width/2]*2,hAlign='LEFT')
    identitas.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),8)]))
    story += [identitas,Spacer(1,4)]
    packs=[]
    for m in muatan:
        packs.append((f"{m['jumlah_karung']} karung" if m.get('jumlah_karung') is not None else 'Jumlah karung belum tercatat')+
            (' | '+m['kemasan'] if m.get('kemasan') else '')+
            (' | '+angka(m['ukuran_kg'])+' kg/kemasan' if m.get('ukuran_kg') is not None else '')+
            '\nBerat tiap karung kosong: '+(kg(m['tara_per_karung_kg'])+'/karung' if m.get('tara_per_karung_kg') is not None else 'Belum tercatat'))
    if not packs and t.get('jumlah_karung') is not None:
        packs.append(str(t['jumlah_karung'])+' karung\nRincian kemasan/tara historis belum tercatat')
    total=Table([[[p('BERAT BARANG DITERIMA',v.bold),p(kg(d['berat']) if d['berat'] is not None else d['keterangan_berat'] or 'Belum diterima',
        ParagraphStyle('TerimaTotal',parent=v.bold,fontSize=16,leading=19,textColor=v.green))],p('\n'.join(packs) or 'Kemasan: tidak tercatat',v.small)]],colWidths=[v.width*.5]*2)
    total.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),v.pale),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    story += [total,Spacer(1,8)]
    statuses=[ticket.get('status_tiket'),t.get('status_transaksi')]
    if ticket.get('status_tiket')=='DITUTUP_PAKSA' or t.get('status_transaksi') not in (None,'AKTIF'):
        story.append(p('Status tiket/transaksi: '+' / '.join(x for x in statuses if x)+'. '+(t.get('tutup_paksa_alasan') or t.get('void_alasan') or t.get('keterangan') or t.get('catatan') or 'Alasan tidak tercatat.'),v.bold))
    story.append(v.bagian('01  Rincian penerimaan'))
    tanggal_terima=tanggal_bersama(c['waktu'] for c in d['catatan'])
    zona=berzona(d['dibuat']).tzname() or ''
    cols=['Partai (batch)','Berat diterima','Waktu '+zona,'Pencatat'];widths=[.29,.22,.23,.26]
    if banyak_pihak:cols+=['Pihak'];widths=[.2,.18,.2,.2,.22]
    rows=[]
    for c in d['catatan']:
        values=[c['kode'],('Ditolak: ' if c['status']=='ditolak' else '')+kg(c['berat']),waktu(c['waktu'],bool(tanggal_terima)),c['pencatat']]
        if banyak_pihak:values.append(c['pihak']+('\nPesanan: '+c['pesanan'] if c.get('pesanan') else ''))
        rows.append(values)
    story.append(v.tabel(cols,rows or [['Belum ada catatan penerimaan','Belum diterima','-','-']+(['-'] if banyak_pihak else [])],widths))
    for c in d['catatan']:
        if c.get('alasan_penolakan'):story.append(p('Alasan penolakan '+c['kode']+': '+c['alasan_penolakan'],v.bold))
    story += [Spacer(1,5),v.bagian('02  Hasil penimbangan')]
    if t.get('cara_timbang')=='PARTAI':
        tanggal_partai=tanggal_bersama(x['waktu'] for x in t['penimbangan'])
        waktu_kepala='Waktu '+zona+('\n'+tanggal_partai if tanggal_partai and tanggal_partai!=tanggal_terima else '')
        rows=[[str(x['urutan']),kg(x['berat_kg']),waktu(x['waktu'],bool(tanggal_partai)),x.get('petugas') or 'Tidak tercatat'] for x in t['penimbangan']]
        story.append(v.tabel(['Penimbangan partai','Berat',waktu_kepala,'Petugas'],rows or [['Rincian partai belum tersedia','-','-','-']],[.25,.23,.25,.27]))
        story.append(v.fakta('Total penimbangan partai (tersimpan)',kg(t.get('netto_timbangan_kg')),v.small))
        for x in t['penimbangan']:
            if x.get('catatan'):story.append(p(f"Catatan partai {x['urutan']}: {x['catatan']}",v.small))
    else:
        def sebut_bobot(n):
            nilai=t.get(f'timbang{n}_kg');bruto=t.get('berat_bermuatan_kg');kosong=t.get('berat_kosong_kg')
            if nilai is not None and bruto!=kosong:
                if nilai==bruto:return f'{n}. Kendaraan + muatan (bruto)'
                if nilai==kosong:return f'{n}. Kendaraan kosong (tara)'
            return f'{n}. Timbang '+('pertama' if n==1 else 'kedua')
        tanggal_timbang=tanggal_bersama((t.get('timbang1_waktu'),t.get('timbang2_waktu')))
        waktu_kepala='Waktu '+zona+('\n'+tanggal_timbang if tanggal_timbang and tanggal_timbang!=tanggal_terima else '')
        rows=[[sebut_bobot(n),kg(t.get(f'timbang{n}_kg')),waktu(t.get(f'timbang{n}_waktu'),bool(tanggal_timbang)),t.get(f'petugas{n}') or 'Tidak tercatat'] for n in (1,2)]
        story.append(v.tabel(['Penimbangan kendaraan','Berat',waktu_kepala,'Petugas'],rows,[.35,.19,.2,.26]))
        if any('Timbang ' in r[0] for r in rows):
            story.append(p('Kendaraan beserta muatan (bruto): '+kg(t.get('berat_bermuatan_kg'))+' | Kendaraan kosong (tara): '+kg(t.get('berat_kosong_kg')),v.small))
    story += [Spacer(1,3),v.fakta('Berat sebelum potongan kemasan (netto)',kg(t.get('netto_timbangan_kg')),v.small),
        v.fakta('Potongan berat karung/kemasan',kg(potongan_kemasan(t))+'; potongan lain: '+kg(t.get('tara_lain_kg'))+'; total: '+kg(t.get('total_tara_kg')),v.small),
        v.fakta('Berat barang setelah potongan',kg(t.get('berat_barang_kg'))+'. Berat nota/acuan: '+(kg(t.get('berat_acuan_kg')) if t.get('berat_acuan_kg') else 'Belum tercatat')+'.',v.small),
        v.fakta('Perbandingan dengan nota/acuan',kalimat_selisih(t,bool(nota)),v.small)]
    for label,key in [('Keterangan tiket','keterangan'),('Catatan tiket','catatan')]:
        if t.get(key):story.append(p(label+': '+t[key],v.small))
    for m in muatan:
        if m.get('catatan'):story.append(p('Catatan muatan '+str(m['urutan'])+': '+m['catatan'],v.small))
    story += [Spacer(1,6),v.bagian('03  Pemeriksaan mutu (QC) | '+status_qc(d).upper())]
    if not d['qc']:
        kosong=('Belum ada batch penerimaan untuk pemeriksaan QC.' if d['jenis'] in ('gabah_basah','gabah_kering','pk') else
                'Pencatatan QC penerimaan jenis barang ini belum tersedia. Catatan produksi tidak dianggap QC.')
        story.append(p(kosong,v.small))
    for g in d['qc']:
        story += [CondPageBreak(35*mm),p('Partai '+g['kode']+' | '+g['status'],v.bold)]
        if not g['putaran']:
            story += [p('Belum diperiksa. Tidak digabung dengan QC batch lain.',v.small),Spacer(1,6)];continue
        qc_ke_tabel(story,v,g)
    if any(g['jenis']=='pk' for g in d['qc']):
        story.append(p('Susut uji adalah persentase penyusutan/bekatul pada uji lab penyosohan, terpisah dari potongan berat kemasan.',v.small))
    story += [p('Rata-rata berlaku per partai dan memakai seluruh isian yang tersedia; isian kosong tidak dianggap nol. Kategori mengikuti aturan QC yang berlaku.',v.small),Spacer(1,5)]
    ringkas=Table([[v.fakta('Kesimpulan',kesimpulan(d),v.small)]],colWidths=[v.width],hAlign='LEFT')
    ringkas.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),v.pale),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    story += [ringkas,Spacer(1,10)]
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
    headers=['QC / waktu','Kadar air','Butir patah','Susut uji','Butir kuning','Kandungan gabah','Merang'] if pk else ['QC / waktu','KA 1','KA 2','Biji hijau','Densiti']+(['Lamur / sak'] if basah else [])
    widths=[.2,.13,.13,.13,.14,.15,.12] if pk else ([.25,.12,.12,.19,.16,.16] if basah else [.26,.14,.14,.24,.22])
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
        story.append(p('Nilai mutu: '+(angka(q['nilai'])+' dari 100 (kelas '+q['kelas']+')' if q['nilai'] is not None else 'Belum dinilai')+'. '+hitungan.replace('Gabah:','Kandungan gabah:'),v.small))
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
