"""Rancangan koreksi bahan/hasil aktif. Satu transaksi milik pemanggil.

Saldo tetap melalui pembaca silo/tumpukan/hasil lama. Snapshot immutable
Peristiwa dan activity_logs menyimpan bukti asli serta nilai efektif baru.
Tidak menjalankan akhir proses, resinkronisasi commit, atau verifikasi.
"""
from __future__ import annotations
import hashlib, hmac, json, re
from types import SimpleNamespace
from decimal import Decimal as D, InvalidOperation
from sqlalchemy import select, func
from hmu_identitas import peran as P
from app.database import now_local
from app.models import (User, Silo, Warehouse, Peristiwa, MillingProcess,
    MillingProcessSource, MillingProgressLog, MillingProcessVerification,
    SiloStorage, PurchaseBatch, DryingLot, DryingLotBatch, GabahKeringBongkar,
    GabahKeringLot, PolishingProcess, PolishingSiloUsage, PkTumpukanToSilo,
    PkGudang2Intake, PkPurchaseBatch, PolishingOutputLog, InternalTransfer,
    BerasKeSilo, HasilSampingKeSilo, BrokenKeSilo)
from app.penggilingan.inventory.models import FinishedGoodsStock, ByproductStock, ProductSku
from app.services.activity_log import log_activity
from app.services import peristiwa as buku
from app.penggilingan.gudang1.services import silo as si, milling as m
from app.penggilingan.gudang1.services.bobot import dari_batch
from app.penggilingan.gudang2 import service as g2, polishing as p

JENIS='koreksi_bahan_hasil_berjalan'

class Konflik(ValueError):
    pass


def hash_(v):
    return hashlib.sha256(json.dumps(buku.bersih(v),sort_keys=True,default=str).encode()).hexdigest()


def raw(r):
    return {c.key:getattr(r,c.key) for c in r.__mapper__.column_attrs if c.key not in ('created_at','updated_at')}


def angka(v, nama, *, nol=True, presisi=3):
    try:n=D(str(v))
    except (InvalidOperation,TypeError):raise ValueError(f'{nama} harus diisi angka.') from None
    if isinstance(v,bool) or not n.is_finite() or n<0 or (n==0 and not nol):
        raise ValueError(f'{nama} harus berupa angka {"tidak negatif" if nol else "positif"}.')
    if n!=n.quantize(D(1).scaleb(-presisi)):
        raise ValueError(f'{nama} mengikuti presisi {presisi} desimal aplikasi.')
    return n


async def izin(db,user,jenis):
    # Operator boleh mengoreksi proses berjalan pada gudang efektifnya.
    # Status proses dan ketergantungan tetap diperiksa oleh layanan berikutnya.
    if jenis not in ('giling','sosoh'):raise ValueError('Jenis proses tidak dikenal.')
    if not user or not (P.admin_keatas(user.role) or P.operator_saja(user.role)):
        raise PermissionError('Koreksi proses berjalan memerlukan petugas operasional yang berwenang.')
    from app.peran import user_wh_scope
    if await user_wh_scope(db,user) not in ('all','g1' if jenis=='giling' else 'g2'):
        raise PermissionError('Gudang efektif tidak mengizinkan koreksi proses ini.')


async def proses(db,jenis,kode,*,kunci=False):
    if kode.startswith('catatan-'):
        ident=kode.removeprefix('catatan-').split('-')
        if len(ident)==2 and jenis=='sosoh':
            model=_CURAH.get(ident[0])
            if model is None:raise ValueError('Jenis catatan bahan tidak dikenal.')
            identitas=int(ident[1])
        else:
            identitas=int(ident[0]);model=SiloStorage if jenis=='giling' else PkTumpukanToSilo
        q=select(model).where(model.id==identitas).execution_options(populate_existing=True)
        entry=await db.scalar(q.with_for_update() if kunci else q)
        if entry is None:raise ValueError('Catatan masuk silo tidak ditemukan.')
        if jenis=='sosoh':
            if entry.dibatalkan_pada:raise ValueError('Catatan sudah dibatalkan.')
            if await siklus_g2(db,entry):raise ValueError('Catatan sudah terkait proses. Buka koreksi dari proses yang bersangkutan.')
            if isinstance(entry,PkTumpukanToSilo):
                source=await db.get(PkGudang2Intake,entry.pk_gudang2_intake_id);owner=source.jasa_id
            else:owner=entry.jasa_id
        else:
            if entry.status!='terisi':raise ValueError('Isi silo ini tidak lagi aktif.')
            if await db.scalar(select(MillingProcessSource.id).where(MillingProcessSource.silo_storage_id==entry.id).limit(1)):
                raise ValueError('Catatan sudah terkait proses. Buka koreksi dari proses yang bersangkutan.')
            owner=entry.jasa_id
        return SimpleNamespace(id=None,kode_proses=kode,status='proses',jasa_id=owner,catatan=entry)
    model=MillingProcess if jenis=='giling' else PolishingProcess
    q=select(model).where(model.kode_proses==kode).execution_options(populate_existing=True)
    pr=await db.scalar(q.with_for_update() if kunci else q)
    if not pr:raise ValueError('Proses tidak ditemukan.')
    if pr.status!='proses':raise ValueError('Proses sudah ditutup. Gunakan mekanisme koreksi proses selesai.')
    return pr


async def g1_sumber(db,key):
    """Alokasi bukan penerimaan baru. NULL alokasi mempertahankan data lama.

    Sumber hasil drying mempertahankan dasar bobot lama (beserta kepastian),
    bukan dianggap bobot kering final baru. Bagian yang dilepas adalah saldo
    sumber belum dialokasikan, bukan penambahan stok fisik kedua.
    """
    tipe,identitas=key.split(':'); identitas=int(identitas)
    if tipe=='batch':
        src=await db.get(PurchaseBatch,identitas,populate_existing=True)
        if not src or src.dibatalkan_pada or src.kondisi_gabah!='kering':raise ValueError('Sumber harus gabah kering yang sah.')
        if await db.scalar(select(DryingLotBatch.purchase_batch_id).where(DryingLotBatch.purchase_batch_id==src.id).limit(1)):
            raise ValueError('Batch sudah menjadi bahan pengeringan; pilih lot pengeringan asal.')
        b=dari_batch(src);kolom=SiloStorage.purchase_batch_id;kode=src.kode_batch;owner=src.jasa_id
    elif tipe=='drying':
        src=await db.get(DryingLot,identitas,populate_existing=True)
        if not src or src.status not in ('selesai','di_silo','digiling','selesai_pindah'):
            # Status sah ditentukan keberadaan penerimaan silo, bukan label
            # contoh pada UI; lot lama yang telah berada di silo tetap sah.
            if not src or not await db.scalar(select(SiloStorage.id).where(SiloStorage.drying_lot_id==identitas).limit(1)):
                raise ValueError('Lot pengeringan belum menjadi sumber silo yang sah.')
        b=await si._lot_bobot(db,identitas);kolom=SiloStorage.drying_lot_id;kode=src.kode_lot;owner=src.jasa_id
    elif tipe=='bongkar':
        src=await db.get(GabahKeringLot,identitas,populate_existing=True)
        if not src:raise ValueError('Sumber gabah kering tidak ditemukan.')
        from app.penggilingan.gudang1.services.gabah_kering import saldo_gabah_kering
        saldo=await saldo_gabah_kering(db,src.id)
        return dict(key=key,kode=src.kode_lot,pemilik=src.jasa_id,kg=float(src.berat_timbang_kg),bebas=float(saldo),final=True,rows=[])
    else:raise ValueError('Jenis sumber gabah tidak sah.')
    rows=list((await db.scalars(select(SiloStorage).where(kolom==identitas).order_by(SiloStorage.id))).all())
    used=sum((D(str(r.alokasi_koreksi_kg)) if r.alokasi_koreksi_kg is not None else D(str(b.kg))) for r in rows if r.status!='batal') if b.diketahui else None
    from app.services.retur_supplier_reservasi import terikat
    reservasi=await terikat(db,sumber=f'gabah:{identitas}') if tipe=='batch' else D(0)
    return dict(key=key,kode=kode,pemilik=owner,kg=b.kg,bebas=None if used is None else float(D(str(b.kg))-used-reservasi),final=b.pasti,rows=[raw(r) for r in rows])


def g1_key(st,bongkar=None):
    if st.purchase_batch_id:return f'batch:{st.purchase_batch_id}'
    if st.drying_lot_id:return f'drying:{st.drying_lot_id}'
    if bongkar:return f'bongkar:{bongkar.gabah_kering_lot_id}'
    raise ValueError('Hubungan sumber historis belum lengkap; telusuri penerimaan asal.')


async def g2_sumber(db,it):
    if not it or it.dibatalkan_pada or it.tujuan!='ditumpuk':raise ValueError('Sumber harus tumpukan PK aktif yang sah.')
    batch=await db.get(PkPurchaseBatch,it.pk_purchase_batch_id,populate_existing=True) if it.pk_purchase_batch_id else None
    from app.penggilingan.gudang2.karung import bobot_per_karung
    saldo=await g2._sisa_tumpukan_intake(db,it.id)
    from app.services.retur_supplier_reservasi import terikat,karung_terikat
    reservasi=await terikat(db,sumber=f'pk:{batch.id}') if batch else D(0)
    n=None;r=None
    if batch and batch.jumlah_karung:
        r=bobot_per_karung(batch)
        used=await db.scalar(select(func.coalesce(func.sum(PkTumpukanToSilo.jumlah_karung),0)).where(PkTumpukanToSilo.pk_gudang2_intake_id==it.id,PkTumpukanToSilo.dibatalkan_pada.is_(None)))
        n=batch.jumlah_karung-int(used)-await karung_terikat(db,f'pk:{batch.id}')
    transfer=await db.get(InternalTransfer,it.internal_transfer_id) if it.internal_transfer_id else None
    if it.pk_purchase_batch_id is not None and (batch is None or batch.status_batch=='ditolak'):
        raise ValueError('Penerimaan PK asal tidak aktif atau sudah ditolak.')
    if it.internal_transfer_id is not None and (transfer is None or transfer.status!='terkirim'):
        raise ValueError('Transfer sumber tidak lagi aktif; periksa penggantinya.')
    return dict(key=str(it.id),kode=batch.kode_batch if batch else transfer.kode_transfer if transfer else f'Tumpukan #{it.id}',pemilik=it.jasa_id,
        kg=float(it.berat_kg) if it.berat_kg is not None else None,bebas=None if saldo is None else float(D(str(saldo))-reservasi),
        satuan='karung' if n is not None else 'kg',karung=n,rasio=None if r is None else float(r),
        final=dari_batch(batch).pasti if batch else it.bobot_final,raw=raw(it),batch=raw(batch) if batch else None)


