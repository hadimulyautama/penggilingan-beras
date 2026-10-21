"""Pembaca riwayat penerimaan. Tidak membuat status atau saldo baru.

Satu tiket dapat memiliki beberapa baris sumber. Daftar memakai satu entri
per tiket, rincian mempertahankan setiap catatan. Cermin batal disaring oleh
ORM; SQL tiket hanya membaca metadata Timbangan dan tidak menulis ke sana.
"""
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import select, text, bindparam
from app.models import PurchaseBatch, PkPurchaseBatch, FinishedGoodsStock, ByproductStock
from app.penggilingan.peta_jenis import intake_dari_jenis


def jenis_tiket(kode):
    p = intake_dari_jenis(kode or '')
    if p:
        return 'gabah_' + p.kondisi if p.model == 'gabah' else 'pk'
    return {'BERAS_MASUK': 'beras', 'BROKEN_MASUK': 'broken'}.get(kode, 'lain')


def bobot_diterima(catatan):
    """Jumlah catatan penerimaan, bukan netto tiket atau saldo tersisa.

    Tiket dapat dipecah. Jangan menghitung catatan penolakan sebagai barang
    diterima atau mengubah berat yang belum diketahui menjadi nol.
    """
    diterima = [c for c in catatan if c['status'] != 'ditolak']
    if not diterima:
        return None, 'Tidak diterima'
    if any(c['berat'] is None for c in diterima):
        return None, 'Belum lengkap' if any(c['berat'] is not None for c in diterima) else 'Belum diukur'
    berat = sum((Decimal(str(c['berat'])) for c in diterima), Decimal(0))
    sementara = any(c['sumber_berat'] in ('menunggu', 'perkiraan') for c in diterima)
    return berat, 'Belum final' if sementara else ''


async def rincian_timbang(db, tid):
    """Snapshot Pos Timbang untuk dibaca setelah gerbang gudang di detail.

    Tidak menghitung ulang bruto/tara atau mengambil nilai finansial. Angka
    dan jejak petugas berasal dari tiket, termasuk partai kecil dan data lama
    yang belum lengkap; NULL tetap ditampilkan sebagai belum tercatat.
    """
    q = text('''SELECT t.cara_timbang,t.timbang1_kg,t.timbang1_waktu,
                       t.timbang2_kg,t.timbang2_waktu,t.berat_bermuatan_kg,
                       t.berat_kosong_kg,t.netto_timbangan_kg,t.jumlah_karung,
                       t.total_tara_kg,t.tara_lain_kg,t.berat_barang_kg,
                       t.berat_acuan_kg,t.selisih_kg,t.selisih_persen,
                       t.batas_bawah_kg,t.batas_atas_kg,t.status_kontrol,
                       t.status_transaksi,t.keterangan,t.catatan,t.tutup_paksa_alasan,
                       a.nama AS petugas1,b.nama AS petugas2
                  FROM timbangan_transaksi t
                  LEFT JOIN timbangan_akun a ON a.id=t.timbang1_petugas_id
                  LEFT JOIN timbangan_akun b ON b.id=t.timbang2_petugas_id
                 WHERE t.id=:tid AND t.arah='MASUK' ''')
    row=(await db.execute(q,{'tid':tid})).mappings().first()
    if not row:
        return None
    hasil=dict(row)
    hasil['muatan']=[dict(r) for r in (await db.execute(text('''
        SELECT m.urutan,m.jenis_kode,j.nama AS jenis_nama,m.nomor_acuan,
               m.jumlah_karung,m.tara_per_karung_kg,m.berat_acuan_kg,m.catatan,
               q.nama AS kualitas,b.nama AS merek,k.nama AS kemasan,s.ukuran_kg
          FROM timbangan_muatan m
          LEFT JOIN timbangan_jenis j ON j.kode=m.jenis_kode
          LEFT JOIN rice_quality_standards q ON q.id=m.kualitas_id
          LEFT JOIN brands b ON b.id=m.merek_produk_id
          LEFT JOIN packaging_materials k ON k.id=m.packaging_material_id
          LEFT JOIN package_sizes s ON s.id=m.package_size_id
         WHERE m.transaksi_id=:tid ORDER BY m.urutan,m.id
    '''),{'tid':tid})).mappings()]
    # Partai kecil datang dari skema Pos Timbang yang lebih baru. Database
    # lama/mandiri Produksi belum tentu memiliki tabel ini; jangan membuat
    # tiket truk biasa gagal dibuka hanya karena rincian partai tidak ada.
    hasil['penimbangan']=[]
    hasil['rincian_partai_tersedia']=True
    if hasil['cara_timbang']=='PARTAI':
        hasil['rincian_partai_tersedia']=bool(await db.scalar(text("SELECT to_regclass('timbangan_penimbangan')")))
    if hasil['cara_timbang']=='PARTAI' and hasil['rincian_partai_tersedia']:
        hasil['penimbangan']=[dict(r) for r in (await db.execute(text('''
        SELECT p.urutan,p.berat_kg,p.waktu,p.catatan,a.nama AS petugas
          FROM timbangan_penimbangan p
          LEFT JOIN timbangan_akun a ON a.id=p.petugas_id
         WHERE p.transaksi_id=:tid ORDER BY p.urutan,p.id
        '''),{'tid':tid})).mappings()]
    return hasil


