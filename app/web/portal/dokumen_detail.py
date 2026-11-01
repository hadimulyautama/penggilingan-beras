"""Bahasa pembaca dokumen pelanggan; PDF resmi tetap disusun Produksi."""
import re
from urllib.parse import urlsplit


def ringkas(s,base):
    path=urlsplit(base).path.removeprefix('/pelanggan')
    rekap=bool(re.fullmatch(r'/jasa/\d+/nota',path))
    bukti=bool(re.fullmatch(r'/barang-(?:masuk|keluar)/\d+/serah-terima',path))
    laporan=bool(re.fullmatch(r'/riwayat-(?:giling|pengeringan|sosoh)/\d+/laporan',path))
    if not (rekap or bukti or laporan):return s
    root=s.select_one('.rekap-jasa')
    if laporan and s.find('iframe'):
        root=s.new_tag('div',attrs={'class':'pelanggan-halaman'})
        for node in list(s.contents):root.append(node.extract())
        s.append(root)
        heading=root.find('h2')
        if heading:
            heading.name='h1'
            title,sep,kode=heading.get_text(' ',strip=True).partition(' · ')
            if sep:
                heading.string=title
                ref=s.new_tag('p',attrs={'class':'pelanggan-detail-kode'});ref.string=kode;heading.insert_after(ref)
        status=root.find(id='status-bagikan')
        if status:status.clear()
    if root is None:return s
    root['class']=[*root.get('class',[]),'pelanggan-detail','pelanggan-pembaca-dokumen']
    for a in list(root.select('a[href]')):
        if a.get_text(' ',strip=True)=='Baca PDF':a.decompose()
    backs=[a for a in root.select('a[href]') if a.get_text(' ',strip=True).startswith('← Kembali')]
    for i,a in enumerate(backs):
        if i:a.decompose();continue
        a['href']='/pelanggan/laporan';a.string='← Kembali ke Dokumen';root.insert(0,a.extract())
    if rekap or bukti:
        heading=root.find('h1')
        if heading:heading.string='Rekap barang' if rekap else 'Bukti barang masuk' if '/barang-masuk/' in path else 'Bukti pengambilan'
        for p in root.select('.rekap-eyebrow'):p.decompose()
        for p in root.select('.rekap-customer'):
            if rekap:p.decompose();continue
            for node in list(p.find_all(string=True,recursive=False)):node.extract()
        for origin in root.select('.rekap-origin'):
            wrapper=s.new_tag('details',attrs={'class':'pelanggan-detail-lipat'})
            summary=s.new_tag('summary');summary.string='Nomor terkait';wrapper.append(summary);origin.wrap(wrapper)
        for h in root.select('h2'):
            if h.get_text(' ',strip=True)=='Neraca bobot':
                section=h.find_parent('section')
                if section:
                    wrapper=s.new_tag('details',attrs={'class':'pelanggan-detail-lipat'})
                    summary=s.new_tag('summary');summary.string='Rincian berat';wrapper.append(summary);section.wrap(wrapper)
    labels={'Pesanan jasa':'Rekap barang','Nomor pesanan utama':'Nomor rekap',
        'Serah terima barang':'Dokumen barang','QC penerimaan':'Pemeriksaan mutu',
        'Tanggal QC selesai':'Pemeriksaan mutu selesai','Tanggal verifikasi':'Pemeriksaan selesai',
        'Neraca bobot':'Rincian berat','Referensi penerimaan':'Kode barang masuk',
        'Referensi pengambilan':'Kode pengambilan','Pengesahan serah terima':'Pengesahan',
        'Identitas serah terima':'Rincian dokumen','Barang yang diserahterimakan':'Rincian barang',
        'Menunggu QC penerimaan selesai':'Menunggu pemeriksaan mutu selesai',
        'Menunggu pengeluaran selesai diverifikasi':'Menunggu pemeriksaan pengambilan selesai'}
    for el in root.select('h2,h3,dt,th,summary,.rekap-eyebrow,.rekap-identitas>span,.rekap-customer .lencana'):
        for node in list(el.find_all(string=True)):
            value=str(node);key=value.strip()
            if key in labels:node.replace_with(value.replace(key,labels[key]))
            elif key.startswith('Lampiran QC penerimaan · '):node.replace_with(value.replace('Lampiran QC penerimaan','Pemeriksaan mutu'))
    for p in root.select('.rekap-help'):
        text=p.get_text(' ',strip=True)
        if text=='Bobot ditampilkan per tahap; saldo antar tahap tidak dijumlahkan sebagai stok siap diambil.':
            p.string='Berat ditampilkan per tahap. Jumlah pada tahap berbeda tidak menunjukkan jumlah yang siap diambil.'
        elif text=='Rincian pemeriksaan tersedia pada lampiran QC di bawah dan PDF.':
            p.string='Rincian pemeriksaan mutu tersedia di bawah dan pada PDF.'
    for p in root.select('.rekap-section>p'):
        text=p.get_text(' ',strip=True)
        if text=='Menunggu QC penerimaan selesai. Ketersediaan dokumen mengikuti pencatatan produksi yang sah.':
            p.string='Dokumen akan tersedia setelah pemeriksaan mutu selesai.'
        elif text=='Menunggu pengeluaran selesai diverifikasi. Ketersediaan dokumen mengikuti pencatatan produksi yang sah.':
            p.string='Dokumen akan tersedia setelah pengambilan selesai diperiksa.'
    for td in root.select('.rekap-table tbody td:first-child'):
        if td.get_text(strip=True)=='Beras PK':td.string='Beras pecah kulit (PK)'
    return s