async def konteks(db,*,jenis,kode,user):
    await izin(db,user,jenis);pr=await proses(db,jenis,kode)
    if getattr(pr,'catatan',None) is not None:
        return await konteks_belum(db,jenis,kode,user,pr)
    entries=[];sources={};deps=[]
    if jenis=='sosoh':
        usages=list((await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pr.id).order_by(PolishingSiloUsage.id))).all())
        # Catatan kg lama tidak punya FK siklus. Hubungkan hanya bila interval
        # waktu benar-benar tunggal; ambiguitas ditampilkan, tidak ditebak.
        for u in usages:
            silo=await db.get(Silo,u.silo_id)
            moves=list((await db.scalars(select(PkTumpukanToSilo).where(PkTumpukanToSilo.silo_id==u.silo_id,PkTumpukanToSilo.dibatalkan_pada.is_(None)).order_by(PkTumpukanToSilo.id))).all())
            for move in moves:
                linked=await siklus_g2(db,move)
                if linked is None or linked.id!=u.id:continue
                it=await db.get(PkGudang2Intake,move.pk_gudang2_intake_id)
                source=await g2_sumber(db,it);sources[source['key']]=source
                entries.append(dict(id=move.id,kode=move.kode_pindah,silo=silo.nama_silo,silo_id=silo.id,siklus=u.id,
                    sumber=source['key'],kg=float(move.berat_kg) if move.berat_kg is not None else None,
                    jumlah=move.jumlah_karung if move.jumlah_karung is not None else float(move.berat_kg) if move.berat_kg is not None else None,
                    satuan='karung' if move.jumlah_karung is not None else 'kg',sisa=u.berat_akhir_kg,raw=raw(move)))
        candidates=(await db.scalars(select(PkGudang2Intake).where(PkGudang2Intake.tujuan=='ditumpuk',PkGudang2Intake.dibatalkan_pada.is_(None),PkGudang2Intake.jasa_id==pr.jasa_id).order_by(PkGudang2Intake.id))).all()
        for it in candidates:
            s=await g2_sumber(db,it)
            if s['key'] in sources or s['bebas'] is None or s['bebas']>0:sources[s['key']]=s
        more,alternatives=await konteks_curah(db,pr,usages)
        entries.extend(more);sources.update(alternatives)
        outputs=await p._output_map(db,pr.id)
        jenis_hasil=sorted(p._ALL_JENIS)
        consumed=sum(float(u.berat_terpakai_kg if u.berat_akhir_kg is not None else u.berat_awal_kg+u.berat_masuk_kg) for u in usages)
        basis=consumed if all(x['kg'] is not None for x in entries) else None;logs=list((await db.scalars(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==pr.id).order_by(PolishingOutputLog.id))).all())
        for model in (FinishedGoodsStock,ByproductStock):
            deps.extend([raw(x) for x in (await db.scalars(select(model).where(model.source_type=='polishing',model.source_id==pr.id).order_by(model.id))).all()])
        for model in (BerasKeSilo,HasilSampingKeSilo):
            deps.extend([raw(x) for x in (await db.scalars(select(model).where(model.polishing_process_id==pr.id).order_by(model.id))).all()])
        verification=None
    else:
        usages=list((await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==pr.id).order_by(MillingProcessSource.id))).all())
        for u in usages:
            st=await db.get(SiloStorage,u.silo_storage_id);silo=await db.get(Silo,st.silo_id)
            bo=await db.scalar(select(GabahKeringBongkar).where(GabahKeringBongkar.silo_storage_id==st.id))
            key=g1_key(st,bo);src=await g1_sumber(db,key);sources[key]=src
            initial=float(st.alokasi_koreksi_kg) if st.alokasi_koreksi_kg is not None else float(bo.berat_kg) if bo else src['kg']
            entries.append(dict(id=st.id,kode=f'Isi silo #{st.id}',silo=silo.nama_silo,silo_id=silo.id,siklus=u.id,sumber=key,kg=initial,jumlah=initial,satuan='kg',sisa=u.berat_akhir_kg,raw=raw(st)))
        candidates=(await db.scalars(select(PurchaseBatch).where(PurchaseBatch.kondisi_gabah=='kering',PurchaseBatch.dibatalkan_pada.is_(None),PurchaseBatch.jasa_id==pr.jasa_id).order_by(PurchaseBatch.id))).all()
        for b in candidates:
            key=f'batch:{b.id}'
            try:s=await g1_sumber(db,key)
            except ValueError:continue
            if key in sources or s['bebas'] is None or s['bebas']>0:sources[key]=s
        for lot in (await db.scalars(select(GabahKeringLot).where(GabahKeringLot.jasa_id==pr.jasa_id).order_by(GabahKeringLot.id))).all():
            key=f'bongkar:{lot.id}';available=await g1_sumber(db,key)
            if key in sources or available['bebas']>0:sources[key]=available
        for lot in (await db.scalars(select(DryingLot).where(DryingLot.jasa_id==pr.jasa_id,DryingLot.status=='selesai',DryingLot.waktu_selesai_pendinginan.is_not(None)).order_by(DryingLot.id))).all():
            key=f'drying:{lot.id}';available=await g1_sumber(db,key)
            if key in sources or available['bebas'] is None or available['bebas']>0:sources[key]=available
        operator=await m._latest_progress(db,pr.id);outputs={'pk':operator};jenis_hasil=['pk'];bd=await m._pk_breakdown(db,pr.id)
        verification=await db.scalar(select(MillingProcessVerification).where(MillingProcessVerification.milling_process_id==pr.id))
        deps.append(vars(bd));logs=list((await db.scalars(select(MillingProgressLog).where(MillingProgressLog.milling_process_id==pr.id).order_by(MillingProgressLog.id))).all())
        basis=None if any(u.berat_kg is None for u in usages) else sum(float(u.berat_terpakai_kg if u.berat_akhir_kg is not None else u.berat_kg) for u in usages)
    from app.services.jasa import nama_pemilik
    owner=await nama_pemilik(db,pr.jasa_id) if pr.jasa_id else 'Milik pabrik'
    if jenis=='giling':
        stock_values={'PK tersedia proses ini':bd.tersedia}
    else:
        from app.services.stok import beras_curah
        from app.penggilingan.inventory.finished_goods import hitung_stok_byproduct_total
        from app.services.jasa import pemilik_hasil_proses
        stock_values={'Hasil '+x.jenis+' belum dikemas/dipindah · proses ini':x.sisa_kg for x in await beras_curah(db,proses_id=pr.id)}
        for k in p.BYPRODUCTS:
            if outputs.get(k,0):
                owner_id=await pemilik_hasil_proses(db,pr.jasa_id,k)
                stock_values['Stok '+k+' tersedia · seluruh sumber pemilik terkait']=await hitung_stok_byproduct_total(db,k,jasa_id=owner_id)
    values=dict(stok_hasil=stock_values,jenis=jenis,kode=kode,id=pr.id,status=pr.status,pemilik=owner,jasa_id=pr.jasa_id,entries=entries,sources=list(sources.values()),outputs=outputs,jenis_hasil=jenis_hasil,basis=basis,
        verification=raw(verification) if verification else None)
    terkait=await siklus_terkait(db,jenis,{x['silo_id'] for x in entries})
    from app.penggilingan.gudang1.services.jeda import jeda_terbuka
    pause=await jeda_terbuka(db,'giling' if jenis=='giling' else 'penyosohan',pr.id)
    values['status_tampil']='Dijeda' if pause else 'Berjalan'
    values['terkait']=terkait
    values['dasar']=hash_([raw(pr),[raw(u) for u in usages],[raw(l) for l in logs],values,deps])
    audits=list((await db.scalars(select(Peristiwa).where(Peristiwa.jenis==JENIS,Peristiwa.muatan['isian'][0].as_string()==jenis,Peristiwa.muatan['isian'][1].as_string()==kode).order_by(Peristiwa.id.desc()).limit(100))).all())
    from app.database import berzona
    names=dict((await db.execute(select(User.id,User.nama).where(User.id.in_({e.pelaku_id for e in audits})))).all()) if audits else {}
    values['riwayat']=[dict(id=e.id,waktu=berzona(e.waktu).strftime('%d/%m/%Y %H:%M'),petugas=names.get(e.pelaku_id,f'Petugas #{e.pelaku_id}'),alasan=e.muatan['isian'][2]['alasan']) for e in audits]
    return buku.bersih(values)


async def konteks_belum(db,jenis,kode,user,pr):
    row=pr.catatan;silo=await db.get(Silo,row.silo_id)
    wh=await db.get(Warehouse,silo.warehouse_id)
    if wh.kode_fungsi!=('g1' if jenis=='giling' else 'g2'):raise ValueError('Gudang catatan tidak sesuai jenis koreksi.')
    if jenis=='sosoh' and not isinstance(row,PkTumpukanToSilo):
        rows,sources=await konteks_curah(db,pr,[],catatan=row);e=rows[0]
    elif jenis=='sosoh':
        src=await g2_sumber(db,await db.get(PkGudang2Intake,row.pk_gudang2_intake_id))
        qty=row.jumlah_karung if row.jumlah_karung is not None else row.berat_kg
        e=dict(id=row.id,kode=row.kode_pindah,silo=silo.nama_silo,silo_id=silo.id,siklus=None,sumber=src['key'],kg=row.berat_kg,jumlah=qty,satuan='karung' if row.jumlah_karung is not None else 'kg',sisa=row.berat_kg,raw=raw(row))
        candidates=(await db.scalars(select(PkGudang2Intake).where(PkGudang2Intake.jasa_id==pr.jasa_id,PkGudang2Intake.dibatalkan_pada.is_(None),PkGudang2Intake.tujuan=='ditumpuk'))).all()
        sources={src['key']:src}
        for it in candidates:
            x=await g2_sumber(db,it)
            if x['key'] in sources or x['bebas'] is not None and x['bebas']>0:sources[x['key']]=x
    else:
        bo=await db.scalar(select(GabahKeringBongkar).where(GabahKeringBongkar.silo_storage_id==row.id))
        key=g1_key(row,bo);src=await g1_sumber(db,key)
        qty=row.alokasi_koreksi_kg if row.alokasi_koreksi_kg is not None else bo.berat_kg if bo else src['kg']
        e=dict(id=row.id,kode=f'Isi silo #{row.id}',silo=silo.nama_silo,silo_id=silo.id,siklus=None,sumber=key,kg=qty,jumlah=qty,satuan='kg',sisa=qty,raw=raw(row))
        sources={key:src}
        for b in (await db.scalars(select(PurchaseBatch).where(PurchaseBatch.jasa_id==pr.jasa_id,PurchaseBatch.kondisi_gabah=='kering',PurchaseBatch.dibatalkan_pada.is_(None)))).all():
            try:x=await g1_sumber(db,f'batch:{b.id}')
            except ValueError:continue
            if x['key'] in sources or x['bebas'] is not None and x['bebas']>0:sources[x['key']]=x
    if jenis=='giling':
        for model,prefix in ((GabahKeringLot,'bongkar'),(DryingLot,'drying')):
            q=select(model).where(model.jasa_id==pr.jasa_id)
            if model==DryingLot:q=q.where(DryingLot.status=='selesai',DryingLot.waktu_selesai_pendinginan.is_not(None))
            for lot in (await db.scalars(q.order_by(model.id))).all():
                x=await g1_sumber(db,f'{prefix}:{lot.id}')
                if x['key'] in sources or x['bebas'] is None or x['bebas']>0:sources[x['key']]=x
    e['sisa']=None
    from app.services.jasa import nama_pemilik
    value=dict(jenis=jenis,kode=kode,id=None,status='belum_dipakai',pemilik=await nama_pemilik(db,pr.jasa_id) if pr.jasa_id else 'Milik pabrik',jasa_id=pr.jasa_id,entries=[e],sources=list(sources.values()),outputs={},jenis_hasil=[],basis=None,verification=None)
    value['dasar']=hash_(value)
    return buku.bersih(value)


