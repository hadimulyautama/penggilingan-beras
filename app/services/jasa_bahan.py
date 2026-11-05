"""Proyeksi baca-saja bahan titipan. Tidak membuat saldo/buku stok baru."""
from decimal import Decimal
from sqlalchemy import select,union_all
from app.performa import baca_sekali

TAHAP_GABAH=(('penempatan','Gabah menunggu penempatan'),('tumpukan','Gabah di tumpukan'),
             ('pengering','Gabah di pengering'),('silo_giling','Gabah di silo / proses giling'))


def ringkas(rows):
    """Jumlah per jenis DAN tahap; tidak ada total lintas tahap/hasil.

    Angka diketahui tetap subtotal bila ada baris tanpa bobot. Bobot tidak
    diketahui tidak pernah diubah menjadi nol. Baris identik dideduplikasi
    memakai identitas sumber, bukan nama pelanggan atau kode tampilan.
    """
    groups={};seen=set()
    for r in rows:
        tahap=r.get('tahap_bahan')
        if not tahap:continue
        ident=r.get('sumber_bahan')
        if ident and ident in seen:continue
        if ident:seen.add(ident)
        key=(r.get('jenis_bahan','Gabah'),tahap)
        g=groups.setdefault(key,dict(jenis=key[0],tahap=tahap,label=r['label_bahan'],
            kg=Decimal(0),belum_diketahui=0,belum_final=False,lokasi=[],jumlah=0))
        n=r.get('kg')
        if n is None:g['belum_diketahui']+=1
        else:g['kg']+=Decimal(str(n))
        g['belum_final']|=not r.get('final',True) or r.get('terikat_proses',False)
        g['jumlah']+=1
        if r.get('lokasi') and r['lokasi'] not in g['lokasi']:g['lokasi'].append(r['lokasi'])
    result=[]
    for stage,label in TAHAP_GABAH:
        g=groups.pop(('Gabah',stage),None)
        result.append(g or dict(jenis='Gabah',tahap=stage,label=label,kg=Decimal(0),
            belum_diketahui=0,belum_final=False,lokasi=[],jumlah=0))
    result.extend(sorted(groups.values(),key=lambda g:(g['jenis'],g['tahap'])))
    return result


@baca_sekali
async def gudang_nama(db):
    from app.models import Warehouse
    return dict((await db.execute(select(Warehouse.id,Warehouse.nama_gudang))).all())


@baca_sekali
async def silo_bahan(db):
    """Pakai pembaca saldo/komposisi dan pagar pemilik silo yang sudah ada.

    Jenis master silo bukan jenis barang. Silo bisa berisi PK, beras, broken,
    menir/reject, atau campuran. Isi tidak dipetakan ke pesanan dari nama.
    Data dibaca sekali per permintaan, kemudian disaring per ID pemilik.
    """
    from app.models import (Silo,PkGudang2Intake,PkTumpukanToSilo,BerasKeSilo,
        BrokenKeSilo,HasilSampingKeSilo,PolishingProcess,PolishingSiloUsage)
    from app.services.jasa import pemilik_silo_g2
    from app.penggilingan.gudang2.service import hitung_stok_silo,komposisi_bahan_silo
    models=[PkGudang2Intake,PkTumpukanToSilo,BerasKeSilo,BrokenKeSilo,HasilSampingKeSilo]
    candidates=union_all(*(select(m.silo_id.label('sid')).where(m.silo_id.isnot(None)) for m in models)).subquery()
    silos=(await db.scalars(select(Silo).where(Silo.id.in_(select(candidates.c.sid))))).all()
    active=set((await db.scalars(select(PolishingSiloUsage.silo_id).join(PolishingProcess,
        PolishingProcess.id==PolishingSiloUsage.polishing_process_id).where(
        PolishingProcess.status=='proses',PolishingSiloUsage.berat_akhir_kg.is_(None)))).all())
    names=await gudang_nama(db);result=[]
    labels={'pk':'PK','beras_putih':'Beras','broken':'Broken','menir':'Menir',
            'reject':'Reject','belum_dikenal':'Bahan campuran · jenis belum diketahui'}
    for silo in silos:
        owners=await pemilik_silo_g2(db,silo.id)
        if len(owners)!=1 or None in owners:continue
        owner=next(iter(owners));total=float(await hitung_stok_silo(db,silo.id,pemilik='jasa'))
        if total<=0.001:continue
        composition=await komposisi_bahan_silo(db,silo.id,target_kg=total)
        for kind,amount in composition.items():
            if amount<=0.001:continue
            name=labels.get(kind,kind)
            result.append(dict(owner=owner,nama=name+' · bahan proses',kode=silo.nama_silo,
                kg=amount,final=kind!='belum_dikenal',terikat_proses=silo.id in active,
                lokasi=silo.nama_silo+' · '+names.get(silo.warehouse_id,'Gudang belum tercatat'),
                href='',pesanan=None,rincian=[],jenis_bahan=name,tahap_bahan='silo_sosoh',
                label_bahan=name+' di silo / proses sosoh',sumber_bahan=f'silo-g2:{silo.id}:{kind}'))
    return result


