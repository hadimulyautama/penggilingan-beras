"""Isi operasional laporan: setiap tahap mempunyai bahan, hasil, atau mutasinya.

Hanya membaca. Perhitungan mesin memakai pembaca yang sama dengan riwayat
serta stok; berat tiket tidak dijadikan bahan atau hasil mesin.
"""
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import select
from app import models as m
from app.web.pdf_proses import angka


def kg(n):
    return angka(n)+' kg' if n is not None else 'Belum tercatat'


def persen(n):
    return f'{float(n):.2f}%'.replace('.',',') if n is not None else 'Belum dapat dihitung'


def jumlah(values):
    values=list(values)
    return sum((Decimal(str(v)) for v in values),Decimal(0)) if values and all(v is not None for v in values) else None


def satuan_di_keterangan(data):
    """Bobot tetap kilogram; satuannya cukup dijelaskan sekali pada laporan."""
    import re
    def bersihkan(value):
        if isinstance(value,str):return re.sub(r'(?<=\d)\s*kg\b','',value)
        if isinstance(value,list):return [bersihkan(v) for v in value]
        if isinstance(value,dict):return {k:bersihkan(v) for k,v in value.items()}
        return value
    for key in ('rincian','ringkasan','ringkasan_kelompok'):
        data[key]=bersihkan(data[key])
    data['catatan'].insert(0,'Seluruh bobot dinyatakan dalam kilogram. Persentase menggunakan total bahan terpakai sebagai dasar.' if data['kode']=='penyosohan' else 'Seluruh bobot dinyatakan dalam kilogram.')
    return data


def kelompokkan_ringkasan(data,kode,baris):
    """Kelompok operasional yang sama untuk layar dan PDF.

    Beras dan hasil samping merupakan rincian dari total hasil, sehingga
    jangan menjumlahkannya sekali lagi sebagai keluaran tambahan.
    """
    groups={}
    def taruh(grup,item,bagian=None):
        value=dict(item)
        if kode in ('pengeringan','penggilingan','penyosohan') and value['nama']=='Jumlah transaksi':value['nama']='Jumlah proses'
        if value['nama']=='Bahan terpakai':value['nama']='Total bahan terpakai'
        if bagian:value['bagian']=bagian
        groups.setdefault(grup,[]).append(value)
    for item in data['ringkasan']:
        nama=item['nama'];bagian=None
        if nama in ('Jumlah transaksi','Milik pabrik','Milik jasa'):
            grup='Aktivitas'
        elif kode=='penyosohan':
            from app.services.stok import nama_produk
            from app.services.jenis_hasil_samping import adalah_samping
            hasil={nama_produk(j):j for r in baris for j in r.get('_output',{})}
            if nama=='Bahan terpakai':grup='Bahan'
            elif nama in ('Susut debu & bobot','Rendemen beras'):grup='Evaluasi proses'
            else:
                grup='Hasil'
                if nama in hasil:bagian='Hasil samping' if adalah_samping(hasil[nama]) else 'Beras'
        elif kode in ('gabah_masuk','pk_masuk'):
            grup='Pemeriksaan bobot' if nama in ('Bobot menurut nota','Bobot menurut timbangan') else 'Penerimaan'
        elif kode in ('penggilingan','pengeringan','kemas_ulang'):
            grup=('Bahan' if nama in ('Bahan terpakai','Gabah basah masuk','Bobot dibuka') else
                  'Estimasi' if nama=='Estimasi gabah kering' else
                  'Evaluasi proses' if nama in ('Rendemen PK','Sisa curah') else 'Hasil')
        else:
            grup={'pengemasan':'Hasil kemasan','barang_keluar':'Muatan',
                  'transfer_pk':'Pemindahan','pemasukan_pk':'Penerimaan',
                  'pindah_pk':'Pemindahan','retur_pk':'Barang kembali',
                  'retur_pelanggan':'Barang kembali'}[kode]
        taruh(grup,item,bagian)
    if kode=='penyosohan':
        from app.services.stok import nama_produk
        from app.services.jenis_hasil_samping import adalah_samping
        jenis=list(dict.fromkeys(j for r in baris for j in r.get('_bahan_per_jenis',{})))
        for j in jenis:
            values=[r['_bahan_per_jenis'][j] for r in baris if j in r.get('_bahan_per_jenis',{})]
            value=jumlah(values)
            taruh('Bahan',dict(nama=nama_produk(j),nilai=kg(value) if value is not None else 'Belum lengkap'))
        # Total di tiap subkelompok memudahkan melihat pembentuk total hasil.
        # Semua jenis tambahan tetap menggunakan klasifikasi master yang sama.
        hasil=groups.get('Hasil',[])
        ordered=[x for x in hasil if not x.get('bagian')]
        for samping,bagian in [(False,'Beras'),(True,'Hasil samping')]:
            items=[x for x in hasil if x.get('bagian')==bagian]
            if not items:continue
            total=sum((Decimal(str(v)) for r in baris for j,v in r.get('_output',{}).items() if adalah_samping(j)==samping),Decimal(0))
            ordered.append(dict(nama='Total '+bagian.lower(),nilai=kg(total),bagian=bagian))
            ordered.extend(items)
        if hasil:groups['Hasil']=ordered
        bahan=jumlah(r.get('_bahan') for r in baris)
        final=bool(bahan) and all(r.get('_rendemen_final') for r in baris)
        numerators={}
        for r in baris:
            for j,v in r.get('_output',{}).items():
                nama=nama_produk(j);numerators[nama]=numerators.get(nama,Decimal(0))+Decimal(str(v))
        numerators.update({'Total hasil tercatat':jumlah(r.get('_hasil') for r in baris),
                           'Total beras':jumlah(r.get('_beras') for r in baris),
                           'Total hasil samping':sum((Decimal(str(v)) for r in baris for j,v in r.get('_output',{}).items() if adalah_samping(j)),Decimal(0))})
        for item in groups.get('Hasil',[]):
            nilai=numerators.get(item['nama'])
            item['persen_bahan']=persen(nilai/bahan*100 if final and nilai is not None else None)
        susut=jumlah(r.get('_susut') for r in baris)
        for item in groups.get('Evaluasi proses',[]):
            if item['nama']=='Susut debu & bobot':
                item['persen_bahan']=persen(susut/bahan*100 if final and susut is not None else None)
    order=('Aktivitas','Penerimaan','Pemeriksaan bobot','Bahan','Hasil','Hasil kemasan','Estimasi','Pemindahan','Muatan','Barang kembali','Evaluasi proses')
    data['ringkasan_kelompok']=[dict(nama=g,rincian=groups[g]) for g in order if g in groups]
    return satuan_di_keterangan(data)


