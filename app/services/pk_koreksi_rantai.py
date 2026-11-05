"""Rancangan penurunan bobot PK yang mengikuti transfer, silo, dan bahan sosoh.

Tidak mengubah hasil timbang/produksi atau menulis saat pratinjau. Seluruh
perubahan efektif dan angka aslinya tersimpan di peristiwa koreksi pemilik.
"""
import copy,json
from decimal import Decimal as D
from types import SimpleNamespace
from sqlalchemy import select,Numeric
from app.models import (InternalTransfer,PkGudang2Intake,PkTumpukanToSilo,
    PolishingSiloUsage,PolishingProcess,PolishingOutputLog,PermintaanPk,Peristiwa)
from app.services import peristiwa as buku
from app.services.koreksi_bahan_berjalan import raw,siklus_g2,sinkron_bahan
from app.services import kepemilikan as umum

MODELS={'transfers':InternalTransfer,'intakes':PkGudang2Intake,
        'moves':PkTumpukanToSilo,'usages':PolishingSiloUsage,'requests':PermintaanPk}
SAAT='saat_koreksi'


async def alasan_perubahan_terpisah(db,kind,ident):
    """Satu rantai dikoreksi melalui akar yang menampung audit angkanya."""
    for event in (await db.scalars(select(Peristiwa).where(Peristiwa.jenis==umum.UBAH).order_by(Peristiwa.id.desc()))).all():
        if any(x['id']==ident for x in event.muatan.get('pk_chain',{}).get(kind,[])):
            return 'Catatan ini mengikuti koreksi AM-PK-'+str(event.muatan['root_id'])+'. Gunakan koreksi atau pembatalan transaksi kepemilikan tersebut agar seluruh bobot dan bahan proses tetap sesuai.'
    return None

