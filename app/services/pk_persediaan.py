"""Satu pembaca bagian PK per sumber, pemilik, dan objek gudang.

Adapter mengenali bentuk sumber, bukan nomor gudang. Mutasi kepemilikan
tersimpan sebagai jurnal; proses giling dan penerimaan asal tetap utuh.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func

from app.domain.gudang import Gudang, StokPK, PersediaanError
from app.performa import baca_sekali
from app.models import (Warehouse, MillingProcess, InternalTransfer, OutgoingItem,
                        OutgoingRecord, PkGudang2Intake, Peristiwa)

AWAL = 'pindah_kepemilikan_rinci'
UBAH = 'koreksi_kepemilikan_rinci'
D = lambda v: Decimal(str(v or 0))


@dataclass
class SumberPK:
    stok: StokPK
    model: object
    label: str
    waktu: datetime
    pemilik_awal: int | None
    reservasi: Decimal = Decimal(0)
    masalah: str = ''
    aliases: dict = field(default_factory=dict)
    terikat: dict = field(default_factory=dict)
    kepemilikan_net: dict = field(default_factory=dict)

    def pemilik(self, ident):
        return self.aliases.get(ident, ident)

    def bebas(self, pemilik_id, transaksi_id=None):
        if self.masalah:raise PersediaanError(self.masalah)
        pemilik_id=self.pemilik(pemilik_id)
        nilai=self.stok.saldo(pemilik_id,transaksi_id=transaksi_id)
        alokasi=sum((n for (owner,tag),n in self.terikat.items()
                     if owner==pemilik_id and (transaksi_id is None or tag==transaksi_id)),Decimal(0))
        return max(Decimal(0),nilai-alokasi)

    def tahan(self, owner, jumlah):
        sisa=D(jumlah)
        if sisa<=0:return D(0)
        sebelumnya=dict(self.terikat)
        for b in self.stok.bagian:
            if b.pemilik_id!=owner:continue
            key=(owner,b.transaksi_id)
            sudah=min(b.berat_kg,sebelumnya.get(key,D(0)))
            sebelumnya[key]=sebelumnya.get(key,D(0))-sudah
            take=min(sisa,max(D(0),b.berat_kg-sudah))
            self.terikat[key]=self.terikat.get(key,D(0))+take
            sisa-=take
            if sisa<=0:break
        return sisa


def _waktu(row, fallback=None):
    v = getattr(row, 'created_at', None) or fallback or getattr(row, 'waktu', None)
    if v is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


@baca_sekali
async def ada_pengalihan(db, *, sumber=None):
    if sumber and not await ada_pengalihan(db):return False
    q = select(Peristiwa.id).where(Peristiwa.jenis == AWAL,
                                 Peristiwa.muatan['kind'].as_string() == 'pk')
    if sumber:
        q = q.where(Peristiwa.muatan['identity']['sumber'].as_string() == sumber)
    return await db.scalar(q.limit(1)) is not None


@baca_sekali
async def baca(db, *, warehouse_id=None):
    from app.penggilingan.gudang1.services.milling import pk_saldo_query
    from app.penggilingan.gudang2.service import sisa_tumpukan_banyak
    from app.penggilingan.gudang2.models import PkTumpukanToSilo, PkPurchaseBatch
    from app.penggilingan.gudang2.karung import bobot_per_karung
    from app.models import CustomerReturnItem
    from app.services.retur_supplier_reservasi import terikat_banyak

    warehouses = {w.id: Gudang.dari_model(w) for w in
                  (await db.scalars(select(Warehouse))).all()}
    from app.models import Jasa
    jasa_rows={j.id:j for j in (await db.scalars(select(Jasa))).all()}
    aliases={}
    for ident,j in jasa_rows.items():
        seen=set()
        while j.digabung_ke_id is not None:
            if j.id in seen or j.digabung_ke_id not in jasa_rows:raise PersediaanError('Jejak penggabungan pesanan PK tidak lengkap.')
            seen.add(j.id)
            other=jasa_rows[j.digabung_ke_id]
            if other.pelanggan_id!=j.pelanggan_id:raise PersediaanError('Jejak pemilik PK berbeda pelanggan.')
            j=other
        aliases[ident]=j.id
    canon=lambda ident:aliases.get(ident,ident)
    result = {}
    timeline = []
    processes = list((await db.scalars(select(MillingProcess))).all())
    balances = {r.id: r for r in (await db.execute(pk_saldo_query())).all()}
    for p in processes:
        w = warehouses.get(p.warehouse_id)
        if w is None or warehouse_id is not None and w.id != warehouse_id:
            continue
        amount = D(balances[p.id].produced)
        # Sumber proses yang masih berjalan tidak ditawarkan untuk dialihkan.
        key = 'giling:' + str(p.id)
        stock = StokPK(w, key, [], p.status == 'selesai')
        from app.domain.gudang import BagianPK
        stock.bagian.append(BagianPK(p.jasa_id, amount, 0))
        result[key] = SumberPK(stock, p, p.kode_proses, _waktu(p, p.waktu_mulai), p.jasa_id)

    intakes = list((await db.scalars(select(PkGudang2Intake).where(
        PkGudang2Intake.tujuan == 'ditumpuk', PkGudang2Intake.dibatalkan_pada.is_(None)))).all())
    intakes = [i for i in intakes if i.warehouse_id in warehouses and
               (warehouse_id is None or i.warehouse_id == warehouse_id)]
    saldo = await sisa_tumpukan_banyak(db, intakes)
    ids = [i.id for i in intakes]
    moves = list((await db.scalars(select(PkTumpukanToSilo).where(
        PkTumpukanToSilo.pk_gudang2_intake_id.in_(ids)))).all()) if ids else []
    batch_ids = {i.pk_purchase_batch_id for i in intakes if i.pk_purchase_batch_id}
    batches = {b.id: b for b in (await db.scalars(select(PkPurchaseBatch).where(
        PkPurchaseBatch.id.in_(batch_ids)))).all()} if batch_ids else {}
    move_weights = {}
    by_intake = {i.id: i for i in intakes}
    moved = {}
    for m in moves:
        i = by_intake[m.pk_gudang2_intake_id]
        batch = batches.get(i.pk_purchase_batch_id)
        value = (bobot_per_karung(batch, jumlah=m.jumlah_karung)
                 if m.jumlah_karung is not None else D(m.berat_timbang_kg))
        if value is None:
            value = D(0)
        move_weights[m.id] = value
        moved[i.id] = moved.get(i.id, D(0)) + value
    transfers=list((await db.scalars(select(InternalTransfer).where(InternalTransfer.status=='terkirim'))).all())
    transfers_by_id={t.id:t for t in transfers}
    processes_by_id={p.id:p for p in processes}
    reservations = await terikat_banyak(db, ['pk:'+str(b) for b in batch_ids])
    for i in intakes:
        key = 'tumpukan:' + str(i.id)
        w = warehouses[i.warehouse_id]
        value = saldo.get(i.id)
        batch = batches.get(i.pk_purchase_batch_id)
        stock = StokPK(w, key, [], bool(i.bobot_final and value is not None))
        from app.domain.gudang import BagianPK
        stock.bagian.append(BagianPK(i.jasa_id, max(D(0), D(value) + moved.get(i.id, D(0))), 0))
        transfer=transfers_by_id.get(i.internal_transfer_id)
        process=processes_by_id.get(transfer.milling_process_id) if transfer else None
        label = batch.kode_batch if batch else 'Giling sendiri · '+process.kode_proses if process else 'PK sumber #'+str(i.id)
        result[key] = SumberPK(stock, i, label, _waktu(i, i.waktu_masuk), i.jasa_id,
                               D(reservations.get('pk:'+str(i.pk_purchase_batch_id))))
    for m in moves:
        timeline.append((_waktu(m, m.waktu), 'pakai',
                         ('tumpukan:'+str(m.pk_gudang2_intake_id), m.jasa_id, move_weights[m.id])))
    for t in transfers:
        timeline.append((_waktu(t, t.waktu), 'pakai',
                         ('giling:'+str(t.milling_process_id), t.jasa_id, D(t.berat_kg))))

    # Pengeluaran lama bertipe tumpukan tidak mempunyai alokasi intake.
    # FIFO tetap dibatasi gudang DAN pemilik yang tersimpan pada pengiriman.
    items = (await db.execute(select(OutgoingItem, OutgoingRecord)
        .join(OutgoingRecord, OutgoingRecord.id == OutgoingItem.outgoing_record_id)
        .where(OutgoingItem.item_type.in_(['pk_langsung', 'pk_g2'])))).all()
    for item, record in items:
        if item.item_type == 'pk_langsung':
            timeline.append((_waktu(item, record.waktu), 'pakai',
                             ('giling:'+str(item.milling_process_id), item.jasa_id, D(item.berat_kg))))
        elif item.silo_id is None:
            timeline.append((_waktu(item, record.waktu), 'pool',
                             (record.warehouse_id, item.jasa_id, D(item.berat_kg))))

    returns = (await db.execute(select(CustomerReturnItem, OutgoingItem)
        .join(OutgoingItem, CustomerReturnItem.outgoing_item_id == OutgoingItem.id)
        .where(OutgoingItem.item_type == 'pk_langsung'))).all()
    for ret,item in returns:
        timeline.append((_waktu(ret), 'credit',
                         ('giling:'+str(item.milling_process_id), ret.jasa_id, D(ret.berat_total_kg))))

    events = list((await db.scalars(select(Peristiwa).where(
        Peristiwa.jenis.in_([AWAL, UBAH])).order_by(Peristiwa.id))).all())
    for event in events:
        state = event.muatan if event.jenis == AWAL else event.muatan.get('after', {})
        if state.get('kind') != 'pk':
            continue
        for delta in event.muatan.get('pk_moves', []):
            timeline.append((_waktu(event, event.waktu), 'alih', delta))
    for source in result.values():
        source.aliases=aliases
        source.pemilik_awal=canon(source.pemilik_awal)
        for b in source.stok.bagian:b.pemilik_id=canon(b.pemilik_id)
    for _, kind, payload in sorted(timeline, key=lambda row: row[0]):
        if kind == 'alih':
            source = result.get(payload['sumber'])
            if source is None:
                continue
            try:
                source.stok.alihkan(canon(payload['dari']), canon(payload['ke']), payload['kg'],
                    transaksi_id=payload['transaksi_id'], sumber_transaksi_id=payload.get('sumber_transaksi_id'), _historis=True)
                dari,ke=canon(payload['dari']),canon(payload['ke'])
                source.kepemilikan_net[dari]=source.kepemilikan_net.get(dari,D(0))-D(payload['kg'])
                source.kepemilikan_net[ke]=source.kepemilikan_net.get(ke,D(0))+D(payload['kg'])
            except PersediaanError as e:
                source.masalah = str(e)
        elif kind == 'credit':
            key, owner, value = payload
            owner=canon(owner)
            source = result.get(key)
            if source is not None:
                from app.domain.gudang import BagianPK
                source.stok.bagian.append(BagianPK(owner, value, 0))
        elif kind == 'pakai':
            key, owner, value = payload
            owner=canon(owner)
            source = result.get(key)
            if source is None or value <= 0:
                continue
            try:
                source.stok.ambil(owner, value)
            except PersediaanError as e:
                source.masalah = str(e)
        else:
            wid, owner, value = payload
            owner=canon(owner)
            sources = sorted((s for key,s in result.items()
                if key.startswith('tumpukan:') and s.stok.gudang.id == wid), key=lambda s:s.waktu)
            for source in sources:
                take = min(value, max(D(0), source.stok.saldo(owner) -
                    (source.reservasi if owner == source.pemilik_awal else D(0))))
                if take > 0:
                    source.stok.ambil(owner, take)
                    value -= take
            if value > D('.001'):
                for source in sources:
                    source.masalah = 'Sumber pengeluaran PK lama belum dapat direkonsiliasi.'
    # Niat pengeluaran menahan bagian bebas, tidak mengurangi fisik. Alokasi
    # tetap per sumber/warehouse/pemilik dan mengikuti urutan bagian yang sama.
    from app.penggilingan.inventory.models import OUT_PERINTAH
    pending=(await db.execute(select(OutgoingItem,OutgoingRecord)
        .join(OutgoingRecord,OutgoingRecord.id==OutgoingItem.outgoing_record_id)
        .where(OutgoingRecord.status==OUT_PERINTAH,
               OutgoingItem.item_type.in_(['pk_langsung','pk_g2'])))).all()
    for source in result.values():
        if source.reservasi>0:source.tahan(source.pemilik_awal,source.reservasi)
    for item,record in pending:
        value=max(D(0),D(item.berat_perintah_kg)-D(item.berat_kg));owner=canon(item.jasa_id)
        if item.item_type=='pk_langsung':
            source=result.get('giling:'+str(item.milling_process_id))
            if source is not None:source.tahan(owner,value)
        elif item.silo_id is None:
            for source in sorted((source for key,source in result.items()
                    if key.startswith('tumpukan:') and source.stok.gudang.id==record.warehouse_id),key=lambda v:v.waktu):
                value=source.tahan(owner,value)
                if value<=0:break
    return result


def pecah_kode(kode):
    value=(kode or '').strip()
    if '|pemilik=' not in value:return value,...
    base,token=value.rsplit('|pemilik=',1)
    if token=='pabrik':return base,None
    if not token.isascii() or not token.isdigit() or int(token)<=0:
        raise PersediaanError('Identitas pemilik PK tidak sah.')
    return base,int(token)


async def pastikan_sumber_tidak_diubah(db, sumber):
    from app.services.barang_keluar import _kunci_saldo_keluar
    await _kunci_saldo_keluar(db)
    if await ada_pengalihan(db,sumber=sumber):
        raise PersediaanError('Sumber PK sudah memiliki riwayat pengalihan kepemilikan. Perubahan atau pembatalan sumber asal ditahan agar hak pemilik dan jejak transaksi tetap utuh; periksa transaksi kepemilikan terkait.')
