"""Dokumen baca dari penerimaan/QC dan pengeluaran produksi yang sah.

Tidak menerbitkan transaksi stok atau menandatangani atas nama pelanggan.
Nomor turunan tiket/OUT stabil; pembatalan sumber mencabut ketersediaan PDF.
"""
from collections import defaultdict
from sqlalchemy import select, func, text
from fastapi import HTTPException
from app.models import (PurchaseBatchQc, PurchaseBatchQcSample, PkPurchaseQcLog,
                        Jasa, User, OutgoingRecord, ActivityLog)
from app.services import barang_masuk as masuk
from app.services.bahan_silo import kg_rinci
from app.services.mutu_pk import penilaian_dari_log
from app.database import berzona


def waktu(value):
    return berzona(value).strftime('%d/%m/%Y %H:%M') if value else 'Belum tercatat'


async def kesiapan_banyak(db, catatan):
    """Aturan gabah dan kelengkapan mutu PK asli, tanpa kueri per tiket."""
    ids={jenis:{c['id'] for c in catatan if c['model']==jenis and c['status']!='ditolak'}
         for jenis in ('gabah','pk')}
    result={}
    if ids['gabah']:
        q=PurchaseBatchQc;s=PurchaseBatchQcSample
        rows=(await db.execute(select(q.id,q.purchase_batch_id,q.ditutup_pada,
            func.count(s.id),func.max(s.created_at)).outerjoin(s,s.purchase_batch_qc_id==q.id)
            .where(q.purchase_batch_id.in_(ids['gabah']))
            .group_by(q.id,q.purchase_batch_id,q.ditutup_pada))).all()
        closed_ids={}
        for qid,bid,closed,n,last in rows:
            if closed and n<5:closed_ids[qid]=bid
            result['gabah',bid]=dict(siap=n>=5 or bool(closed and n>0),
                tanggal=closed or last,status=f"{'Ditutup lebih awal' if closed and n<5 else 'Lengkap' if n>=5 else 'Berjalan'} · {n}/5 pemeriksaan")
        if closed_ids:
            seen=set()
            for log in (await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='purchase_batch_qc',ActivityLog.record_id.in_(closed_ids),ActivityLog.field_name=='ditutup_pada').order_by(ActivityLog.id.desc()))).all():
                if log.record_id in seen:continue
                seen.add(log.record_id)
                result['gabah',closed_ids[log.record_id]]['alasan']=log.alasan_perubahan
    if ids['pk']:
        grouped=defaultdict(list)
        for log in (await db.scalars(select(PkPurchaseQcLog).where(
            PkPurchaseQcLog.pk_purchase_batch_id.in_(ids['pk'])))).all():
            grouped[log.pk_purchase_batch_id].append(log)
        for bid,logs in grouped.items():
            quality=penilaian_dari_log(logs)
            result['pk',bid]=dict(siap=quality['lengkap'],tanggal=max(l.waktu for l in logs),
                status=f"{quality['n']}/6 komponen mutu · {quality['putaran']} pemeriksaan")
    return result


def siap(catatan, gates):
    accepted=[c for c in catatan if c['status']!='ditolak']
    return bool(accepted) and all(gates.get((c['model'],c['id']),{}).get('siap',False) for c in accepted)


