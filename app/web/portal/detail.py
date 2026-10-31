"""Susunan detail pelanggan di atas HTML pembaca Produksi yang sudah dibatasi."""
from urllib.parse import parse_qsl,urlsplit


JENIS={'pengeringan':'Pengeringan','pendinginan':'Pendinginan','giling':'Penggilingan',
       'sosoh':'Penyosohan','transfer':'Pemindahan barang'}


def ringkas(s,base,*,report_available=None):
    path=urlsplit(base).path.removeprefix('/pelanggan')
    stok=s.select_one('.pk-detail')
    proses=s.select_one('.proses-detail')
    riwayat=s.select_one('.riwayat-detail') if path.startswith(('/riwayat-giling/',
        '/riwayat-pengeringan/','/riwayat-sosoh/','/riwayat-transfer/')) else None
    root=stok or proses or riwayat
    if root is None:return s
    root['class']=[*root.get('class',[]),'pelanggan-detail']

    def lipat(section,label):
        if section is None or section.find_parent('details'):return
        wrapper=s.new_tag('details',attrs={'class':'pelanggan-detail-lipat'})
        summary=s.new_tag('summary');summary.string=label;wrapper.append(summary)
        section.wrap(wrapper)

    # Identitas pengguna sudah ada pada shell. ID jasa dan pengaturan mesin
    # bukan informasi yang perlu dibaca berulang untuk mengetahui stok/hasil.
    for el in root.select('.pk-detail__owner,.pk-detail__actions,.pk-detail__overline,.identitas-barang,.riwayat-status--jasa'):
        el.decompose()
    internal={'ID jasa','Pemilik','Pemilik jasa','Pemilik bahan','Pelanggan',
        'Mode dryer','Mode pengeringan','Ikatan silo aktif','Silo yang sedang dipakai'}
    for dt in list(root.select('dt')):
        if dt.get_text(' ',strip=True) in internal:
            row=dt.parent
            if row.name=='div':row.decompose()
    for nota in list(root.select('.nota')):
        if nota.get_text(' ',strip=True).startswith('ID jasa '):nota.decompose()

    labels={'Letak':'Lokasi','Rendemen':'Rasio hasil','Rendemen sementara':'Rasio hasil sementara',
        'Hasil PK kumulatif':'Total hasil giling','Nilai kualitas':'Pemeriksaan mutu',
        'Rincian QC':'Hasil pemeriksaan','Perhitungan nilai kualitas':'Perhitungan pemeriksaan mutu',
        'QC gabah asal':'Pemeriksaan mutu bahan asal','Jenis PK dari sumber':'Jenis bahan',
        'Silo dalam proses':'Lokasi bahan','Durasi efektif':'Lama proses aktif',
        'Neraca hasil':'Hasil proses','Neraca sosoh sementara':'Hasil sementara',
        'Berat tersedia':'Stok saat ini','Sisa di gudang':'Stok saat ini',
        'PROSES AKTIF':'Proses berjalan','Sudah ditransfer':'Sudah dipindahkan'}
    for el in root.select('h2,h3,summary,dt,.pk-detail__weight>span,.proses-detail__statistik article>span'):
        text=el.get_text(' ',strip=True)
        if text in labels and not el.find(['table','dl']):el.string=labels[text]

    heading=root.find('h1')
    if stok:
        for el in stok.select('.pk-detail__chip,.pk-detail__dot'):el.decompose()
        if not stok.select_one('.produk-detail') and 'produk-detail' not in stok.get('class',[]):
            if heading:
                kode=s.new_tag('p',attrs={'class':'pelanggan-detail-kode'});kode.string=heading.get_text(' ',strip=True)
                heading.string='Beras pecah kulit (PK)';heading.insert_after(kode)
            eyebrow=stok.select_one('.pk-detail__eyebrow')
            if eyebrow:
                lokasi=next((x.get_text(strip=True) for x in eyebrow.find_all('span')
                    if x.get_text(strip=True) in ('Gudang 1','Gudang 2')),None)
                eyebrow.string=lokasi or 'Rincian stok'
        else:
            for p in stok.select('.pk-detail__heading>p'):
                if p.get_text(strip=True).startswith('Pemilik:'):p.decompose()
        for section in list(stok.select('.pk-detail__quality')):lipat(section,'Pemeriksaan mutu')
        for section in list(stok.select('.pk-detail__batches')):lipat(section,'Asal bahan')
        lipat(stok.select_one('section[aria-labelledby=rincian-produk]'),'Rincian kemasan dan asal stok')
        for el in stok.select('.anak__kepala'):
            text=el.get_text(' ',strip=True)
            if text.startswith('Perkiraan asal stok (FIFO)'):el.string=text.replace(' (FIFO)','')
        for section in list(s.select('section[aria-labelledby=perhitungan-kualitas-pk]')):
            lipat(section,'Perhitungan pemeriksaan mutu')
        for section in list(s.select('section[aria-labelledby=riwayat-qc-pk]')):
            lipat(section,'Riwayat pemeriksaan mutu')
        for section in list(s.select('.qc-gabah-asal')):lipat(section,'Pemeriksaan mutu bahan asal')

    if proses or riwayat:
        parts=path.split('/')
        jenis=parts[2] if path.startswith('/proses-aktif/') else parts[1].removeprefix('riwayat-')
        if heading and jenis in JENIS:
            kode=s.new_tag('p',attrs={'class':'pelanggan-detail-kode'});kode.string=heading.get_text(' ',strip=True)
            heading.string=JENIS[jenis];heading.insert_after(kode)
        for section in list(root.select('.qc-gabah-asal')):lipat(section,'Pemeriksaan mutu bahan asal')
        for summary in root.select('details>summary'):
            text=summary.get_text(' ',strip=True)
            if text.startswith('Data batch asal · '):summary.string=text.replace('Data batch asal','Asal bahan',1)+' batch'
        if proses:
            for eyebrow in proses.select('.proses-detail__label>.riwayat-detail__eyebrow'):eyebrow.decompose()
            for p in proses.select('header.riwayat-detail__hero>p'):
                text=p.get_text(' ',strip=True)
                if 'pengeringan-detail' in proses.get('class',[]) and text.startswith('Gudang 1 · ') and text.count(' · ')>=2:
                    p.string=text.rsplit(' · ',1)[0]
            for tab in proses.select('a[role=tab]'):
                control=tab.get('aria-controls')
                if control=='panel-bahan':tab.string='Bahan'
                elif control=='panel-hasil':tab.string='Hasil & mutu'
        # Tab tetap satu pintu untuk tiap bagian. Tombol di dalam ringkasan
        # yang membuka tab yang sama hanya menambah pilihan berulang.
        for a in list(root.select('a[href]')):
            q=dict(parse_qsl(urlsplit(a['href']).query))
            if a.get('role')!='tab' and 'tab_detail' in q and a.get_text(strip=True).startswith(('Lihat','Buka')):
                a.decompose()
        tindakan=root.select_one('section#tindakan-proses')
        if tindakan:
            kondisi=tindakan.select_one('.pendinginan-kondisi')
            if kondisi:
                title=tindakan.find('h2')
                if title:title.string='Status pendinginan'
                for p in kondisi.find_all('p'):p.string='Pendinginan dan pemindahan barang ditangani petugas.'
            else:
                for warning in list(tindakan.select('.riwayat-detail__warning')):
                    tindakan.insert_before(warning.extract())
                tindakan.decompose()
        for section in list(root.select('section#kualitas-proses')):
            lipat(section,'Rincian pemeriksaan mutu')
        for h in list(root.select('h2')):
            text=h.get_text(' ',strip=True)
            if text.startswith(('Bahan & pemakaian silo','Asal bahan','Data batch asal')):
                section=h.find_parent('section')
                if section:lipat(section,'Asal dan pemakaian bahan')
        for p in list(root.select('p.bantu')):
            if p.get_text(' ',strip=True).startswith(('Sesudah fase berubah,','Sesudah proses ditutup,')):
                p.decompose()
        if report_available is False:
            for a in list(root.select('a[href]')):
                if urlsplit(a['href']).path.endswith(('/laporan','/laporan.pdf')):a.decompose()
            note=s.new_tag('p',attrs={'class':'pelanggan-redup'});note.string='PDF belum tersedia.';root.append(note)

    # Tidak menghapus tautan kode asal di tabel. Yang dibersihkan hanya
    # tombol baca yang berulang, bukan hubungan antarbatch/proses.
    seen=set()
    for a in list(root.select('a[href]')):
        if a.get('role')=='tab' or a.find_parent('nav'):continue
        text=a.get_text(' ',strip=True)
        if 'btn' not in a.get('class',[]) and not text.startswith(('Lihat ','Buka ','Unduh ')):continue
        u=urlsplit(a['href']);query=tuple(sorted((k,v) for k,v in parse_qsl(u.query)
            if k not in ('pelanggan_id','kepemilikan','pemilik','jasa','kembali_kerja','kembali_qc')))
        key=(u.path,query,u.fragment)
        if key in seen:a.decompose()
        else:seen.add(key)
    return s
