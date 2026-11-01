"""Rapikan pembaca penerimaan/pengambilan tanpa mengubah data Produksi."""
import re
from urllib.parse import parse_qsl, urlsplit


def ringkas_transaksi(s, base):
    path=urlsplit(base).path.removeprefix('/pelanggan')
    masuk=s.select_one('.penerimaan-detail') if re.fullmatch(r'/barang-masuk/\d+',path) else None
    keluar=s.select_one('.kirim-detail,.rk') if re.fullmatch(r'/barang-keluar/\d+',path) else None
    root=masuk or keluar
    if root is None:return s
    root['class']=[*root.get('class',[]),'pelanggan-detail','pelanggan-transaksi-detail']

    def lipat(section, label):
        if section is None or section.find_parent('details'):return
        wrapper=s.new_tag('details',attrs={'class':'pelanggan-detail-lipat'})
        summary=s.new_tag('summary');summary.string=label;wrapper.append(summary)
        section.wrap(wrapper)

    def sections(title):
        return [h.find_parent('section') for h in root.select('h2') if h.get_text(' ',strip=True)==title]

    def hapus_baris(labels):
        for dt in list(root.select('dt')):
            if dt.get_text(' ',strip=True) in labels and dt.parent.name=='div':dt.parent.decompose()

    # Dokumen berbeda tetap tersedia sekali; melihat/mengunduh laporan yang
    # sama bukan tiga keputusan terpisah di kepala halaman.
    dokumen=[]
    for a in list(root.select('a[href]')):
        u=urlsplit(a['href'])
        if u.path.endswith('/laporan.pdf') and masuk:
            if not dokumen:
                a['href']=u.path+'?unduh=0';a.attrs.pop('download',None)
                a.string='Laporan penerimaan (PDF)';dokumen.append(a.extract())
            else:a.decompose()
        elif u.path==('/pelanggan'+path+'/serah-terima'):
            a.string='Bukti penerimaan' if masuk else 'Bukti pengambilan'
            dokumen.append(a.extract())
    for a in list(root.select('a[href]')):
        u=urlsplit(a['href']);q=dict(parse_qsl(u.query))
        if u.path.removeprefix('/pelanggan')==path and a.get('role')!='tab' and (
            'tab_detail' in q or 'rincian_perintah' in q):a.decompose()
    for a in root.select('.penerimaan-kembali,.detail-kirim-kembali'):
        a['href']='/pelanggan'+('/barang-masuk' if masuk else '/barang-keluar')
        a.string='← Kembali ke '+('Barang masuk' if masuk else 'Pengambilan barang')

    if masuk:
        for el in root.select('#bagikan-pdf,#status-bagikan,.penerimaan-pemilik'):el.decompose()
        for script in list(s.select('script[src*="pdf-penerimaan.js"]')):script.decompose()
        header=root.select_one('.penerimaan-kepala')
        if header:
            for p in list(header.select(':scope>p')):
                text=p.get_text(' ',strip=True)
                if text.startswith(('Pihak pada tiket:','Pemilik catatan:')) or not text:p.decompose()
            for small in header.select('.penerimaan-bobot>small'):
                if small.get_text(strip=True).startswith('Sumber bobot:'):small.decompose()
            if header.h1 and header.h1.get_text(strip=True) in ('PK','Beras PK'):header.h1.string='Beras pecah kulit (PK)'
        hapus_baris({'Tiket','Status tiket','Catatan penerimaan','Sumber bobot','Cara penimbangan','Arah','Pihak pada tiket','Pemilik catatan','Status transaksi','Status kontrol','Batas bawah / atas'})
        for title in ('Jejak penerimaan',):
            for section in sections(title):section.decompose()
        for a in list(root.select('a[href]')):
            if urlsplit(a['href']).path=='/pelanggan/jasa-saya':a.decompose()
            elif a.get_text(' ',strip=True).startswith('Stok terkait · '):a.decompose()
            elif urlsplit(a['href']).path.startswith('/pelanggan/riwayat-qc/'):
                # Semua putaran pemeriksaan sudah ada pada tab Mutu.
                a.decompose()
        for el in root.select('.terima-catatan__waktu>small'):el.decompose()
        for p in root.select('p.terima-bantu,.penerimaan-bobot>small'):
            text=p.get_text(' ',strip=True)
            replacements={
                'Total berasal dari catatan penerimaan yang sah. Catatan ditolak tidak dihitung; ini bukan saldo stok sekarang.':'Jumlah ini adalah barang yang diterima. Sisa stok dapat dilihat di Barang Saya.',
                'Bobot penerimaan, bukan saldo stok saat ini.':'Berat saat barang diterima. Sisa stok dapat dilihat di Barang Saya.',
                'Pencatatan QC penerimaan jenis barang ini belum tersedia.':'Pemeriksaan mutu belum tersedia untuk jenis barang ini.'}
            if text in replacements:p.string=replacements[text]

    elif 'kirim-detail' in root.get('class',[]):
        for nav in root.select('.pengiriman-tab'):nav.decompose()
        heading=root.find('h1')
        if heading:
            kode=s.new_tag('p',attrs={'class':'pelanggan-detail-kode'});kode.string=heading.get_text(' ',strip=True)
            heading.string='Pengambilan barang';heading.insert_after(kode)
        for el in root.select('.kirim-detail__judul .kirim-detail__label,.kirim-detail__penanda>span:not(.kirim-detail__status),.kirim-detail__tabel th>small'):el.decompose()
        hapus_baris({'Pemilik','Pelanggan','Pelanggan / pemilik','Kepemilikan'})
        for title in ('Identitas pengiriman','Muatan & tiket'):
            for section in sections(title):section.decompose()
        for section in sections('Tindakan saat ini'):
            pemeriksaan=section.select_one('.keluar-periksa')
            if pemeriksaan:
                section.insert_before(pemeriksaan.extract());lipat(pemeriksaan,'Pemeriksaan berat')
                for el in pemeriksaan.select('strong'):
                    if el.get_text(strip=True)=='Periksa sebelum verifikasi':el.string='Pemeriksaan berat'
                for node in list(pemeriksaan.find_all(string=True)):
                    text=str(node)
                    for old,new in {
                        'Di luar batas. Periksa tiket dan muatan; alasan selisih wajib saat verifikasi.':'Petugas sedang memeriksa selisih berat.',
                        'Bandingkan tiket dan muatan aktual sebelum menutup.':'Selisih berat diperiksa oleh petugas.',
                        'Selesaikan timbang kedua sebelum verifikasi.':'Menunggu penimbangan berikutnya.',
                        'Tiket armada belum dipilih. Periksa armada sebelum menutup pengiriman.':'Data penimbangan belum tersedia.'}.items():text=text.replace(old,new)
                    node.replace_with(text)
            section.decompose()
        # Panel pengembalian sebelumnya muncul lagi pada tab riwayat.
        for section in list(root.select('#panel-ringkasan section')):
            if section.h2 and section.h2.get_text(strip=True)=='Retur terkait':section.decompose()
        for p in root.select('.kirim-detail__catatan'):
            text=p.get_text(' ',strip=True)
            if text.startswith('Selesaikan timbang kedua di Pos Timbang'):
                p.string='Menunggu penimbangan berikutnya oleh petugas.'
            elif text in ('Ditutup tanpa tiket timbang terkait.','Tiket armada belum dipilih.'):
                p.string='Data penimbangan tidak tersedia pada catatan ini.'

    else:
        for nav in root.select('.pengiriman-tab'):nav.decompose()
        back=root.find('a',recursive=False)
        if back:
            back['href']='/pelanggan/barang-keluar';back.string='← Kembali ke Pengambilan barang'
        heading=root.find('h1');customer=root.select_one('.rk-customer')
        code=customer.select_one('summary small') if customer else None
        code=code.get_text(' ',strip=True).split(' · ')[0] if code else ''
        if heading:
            old=heading.get_text(' ',strip=True);heading.string='Pengambilan barang'
            ref=s.new_tag('p',attrs={'class':'pelanggan-detail-kode'});ref.string=code or old;heading.insert_after(ref)
            if code and old!=code:
                plate=s.new_tag('p');plate.string='Kendaraan: '+old;ref.insert_after(plate)
        for p in root.select('.rk-hero>div:first-child>p'):
            text=p.get_text(' ',strip=True)
            if re.match(r'^\d+ pelanggan · ',text):p.string=re.sub(r'^\d+ pelanggan · ','',text)
        for el in root.select('.rk-hero>div:first-child>small'):el.decompose()
        for el in root.select('.rk-hero>div:last-child>span'):el.string='Jumlah barang keluar'
        # Satu pelanggan per halaman: tak perlu laci pemilihan pelanggan lagi.
        for detail in root.select('.rk-customer'):
            summary=detail.find('summary',recursive=False)
            if summary:
                h=s.new_tag('h2',attrs={'class':'pelanggan-rincian-judul'});h.string='Rincian barang';summary.replace_with(h)
            detail.name='section';detail.attrs.pop('open',None)
        for p in root.select('.rk-item>p'):
            text=p.get_text(' ',strip=True)
            if ' · ' in text:p.string=text.split(' · ',1)[1]
        for balance in root.select('.rk-balance'):
            nilai=[dd.get_text(' ',strip=True) for dd in balance.select('dd')[:2]]
            if len(nilai)==2 and all(re.fullmatch(r'0(?:[,.]0+)?\s+(?:kg|karung)',v) for v in nilai):
                balance.decompose();continue
            balance.attrs.pop('open',None)
            if balance.summary:balance.summary.string='Pengembalian barang ini'
            for small in balance.select(':scope>small'):small.decompose()
        hapus_baris({'Bisa diajukan lagi'})
        for section in list(root.select('aside>section')):
            if section.h2 and section.h2.get_text(' ',strip=True)=='Ringkasan pelanggan':section.decompose()
        for section in root.select('.rk-weigh'):
            if not section.select('dl'):section.decompose()
            else:lipat(section,'Penimbangan')
        for p in root.select('.rk-weigh>p'):
            text=p.get_text(' ',strip=True)
            replacements={
                'Snapshot berat barang setelah tara tidak tersedia; pembanding memakai netto sesuai kompatibilitas tiket lama.':'Berat barang setelah potongan belum tercatat. Pembanding memakai berat bersih pada tiket lama.',
                'Subtotal pelanggan mengikuti catatan muatan. Selisih timbang tetap pada armada.':'Jumlah barang mengikuti catatan pengambilan.',
                'Ditutup tanpa tiket timbang terkait pada catatan ini.':'Data penimbangan tidak tersedia pada catatan ini.',
                'Tiket terkait tidak ditemukan; angka historis tidak direka.':'Data penimbangan belum ditemukan pada catatan lama ini.'}
            if text in replacements:p.string=replacements[text]
            elif ' · ' in text:
                for node in list(p.find_all(string=True)):
                    value=str(node)
                    value=value.replace(' · AKTIF','')
                    for old,new in {'SELESAI':'Selesai','TERBUKA':'Belum selesai','AKTIF':'Aktif','DIBATALKAN':'Dibatalkan','DITUTUP_PAKSA':'Ditutup dengan catatan'}.items():value=value.replace(old,new)
                    node.replace_with(value)
        for p in root.select('.rk-weigh details>p'):
            if p.get_text(strip=True)=='Tara memakai snapshot tiket. Tidak dipotong lagi di PadiFlow.':p.string='Potongan berat mengikuti catatan penimbangan.'

    labels={
        'Bobot diterima':'Berat diterima','Bobot penerimaan':'Berat penerimaan','Bobot':'Berat',
        'Penerimaan':'Pengangkutan','Armada':'Kendaraan','Nomor polisi':'Nomor kendaraan','Sopir':'Pengemudi',
        'Tiket & bobot':'Penimbangan','QC':'Mutu','Hasil QC':'Hasil pemeriksaan mutu',
        'Catatan QC lama · rincian putaran belum tersedia':'Pemeriksaan lama · rincian tiap pemeriksaan belum tersedia',
        'Waktu / petugas':'Waktu penerimaan',
        'Catatan':'Kode barang','Perintah':'Rencana pengambilan','Rencana':'Rencana pengambilan',
        'Total perintah':'Rencana pengambilan','Rencana pengiriman':'Rencana pengambilan',
        'Dimuat aktual':'Sudah dimuat','Dikirim aktual':'Jumlah keluar',
        'Jumlah aktual':'Jumlah tercatat','Perintah dan muatan aktual per barang':'Rencana dan jumlah barang',
        'Retur & riwayat':'Riwayat','Retur terkait':'Barang yang dikembalikan',
        'Retur pelanggan ini':'Barang yang dikembalikan','Riwayat petugas':'Riwayat pengambilan',
        'Petugas perintah pelanggan':'Riwayat pengambilan','Diperintahkan':'Pengambilan dicatat',
        'Diperintah':'Pengambilan dicatat','Dimuat':'Barang dimuat',
        'Diverifikasi':'Pemeriksaan selesai','Diverifikasi otomatis':'Pemeriksaan selesai',
        'Diverifikasi manual':'Pemeriksaan selesai','Diverifikasi tidak tercatat':'Pemeriksaan selesai',
        'Total aktual PadiFlow':'Jumlah barang keluar','Selisih seluruh armada':'Selisih berat',
        'Netto kompatibilitas tiket lama':'Berat bersih (catatan lama)',
        'Netto timbangan':'Berat bersih sebelum potongan','Netto jembatan timbang':'Berat bersih sebelum potongan',
        'Netto timbang':'Berat bersih sebelum potongan','Berat nota / acuan':'Berat pada dokumen',
        'Berat tiket saat ini · dasar penerimaan':'Berat pada tiket','Total tara & pengurang':'Total potongan berat',
        'Tara kemasan':'Potongan berat kemasan','Total potongan tara':'Potongan berat kemasan',
        'Tara lain':'Potongan berat lain','Tara lain · termasuk total':'Potongan lain (termasuk total)',
        'Bruto · bermuatan':'Kendaraan bermuatan','Tara · truk kosong':'Kendaraan kosong',
        'Berat barang setelah tara':'Berat barang setelah potongan','Catatan perintah:':'Catatan pengambilan:',
        'Retur sudah diterima':'Sudah diterima kembali','Pengajuan masih tertunda':'Menunggu penerimaan kembali',
        'Menunggu verifikasi':'Menunggu pemeriksaan','Menunggu penyerahan · <200 kg':'Menunggu penyerahan'}
    for el in root.select('h2,h3,summary,dt,th,caption,nav a,.kirim-detail__status,.kirim-detail__label-ponsel,.penerimaan-bobot>span,.rk-timeline strong,.kirim-detail__jejak strong,.kirim-detail__catatan>strong,.rk-content>p>strong,.terima-qc__kepala>span'):
        for node in list(el.find_all(string=True)):
            value=str(node);key=value.strip()
            if key in labels:node.replace_with(value.replace(key,labels[key]))
            elif key.startswith('Riwayat QC · '):node.replace_with(value.replace('Riwayat QC','Pemeriksaan sebelumnya'))
            elif el.find_parent(class_='rk-timeline') and ' · ' in key:
                label,sep,nama=key.partition(' · ')
                if label in labels:node.replace_with(labels[label]+sep+nama)
    for section in list(root.select('.rk-returns,#panel-riwayat .kirim-detail__bagian')):
        if section.h2 and section.h2.get_text(strip=True)=='Barang yang dikembalikan':
            if not section.select('a[href]'):section.decompose()
            else:lipat(section,'Barang yang dikembalikan')
    for el in root.select('.rk-item>h2,.kirim-detail__tabel tbody th'):
        for node in list(el.find_all(string=True,recursive=False)):
            text=str(node)
            if re.match(r'^\s*PK(?:\s|$)',text):node.replace_with(re.sub(r'^(\s*)PK',r'\1Beras pecah kulit (PK)',text,count=1))
    # Buang pembungkus kosong setelah tombol/panel berulang dipindahkan.
    for el in list(root.select('p,.rk-actions,.detail-kirim-grid,.rk-stack')):
        if not el.get_text(strip=True) and not el.select('a,button,img'):el.decompose()
    if dokumen:
        section=s.new_tag('section',attrs={'class':'pelanggan-dokumen-detail'})
        seen=set()
        for a in dokumen:
            if a['href'] not in seen:section.append(a);seen.add(a['href'])
        root.append(section);lipat(section,'Dokumen')
    return s
