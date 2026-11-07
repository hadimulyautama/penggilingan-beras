"""Ringkasan pengeringan; pembacaan dan otorisasi tetap pada layanan lama."""
from collections import defaultdict
from datetime import datetime
from reportlab.platypus import Table, TableStyle, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from app.database import now_local
from app.web.pdf_giling import LaporanGiling
from app.web.pdf_proses import angka, durasi, teks_angka, bagian_jeda
from app.web.pdf_penerimaan import waktu, tanggal_bersama
from app.web.qc_warna import NilaiQC


def buat_pdf(data):
    d=dict(data,dibuat=data.get('dibuat') or now_local(),pembuat=data.get('pembuat') or 'PadiFlow')
    view=LaporanGiling(d);view.judul='Laporan Pengeringan'
    story=[]
    def p(x):return view.p(teks_angka(x))
    def note(x):story.append(view.p(teks_angka(x),view.small))
    def section(x):story.extend([Spacer(1,6),view.bagian(x)])
    def table(h,r,w):story.append(view.tabel(h,[[teks_angka(c) for c in row] for row in r],w))
    def kg(x):return angka(x)+' kg' if x is not None else 'Belum dicatat'
    def duration(a,b):return durasi((b-a).total_seconds()) if a and b else 'Belum tercatat'
    story.extend([view.fakta('Pemilik barang',d['owner']),view.fakta('Mesin / mode',d['dryer'])])
    section('Ringkasan hasil')
    valid=[x for x in d['moisture'] if x.get('average') not in (None,'','—','-','Tidak tersedia')]
    first,last=(valid[0],valid[-1]) if valid else (None,None)
    bobot=d.get('bobot_pengeringan') or {}
    cards=[('GABAH BASAH MASUK',bobot.get('basah') or kg(d['weight'])),('KA TES AWAL',first['average'] if first else 'Belum dicatat'),('KA TES AKHIR',last['average'] if last else 'Belum dicatat')]
    main=Table([[[view.p(label,view.small),view.p(teks_angka(value),ParagraphStyle("AngkaPengeringan",parent=view.bold,fontSize=15,leading=18))] for label,value in cards]],colWidths=[view.width/3]*3)
    main.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),view.pale),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]));story.append(main)
    note('KA = kadar air. KA tes memakai rata-rata sampel pada pengukuran pertama dan terakhir yang memiliki bacaan.')
    if bobot.get('terukur'):
        note('Bobot kering terukur - flowing scale: '+bobot['terukur'])
        note('Pencatatan bobot terukur: '+(waktu(datetime.fromisoformat(bobot['timbang_waktu'])) if bobot.get('timbang_waktu') else 'Belum tercatat')+' | '+(bobot.get('timbang_petugas') or 'Petugas belum tercatat'))
    if bobot.get('kering'):
        note('Estimasi bobot gabah kering: Sekitar '+bobot['kering']+'. Estimasi dari perubahan indikator mesin pertama tercatat sampai selesai; bukan hasil timbang dan tidak mengganti bobot basah asal.')
        note('Indikator mesin pertama / selesai: '+(bobot.get('awal') or 'Belum tercatat')+' / '+(bobot.get('akhir') or 'Belum tercatat'))
    section('Hasil pengukuran terakhir')
    machines=[x for x in d['moisture'] if x.get('machine') not in (None,'','—','-','Tidak tersedia')]
    machine=machines[-1] if machines else None
    rows=[]
    if last and machine and last['time']==machine['time']:
        rows.append([waktu(last['time']),last['average'],machine['machine']])
    else:
        if last:rows.append([waktu(last['time']),last['average'],'-'])
        if machine:rows.append([waktu(machine['time']),'-',machine['machine']])
    table(['Waktu','Rata-rata alat tes','Indikator mesin'],rows or [['Belum ada pembacaan','-','-']],[.4,.3,.3])
    if d['target'] is not None:note('Target kadar air: '+angka(d['target'])+'%.')
    section('Waktu proses')
    table(['Tahap','Mulai','Selesai','Durasi'],[
        ['Pengeringan',waktu(d['dry_start']),waktu(d['dry_end']),duration(d['dry_start'],d['dry_end'])],
        ['Pendinginan',waktu(d['cool_start']),waktu(d['cool_end']),duration(d['cool_start'],d['cool_end'])],
        ['Total',waktu(d['dry_start']),waktu(d['cool_end']),duration(d['dry_start'],d['cool_end'])]], [.2,.27,.27,.26])
    note('Silo tujuan: '+d['silo'])
    note('Rincian pembacaan kadar air dan QC penerimaan tersedia pada lampiran.')
    story.append(PageBreak())
    story.append(view.heading('Pemantauan kadar air selama proses',2))
    table(['Waktu','Pembacaan alat tes','Rata-rata tes','Indikator mesin'],[[waktu(x['time']),x['samples'],x['average'],x['machine']] for x in d['moisture']] or [['Belum ada catatan','-','-','-']],[.22,.42,.18,.18])
    if d['cooling_notes']:
        section('Catatan pendinginan')
        for line in d['cooling_notes']:note(line)
    if d.get('jeda'):
        bagian_jeda(story,d['jeda'],lambda value,style=None:view.heading(value,3) if style else p(value),lambda rows,widths:view.tabel(rows[0],rows[1:],[w/sum(widths) for w in widths]),'section')
    story.append(PageBreak())
    story.append(view.heading('Bahan baku dan asal',2))
    table(['Batch','Asal / pemilik','Nomor polisi','Berat'],[[b['kode'],b['asal'],b['plat'],kg(b['weight'])] for b in d['batches']] or [['Belum tercatat','-','-','-']],[.28,.28,.22,.22])
    section('Riwayat QC bahan baku')
    groups=defaultdict(list)
    for row in d['qc']:groups[row['batch'].split(' · QC')[0]].append(row)
    for code,entries in groups.items():
        day=bool(tanggal_bersama(x['time'] for x in entries))
        story.append(view.heading(code,4))
        if day:note(tanggal_bersama(x['time'] for x in entries))
        table(['QC / waktu','Kadar air','Lamur / sak','Biji hijau','Densiti'],[[x['batch'].split(' · ')[-1]+' / '+waktu(x['time'],day),x['moisture'],NilaiQC('Lamur',x['lamur']),NilaiQC('Biji hijau',x['green']),NilaiQC('Densiti',x['density'])] for x in entries],[.28,.22,.18,.16,.16])
    if not groups:note('Belum ada catatan QC penerimaan.')
    return view.pdf(story)