class Rancangan:
    def __init__(self):
        self.data={k:[] for k in MODELS};self.rows={};self.totals={};self.procs={};self.silos=set()

    def row(self,kind,row):
        key=(kind,row.id)
        if key not in self.rows:
            before=buku.bersih(raw(row))
            item=dict(id=row.id,before=before,after=copy.deepcopy(before))
            self.data[kind].append(item);self.rows[key]=item
        return self.rows[key]

    async def usage(self,db,u,delta,col):
        item=self.row('usages',u);after=item['after']
        oldtotal=self.totals.get(u.id,D(str(u.berat_awal_kg))+D(str(u.berat_masuk_kg)))
        total=oldtotal+delta
        if total<0:raise umum.InventoryError('Koreksi membuat jumlah bahan silo negatif; periksa rantai yang ditampilkan.')
        if col:after[col]=str(D(str(after[col] or 0))+delta)
        self.totals[u.id]=total
        proc=await db.get(PolishingProcess,u.polishing_process_id)
        self.procs[proc.id]=proc;self.silos.add(u.silo_id)
        item.update(kode=proc.kode_proses,total_before=str(D(str(u.berat_awal_kg))+D(str(u.berat_masuk_kg))),total_after=str(total))
        if after['berat_akhir_kg'] is not None:
            oldtail=D(str(after['berat_akhir_kg']));tail=min(oldtail,total)
            after['berat_akhir_kg']=str(tail);after['terpakai_lama_kg']=str(total-tail)
            if tail!=oldtail:
                # Sisa yang menjadi bahan siklus selanjutnya ikut berkurang.
                nxt=await db.scalar(select(PolishingSiloUsage).where(
                    PolishingSiloUsage.silo_id==u.silo_id,PolishingSiloUsage.id>u.id)
                    .order_by(PolishingSiloUsage.id).limit(1))
                if nxt:await self.usage(db,nxt,tail-oldtail,'awal_tetap_kg')

    async def silo(self,db,entry,delta,*,dynamic=False):
        u=await siklus_g2(db,entry)
        self.silos.add(entry.silo_id)
        if u is None:return
        proc=await db.get(PolishingProcess,u.polishing_process_id)
        col=None if dynamic else 'masuk_tetap_kg' if entry.waktu>proc.waktu_mulai else 'awal_tetap_kg'
        await self.usage(db,u,delta,col)

    async def intake(self,db,it,delta):
        from app.services.cakupan_fasilitas import lokasi_banyak
        lokasi=(await lokasi_banyak(db,PkGudang2Intake,[it.id]))[it.id]
        await umum.izin(db,self.user,[lokasi['warehouse_id']])
        item=self.row('intakes',it);new=D(str(it.berat_kg))-delta
        if new<0:raise umum.InventoryError('Bobot koreksi melebihi pemasukan pasangan transfer.')
        item.update(effective_before=str(it.berat_kg),effective_after=str(new))
        if new:item['after']['berat_kg']=str(new)
        else:item['after']['dibatalkan_pada']=SAAT
        if it.silo_id:
            await self.silo(db,SimpleNamespace(silo_id=it.silo_id,waktu=it.waktu_masuk),-delta)
            return
        from app.services import pk_persediaan
        key='tumpukan:'+str(it.id)
        if await pk_persediaan.ada_pengalihan(db,sumber=key):
            raise umum.InventoryError('Pemasukan terkait mempunyai pengalihan kepemilikan lain. Rincian pengalihan lanjutan perlu diperiksa bersama sebelum bobotnya dikurangi.')
        source=(await pk_persediaan.baca(db)).get(key)
        if source is None or source.masalah:raise umum.InventoryError('Saldo tumpukan pasangan transfer tidak dapat dibuktikan.')
        remaining=max(D(0),delta-source.bebas(it.jasa_id))
        moves=list((await db.scalars(select(PkTumpukanToSilo).where(
            PkTumpukanToSilo.pk_gudang2_intake_id==it.id,PkTumpukanToSilo.dibatalkan_pada.is_(None))
            .order_by(PkTumpukanToSilo.id.desc()))).all())
        for m in moves:
            if remaining<=0:break
            take=min(D(str(m.berat_kg or 0)),remaining)
            await self.move(db,m,take)
            remaining-=take
        if remaining>0:
            raise umum.InventoryError('Sebagian PK terkait sudah keluar gudang atau terikat pengeluaran. Koreksi pengeluaran tersebut perlu diperiksa bersama; bagian itu tidak dikurangi dua kali.')

    async def move(self,db,m,take):
        from app.services.pk_50 import bagi_tersimpan
        old=D(str(m.berat_kg or 0));newkg=old-take
        if not D(0)<take<=old:raise umum.InventoryError('Jumlah koreksi pemindahan silo tidak sah.')
        row=self.row('moves',m);a=row['after']
        row.update(effective_before=str(old),effective_after=str(newkg))
        if newkg:
            a.update(jumlah_karung=None,berat_timbang_kg=str(newkg))
            bags,loose=bagi_tersimpan(newkg,3)
            a.update(jumlah_karung_50=bags,berat_curah_kg=str(loose))
        else:a['dibatalkan_pada']=SAAT
        u=await siklus_g2(db,m)
        dynamic=bool(u and m.pemakaian_silo_id==u.id)
        await self.silo(db,m,-take,dynamic=dynamic)

    async def selesai(self,db):
        summaries=[];warnings=[]
        for pid,proc in sorted(self.procs.items()):
            rows=list((await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pid).order_by(PolishingSiloUsage.id))).all())
            before=D(0);after=D(0)
            for u in rows:
                total=D(str(u.berat_awal_kg))+D(str(u.berat_masuk_kg))
                original=D(str(u.berat_terpakai_kg)) if u.berat_akhir_kg is not None else total
                before+=original
                item=self.rows.get(('usages',u.id))
                if item:
                    a=item['after'];t=self.totals[u.id]
                    after+=t-D(str(a['berat_akhir_kg'])) if a['berat_akhir_kg'] is not None else t
                else:after+=original
            logs=list((await db.scalars(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==pid).order_by(PolishingOutputLog.id))).all())
            output=sum((D(str(x.berat_kg)) for x in logs),D(0))
            summaries.append(dict(id=pid,kode=proc.kode_proses,status=proc.status,
                bahan_before=str(before),bahan_after=str(after),hasil_tercatat=str(output),
                output_facts=[buku.bersih(raw(x)) for x in logs]))
            if output>after:
                warnings.append(f'{proc.kode_proses}: hasil tercatat {output} kg melebihi bahan setelah koreksi {after} kg. Hasil tidak diubah otomatis; periksa catatan bahan/hasil proses ini.')
        self.data.update(processes=summaries,warnings=warnings,silos=sorted(self.silos))
        return self.data