async def siklus_g2(db,move):
    if getattr(move,"pemakaian_silo_id",None):
        return await db.get(PolishingSiloUsage,move.pemakaian_silo_id,populate_existing=True)
    from app.models import ActivityLog
    rows=(await db.execute(select(PolishingSiloUsage,PolishingProcess).join(PolishingProcess).where(PolishingSiloUsage.silo_id==move.silo_id).order_by(PolishingSiloUsage.id))).all()
    ends={}
    if rows:
        logs=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='polishing_silo_usage',ActivityLog.aksi=='tutup_silo_sosoh',ActivityLog.record_id.in_([u.id for u,pr in rows])).order_by(ActivityLog.id))).all()
        ends={x.record_id:x.waktu_perubahan for x in logs}
    for u,pr in rows:
        end=ends.get(u.id,pr.waktu_selesai)
        if pr.waktu_mulai<=move.waktu and ((end is not None and move.waktu<=end) or (end is None and u.berat_akhir_kg is None and pr.status=='proses')):
            return u
    later=[u for u,pr in rows if pr.waktu_mulai>=move.waktu]
    return later[0] if later else None


async def hasil_berjalan(db,jenis,pr,targets,user,alasan):
    if not targets:return
    if jenis=='giling':
        if set(targets)!={'pk'}:raise ValueError('Penggilingan memakai hasil PK kumulatif.')
        target=angka(targets['pk'],'Total PK',nol=False,presisi=2)
        old=await m._latest_progress(db,pr.id)
        if old is not None and D(str(old))==target:raise ValueError('Total PK tidak berubah.')
        v=await db.scalar(select(MillingProcessVerification).where(MillingProcessVerification.milling_process_id==pr.id))
        if not v or v.berat_output_final_kg is None:
            used=await m._transferred_pk(db,pr.id)+await m._sold_pk_langsung(db,pr.id)
            if target<D(str(used)):
                from app.services.penghalang_koreksi import daftar
                raise ValueError(f'Total PK {target} kg kurang dari {used:g} kg yang sudah dipakai: '+json.dumps(await daftar(db,'giling',pr.id),ensure_ascii=False))
        await m.log_progress(db,user=user,kode_proses=pr.kode_proses,berat_kumulatif=float(target),simpan=False)
        await log_activity(db,table_name='milling_progress_logs',record_id=pr.id,action='UPDATE',changed_by=user.id,
            field_name='kumulatif_operator',old_value=str(old),new_value=str(target),alasan=alasan,aksi=JENIS)
    else:
        if not set(targets)<=p._ALL_JENIS:raise ValueError('Jenis hasil penyosohan tidak dikenal.')
        old=await p._output_map(db,pr.id);new={k:old.get(k,0) for k in p._ALL_JENIS}
        from app.penggilingan.inventory.models import FinishedGoodsStock,ByproductStock,ProductSku
        from app.models import BerasKeSilo,HasilSampingKeSilo
        for kind,v in targets.items():
            target=angka(v,'Total '+kind,presisi=2)
            if target==D(str(new[kind])):continue
            if target>D(str(new[kind])):
                # Menambah hasil tidak membatalkan pemakaian/kemasan lama.
                new[kind]=float(target);continue
            # Catatan hilir hanya memblokir jenis yang sedang dikoreksi.
            from app.services.stok import kategori_dan_mutu
            from app.penggilingan.inventory.finished_goods import get_standard
            kategori,mutu=kategori_dan_mutu(kind)
            std=await get_standard(db,mutu) if mutu else None
            blockers=[]
            stock=await db.scalar(select(FinishedGoodsStock).join(ProductSku,ProductSku.id==FinishedGoodsStock.product_sku_id).where(FinishedGoodsStock.source_type=='polishing',FinishedGoodsStock.source_id==pr.id,
                ProductSku.kategori==kategori,FinishedGoodsStock.rice_quality_standard_id==(std.id if std else None)).limit(1))
            if stock:blockers.append(f'Catatan kemasan/curah #{stock.id}: {stock.berat_total_kg} kg (/koreksi-catatan/packing/{stock.id})')
            for model,where in [(ByproductStock,ByproductStock.jenis_produk==kind),
                (BerasKeSilo,BerasKeSilo.jenis==kind),(HasilSampingKeSilo,HasilSampingKeSilo.jenis==kind)]:
                q=select(model).where(where)
                if model==ByproductStock:q=q.where(model.source_type=='polishing',model.source_id==pr.id)
                else:q=q.where(model.polishing_process_id==pr.id)
                for row in (await db.scalars(q)).all():blockers.append(f'{model.__tablename__} #{row.id}: {getattr(row,"berat_kg",None)} kg')
            if blockers:raise ValueError('Koreksi '+kind+' ditahan oleh '+ '; '.join(blockers)+'. Perbaiki catatan terkait melalui alur yang sah.')
            new[kind]=float(target)
        if all(new[k]==old.get(k,0) for k in new):raise ValueError('Tidak ada perubahan hasil.')
        await p.koreksi_hasil_sosoh(db,user=user,process_id=pr.id,perubahan=new,dasar={k:old.get(k,0) for k in p._ALL_JENIS},alasan=alasan,berjalan=True,simpan=False)


async def bahan_g2(db,entry,change,pr,user,alasan,*,gabungan=False):
    move=await db.get(PkTumpukanToSilo,entry['id'],populate_existing=True)
    if not move or move.dibatalkan_pada:raise Konflik('Catatan bahan sudah dibatalkan.')
    before=raw(move);oldkg=move.berat_kg
    if oldkg is None:raise ValueError('Bobot bahan belum diketahui; pemeriksaan dampak menunggu sumber yang sah.')
    usage=await siklus_g2(db,move)
    if usage and (not pr or usage.polishing_process_id!=pr.id):
        other=await db.get(PolishingProcess,usage.polishing_process_id)
        raise ValueError(f'{move.kode_pindah} terkait {other.kode_proses} ({other.status}); periksa proses terkait.')
    oldsource=await db.get(PkGudang2Intake,move.pk_gudang2_intake_id)
    cancel=change.get('hapus',False)
    target=oldsource if cancel else await db.get(PkGudang2Intake,int(change['sumber']),populate_existing=True)
    source=await g2_sumber(db,target)
    if target.jasa_id!=oldsource.jasa_id or (pr and target.jasa_id!=pr.jasa_id):raise ValueError('Pemilik sumber pengganti harus sesuai seluruh bahan proses.')
    silo=await db.get(Silo,move.silo_id)
    if not silo or not silo.aktif:raise ValueError('Silo tujuan tidak lagi aktif.')
    g2._pastikan_komoditas_silo(silo,'pk')
    if await g2._g2_warehouse_id(db)!=silo.warehouse_id:raise ValueError('Gudang silo tidak sesuai.')
    unit=source['satuan'];qty=D(0) if cancel else angka(change.get('jumlah'),'Jumlah bahan',nol=False)
    if unit=='karung' and qty!=qty.to_integral_value():raise ValueError('Jumlah karung harus bilangan bulat.')
    if unit=='karung':
        if source['rasio'] is None:raise ValueError('Bobot per karung belum tersedia dari partai asal.')
        from app.penggilingan.gudang2.karung import bobot_per_karung
        batch=await db.get(PkPurchaseBatch,target.pk_purchase_batch_id)
        newkg=D(0) if cancel else bobot_per_karung(batch,jumlah=int(qty))
        available=source['karung']+(move.jumlah_karung or 0 if target.id==oldsource.id else 0)
        if not gabungan and qty>available:raise ValueError(f'Saldo bebas {source["karung"]} karung; batas catatan ini {available} karung pada {source["kode"]}.')
    else:newkg=qty;batch=None
    free=None if source['bebas'] is None else D(str(source['bebas']))+(D(str(oldkg)) if target.id==oldsource.id else D(0))
    if free is None:raise ValueError('Saldo sumber belum tersedia; bukan nol.')
    if not gabungan and newkg>free+D('.000001'):raise ValueError(f'{source["kode"]}: saldo bebas {source["bebas"]} kg; batas koreksi {free} kg; diminta {newkg} kg. Alokasi transaksi lain dipertahankan.')
    # Kontribusi dipasang dahulu; sisa seluruh rancangan diperiksa bersama.
    old_fixed=None
    if usage and move.pemakaian_silo_id!=usage.id:
        column='awal_tetap_kg' if move.waktu<=pr.waktu_mulai else 'masuk_tetap_kg'
        old_fixed=(column,D(str(getattr(usage,column) or 0)))
    if cancel:
        move.dibatalkan_pada=now_local()
    else:
        move.pk_gudang2_intake_id=target.id;move.batch=batch
        move.jumlah_karung=int(qty) if unit=='karung' else None
        move.berat_timbang_kg=None if unit=='karung' else newkg
        if target.internal_transfer_id:
            from app.services.pk_50 import bagi_tersimpan
            move.jumlah_karung_50,move.berat_curah_kg=bagi_tersimpan(newkg,3)
        else:move.jumlah_karung_50=None;move.berat_curah_kg=None
    if usage:
        if old_fixed:
            col,value=old_fixed
            # Semua kontribusi yang sebelumnya kg tetap tetap di basis tetap;
            # baris dinamis lama otomatis membaca jumlah/partai efektif baru.
            setattr(usage,col,value+newkg-D(str(oldkg)))
    if not cancel and before==raw(move) and 'sisa' not in change:raise ValueError('Catatan bahan tidak berubah.')
    await log_activity(db,table_name='pk_tumpukan_to_silo',record_id=move.id,action='UPDATE',changed_by=user.id,
        old_value=json.dumps(buku.bersih(before),default=str),new_value=json.dumps(buku.bersih(raw(move)),default=str),alasan=alasan,aksi=JENIS)
    await db.flush()
    return dict(peristiwa_asal_id=move.peristiwa_id,move_id=move.id,intake_id=move.pk_gudang2_intake_id,
        berat_kg=move.berat_timbang_kg,jumlah_karung=move.jumlah_karung,jumlah_karung_50=move.jumlah_karung_50,
        berat_curah_kg=move.berat_curah_kg,batal=bool(move.dibatalkan_pada))


