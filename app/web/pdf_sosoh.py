"""Ringkasan hasil penyosohan, neraca, sumber PK dan QC bahan."""
from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace
from reportlab.platypus import Table, TableStyle, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from app.database import now_local
from app.web.pdf_giling import LaporanGiling
from app.web.pdf_proses import angka, persen, durasi, bagian_jeda
from app.web.pdf_penerimaan import waktu
from app.services.mutu_pk import penilaian_dari_log
from app.web.qc_warna import GabunganQC, NilaiQC


def ringkas_sumber(data):
    groups={}
    for row in data['source_rows']:
        key=(row['kind'],row['code'],row['material'],row['owner'])
        if key not in groups:groups[key]=dict(row,weight=Decimal('0'))
        if row['weight'] is None:groups[key]['weight']=None
        elif groups[key]['weight'] is not None:groups[key]['weight']+=Decimal(str(row['weight']))
    return list(groups.values())


def qc_bahan(data):
    groups=defaultdict(list)
    for row in data['milling_qc']+data['external_qc']:
        # Tiga angka dan kategori asli dinilai dengan layanan QC yang sama.
        groups[row['code']].append(SimpleNamespace(kadar_air=row['moisture'],broken_persen=row['broken'],susut_persen=row['loss'],butir_kuning=row.get('yellow'),gabah=row.get('paddy'),merang=row.get('chaff')))
    return {code:dict(penilaian_dari_log(rows),jumlah=len(rows)) for code,rows in groups.items()}


