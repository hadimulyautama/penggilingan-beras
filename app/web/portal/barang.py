"""Ringkasan komoditas dari saldo lokasi saat ini, tanpa menjumlah jejak asal.

Semua bobot berasal dari pembaca produksi. Asal batch hanya rincian untuk
penelusuran, tidak masuk penjumlahan kedua. Tidak menulis stok atau transaksi.
"""
from decimal import Decimal
from urllib.parse import parse_qs,urlsplit

from sqlalchemy import select,exists,func

from .navigation import portal_url

NAMA={'gabah':'Gabah','pk':'Beras pecah kulit (PK)','beras':'Beras',
      'broken':'Beras pecah (broken)','menir':'Menir','bekatul':'Bekatul',
      'reject':'Beras sortir (reject)','belum_dikenal':'Bahan belum teridentifikasi'}


def ringkas(rows):
    """Satu angka per komoditas; bobot tak diketahui tetap bukan nol."""
    grup={};seen=set()
    for r in rows:
        identitas=r.get('identitas')
        if identitas is not None:
            if identitas in seen:continue
            seen.add(identitas)
        if r['kg']==0 and r['final']:
            continue
        k=r['komoditas']
        g=grup.setdefault(k,dict(kunci=k,nama=NAMA.get(k,r['nama']),kg=None,
            belum_diukur=0,sementara=False,rincian=[],perlu_periksa=False))
        g['rincian'].append(r)
        if r['kg'] is None:
            g['belum_diukur']+=1
        else:
            g['kg']=(g['kg'] or Decimal(0))+Decimal(str(r['kg']))
            g['perlu_periksa']=g['perlu_periksa'] or r['kg']<0
        g['sementara']=g['sementara'] or not r['final']
    urut={k:i for i,k in enumerate(NAMA)}
    return sorted(grup.values(),key=lambda g:(urut.get(g['kunci'],99),g['nama']))


def _baris(jenis,nama,kode,bobot,lokasi,*,href=None,status='',asal=(),catatan=(),identitas=None):
    return dict(komoditas=jenis,nama=nama,kode=kode,kg=bobot.kg,
        final=bobot.pasti,lokasi=lokasi,href=portal_url(href) if href else None,
        status=status,asal=list(asal),catatan=list(catatan),identitas=identitas)


def _batch(b,scope):
    from app.penggilingan.gudang1.services.bobot import dari_batch
    href=(f'/barang-masuk/{b.timbangan_transaksi_id}'
          if b.timbangan_transaksi_id in scope.resources.get('timbangan_transaksi',())
          else f'/riwayat-qc/gabah-{b.kondisi_gabah}/{b.kode_batch}')
    return dict(kode=b.kode_batch,jenis='Gabah '+b.kondisi_gabah,
        kg=dari_batch(b).kg,tanggal=b.waktu_pembelian,
        kendaraan=b.no_polisi_truk,href=portal_url(href))


