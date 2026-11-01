"""Pencarian dan halaman atas catatan yang sudah dibatasi pemiliknya."""
from urllib.parse import urlencode


def daftar(rows, request, *, base, pilihan, judul, pengantar, label_jenis, satuan):
    q=request.query_params.get('q','').strip()[:120]
    jenis=request.query_params.get('jenis','')
    if jenis not in dict(pilihan):jenis=''
    hasil=[r for r in rows if (not jenis or r['jenis']==jenis) and (not q or
        q.casefold() in ' '.join(str(r.get(k) or '') for k in ('judul','kode','cari')).casefold())]
    hasil.sort(key=lambda r:((r.get('tanggal').timestamp() if r.get('tanggal') else 0),r['kode']),reverse=True)
    total=len(hasil);akhir=max(1,(total+24)//25)
    try:halaman=max(1,int(request.query_params.get('halaman','1')))
    except (ValueError,TypeError):halaman=1
    halaman=min(halaman,akhir)
    def href(page):
        params={k:v for k,v in dict(jenis=jenis,q=q,halaman=page).items() if v}
        return base+'?'+urlencode(params)
    mulai=(halaman-1)*25
    return dict(rows=hasil[mulai:mulai+25],total=total,halaman=halaman,akhir=akhir,
        dari=mulai+1 if total else 0,sampai=min(mulai+25,total),sebelumnya=href(halaman-1),
        berikutnya=href(halaman+1),q=q,jenis=jenis,pilihan=pilihan,base=base,
        judul=judul,pengantar=pengantar,label_jenis=label_jenis,satuan=satuan,
        tersaring=bool(q or jenis))