async def bahan_g1(db,entry,change,pr,user,alasan,*,gabungan=False):
    st=await db.get(SiloStorage,entry['id'],populate_existing=True)
    if not st or st.status=='batal':raise Konflik('Catatan isi silo tidak aktif.')
    silo=await si.silo_g1_by_id(db,st.silo_id)
    from app.penggilingan.silo_policy import boleh_masuk
    if not silo or not boleh_masuk(silo,'gabah_kering','g1'):
        raise ValueError('Silo Gudang 1 atau kompatibilitas gabah berubah; periksa tujuan terkait.')
    before=raw(st)
    if st.status=='koreksi':before['status']=entry['raw']['status']
    oldkey=entry['sumber'];newkey=change.get('sumber',oldkey)
    cancel=change.get('hapus',False);oldkg=angka(entry['kg'],'Bobot sebelumnya')
    target=await g1_sumber(db,newkey)
    if newkey!=oldkey and newkey.startswith('drying:'):
        lot=await db.get(DryingLot,int(newkey.split(':')[1]))
        if lot.status!='selesai' or lot.waktu_selesai_pendinginan is None:raise ValueError('Lot pengganti harus selesai pengeringan dan pendinginan melalui alur lama.')
    if target['pemilik']!=st.jasa_id or (pr and target['pemilik']!=pr.jasa_id):raise ValueError('Pemilik sumber pengganti tidak sesuai proses.')
    if (oldkey.split(':')[0]=='bongkar')!=(newkey.split(':')[0]=='bongkar'):raise ValueError('Sumber hasil timbang gabah kering harus tetap memakai hubungan bongkar asal yang sah.')
    qty=D(0) if cancel else angka(change.get('jumlah'),'Bobot bahan',nol=False,presisi=2 if newkey.startswith('bongkar:') else 3)
    if not cancel and oldkey==newkey and qty==oldkg and ('sisa' not in change or change['sisa']==entry['sisa']):raise ValueError('Tidak ada perubahan jumlah, sumber, atau sisa.')
    free=None if target['bebas'] is None else D(str(target['bebas']))+(oldkg if oldkey==newkey else D(0))
    if free is None:raise ValueError('Bobot sumber belum tersedia. Periksa sumber timbang, bukan mengisinya sebagai nol.')
    if not gabungan and not cancel and newkey!=oldkey and any(r['status']=='terisi' and r['id']!=st.id for r in target['rows']):
        raise ValueError('Sumber pengganti sudah berada di catatan silo aktif lain. Periksa catatan tersebut; hubungan silo tidak boleh digandakan.')
    if not gabungan and qty>free+D('.000001'):raise ValueError(f'{target["kode"]}: saldo bebas {target["bebas"]} kg, batas koreksi {free} kg, diminta {qty} kg.')
    sources=list((await db.scalars(select(MillingProcessSource).where(MillingProcessSource.silo_storage_id==st.id).order_by(MillingProcessSource.id))).all())
    current=[u for u in sources if pr and u.milling_process_id==pr.id]
    if sources and current and sources[0].id!=current[0].id:
        raise ValueError('Catatan juga membentuk siklus sebelumnya. Buka koreksi dari proses asal agar seluruh pengaruhnya diperiksa bersama.')
    for u in sources:
        other=await db.get(MillingProcess,u.milling_process_id)
        if other.status!='proses':
            raise ValueError(f'Siklus terkait {other.kode_proses} sudah {other.status}: /riwayat-giling/{other.id}. Gunakan koreksi proses selesai yang sah.')
    if len(current)>1:raise ValueError('Hubungan siklus giling tidak tunggal; periksa catatan sumber.')
    if current:
        src=current[0]
        if src.berat_kg is None:raise ValueError('Basis bahan proses belum diketahui; koreksi memerlukan pembanding sah.')
        before_src=raw(src)
        old_consumed=D(str(src.berat_terpakai_kg)) if src.berat_akhir_kg is not None else None
        old_remain=D(str(src.berat_akhir_kg)) if src.berat_akhir_kg is not None else None
        if 'sisa' in change:
            if src.berat_akhir_kg is None:raise ValueError('Gunakan pemeriksaan sisa silo lama untuk pencatatan sisa pertama.')
            src.berat_akhir_kg=angka(change['sisa'],'Sisa fisik')
        before_basis=D(str(src.berat_kg));new_basis=before_basis+qty-oldkg
        if old_consumed is not None and 'sisa' not in change:src.berat_akhir_kg=new_basis-old_consumed
        if src.berat_akhir_kg is not None and D(str(src.berat_akhir_kg))<0:
            raise ValueError(f'Pemakaian terkonfirmasi {old_consumed} kg melebihi bahan setelah koreksi {new_basis} kg. Perbaiki data terkait.')
        if src.berat_akhir_kg is not None and D(str(src.berat_akhir_kg))>new_basis:raise ValueError(f'Sisa terukur {src.berat_akhir_kg} kg melebihi bahan {new_basis} kg. Perbaiki data terkait.')
        if cancel:
            if len((await db.scalars(select(MillingProcessSource.id).where(MillingProcessSource.milling_process_id==pr.id))).all())<=1:
                raise ValueError('Proses berjalan tidak boleh ditinggalkan tanpa sumber bahan sah.')
            if (src.berat_akhir_kg or 0)>0:raise ValueError('Catatan masih mempunyai sisa fisik. Periksa sumber pengganti dan sisa terkait sebelum membatalkan.')
            await log_activity(db,table_name='milling_process_sources',record_id=src.id,action='UPDATE',changed_by=user.id,
                old_value=json.dumps(buku.bersih(raw(src)),default=str),new_value='dibatalkan; bukti sumber tersimpan pada peristiwa koreksi',alasan=alasan,aksi=JENIS)
            await db.delete(src)
        else:
            src.berat_kg=new_basis
            if src.berat_akhir_kg is not None:
                src.berat_terpakai_kg=new_basis-D(str(src.berat_akhir_kg))
                await alir_sisa_g1(db,st,src,old_remain,D(str(src.berat_akhir_kg)),user,alasan)
            await log_activity(db,table_name='milling_process_sources',record_id=src.id,action='UPDATE',changed_by=user.id,
                field_name='koreksi_bahan_sisa',old_value=json.dumps(buku.bersih(before_src),default=str),new_value=json.dumps(buku.bersih(raw(src)),default=str),alasan=alasan,aksi=JENIS)
            tipe,identitas=newkey.split(':')
            src.purchase_batch_id=int(identitas) if tipe=='batch' else None
            src.drying_lot_id=int(identitas) if tipe=='drying' else None
    if oldkey.startswith('bongkar:'):
        bo=await db.scalar(select(GabahKeringBongkar).where(GabahKeringBongkar.silo_storage_id==st.id))
        if bo is None:raise Konflik('Hubungan bongkar asal tidak ditemukan.')
        before_bo=raw(bo)
        bo.gabah_kering_lot_id=int(newkey.split(':')[1])
        # Nol adalah pembatalan kontribusi, bukan penghapusan lot/timbang asal.
        # Buku saldo lama membaca berat efektif; bukti awal ada pada audit/peristiwa.
        bo.berat_kg=qty
        await log_activity(db,table_name='gabah_kering_bongkar',record_id=bo.id,action='UPDATE',changed_by=user.id,
            old_value=json.dumps(buku.bersih(before_bo),default=str),new_value=json.dumps(buku.bersih(raw(bo)),default=str),alasan=alasan,aksi=JENIS)
    else:
        tipe,identitas=newkey.split(':');st.purchase_batch_id=int(identitas) if tipe=='batch' else None
        st.drying_lot_id=int(identitas) if tipe=='drying' else None
        st.tipe_masuk='langsung_kering' if tipe=='batch' else 'dari_pengeringan'
    if newkey!=oldkey:
        tipe,identitas=newkey.split(':')
        for x in sources:
            if x not in db.deleted:
                x.purchase_batch_id=int(identitas) if tipe=='batch' else None
                x.drying_lot_id=int(identitas) if tipe=='drying' else None
    st.alokasi_koreksi_kg=qty
    if cancel and D(str(st.dikemas_kg or 0))>0:
        raise ValueError(f'Isi silo sudah dikeluarkan {st.dikemas_kg} kg untuk lot gabah kering. Periksa catatan pengeluaran terkait sebelum membatalkan bahan.')
    if not cancel:
        physical=await si._row_bobot(db,st)
        if physical.kg is not None and physical.kg<0:raise ValueError(f'Silo #{st.id}: saldo setelah koreksi {physical.kg} kg tidak sah. Periksa pemakaian dan pengeluaran terkait.')
    if cancel:st.status='batal';st.milling_process_id=None
    await db.flush()
    if pr:
        left=list((await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==pr.id).order_by(MillingProcessSource.id))).all())
        pr.berat_gabah_masuk_kg=None if any(x.berat_kg is None for x in left) else sum(D(str(x.berat_kg)) for x in left)
        if left:
            pr.silo_storage_id=left[0].silo_storage_id;pr.purchase_batch_id=left[0].purchase_batch_id;pr.drying_lot_id=left[0].drying_lot_id
    after_st=raw(st)
    if st.status=='koreksi':after_st['status']=entry['raw']['status']
    if not cancel and before==after_st:raise ValueError('Catatan bahan tidak berubah.')
    await log_activity(db,table_name='silo_storage',record_id=st.id,action='UPDATE',changed_by=user.id,
        old_value=json.dumps(buku.bersih(before),default=str),new_value=json.dumps(buku.bersih(after_st),default=str),alasan=alasan,aksi=JENIS)