async def nama_sku(db, skus, standar):
    from app.services.stok import nama_produk, jenis_produk
    rows=(await db.execute(select(m.ProductSku,m.PackagingMaterial.nama,m.PackageSize.ukuran_kg,m.Brand.nama)
        .join(m.PackagingMaterial,m.PackagingMaterial.id==m.ProductSku.packaging_material_id)
        .join(m.PackageSize,m.PackageSize.id==m.ProductSku.package_size_id)
        .outerjoin(m.Brand,m.Brand.id==m.ProductSku.brand_id)
        .where(m.ProductSku.id.in_(skus or {0})))).all()
    specs=dict((await db.execute(select(m.RiceQualityStandard.id,m.RiceQualityStandard.kode)
        .where(m.RiceQualityStandard.id.in_(standar or {0})))).all())
    def sebut(sku, std=None):
        row=next((r for r in rows if r[0].id==sku),None)
        if row is None:return f'SKU #{sku}' if sku else 'Produk belum tercatat'
        s,bahan,ukuran,merek=row
        return ' · '.join(x for x in [nama_produk(jenis_produk(s.kategori,specs.get(std))),merek,f'{bahan} {angka(ukuran)} kg'] if x)
    return sebut


async def lengkapi(db,kode,baris):
    if not baris:return
    from app.services.laporan_periode import TAHAP
    from app.services.spesifikasi_beras import daftar as daftar_spek
    from app.services.jenis_hasil_samping import daftar as daftar_samping
    await daftar_spek(db,termasuk_nonaktif=True)
    await daftar_samping(db,termasuk_nonaktif=True)
    model=TAHAP[kode][1]
    objek={x.id:x for x in (await db.scalars(select(model).where(model.id.in_([r['id'] for r in baris])))).all()}
    from app.services.jasa import nama_pemilik_banyak
    owners=await nama_pemilik_banyak(db,{o.jasa_id for o in objek.values() if getattr(o,'jasa_id',None)})
    for r in baris:
        o=objek[r['id']]
        r['pemilik_teks']=owners.get(getattr(o,'jasa_id',None)) or ('Pabrik' if getattr(o,'jasa_id',None) is None else 'Pemilik belum tercatat')
    if kode=='penggilingan':
        await _giling(db,baris,objek)
    elif kode=='penyosohan':
        await _sosoh(db,baris,objek)
    elif kode=='pengeringan':
        from app.services.estimasi_pengeringan import untuk_lot_banyak
        data=await untuk_lot_banyak(db,objek.values())
        from app.penggilingan.gudang1.services.bobot import dari_batches
        batches=defaultdict(list)
        for lid,b in (await db.execute(select(m.DryingLotBatch.drying_lot_id,m.PurchaseBatch).join(m.PurchaseBatch,m.PurchaseBatch.id==m.DryingLotBatch.purchase_batch_id).where(m.DryingLotBatch.drying_lot_id.in_(objek)))).all():batches[lid].append(b)
        dryers=dict((await db.execute(select(m.Dryer.id,m.Dryer.nama))).all())
        for r in baris:
            d=data[r['id']];o=objek[r['id']]
            basah=dari_batches(batches[o.id])
            masuk=(basah.kg+sum(float(b.retur_supplier_keluar_kg or 0) for b in batches[o.id])) if basah.pasti and basah.kg is not None else None
            def ukur(teks):
                if not teks:return None
                return Decimal(teks.removesuffix(' kg').replace('.','').replace(',','.'))
            r.update(bahan=d['basah'],_basah=masuk,_kering=ukur(d.get('terukur')),_estimasi=ukur(d.get('kering')),hasil=d.get('terukur') or 'Belum ditimbang',estimasi=d.get('kering') or 'Belum dapat dihitung',
                     kadar_awal=d.get('awal') or 'Belum tercatat',kadar_akhir=d.get('akhir') or 'Belum tercatat',
                     alat=dryers.get(o.dryer_id,'Belum tercatat'))
    elif kode in ('gabah_masuk','pk_masuk'):
        from app.services.jasa import nama_pemilik_banyak
        pemilik=await nama_pemilik_banyak(db,{o.jasa_id for o in objek.values() if o.jasa_id})
        suppliers=dict((await db.execute(select(m.Supplier.id,m.Supplier.nama_supplier).where(
            m.Supplier.id.in_({o.supplier_id for o in objek.values() if o.supplier_id} or {0})))).all())
        for r in baris:
            o=objek[r['id']]
            r.update(mitra=pemilik.get(o.jasa_id) if o.jasa_id else suppliers.get(o.supplier_id),
                     jenis=o.kondisi_gabah if kode=='gabah_masuk' else o.jenis_pk,
                     kadar_air=persen(o.kadar_air_awal_persen),karung=getattr(o,'jumlah_karung',None))
    elif kode in ('transfer_pk','pemasukan_pk','pindah_pk','retur_pk'):
        await _perpindahan(db,kode,baris,objek)
    elif kode in ('pengemasan','kemas_ulang'):
        skus={o.product_sku_id for o in objek.values()} if kode=='pengemasan' else {i for o in objek.values() for i in (o.sku_asal_id,o.sku_baru_id)}
        stok_asal={x.id:x for x in (await db.scalars(select(m.FinishedGoodsStock).where(m.FinishedGoodsStock.id.in_({o.sumber_id for o in objek.values()} if kode=='kemas_ulang' else {0})))).all()}
        standar={o.rice_quality_standard_id for o in objek.values() if o.rice_quality_standard_id} if kode=='pengemasan' else {x.rice_quality_standard_id for x in stok_asal.values() if x.rice_quality_standard_id}
        sebut=await nama_sku(db,skus,standar)
        asal_sosoh=dict((await db.execute(select(m.PolishingProcess.id,m.PolishingProcess.kode_proses).where(m.PolishingProcess.id.in_({o.source_id for o in objek.values() if o.source_id} if kode=='pengemasan' else {0})))).all())
        for r in baris:
            o=objek[r['id']]
            if kode=='pengemasan':
                r.update(produk=sebut(o.product_sku_id,o.rice_quality_standard_id),karung=o.jumlah_karung,
                         sumber=asal_sosoh.get(o.source_id,'Proses asal belum tercatat'),_hasil=o.berat_total_kg,hasil=kg(o.berat_total_kg))
            else:
                sumber=stok_asal.get(o.sumber_id)
                standar=sumber.rice_quality_standard_id if sumber else None
                r.update(produk_asal=sebut(o.sku_asal_id,standar),produk=sebut(o.sku_baru_id,standar),karung_asal=o.karung_dibuka,karung=o.karung_baru,
                         bahan=kg(o.berat_asal_kg),hasil=kg(o.berat_baru_kg),sisa=kg(o.sisa_kg),
                         _bahan=o.berat_asal_kg,_hasil=o.berat_baru_kg,_sisa=o.sisa_kg)
    elif kode=='barang_keluar':
        await _keluar(db,baris,objek)
    elif kode=='retur_pelanggan':
        items=(await db.scalars(select(m.CustomerReturnItem).where(m.CustomerReturnItem.customer_return_id.in_(objek)))).all()
        sebut=await nama_sku(db,{i.product_sku_id for i in items if i.product_sku_id},{i.rice_quality_standard_id for i in items if i.rice_quality_standard_id})
        from app.services.stok import nama_produk
        asal_items={i.id:i for i in (await db.scalars(select(m.OutgoingItem).where(m.OutgoingItem.id.in_({x.outgoing_item_id for x in items if x.outgoing_item_id} or {0})))).all()}
        def nama_retur(i):
            if i.product_sku_id:return sebut(i.product_sku_id,i.rice_quality_standard_id)
            asal=asal_items.get(i.outgoing_item_id)
            return nama_produk(asal.jenis_byproduct or {'pk_langsung':'pk','pk_g2':'pk','gabah_langsung':'gabah_kering'}.get(asal.item_type,asal.item_type)) if asal else 'Produk belum tercatat'
        for r in baris:
            o=objek[r['id']];anak=[i for i in items if i.customer_return_id==o.id]
            r.update(mitra=o.nama_pelanggan or 'Belum tercatat',hasil='\n'.join(f'{nama_retur(i)}: {i.jumlah_karung} karung · {kg(i.berat_total_kg)}' for i in anak) or 'Belum tercatat',
                     diterima=kg(o.berat_rincian_kg),tiket_retur=kg(o.berat_tiket_kg),selisih_retur=kg(o.selisih_kg),alasan=o.catatan or o.alasan_selisih or '-',karung=sum(i.jumlah_karung for i in anak))