def buat_pdf(data):
    proc=data['process'];balance=data['balance'];complete=data.get('input_complete',True)
    v=LaporanGiling(dict(kode=proc.kode_proses,dibuat=data.get('dibuat') or now_local(),pembuat=data.get('pembuat') or 'PadiFlow'))
    v.judul='Laporan Penyosohan';story=[]
    def kg(n):return angka(n)+' kg' if n is not None else 'Belum dicatat'
    def note(s):story.append(v.p(s,v.small))
    def section(s):story.append(v.heading(s,3))
    def table(h,r,w):story.append(v.tabel(h,r,w))
    def pct(n):return persen(n) if n is not None else 'Belum dapat dipastikan'
    def duration(a,b):return durasi((b-a).total_seconds()) if a and b else 'Belum tercatat'
    sources=ringkas_sumber(data)
    mixed=any(x['kind'] not in ('giling','pk_luar','legacy') for x in sources)
    bahan='BAHAN DIPAKAI' if mixed else 'PK DIPAKAI'
    for label,value in [('Pemilik barang',data['owner']),('Operator',data['operator'])]:story.append(v.fakta(label,value))
    if data.get('jasa'):story.append(v.fakta('Pesanan jasa',data['jasa']))
    section('Ringkasan hasil')
    rate=balance.beras.kg/balance.bahan_kg*100 if complete and balance.bahan_kg else None
    cards=[(bahan,kg(balance.bahan_kg) if complete else 'Belum dapat dipastikan'),('HASIL BERAS',kg(balance.beras.kg)),('RENDEMEN BERAS',pct(rate))]
    t=Table([[[v.p(k,v.small),v.p(val,ParagraphStyle('AngkaSosoh',parent=v.bold,fontSize=18,leading=23))] for k,val in cards]],colWidths=[v.width/3]*3)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),v.pale),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]));story.append(t)
    section('Hasil penyosohan')
    labels={'sayur':'Ekonomis','medium':'Beras Medium','medsuper':'Beras Medium Super','premium':'Beras Premium','beras_b':'Beras B','menir':'Menir','broken':'Broken','bekatul':'Bekatul','reject':'Reject'}
    rows=[]
    kinds=list(dict.fromkeys([*data['outputs']]))
    from app.services.stok import nama_produk
    labels.update({j: nama_produk(j) for j in kinds})
    for kind in kinds:
        amount=Decimal(str(data['outputs'].get(kind) or 0))
        if amount>0:
            rows.append([labels.get(kind) or nama_produk(kind).capitalize(),kg(amount),pct(amount/Decimal(str(balance.bahan_kg))*100 if complete and balance.bahan_kg else None)])
    rows.append(['Total hasil tercatat',kg(balance.keluar_kg),pct(balance.keluar_kg/balance.bahan_kg*100 if complete and balance.bahan_kg else None)])
    table(['Produk','Berat','% dari bahan dipakai'],rows,[.5,.25,.25])
    section('Neraca berat')
    table(['Bahan dipakai','Total hasil tercatat','Selisih neraca'],[[kg(balance.bahan_kg) if complete else 'Belum dapat dipastikan',kg(balance.keluar_kg),(kg(balance.susut.kg)+' ('+pct(balance.susut.persen)+')') if complete else 'Belum dapat dipastikan']],[.33,.34,.33])
    note('Total hasil = beras + hasil samping. Selisih neraca berbeda dari susut uji pada QC.')
    if not complete:
        bobot=data.get('bobot_bahan')
        if bobot is not None and not bobot.pasti:
            note('Belum dapat dipastikan: bobot truk belum final. Bobot bahan mengikuti sumber timbang sampai dinyatakan final.')
        else:
            note('Belum dapat dipastikan: sisa pemakaian silo belum dicatat lengkap.')
    previous=data.get('neraca_tercatat')
    if previous:note('Hitungan ulang mengikuti koreksi bobot truk. Saat ditutup: bahan '+kg(previous.bahan_kg)+', susut '+kg(previous.susut.kg)+'. Catatan penutupan tetap tersimpan.')
    section('Waktu proses')
    note(waktu(proc.waktu_mulai)+' - '+waktu(proc.waktu_selesai)+' | Durasi '+duration(proc.waktu_mulai,proc.waktu_selesai))
    jeda=data.get('jeda')
    if jeda:note('Total jeda: '+jeda['tertahan']+' | Durasi efektif: '+jeda['efektif'])
    note('Status: penyosohan selesai. QC bahan PK pada lampiran berbeda dari QC beras hasil penyosohan.')
    story.append(PageBreak())
    story.append(v.heading('Bahan PK dan catatan proses' if not mixed else 'Bahan dan catatan proses',2))
    section('Asal bahan yang dipakai')
    table(['Sumber','Jenis bahan','Pemilik / pemasok','Berat dipakai'],[[x['code'],x['material'],x['owner'],kg(x['weight'])] for x in sources] or [['Belum tercatat','-','-','-']],[.3,.23,.25,.22])
    note('Berat di atas adalah jumlah yang dipakai pada penyosohan ini, bukan seluruh netto lot asal.')
    qc=qc_bahan(data)
    section('Ringkasan QC bahan PK')
    table(['Sumber','Kadar air','Butir patah','Susut uji'],[[code]+[x['hasil'] for x in rating['rows'][:3]] for code,rating in qc.items()] or [['Belum ada catatan QC','-','-','-']],[.4,.2,.2,.2])
    for code,rating in qc.items():note(code+': '+str(rating['jumlah'])+' pemeriksaan. Nilai yang belum diisi tidak dianggap nol.')
    note('Ini adalah mutu bahan PK, bukan mutu beras hasil penyosohan.')
    if qc:
        story.append(v.heading('Mutu visual bahan',4))
        table(['Sumber','Butir kuning / kandungan gabah / merang'],[[code,GabunganQC([NilaiQC(r['label'],r['hasil']) for r in rating['rows'][3:]])] for code,rating in qc.items()],[.4,.6])
    if jeda and jeda['items']:
        # Semua kejadian, termasuk koreksi dan pembatalan, tetap tersedia.
        bagian_jeda(story,jeda,lambda value,style=None:v.heading(value,3) if style else v.p(value),lambda rows,widths:v.tabel(rows[0],rows[1:],[x/sum(widths) for x in widths]),'section')
    if not sources:note('Jejak asal bahan belum tercatat.')
    return v.pdf(story)
