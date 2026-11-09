"""Laporan penggilingan: penyajian data layanan lama, tanpa mutasi proses."""
from collections import defaultdict, Counter
from decimal import Decimal
from app.database import now_local
from app.web.pdf_penerimaan import Laporan, angka, waktu, tanggal_bersama
from app.web.pdf_proses import angka as angka_stok, durasi
from app.web.qc_warna import NilaiQC
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Table, TableStyle, Spacer, PageBreak
from app.web.identitas_dokumen import NAMA_PERUSAHAAN


def persen(v):
    return angka(v,max(2,-Decimal(str(v)).normalize().as_tuple().exponent))+'%' if v is not None else 'Belum dinilai'


def lamur(q):
    if q.lamur is None:return 'Tidak tercatat'
    return ('Ya' if q.lamur else 'Tidak')+(' · '+str(q.jumlah_sak_lamur)+' sak' if q.jumlah_sak_lamur is not None else ' · sak tidak tercatat')


def rincian_gabah(batches, headers, samples, legacy_names=None):
    """Parent adalah agregat layanan QC; dua bacaan asli tetap tersedia.

    Rata-rata per pemeriksaan hanya menyajikan pasangan pembacaan yang sah,
    bukan menilai ulang mutu. Rata-rata batch tetap membaca parent yang sama
    dengan Stok/detail dan tidak dibentuk dari angka tampilan.
    """
    groups=defaultdict(list)
    for q,nama in samples:groups[q.purchase_batch_qc_id].append((q,nama))
    rows=[];summary={}
    for b,_ in batches:
        head=headers.get(b.id);entries=groups.get(head.id,[]) if head else []
        for q,nama in entries:
            readings=[Decimal(str(v)) for v in (q.kadar_air_1,q.kadar_air_2) if v is not None]
            avg=sum(readings)/len(readings) if readings else None
            rows.append(dict(code=b.kode_batch,batch=f'{b.kode_batch} · QC {q.nomor_sampel}',number=q.nomor_sampel,
                time=q.created_at,actor=nama or 'Tidak tercatat',moisture=persen(avg),
                readings=' / '.join(persen(v) for v in (q.kadar_air_1,q.kadar_air_2)),
                lamur=lamur(q),green=(q.biji_hijau or 'Tidak tercatat').replace('_',' '),
                density=(q.densiti or 'Tidak tercatat').capitalize()))
        if head:
            summary[b.kode_batch]=dict(air=b.kadar_air_awal_persen,
                n=sum(v is not None for q,_ in entries for v in (q.kadar_air_1,q.kadar_air_2)),
                sak=head.jumlah_sak_lamur,lamur=head.lamur,legacy=not entries)
            if not entries:
                rows.append(dict(code=b.kode_batch,batch=b.kode_batch+' · QC historis',number=None,
                    time=head.created_at,actor=(legacy_names or {}).get(head.input_by) or 'Pencatat ID '+str(head.input_by),moisture=persen(b.kadar_air_awal_persen),
                    readings='Rincian bacaan tidak tersedia',lamur=lamur(head),
                    green=(head.biji_hijau or 'Tidak tercatat').replace('_',' '),density=head.densiti or 'Tidak tercatat'))
    return rows,summary


def ringkasan_penerimaan(data):
    """Gunakan agregat sumber, bukan menghitung rata-rata dari teks PDF."""
    groups=defaultdict(list)
    for row in data['raw_qc']:
        groups[row.get('code') or row['batch'].split(' · QC')[0]].append(row)
    result=[]
    multiple_origins=len({b['origin'] for b in data['batches']})>1
    for batch in data['batches']:
        code=batch['code']; rows=groups[code]; summary=data.get('raw_summary',{}).get(code)
        air=persen(summary['air']) if summary else 'Belum tersedia'
        sak=str(summary['sak'])+' sak' if summary and summary['sak'] is not None else 'Belum dicatat'
        if summary and summary['legacy']:
            green='Historis: '+(rows[0]['green'] if rows else 'Belum dicatat')
        else:
            counts=Counter(row.get('green') or 'Belum dicatat' for row in rows)
            green='; '.join(str(k).capitalize()+' '+str(n)+'/'+str(len(rows)) for k,n in counts.items()) or 'Belum diperiksa'
        result.append([code+'\nGabah '+batch['condition'].lower()+('\n'+batch['origin'] if multiple_origins else ''),angka_stok(batch['weight'])+' kg' if batch['weight'] is not None else 'Belum dicatat',air,sak,green])
    return result