async def _giling(db,baris,objek):
    from app.penggilingan.gudang1.services.milling import pk_breakdown_banyak,pk_jenis_banyak,hitung_rendemen,progress_banyak
    from app.services.bahan_silo import sumber_giling_banyak
    bd=await pk_breakdown_banyak(db,objek)
    jenis=await pk_jenis_banyak(db,objek.values())
    sumber=await sumber_giling_banyak(db,objek)
    progres=await progress_banyak(db,objek)
    verified=set((await db.scalars(select(m.MillingProcessVerification.milling_process_id).where(m.MillingProcessVerification.milling_process_id.in_(objek),m.MillingProcessVerification.berat_output_final_kg.is_not(None)))).all())
    for r in baris:
        o=objek[r['id']]
        hasil=bd[o.id].produced if o.id in verified or progres.get(o.id) is not None else None
        bahan=o.berat_gabah_masuk_kg
        pasti=o.bobot_masuk_final and bahan is not None
        final=o.status=='selesai'
        r.update(bahan=kg(bahan)+(' · sementara' if bahan is not None and not pasti else ''),
                 asal='\n'.join(g['nama']+' · '+', '.join(x['nama'] for x in g['sumber']) for g in sumber.get(o.id,[])) or 'Sumber lama',
                 hasil=kg(hasil),jenis_pk=jenis.get(o.id) or 'Belum tercatat',
                 rendemen=persen(hitung_rendemen(hasil,bahan) if pasti and final else None),
                 selisih_bahan=kg(Decimal(str(bahan))-Decimal(str(hasil))) if pasti and final and hasil is not None else 'Belum dapat dihitung',
                 _bahan=bahan if pasti else None,_hasil=hasil,_rendemen_final=final and pasti and hasil is not None)