async def penerimaan(db, tid, *, scope=None):
    # Seluruh isi tiket dibaca sebelum penyaringan: dokumen campuran tidak
    # boleh dipotong lalu tampak seolah seluruh truk milik satu pelanggan.
    if scope and tid not in scope.resources['timbangan_transaksi']:
        raise HTTPException(404,'Penerimaan tidak ditemukan.')
    rows=await masuk.riwayat(db,g1=True,g2=True,tid=tid)
    if not rows:raise HTTPException(404,'Penerimaan tidak ditemukan.')
    row=rows[0];catatan=row['catatan']
    if scope and row.get('jasa_id') is not None and row['jasa_id'] not in scope.jasa_ids:
        raise HTTPException(404,'Penerimaan tidak ditemukan.')
    if scope and any(c['jasa_id'] not in scope.jasa_ids for c in catatan):
        raise HTTPException(404,'Penerimaan tidak ditemukan.')
    accepted=[c for c in catatan if c['status']!='ditolak']
    gates=await kesiapan_banyak(db,catatan)
    ready=siap(catatan,gates)
    timbang=await masuk.rincian_timbang(db,tid)
    status='Tersedia' if ready else 'Menunggu QC penerimaan selesai' if accepted else 'Tidak ada barang diterima'
    if not timbang or timbang['status_transaksi']!='AKTIF' or row['status_tiket']=='DITUTUP_PAKSA':
        ready=False;status='Tiket penerimaan tidak aktif'
    qc=await masuk.hasil_qc(db,accepted)
    by_code={c['kode']:gates.get((c['model'],c['id']),{}) for c in accepted}
    for g in qc:g['catatan']=by_code.get(g['kode'],{}).get('alasan')
    orders=(await db.scalars(select(Jasa).where(Jasa.id.in_({c['jasa_id'] for c in accepted if c['jasa_id']})))).all()
    people={u.id:u.nama for u in (await db.scalars(select(User).where(User.id.in_({c['petugas_id'] for c in accepted})))).all()}
    dates=[gates[c['model'],c['id']]['tanggal'] for c in accepted if (c['model'],c['id']) in gates]
    items=[]
    for c in accepted:
        name=('Gabah '+row['jenis'].removeprefix('gabah_') if c['model']=='gabah' else 'Beras PK' if c['model']=='pk' else c['model'].title())
        items.append([name,c['kode'],kg_rinci(c['berat']) if c['berat'] is not None else 'Belum diukur'])
    return dict(judul='Serah Terima Penerimaan',nomor='STP-'+row['kode'],siap=ready,
        pelanggan=scope.reader.nama if scope else row['nama'],jenis=row['jenis'],label_tanggal='Tanggal QC selesai',
        tanggal=waktu(max(dates)) if dates and ready else 'Menunggu QC selesai',
        referensi=row['kode'],pesanan=list(dict.fromkeys(([row['jasa_kode']] if row.get('jasa_kode') else [])+[j.kode for j in orders])),
        identitas=[('Tiket penerimaan',row['kode']),('Waktu penerimaan',waktu(min(c['waktu'] for c in accepted if c['waktu'])) if any(c['waktu'] for c in accepted) else 'Belum tercatat'),('Pesanan pada tiket',row.get('jasa_kode') or 'Belum tercatat'),('Pesanan barang saat ini',' · '.join(j.kode for j in orders) or 'Bukan barang jasa'),('Nomor polisi',row.get('nomor_polisi') or 'Belum tercatat'),
                   ('Sopir',row.get('nama_sopir') or 'Belum tercatat'),('Petugas penerimaan',' · '.join(dict.fromkeys(people.values())) or 'Belum tercatat')],
        kolom=['Bahan diterima','Referensi penerimaan','Berat'],baris=items,qc=qc,total=kg_rinci(row['berat_diterima']) if row['berat_diterima'] is not None else None,label_total='Total diterima',
        catatan=('Bobot penerimaan: '+(row['keterangan_berat'] or 'sesuai catatan produksi')+'. QC penerimaan terlampir; hasil proses berikutnya mengikuti Rekap Barang Jasa.'),
        status=status,
        url=f'/barang-masuk/{tid}/serah-terima',kembali=f'/barang-masuk/{tid}',
        serah='Pelanggan / pengirim',terima='Penerima di pabrik')


async def pengeluaran(db, oid, *, scope=None):
    from app.models import KoreksiPengiriman
    from app.services import barang_keluar as keluar
    from app.web.layar_keluar import _nama_barang, _nama_orang
    rows=await keluar.daftar(db,transaksi_id=oid,batas=1,
        **({'allowed_ids':scope.ids(OutgoingRecord)} if scope else {}))
    if not rows:raise HTTPException(404,'Pengeluaran tidak ditemukan.')
    rec,items=rows[0]
    if scope and (not items or any(it.jasa_id not in scope.jasa_ids for it in items)):
        raise HTTPException(404,'Pengeluaran tidak ditemukan.')
    names=await _nama_barang(db,rows);people=await _nama_orang(db,rows)
    orders=(await db.scalars(select(Jasa).where(Jasa.id.in_({it.jasa_id for it in items if it.jasa_id})))).all()
    codes={j.id:j.kode for j in orders}
    ticket=(await db.execute(text('SELECT kode,pelanggan_id,nama_sopir,netto_timbangan_kg,total_tara_kg,berat_barang_kg FROM timbangan_transaksi WHERE id=:id AND arah=\'KELUAR\''),{'id':rec.timbangan_transaksi_id})).mappings().first() if rec.timbangan_transaksi_id else None
    # Identitas pada tiket harus cocok dengan sesi; ini bukan klasifikasi jasa.
    if scope and ticket and ticket['pelanggan_id'] not in (None,scope.reader.pelanggan_id):
        raise HTTPException(404,'Pengeluaran tidak ditemukan.')
    ready=rec.status=='selesai' and bool(items) and any(float(it.berat_kg or 0)>0 for it in items)
    baris=[]
    for it in items:
        if float(it.berat_kg or 0)<=0:continue
        name=names.get(it.id,'Barang belum dikenali')
        if it.jasa_id:name+=' · '+codes.get(it.jasa_id,'Pesanan belum tercatat')
        baris.append([name,str(it.jumlah_karung) if it.jumlah_karung is not None else 'Curah' if it.item_type=='byproduct_curah' else 'Belum dicatat',kg_rinci(it.berat_kg)])
    identitas=[('Referensi pengeluaran',rec.kode),('Tiket timbang',ticket['kode'] if ticket else 'Tidak memakai tiket / belum tercatat'),
        ('Nomor polisi',rec.no_polisi or 'Belum tercatat'),('Sopir',ticket['nama_sopir'] if ticket and ticket['nama_sopir'] else 'Belum tercatat'),
        ('Dimuat oleh',people.get(rec.dimuat_oleh,'Belum tercatat')),('Diverifikasi oleh',people.get(rec.diverifikasi_oleh,'Belum tercatat'))]
    if ticket:
        identitas += [(label,kg_rinci(ticket[key]) if ticket[key] is not None else 'Belum dicatat') for label,key in [('Netto timbang','netto_timbangan_kg'),('Tara','total_tara_kg'),('Berat barang pada tiket','berat_barang_kg')]]
    koreksi=(await db.execute(select(KoreksiPengiriman.versi,KoreksiPengiriman.waktu).where(
        KoreksiPengiriman.outgoing_record_id==oid).order_by(KoreksiPengiriman.versi.desc()).limit(1))).first()
    versi_note=f' Memuat koreksi pascaverifikasi v{koreksi.versi} ({waktu(koreksi.waktu)}).' if koreksi else ''
    return dict(judul='Serah Terima Pengeluaran',nomor='STK-'+rec.kode,siap=ready,
        pelanggan=scope.reader.nama if scope else rec.nama_pembeli or 'Belum tercatat',label_tanggal='Tanggal verifikasi',
        tanggal=waktu(rec.waktu_verifikasi or rec.waktu) if ready else 'Menunggu verifikasi',
        referensi=rec.kode,pesanan=[j.kode for j in orders],identitas=identitas,
        kolom=['Barang, merek & kemasan','Jumlah sak','Berat aktual'],baris=baris,qc=[],total=kg_rinci(sum(float(it.berat_kg or 0) for it in items)),label_total='Total diserahkan',
        catatan='Jumlah dan berat memakai muatan aktual, bukan perintah. '+(rec.sebab_selisih or rec.catatan or '')+versi_note,
        status='Tersedia' if ready else 'Dibatalkan' if rec.status=='batal' else 'Menunggu pengeluaran selesai diverifikasi',
        url=f'/barang-keluar/{oid}/serah-terima',kembali=f'/barang-keluar/{oid}',
        serah='Penyerah di pabrik',terima='Pelanggan / penerima')


