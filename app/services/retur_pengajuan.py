"""Pengajuan retur beridentitas asal; seluruh penulis mengunci pengiriman dulu.

Kunci header asal membuat pemeriksaan sisa kumulatif serial, termasuk dua
penerimaan berbeda pada item yang sama. Tiket ikut dikunci sebelum diperiksa;
indeks unik lama tetap menjadi pagar terakhir penerimaan ganda.
"""
from decimal import Decimal

from sqlalchemy import select, text

from app.database import now_local
from app.models import (CustomerReturn, KemasanTara, OutgoingItem, OutgoingRecord,
                        PackageSize, PackagingMaterial, ProductSku)
from app.penggilingan.inventory.models import ReturPemeriksaanLog, ReturRincian
from app.services.retur import angka
from app.services.retur_pemeriksaan import BarisBobot, periksa_bobot


async def kunci_asal(db, pengiriman_id):
    asal = await db.scalar(select(OutgoingRecord).where(
        OutgoingRecord.id == pengiriman_id).with_for_update().execution_options(populate_existing=True))
    if not asal or asal.status != 'selesai':
        raise ValueError('Retur hanya dapat diajukan dari pengiriman yang sudah keluar.')
    if not asal.pelanggan_id:
        raise ValueError('Pengiriman belum memiliki identitas pelanggan yang sah.')
    from app.models import Jasa
    if await db.scalar(select(OutgoingItem.id).join(Jasa, Jasa.id == OutgoingItem.jasa_id).where(
            OutgoingItem.outgoing_record_id == asal.id,
            Jasa.pelanggan_id != asal.pelanggan_id).limit(1)):
        raise ValueError('Identitas pemilik item pengiriman perlu diperiksa.')
    return asal


async def kunci_tiket(db, tiket_id, pelanggan_id):
    tiket = (await db.execute(text('''
        SELECT t.*, p.nama_pelanggan FROM timbangan_transaksi t
        LEFT JOIN pelanggan p ON p.id=t.pelanggan_id
        WHERE t.id=:id FOR UPDATE OF t
    '''), {'id': tiket_id})).mappings().first()
    if (not tiket or tiket['arah'] != 'RETUR_MASUK'
            or tiket['status_transaksi'] != 'AKTIF'
            or tiket['status_tiket'] not in ('TERBUKA', 'SELESAI')
            or tiket['pelanggan_id'] != pelanggan_id):
        raise ValueError('Pilih tiket RTP aktif milik pelanggan pengiriman ini.')
    if await db.scalar(select(CustomerReturn.id).where(
            CustomerReturn.timbangan_transaksi_id == tiket_id)):
        raise ValueError('Tiket sudah digunakan untuk penerimaan retur.')
    for nama in ('timbang1_kg',):
        if tiket[nama] is None or angka(tiket[nama], 'Bobot timbang pertama', 1_000_000, '.01') <= 0:
            raise ValueError('Data timbang pertama tiket belum sah.')
    if tiket['status_tiket'] == 'SELESAI':
        for nama in ('timbang2_kg', 'berat_barang_kg'):
            if tiket[nama] is None or angka(tiket[nama], 'Bobot tiket', 1_000_000, '.01') <= 0:
                raise ValueError('Data timbang kedua tiket belum sah.')
    koreksi = (await db.execute(text('''
        SELECT id,akun_id,akun_nama,waktu,ringkasan FROM timbangan_audit
        WHERE entitas='transaksi' AND entitas_id=:kode AND aksi='KOREKSI'
        ORDER BY id DESC LIMIT 1
    '''), {'kode': tiket['kode']})).mappings().first()
    return dict(tiket, koreksi_timbang=(dict(id=koreksi['id'], akun_id=koreksi['akun_id'],
        nama=koreksi['akun_nama'], waktu=str(koreksi['waktu']), alasan=koreksi['ringkasan'])
        if koreksi else None))


