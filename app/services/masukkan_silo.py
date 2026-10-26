"""Bentuk stok untuk formulir, tanpa buku stok atau pemindahan kedua.

Identitas pilihan = intake dan bentuk yang tercatat. Dua pilihan PK sendiri
membaca bagian dari saldo yang sama, bukan menggandakan seluruh partai.
PK luar tanpa N tetap data lama, bukan bukti bahwa barangnya curah.
"""
from decimal import Decimal
from sqlalchemy import select, func
from app.models import (PkGudang2Intake, PkPurchaseBatch, PkTumpukanToSilo,
                        InternalTransfer, MillingProcess)


def urai(nilai):
    bagian = str(nilai or '').strip().split(':')
    if not bagian[0].isdigit() or len(bagian) > 2:
        raise ValueError('Pilih sumber stok yang sah.')
    bentuk = bagian[1] if len(bagian) == 2 else None
    if bentuk not in (None, 'karung', 'curah', 'lama'):
        raise ValueError('Bentuk sumber stok tidak dikenali.')
    return int(bagian[0]), bentuk


async def sumber(db, intake, *, jumlah_partai=None):
    """Saldo terkini dari pembaca lama; tidak melengkapi N saat pratinjau."""
    from app.penggilingan.gudang2.service import _sisa_tumpukan_intake, acuan_karung_surat_jalan
    from app.penggilingan.gudang2.karung import bobot_per_karung
    from app.penggilingan.gudang1.services.bobot import dari_batch
    from app.services.jasa import nama_pemilik
    from app.services.pk_50 import bagi, UKURAN
    if intake is None or intake.tujuan != 'ditumpuk':
        raise ValueError('Sumber tumpukan tidak ditemukan. Muat ulang pilihan.')
    saldo = await _sisa_tumpukan_intake(db, intake.id)
    pemilik = await nama_pemilik(db, intake.jasa_id) if intake.jasa_id else 'Milik pabrik'
    batch = await db.get(PkPurchaseBatch, intake.pk_purchase_batch_id) if intake.pk_purchase_batch_id else None
    transfer = await db.get(InternalTransfer, intake.internal_transfer_id) if intake.internal_transfer_id else None
    proc = await db.get(MillingProcess, transfer.milling_process_id) if transfer else None
    kode = batch.kode_batch if batch else proc.kode_proses if proc else f'Tumpukan #{intake.id}'
    final = dari_batch(batch).pasti if batch else intake.bobot_final
    umum = dict(intake_id=intake.id, kode=kode, pemilik=pemilik or 'Pemilik belum tercatat',
        asal='PK beli luar' if batch else 'Hasil penggilingan sendiri' if transfer else 'Catatan lama',
        bobot_final=bool(final), saldo_partai_kg=saldo,
        berat_awal=batch.berat_total_kg if batch else intake.berat_kg,
        karung_awal=batch.jumlah_karung if batch else transfer.jumlah_karung if transfer else None,
        tiket_id=batch.timbangan_transaksi_id if batch else None, bisa_lengkapi=False,
        jumlah_partai=None, bagian_karung_kg=None)
    sudah = await db.scalar(select(func.coalesce(func.sum(PkTumpukanToSilo.jumlah_karung), 0))
        .where(PkTumpukanToSilo.pk_gudang2_intake_id == intake.id))
    if batch and not batch.jumlah_karung:
        ada = await db.scalar(select(PkTumpukanToSilo.id).where(
            PkTumpukanToSilo.pk_gudang2_intake_id == intake.id).limit(1))
        umum['bisa_lengkapi'] = ada is None
        if jumlah_partai is not None and ada is None:
            if isinstance(jumlah_partai, bool) or jumlah_partai <= 0 or int(jumlah_partai) != jumlah_partai:
                raise ValueError('Jumlah karung separtai harus bilangan bulat lebih dari nol.')
            # Layanan ini membuat acuan salinan. Tidak mengubah baris, pemilik,
            # atau ledger. Penulisan surat jalan tetap di layanan pindah lama.
            batch = await acuan_karung_surat_jalan(db, batch, int(jumlah_partai))
            saldo = None if batch.berat_total_kg is None else float(batch.berat_total_kg)
            umum.update(saldo_partai_kg=saldo, bobot_final=dari_batch(batch).pasti,
                         jumlah_partai=int(jumlah_partai))
    if batch and batch.jumlah_karung:
        k = max(0, batch.jumlah_karung - int(sudah))
        r = bobot_per_karung(batch)
        if r is not None and saldo is not None:
            k = max(0, min(k, int((Decimal(str(saldo)) + Decimal('0.000001')) // r)))
            umum['bagian_karung_kg'] = float(max(Decimal(0), Decimal(str(saldo)) - k*r))
        # Bagian karung tetap disebut, bukan diubah menjadi partai curah.
        # Ketika tak ada karung utuh, jalur kg lama tetap bisa menghabiskannya.
        bentuk = 'karung' if k or saldo is None else 'lama'
        return [{**umum, 'value':f'{intake.id}:{bentuk}', 'bentuk':bentuk,
                 'saldo_kg':saldo, 'karung':k, 'rasio_kg':None if r is None else float(r)}]
    if transfer and transfer.jumlah_karung is not None and transfer.berat_curah_kg is not None and saldo is not None:
        k, c = bagi(max(0, saldo))
        return [{**umum, 'value':f'{intake.id}:{bentuk}', 'bentuk':bentuk,
                 'saldo_kg':float(kg), 'karung':n, 'rasio_kg':float(UKURAN) if bentuk=='karung' else None}
                for bentuk,kg,n in [('karung',k*UKURAN,k),('curah',c,None)] if kg > 0]
    return [{**umum,'value':f'{intake.id}:lama','bentuk':'lama',
             'saldo_kg':saldo,'karung':None,'rasio_kg':None}]


def pilih(daftar, bentuk):
    # Bentuk lama boleh membaca karung yang baru dilengkapi dari surat jalan;
    # pemeriksaan fisik jumlahnya tetap dilakukan oleh layanan yang sama.
    cocok = next((s for s in daftar if s['bentuk']==bentuk), None)
    if cocok is None and bentuk=='lama' and len(daftar)==1 and daftar[0]['jumlah_partai'] is not None:
        cocok=daftar[0]
    if cocok is None:
        raise ValueError('Bentuk stok ini sudah tidak tersedia. Periksa saldo terbaru dan pilih sumber yang benar.')
    return cocok


def periksa(jenis, *, jumlah_karung=None, berat_kg=None):
    """Penjaga formulir eksplisit; tidak mengubah kontrak kosong klien lama."""
    if jenis['bentuk']=='karung':
        try:
            k=Decimal(str(jumlah_karung))
        except ArithmeticError:
            k=Decimal('NaN')
        if jumlah_karung is None or isinstance(jumlah_karung,bool) or not k.is_finite() or k<=0 or k!=k.to_integral_value():
            raise ValueError('Isi jumlah karung bulat lebih dari nol; kosong tidak berarti seluruh partai.')
        if jumlah_karung>jenis['karung']:
            raise ValueError(f"Saldo terbaru tinggal {jenis['karung']} karung utuh. Periksa kembali jumlah yang dimasukkan.")
        if berat_kg is not None:
            raise ValueError('Sumber berkarung memakai jumlah karung, bukan isian kg bersamaan.')
        return None if jenis['rasio_kg'] is None else float(k*Decimal(str(jenis['rasio_kg'])))
    if berat_kg is None:
        raise ValueError('Isi berat lebih dari nol; kosong tidak berarti seluruh sisa.')
    from app.services.angka import angka_wajar
    nilai=angka_wajar(berat_kg,'Berat yang dimasukkan')
    if jumlah_karung is not None:
        raise ValueError('Sumber kg tidak menerima jumlah karung bersamaan.')
    saldo=jenis['saldo_kg']
    if saldo is None:
        raise ValueError('Bobot sumber belum diketahui. Tunggu timbang atau lengkapi data karung sesuai jalur lama.')
    # Curah PK sendiri memakai penjaga unit50 yang sudah berlaku (tanpa
    # toleransi tambahan). Kg data lama mengikuti toleransi lama sebesar1kg.
    from app.penggilingan.gudang2.service import TOLERANSI_PINDAH_KG
    toleransi=0 if jenis['bentuk']=='curah' else TOLERANSI_PINDAH_KG
    if nilai>saldo+toleransi:
        raise ValueError(f'Saldo terbaru tinggal {saldo:g} kg. Periksa kembali berat yang dimasukkan.')
    return min(nilai,saldo)