async def daftar(db, *, scope=None, g1=True, g2=True):
    """Daftar hanya dokumen yang siap, seluruh gerbang dibaca secara batch."""
    from sqlalchemy import bindparam
    from app.models import PurchaseBatch, PkPurchaseBatch, FinishedGoodsStock, ByproductStock, OutgoingItem
    incoming=await masuk.riwayat(db,g1=g1,g2=g2,jasa_ids=scope.jasa_ids if scope else None)
    gates=await kesiapan_banyak(db,[c for t in incoming for c in t['catatan']])
    ids={t['id'] for t in incoming}
    valid=set((await db.scalars(text("SELECT id FROM timbangan_transaksi WHERE id IN :ids AND status_transaksi='AKTIF' AND status_tiket<>'DITUTUP_PAKSA'").bindparams(bindparam('ids',expanding=True)),{'ids':sorted(ids)})).all()) if ids else set()
    if scope:valid &= scope.resources['timbangan_transaksi']
    unsafe=set()
    if scope and ids:
        for model,column in [(PurchaseBatch,PurchaseBatch.timbangan_transaksi_id),(PkPurchaseBatch,PkPurchaseBatch.timbangan_transaksi_id),(FinishedGoodsStock,FinishedGoodsStock.source_id),(ByproductStock,ByproductStock.source_id)]:
            query=select(column).where(column.in_(ids),(model.jasa_id.not_in(scope.jasa_ids) | model.jasa_id.is_(None)))
            if model in (FinishedGoodsStock,ByproductStock):query=query.where(model.source_type=='timbangan')
            unsafe.update((await db.scalars(query)).all())
    result=[]
    for t in incoming:
        if t['id'] not in valid or t['id'] in unsafe or not siap(t['catatan'],gates):continue
        dates=[gates[c['model'],c['id']]['tanggal'] for c in t['catatan'] if c['status']!='ditolak']
        result.append(dict(jenis='Penerimaan',nomor='STP-'+t['kode'],referensi=t['kode'],
            pelanggan=scope.reader.nama if scope else t['nama'],tanggal=waktu(max(dates)),
            urut=max(dates),url=f"/barang-masuk/{t['id']}/serah-terima"))
    if g2:
        query=select(OutgoingRecord).where(OutgoingRecord.status=='selesai',OutgoingRecord.id.in_(select(OutgoingItem.outgoing_record_id).where(OutgoingItem.berat_kg>0)))
        if scope:query=query.where(OutgoingRecord.id.in_(scope.ids(OutgoingRecord)))
        for r in (await db.scalars(query)).all():
            result.append(dict(jenis='Pengeluaran',nomor='STK-'+r.kode,referensi=r.kode,
                pelanggan=scope.reader.nama if scope else r.nama_pembeli or 'Belum tercatat',
                tanggal=waktu(r.waktu_verifikasi or r.waktu),urut=r.waktu_verifikasi or r.waktu,
                url=f'/barang-keluar/{r.id}/serah-terima'))
    return sorted(result,key=lambda r:(r['urut'],r['nomor']),reverse=True)