async def hasil_qc(db, catatan):
    """QC penerimaan pada batch yang tertaut, bukan hasil mesin sesudahnya."""
    from app.models import PurchaseBatchQc, PurchaseBatchQcSample, PkPurchaseQcLog, PkPurchaseVerification, User
    from app.services.mutu_pk import rincian_kualitatif
    kelompok=[]
    def persen(v):
        return f'{float(v):g}%'.replace('.',',') if v is not None else 'Belum diukur'
    def kondisi(v):
        return (v or 'Belum dicatat').replace('_',' ')
    for c in catatan:
        if c['model'] not in ('gabah','pk'):
            continue
        g=dict(kode=c['kode'],putaran=[],status='Belum diperiksa')
        if c['model']=='gabah':
            b=await db.get(PurchaseBatch,c['id'])
            q=await db.scalar(select(PurchaseBatchQc).where(PurchaseBatchQc.purchase_batch_id==c['id']))
            rows=(await db.execute(select(PurchaseBatchQcSample,User.nama)
                .outerjoin(User,User.id==PurchaseBatchQcSample.input_by)
                .where(PurchaseBatchQcSample.purchase_batch_qc_id==q.id)
                .order_by(PurchaseBatchQcSample.nomor_sampel))).all() if q else []
            for s,nama in rows:
                fields=[('Kadar air 1',persen(s.kadar_air_1)),('Kadar air 2',persen(s.kadar_air_2)),
                        ('Biji hijau',kondisi(s.biji_hijau)),('Densiti',kondisi(s.densiti))]
                if b.kondisi_gabah=='basah':
                    fields.append(('Lamur',('Ya' if s.lamur else 'Tidak')+f' · {s.jumlah_sak_lamur or 0} sak' if s.lamur is not None else 'Belum dicatat'))
                g['putaran'].append(dict(nomor=s.nomor_sampel,waktu=s.created_at,petugas=nama or 'Tidak tercatat',hasil=fields))
            if q:
                g['status']=f"{'Ditutup' if q.ditutup_pada else 'Lengkap' if len(rows)==5 else 'Berjalan'} · {len(rows)}/5 pemeriksaan"
                if not rows:
                    # Parent lama tidak menjanjikan dua bacaan yang tidak
                    # tersimpan. Pertahankan hanya nilai yang benar-benar ada.
                    nama=await db.get(User,q.input_by)
                    fields=[('Kadar air awal',persen(b.kadar_air_awal_persen)),('Biji hijau',kondisi(q.biji_hijau)),('Densiti',kondisi(q.densiti))]
                    if b.kondisi_gabah=='basah':
                        fields.append(('Lamur',('Ya' if q.lamur else 'Tidak')+f' · {q.jumlah_sak_lamur or 0} sak' if q.lamur is not None else 'Belum dicatat'))
                    g['status']='Catatan QC lama · rincian putaran belum tersedia'
                    g['putaran'].append(dict(nomor=None,waktu=q.created_at,petugas=nama.nama if nama else 'Tidak tercatat',hasil=fields))
            jenis='gabah-'+b.kondisi_gabah
        else:
            rows=(await db.execute(select(PkPurchaseQcLog,User.nama)
                .outerjoin(User,User.id==PkPurchaseQcLog.input_by)
                .where(PkPurchaseQcLog.pk_purchase_batch_id==c['id'])
                .order_by(PkPurchaseQcLog.waktu,PkPurchaseQcLog.id))).all()
            for nomor,(s,nama) in enumerate(rows,1):
                fields=[('Kadar air',persen(s.kadar_air)),('Broken',persen(s.broken_persen)),('Susut uji',persen(s.susut_persen))]
                fields.extend(rincian_kualitatif(s,termasuk_kosong=True))
                fields.append(('Catatan lab',s.catatan_lab or 'Belum dicatat'))
                g['putaran'].append(dict(nomor=nomor,waktu=s.waktu,petugas=nama or 'Tidak tercatat',hasil=fields))
            if rows:g['status']=f'{len(rows)} pemeriksaan'
            if not rows:
                lama=await db.scalar(select(PkPurchaseVerification).where(PkPurchaseVerification.pk_purchase_batch_id==c['id']))
                if lama and any(getattr(lama,k) is not None for k in ('kadar_air','broken_persen','penyusutan_persen','butir_kuning','gabah','merang','catatan_lab')):
                    fields=[('Kadar air',persen(lama.kadar_air)),('Broken',persen(lama.broken_persen)),('Susut uji',persen(lama.penyusutan_persen))]
                    fields.extend(rincian_kualitatif(lama,termasuk_kosong=True))
                    fields.append(('Catatan lab',lama.catatan_lab or 'Belum dicatat'))
                    g['status']='Catatan QC lama · rincian putaran belum tersedia'
                    # verified_by/waktu_verifikasi adalah jejak harga lama,
                    # bukan bukti siapa/kapan QC dilakukan.
                    g['putaran'].append(dict(nomor=None,waktu=None,petugas='Tidak tercatat',hasil=fields))
            jenis='pk-luar'
        g['url']=f"/riwayat-qc/{jenis}/{c['kode']}" if rows else None
        kelompok.append(g)
    return kelompok


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