async def _sosoh(db,baris,objek):
    from app.services.stok import output_sosoh_banyak,nama_produk
    from app.services.jenis_hasil_samping import daftar,adalah_samping
    from app.penggilingan.gudang2.polishing import neraca_sosoh,rendemen
    from app.penggilingan.gudang2.karung import bobot_pemakaian
    await daftar(db,termasuk_nonaktif=True)
    outputs=await output_sosoh_banyak(db,objek)
    from app.services.spesifikasi_beras import jenis_hasil
    urutan_hasil=await jenis_hasil(db,termasuk_nonaktif=True)
    usages=(await db.scalars(select(m.PolishingSiloUsage).where(m.PolishingSiloUsage.polishing_process_id.in_(objek)).order_by(m.PolishingSiloUsage.id))).all()
    silos={s.id:s for s in (await db.scalars(select(m.Silo).where(m.Silo.id.in_({u.silo_id for u in usages} or {0})))).all()}
    for r in baris:
        o=objek[r['id']];used=[u for u in usages if u.polishing_process_id==o.id];out=outputs.get(o.id,{})
        final=o.status=='selesai' and bool(used) and all(u.berat_akhir_kg is not None for u in used)
        bobot=bobot_pemakaian(used) if used else None
        pasti=final and bobot is not None and bobot.pasti and bobot.kg is not None
        n=neraca_sosoh(bobot.kg if pasti else 0,out)
        def rincian(samping):
            return '\n'.join(f'{nama_produk(j)}: {kg(v)}' for j,v in out.items() if adalah_samping(j)==samping) or 'Belum tercatat'
        per_jenis=defaultdict(list)
        for u in used:
            jenis=(silos[u.silo_id].jenis_isi or 'pk') if u.silo_id in silos else 'jenis_bahan_belum_tercatat'
            b=bobot_pemakaian([u])
            per_jenis[jenis].append(b.kg if u.berat_akhir_kg is not None and b.pasti else None)
        bahan_jenis='\n'.join(('Jenis bahan belum tercatat' if j=='jenis_bahan_belum_tercatat' else nama_produk(j))+': '+(kg(jumlah(v)) if jumlah(v) is not None else 'Belum final') for j,v in per_jenis.items()) or 'Belum tercatat'
        r.update(bahan=bobot.teks() if pasti else 'Belum final',
                 bahan_jenis=bahan_jenis,_bahan_per_jenis={j:jumlah(v) for j,v in per_jenis.items()},
                 hasil_beras=rincian(False),hasil_samping=rincian(True),hasil=kg(n.keluar_kg) if out else 'Belum tercatat',
                 rendemen=persen(rendemen(n.beras.kg,bobot.kg) if pasti and out else None),
                 susut=kg(n.susut.kg) if pasti and out else 'Belum dapat dihitung',
                 _bahan=bobot.kg if pasti else None,_hasil=n.keluar_kg if out else None,
                 _beras=n.beras.kg if out else None,_susut=n.susut.kg if pasti and out else None,
                 _output=out,_urutan_hasil=urutan_hasil,_rendemen_final=pasti and bool(out))


