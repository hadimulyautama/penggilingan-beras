"""Hierarki halaman desktop, bukan riwayat klik peramban atau judul yang disambung.

Tujuan Kembali berasal dari induk terakhir yang benar-benar ditampilkan.
Konteks pencarian boleh mengganti query induk itu, tidak mengganti keluarganya.
Tidak membaca transaksi, menulis data, maupun mengubah gerbang akses endpoint.
"""
import re
from urllib.parse import urlsplit,parse_qs,urlencode


def aman(value):
    if not isinstance(value,str) or not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c)<32 for c in value):return None
    try:u=urlsplit(value)
    except ValueError:return None
    return value if not u.scheme and not u.netloc else None


def _ambil(o,key,default=None):
    return o.get(key,default) if isinstance(o,dict) else getattr(o,key,default)


def kode(ctx,fallback):
    detail=ctx.get('breadcrumb_detail')
    if detail and str(detail) not in ('Detail PK','Riwayat alih kepemilikan','Alihkan kepemilikan PK'):return str(detail)
    for name in ('k','data','awal','perjalanan'):
        obj=ctx.get(name)
        if isinstance(obj,list):obj=obj[0] if obj else None
        for value in (_ambil(obj,'kode'),_ambil(obj,'code'),_ambil(_ambil(obj,'rec'),'kode')):
            if value:return str(value)
    return fallback