async def baca(db,scope,d):
    from app.models import (PurchaseBatch,DryingLot,DryingLotBatch,Dryer,Silo,
        SiloStorage,Warehouse,GabahKeringLot,GabahKeringBongkar,
        PkGudang2Intake,PolishingProcess,PolishingSiloUsage,PkTumpukanToSilo,
        PkPurchaseBatch,InternalTransfer,BerasKeSilo,BrokenKeSilo,HasilSampingKeSilo,ByproductStock,
        CustomerReturn)
    from app.penggilingan.gudang1.services.bobot import dari_batch,dari_batches,Bobot,PASTI,PERKIRAAN
    from app.penggilingan.gudang1.services.drying import _loose_dryer_batches,_lot_batches
    from app.penggilingan.gudang1.services.silo import _row_bobot,giling_berjalan_untuk_silo
    from app.penggilingan.gudang1.services.gabah_kering import pending_gabah_kering_kg
    from app.services import berjalan,stok
    from app.services.transit_pelanggan import boleh_baca_ruang
    from app.penggilingan.gudang2.service import hitung_stok_silo,komposisi_bahan_silo
    rows=[]
    sumber_cache={}

    async def asal_storage(row,seen=frozenset()):
        if row is None or row.jasa_id not in scope.jasa_ids or row.id in seen:
            return []
        if row.id in sumber_cache:return sumber_cache[row.id]
        asal=[]
        if row.purchase_batch_id in scope.ids(PurchaseBatch):
            asal=[_batch(await db.get(PurchaseBatch,row.purchase_batch_id),scope)]
        elif row.drying_lot_id in scope.ids(DryingLot):
            asal=[_batch(b,scope) for b in await _lot_batches(db,row.drying_lot_id)
                  if b.id in scope.ids(PurchaseBatch)]
        elif row.tipe_masuk=='dari_gabah_kering':
            pindah=await db.scalar(select(GabahKeringBongkar).where(GabahKeringBongkar.silo_storage_id==row.id))
            lot=await db.get(GabahKeringLot,pindah.gabah_kering_lot_id) if pindah else None
            if lot and lot.jasa_id in scope.jasa_ids:
                asal=await asal_storage(await db.get(SiloStorage,lot.silo_storage_id),seen|{row.id})
        sumber_cache[row.id]=asal
        return asal

    # Gabah sebelum pengeringan: satu catatan per batch.
    batches=(await db.scalars(select(PurchaseBatch).where(PurchaseBatch.id.in_(scope.ids(PurchaseBatch)),
        PurchaseBatch.status_batch.in_(('baru','ditumpuk'))))).all()
    for b in batches:
        rows.append(_baris('gabah','Gabah '+b.kondisi_gabah,b.kode_batch,dari_batch(b),
            'Tumpukan · Gudang 1',status='Menunggu penempatan',asal=[_batch(b,scope)],
            href=_batch(b,scope)['href'],identitas=('batch',b.id)))
    mesin_map={m.id:m for m in (await db.scalars(select(Dryer))).all()}
    for b in await _loose_dryer_batches(db):
        if b.id not in scope.ids(PurchaseBatch):continue
        mesin=mesin_map.get(b.dryer_id)
        rows.append(_baris('gabah','Gabah '+b.kondisi_gabah,b.kode_batch,dari_batch(b),
            mesin.nama if mesin else 'Mesin pengering',status='Menunggu pengeringan',
            asal=[_batch(b,scope)],href=_batch(b,scope)['href'],identitas=('batch',b.id)))
    # Lot yang sudah pindah ke silo tidak dihitung lagi di mesin.
    lots=list((await db.scalars(select(DryingLot).where(DryingLot.id.in_(scope.ids(DryingLot)),
        DryingLot.status=='proses',~exists().where(SiloStorage.drying_lot_id==DryingLot.id)))).all())
    for selesai in (False,True):
        lots.extend(await berjalan._lot(db,pendinginan_selesai=selesai))
    for lot in lots:
        if lot.id not in scope.ids(DryingLot):continue
        bs=[b for b in await _lot_batches(db,lot.id) if b.id in scope.ids(PurchaseBatch)]
        if not bs:continue
        mesin=mesin_map.get(lot.dryer_id)
        selesai=lot.waktu_selesai_pendinginan is not None
        phase='pengeringan' if lot.status=='proses' else 'pendinginan'
        href=f'/proses-aktif/{phase}/{lot.kode_lot}' if not selesai else f'/riwayat-pengeringan/{lot.id}'
        rows.append(_baris('gabah','Gabah',lot.kode_lot,dari_batches(bs),
            mesin.nama if mesin else 'Mesin pengering',
            status='Sedang dikeringkan' if lot.status=='proses' else 'Menunggu dipindahkan' if selesai else 'Sedang didinginkan',
            asal=[_batch(b,scope) for b in bs],href=href,identitas=('pengeringan',lot.id)))
    for row,nama in (await db.execute(select(SiloStorage,Silo.nama_silo).join(Silo,Silo.id==SiloStorage.silo_id)
        .where(SiloStorage.jasa_id.in_(scope.jasa_ids),SiloStorage.status=='terisi'))).all():
        asal=await asal_storage(row)
        if not asal:continue
        proses=await giling_berjalan_untuk_silo(db,row.silo_id)
        rows.append(_baris('gabah','Gabah',nama,await _row_bobot(db,row),nama,
            status='Sedang digiling' if proses and proses.kode_proses in scope.codes else 'Menunggu penggilingan',
            asal=asal,identitas=('silo-gabah',row.id)))
    for lot in (await db.scalars(select(GabahKeringLot).where(GabahKeringLot.jasa_id.in_(scope.jasa_ids)))).all():
        kg=await pending_gabah_kering_kg(db,lot.id)
        if kg<=0:continue
        asal=await asal_storage(await db.get(SiloStorage,lot.silo_storage_id))
        if asal:rows.append(_baris('gabah','Gabah kering',lot.kode_lot,Bobot(kg,PASTI),
            'Tumpukan · Gudang 1',asal=asal,status='Sudah ditimbang',identitas=('gabah-kering',lot.id)))

    for pk in (await db.scalars(select(PkPurchaseBatch).where(PkPurchaseBatch.id.in_(scope.ids(PkPurchaseBatch)),
        PkPurchaseBatch.status_batch=='diterima',~exists().where(PkGudang2Intake.pk_purchase_batch_id==PkPurchaseBatch.id)))).all():
        href=f'/riwayat-qc/pk-luar/{pk.kode_batch}'
        rows.append(_baris('pk',NAMA['pk'],pk.kode_batch,dari_batch(pk),'Gudang 2',
            status='Menunggu penempatan',href=href,identitas=('pk-masuk',pk.id),
            asal=[dict(kode=pk.kode_batch,jenis=NAMA['pk'],kg=dari_batch(pk).kg,
                tanggal=pk.waktu_pembelian,kendaraan=pk.no_polisi_truk,href=portal_url(href))]))

    # Stok tumpukan dan produk sudah dikurangi pemindahan/keluar oleh pembaca
    # asal. Jangan tambahkan lagi berat penerimaan pada daftar rincian asal.
    for r in d.get('stok',[]):
        if r['nama']!='PK' and 'kemasan_kg' not in r:continue
        query=parse_qs(urlsplit(r.get('href','')).query)
        bobot_kg=r['kg']
        if r['nama']=='PK':
            if query.get('gudang')==['g1'] and query.get('kode',[''])[0] not in scope.codes:continue
            if query.get('gudang')==['g2']:
                ident=int(query.get('id',['0'])[0])
                if ident not in scope.ids(PkGudang2Intake):continue
                intake=await db.get(PkGudang2Intake,ident)
                if intake.berat_kg is None:bobot_kg=None
            jenis='pk'
        else:
            jenis=query.get('jenis',['belum_dikenal'])[0]
            if stok.adalah_beras(jenis):jenis='beras'
        nama=r['nama'].split(' · ')[0] if r['nama']!='PK' else NAMA['pk']
        catatan=r.get('rincian',[])
        if 'kemasan_kg' in r:catatan=[c for c in catatan if c[0] in scope.codes]
        rows.append(dict(komoditas=jenis,nama=nama,kode=r['kode'],
            kg=bobot_kg,final=r['final'],lokasi=r['lokasi'],href=portal_url(r['href']),
            status='Berat sementara' if not r['final'] else '',asal=[],catatan=catatan,
            identitas=('stok',r['href'])))

    # Semua silo G2, termasuk yang sedang dipakai proses. Guard sumber
    # dijalankan sebelum membaca komposisi maupun daftar asalnya.
    silos=(await db.scalars(select(Silo).join(Warehouse,Silo.warehouse_id==Warehouse.id)
        .where(Warehouse.kode_fungsi=='g2'))).all()
    for silo in silos:
        if not await boleh_baca_ruang(db,scope,('silo_pk',silo.id)):continue
        kg=await hitung_stok_silo(db,silo.id)
        komposisi=await komposisi_bahan_silo(db,silo.id,target_kg=kg)
        proses=await db.scalar(select(PolishingProcess).join(PolishingSiloUsage,
            PolishingSiloUsage.polishing_process_id==PolishingProcess.id).where(
                PolishingSiloUsage.silo_id==silo.id,PolishingSiloUsage.berat_akhir_kg.is_(None),
                PolishingProcess.id.in_(scope.ids(PolishingProcess)),PolishingProcess.status=='proses'))
        # Asal hanya dari isian saat ini. Bobot asal adalah pemasukan, bukan
        # alokasi sisa per batch: pembaca komposisi hanya menetapkan komoditas.
        kosong=await db.scalar(select(func.max(PolishingProcess.waktu_selesai)).join(
            PolishingSiloUsage,PolishingSiloUsage.polishing_process_id==PolishingProcess.id).where(
                PolishingSiloUsage.silo_id==silo.id,PolishingSiloUsage.berat_akhir_kg==0))
        def setelah(col):return [col>=kosong] if kosong else []
        asal={}
        def tambah_asal(jenis,kode,berat,waktu,href):
            asal.setdefault(jenis,[]).append(dict(kode=kode,jenis=NAMA.get(jenis,jenis),
                kg=berat,tanggal=waktu,kendaraan=None,href=portal_url(href) if href else None))
        intakes=[(i,i.berat_kg,i.waktu_masuk) for i in (await db.scalars(select(PkGudang2Intake).where(
            PkGudang2Intake.silo_id==silo.id,*setelah(PkGudang2Intake.waktu_masuk)))).all()]
        intakes.extend((i,m.berat_kg,m.waktu) for i,m in (await db.execute(select(PkGudang2Intake,PkTumpukanToSilo)
            .join(PkTumpukanToSilo,PkTumpukanToSilo.pk_gudang2_intake_id==PkGudang2Intake.id).where(
                PkTumpukanToSilo.silo_id==silo.id,*setelah(PkTumpukanToSilo.waktu)))).all())
        for i,n,w in intakes:
            if i.id not in scope.ids(PkGudang2Intake):continue
            pk=await db.get(PkPurchaseBatch,i.pk_purchase_batch_id) if i.pk_purchase_batch_id else None
            tr=await db.get(InternalTransfer,i.internal_transfer_id) if i.internal_transfer_id else None
            tambah_asal('pk',pk.kode_batch if pk else tr.kode_transfer if tr else 'Penerimaan PK',n,w,
                f'/stok/pk/detail?gudang=g2&id={i.id}')
        for model in (BerasKeSilo,BrokenKeSilo,HasilSampingKeSilo):
            for m in (await db.scalars(select(model).where(model.silo_id==silo.id,*setelah(model.waktu)))).all():
                jenis='beras' if model is BerasKeSilo else 'broken' if model is BrokenKeSilo else m.jenis
                pid=getattr(m,'polishing_process_id',None)
                stock=await db.get(ByproductStock,m.byproduct_stock_id) if model is BrokenKeSilo else None
                source_type=stock.source_type if stock else getattr(m,'source_type',None)
                source_id=stock.source_id if stock else getattr(m,'source_id',None)
                if not pid and source_type=='polishing':pid=source_id
                kode,href=m.kode_pindah,None
                if pid in scope.ids(PolishingProcess):
                    p=await db.get(PolishingProcess,pid);kode=p.kode_proses;href=f'/riwayat-sosoh/{pid}'
                elif source_type=='timbangan' and source_id in scope.resources.get('timbangan_transaksi',()):
                    href=f'/barang-masuk/{source_id}'
                elif source_type=='retur' and source_id in scope.ids(CustomerReturn):href=f'/retur/{source_id}'
                tambah_asal(jenis,kode,m.berat_kg,m.waktu,href)
        for jenis,n in komposisi.items():
            if n<=0:continue
            k='beras' if jenis=='beras_putih' else jenis
            pasti=not proses and all(i.bobot_final for i,_,_ in intakes)
            rows.append(_baris(k,NAMA.get(k,k),silo.nama_silo,Bobot(n,PASTI if pasti else PERKIRAAN),silo.nama_silo,
                status='Sedang disosoh' if proses else 'Menunggu penyosohan',
                asal=asal.get(k,[]),href=f'/proses-aktif/sosoh/{proses.kode_proses}' if proses else None,
                identitas=('silo-g2',silo.id,k)))
        if any(n is None or (not n and not i.bobot_final) for i,n,_ in intakes):
            rows.append(_baris('pk',NAMA['pk'],silo.nama_silo,Bobot(None,PERKIRAAN),silo.nama_silo,
                status='Sebagian bahan belum ditimbang',asal=asal.get('pk',[]),
                identitas=('silo-g2-belum-diukur',silo.id)))
    return ringkas(rows)
