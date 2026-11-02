"""Susun daftar penerimaan pelanggan untuk komponen daftar Produksi."""
from app.performa import dalam
from urllib.parse import urlencode
from sqlalchemy import select


async def daftar(db,scope,penerimaan,request):
    from app.models import PurchaseBatch,PkPurchaseBatch
    from app.services.barang_masuk import riwayat,bobot_diterima
    from app.services.kelompok_kerja import JENIS_BARANG
    from app.services.penerimaan_halaman import pilih
    q=request.query_params
    jenis=q.get('jenis','') if q.get('jenis','') in dict(JENIS_BARANG) else ''
    cari=q.get('cari','').strip()[:200]
    selected,pag,_=await pilih(db,scope.reader.pelanggan_id,portal=True,scope=scope,nama=scope.reader.nama,
        pilihan=dict(jenis=jenis,cari=cari,halaman=q.get('halaman','1')))
    tids=[r['id'] for r in selected if r['sumber']=='tiket']
    native={r['id']:r for r in await riwayat(db,g1=True,g2=True,jasa_ids=scope.jasa_ids,ids_tiket=tids)} if tids else {}
    legacy={}
    for kind,model in (('gabah',PurchaseBatch),('pk',PkPurchaseBatch)):
        ids=[r['id'] for r in selected if r['sumber']==kind]
        if ids:
            legacy.update({b.kode_batch:b for b in (await db.scalars(select(model).where(model.id.in_(ids)))).all()})
    penerimaan=[]
    for r in selected:
        if r['sumber']=='tiket':
            t=native.get(r['id'])
            if t:penerimaan.append(dict(id=t['id'],kode=t['kode'],jenis=t['jenis_nama'] or t['jenis_kode'],catatan=t['catatan']))
        else:
            b=legacy[r['kode']]
            penerimaan.append(dict(id=None,kode=b.kode_batch,jenis='PK' if r['sumber']=='pk' else 'Gabah '+b.kondisi_gabah,
                catatan=[dict(berat=b.berat_total_kg,sumber_berat=b.sumber_berat,waktu=b.waktu_pembelian,status=b.status_batch)]))
    from .beranda import penerimaan_diterima
    penerimaan=penerimaan_diterima(penerimaan)
    batches=legacy
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
            jenis_baris='pk' if pk else 'gabah_'+b.kondisi_gabah
            row=dict(id=None,kode=t['kode'],nama=scope.reader.nama,jenis=jenis_baris,
                jenis_nama='Beras pecah kulit (PK)' if pk else t['jenis'],jenis_kode=jenis_baris,
                nomor_polisi=b.no_polisi_truk,status_tiket='')
            href=f"/riwayat-qc/{'pk-luar' if pk else 'gabah-'+b.kondisi_gabah}/{b.kode_batch}"
        berat,ket=bobot_diterima(t['catatan'])
        row.update(catatan=t['catatan'],berat_diterima=berat,keterangan_berat=ket,
            kepemilikan='jasa',href=href)
        rows.append(row)
    jumlah,akhir,halaman=pag['jumlah'],pag['akhir'],pag['halaman']
    def href(**params):
        return '/barang-masuk?'+urlencode({k:v for k,v in dict(jenis=jenis,cari=cari,**params).items() if v})
    return dict(riwayat=rows,jumlah=jumlah,halaman=halaman,
        halaman_akhir=akhir,jenis=jenis,cari=cari,jenis_barang=JENIS_BARANG,href=href)