async def rancang(db,*,source,ident,owner,jumlah,user):
    """Hanya arus yang terbukti menghabiskan bagian transaksi ini yang dibalik."""
    if not source.stok.sumber.startswith(('giling:','tumpukan:')):
        raise umum.InventoryError('Rantai fisik sumber ini belum dapat dibuktikan. Periksa sumber dan pengeluaran yang terkait.')
    plan=Rancangan();plan.user=user;need=D(jumlah);flows=[]
    uses={}
    ref_prefix='transfer:' if source.stok.sumber.startswith('giling:') else 'move:'
    for x in source.pemakaian:
        if x['tag']==ident and x['owner']==owner and x['kg']>0 and (x['ref'] or '').startswith(ref_prefix):
            tid=int(x['ref'].split(':')[1]);uses[tid]=uses.get(tid,D(0))+x['kg']
    from app.services.pk_50 import bagi_tersimpan
    for tid,available in sorted(uses.items(),reverse=True):
        if need<=0:break
        if ref_prefix=='move:':
            m=await db.get(PkTumpukanToSilo,tid,populate_existing=True)
            if not m or m.dibatalkan_pada is not None:continue
            take=min(need,available,D(str(m.berat_kg or 0)))
            await plan.move(db,m,take)
            flows.append(dict(sumber=source.stok.sumber,owner=owner,tag=ident,ref=ref_prefix+str(tid),kg=str(take)))
            need-=take
            continue
        t=await db.get(InternalTransfer,tid,populate_existing=True)
        if not t or t.status!='terkirim' or source.pemilik(t.jasa_id)!=owner:continue
        take=min(need,available,D(str(t.berat_kg)))
        if take<=0:continue
        it=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id==t.id,PkGudang2Intake.dibatalkan_pada.is_(None)))
        if not it or it.berat_kg is None or D(str(it.berat_kg))!=D(str(t.berat_kg)):
            raise umum.InventoryError('Pemasukan pasangan transfer tidak sesuai. Periksa rincian penerimaan terkait.')
        item=plan.row('transfers',t);new=D(str(t.berat_kg))-take
        bags,loose=bagi_tersimpan(new,2)
        item.update(effective_before=str(t.berat_kg),effective_after=str(new))
        if new:item['after'].update(berat_kg=str(new),jumlah_karung=bags,berat_curah_kg=str(loose))
        item['kode']=t.kode_transfer
        if not new:item['after']['status']='dibatalkan'
        await plan.intake(db,it,take)
        # Angka muat asli dan persetujuan tetap menjadi fakta historis.
        # Angka final efektif mengikuti koreksi yang diaudit.
        for request in (await db.scalars(select(PermintaanPk).where(PermintaanPk.internal_transfer_id==t.id))).all():
            row=plan.row('requests',request)
            if new:row['after']['berat_final_kg']=str(new)
            if not new:row['after']['status']='gugur'
        flows.append(dict(sumber=source.stok.sumber,owner=owner,tag=ident,ref='transfer:'+str(tid),kg=str(take)))
        need-=take
    if need>0:
        raise umum.InventoryError('Sisa koreksi berada pada alokasi/pengeluaran atau pengalihan lain yang belum mempunyai rantai transfer lengkap. Periksa rincian terkait; stok tidak dibuat kembali tanpa bukti.')
    result=await plan.selesai(db)
    result.update(flows=flows,restored_kg=str(jumlah))
    return result


async def proyeksi(db,event):
    from app.models.peristiwa import ProyeksiTransferPk,ProyeksiPkMasukG2,ProyeksiPindahTumpukanSilo
    models={'transfers':ProyeksiTransferPk,'intakes':ProyeksiPkMasukG2,'moves':ProyeksiPindahTumpukanSilo}
    fields={'transfers':['berat_kg','jumlah_karung','berat_curah_kg'],
            'intakes':['berat_kg'],'moves':['jumlah_karung','jumlah_karung_50','berat_curah_kg']}
    for kind,model in models.items():
        for item in event.muatan.get('pk_chain',{}).get(kind,[]):
            eid=item['before'].get('peristiwa_id')
            if not eid:continue
            row=await db.get(model,eid)
            if row is None:raise umum.InventoryError('Proyeksi peristiwa asal rantai PK tidak ditemukan.')
            for key in fields[kind]:
                value=item['after'][key]
                if value is not None and isinstance(row.__mapper__.attrs[key].columns[0].type,Numeric):value=D(str(value))
                setattr(row,key,value)
            if kind=='moves':row.berat_kg=D(str(item['after']['berat_timbang_kg'])) if item['after']['berat_timbang_kg'] is not None else D(item['effective_before'])
            cancelled=item['after'].get('status')=='dibatalkan' or item['after'].get('dibatalkan_pada')==SAAT
            if cancelled:row.status='dibatalkan';row.dibatalkan_peristiwa_id=event.id
    await db.flush()


async def terapkan(db,*,event,user):
    from app.services.activity_log import log_activity
    for kind,model in MODELS.items():
        for item in event.muatan['pk_chain'].get(kind,[]):
            row=await db.get(model,item['id'],populate_existing=True,with_for_update=True)
            if row is None or buku.bersih(raw(row))!=item['before']:
                raise umum.InventoryError('Rantai berubah sejak pemeriksaan. Baca kembali dan periksa dampaknya.')
            for key,value in item['after'].items():
                if value==item['before'].get(key):continue
                if value==SAAT:value=event.waktu
                elif value is not None and isinstance(row.__mapper__.attrs[key].columns[0].type,Numeric):value=D(str(value))
                setattr(row,key,value)
            await log_activity(db,table_name=model.__tablename__,record_id=row.id,action='UPDATE',
                changed_by=user.id,old_value=json.dumps(item['before']),new_value=json.dumps(buku.bersih(raw(row))),
                alasan=event.muatan['request']['reason'],aksi='koreksi_kepemilikan_pk_berantai')
    await db.flush()
    await proyeksi(db,event)
    ids={x['id'] for x in event.muatan['pk_chain'].get('processes',[])}
    await sinkron_bahan(db,'sosoh',ids)
    from app.penggilingan.gudang2.service import segarkan_status_silo
    for sid in event.muatan['pk_chain'].get('silos',[]):await segarkan_status_silo(db,sid)