async def _perpindahan(db,kode,baris,objek):
    ids={getattr(o,'silo_id',None) for o in objek.values()}-{None}
    silos=dict((await db.execute(select(m.Silo.id,m.Silo.nama_silo).where(m.Silo.id.in_(ids or {0})))).all())
    intakes={x.id:x for x in (await db.scalars(select(m.PkGudang2Intake).where(m.PkGudang2Intake.id.in_({o.pk_gudang2_intake_id for o in objek.values()} if kode=='pindah_pk' else {0})))).all()}
    asal=list(objek.values()) if kode in ('pemasukan_pk','retur_pk') else list(intakes.values())
    pk={x.id:x for x in (await db.scalars(select(m.PkPurchaseBatch).where(m.PkPurchaseBatch.id.in_({o.pk_purchase_batch_id for o in asal if o.pk_purchase_batch_id} or {0})))).all()}
    giling=dict((await db.execute(select(m.MillingProcess.id,m.MillingProcess.kode_proses).where(m.MillingProcess.id.in_({o.milling_process_id for o in objek.values()} if kode=='transfer_pk' else {0})))).all())
    transfers=dict((await db.execute(select(m.InternalTransfer.id,m.InternalTransfer.kode_transfer).where(m.InternalTransfer.id.in_({o.internal_transfer_id for o in asal if getattr(o,'internal_transfer_id',None)} or {0})))).all())
    suppliers=dict((await db.execute(select(m.Supplier.id,m.Supplier.nama_supplier).where(m.Supplier.id.in_({p.supplier_id for p in pk.values() if p.supplier_id} or {0})))).all()) if kode=='retur_pk' else {}
    from app.services.jasa import nama_pemilik_banyak
    owners=await nama_pemilik_banyak(db,{p.jasa_id for p in pk.values() if p.jasa_id}) if kode=='retur_pk' else {}
    for r in baris:
        o=objek[r['id']]
        if kode=='retur_pk':
            batch=pk.get(o.pk_purchase_batch_id)
            r.update(asal=batch.kode_batch if batch else 'Belum tercatat',mitra=suppliers.get(batch.supplier_id,'Belum tercatat') if batch else 'Belum tercatat',alasan=o.alasan)
            if batch and batch.jasa_id:
                r['pemilik_teks']=owners.get(batch.jasa_id,'Pemilik belum tercatat')
            continue
        r['tujuan']=silos.get(o.silo_id) or getattr(o,'lokasi_tujuan',None) or getattr(o,'tujuan',None) or 'Tumpukan'
        r['karung']=getattr(o,'jumlah_karung',None)
        if kode=='transfer_pk':r['asal']=giling.get(o.milling_process_id,'Belum tercatat')
        else:
            intake=o if kode=='pemasukan_pk' else intakes.get(o.pk_gudang2_intake_id)
            batch=pk.get(intake.pk_purchase_batch_id) if intake else None
            r['asal']=(batch.kode_batch if batch else transfers.get(intake.internal_transfer_id,'Belum tercatat')) if intake else 'Belum tercatat'
        if kode=='pindah_pk':
            r['bobot']=o.berat_kg
            r['selama_proses']='Saat proses berjalan' if o.selama_proses else 'Sebelum proses'


