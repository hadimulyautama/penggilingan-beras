"""Pintu lanjutan pelanggan: mutu dan pengembalian tetap pembaca native."""
import re
from urllib.parse import parse_qsl,urlsplit


def ringkas(s,base):
    path=urlsplit(base).path.removeprefix('/pelanggan')
    qc=s.select_one('.qc-detail') if path.startswith('/riwayat-qc/') else None
    retur=s.select_one('.riwayat-detail[data-detail-tab]') if re.fullmatch(r'/retur/\d+',path) else None
    root=qc or retur
    if root is None:return s
    root['class']=[*root.get('class',[]),'pelanggan-detail']
    h=root.find('h1')
    if h:
        code=s.new_tag('p',attrs={'class':'pelanggan-detail-kode'});code.string=h.get_text(' ',strip=True)
        h.string='Pemeriksaan mutu' if qc else 'Barang dikembalikan';h.insert_after(code)
    if qc:
        for el in root.select('.qc-topline>span:first-child'):
            el.string=el.get_text(' ',strip=True).partition(' · ')[2] or 'Rincian pemeriksaan'
        for el in root.select('.qc-topline .lencana'):
            el.string={'QC gabah basah':'Gabah basah','QC gabah kering':'Gabah kering',
                'QC PK hasil giling':'Beras pecah kulit (PK)','QC PK luar':'Beras pecah kulit (PK)'}.get(el.get_text(strip=True),el.get_text(strip=True))
        for p in list(root.select('.qc-hero>p')):
            text=p.get_text(' ',strip=True)
            if text.startswith(('Pemilik jasa:','Pemilik bahan:')):p.decompose()
            elif re.match(r'^\d+ putaran tercatat · ',text):p.string=text.replace('putaran tercatat','pemeriksaan',1)
        for nav in root.select('.qc-tabs'):nav['aria-label']='Bagian pemeriksaan mutu'
        for el in root.select('.qc-summary-actions'):el.decompose()
        # Tab sudah menjadi satu pintu tiap bagian. Tautan ke pemeriksaan
        # tertentu (misalnya sumber catatan) dan paginasi tetap dipertahankan.
        for a in list(root.select('a[href]')):
            u=urlsplit(a['href']);q=dict(parse_qsl(u.query))
            if (not a.find_parent(class_='qc-tabs') and u.path.removeprefix('/pelanggan')==path
                and q.get('tab_qc') and not q.get('putaran') and a.get_text(strip=True).startswith(('Buka','Lihat'))):a.decompose()
        for h2 in list(root.select('h2')):
            if h2.get_text(strip=True)=='Penelusuran':h2.find_parent('section').decompose()
        for dt in list(root.select('dt')):
            if dt.get_text(strip=True) in ('Kepemilikan','Asal / pemilik'):dt.parent.decompose()
        for p in list(root.select('p')):
            text=p.get_text(' ',strip=True)
            if text.startswith('Halaman ini membaca riwayat. Pencatatan dan penutupan'):p.decompose()
            elif text.startswith('Sebagian hasil berasal dari catatan QC lama.'):
                p.string='Sebagian pemeriksaan berasal dari catatan lama. Waktu atau petugas yang tidak tercatat tetap ditandai.'
            elif text.startswith('Ringkasan memakai nilai yang diperbarui layanan pencatatan QC gabah.'):
                p.string='Ringkasan memakai seluruh hasil pemeriksaan. Biji hijau dan densiti tetap ditampilkan per pemeriksaan.'
            elif re.fullmatch(r'Seluruh \d+ putaran tersedia\. Pemilihan putaran hanya mengubah tampilan\.',text):p.decompose()
        for el in root.select('.qc-score small'):
            for node in list(el.find_all(string=True)):
                node.replace_with(str(node).replace('putaran QC','pemeriksaan'))
    else:
        for nav in root.select('.pengiriman-tab'):nav.decompose()
        for a in root.select('.detail-kirim-kembali'):
            a['href']='/pelanggan/barang-keluar';a.string='← Kembali ke Pengambilan barang'
        for h2 in list(root.select('h2')):
            if h2.get_text(strip=True)=='Tindakan saat ini':h2.find_parent('section').decompose()
        for dt in list(root.select('dt')):
            if dt.get_text(strip=True) in ('Pelanggan','Diterima oleh'):dt.parent.decompose()
        for div in list(root.select('.detail-kirim-stat>div')):
            label=div.find('span')
            if label and label.get_text(strip=True)=='Status stok':div.decompose()
        for p in list(root.select('header>p')):
            if p.select('a[href*="/barang-keluar/"]'):p.decompose()
        for a in list(root.select('a[href]')):
            u=urlsplit(a['href']);q=dict(parse_qsl(u.query))
            if (u.path.removeprefix('/pelanggan')==path and q.get('tab_detail')
                and a.get('role')!='tab' and a.get_text(strip=True).startswith(('Lihat','Buka'))):a.decompose()
        for p in root.select('p'):
            text=p.get_text(' ',strip=True)
            if text=='Tara hanya toleransi pencocokan; berat rincian masuk stok tidak dipotong tara.':p.string='Berat diterima mengikuti rincian barang.'
            elif text=='Hubungan pengiriman asal belum tercatat pada data lama ini.':p.string='Pengambilan asal belum tercatat pada catatan lama ini.'
        for small in list(root.select('td small')):
            if small.get_text(strip=True).startswith('Item pengiriman asal #'):small.decompose()
        for table in root.select('table'):
            heads=table.select('thead th')
            for i in reversed([i for i,h in enumerate(heads) if h.get_text(strip=True)=='Catatan stok']):
                for row in table.select('tr'):
                    cells=row.find_all(['th','td'],recursive=False)
                    if len(cells)>i:cells[i].decompose()
        labels={'Pengiriman asal':'Pengambilan asal','Buka pengiriman asal':'Lihat pengambilan asal',
            'Berat rincian masuk stok':'Berat diterima kembali','Bobot tiket saat diterima':'Berat pada tiket',
            'Tiket & bobot':'Penimbangan','Pencocokan bobot':'Perbandingan berat',
            'Nomor polisi':'Nomor kendaraan','Netto timbang':'Berat bersih sebelum potongan'}
        for el in root.select('h2,dt,.detail-kirim-stat span,nav a,a.btn'):
            for node in list(el.find_all(string=True)):
                value=str(node)
                if value.strip() in labels:node.replace_with(value.replace(value.strip(),labels[value.strip()]))
    for container in list(root.select('.qc-actions')):
        if not container.get_text(strip=True):container.decompose()
    return s