async def sisa_asal(db, pengiriman_id, *, kecuali=None):
    """Termasuk pengajuan belum diterima: bukan sekadar stok yang sudah masuk."""
    items = (await db.scalars(select(OutgoingItem).where(
        OutgoingItem.outgoing_record_id == pengiriman_id).order_by(OutgoingItem.id)
        .execution_options(populate_existing=True))).all()
    terpakai = {i.id: {'karung': 0, 'kg': Decimal('0'),
                       'diterima_karung': 0, 'diterima_kg': Decimal('0')} for i in items}
    pengajuan = (await db.scalars(select(ReturRincian).where(
        ReturRincian.outgoing_record_id == pengiriman_id))).all()
    for r in pengajuan:
        if r.id == kecuali or r.status_pemeriksaan == 'dibatalkan':
            continue
        for m in r.muatan:
            identitas = m.get('outgoing_item_id')
            if identitas not in terpakai:
                raise ValueError('Hubungan rincian retur perlu diperiksa administrator.')
            terpakai[identitas]['karung'] += m['jumlah_karung']
            terpakai[identitas]['kg'] += Decimal(m['berat_kg'])
            if r.customer_return_id:
                terpakai[identitas]['diterima_karung'] += m['jumlah_karung']
                terpakai[identitas]['diterima_kg'] += Decimal(m['berat_kg'])
    return items, terpakai


async def susun_muatan(db, items, terpakai, jumlah, kemasan_item=None, karung_item=None):
    """Identitas/pemilik selalu dari item asal; klien hanya mengirim jumlah.

    Barang jadi dihitung ukuran × karung seperti penerimaan lama. Bahan dan
    curah tetap memakai kg. PK/gabah mencatat jumlah karung fisik yang kembali;
    angka ini untuk toleransi, tidak menggantikan bobot rincian dalam kg.
    """
    if set(jumlah) - {i.id for i in items}:
        raise ValueError('Item bukan bagian dari pengiriman asal.')
    hasil = []
    for item in items:
        nilai = angka(jumlah.get(item.id, '0'), 'Jumlah retur', 1_000_000, '.01')
        if nilai == 0:
            continue
        sku = None
        tara = None
        material_id = ukuran_id = None
        if item.item_type == 'finished_goods':
            if nilai != int(nilai):
                raise ValueError('Jumlah retur barang kemasan harus karung bulat.')
            count = int(nilai)
            sku = await db.get(ProductSku, item.product_sku_id)
            ukuran = await db.get(PackageSize, sku.package_size_id) if sku else None
            if not ukuran or ukuran.ukuran_kg <= 0:
                raise ValueError('Ukuran kemasan barang asal tidak sah.')
            berat = Decimal(str(ukuran.ukuran_kg)) * count
            material_id, ukuran_id = sku.packaging_material_id, sku.package_size_id
        elif item.item_type in ('pk_langsung', 'pk_g2', 'gabah_langsung', 'byproduct_curah'):
            if ((item.item_type == 'pk_langsung' and item.milling_process_id is None)
                    or (item.item_type == 'gabah_langsung' and item.gabah_kering_lot_id is None)
                    or (item.item_type == 'byproduct_curah' and not item.jenis_byproduct)):
                raise ValueError('Identitas sumber barang pengiriman belum lengkap.')
            berat = nilai
            count = 0
            if item.item_type != 'byproduct_curah':
                n = angka((karung_item or {}).get(item.id), 'Jumlah karung retur', 100_000, '1')
                if n <= 0 or n != int(n):
                    raise ValueError('Isi jumlah karung fisik yang kembali untuk PK/gabah.')
                count = int(n)
            if count:
                ukuran_id = await db.scalar(select(PackageSize.id).where(PackageSize.ukuran_kg == 50, PackageSize.aktif.is_(True)))
                if item.item_type in ('pk_langsung', 'pk_g2'):
                    material_id = await db.scalar(select(PackagingMaterial.id).where(
                        PackagingMaterial.kode == 'karung_pk', PackagingMaterial.aktif.is_(True)))
                else:
                    # Pengiriman gabah lama tidak menyimpan jenis karung.
                    # Jenis karung penerimaan harus dipilih secara eksplisit;
                    # tidak menebak dari daftar tara yang kebetulan tersedia.
                    dipilih = (kemasan_item or {}).get(item.id)
                    if dipilih:
                        material_id = await db.scalar(select(PackagingMaterial.id).where(
                            PackagingMaterial.id == int(dipilih), PackagingMaterial.aktif.is_(True)))
                        if not material_id:
                            raise ValueError('Jenis karung penerimaan tidak tersedia.')
        else:
            raise ValueError('Jenis item pengiriman belum memiliki aturan penerimaan retur.')
        if (item.jumlah_karung is not None
                and count + terpakai[item.id]['karung'] > item.jumlah_karung):
            raise ValueError('Jumlah retur kumulatif melebihi jumlah karung yang dikirim.')
        if berat + terpakai[item.id]['kg'] > Decimal(str(item.berat_kg)):
            raise ValueError('Jumlah retur kumulatif melebihi berat yang dikirim.')
        if count and material_id and ukuran_id:
            tara = await db.scalar(select(KemasanTara.tara_per_karung_kg).where(
                KemasanTara.packaging_material_id == material_id,
                KemasanTara.package_size_id == ukuran_id))
        hasil.append(dict(outgoing_item_id=item.id, item_type=item.item_type,
            sku_id=item.product_sku_id, quality_id=item.rice_quality_standard_id,
            jasa_id=item.jasa_id, jumlah_karung=count, berat_kg=str(berat),
            packaging_material_id=material_id, package_size_id=ukuran_id,
            tara_per_karung_kg='0',
            # Nilai ini hanya untuk pemeriksaan, tidak dikirim sebagai
            # potongan tara ke Pos Timbang atau ke penerimaan stok.
            tara_toleransi_kg=str(tara) if tara is not None else None))
    if not hasil:
        raise ValueError('Isi jumlah retur lebih dari nol pada minimal satu barang.')
    if sum(m['jumlah_karung'] for m in hasil) > 100_000:
        raise ValueError('Total jumlah karung melampaui batas satu tiket timbang.')
    return hasil


