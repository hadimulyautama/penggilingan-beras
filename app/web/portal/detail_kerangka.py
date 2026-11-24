"""Finite native customer detail presentation, never an ownership capability."""
import re
from urllib.parse import parse_qsl, urlsplit

TABS={
 'giling': [('ringkasan','Ringkasan'),('bahan','Bahan'),('hasil','Hasil & mutu'),('riwayat','Riwayat')],
 'penerimaan': [('ringkasan','Ringkasan'),('tiket','Penimbangan'),('qc','Pemeriksaan mutu'),('riwayat','Lokasi & riwayat')],
}
# Only invariant native customer fields. Variant-dependent sources/timbang/QC
# groups are not invented while their real reader has not returned.
SECTIONS={
 'giling': {
  'ringkasan':[('Jumlah bahan',['Jumlah bahan']),('Hasil giling sementara',['Total hasil giling']),('Waktu proses',['Mulai proses','Lama proses aktif','Total jeda'])],
  'bahan':[('Bahan yang dipakai',[])],
  'hasil':[('Total hasil giling',['Total hasil giling']),('Hasil pemeriksaan',[])],
  'riwayat':[('Identitas & waktu proses',['Kode proses']),('Riwayat jeda proses',[])],
 },
 'penerimaan': {
  'ringkasan':[('Pengangkutan',['Total diterima']),('Lokasi & proses',[]),('Mutu penerimaan',[])],
  'tiket':[('Identitas tiket',['Kode tiket','Jenis','Cara timbang','Nomor kendaraan','Pengemudi']),('Data timbang',[]),('Berat penerimaan',['Total diterima'])],
  'qc':[('Hasil pemeriksaan',[])],
  'riwayat':[('Catatan penerimaan',[]),('Lokasi & proses terkait',[])],
 },
}


def deskripsi(value):
    if not isinstance(value,str) or len(value)>4096 or not value.startswith('/pelanggan/') or value.startswith('//'):return None
    u=urlsplit(value)
    if u.scheme or u.netloc or u.path+('?' +u.query if u.query else '')+('#'+u.fragment if u.fragment else '')!=value:return None
    if re.search(r'%(?![0-9A-Fa-f]{2})',u.query):return None
    try:pairs=parse_qsl(u.query,keep_blank_values=True,errors='strict',max_num_fields=9)
    except (ValueError,UnicodeError):return None
    q=dict(pairs)
    if len(q)!=len(pairs):return None
    if m:=re.fullmatch(r'/pelanggan/proses-aktif/giling/([A-Za-z0-9_-]{1,100})',u.path):
        kind='giling';resource=m[1];keys={'tab_detail','halaman_hasil','halaman_qc','halaman_jeda','pelanggan_id','pemilik','kepemilikan'}
    elif m:=re.fullmatch(r'/pelanggan/barang-masuk/([1-9][0-9]{0,9})',u.path):
        kind='penerimaan';resource=m[1];keys={'tab_detail','pelanggan_id','pemilik','kepemilikan'}
    else:return None
    if set(q)-keys:return None
    tab=q.get('tab_detail','ringkasan')
    if tab not in dict(TABS[kind]):return None
    if 'pemilik' in q and q['pemilik']!='jasa' or 'kepemilikan' in q and q['kepemilikan']!='jasa':return None
    for k,v in q.items():
        if k.startswith('halaman_') or k=='pelanggan_id':
            if not re.fullmatch(r'[1-9][0-9]{0,9}',v) or int(v)>2147483647:return None
    if u.fragment and (kind!='giling' or u.fragment!='panel-'+tab):return None
    return dict(kind=kind,resource=resource,path=u.path,address=u.path+('?' +u.query if u.query else ''),hash=('#'+u.fragment if u.fragment else ''),tab=tab)