async def _keluar(db,baris,objek):
    from app.services.stok import nama_produk
    items=(await db.scalars(select(m.OutgoingItem).where(m.OutgoingItem.outgoing_record_id.in_(objek)))).all()
    sebut=await nama_sku(db,{i.product_sku_id for i in items if i.product_sku_id},{i.rice_quality_standard_id for i in items if i.rice_quality_standard_id})
    from app.services.jasa import nama_pemilik_banyak
    owners=await nama_pemilik_banyak(db,{i.jasa_id for i in items if i.jasa_id})
    for r in baris:
        o=objek[r['id']];anak=[i for i in items if i.outgoing_record_id==o.id]
        pemilik=list(dict.fromkeys(owners.get(i.jasa_id,'Pemilik belum tercatat') if i.jasa_id else 'Pabrik' for i in anak))
        if pemilik:r['pemilik_teks']='\n'.join(pemilik)
        def nama(i):
            return sebut(i.product_sku_id,i.rice_quality_standard_id) if i.product_sku_id else nama_produk(i.jenis_byproduct or {'pk_langsung':'pk','pk_g2':'pk','gabah_langsung':'gabah_kering'}.get(i.item_type,i.item_type))
        r.update(mitra=o.nama_pembeli or 'Belum tercatat',armada=o.no_polisi or '-',
                 produk='\n'.join(nama(i) for i in anak) or 'Belum tercatat',
                 perintah=kg(jumlah(i.berat_perintah_kg for i in anak)),dimuat=kg(jumlah(i.berat_kg for i in anak)),
                 _perintah=jumlah(i.berat_perintah_kg for i in anak),_dimuat=jumlah(i.berat_kg for i in anak),
                 rincian_muatan='\n'.join(f'{nama(i)}: '+(f'{i.jumlah_karung} karung · ' if i.jumlah_karung is not None else '')+kg(i.berat_kg) for i in anak))


ISI = {
 'gabah_masuk':[('mitra','Pemasok / pemilik'),('jenis','Kondisi gabah'),('kadar_air','Kadar air awal'),('nota','Bobot nota'),('timbangan','Bobot timbangan'),('selisih','Selisih nota - timbang'),('bobot','Gabah diterima')],
 'pk_masuk':[('mitra','Pemasok / pemilik'),('jenis','Jenis PK'),('karung','Karung'),('nota','Bobot nota'),('timbangan','Bobot timbangan'),('selisih','Selisih nota - timbang'),('bobot','PK diterima')],
 'pengeringan':[('alat','Pengering'),('bahan','Gabah basah masuk'),('kadar_awal','KA awal'),('kadar_akhir','KA akhir'),('estimasi','Estimasi gabah kering'),('hasil','Gabah kering terukur')],
 'penggilingan':[('asal','Sumber gabah'),('bahan','Gabah terpakai'),('jenis_pk','Jenis PK'),('hasil','Hasil PK'),('rendemen','Rendemen PK'),('selisih_bahan','Selisih bahan - PK')],
 'penyosohan':[('bahan_jenis','Bahan per jenis'),('bahan','Bahan terpakai'),('hasil_beras','Beras per spek / grade'),('hasil_samping','Hasil samping per jenis'),('hasil','Total hasil'),('susut','Susut debu & bobot'),('rendemen','Rendemen beras')],
 'transfer_pk':[('asal','Lot giling asal'),('tujuan','Tujuan'),('karung','Karung'),('bobot','PK dipindahkan')],
 'pemasukan_pk':[('asal','Sumber PK'),('tujuan','Penempatan'),('bobot','PK masuk Gudang 2')],
 'pindah_pk':[('asal','Asal tumpukan'),('tujuan','Silo tujuan'),('karung','Karung'),('bobot','PK dipindahkan'),('selama_proses','Waktu pemasukan')],
 'pengemasan':[('sumber','Proses asal'),('produk','Produk / mutu / kemasan'),('karung','Karung tercatat'),('hasil','Bobot batch kemasan')],
 'kemas_ulang':[('produk_asal','Kemasan asal'),('karung_asal','Karung dibuka'),('bahan','Bobot dibuka'),('produk','Kemasan baru'),('karung','Karung baru'),('hasil','Bobot kemasan baru'),('sisa','Sisa curah')],
 'barang_keluar':[('mitra','Penerima'),('armada','Armada'),('rincian_muatan','Produk / muatan aktual'),('perintah','Bobot perintah'),('dimuat','Bobot dimuat'),('nota','Bobot nota'),('timbangan','Bobot timbangan')],
 'retur_pelanggan':[('mitra','Pelanggan'),('hasil','Produk dikembalikan'),('karung','Karung'),('diterima','Rincian diterima'),('tiket_retur','Bobot tiket retur'),('selisih_retur','Selisih rincian - tiket'),('alasan','Catatan')],
 'retur_pk':[('mitra','Pemasok'),('asal','Batch PK dikembalikan'),('bobot','PK dikembalikan'),('alasan','Alasan retur')],
}


