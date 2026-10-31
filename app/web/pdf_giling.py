"""Laporan penggilingan: penyajian data layanan lama, tanpa mutasi proses."""
from collections import defaultdict
from decimal import Decimal
from app.database import now_local
from app.web.pdf_penerimaan import Laporan, angka, waktu, tanggal_bersama
from app.web.pdf_proses import angka as angka_stok, durasi
from app.web.qc_warna import NilaiQC
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Table, TableStyle, Spacer
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


class LaporanGiling(Laporan):
    def __init__(self,d):
        super().__init__(d)
        self.judul='Laporan Penggilingan'
        # Ukuran tetap, tidak mengecil mengikuti jumlah catatan.
        self.normal=ParagraphStyle('GilingIsi',parent=self.normal,fontSize=8,leading=9.6)
        self.small=ParagraphStyle('GilingCatatan',parent=self.small,fontSize=7.5,leading=9)
        self.bold=ParagraphStyle('GilingTebal',parent=self.normal,fontName='Helvetica-Bold')
        self.head=ParagraphStyle('GilingKepala',parent=self.bold,textColor=colors.white)
    def kop(self,c,doc):
        c.saveState();w,h=A4;left=14*mm
        c.setFillColor(self.green);c.rect(0,h-2*mm,w,2*mm,fill=1,stroke=0)
        c.setFont('Helvetica-Bold',11);c.drawString(left,h-11*mm,NAMA_PERUSAHAAN)
        c.setFillColor(self.ink);c.setFont('Helvetica-Bold',20);c.drawString(left,h-22*mm,'Laporan Penggilingan')
        c.setFont('Helvetica-Bold',8);c.drawString(left,h-29*mm,self.d['kode'])
        status='PENGGILINGAN '+self.d.get('status','selesai').upper()
        status+=' | '+(self.d.get('verification_status') or 'Verifikasi belum tercatat').replace('_',' ').upper()
        c.setFillColor(self.green);c.drawRightString(w-left,h-29*mm,status)
        c.setStrokeColor(self.border);c.line(left,h-33*mm,w-left,h-33*mm);c.restoreState()