def cuplikan(rincian):
    return dict(tiket_id=rincian.timbangan_transaksi_id, muatan=rincian.muatan,
                hasil=rincian.hasil_pemeriksaan, wajib_manual=rincian.wajib_manual,
                pengiriman_id=rincian.outgoing_record_id, status=rincian.status_pemeriksaan)


async def batalkan(db, *, identitas, pelaku, alasan):
    """Melepas klaim jumlah draf yang belum menjadi penerimaan; tanpa stok."""
    from app.peran import can_see_financials
    if not can_see_financials(pelaku):
        raise ValueError('Pembatalan pengajuan hanya tersedia bagi pengguna berwenang.')
    awal = await db.get(ReturRincian, identitas)
    if not awal or not awal.outgoing_record_id:
        raise ValueError('Pengajuan retur tidak tersedia.')
    await db.scalar(select(OutgoingRecord).where(
        OutgoingRecord.id == awal.outgoing_record_id).with_for_update())
    rincian = await db.scalar(select(ReturRincian).where(ReturRincian.id == identitas)
        .with_for_update().execution_options(populate_existing=True))
    if rincian.customer_return_id:
        raise ValueError('Penerimaan sudah masuk stok dan tidak dapat dibatalkan sebagai pengajuan.')
    if not alasan or not alasan.strip() or len(alasan) > 500:
        raise ValueError('Isi alasan pembatalan, maksimal 500 karakter.')
    if rincian.status_pemeriksaan == 'dibatalkan':
        return rincian
    sebelum = cuplikan(rincian)
    rincian.status_pemeriksaan = 'dibatalkan'
    db.add(ReturPemeriksaanLog(retur_rincian_id=rincian.id, pelaku_id=pelaku.id,
        waktu=now_local(), aksi='dibatalkan', alasan=alasan.strip(), sebelum=sebelum,
        sesudah=cuplikan(rincian)))
    return rincian