KELOMPOK = {
 'gabah_masuk': {'jenis':'Bahan','kadar_air':'Bahan',**{k:'Bobot penerimaan' for k in ('nota','timbangan','selisih','bobot')}},
 'pk_masuk': {'jenis':'Bahan',**{k:'Penerimaan' for k in ('karung','nota','timbangan','selisih','bobot')}},
 'pengeringan': {'bahan':'Bahan','kadar_awal':'Bahan',**{k:'Hasil' for k in ('kadar_akhir','estimasi','hasil')}},
 'penggilingan': {'asal':'Bahan','bahan':'Bahan','jenis_pk':'Hasil','hasil':'Hasil'},
 'transfer_pk': {'asal':'Pemindahan','tujuan':'Pemindahan','karung':'Jumlah dipindahkan','bobot':'Jumlah dipindahkan'},
 'pemasukan_pk': {'asal':'Penerimaan','tujuan':'Penerimaan','bobot':'Penerimaan'},
 'pindah_pk': {'asal':'Pemindahan','tujuan':'Pemindahan','karung':'Jumlah dipindahkan','bobot':'Jumlah dipindahkan'},
 'pengemasan': {'produk':'Hasil kemasan','karung':'Hasil kemasan','hasil':'Hasil kemasan'},
 'kemas_ulang': {**{k:'Bahan' for k in ('produk_asal','karung_asal','bahan')},**{k:'Hasil' for k in ('produk','karung','hasil')},'sisa':'Sisa'},
 'barang_keluar': {'rincian_muatan':'Barang','perintah':'Muatan','dimuat':'Muatan','nota':'Tiket armada','timbangan':'Tiket armada'},
 'retur_pelanggan': {**{k:'Barang kembali' for k in ('hasil','karung','diterima')},'tiket_retur':'Pemeriksaan bobot','selisih_retur':'Pemeriksaan bobot'},
 'retur_pk': {'asal':'Barang kembali','bobot':'Barang kembali'},
}