async def terapkan(db,*,jenis,kode,user,req):
    before=await konteks(db,jenis=jenis,kode=kode,user=user)
    if before['dasar']!=req['dasar']:raise Konflik('Data/saldo berubah sejak dibaca. Isian dipertahankan; baca data terbaru lalu periksa ulang.')
    pr=await proses(db,jenis,kode)
    if getattr(pr,'catatan',None) is not None:pr=None
    changes=req.get('bahan',[]);entries={x['id']:x for x in before['entries']}
    if len({x['id'] for x in changes})!=len(changes):raise ValueError('Satu catatan bahan tidak boleh dikoreksi dua kali dalam rancangan yang sama.')
    projection=[]
    rencana_sisa=await siapkan_sisa_g2(db,before,entries,changes) if jenis=='sosoh' else {}
    if jenis=='sosoh':
        await anggaran_pk(db,entries,[c for c in changes if isinstance(c['id'],int)])
        await anggaran_curah(db,entries,[c for c in changes if isinstance(c['id'],str) and not entries.get(c['id'],{}).get('alokasi')])
        beras_plans=await rencana_stok_beras(db,entries,[c for c in changes if entries.get(c['id'],{}).get('alokasi')],user,req['alasan'])
    else:
        await anggaran_g1(db,entries,changes)
        # Indeks unik sumber aktif tetap berlaku pada keadaan akhir. Lepaskan
        # sementara indeks dalam transaksi agar pertukaran dua sumber tidak
        # bergantung urutan; status ini tidak pernah dikomit atau ditampilkan.
        for c in changes:
            if c['id'] not in entries:raise ValueError('Catatan bahan bukan bagian proses yang dipilih.')
            row=await db.get(SiloStorage,c['id']);row.status='koreksi'
        await db.flush()
    for c in changes:
        if c['id'] not in entries:raise ValueError('Catatan bahan bukan bagian proses/pelanggan yang dipilih.')
        if jenis=='sosoh':
            if isinstance(c['id'],str):await bahan_curah(db,entries[c['id']],c,pr,user,req['alasan'],stok_plan=beras_plans.get(c['id']))
            else:projection.append(await bahan_g2(db,entries[c['id']],c,pr,user,req['alasan'],gabungan=True))
        else:await bahan_g1(db,entries[c['id']],c,pr,user,req['alasan'],gabungan=True)
    if jenis=='sosoh':await terapkan_sisa_g2(db,rencana_sisa,user,req['alasan'])
    if jenis=='giling':
        for c in changes:
            row=await db.get(SiloStorage,c['id'])
            if row.status=='koreksi':row.status=entries[c['id']]['raw']['status']
        await db.flush()
    if pr is None and req.get('hasil'):raise ValueError('Catatan belum terkait proses tidak menerima koreksi hasil produksi.')
    await hasil_berjalan(db,jenis,pr,req.get('hasil',{}),user,req['alasan'])
    await db.flush()
    if pr is None and any(c.get('hapus') for c in changes):
        after={**before,'entries':[]}
        after['sources']=[await (g2_sumber(db,await db.get(PkGudang2Intake,int(x['key']))) if jenis=='sosoh' and x['key'].isdigit() else sumber_curah(db,x['key']) if jenis=='sosoh' else g1_sumber(db,x['key'])) for x in before['sources']]
    else:after=await konteks(db,jenis=jenis,kode=kode,user=user)
    if changes and not any(c.get('hapus') for c in changes) and not req.get('hasil') and before['dasar']==after.get('dasar'):raise ValueError('Tidak ada perubahan bahan atau sisa yang diminta.')
    if pr is None:balance=dict(bahan=None,hasil=None,rendemen=None)
    elif jenis=='sosoh':
        if after['basis'] is not None and after['basis']<=0:raise ValueError('Proses berjalan harus tetap mempunyai sumber bahan yang sah.')
        # Neraca aktif menggunakan fungsi lama, tidak mengambil toleransi mockup.
        # Penolakan akhir tidak dipasang menjadi syarat baru pencatatan aktif.
        balance=dict(bahan=after['basis'],hasil=sum(after['outputs'].values()),rendemen=p.rendemen(p.beras_dari_output(after['outputs']),after['basis']) if after['basis'] is not None else None)
    else:
        balance=dict(bahan=after['basis'],hasil=after['outputs']['pk'],rendemen=m.hitung_rendemen(after['outputs']['pk'],after['basis']))
        if pr.jasa_id is not None and pr.bobot_masuk_final and after['outputs']['pk'] is not None and after['basis'] is not None and after['outputs']['pk']>after['basis']:
            raise ValueError('Hasil PK jasa melebihi bahan final setelah koreksi. Perbaiki data terkait sebagai satu rancangan.')
    if not changes and not req.get('hasil'):raise ValueError('Tidak ada perubahan yang diminta.')
    if pr and changes:
        changed={pr.id}
        before_related={x['siklus']['id']:x for x in before['terkait']}
        for x in after['terkait']:
            if before_related.get(x['siklus']['id'])!=x:changed.add(x['proses']['id'])
        await sinkron_bahan(db,jenis,changed)
    if jenis=='sosoh':
        for sid in sorted({entries[c['id']]['silo_id'] for c in changes}):await g2.segarkan_status_silo(db,sid)
    return dict(sebelum=before,sesudah=after,neraca=balance,proyeksi=projection)


async def kunci(db,jenis,kode,user):
    await izin(db,user,jenis)
    from app.services.barang_keluar import _kunci_saldo_keluar
    await _kunci_saldo_keluar(db)
    # Urutan konsisten: sumber tumpukan → silo → proses. Pembaca pratinjau
    # di bawah dijalankan lagi SETELAH seluruh kunci didapat.
    for model in (PurchaseBatch,DryingLot,GabahKeringLot,PkPurchaseBatch,PkGudang2Intake):
        # Batasi ke pemilik proses; semua sumber alternatif yang boleh dipilih
        # ikut dikunci agar dua penggantian tak memakai saldo bebas yang sama.
        pr=await proses(db,jenis,kode)
        q=select(model).where(model.jasa_id==pr.jasa_id).order_by(model.id)
        await db.scalars(q.with_for_update().execution_options(populate_existing=True))
    pr=await proses(db,jenis,kode)
    ctx=await konteks(db,jenis=jenis,kode=kode,user=user)
    for id_ in sorted({x['silo_id'] for x in ctx['entries']}):
        await db.scalar(select(Silo).where(Silo.id==id_).with_for_update())
    await proses(db,jenis,kode,kunci=True)
    ids=[e['id'] for e in ctx['entries'] if isinstance(e['id'],int)]
    if jenis=='sosoh':
        for model in (BrokenKeSilo,BerasKeSilo,HasilSampingKeSilo):
            list((await db.scalars(select(model).where(model.silo_id.in_([x['silo_id'] for x in ctx['entries']])).order_by(model.id).with_for_update())).all())
    model=SiloStorage if jenis=='giling' else PkTumpukanToSilo
    list((await db.scalars(select(model).where(model.id.in_(ids)).order_by(model.id).with_for_update().execution_options(populate_existing=True))).all())
    return await proses(db,jenis,kode,kunci=True)


def tanda(jenis,kode,user,req):
    from app.web.security import _kunci
    return hmac.new(_kunci(),json.dumps([jenis,kode,user.id,isi(req)],sort_keys=True,default=str).encode(),hashlib.sha256).hexdigest()


def isi(req):
    if not isinstance(req.get('alasan'),str) or not req['alasan'].strip():raise ValueError('Alasan koreksi/penghapusan wajib diisi; spasi tidak cukup.')
    if len(req['alasan'])>2000:raise ValueError('Alasan maksimal 2.000 karakter.')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}',req.get('kunci','')):raise ValueError('Identitas kiriman tidak sah.')
    return {k:v for k,v in req.items() if k not in ('pemeriksaan','konfirmasi')}


async def periksa(db,*,jenis,kode,user,req):
    isi(req);await kunci(db,jenis,kode,user)
    sp=await db.begin_nested()
    try:result=await terapkan(db,jenis=jenis,kode=kode,user=user,req=req)
    finally:await sp.rollback()
    # Acuan rencana tidak memuat ID/time hasil INSERT simulasi.
    result['pemeriksaan']=tanda(jenis,kode,user,req)
    return buku.bersih(result)


async def simpan(db,*,jenis,kode,user,req):
    clean=isi(req);await izin(db,user,jenis)
    key=f'{JENIS}:{user.id}:{req["kunci"]}'
    from app.services.barang_keluar import _kunci_saldo_keluar
    await _kunci_saldo_keluar(db)
    old=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==key))
    if old:
        if old.muatan.get('isian')!=buku.bersih([jenis,kode,clean]):raise Konflik('Kunci kiriman sudah dipakai untuk rancangan berbeda. Periksa catatan tersimpan.')
        return dict(sudah_tercatat=True,peristiwa_id=old.id,hasil=old.muatan['hasil'])
    await kunci(db,jenis,kode,user)
    if req.get('konfirmasi') is not True or not hmac.compare_digest(req.get('pemeriksaan',''),tanda(jenis,kode,user,req)):raise ValueError('Periksa dampak terbaru dan konfirmasikan sebelum menyimpan.')
    result=await terapkan(db,jenis=jenis,kode=kode,user=user,req=req)
    event=await buku.catat(db,jenis=JENIS,pelaku_id=user.id,kunci_kiriman=key,
        muatan=dict(isian=[jenis,kode,clean],hasil=result),terapkan=False)
    # Proyeksi pemindahan memakai peristiwa koreksi ini juga saat replay.
    await buku.terapkan_ke_proyeksi(db,event)
    await db.flush()
    return dict(sudah_tercatat=False,peristiwa_id=event.id,hasil=buku.bersih(result))


async def siklus_terkait(db,jenis,silo_ids):
    """Snapshot seluruh siklus yang benar-benar mungkin membawa sisa bahan."""
    if not silo_ids:return []
    if jenis=='sosoh':
        q=select(PolishingSiloUsage,PolishingProcess).join(PolishingProcess).where(PolishingSiloUsage.silo_id.in_(silo_ids)).order_by(PolishingSiloUsage.id)
    else:
        q=select(MillingProcessSource,MillingProcess).join(MillingProcess).join(SiloStorage,SiloStorage.id==MillingProcessSource.silo_storage_id).where(SiloStorage.silo_id.in_(silo_ids)).order_by(MillingProcessSource.id)
    return [dict(siklus=raw(u),proses=raw(pr)) for u,pr in (await db.execute(q)).all()]


