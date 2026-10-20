"""Pembaca riwayat penerimaan. Tidak membuat status atau saldo baru.

Satu tiket dapat memiliki beberapa baris sumber. Daftar memakai satu entri
per tiket, rincian mempertahankan setiap catatan. Cermin batal disaring oleh
ORM; SQL tiket hanya membaca metadata Timbangan dan tidak menulis ke sana.
"""
from collections import defaultdict
from sqlalchemy import select, text, bindparam
from app.models import PurchaseBatch, PkPurchaseBatch, FinishedGoodsStock, ByproductStock
from app.penggilingan.peta_jenis import intake_dari_jenis


def jenis_tiket(kode):
    p = intake_dari_jenis(kode or '')
    if p:
        return 'gabah_' + p.kondisi if p.model == 'gabah' else 'pk'
    return {'BERAS_MASUK': 'beras', 'BROKEN_MASUK': 'broken'}.get(kode, 'lain')


async def tiket_riwayat(db, tid):
    """Metadata tiket tak aktif hanya untuk catatan penerimaan yang sudah ada.

    ambil_tiket sengaja menolak DITUTUP_PAKSA agar tidak dapat diterima lagi.
    Riwayat penolakan PK tetap perlu terbaca; pembaca ini tidak memasok opsi
    penerimaan dan tidak menghitung ulang bobot tiket yang telah ditutup.
    """
    q = text('''SELECT t.id,t.kode,t.arah,t.jenis_kode,j.nama AS jenis_nama,
                       t.nomor_polisi,t.nama_sopir,t.status_tiket,t.jasa,
                       t.pihak_nama,s.nama_supplier,p.nama_pelanggan,t.timbang1_waktu
                  FROM timbangan_transaksi t
                  LEFT JOIN timbangan_jenis j ON j.kode=t.jenis_kode
                  LEFT JOIN suppliers s ON s.id=t.supplier_id
                  LEFT JOIN pelanggan p ON p.id=t.pelanggan_id
                 WHERE t.id=:tid AND t.arah='MASUK' ''')
    r = (await db.execute(q, {'tid':tid})).mappings().first()
    return {**dict(r), 'berat_hpp_kg':None, 'sumber_berat':'lihat catatan penerimaan'} if r else None


async def riwayat(db, *, g1, g2, tid=None):
    # Sumbernya sama dengan pemeriksaan tiket yang telah tertaut. Tidak
    # memakai saldo tersedia sebagai tanda diterima: barang yang sudah habis
    # diproses tetap memiliki catatan penerimaan.
    hasil = defaultdict(list)
    specs = []
    if g1:
        specs.append((PurchaseBatch, PurchaseBatch.timbangan_transaksi_id, 'gabah'))
    if g2:
        specs.extend(((PkPurchaseBatch, PkPurchaseBatch.timbangan_transaksi_id, 'pk'),
                      (FinishedGoodsStock, FinishedGoodsStock.source_id, 'beras'),
                      (ByproductStock, ByproductStock.source_id, 'broken')))
    for model, kolom, jenis in specs:
        q = select(model).where(kolom.is_not(None))
        if tid is not None:
            q = q.where(kolom == tid)
        if jenis in ('beras', 'broken'):
            q = q.where(model.source_type == 'timbangan')
        for x in (await db.scalars(q)).all():
            hasil[int(getattr(x, kolom.key))].append({
                'id': x.id, 'model': jenis,
                'kode': getattr(x, 'kode_batch', None) or f"{'BJ' if jenis == 'beras' else 'HS'} #{x.id}",
                'jasa_id': x.jasa_id,
                'berat': getattr(x, 'berat_total_kg', getattr(x, 'berat_kg', None)),
                'sumber_berat': getattr(x, 'sumber_berat', 'timbangan'),
                'status': getattr(x, 'status_batch', getattr(x, 'status', 'diterima')),
                'waktu': getattr(x, 'waktu_pembelian', getattr(x, 'waktu', None)),
                'petugas_id': x.input_by,
            })
    if not hasil:
        return []
    # Sekali untuk seluruh metadata daftar, bukan satu panggilan per tiket.
    q = text('''SELECT t.id,t.kode,t.jenis_kode,j.nama AS jenis_nama,
                       t.nomor_polisi,t.nama_sopir,t.status_tiket,t.jasa,
                       t.pihak_nama,s.nama_supplier,p.nama_pelanggan,t.jasa_id,ja.kode AS jasa_kode
                  FROM timbangan_transaksi t
                  LEFT JOIN timbangan_jenis j ON j.kode=t.jenis_kode
                  LEFT JOIN suppliers s ON s.id=t.supplier_id
                  LEFT JOIN pelanggan p ON p.id=t.pelanggan_id
                  LEFT JOIN jasa ja ON ja.id=t.jasa_id
                 WHERE t.id IN :ids AND t.arah='MASUK' ORDER BY t.id DESC''').bindparams(bindparam('ids', expanding=True))
    keluar = []
    from app.penggilingan.gudang1.services.timbang_link import nama_pihak
    from app.services.jasa import nama_pemilik_banyak
    pemilik = await nama_pemilik_banyak(db, {c['jasa_id'] for cs in hasil.values() for c in cs if c['jasa_id'] is not None})
    for cs in hasil.values():
        for c in cs:
            c['pemilik'] = pemilik.get(c['jasa_id'], 'Pemilik belum diketahui') if c['jasa_id'] else 'Milik pabrik'
    for row in (await db.execute(q, {'ids': sorted(hasil)})).mappings():
        t = dict(row)
        owners = {c['jasa_id'] for c in hasil[t['id']]}
        t.update(jenis=jenis_tiket(t['jenis_kode']), catatan=hasil[t['id']],
                 nama=nama_pihak(t),
                 kepemilikan='pabrik' if owners == {None} else 'campuran' if None in owners else 'jasa')
        keluar.append(t)
    return keluar