def susun(path,ctx,judul):
    u=urlsplit(path);p=u.path.rstrip('/') or '/';q=parse_qs(u.query)
    home=('Beranda','/');parents=[home];leaf=judul
    def add(name,url):parents.append((name,url))
    def stok():
        add('Stok','/stok')
    def riwayat():add('Riwayat','/riwayat')
    if p=='/':parents=[];leaf='Beranda'
    elif p=='/stok':
        tab=q.get('tab',['bahan'])[0]
        if tab in ('produk','karung'):add('Stok','/stok');leaf={'produk':'Produk','karung':'Karung'}[tab]
        else:leaf='Stok'
    elif p.startswith('/stok'):
        stok()
        tab='produk' if p.startswith(('/stok-produk','/stok/produk')) else 'karung' if p.startswith(('/stok-karung','/stok/karung')) else 'bahan'
        detail=p.endswith('/detail') or p.startswith('/stok/sumber/') or ctx.get('detail')
        if detail:
            if tab!='bahan':add({'produk':'Produk','karung':'Karung'}[tab],'/stok?'+urlencode({'tab':tab}))
            leaf=kode(ctx,judul)
        elif tab!='bahan':leaf={'produk':'Produk','karung':'Karung'}[tab]
        else:leaf=judul
    elif p.startswith('/kepemilikan') or p.startswith('/pk-kepemilikan'):
        stok()
        if p=='/kepemilikan':leaf='Riwayat alih kepemilikan'
        else:
            add('Riwayat alih kepemilikan','/kepemilikan'+('?' +urlencode({'kind':q['kind'][0]}) if q.get('kind') else ''))
            leaf=kode(ctx,judul)
    elif p.startswith('/riwayat-retur-supplier'):
        add('Barang Masuk','/barang-masuk')
        if p=='/riwayat-retur-supplier':leaf='Retur ke Supplier'
        else:add('Retur ke Supplier','/riwayat-retur-supplier');leaf=kode(ctx,judul)
    elif p.startswith('/retur-supplier/'):
        add('Barang Masuk','/barang-masuk');add('Retur ke Supplier','/riwayat-retur-supplier')
        parts=p.split('/')
        if len(parts)>3:add(kode(ctx,'Detail retur supplier'),'/retur-supplier/'+parts[2]);leaf=judul
        else:leaf=kode(ctx,judul)
    elif p.startswith('/barang-masuk'):

        if p=='/barang-masuk':leaf='Barang Masuk'
        else:add('Barang Masuk','/barang-masuk');leaf=kode(ctx,judul)
    elif p.startswith('/barang-keluar') or p in ('/muatan','/selesai-muat','/verifikasi-pengiriman'):
        parent_url=ctx.get('PENGIRIMAN_URL','/barang-keluar')
        if p==parent_url:leaf='Barang Keluar' if parent_url=='/barang-keluar' else 'Muatan'
        else:
            add('Barang Keluar' if parent_url=='/barang-keluar' else 'Muatan',parent_url)
            m=re.match(r'^/barang-keluar/(\d+)(?:/(.+))?$',p)
            if m:
                if m[2]:add(kode(ctx,'Detail pengiriman'),'/barang-keluar/'+m[1]);leaf=judul
                else:leaf=kode(ctx,judul)
            elif p in ('/muatan','/selesai-muat','/verifikasi-pengiriman'):
                rid=q.get('perintah',[''])[0]
                if rid.isdigit() and parent_url=='/barang-keluar':add('Detail pengiriman','/barang-keluar/'+rid)
    elif p.startswith('/retur'):
        add('Barang Keluar','/barang-keluar')
        if p=='/retur':leaf='Barang Retur'
        else:add('Barang Retur','/retur');leaf=kode(ctx,judul)
    elif p.startswith('/jasa'):
        if p=='/jasa':leaf='Pesanan Jasa'
        else:add('Pesanan Jasa','/jasa');leaf=judul
    elif p.startswith('/proses-aktif/'):
        add('Pekerjaan','/pekerjaan?tab=berjalan');leaf=kode(ctx,judul)
    elif p.startswith(('/koreksi-bahan/','/koreksi-bahan-berjalan/')):
        target=aman(ctx.get('kembali'))
        if target and urlsplit(target).path.startswith('/proses-aktif/'):
            add('Pekerjaan','/pekerjaan?tab=berjalan');add(kode(ctx,'Detail proses'),target)
        else:stok()
        leaf='Koreksi bahan proses'
    elif p=='/pekerjaan':leaf='Pekerjaan'
    elif p.startswith('/permintaan-pk/'):
        add('Pekerjaan','/pekerjaan');add('Transfer PK','/transfer-bertahap');leaf=kode(ctx,judul)
    elif p.startswith('/pekerjaan/') or p=='/transfer-bertahap':
        add('Pekerjaan','/pekerjaan');leaf=kode(ctx,judul)
    elif p.startswith('/riwayat-qc/'):
        riwayat();parts=p.split('/');add('Riwayat QC','/riwayat?tab=qc')
        jenis={'gabah-basah':'Gabah basah','gabah-kering':'Gabah kering','pk-hasil-giling':'PK hasil giling','pk-luar':'PK luar','beras-hasil-sosoh':'Beras hasil sosoh'}.get(parts[2],parts[2])
        if len(parts)>3:add(jenis,'/riwayat-qc/'+parts[2]);leaf=kode(ctx,judul)
        else:leaf=jenis
    elif any(p==x or p.startswith(x+'/') for x in ('/riwayat-giling','/riwayat-sosoh','/riwayat-pengeringan','/riwayat-transfer')):
        riwayat();base='/'+p.split('/')[1];label={'/riwayat-giling':'Riwayat Penggilingan','/riwayat-sosoh':'Riwayat Penyosohan','/riwayat-pengeringan':'Riwayat Pengeringan','/riwayat-transfer':'Riwayat Transfer PK'}[base]
        if p==base:leaf=label
        else:
            add(label,base)
            tail=p[len(base)+1:].split('/')
            if len(tail)>1:add(kode(ctx,'Detail proses'),base+'/'+tail[0]);leaf=judul
            else:leaf=kode(ctx,judul)
    elif p in ('/riwayat','/laporan-riwayat'):leaf='Riwayat'
    elif p=='/audit':riwayat();leaf='Audit'
    elif p=='/laporan':leaf='Laporan'
    elif p=='/pengaturan':leaf='Pengaturan'
    elif p.startswith(('/pengaturan/','/pengguna','/silo','/qc-pengaturan','/kontak','/kemasan')):
        add('Pengaturan','/pengaturan');leaf=judul
    else:
        # Metadata eksplisit halaman lama tetap dihormati; tidak menebak
        # induk hanya dari judul atau membangun tautan dari segmen URL mentah.
        induk=ctx.get('breadcrumb_induk')
        if induk and aman(_ambil(induk,'alamat')):add(_ambil(induk,'nama'),_ambil(induk,'alamat'))
        else:
            target=aman(ctx.get('kembali'))
            if target and urlsplit(target).path not in ('/',p):
                # Halaman lama sudah memiliki induk eksplisit. Susun juga
                # leluhurnya, alih-alih langsung melompat dari Beranda.
                parent=susun(target,{},'Detail')
                parents=[(x['nama'],x['alamat'] or target) for x in parent['items']]
            else:
                sections={'stok':('Stok','/stok'),'pekerjaan':('Pekerjaan','/pekerjaan'),'barang_masuk':('Barang Masuk','/barang-masuk'),'barang_keluar':('Barang Keluar',ctx.get('PENGIRIMAN_URL','/barang-keluar')),'jasa':('Pesanan Jasa','/jasa'),'pengaturan':('Pengaturan','/pengaturan')}
                section=sections.get(ctx.get('MENU_AKTIF') or ctx.get('layar'))
                if section and urlsplit(section[1]).path!=p:add(*section)
        leaf=kode(ctx,judul)
    # Koreksi pada cabang lain juga harus naik dulu ke detailnya. Kembali
    # yang berbeda keluarga tidak dipakai mengganti rantai halaman.
    nested=re.match(r'^(/barang-masuk/\d+|/retur/(?:pengajuan/)?\d+|/jasa/\d+)(/.+)$',p)
    if nested and all(urlsplit(x[1]).path!=nested[1] for x in parents):add(kode(ctx,'Detail'),nested[1]);leaf=judul
    candidates=[ctx.get('kembali'),q.get('kembali',[''])[0],q.get('kembali_stok',[''])[0],q.get('kembali_kerja',[''])[0]]
    if isinstance(ctx.get('filter_query'),str):
        candidates.append((parents[-1][1] if parents else '/')+('&' if parents and '?' in parents[-1][1] else '?')+ctx['filter_query'])
    # Filter dipertahankan pada induk yang sama. Query yang menunjuk dirinya
    # sendiri atau halaman lain tidak boleh menciptakan lompatan/siklus.
    candidates=sorted((x for x in candidates if aman(x)),key=lambda x:bool(urlsplit(x).query),reverse=True)
    for i in ([len(parents)-1] if parents else []):
        name,url=parents[i]
        for target in candidates:
            target=aman(target)
            if target and urlsplit(target).path==urlsplit(url).path and urlsplit(target).path!=p and (urlsplit(target).query or not urlsplit(url).query):
                parents[i]=(name,target);break
    nodes=[]
    for name,url in parents:
        name=' '.join(str(name or '').split())
        if not name or url.rstrip('/')==path.rstrip('/'):continue
        if nodes and (name.casefold()==nodes[-1]['nama'].casefold() or url==nodes[-1]['alamat']):continue
        nodes.append(dict(nama=name,alamat=url))
    leaf=' '.join(str(leaf or judul or 'Halaman').split())
    if nodes and nodes[-1]['nama'].casefold()==leaf.casefold():leaf='Detail'
    back=nodes[-1]['alamat'] if nodes else None
    nodes.append(dict(nama=leaf,alamat=None))
    return dict(items=nodes,kembali=back)


from jinja2 import pass_context

@pass_context
def tampil(context,judul):
    request=context.get('request')
    path=(request.url.path+('?' +request.url.query if request.url.query else '')) if request else '/'
    if context.get('kode') in (403,404,500):judul=context.get('judul') or judul
    return susun(path,context,judul)