async def menunggu(db,ids):
    """PK yang telah diterima tetapi belum punya penempatan/intake."""
    from app.models import PkPurchaseBatch,PkGudang2Intake,InternalTransfer,Silo
    from app.penggilingan.gudang1.services.bobot import dari_batch
    if not ids:return []
    names=await gudang_nama(db);rows=[]
    batches=(await db.scalars(select(PkPurchaseBatch).where(PkPurchaseBatch.jasa_id.in_(ids),
        PkPurchaseBatch.status_batch.in_(('baru','diterima')),
        ~select(PkGudang2Intake.id).where(PkGudang2Intake.pk_purchase_batch_id==PkPurchaseBatch.id).exists()))).all()
    for b in batches:
        bobot=dari_batch(b)
        rows.append(dict(nama='PK · menunggu penempatan',kode=b.kode_batch,
            kg=bobot.kg if bobot.diketahui else None,final=bobot.pasti,
            lokasi='Menunggu penempatan · '+names.get(b.warehouse_id,'Gudang belum tercatat'),
            href='/barang-masuk/'+str(b.timbangan_transaksi_id) if b.timbangan_transaksi_id else '',
            pesanan=None,rincian=[],jenis_bahan='PK',tahap_bahan='penempatan',
            label_bahan='PK menunggu penempatan',sumber_bahan=f'pk-batch:{b.id}'))
    unknown=(await db.execute(select(PkGudang2Intake,Silo.nama_silo,Silo.warehouse_id).join(Silo,Silo.id==PkGudang2Intake.silo_id)
        .where(PkGudang2Intake.jasa_id.in_(ids),PkGudang2Intake.berat_kg.is_(None)))).all()
    for intake,name,wid in unknown:
        rows.append(dict(nama='PK · bobot silo belum diketahui',kode=name,kg=None,final=False,
            lokasi=name+' · '+names.get(wid,'Gudang belum tercatat'),href='',pesanan=None,rincian=[],
            jenis_bahan='PK',tahap_bahan='silo_sosoh',label_bahan='PK di silo / proses sosoh',
            sumber_bahan=f'silo-intake-tanpa-bobot:{intake.id}'))
    transfers=(await db.scalars(select(InternalTransfer).where(InternalTransfer.jasa_id.in_(ids),
        InternalTransfer.status=='terkirim',~select(PkGudang2Intake.id).where(
        PkGudang2Intake.internal_transfer_id==InternalTransfer.id).exists()))).all()
    for t in transfers:
        rows.append(dict(nama='PK · transfer belum diterima',kode=t.kode_transfer,kg=float(t.berat_kg) if t.berat_kg else None,
            final=bool(t.berat_kg),lokasi='Transfer · penempatan tujuan belum tercatat',
            href=f'/riwayat-transfer/{t.id}',pesanan=None,rincian=[],jenis_bahan='PK',tahap_bahan='transfer',
            label_bahan='PK dalam transfer',sumber_bahan=f'transfer:{t.id}'))
    return rows