async def simpan(db, *, pengiriman_id, tiket_id, jumlah, pelaku_id,
                 pengajuan_id=None, alasan=None, catatan=None, catatan_item=None,
                 kemasan_item=None, karung_item=None):
    """Tidak commit: pengajuan dan pemeriksaan disimpan dalam transaksi pemanggil."""
    from app.models import User
    from app.peran import can_see_financials
    pelaku = await db.get(User, pelaku_id)
    if not pelaku or pelaku.status != 'aktif' or not can_see_financials(pelaku):
        raise ValueError('Pengajuan retur hanya dapat disimpan oleh pengguna berwenang.')
    asal = await kunci_asal(db, pengiriman_id)
    rincian = None
    sebelum = None
    if pengajuan_id:
        rincian = await db.scalar(select(ReturRincian).where(
            ReturRincian.id == pengajuan_id,
            ReturRincian.outgoing_record_id == asal.id).with_for_update())
        if not rincian or rincian.customer_return_id or rincian.status_pemeriksaan == 'dibatalkan':
            raise ValueError('Pengajuan tidak dapat dikoreksi.')
        if not alasan or not alasan.strip() or len(alasan) > 500:
            raise ValueError('Isi alasan koreksi, maksimal 500 karakter.')
        sebelum = cuplikan(rincian)
    tiket = await kunci_tiket(db, tiket_id, asal.pelanggan_id)
    pemakai = await db.scalar(select(ReturRincian).where(
        ReturRincian.timbangan_transaksi_id == tiket_id))
    if pemakai and (not rincian or pemakai.id != rincian.id):
        if rincian or pemakai.outgoing_record_id is not None:
            raise ValueError('Tiket sudah terhubung dengan rincian penerimaan lain.')
        # Rincian lama boleh dihubungkan hanya melalui pilihan asal dan item
        # yang eksplisit. Tidak ada pencocokan otomatis berdasarkan teks/SKU.
        rincian = pemakai
        sebelum = cuplikan(rincian)
        rincian.outgoing_record_id = asal.id
        pengajuan_id = rincian.id
    items, terpakai = await sisa_asal(db, asal.id, kecuali=pengajuan_id)
    muatan = await susun_muatan(db, items, terpakai, jumlah, kemasan_item, karung_item)
    for m in muatan:
        note = (catatan_item or {}).get(m['outgoing_item_id'], '')
        if len(note) > 200:
            raise ValueError('Catatan barang maksimal 200 karakter.')
        m['catatan_item'] = note.strip()
    if catatan and len(catatan) > 500:
        raise ValueError('Catatan maksimal 500 karakter.')
    if rincian is None:
        rincian = ReturRincian(outgoing_record_id=asal.id,
            timbangan_transaksi_id=tiket_id, muatan=muatan, input_by=pelaku_id,
            wajib_manual=False)
        db.add(rincian)
    rincian.muatan = muatan
    rincian.timbangan_transaksi_id = tiket_id
    rincian.catatan = catatan
    await db.flush()
    await periksa(db, rincian, tiket=tiket, pelaku_id=pelaku_id,
                  aksi='koreksi' if sebelum else 'pengajuan',
                  sebelum=sebelum, alasan=alasan)
    return rincian


async def periksa(db, rincian, *, tiket, pelaku_id=None, aksi='pemeriksaan',
                   sebelum=None, alasan=None):
    """Menyimpan hasil pemeriksaan; penerimaan stok dilakukan tahap berikutnya."""
    sebelum = sebelum or cuplikan(rincian)
    # Baca ulang master pada setiap pemeriksaan, bukan percaya tara kiriman
    # peramban ataupun salinan pengajuan sebelum master dikoreksi.
    muatan = []
    for m in rincian.muatan:
        tara = None
        if m['jumlah_karung']:
            tara = await db.scalar(select(KemasanTara.tara_per_karung_kg).where(
                KemasanTara.packaging_material_id == m['packaging_material_id'],
                KemasanTara.package_size_id == m['package_size_id']))
        muatan.append(dict(m, tara_toleransi_kg=str(tara) if tara is not None else None))
    rincian.muatan = muatan
    hasil = periksa_bobot([BarisBobot(Decimal(m['berat_kg']), m['jumlah_karung'],
        Decimal(m['tara_toleransi_kg']) if m['tara_toleransi_kg'] is not None else None)
        for m in muatan], tiket_selesai=tiket['status_tiket'] == 'SELESAI',
        berat_tiket_kg=tiket['berat_barang_kg'],
        pernah_selisih_besar=rincian.wajib_manual)
    rincian.wajib_manual = hasil.wajib_manual
    rincian.status_pemeriksaan = hasil.status
    rincian.hasil_pemeriksaan = dict(status=hasil.status, alasan=hasil.alasan,
        berat_rincian_kg=str(hasil.berat_rincian_kg),
        selisih_kg=str(hasil.selisih_kg) if hasil.selisih_kg is not None else None,
        toleransi_kg=str(hasil.toleransi_kg) if hasil.toleransi_kg is not None else None,
        timbang1_kg=str(tiket['timbang1_kg']), timbang2_kg=str(tiket['timbang2_kg']),
        berat_tiket_kg=str(tiket['berat_barang_kg']), koreksi_timbang=tiket.get('koreksi_timbang'))
    sesudah = cuplikan(rincian)
    if sebelum != sesudah:
        db.add(ReturPemeriksaanLog(retur_rincian_id=rincian.id,
            pelaku_id=pelaku_id, waktu=now_local(), aksi=aksi, alasan=alasan,
            sebelum=sebelum, sesudah=sesudah))
    return hasil