async def alir_sisa_g2(db,usage,sebelum,sesudah,user,alasan):
    if sebelum is None or sesudah==sebelum:return
    delta=sesudah-sebelum
    rows=(await db.execute(select(PolishingSiloUsage,PolishingProcess).join(PolishingProcess).where(PolishingSiloUsage.silo_id==usage.silo_id,PolishingSiloUsage.id>usage.id).order_by(PolishingSiloUsage.id).with_for_update(of=PolishingSiloUsage))).all()
    for nxt,pr in rows:
        if pr.status!='proses':raise ValueError(f'Sisa dipakai {pr.kode_proses} ({pr.status}), siklus #{nxt.id}. Periksa /riwayat-sosoh/{pr.id}; proses selesai tidak diubah otomatis.')
        before=raw(nxt);consumed=D(str(nxt.berat_terpakai_kg)) if nxt.berat_akhir_kg is not None else None
        nxt.awal_tetap_kg=D(str(nxt.awal_tetap_kg))+delta
        if nxt.berat_awal_kg<0:raise ValueError(f'Perubahan sisa membuat bahan siklus #{nxt.id} pada {pr.kode_proses} negatif. Perbaiki data terkait.')
        if consumed is not None:
            tail=D(str(nxt.berat_akhir_kg))+delta
            if tail<0:raise ValueError(f'{pr.kode_proses} siklus #{nxt.id} sudah memakai {consumed} kg; sisa setelah koreksi {tail} kg tidak sah.')
            nxt.berat_akhir_kg=tail;nxt.terpakai_lama_kg=consumed
        await log_activity(db,table_name='polishing_silo_usage',record_id=nxt.id,action='UPDATE',changed_by=user.id,field_name='koreksi_sisa_siklus_sebelumnya',
            old_value=json.dumps(buku.bersih(before),default=str),new_value=json.dumps(buku.bersih(raw(nxt)),default=str),alasan=alasan,aksi=JENIS)
        if consumed is None:break


async def alir_sisa_g1(db,st,src,sebelum,sesudah,user,alasan):
    if sebelum is None or sebelum==sesudah:return
    delta=sesudah-sebelum
    rows=(await db.execute(select(MillingProcessSource,MillingProcess).join(MillingProcess).where(MillingProcessSource.silo_storage_id==st.id,MillingProcessSource.id>src.id).order_by(MillingProcessSource.id).with_for_update(of=MillingProcessSource))).all()
    for nxt,pr in rows:
        if pr.status!='proses':raise ValueError(f'Sisa dipakai {pr.kode_proses} ({pr.status}), siklus #{nxt.id}. Periksa /riwayat-giling/{pr.id}.')
        before=raw(nxt)
        if nxt.berat_kg is None:raise ValueError(f'Bobot siklus #{nxt.id} belum tersedia; periksa sumber sebelum koreksi lintas siklus.')
        nxt.berat_kg=D(str(nxt.berat_kg))+delta
        if nxt.berat_kg<=0:raise ValueError(f'Bahan {pr.kode_proses} setelah koreksi tidak sah. Periksa pemakaian berikutnya.')
        if nxt.berat_akhir_kg is not None:
            tail=D(str(nxt.berat_akhir_kg))+delta
            if tail<0:raise ValueError(f'Pemakaian {pr.kode_proses} sudah melebihi sisa terkoreksi. Periksa siklus #{nxt.id}.')
            nxt.berat_akhir_kg=tail
        else:
            # Masih terikat: basis/rendemen sementara berubah, status mesin tetap.
            pass
        await db.flush()
        others=(await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==pr.id))).all()
        pr.berat_gabah_masuk_kg=None if any(x.berat_kg is None for x in others) else sum(D(str(x.berat_kg)) for x in others)
        await log_activity(db,table_name='milling_process_sources',record_id=nxt.id,action='UPDATE',changed_by=user.id,field_name='koreksi_sisa_siklus_sebelumnya',
            old_value=json.dumps(buku.bersih(before),default=str),new_value=json.dumps(buku.bersih(raw(nxt)),default=str),alasan=alasan,aksi=JENIS)
        if nxt.berat_akhir_kg is None:break


async def sumber_bebas_g1(db,*,jasa=False,pelanggan_id=None):
    """Saldo sumber yang dilepas oleh koreksi alokasi, bukan stok masuk baru.

    Hanya sumber dengan jejak koreksi yang diperiksa. Tidak menyusun ulang
    seluruh penerimaan historis atau menggandakan tumpukan gabah kering.
    """
    rows=(await db.scalars(select(SiloStorage).where(SiloStorage.alokasi_koreksi_kg.is_not(None)))).all()
    keys={g1_key(r) for r in rows if r.purchase_batch_id or r.drying_lot_id}
    events=(await db.scalars(select(Peristiwa).where(Peristiwa.jenis==JENIS,Peristiwa.muatan['isian'][0].as_string()=='giling'))).all()
    for e in events:
        keys.update(x['sumber'] for x in e.muatan['hasil']['sebelum']['entries'] if x['sumber'].startswith(('batch:','drying:')))
    result=[]
    from app.services.jasa import nama_pemilik
    for key in sorted(keys):
        src=await g1_sumber(db,key)
        if bool(src['pemilik'])!=jasa or src['bebas'] is None or src['bebas']<=0:continue
        if pelanggan_id is not None:
            from app.models import Jasa
            order=await db.get(Jasa,src['pemilik']) if src['pemilik'] else None
            if order is None or order.pelanggan_id!=pelanggan_id:continue
        src['nama_pemilik']=await nama_pemilik(db,src['pemilik']) if src['pemilik'] else 'Milik pabrik'
        result.append(src)
    return result


async def sinkron_bahan(db,jenis,ids):
    """Pakai adaptor ProsesTerpadu lama; jangan menutup/verifikasi proses."""
    from app.services.proses_bersama import perbarui_bahan_proses_bersama
    from hmu_core import ArusProses
    from hmu_core.komoditas import buat_produk
    for pid in sorted(ids):
        if jenis=='giling':
            rows=(await db.execute(select(MillingProcessSource,SiloStorage).join(SiloStorage,SiloStorage.id==MillingProcessSource.silo_storage_id).where(MillingProcessSource.milling_process_id==pid).order_by(MillingProcessSource.id))).all()
            bahan=tuple(ArusProses(produk=buat_produk('gabah',kondisi='kering'),berat_kg=D(str(src.berat_terpakai_kg if src.berat_akhir_kg is not None else src.berat_kg)),referensi=f'SiloStorage:{st.id}',lokasi_id=st.silo_id) for src,st in rows if src.berat_kg is not None and src.berat_kg>0)
            await perbarui_bahan_proses_bersama(db,tabel_sumber='milling_process',id_sumber=pid,bahan=bahan)
        else:
            proc=await db.get(PolishingProcess,pid)
            rows=(await db.execute(select(PolishingSiloUsage,Silo).join(Silo).where(PolishingSiloUsage.polishing_process_id==pid).order_by(PolishingSiloUsage.id))).all()
            bahan=[];kelompok={};rincian={}
            for u,silo in rows:
                # Sisa yang dipakai ulang bukan bahan baru. Kelompokkan satu
                # silo memakai basis operasional yang sama dengan detail.
                total=float(u.berat_terpakai_kg) if u.berat_akhir_kg is not None else float(u.berat_awal_kg)+float(u.berat_masuk_kg)
                kelompok[silo.id]=(silo,kelompok.get(silo.id,(None,0))[1]+total)
            for silo,total in kelompok.values():
                comp=await g2.komposisi_bahan_silo(db,silo.id,sampai=proc.waktu_selesai or now_local(),kecuali_proses_id=pid,target_kg=total)
                rincian[silo.nama_silo]=comp
                bahan.extend(p._arus_dari_komposisi(silo,comp))
            row=await perbarui_bahan_proses_bersama(db,tabel_sumber='polishing_process',id_sumber=pid,bahan=tuple(bahan))
            if row is not None:row.metadata_domain={**(row.metadata_domain or {}),'komposisi_bahan':rincian}


async def anggaran_pk(db,entries,changes):
    """Validasi saldo akhir seluruh rancangan sebelum mutasi per catatan.

    Jumlah lama hanya dikreditkan untuk catatan yang benar-benar dipilih.
    Alokasi retur dan pemakaian catatan lain tetap dikurangkan pembaca lama.
    """
    budget={}; bags={}
    async def init(key):
        if key not in budget:
            src=await g2_sumber(db,await db.get(PkGudang2Intake,int(key)))
            if src['bebas'] is None:raise ValueError('Saldo sumber belum tersedia.')
            budget[key]=D(str(src['bebas']));bags[key]=src['karung']
        return await g2_sumber(db,await db.get(PkGudang2Intake,int(key)))
    for c in changes:
        e=entries.get(c['id'])
        if not e:raise ValueError('Catatan bukan bagian proses yang dipilih.')
        await init(e['sumber'])
        if e['kg'] is None:raise ValueError('Bobot catatan sebelumnya belum tersedia.')
        budget[e['sumber']]+=D(str(e['kg']))
        if e['satuan']=='karung':bags[e['sumber']]+=int(e['jumlah'])
    for c in changes:
        if c.get('hapus'):continue
        key=c['sumber'];src=await init(key)
        qty=angka(c.get('jumlah'),'Jumlah bahan',nol=False)
        if src['satuan']=='karung':
            if qty!=qty.to_integral_value():raise ValueError('Jumlah karung harus bulat.')
            it=await db.get(PkGudang2Intake,int(key))
            from app.penggilingan.gudang2.karung import bobot_per_karung
            weight=bobot_per_karung(await db.get(PkPurchaseBatch,it.pk_purchase_batch_id),jumlah=int(qty))
            if weight is None:raise ValueError('Bobot per karung belum tersedia.')
            bags[key]-=int(qty)
        else:weight=qty
        budget[key]-=weight
    for key,remaining in budget.items():
        if remaining < D('-.000001') or bags[key] is not None and bags[key]<0:
            raise ValueError(f'Sumber #{key}: saldo akhir rancangan {remaining} kg, karung {bags[key]}. Alokasi/pemakaian lain tetap dilindungi.')


async def anggaran_g1(db,entries,changes):
    """Saldo rancangan akhir lintas sumber, memakai alokasi/reservasi lama."""
    saldo={}
    for c in changes:
        if c['id'] not in entries:raise ValueError('Catatan bahan bukan bagian proses yang dipilih.')
        e=entries[c['id']];old=e['sumber'];new=c.get('sumber',old)
        for key in (old,new):
            if key not in saldo:
                src=await g1_sumber(db,key)
                if src['bebas'] is None:raise ValueError('Bobot sumber belum tersedia; periksa timbang asal.')
                saldo[key]=D(str(src['bebas']))
        saldo[old]+=angka(e['kg'],'Bobot sebelum koreksi')
        if not c.get('hapus'):saldo[new]-=angka(c.get('jumlah'),'Bobot bahan',nol=False)
    for key,value in saldo.items():
        if value < D('-.000001'):
            src=await g1_sumber(db,key)
            raise ValueError(f"{src['kode']}: kekurangan {abs(value)} kg pada rancangan bersama. Alokasi transaksi lain tidak boleh dipakai.")