class LaporanGiling(Laporan):
    def __init__(self,d):
        super().__init__(d)
        self.judul='Laporan Penggilingan'

    def pdf(self, story):
        from app.web.pdf_dokumen import PenyajiDokumen
        opening = [self.heading(self.judul,1), self.p(self.d['kode'],self.small), Spacer(1,12)]
        closing = [Spacer(1,8),self.p('Dibuat '+waktu(self.d['dibuat'])+' | '+self.d['pembuat'],self.small)]
        return PenyajiDokumen.pdf(self,opening+story+closing,judul=self.judul,referensi=self.d['kode'])

    def bagian(self, nama):
        return self.heading(nama,3)



def buat_pdf(data):
    d=dict(data,dibuat=data.get('dibuat') or now_local(),pembuat=data.get('pembuat') or 'PadiFlow')
    v=LaporanGiling(d);p=v.p;story=[]
    def kg(x):return angka_stok(x)+' kg' if x is not None else 'Belum dicatat'
    def note(s):story.append(p(s,v.small))
    def section(s):story.extend([Spacer(1,3),v.bagian(s)])
    def table(h,r,w,rata=False):
        story.append(v.tabel(h,r,w,rata=rata))
    def stamp(x,day=False):return waktu(x,day)
    def duration(a,b):return durasi((b-a).total_seconds()) if a and b else 'Belum tercatat'
    owner=d.get('label_owner','Pemilik barang')
    facts=[(v.fakta(owner,d['owner']),v.fakta('Tanggal proses',stamp(d['start']))),
        (v.fakta('Pesanan jasa',d.get('jasa') or 'Tidak berlaku') if d.get('jasa') else v.fakta('Kondisi PK',d['class']),
         v.fakta('Bahan',d['composition']))]
    ident=Table(facts,colWidths=[v.width/2]*2)
    ident.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    story.append(ident)
    section('Ringkasan hasil')
    rate=f"{float(d['yield']):.1f}%".replace('.',',') if d['yield'] is not None else 'Belum dihitung'
    total=Table([[[p(k,v.small),p(val,ParagraphStyle('GilingAngkaUtama',parent=v.bold,fontSize=15,leading=18))] for k,val in [('GABAH DIPAKAI',kg(d['input_kg'])),('HASIL PK',kg(d['output_kg'])),('RENDEMEN PK',rate)]]],colWidths=[v.width/3]*3)
    total.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),v.pale),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]));story.append(total)
    story.append(Spacer(1,10))
    rating=d.get('qc_rating')
    if rating:
        headers=['Susut uji' if r['label']=='Susut' else r['label'] for r in rating['rows'][:3]]
        values=[r['hasil'] for r in rating['rows'][:3]]
        if d.get('show_quality',True):
            headers.append('Nilai mutu')
            values.append(angka(rating['nilai'])+' / 100 ('+rating['kelas']+')' if rating['nilai'] is not None else 'Belum dinilai')
        table(headers,[values],[1/len(headers)]*len(headers))
        categories=rating['rows'][3:]
        if categories:note('; '.join(r['label']+': '+r['hasil'] for r in categories)+'.')
        note('Rata-rata '+str(len(d['qc']))+' pemeriksaan. Susut uji adalah hasil uji mutu, terpisah dari rendemen.')
    else:
        note('Rata-rata QC: '+d['qc_summary'])
    section('Waktu proses')
    note(stamp(d['start'])+' - '+stamp(d['end'])+' | '+duration(d['start'],d['end']))
    jeda=d.get('jeda')
    if jeda:
        if jeda['items']:
            note('Total jeda: '+jeda['tertahan']+' | Durasi efektif: '+jeda['efektif'])
        else:note('Tanpa jeda tercatat.')
    note('Status proses: selesai. '+('Hasil diverifikasi '+stamp(d['verified_at'])+' · '+kg(d['verified_weight'])+' · '+(d.get('verification_actor') or 'Pemeriksa tidak tercatat') if d['verified_at'] else 'Verifikasi hasil belum tercatat.'))
    note('Rincian pencatatan hasil, QC dan riwayat bahan tersedia pada lampiran.')
    section('Asal bahan dan QC penerimaan')
    table(['Batch','Netto asal','KA rata-rata','Lamur','Biji hijau'],ringkasan_penerimaan(d) or [['Belum tercatat','-','-','-','-']],[.24,.2,.15,.13,.28])
    kendaraan=list(dict.fromkeys(b.get('plate') for b in d['batches'] if b.get('plate') and b.get('plate')!='Tidak tercatat'))
    if kendaraan:note('Kendaraan asal: '+', '.join(kendaraan))
    note('QC penerimaan sebelum pengeringan bila bahan melalui pengeringan. Biji hijau menunjukkan jumlah pemeriksaan pada tiap kategori; data historis ditandai terpisah.')
    counts=[r['n'] for r in d.get('raw_summary',{}).values() if not r['legacy']]
    if counts and len(counts)==len(d['batches']) and len(set(counts))==1:
        note('Setiap batch: '+str(counts[0])+' bacaan kadar air.')
    story.append(PageBreak())
    story.append(v.heading('Rincian penggilingan',2))
    section('Pencatatan hasil PK')
    logs=d['progress']
    values=[]
    if len(logs)>1:
        first,previous=logs[0],logs[-2]
        values.append([stamp(first['time'])+(' - '+stamp(previous['time']) if len(logs)>2 else ''),str(len(logs)-1)+' pencatatan',kg(first['weight'])+(' - '+kg(previous['weight']) if len(logs)>2 else '')])
    if logs:
        last=logs[-1]
        values.append([stamp(last['time']),'Catatan terakhir',kg(last['weight'])])
    table(['Waktu','Pencatatan','PK kumulatif'],values or [['Belum ada catatan','-','-']],[.38,.24,.38])
    if logs:
        note('Pencatat: '+', '.join(dict.fromkeys(x.get('actor') or 'Tidak tercatat' for x in logs))+'. '+str(len(logs))+' pencatatan; angka kumulatif tidak dijumlahkan.')
    section('QC hasil PK')
    rows=d['qc'];rating=d.get('qc_rating')
    if rows:
        day=bool(tanggal_bersama(x['time'] for x in rows))
        actors={x.get('actor','Tidak tercatat') for x in rows};same_actor=len(actors)==1
        if day or same_actor:note(('Tanggal: '+tanggal_bersama(x['time'] for x in rows)+' | ' if day else '')+('Seluruh pemeriksaan: '+next(iter(actors)) if same_actor else ''))
        categories=[('Butir kuning','yellow'),('Kandungan gabah','paddy'),('Merang','chaff')]
        same_categories=all(len({x.get(key,'Belum dinilai') for x in rows})==1 for _,key in categories)
        headers=['QC / waktu / pencatat','Kadar air','Butir patah','Susut uji','Kondisi']
        values=[[str(x.get('number',i))+' / '+stamp(x['time'],day)+('' if same_actor else '\n'+x.get('actor','Tidak tercatat')),x['moisture'],x['broken'],x['loss'],x['condition']] for i,x in enumerate(rows,1)]
        if same_categories:
            table(headers,values,[.28,.18,.18,.18,.18])
            note('Semua pemeriksaan: '+'; '.join(label+': '+rows[0].get(key,'Belum dinilai') for label,key in categories)+'.')
        else:
            for value,x in zip(values,rows):
                value.extend(NilaiQC(label,x.get(key,'Belum dinilai')) for label,key in categories)
            table(headers+[label for label,_ in categories],values,[.22,.11,.11,.11,.12,.11,.11,.11])
        for i,x in enumerate(rows,1):
            if x.get('note'):
                note('QC '+str(x.get('number',i))+' · '+x['note'])
    else:note('Belum diperiksa.')
    if d['drying_lots'] or d['drying_moisture']:
        section('Pengeringan sumber bahan')
        for lot in d['drying_lots']:
            note(lot['code'])
            note('Pengeringan: '+stamp(lot['dry_start'])+' - '+stamp(lot['dry_end'])+' ('+duration(lot['dry_start'],lot['dry_end'])+'). Pendinginan: '+stamp(lot['cool_start'])+' - '+stamp(lot['cool_end'])+' ('+duration(lot['cool_start'],lot['cool_end'])+').')
        moisture=defaultdict(list)
        for x in d['drying_moisture']:moisture[x['lot']].append(x)
        for lot,entries in moisture.items():
            if len(moisture)>1:note(lot)
            table(['Waktu','Pembacaan sampel','Rata-rata tes','Indikator mesin'],[[stamp(x['time']),x['samples'],x['average'],x['machine']] for x in entries],[.22,.42,.18,.18])
    if jeda and jeda['items']:
        section('Riwayat jeda')
        for e in jeda['items']:
            note(e['aksi']+(' · Dibatalkan' if e['dibatalkan'] else '')+' · '+e['petugas']+' · '+e['waktu']+' · Dicatat: '+e['dicatat']+' · '+e['sebab']+(' · '+e['catatan'] if e['catatan'] else '')+(' · Alasan terlambat: '+e['alasan'] if e['alasan'] else ''))
    section('Transfer dan sisa PK')
    values = [[stamp(x['time']),x['code']+' / '+x['destination'],kg(x['weight'])] for x in d['transfers']]
    table(['Waktu','Catatan / referensi','Berat'],values or [['Belum ada catatan','-','-']],[.24,.54,.22])
    note('Transfer ke Gudang 2: '+kg(d['transferred_kg'])+'. Sisa PK tersedia: '+kg(d['available_kg'])+'.')
    return v.pdf(story)
