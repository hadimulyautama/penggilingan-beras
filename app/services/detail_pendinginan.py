"""Metadata penyajian pendinginan; layanan transaksi dan definisi waktu tetap lama."""
from datetime import datetime

from sqlalchemy import select

from app.database import now_local, berzona
from app.models import Silo, SiloStorage
from app.services import berjalan
from app.services.proses_aktif import _waktu


def _tanggal(nilai):
    if not nilai:
        return None
    try:
        return berzona(datetime.fromisoformat(nilai) if isinstance(nilai, str) else nilai)
    except ValueError:
        return None


def _lama(mulai, selesai):
    return berjalan.lama_kata(max(0, (selesai-mulai).total_seconds())) if mulai and selesai else 'Belum dapat dihitung'


async def lengkapi(db, *, lot, detail, riwayat=None):
    from hmu_core.proses_db import ProsesTerpadu
    sumber = (await db.execute(select(Silo.nama_silo, SiloStorage.tanggal_masuk)
               .join(SiloStorage, SiloStorage.silo_id == Silo.id)
               .where(SiloStorage.drying_lot_id == lot.id)
               .order_by(SiloStorage.tanggal_masuk, SiloStorage.id).limit(1))).first()
    # Rincian riwayat lama juga menyimpan tanggal pembelian dan presisi batch.
    # Lengkapi penyajian tanpa mengubah bobot total dari helper proses.
    from app.penggilingan.gudang1.services.drying import _lot_batches
    from app.penggilingan.gudang1.services.bobot import dari_batch
    from app.services.bahan_silo import kg_rinci
    bahan = {b.kode_batch: b for b in await _lot_batches(db, lot.id)}
    for bagian in detail['bagian']:
        if bagian['judul'] != 'Asal bahan gabah':
            continue
        for baris in bagian['baris']:
            batch = bahan.get(baris[0])
            if batch is None:
                continue
            bobot = dari_batch(batch)
            if bobot.pasti and bobot.kg is not None:
                baris[2] = f'{batch.kondisi_gabah} · {kg_rinci(bobot.kg)}'
            tanggal = batch.tanggal_pembelian
            waktu = berzona(batch.waktu_pembelian)
            if tanggal and (waktu is None or waktu.date() != tanggal):
                baris[4] += f' · Tanggal pembelian {tanggal:%d/%m/%Y}'
    selesai = lot.waktu_selesai_pendinginan
    mulai = lot.waktu_mulai_pendinginan or lot.waktu_selesai_pengeringan
    kini = now_local()
    lokasi = f'Sudah dipindah ke {sumber[0]}' if sumber else f'Masih di {detail["dryer"]}'
    status = 'Sudah di silo' if sumber else 'Sudah dingin' if selesai else 'Sedang didinginkan'
    terpadu = await db.scalar(select(ProsesTerpadu).where(
        ProsesTerpadu.aplikasi=='produksi', ProsesTerpadu.tabel_sumber=='drying_cooling',
        ProsesTerpadu.id_sumber==str(lot.id)))
    arsip = (terpadu.metadata_domain or {}).get('putaran_sebelumnya', []) if terpadu else []
    putaran = []
    for nomor, row in enumerate(arsip, 1):
        a, b = _tanggal(row.get('mulai')), _tanggal(row.get('selesai'))
        putaran.append(dict(nomor=nomor, mulai=_waktu(a), selesai=_waktu(b), lama=_lama(a,b), aktif=False))
    putaran.append(dict(nomor=len(putaran)+1 if terpadu else None, mulai=_waktu(mulai),
                        selesai=_waktu(selesai) if selesai else 'Belum dinyatakan',
                        lama=_lama(mulai, selesai or kini), aktif=selesai is None))
    lama = _lama(mulai, selesai or kini)
    detail.update(lot_id=lot.id, riwayat_putaran_lengkap=terpadu is not None, status=status, tahap=3 if sumber else 2 if selesai else 1,
                  lokasi=lokasi, pindah_waktu=_waktu(sumber[1]) if sumber else 'Belum dipindahkan',
                  dingin_waktu=_waktu(selesai) if selesai else 'Belum dinyatakan',
                  putaran=putaran, lama_pendinginan=lama, laporan_tersedia=selesai is not None,
                  statistik_pendinginan=[('Bahan dalam lot',detail['statistik'][0][1]),
                    ('Lama pendinginan terakhir' if selesai else 'Lama pendinginan saat ini',lama),
                    ('Lokasi gabah',sumber[0] if sumber else detail['dryer'])],
                  waktu_pendinginan=[('Selesai pengeringan',_waktu(lot.waktu_selesai_pengeringan)),
                    ('Mulai pendinginan saat ini',_waktu(mulai)),('Lama pendinginan',lama),
                    ('Dinyatakan dingin',_waktu(selesai) if selesai else 'Belum dinyatakan'),
                    ('Putaran pendinginan',f'{len(putaran)} putaran' if terpadu else 'Belum diketahui · data lama')])
    if selesai and not sumber:
        detail['waktu_pendinginan'].append(('Sejak pernyataan dingin', _lama(selesai, kini)))
    detail['fakta'] = [(label, lama if label in ('Lama pendinginan', 'Waktu berlalu') else nilai) for label, nilai in detail['fakta']]
    detail['fakta'] += [('Durasi pengeringan', (riwayat.lama_kering or 'Belum dapat dihitung') if riwayat else _lama(lot.waktu_mulai_pengeringan,lot.waktu_selesai_pengeringan)),
                        ('Durasi total', (riwayat.lama_total or 'Belum dapat dihitung') if riwayat else _lama(lot.waktu_mulai_pengeringan,kini)),
                        ('Dinyatakan dingin',detail['dingin_waktu']),('Lokasi gabah',lokasi),
                        ('Waktu pindah ke silo',detail['pindah_waktu'])]
    return detail