_CURAH={'broken':BrokenKeSilo,'samping':HasilSampingKeSilo,'beras':BerasKeSilo}

async def sumber_curah(db,key):
    """Saldo sumber efektif dari pembaca operasional yang sama dengan input."""
    parts=key.split(':');tipe=parts[0];ident=int(parts[-1])
    if tipe=='berasstok':return await sumber_beras_stok(db,key)
    if tipe=='broken':
        row=await db.get(ByproductStock,ident,populate_existing=True)
        if not row or row.jenis_produk!='broken':
            raise ValueError('Sumber broken harus stok curah sah; karung mengikuti alur kemasan asal.')
        from app.services.retur_supplier_reservasi import terikat
        free=D(str(await g2._sisa_broken_row(db,row.id)))-await terikat(db,sumber=f'broken:{row.id}')
        return dict(key=key,kode=f'Broken #{row.id}',pemilik=row.jasa_id,kg=float(row.berat_kg),bebas=float(free),satuan='kg',karung=None,rasio=None,final=True,raw=raw(row),jenis='broken',proses_id=row.source_id if row.source_type=='polishing' else None)
    grade=parts[1];proc=await db.get(PolishingProcess,ident,populate_existing=True)
    if not proc:raise ValueError('Proses sumber bahan tidak ditemukan.')
    if tipe=='samping':
        from app.penggilingan.gudang2.rencana_hasil_samping import saldo_sumber
        data=await saldo_sumber(db,grade,proc.jasa_id)
        free=next((kg for p_,kg in data['candidates'] if p_.id==ident),0)
        from app.services.stok import output_sosoh
        original=(await output_sosoh(db,ident)).get(grade)
    elif tipe=='beras':
        from app.penggilingan.gudang2.rencana_beras import curah_beras_sumber
        free=None
        async for p_,kg in curah_beras_sumber(db,grade,proc.jasa_id):
            if p_.id==ident:free=kg;break
        original=(await p._output_map(db,ident)).get(grade)
    else:raise ValueError('Jenis sumber bahan tidak dikenal.')
    return dict(key=key,kode=proc.kode_proses+' · '+grade,pemilik=proc.jasa_id,kg=original,bebas=free,satuan='kg',karung=None,rasio=None,final=True,raw=raw(proc),jenis=grade,proses_id=ident)


def key_curah(move,tipe):
    if tipe=='broken':return f'broken:{move.byproduct_stock_id}'
    return f'{tipe}:{move.jenis}:{move.polishing_process_id}'


async def konteks_curah(db,pr,usages,*,catatan=None):
    entries=[];sources={}
    for tipe,model in _CURAH.items():
        if catatan is not None:rows=[catatan] if isinstance(catatan,model) else []
        else:rows=(await db.scalars(select(model).where(model.silo_id.in_([u.silo_id for u in usages])).order_by(model.id))).all()
        for move in rows:
            usage=await siklus_g2(db,move)
            if catatan is None and (usage is None or usage.polishing_process_id!=pr.id):continue
            silo=await db.get(Silo,move.silo_id)
            # Kemasan beras harus membawa snapshot pembongkaran sebenarnya;
            # jangan menganggapnya curah atau memulihkan kilogram fiktif.
            allocation=None
            if tipe=='beras' and move.product_sku_id is not None:
                allocation=await asal_beras_stok(db,move)
                key=f'berasstok:{move.jenis}:{allocation["id"]}'
                src=await sumber_beras_stok(db,key,asli=allocation)
            else:
                key=key_curah(move,tipe);src=await sumber_curah(db,key)
            sources[key]=src
            entries.append(dict(id=f'{tipe}:{move.id}',kode=move.kode_pindah,silo=silo.nama_silo,silo_id=silo.id,siklus=usage.id if usage else None,sumber=key,kg=float(move.berat_kg),jumlah=float(move.berat_kg),satuan='karung' if allocation and allocation['jumlah_karung'] else 'kg',sisa=usage.berat_akhir_kg if usage else move.berat_kg,raw=raw(move),tipe=tipe,alokasi=allocation))
            if allocation:
                entries[-1]['jumlah']=allocation['jumlah_karung'] if allocation['jumlah_karung'] else float(move.berat_kg)
                for stock in (await db.scalars(select(FinishedGoodsStock).where(FinishedGoodsStock.jasa_id==pr.jasa_id,FinishedGoodsStock.product_sku_id.in_(select(ProductSku.id).where(ProductSku.kategori==('beras_b' if move.jenis=='beras_b' else 'beras_putih'))),FinishedGoodsStock.rice_quality_standard_id==allocation.get('rice_quality_standard_id')))).all():
                    candidate=f'berasstok:{move.jenis}:{stock.id}'
                    source=await sumber_beras_stok(db,candidate)
                    if source['bebas']>0:sources[candidate]=source
                continue
            if tipe=='broken':
                keys=[f'broken:{x.id}' for x in (await db.scalars(select(ByproductStock).where(ByproductStock.jenis_produk=='broken',ByproductStock.jasa_id==pr.jasa_id))).all()]
            else:
                keys=[f'{tipe}:{move.jenis}:{x.id}' for x in (await db.scalars(select(PolishingProcess).where(PolishingProcess.jasa_id==pr.jasa_id,PolishingProcess.id!=pr.id))).all()]
            for candidate in keys:
                source=await sumber_curah(db,candidate)
                if source['bebas'] is not None and source['bebas']>0:sources[candidate]=source
    return entries,sources


async def anggaran_curah(db,entries,changes):
    balances={}
    for c in changes:
        e=entries.get(c['id'])
        if not e:raise ValueError('Bahan bukan bagian proses yang dipilih.')
        target=c.get('sumber',e['sumber'])
        if target.split(':')[0]!=e['tipe']:raise ValueError('Jenis sumber pengganti tidak sesuai bahan asal.')
        if e['tipe']!='broken' and target.split(':')[1]!=e['sumber'].split(':')[1]:raise ValueError('Grade/jenis bahan pengganti tidak sesuai.')
        for key in (e['sumber'],target):
            if key not in balances:
                src=await sumber_curah(db,key)
                if src['bebas'] is None:raise ValueError('Saldo sumber bahan belum diketahui.')
                balances[key]=D(str(src['bebas']))
        balances[e['sumber']]+=D(str(e['kg']))
        if not c.get('hapus'):balances[target]-=angka(c.get('jumlah'),'Jumlah bahan',nol=False,presisi=2)
    for key,kg in balances.items():
        if kg<D('-.000001'):raise ValueError(f'Sumber {key} kekurangan {abs(kg)} kg setelah seluruh koreksi. Periksa pengiriman, alokasi, dan pemakaian terkait.')


async def bahan_curah(db,entry,change,pr,user,alasan,*,stok_plan=None):
    tipe=entry['tipe'];model=_CURAH[tipe]
    move=await db.get(model,int(entry['id'].split(':')[1]),populate_existing=True)
    if not move or move.dibatalkan_pada:raise Konflik('Catatan bahan sudah dibatalkan.')
    usage=await siklus_g2(db,move)
    if (pr is not None and (not usage or usage.polishing_process_id!=pr.id)) or (pr is None and usage):raise Konflik('Hubungan siklus bahan berubah.')
    if usage is None and 'sisa' in change:raise ValueError('Sisa terukur pertama melalui pemeriksaan silo, bukan koreksi bahan belum dipakai.')
    before=raw(move);ubefore=raw(usage) if usage else None
    source=stok_plan['source'] if stok_plan else await sumber_curah(db,change.get('sumber',entry['sumber']))
    if source['pemilik']!=move.jasa_id or (pr is not None and source['pemilik']!=pr.jasa_id):raise ValueError('Pemilik sumber pengganti tidak sesuai proses.')
    if pr is not None and source['proses_id']==pr.id:raise ValueError('Proses tidak boleh menggunakan hasilnya sendiri sebagai bahan.')
    silo=await db.get(Silo,move.silo_id)
    if not silo or not silo.aktif or silo.warehouse_id!=await g2._g2_warehouse_id(db):raise ValueError('Silo/gudang tujuan tidak lagi sah.')
    g2._pastikan_komoditas_silo(silo,'broken' if tipe=='broken' else 'beras_putih' if tipe=='beras' else source['jenis'])
    old=D(str(move.berat_kg));qty=D(str(stok_plan['kg'])) if stok_plan else D(0) if change.get('hapus') else angka(change.get('jumlah'),'Jumlah bahan',nol=False,presisi=2)
    if usage:
        col='awal_tetap_kg' if move.waktu<=pr.waktu_mulai else 'masuk_tetap_kg'
        setattr(usage,col,D(str(getattr(usage,col) or 0))+qty-old)
    if change.get('hapus'):move.dibatalkan_pada=now_local()
    else:
        ident=int(source['key'].split(':')[-1])
        if stok_plan:
            stock=stok_plan['allocation'];move.sumber_koreksi_json=json.dumps(buku.bersih(stock),default=str)
            move.source_type=stock['source_type'];move.source_id=stock['source_id'];move.product_sku_id=stock['product_sku_id']
            move.polishing_process_id=stock['source_id'] if stock['source_type']=='polishing' else None
        elif tipe=='broken':move.byproduct_stock_id=ident
        else:
            move.polishing_process_id=ident
            if tipe=='beras':move.source_id=ident
        move.berat_kg=qty
    if before==raw(move) and (usage is None or ubefore==raw(usage)) and 'sisa' not in change:raise ValueError('Catatan bahan tidak berubah.')
    for row,oldrow in ((move,before),):
        if row is None:continue
        await log_activity(db,table_name=row.__tablename__,record_id=row.id,action='UPDATE',changed_by=user.id,field_name='koreksi_bahan_sisa',old_value=json.dumps(buku.bersih(oldrow),default=str),new_value=json.dumps(buku.bersih(raw(row)),default=str),alasan=alasan,aksi=JENIS)
    await db.flush()


