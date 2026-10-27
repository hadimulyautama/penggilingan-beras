"""Pembaca sumber yang benar-benar diterima; tidak memakai nota sebagai saldo.

Saldo fisik didelegasikan ke pembaca FIFO/partai lama. Silo, hasil proses,
dan barang titipan tidak diubah menjadi stok pembelian oleh layar baru.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from sqlalchemy import select, func, text
from app.models import (PurchaseBatch, PkPurchaseBatch, FinishedGoodsStock,
                        ByproductStock, Warehouse, PkGudang2Intake, ProductSku,
                        DryingLotBatch, SiloStorage, MillingProcessSource, KemasUlang)
from app.services import barang_masuk, barang_keluar as keluar
from app.services.retur_supplier_reservasi import terikat,karung_terikat
from app.penggilingan.inventory import finished_goods as barang_jadi

D = lambda v: Decimal(str(v))
MODEL = {'gabah': PurchaseBatch, 'pk': PkPurchaseBatch,
         'beras': FinishedGoodsStock, 'broken': ByproductStock}
FK = {'gabah': 'purchase_batch_id', 'pk': 'pk_purchase_batch_id',
      'beras': 'finished_goods_stock_id', 'broken': 'byproduct_stock_id'}


def batas_karung(item, saldo):
    """Bandingkan bobot simpan dua desimal, bukan hasil bagi yang berulang.

    Misalnya 998 kg / 30 karung tidak boleh menghilangkan karung terakhir
    karena representasi pecahan atau pembulatan pengajuan parsial.
    """
    row=item['_row']
    def berat(n):
        if item['_jenis']=='pk':
            from app.penggilingan.gudang2.karung import bobot_per_karung
            return bobot_per_karung(row,jumlah=n).quantize(D('.00000001'),rounding=ROUND_HALF_UP)
        from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
        return berat_karung_nyata(row,n)
    toleransi=D('.000001') if item['_jenis']=='pk' else D(0)  # pagar pecahan PK layanan lama
    max_n=row.jumlah_karung-int(getattr(row,'retur_supplier_keluar_karung',0) or 0)
    n=min(max_n,max(0,int(saldo/item['per_kg'])))
    while n and berat(n)>saldo+toleransi:n-=1
    # Batas karung fisik asal juga tetap berlaku, meski rasio sangat kecil.
    while n<max_n and berat(n+1)<=saldo+toleransi:n+=1
    return D(n)


async def penerimaan(db, tid, *, kunci=False):
    sql='''SELECT t.id,t.kode,t.arah,t.jenis_kode,
        t.supplier_id,t.status_transaksi,t.status_tiket,t.timbang1_waktu,
        s.nama_supplier FROM timbangan_transaksi t
        LEFT JOIN suppliers s ON s.id=t.supplier_id WHERE t.id=:id'''
    if kunci and db.get_bind().dialect.name=='postgresql':sql+=' FOR UPDATE OF t'
    tiket = (await db.execute(text(sql), {'id':tid})).mappings().first()
    if not tiket or tiket['arah'] != 'MASUK':
        raise ValueError('Penerimaan Barang Masuk tidak ditemukan.')
    riwayat = await barang_masuk.riwayat(db, g1=True, g2=True, tid=tid)
    catatan = riwayat[0]['catatan'] if riwayat else []
    if not catatan or not any(c['status'] != 'ditolak' for c in catatan):
        raise ValueError('Retur ke Supplier hanya dari penerimaan yang sudah diterima.')
    if not tiket['supplier_id'] or not tiket['nama_supplier']:
        raise ValueError('Penerimaan ini tidak memiliki supplier pembelian yang sah. Barang titipan tetap melalui alur jasa.')
    sumber = []
    for c in sorted(catatan, key=lambda c:(c['model'],c['id'])):
        model = MODEL[c['model']]
        q = select(model).where(model.id == c['id']).execution_options(populate_existing=True)
        row = await db.scalar(q.with_for_update() if kunci else q)
        if row is None:
            continue
        if getattr(row,'supplier_id',tiket['supplier_id']) != tiket['supplier_id'] and row.jasa_id is None:
            raise ValueError('Supplier pada catatan penerimaan berbeda dari tiket. Periksa hubungan sumber terlebih dahulu.')
        sumber.append((c,row))
    # Nota berasal dari baris muatan tersimpan, dan tetap boleh kosong.
    nota = (await db.scalars(text('SELECT nomor_acuan FROM timbangan_muatan WHERE transaksi_id=:id ORDER BY urutan,id'), {'id':tid})).all()
    return dict(tiket, nota=' · '.join(dict.fromkeys(n for n in nota if n))), sumber


async def _saldo_curah_sumber(db, row):
    """Alokasikan pemakaian total resmi ke sumber tertua, seperti FIFO karung."""
    q = select(ByproductStock).where(ByproductStock.jenis_produk == row.jenis_produk,
                                    ByproductStock.jasa_id.is_(None)).order_by(ByproductStock.waktu,ByproductStock.id)
    rows = (await db.scalars(q)).all()
    total = D(await barang_jadi.hitung_stok_byproduct_curah(db,row.jenis_produk))
    from app.penggilingan.gudang2.service import _sisa_broken_row
    # Pemindahan ke silo menyebut ID sumber. Kurangkan pada sumber itu
    # terlebih dahulu, baru alokasikan pengiriman agregat secara FIFO.
    fisik={x.id:max(D(0),D(await _sisa_broken_row(db,x.id))) if row.jenis_produk=='broken'
           else max(D(0),D(x.berat_kg)) for x in rows}
    dipakai = max(D(0), sum(fisik.values(),D(0)) - total)
    for x in rows:
        alokasi=await terikat(db,sumber=f'broken:{x.id}')
        ambil = min(max(D(0),fisik[x.id]-alokasi),dipakai)
        dipakai -= ambil
        if x.id == row.id:
            return max(D(0),fisik[x.id]-ambil)
    return D(0)


async def pilihan(db, tiket, sumber, *, kecuali=None):
    hasil = []
    for c,row in sumber:
        jenis = c['model']; whkode = 'g1' if jenis == 'gabah' else 'g2'
        wh = await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == whkode,Warehouse.aktif.is_(True)))
        key = f'{jenis}:{row.id}'
        item = dict(kunci=key,kode=c['kode'],nama={'gabah':'Gabah '+getattr(row,'kondisi_gabah',''),
            'pk':'PK '+str(getattr(row,'jenis_pk','') or ''),'beras':'Beras','broken':'Broken'}[jenis],
            pemilik=c['pemilik'],gudang=wh.nama_gudang if wh else 'Gudang belum tersedia',
            warehouse_id=wh.id if wh else None,lokasi='Menunggu penempatan' if jenis=='gabah' else 'Gudang 2',
            diterima_kg=c['berat'],diterima_jumlah=None,satuan='kg',per_kg=D(1),
            stok_kg=None,stok_jumlah=None,terikat_kg=await terikat(db,sumber=key,kecuali=kecuali),
            sudah_retur_kg=None,tersedia_kg=None,maksimum=D(0),alasan_tidak_bisa=None,
            _row=row,_jenis=jenis,_pool=key,_batas_pool=None,_tambahan_pool=None)
        alasan = None; fisik = None; b = None
        if row.jasa_id is not None:
            alasan = 'Barang titipan tidak dapat diretur sebagai pembelian supplier.'
        elif not wh or (getattr(row,'warehouse_id',None) and row.warehouse_id != wh.id):
            alasan = 'Gudang sumber belum sah atau tidak sesuai penerimaan.'
        elif c['status']=='ditolak':
            alasan = 'Catatan penolakan mengikuti alur sebelum penerimaan.'
        elif tiket['status_transaksi'] != 'AKTIF':
            alasan = 'Tiket penerimaan dibatalkan; hubungan sumber perlu diperiksa.'
        elif c['berat'] is None or c['sumber_berat'] in ('menunggu','perkiraan'):
            alasan = 'Bobot penerimaan belum final atau belum diketahui.'
        elif jenis == 'gabah':
            from app.penggilingan.gudang1.services.tumpukan import MENUNGGU_TEMPAT
            terproses = any([await db.scalar(select(m.id).where(col==row.id).limit(1)) for m,col in (
                (DryingLotBatch,DryingLotBatch.purchase_batch_id),
                (SiloStorage,SiloStorage.purchase_batch_id),
                (MillingProcessSource,MillingProcessSource.purchase_batch_id))])
            if row.status_batch not in MENUNGGU_TEMPAT or row.dryer_id or terproses:
                alasan = 'Gabah sudah ditempatkan pada proses; tidak tersedia sebagai barang asal.'
                fisik = D(0)
            else:
                fisik = D(row.berat_total_kg)-D(row.retur_supplier_keluar_kg)
                item['lokasi'] = 'Tumpukan gabah '+row.kondisi_gabah+' · Gudang 1'
        elif jenis == 'pk':
            intake = await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.pk_purchase_batch_id==row.id))
            if not intake or intake.tujuan != 'ditumpuk':
                alasan = 'PK belum berada di tumpukan yang dapat dikembalikan, atau sudah menjadi bahan silo.'
                fisik = D(0)
            else:
                from app.penggilingan.gudang2.service import _sisa_tumpukan_intake
                from app.penggilingan.gudang2.karung import bobot_per_karung
                nilai = await _sisa_tumpukan_intake(db,intake.id)
                fisik = D(nilai) if nilai is not None else None
                item['lokasi']='Tumpukan PK · Gudang 2'
                if row.jumlah_karung is not None:
                    item.update(satuan='karung',per_kg=bobot_per_karung(row),diterima_jumlah=row.jumlah_karung)
                b = keluar.BarisPerintah(tipe='pk_g2')
                item['_pool']='pk_g2';item['tipe_pool']='pk_g2'
        elif jenis == 'beras':
            sku = await db.get(ProductSku,row.product_sku_id)
            if not sku:
                alasan = 'Identitas produk asal tidak tersedia.'
            else:
                item['nama']=await keluar._nama_sku(db,row.product_sku_id,row.rice_quality_standard_id)
                item.update(product_sku_id=sku.id,rice_quality_standard_id=row.rice_quality_standard_id,jenis_produk=sku.kategori)
                if row.curah_kemas_ulang:
                    fisik=D(row.berat_total_kg)-D(row.retur_supplier_keluar_kg)
                    item['tipe_pool']='fg_curah'
                else:
                    saldo=await barang_jadi.sisa_karung_per_sumber(db,sku.id,row.rice_quality_standard_id,source_type=None)
                    saldo=next(((n,kg) for r,n,kg in saldo if r.id==row.id),(0,0))
                    fisik=D(saldo[1]);item.update(satuan='karung',per_kg=D(row.berat_total_kg)/row.jumlah_karung if row.jumlah_karung else None,
                                                diterima_jumlah=row.jumlah_karung,stok_jumlah=saldo[0])
                    n_sisa=row.jumlah_karung-int(row.retur_supplier_keluar_karung)
                    if n_sisa:item['per_kg']=(D(row.berat_total_kg)-D(row.retur_supplier_keluar_kg))/n_sisa
                    b=keluar.BarisPerintah(tipe='finished_goods',sku_id=sku.id,std_id=row.rice_quality_standard_id)
                item['_pool']=f'fg_curah:{row.id}' if row.curah_kemas_ulang else f'fg:{sku.id}:{row.rice_quality_standard_id or 0}'
                item.setdefault('tipe_pool','finished_goods')
                # Kemas ulang mencatat hasil baru dengan asal tiket yang sama;
                # hasil itu bukan partai asli meskipun source_id-nya sama.
                asal_kemas=FinishedGoodsStock.__table__.alias('asal_kemas')
                hasil_kemas=await db.scalar(select(KemasUlang.id).join(asal_kemas,asal_kemas.c.id==KemasUlang.sumber_id).where(
                    asal_kemas.c.source_type=='timbangan',asal_kemas.c.source_id==row.source_id,
                    KemasUlang.waktu==row.waktu,KemasUlang.sumber_id!=row.id).limit(1))
                if hasil_kemas:alasan='Barang hasil kemas ulang bukan partai penerimaan asal.'
                riwayat_kemas=(await db.scalars(select(KemasUlang).where(KemasUlang.sumber_id==row.id))).all()
                if riwayat_kemas:
                    item['diterima_kg']=D(row.berat_total_kg)+sum((D(x.berat_asal_kg) for x in riwayat_kemas),D(0))
                    item['diterima_jumlah']=row.jumlah_karung+sum(x.karung_dibuka for x in riwayat_kemas)
        else:
            fisik=await _saldo_curah_sumber(db,row)
            item.update(jenis_produk=row.jenis_produk,tipe_pool='byproduct_curah',_pool='curah:'+row.jenis_produk)
            b=keluar.BarisPerintah(tipe='byproduct_curah',jenis=row.jenis_produk)
        if item.get('per_kg') is None or item.get('per_kg',D(0)) <= 0:
            alasan='Dasar bobot per karung belum sah; lengkapi data partai asal.'
        item.setdefault('tipe_pool','gabah')
        item['stok_kg']=fisik
        if fisik is not None and item['per_kg']:
            item['stok_jumlah'] = batas_karung(item,fisik) if item['satuan']=='karung' else max(D(0),fisik)
            bebas=max(D(0),fisik-item['terikat_kg'])
            if b:
                # `tersedia` sudah mencakup alokasi RSP melalui _sudah_dipesan;
                # sumber tidak dikurangkan lagi pada batas gabungan ini.
                pool_bebas=D((await keluar.tersedia(db,b))[0])
                if kecuali:
                    from app.models.retur_supplier import ReturSupplierItem
                    milik_sendiri=await db.scalar(select(func.coalesce(func.sum(ReturSupplierItem.bobot_kg),0)).where(
                        ReturSupplierItem.retur_supplier_id==kecuali,ReturSupplierItem.tipe_pool==item['tipe_pool'],
                        ReturSupplierItem.product_sku_id==item.get('product_sku_id'),
                        ReturSupplierItem.rice_quality_standard_id==item.get('rice_quality_standard_id'),
                        ReturSupplierItem.jenis_produk==item.get('jenis_produk')))
                    pool_bebas += D(milik_sendiri)
                item['_batas_pool']=max(D(0),pool_bebas)
                bebas=min(bebas,item['_batas_pool'])
            item['maksimum'] = batas_karung(item,bebas) if item['satuan']=='karung' else max(D(0),bebas.quantize(D('.01'),rounding=ROUND_FLOOR))
            if item['satuan']=='karung':item['maksimum']=min(item['maksimum'],max(D(0),item['stok_jumlah']-await karung_terikat(db,key,kecuali=kecuali)))
            item['tersedia_kg']=bebas
            if fisik<=0 and not alasan:alasan='Stok sumber sudah habis atau sudah digunakan.'
        if b and item.get('jenis_produk') in {'broken','menir','reject','bekatul'}:
            jenis_produk=item['jenis_produk']
            gabungan=D(await barang_jadi.hitung_stok_byproduct_total(db,jenis_produk)) - D(await keluar._sudah_dipesan(db,jenis=jenis_produk))
            if kecuali:
                from app.models.retur_supplier import ReturSupplierItem
                gabungan+=D(await db.scalar(select(func.coalesce(func.sum(ReturSupplierItem.bobot_kg),0)).where(
                    ReturSupplierItem.retur_supplier_id==kecuali,ReturSupplierItem.jenis_produk==jenis_produk)))
            item['_tambahan_pool']=('hasil:'+jenis_produk,max(D(0),gabungan))
            if item['tersedia_kg'] is not None:item['tersedia_kg']=min(item['tersedia_kg'],max(D(0),gabungan))
            if item['per_kg']:
                batas=max(D(0),gabungan/item['per_kg'])
                item['maksimum']=min(item['maksimum'],batas_karung(item,max(D(0),gabungan)) if item['satuan']=='karung' else batas.quantize(D('.01'),rounding=ROUND_FLOOR))
        if alasan:item['alasan_tidak_bisa']=alasan;item['maksimum']=D(0)
        hasil.append(item)
    return hasil
