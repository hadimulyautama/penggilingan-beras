"""Susun daftar penerimaan pelanggan untuk komponen daftar Produksi."""
from urllib.parse import urlencode
from sqlalchemy import select


async def daftar(db,scope,penerimaan,request):
    from app.models import PurchaseBatch,PkPurchaseBatch
    from app.services.barang_masuk import riwayat,bobot_diterima
    from app.services.kelompok_kerja import JENIS_BARANG
    native={r['id']:r for r in await riwayat(db,g1=True,g2=True,jasa_ids=scope.jasa_ids)
        if r['id'] in scope.resources.get('timbangan_transaksi',())}
    batches={b.kode_batch:b for model in (PurchaseBatch,PkPurchaseBatch)
        for b in (await db.scalars(select(model).where(model.id.in_(scope.ids(model)),
            model.timbangan_transaksi_id.is_(None)))).all()}
    rows=[]
    for t in penerimaan:
        if t['id'] is not None:
            if t['id'] not in native:continue
            row=dict(native[t['id']])
            href=f"/barang-masuk/{t['id']}"
        else:
            b=batches.get(t['kode'])
            if b is None:continue
            pk=isinstance(b,PkPurchaseBatch)
            jenis='pk' if pk else 'gabah_'+b.kondisi_gabah
            row=dict(id=None,kode=t['kode'],nama=scope.reader.nama,jenis=jenis,
                jenis_nama='Beras pecah kulit (PK)' if pk else t['jenis'],jenis_kode=jenis,
                nomor_polisi=b.no_polisi_truk,status_tiket='')
            href=f"/riwayat-qc/{'pk-luar' if pk else 'gabah-'+b.kondisi_gabah}/{b.kode_batch}"
        berat,ket=bobot_diterima(t['catatan'])
        row.update(catatan=t['catatan'],berat_diterima=berat,keterangan_berat=ket,
            kepemilikan='jasa',href=href)
        rows.append(row)
    rows.sort(key=lambda r:max((c['waktu'].timestamp() for c in r['catatan'] if c.get('waktu')),default=0),reverse=True)
    q=request.query_params
    jenis=q.get('jenis','') if q.get('jenis','') in dict(JENIS_BARANG) else ''
    cari=q.get('cari','').strip()[:200]
    rows=[r for r in rows if (not jenis or r['jenis']==jenis) and (not cari or cari.casefold() in
        ' '.join((r['kode'],r.get('nama') or '',r.get('nomor_polisi') or '')).casefold())]
    jumlah=len(rows);akhir=max(1,(jumlah+24)//25)
    try:halaman=min(akhir,max(1,int(q.get('halaman','1'))))
    except ValueError:halaman=1
    def href(**params):
        return '/barang-masuk?'+urlencode({k:v for k,v in dict(jenis=jenis,cari=cari,**params).items() if v})
    return dict(riwayat=rows[(halaman-1)*25:halaman*25],jumlah=jumlah,halaman=halaman,
        halaman_akhir=akhir,jenis=jenis,cari=cari,jenis_barang=JENIS_BARANG,href=href)