async def asal_beras_stok(db,move):
    """Hubungan stok yang benar dari cuplikan INSERT, bukan kemiripan nama."""
    if move.sumber_koreksi_json:return json.loads(move.sumber_koreksi_json)
    from app.models import ActivityLog
    logs=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='beras_ke_silo',ActivityLog.aksi=='beras_masuk_silo',ActivityLog.action=='INSERT',ActivityLog.record_id<=move.id).order_by(ActivityLog.id.desc()))).all()
    for log in logs:
        try:data=json.loads(log.old_value or '{}')
        except (TypeError,ValueError):continue
        if move.id not in data.get('moves',[]):continue
        moves=(await db.scalars(select(BerasKeSilo).where(BerasKeSilo.id.in_(data['moves'])).order_by(BerasKeSilo.id).execution_options(termasuk_dibatalkan=True))).all()
        # Writer lama menulis satu move per baris stok dalam urutan FIFO,
        # setelah move curah tak tercatat. Tidak mengalokasikan kg proporsional.
        stock_moves=[x for x in moves if x.product_sku_id is not None]
        stocks=data.get('stok',[])
        if len(stock_moves)!=len(stocks):raise ValueError('Cuplikan pembongkaran lama tidak lengkap; koreksi perlu penelusuran sumber, bukan perkiraan.')
        for row,stock in zip(stock_moves,stocks):
            if row.id!=move.id:continue
            if any(getattr(move,k)!=stock.get(k) for k in ('source_type','source_id','product_sku_id','jasa_id')):raise ValueError('Identitas cuplikan stok tidak sesuai catatan bahan.')
            if D(str(stock.get('berat_total_kg')))!=D(str(move.berat_kg)):raise ValueError('Bobot catatan berbeda dari cuplikan stok; telusuri koreksi historis terlebih dahulu.')
            return stock
    raise ValueError('Cuplikan sumber pembongkaran beras belum tersedia. Stok tidak dipulihkan berdasarkan tebakan.')


async def sumber_beras_stok(db,key,*,asli=None):
    _,grade,ident=key.split(':');rid=int(ident)
    row=await db.get(FinishedGoodsStock,rid,populate_existing=True)
    if row is None and asli is None:raise ValueError('Stok sumber tidak ditemukan; baca ulang catatan dan cuplikannya.')
    snapshot=raw(row) if row else dict(asli)
    if row and asli:
        for k in ('source_type','source_id','product_sku_id','jasa_id','warehouse_id','rice_quality_standard_id','curah_kemas_ulang','kemasan_mengurangi_stok'):
            if getattr(row,k)!=asli.get(k,False if k=='curah_kemas_ulang' else None):raise Konflik('ID stok kini menunjuk sumber berbeda. Pemulihan otomatis ditahan.')
    sku=await db.get(ProductSku,snapshot['product_sku_id'])
    from app.penggilingan.inventory.finished_goods import get_standard
    std=await get_standard(db,grade)
    if not sku or sku.kategori!=('beras_b' if grade=='beras_b' else 'beras_putih') or snapshot.get('rice_quality_standard_id')!=(std.id if std else None):raise ValueError('Grade dan produk stok pengganti tidak sesuai.')
    if snapshot['warehouse_id']!=await g2._g2_warehouse_id(db):raise ValueError('Stok sumber berada di luar Gudang 2.')
    from app.services.retur_supplier_reservasi import terikat
    if row and not row.curah_kemas_ulang:
        from app.penggilingan.gudang2.rencana_beras import sumber_karung_beras
        rows,_=await sumber_karung_beras(db,row.product_sku_id,row.rice_quality_standard_id,row.jasa_id)
        n,free=next(((n,kg) for stock,n,kg in rows if stock.id==rid),(0,0))
    elif row:
        n=0;free=D(str(row.berat_total_kg))-D(str(row.retur_supplier_keluar_kg))-await terikat(db,sumber=f'beras:{rid}')
    else:n=0;free=0
    bags=bool(asli['jumlah_karung'] if asli else not snapshot.get('curah_kemas_ulang',False))
    from app.services.rencana_beras_silo import identitas
    origin=await identitas(db,snapshot['source_id'] if snapshot['source_type']=='polishing' else None,snapshot['source_type'],snapshot['source_id'],rid)
    return dict(key=key,kode=origin['kode']+f' · stok #{rid} · {grade}',pemilik=snapshot['jasa_id'],kg=float(row.berat_total_kg) if row else 0,bebas=float(free),satuan='karung' if bags else 'kg',karung=n if bags else None,rasio=None,final=True,raw=snapshot,jenis=grade,proses_id=snapshot['source_id'] if snapshot['source_type']=='polishing' else None)


async def rencana_stok_beras(db,entries,changes,user,alasan):
    """Pulihkan kontribusi terpilih lalu ambil jumlah benar, satu transaksi.

    Bukan penerimaan baru: baris sumber dan berat nyatanya dikembalikan tepat
    sejumlah kontribusi lama. Savepoint/transaction pemanggil melindungi semua.
    """
    plans={};before={}
    from datetime import datetime
    for c in changes:
        e=entries[c['id']];old=e['alokasi'];rid=old['id']
        row=await db.get(FinishedGoodsStock,rid,populate_existing=True)
        # Pembacaan ini juga memeriksa identitas, gudang, dan penggunaan ID.
        await sumber_beras_stok(db,e['sumber'],asli=old)
        if rid not in before:before[rid]=raw(row) if row else None
        if row is None:
            data={k:v for k,v in old.items() if k in FinishedGoodsStock.__table__.columns.keys()}
            data['waktu']=datetime.fromisoformat(data['waktu']) if isinstance(data['waktu'],str) else data['waktu']
            data['jumlah_karung']=0;data['berat_total_kg']=0
            row=FinishedGoodsStock(**data);db.add(row)
        row.jumlah_karung+=int(old['jumlah_karung']);row.berat_total_kg=D(str(row.berat_total_kg))+D(str(old['berat_total_kg']))
    await db.flush()
    for c in changes:
        e=entries[c['id']]
        if c.get('hapus'):
            plans[c['id']]={'source':await sumber_beras_stok(db,e['sumber']),'kg':0,'allocation':None};continue
        key=c.get('sumber',e['sumber'])
        if not key.startswith('berasstok:'+e['sumber'].split(':')[1]+':'):raise ValueError('Sumber pengganti harus stok beras dengan grade yang sama.')
        source=await sumber_beras_stok(db,key);row=await db.get(FinishedGoodsStock,int(key.split(':')[-1]))
        old=e['alokasi']
        if row.jasa_id!=old['jasa_id']:raise ValueError('Pemilik sumber pengganti harus sama.')
        qty=angka(c.get('jumlah'),'Jumlah bahan',nol=False,presisi=2)
        if source['satuan']=='karung':
            if qty!=qty.to_integral_value():raise ValueError('Jumlah karung harus bilangan bulat.')
            if qty>source['karung']:raise ValueError(f"Stok #{row.id} hanya menyediakan {source['karung']} karung setelah pemulihan catatan terpilih.")
            from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
            kg=berat_karung_nyata(row,int(qty));n=int(qty)
        else:kg=qty;n=0
        if kg>D(str(source['bebas']))+D('.000001'):raise ValueError(f"Stok #{row.id}: {kg} kg melebihi saldo bebas {source['bebas']} kg. Alokasi lain tetap dipertahankan.")
        if row.id not in before:before[row.id]=raw(row)
        allocation=raw(row);allocation['jumlah_karung']=n;allocation['berat_total_kg']=kg
        row.jumlah_karung-=n;row.berat_total_kg=D(str(row.berat_total_kg))-kg
        plans[c['id']]=dict(source=source,kg=kg,allocation=allocation)
        await db.flush()
    for rid,old in before.items():
        row=await db.get(FinishedGoodsStock,rid)
        await db.refresh(row)
        await log_activity(db,table_name='finished_goods_stock',record_id=rid,action='UPDATE',changed_by=user.id,old_value=json.dumps(buku.bersih(old),default=str),new_value=json.dumps(buku.bersih(raw(row)),default=str),alasan=alasan,aksi=JENIS)
    return plans


async def siapkan_sisa_g2(db,before,entries,changes):
    plans={}
    for c in changes:
        e=entries.get(c['id'])
        if e is None:raise ValueError('Bahan bukan bagian proses yang dipilih.')
        uid=e.get('siklus')
        if uid is None:
            if 'sisa' in c:raise ValueError('Sisa pertama tetap melalui pemeriksaan silo yang sah.')
            continue
        if uid not in plans:
            usage=await db.get(PolishingSiloUsage,uid,populate_existing=True)
            for rel in before.get('terkait',[]):
                if rel['siklus']['silo_id']==usage.silo_id and rel['siklus']['id']>uid and rel['proses']['status']!='proses':
                    raise ValueError(f"Silo sudah dipakai proses {rel['proses']['kode_proses']} ({rel['proses']['status']}). Koreksi proses selesai harus melalui mekanisme terkait, bukan mengubah sumber historis diam-diam.")
            plans[uid]=dict(usage=usage,sebelum=raw(usage),terpakai=D(str(usage.berat_terpakai_kg)) if usage.berat_akhir_kg is not None else None)
        if 'sisa' in c:
            plan=plans[uid]
            if plan['sebelum']['berat_akhir_kg'] is None:raise ValueError('Sisa pertama tetap melalui Periksa sisa & bebaskan.')
            target=angka(c['sisa'],'Sisa yang benar',presisi=2)
            if 'target' in plan and plan['target']!=target:raise ValueError('Satu siklus memiliki dua koreksi sisa yang berbeda. Periksa kembali rancangan.')
            plan['target']=target
    return plans


async def terapkan_sisa_g2(db,plans,user,alasan):
    await db.flush()
    for uid,plan in sorted(plans.items()):
        usage=plan['usage']
        await db.refresh(usage,['pemindahan_karung'])
        total=D(str(usage.berat_awal_kg))+D(str(usage.berat_masuk_kg))
        # Dapat sudah berubah akibat propagasi siklus sebelumnya dalam rencana
        # yang sama. Propagasi berikutnya hanya selisih yang belum diterapkan.
        sebelum_alir=None if usage.berat_akhir_kg is None else D(str(usage.berat_akhir_kg))
        if plan['terpakai'] is not None:
            target=plan.get('target',total-plan['terpakai'])
            if not D(0)<=target<=total:raise ValueError(f'Siklus #{uid}: total bahan rancangan {total} kg tidak mencakup sisa {target} kg. Pemakaian terkonfirmasi {plan["terpakai"]} kg tetap dilindungi.')
            usage.berat_akhir_kg=target;usage.terpakai_lama_kg=total-target
            await alir_sisa_g2(db,usage,sebelum_alir,target,user,alasan)
        elif total<0:raise ValueError(f'Saldo bahan siklus #{uid} menjadi {total} kg; seluruh rancangan dibatalkan.')
        await log_activity(db,table_name='polishing_silo_usage',record_id=uid,action='UPDATE',changed_by=user.id,field_name='koreksi_bahan_sisa',old_value=json.dumps(buku.bersih(plan['sebelum']),default=str),new_value=json.dumps(buku.bersih(raw(usage)),default=str),alasan=alasan,aksi=JENIS)
    await db.flush()