async def riwayat(db, *, g1, g2, tid=None, jasa_ids=None):
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
        if jasa_ids is not None:
            q=q.where(model.jasa_id.in_(jasa_ids))
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
    from app.penggilingan.gudang1.services.timbang_link import nama_pihak, adalah_jasa
    from app.services.jasa import nama_pemilik_banyak
    pemilik = await nama_pemilik_banyak(db, {c['jasa_id'] for cs in hasil.values() for c in cs if c['jasa_id'] is not None})
    for cs in hasil.values():
        for c in cs:
            c['pemilik'] = pemilik.get(c['jasa_id'], 'Pemilik belum diketahui') if c['jasa_id'] else 'Milik pabrik'
    for row in (await db.execute(q, {'ids': sorted(hasil)})).mappings():
        t = dict(row)
        owners = {c['jasa_id'] for c in hasil[t['id']]}
        berat, ket_berat = bobot_diterima(hasil[t['id']])
        t.update(jenis=jenis_tiket(t['jenis_kode']), catatan=hasil[t['id']],
                 # Penanda kepemilikan sudah memiliki kolom sendiri. Nama
                 # asli tidak dipangkas dengan replace("JASA"), sebab itu
                 # bisa menjadi bagian sah dari nama pelanggan.
                 nama=((t.get('nama_pelanggan') or t.get('pihak_nama') or '').strip() or 'Pelanggan belum tercatat') if adalah_jasa(t) else nama_pihak(t),
                 berat_diterima=berat, keterangan_berat=ket_berat,
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
