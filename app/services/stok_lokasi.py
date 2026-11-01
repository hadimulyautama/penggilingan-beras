"""Bahan di lokasi untuk layar Stok; seluruh bobot memakai pembaca lama.

Kartu PK dan produk tetap memakai stok.pk_gudang1/pk_gudang2/stok_produk.
Pembaca ini melengkapi gabah dan isi silo yang belum ada pada daftar PK.
Tidak mengurangi saldo ketika proses dimulai atau hasil dicatat.
"""
from sqlalchemy import select, exists, func

from app.models import (PurchaseBatch, DryingLot, Dryer, Silo, SiloStorage,
                        GabahKeringLot, PolishingProcess, PolishingSiloUsage,
                        Warehouse, Jasa, PkPurchaseBatch, PkGudang2Intake, PkTumpukanToSilo)
from app.services.tahap_stok import MENUNGGU, DALAM_PROSES


async def bahan(db, *, jasa_ids=None, g1=True, g2=True):
    from app.penggilingan.gudang1.services.bobot import dari_batch, dari_batches
    from app.penggilingan.gudang1.services.drying import _loose_dryer_batches, _lot_batches
    from app.penggilingan.gudang1.services.silo import _row_bobot, giling_berjalan_untuk_silo
    from app.penggilingan.gudang1.services.gabah_kering import pending_gabah_kering_kg
    from app.penggilingan.gudang2.service import (hitung_stok_silo,
        komposisi_bahan_silo, pemilik_silo_g2)
    from app.services import berjalan

    ids = None if jasa_ids is None else frozenset(jasa_ids)
    def milik(model):
        return model.jasa_id.is_(None) if ids is None else model.jasa_id.in_(ids)
    def boleh(jid):
        return jid is None if ids is None else jid in ids

    rows = []
    def tambah(*, nama, kode, kg, pasti, lokasi, tahap, jid, href='', proses=''):
        if kg == 0:
            return
        rows.append(dict(nama=nama, kode=kode, kg=kg, final=pasti,
            lokasi=lokasi, tahap=tahap, jasa_id=jid, href=href, proses=proses))

    if g1:
        for b in (await db.scalars(select(PurchaseBatch).where(milik(PurchaseBatch),
                PurchaseBatch.status_batch.in_(('baru', 'ditumpuk'))))).all():
            n = dari_batch(b)
            tambah(nama='Gabah '+b.kondisi_gabah, kode=b.kode_batch, kg=n.kg,
                pasti=n.pasti, lokasi='Tumpukan · Gudang 1', tahap=MENUNGGU,
                jid=b.jasa_id, href=f'/barang-masuk/{b.timbangan_transaksi_id}' if b.timbangan_transaksi_id else '')
        mesin = {m.id:m.nama for m in (await db.scalars(select(Dryer))).all()}
        for b in await _loose_dryer_batches(db):
            if not boleh(b.jasa_id):
                continue
            n = dari_batch(b)
            tambah(nama='Gabah '+b.kondisi_gabah, kode=b.kode_batch, kg=n.kg,
                pasti=n.pasti, lokasi=mesin.get(b.dryer_id, 'Mesin pengering'),
                tahap=MENUNGGU, jid=b.jasa_id)
        lots = list((await db.scalars(select(DryingLot).where(milik(DryingLot),
            DryingLot.status=='proses', ~exists().where(SiloStorage.drying_lot_id==DryingLot.id)))).all())
        for selesai in (False, True):
            lots.extend(l for l in await berjalan._lot(db, pendinginan_selesai=selesai) if boleh(l.jasa_id))
        for lot in lots:
            n = dari_batches(await _lot_batches(db, lot.id))
            tahap = MENUNGGU if lot.waktu_selesai_pendinginan else DALAM_PROSES
            phase = 'pengeringan' if lot.status=='proses' else 'pendinginan'
            tambah(nama='Gabah', kode=lot.kode_lot, kg=n.kg, pasti=n.pasti,
                lokasi=mesin.get(lot.dryer_id, 'Mesin pengering'), tahap=tahap, jid=lot.jasa_id,
                href=f'/proses-aktif/{phase}/{lot.kode_lot}' if tahap==DALAM_PROSES else f'/riwayat-pengeringan/{lot.id}',
                proses=lot.kode_lot if tahap==DALAM_PROSES else '')
        for st, nama in (await db.execute(select(SiloStorage,Silo.nama_silo)
                .join(Silo,Silo.id==SiloStorage.silo_id)
                .where(milik(SiloStorage),SiloStorage.status=='terisi'))).all():
            n = await _row_bobot(db, st)
            p = await giling_berjalan_untuk_silo(db, st.silo_id)
            asal = (await db.get(PurchaseBatch, st.purchase_batch_id) if st.purchase_batch_id else
                    await db.get(DryingLot, st.drying_lot_id) if st.drying_lot_id else None)
            kode = getattr(asal, 'kode_batch', None) or getattr(asal, 'kode_lot', None) or nama
            tambah(nama='Gabah', kode=kode, kg=n.kg, pasti=n.pasti, lokasi=nama+' · Gudang 1',
                tahap=DALAM_PROSES if p else MENUNGGU, jid=st.jasa_id,
                href=f'/proses-aktif/giling/{p.kode_proses}' if p else '', proses=p.kode_proses if p else '')
        for lot in (await db.scalars(select(GabahKeringLot).where(milik(GabahKeringLot)))).all():
            kg = await pending_gabah_kering_kg(db, lot.id)
            if kg > 0:
                tambah(nama='Gabah kering',kode=lot.kode_lot,kg=kg,pasti=True,
                    lokasi='Tumpukan · Gudang 1',tahap=MENUNGGU,jid=lot.jasa_id)
    if g2:
        for b in (await db.scalars(select(PkPurchaseBatch).where(milik(PkPurchaseBatch),
                PkPurchaseBatch.status_batch=='diterima',
                ~exists().where(PkGudang2Intake.pk_purchase_batch_id==PkPurchaseBatch.id)))).all():
            n = dari_batch(b)
            tambah(nama='PK',kode=b.kode_batch,kg=n.kg,pasti=n.pasti,
                lokasi='Menunggu penempatan · Gudang 2',tahap=MENUNGGU,jid=b.jasa_id)
        peta = {}
        if ids is not None:
            peta = dict((await db.execute(select(Jasa.id,Jasa.pelanggan_id))).all())
        nama_jenis = {'pk':'PK', 'beras_putih':'Beras putih', 'broken':'Broken',
                      'menir':'Menir', 'reject':'Reject', 'bekatul':'Bekatul'}
        silos = (await db.scalars(select(Silo).join(Warehouse,Warehouse.id==Silo.warehouse_id)
            .where(Warehouse.kode_fungsi=='g2'))).all()
        for silo in silos:
            owners = await pemilik_silo_g2(db, silo.id)
            if not owners or not all(boleh(jid) for jid in owners):
                continue
            # Satu saldo lokasi hanya boleh dimasukkan ke satu pelanggan.
            if ids is not None and len({peta.get(jid) for jid in owners}) != 1:
                continue
            jid = next(iter(owners))
            kg = await hitung_stok_silo(db, silo.id)
            komposisi = await komposisi_bahan_silo(db, silo.id, target_kg=kg)
            p = await db.scalar(select(PolishingProcess).join(PolishingSiloUsage,
                PolishingSiloUsage.polishing_process_id==PolishingProcess.id).where(
                    PolishingSiloUsage.silo_id==silo.id,PolishingSiloUsage.berat_akhir_kg.is_(None),
                    PolishingProcess.status=='proses'))
            kosong = await db.scalar(select(func.max(PolishingProcess.waktu_selesai))
                .join(PolishingSiloUsage,PolishingSiloUsage.polishing_process_id==PolishingProcess.id)
                .where(PolishingSiloUsage.silo_id==silo.id,PolishingSiloUsage.berat_akhir_kg==0))
            def setelah(col):
                return [col>=kosong] if kosong else []
            intakes = list((await db.scalars(select(PkGudang2Intake).where(
                PkGudang2Intake.silo_id==silo.id,*setelah(PkGudang2Intake.waktu_masuk)))).all())
            intakes += list((await db.scalars(select(PkGudang2Intake)
                .join(PkTumpukanToSilo,PkTumpukanToSilo.pk_gudang2_intake_id==PkGudang2Intake.id)
                .where(PkTumpukanToSilo.silo_id==silo.id,*setelah(PkTumpukanToSilo.waktu)))).all())
            for jenis, n in komposisi.items():
                tambah(nama=nama_jenis.get(jenis,jenis),kode=silo.nama_silo,kg=n,
                    pasti=not p and all(i.bobot_final for i in intakes),
                    lokasi=silo.nama_silo+' · Gudang 2',tahap=DALAM_PROSES if p else MENUNGGU,
                    jid=jid,href=f'/proses-aktif/sosoh/{p.kode_proses}' if p else '',proses=p.kode_proses if p else '')
            if any(i.berat_kg is None or (not i.berat_kg and not i.bobot_final) for i in intakes):
                tambah(nama='PK',kode=silo.nama_silo,kg=None,pasti=False,
                    lokasi=silo.nama_silo+' · Gudang 2',tahap=DALAM_PROSES if p else MENUNGGU,
                    jid=jid,href=f'/proses-aktif/sosoh/{p.kode_proses}' if p else '',proses=p.kode_proses if p else '')
    return rows