def atur(data,kode,baris):
    """Kontrak kolom yang sama dipakai layar, kartu ponsel, dan PDF."""
    cols=[('kode','Kode')]+ISI[kode]
    if kode not in ('gabah_masuk','pk_masuk','retur_pelanggan'):
        cols.append(('pemilik','Pemilik'))
    bahan_cols=[];hasil_cols=[]
    if kode=='penyosohan':
        from app.services.stok import nama_produk
        jenis_bahan=list(dict.fromkeys(j for r in baris for j in r.get('_bahan_per_jenis',{})))
        jenis_hasil=list(dict.fromkeys(j for r in baris for j in r.get('_output',{})))
        urutan=list(dict.fromkeys(j for r in baris for j in r.get('_urutan_hasil',[])))
        jenis_hasil.sort(key=lambda j:(urutan.index(j) if j in urutan else len(urutan),nama_produk(j)))
        bahan_cols=[(f'bahan_{i}',nama_produk(j),j) for i,j in enumerate(jenis_bahan)]
        hasil_cols=[(f'hasil_{i}',nama_produk(j),j) for i,j in enumerate(jenis_hasil)]
        cols=[('kode','Kode'),('pemilik','Pemilik')]+[(k,n) for k,n,_ in bahan_cols]+[('bahan','Total bahan')]+[(k,n) for k,n,_ in hasil_cols]+[('hasil','Total hasil'),('susut','Susut debu & bobot'),('rendemen','Rendemen beras')]
    data['kolom']=[dict(kunci=k,nama=n,kelompok=('Bahan' if k=='bahan' or any(k==x[0] for x in bahan_cols) else 'Hasil' if k=='hasil' or any(k==x[0] for x in hasil_cols) else None) if kode=='penyosohan' else KELOMPOK.get(kode,{}).get(k)) for k,n in cols]
    for r,asli in zip(data['rincian'],baris):
        for k,_ in ISI[kode]:
            if k in ('bobot','nota','timbangan','selisih'):continue
            if k in asli:r[k]=str(asli[k]) if asli[k] is not None else 'Belum tercatat'
            else:r.setdefault(k,'Belum tercatat')
        if asli.get('pemilik_teks'):r['pemilik']=asli['pemilik_teks']
        for k,_,j in bahan_cols:
            bahan=asli.get('_bahan_per_jenis',{})
            # Kolom mencakup semua jenis dalam periode; jenis yang tidak
            # dipakai proses ini berbeda dari pemakaian yang belum final.
            r[k]=('-' if j not in bahan else kg(bahan[j]) if bahan[j] is not None else 'Belum final')
        for k,_,j in hasil_cols:
            outputs=asli.get('_output',{})
            r[k]=kg(outputs[j]) if j in outputs else ('-' if outputs else 'Belum tercatat')
    # Ringkasan memuat besaran yang memang dinilai pada tahap ini. Tidak ada
    # penjumlahan rendemen per lot atau pemakaian bobot nota sebagai bahan mesin.
    if kode in ('gabah_masuk','pk_masuk'):
        return kelompokkan_ringkasan(data,kode,baris)
    summary=[dict(nama='Jumlah transaksi',nilai=str(len(baris)))]
    def tambah(nama,kunci):
        value=jumlah(r.get(kunci) for r in baris)
        summary.append(dict(nama=nama,nilai=kg(value) if value is not None else ('0 kg' if not baris else 'Belum lengkap')))
    if kode in ('penggilingan','penyosohan','kemas_ulang'):
        tambah('Bahan terpakai' if kode!='kemas_ulang' else 'Bobot dibuka','_bahan')
        tambah('Hasil PK' if kode=='penggilingan' else 'Total hasil tercatat' if kode=='penyosohan' else 'Bobot kemasan baru','_hasil')
        if kode=='kemas_ulang':tambah('Sisa curah','_sisa')
        elif kode=='penyosohan':
            totals=defaultdict(Decimal)
            for r in baris:
                for jenis,v in r.get('_output',{}).items():totals[jenis]+=Decimal(str(v))
            from app.services.stok import nama_produk
            summary.extend(dict(nama=nama_produk(j),nilai=kg(v)) for j,v in totals.items())
            tambah('Susut debu & bobot','_susut')
        # Rendemen gabungan dihitung ulang atas bahan/hasil proses yang sama
        # dan sudah final; tidak merata-ratakan persentase lot berbeda ukuran.
        if kode!='kemas_ulang':
            b=jumlah(r.get('_bahan') for r in baris)
            h=jumlah(r.get('_hasil' if kode=='penggilingan' else '_beras') for r in baris)
            summary.append(dict(nama='Rendemen PK' if kode=='penggilingan' else 'Rendemen beras',nilai=persen(h/b*100 if b and h is not None and all(r.get('_rendemen_final') for r in baris) else None)))
    elif kode=='pengeringan':
        tambah('Gabah basah masuk','_basah');tambah('Gabah kering terukur','_kering');tambah('Estimasi gabah kering','_estimasi')
    elif kode=='pengemasan':tambah('Bobot batch kemasan','_hasil')
    elif kode=='barang_keluar':
        tambah('Bobot perintah','_perintah');tambah('Bobot dimuat','_dimuat')
    elif kode in ('transfer_pk','pemasukan_pk','pindah_pk','retur_pk','retur_pelanggan'):
        tambah(dict(transfer_pk='PK dipindahkan',pemasukan_pk='PK masuk Gudang 2',pindah_pk='PK dipindahkan',retur_pk='PK dikembalikan',retur_pelanggan='Retur diterima')[kode],'bobot')
    data['ringkasan']=summary
    data['catatan']=[c for c in data['catatan'] if not c.startswith('Bobot nota mengikuti')]
    if kode=='pengeringan':data['catatan'].append('Estimasi gabah kering dihitung dari kadar air mesin. Hasil terukur hanya berasal dari catatan flowing scale; estimasi tidak menggantikan hasil timbang.')
    if kode=='penggilingan':data['catatan'].append('Hasil PK mengikuti verifikasi final bila tersedia, selain itu progres kumulatif terakhir. Selisih gabah dengan PK mencakup sekam dan kehilangan lain yang tidak ditimbang terpisah; bukan ukuran sekam terukur. Rendemen hanya ditampilkan bila bahan pasti dan proses selesai.')
    if kode=='penyosohan':data['catatan'].append('Total hasil = total beras + total hasil samping; rincian di bawahnya adalah bagian dari total tersebut. % bahan baku = bobot hasil / total bahan terpakai × 100%, untuk setiap jenis dan total hasil. Rendemen beras = total beras / bahan terpakai × 100%. Susut = bahan terpakai - total hasil. Hasil mencakup setiap catatan keluaran per jenis dan spek, termasuk jenis tambahan pada master. Persentase, susut, dan rendemen hanya dihitung ketika bahan terpakai sudah final dan pasti. Susut negatif tetap ditampilkan untuk pemeriksaan.')
    if kode=='barang_keluar':data['catatan'].append('Muatan aktual dirinci per produk. Bobot nota/timbangan adalah bobot tiket armada; satu tiket dapat dipakai beberapa perintah. Nota kosong mengikuti timbangan.')
    return kelompokkan_ringkasan(data,kode,baris)