async def rincian_lokasi(db, catatan):
    """Relasi bahan/proses aktual, termasuk pemakaian yang sudah selesai."""
    from app.models import (DryingLot, DryingLotBatch, SiloStorage, Silo,
                            MillingProcess, MillingProcessSource, PkGudang2Intake,
                            User)
    lokasi, proses = [], []
    g = [x['id'] for x in catatan if x['model'] == 'gabah']
    pk = [x['id'] for x in catatan if x['model'] == 'pk']
    lot_ids = []
    if g:
        for lot in (await db.scalars(select(DryingLot).join(DryingLotBatch, DryingLotBatch.drying_lot_id == DryingLot.id).where(DryingLotBatch.purchase_batch_id.in_(g)))).all():
            lot_ids.append(lot.id)
            tujuan = (f'/proses-aktif/pengeringan/{lot.kode_lot}' if lot.status == 'proses' else
                      f'/proses-aktif/pendinginan/{lot.kode_lot}' if lot.waktu_selesai_pendinginan is None else
                      f'/riwayat-pengeringan/{lot.id}')
            proses.append((lot.kode_lot, tujuan))
        from sqlalchemy import or_
        for nama, status in (await db.execute(select(Silo.nama_silo, SiloStorage.status).join(SiloStorage, SiloStorage.silo_id == Silo.id).where(or_(SiloStorage.purchase_batch_id.in_(g), SiloStorage.drying_lot_id.in_(lot_ids))))).all():
            lokasi.append(f'{nama} · {status}')
        for p in (await db.scalars(select(MillingProcess).join(MillingProcessSource, MillingProcessSource.milling_process_id == MillingProcess.id).where(or_(MillingProcessSource.purchase_batch_id.in_(g), MillingProcessSource.drying_lot_id.in_(lot_ids))).distinct())).all():
            proses.append((p.kode_proses, f'/proses-aktif/giling/{p.kode_proses}' if p.status == 'proses' else f'/riwayat-giling/{p.id}'))
        for b in (await db.scalars(select(PurchaseBatch).where(PurchaseBatch.id.in_(g)))).all():
            if b.dryer_id:
                from app.models import Dryer
                d = await db.get(Dryer, b.dryer_id)
                lokasi.append(d.nama if d else 'Mesin pengering')
            elif b.status_batch == 'ditumpuk':
                lokasi.append(f'Tumpukan gabah {b.kondisi_gabah} · Gudang 1')
            elif b.status_batch == 'baru':
                lokasi.append('Menunggu penempatan · Gudang 1')
    if pk:
        from app.services.stok import pk_gudang2
        tersedia = {x.intake_id for x in await pk_gudang2(db)}
        for it in (await db.scalars(select(PkGudang2Intake).where(PkGudang2Intake.pk_purchase_batch_id.in_(pk)))).all():
            s = await db.get(Silo, it.silo_id) if it.silo_id else None
            lokasi.append('Lokasi penerimaan: '+(s.nama_silo if s else 'Tumpukan Gudang 2'))
            if it.id in tersedia:
                proses.append((f'Penerimaan PK #{it.id}', f'/stok/pk/detail?gudang=g2&id={it.id}'))
            from app.models import PkTumpukanToSilo
            for pindah,nama in (await db.execute(select(PkTumpukanToSilo,Silo.nama_silo).join(Silo, Silo.id==PkTumpukanToSilo.silo_id).where(PkTumpukanToSilo.pk_gudang2_intake_id==it.id))).all():
                lokasi.append(f'{pindah.kode_pindah} · {float(pindah.berat_kg):g} kg ke {nama}')
    if any(x['model'] in ('beras', 'broken') for x in catatan):
        lokasi.append('Stok produk · Gudang 2')
    # Tautan stok mengikuti pemilik CATATAN, bukan pihak pada tiket yang bisa
    # sudah dikoreksi. Tidak menebak alokasi satu tiket ke mesin dari sekadar
    # kesamaan silo: silo dapat dipakai ulang dengan bahan berbeda.
    from app.models import Jasa
    from urllib.parse import urlencode
    for c in catatan:
        params = {'tab':'bahan' if c['model'] in ('gabah','pk') else 'produk',
                  'pemilik':'jasa' if c['jasa_id'] else 'pabrik',
                  'gudang':'g1' if c['model']=='gabah' else 'g2'}
        if c['jasa_id']:
            pesanan = await db.get(Jasa,c['jasa_id'])
            if pesanan:
                params['pelanggan_id'] = pesanan.pelanggan_id
        proses.append(('Stok terkait · '+c['pemilik'], '/stok?'+urlencode(params)))
    petugas = {u.id: u.nama for u in (await db.scalars(select(User).where(User.id.in_({x['petugas_id'] for x in catatan})))).all()}
    return list(dict.fromkeys(lokasi)), list(dict.fromkeys(proses)), petugas