def buat_pdf(data):
    d=dict(data,dibuat=data.get('dibuat') or now_local(),pembuat=data.get('pembuat') or 'PadiFlow')
    v=LaporanGiling(d);p=v.p;story=[]
    def kg(x):return angka_stok(x)+' kg' if x is not None else 'Belum dicatat'
    def note(s):story.append(p(s,v.small))
    def section(s):story.extend([Spacer(1,5),v.bagian(s)])
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
    rate=f"{float(d['yield']):.1f}%".replace('.',',') if d['yield'] is not None else 'Belum dihitung'
    total=Table([[[p(k,v.small),p(val,ParagraphStyle('GilingAngkaUtama',parent=v.bold,fontSize=15,leading=18))] for k,val in [('GABAH DIPAKAI',kg(d['input_kg'])),('HASIL PK',kg(d['output_kg'])),('RENDEMEN PK',rate)]]],colWidths=[v.width/3]*3)
    total.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),v.pale),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]));story.append(total)
    section('01  Asal bahan dan pemakaian silo')
    origins=list(dict.fromkeys(x['origin'] for x in d['batches']))
    multi=len(origins)>1
    headers=['Batch bahan','Netto batch asal','Sopir','Nomor polisi']+(['Asal / pemilik'] if multi else [])
    rows=[[x['code']+'\nGabah '+x['condition'].lower(),kg(x['weight']),x.get('driver','Tidak tercatat'),x['plate']]+([x['origin']] if multi else []) for x in d['batches']]
    table(headers,rows or [['Tidak tercatat']+['-']*(len(headers)-1)], [.22,.19,.18,.18,.23] if multi else [.32,.23,.23,.22])
    groups=d.get('pemakaian_silo')
    if groups:
        rows=[]
        for i,g in enumerate(groups,1):
            a=dict(g['angka'])
            rows.append([g['nama']+' / '+ ' · '.join(x['nama'] for x in g['sumber'])+f' · catatan {i}',a.get('Awal','Belum diketahui'),a.get('Tambahan','Tidak dipisahkan'),a.get('Terpakai','Belum dicatat'),a.get('Sisa akhir','Belum dicatat')+'\n'+g['status']])
        table(['Silo / sumber','Awal','Tambahan','Dipakai','Sisa akhir'],rows,[.34,.16,.16,.16,.18])
        # Ringkasan sisa silo memakai audit pelepasan layanan, bukan sum FIFO.
        for g in groups:
            if 'ringkasan_sisa' in g:note(g['nama']+' · sisa terakhir silo: '+g['ringkasan_sisa']+' · '+g['ringkasan_status'])
        note('Tambahan yang belum dipisahkan tidak dianggap nol. Setiap pemakaian/sumber tetap terpisah.')
    else:
        table(['Silo / sumber','Awal','Tambahan','Dipakai','Sisa akhir'],[[x['silo']+' / '+x['source'],kg(x['weight']),'Tidak dipisahkan',kg(x['used']),kg(x['remaining'])] for x in d['sources']],[.34,.16,.16,.16,.18])
    note('Netto batch asal bukan jumlah yang seluruhnya digiling. Sisa silo berbeda dari sisa PK.')
    if d['drying_lots']:
        note('Riwayat pengeringan bahan:')
        table(['Lot / batch asal','Pengeringan mulai - selesai / durasi','Pendinginan mulai - selesai / durasi'],[[x['code']+' / '+x['batches'],stamp(x['dry_start'])+' - '+stamp(x['dry_end'])+' / '+duration(x['dry_start'],x['dry_end']),stamp(x['cool_start'])+' - '+stamp(x['cool_end'])+' / '+duration(x['cool_start'],x['cool_end'])] for x in d['drying_lots']],[.3,.35,.35])
    else:note('Tidak ada hubungan pengeringan tercatat pada sumber proses ini.')
    if d['drying_moisture']:
        table(['Lot / waktu','Pembacaan sampel','Rata-rata tes','Indikator mesin'],[[x['lot']+' / '+stamp(x['time']),x['samples'],x['average'],x['machine']] for x in d['drying_moisture']],[.32,.32,.18,.18])
    section('02  QC bahan sebelum digiling')
    rawgroups=defaultdict(list)
    for x in d['raw_qc']:rawgroups[x.get('code') or x['batch'].split(' · QC')[0]].append(x)
    for b in d['batches']:
        code=b['code'];rows=rawgroups.get(code,[]);r=d.get('raw_summary',{}).get(code)
        note('Batch '+code+' | '+str(len(rows))+' catatan QC'+(' historis' if r and r['legacy'] else ''))
        if not rows:note('Belum diperiksa.');continue
        day=bool(tanggal_bersama(x['time'] for x in rows))
        actors={x.get('actor','Tidak tercatat') for x in rows};same_actor=len(actors)==1
        if day or same_actor:note(('Tanggal: '+tanggal_bersama(x['time'] for x in rows)+' | ' if day else '')+('Seluruh pemeriksaan: '+next(iter(actors)) if same_actor else ''))
        values=[[str(x.get('number',x['batch']))+' / '+stamp(x['time'],day)+('' if same_actor else '\n'+x.get('actor','Tidak tercatat')),x['moisture'],NilaiQC('Lamur',x['lamur']),NilaiQC('Biji hijau',x['green']),NilaiQC('Densiti',x['density'])] for x in rows]
        if r:values.append(['Rata-rata',persen(r['air']),'Total '+str(r['sak'])+' sak' if r['sak'] is not None else 'Sak tidak tercatat','-','-'])
        table(['QC / waktu / pencatat','KA rata-rata' if all(x.get('readings') for x in rows) else 'Kadar air tersimpan','Lamur / sak','Biji hijau','Densiti'],values,[.3,.16,.19,.18,.17],bool(r))
        if not r:note('Rata-rata batch belum tersedia pada sumber lama; nilai tersimpan tidak dihitung dari teks tampilan.')
        if r:note(str(r['n'])+' pembacaan kadar air. Lamur mengikuti catatan asli, termasuk setelah pengeringan.' if not r['legacy'] else 'QC historis: rincian putaran/pembacaan asli tidak tersedia; nilai tersimpan dipertahankan.')
        readings=[str(x.get('number'))+': '+x['readings'] for x in rows if x.get('readings')]
        if readings:note('Bacaan 1 / 2: '+'; '.join(readings))
    if not d['batches']:note('Asal batch belum tercatat; QC tidak direka.')
    section('03  QC hasil PK - seluruh putaran dan rata-rata')
    rows=d['qc'];rating=d.get('qc_rating')
    if rows:
        day=bool(tanggal_bersama(x['time'] for x in rows))
        actors={x.get('actor','Tidak tercatat') for x in rows};same_actor=len(actors)==1
        if day or same_actor:note(('Tanggal: '+tanggal_bersama(x['time'] for x in rows)+' | ' if day else '')+('Seluruh pemeriksaan: '+next(iter(actors)) if same_actor else ''))
        values=[[str(x.get('number',i))+' / '+stamp(x['time'],day)+('' if same_actor else '\n'+x.get('actor','Tidak tercatat')),x['moisture'],x['broken'],x['loss'],NilaiQC('Butir kuning',x.get('yellow','Belum dinilai')),NilaiQC('Gabah',x.get('paddy','Belum dinilai')),NilaiQC('Merang',x.get('chaff','Belum dinilai'))] for i,x in enumerate(rows,1)]
        if rating:values.append(['Rata-rata']+[NilaiQC(r['label'],r['hasil']) if i>=3 else r['hasil'] for i,r in enumerate(rating['rows'])])
        table(['QC / waktu / pencatat','Kadar air','Butir patah','Susut uji','Butir kuning','Kandungan gabah','Merang'],values,[.25,.12,.12,.12,.13,.14,.12],bool(rating))
        if rating:
            note(('Nilai mutu: '+(angka(rating['nilai'])+' / 100 ('+rating['kelas']+')' if rating['nilai'] is not None else 'Belum dinilai')+'. ' if d.get('show_quality',True) else '')+'Pengukuran: '+'; '.join(r['label']+' '+str(r['n']) for r in rating['rows']))
        notes=['QC '+str(x.get('number',i))+' · kondisi '+x['condition']+' · catatan lab: '+(x.get('note') or 'Belum dicatat') for i,x in enumerate(rows,1)]
        for line in (['; '.join(notes)] if all(len(n)<100 for n in notes) and len(notes)<=5 else notes):note(line)
    else:note('Belum diperiksa.')
    if not rating:note('Rata-rata QC: '+d['qc_summary'])
    note('Susut uji adalah parameter mutu laboratorium, terpisah dari rendemen PK. Kategori rata-rata mengikuti aturan QC; kosong tidak dianggap nol.')
    section('04  Pencatatan hasil, transfer dan sisa PK')
    values=[[stamp(x['time']),'Hasil PK kumulatif · '+x.get('actor','Pencatat tidak tercatat'),kg(x['weight'])] for x in d['progress']]
    values += [[stamp(x['time']),x['code']+' / '+x['destination'],kg(x['weight'])] for x in d['transfers']]
    table(['Waktu','Catatan / referensi','Berat'],values or [['Belum ada catatan','-','-']],[.24,.54,.22])
    note('Catatan hasil PK bersifat kumulatif, tidak dijumlahkan sebagai total produksi. Transfer ke Gudang 2: '+kg(d['transferred_kg'])+'. Sisa PK tersedia: '+kg(d['available_kg'])+'.')
    note('Verifikasi hasil: '+stamp(d['verified_at'])+' · '+kg(d['verified_weight'])+' · '+(d.get('verification_actor') or 'Pemeriksa tidak tercatat'))
    section('05  Waktu proses dan kesimpulan')
    note('Mulai: '+stamp(d['start'])+'; selesai: '+stamp(d['end'])+'; durasi: '+duration(d['start'],d['end'])+'.')
    jeda=d.get('jeda')
    if jeda:
        note('Durasi kalender: '+jeda['kalender']+'; total jeda: '+jeda['tertahan']+'; waktu aktif / Durasi efektif: '+jeda['efektif']+'.')
        for e in jeda['items']:
            note(e['aksi']+(' · Dibatalkan' if e['dibatalkan'] else '')+' · '+e['petugas']+' · '+e['waktu']+' · Dicatat: '+e['dicatat']+' · '+e['sebab']+(' · '+e['catatan'] if e['catatan'] else '')+(' · Alasan terlambat: '+e['alasan'] if e['alasan'] else ''))
    else:note('Rincian jeda / waktu aktif belum tersedia.')
    note('Kesimpulan: '+kg(d['input_kg'])+' gabah dipakai menghasilkan '+kg(d['output_kg'])+' PK (rendemen '+rate+').')
    return v.pdf(story)
