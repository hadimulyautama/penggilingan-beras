"""Proyeksi baca pemeriksaan armada; penulisan tetap barang_keluar.verifikasi.

Bobot pembanding memakai SQL_REAL_TIKET lama, angka tara memakai snapshot
TeraFlow. Tidak menghitung ulang berat barang atau membagi beda ke pelanggan.
"""
import hashlib
import json
from decimal import Decimal
from sqlalchemy import select,func,text,inspect
from fastapi import HTTPException
from app.database import berzona
from app.models import OutgoingRecord,OutgoingItem,ActivityLog,User,KoreksiPengiriman
from app.services import barang_keluar as bk
from app.penggilingan.gudang1.services.timbang_link import SQL_REAL_TIKET


def waktu(v):
    return berzona(v).strftime('%d/%m/%Y %H:%M %Z') if v else None


async def baca(db,rec):
    await bk._kunci_saldo_keluar(db)
    anggota=[r for r in await bk.anggota_kiriman(db,rec,kunci=True) if r.status!='batal']
    ids=[r.id for r in anggota]
    total=float(await db.scalar(select(func.coalesce(func.sum(OutgoingItem.berat_kg),0))
        .where(OutgoingItem.outgoing_record_id.in_(ids))))
    sidik=await bk.sidik_sumber_muatan(db,rec)
    tiket=None;kemasan=[];pesan_tiket=None;berat=None;catatan_integrasi=None
    raw=None
    if rec.timbangan_transaksi_id:
        row=(await db.execute(text('SELECT * FROM timbangan_transaksi WHERE id=:id FOR UPDATE'),
            {'id':rec.timbangan_transaksi_id})).mappings().first()
        if row:
            raw=dict(row)
            kolom=('id','kode','nomor_polisi','arah','status_tiket','status_transaksi','timbang1_kg','timbang2_kg',
                'berat_kosong_kg','berat_bermuatan_kg','netto_timbangan_kg','tara_lain_kg','total_tara_kg','berat_barang_kg',
                'timbang1_waktu','timbang2_waktu')
            tiket={k:raw.get(k) for k in kolom}
            legacy=raw.get('berat_barang_kg') in (None,0)
            tiket['kompatibilitas_netto']=legacy
            if legacy:tiket['berat_barang_kg']=None
            # Pemisahan komponen tampilan dari total tersimpan saja. Nilai ini
            # tidak dipakai lagi untuk memotong berat barang atau verifikasi.
            tara,lain=raw.get('total_tara_kg'),raw.get('tara_lain_kg')
            tiket['tara_karung_kg']=float(Decimal(str(tara))-Decimal(str(lain))) if tara is not None and lain is not None and tara>=lain>=0 else None
            kemasan=[dict(r) for r in (await db.execute(text('''SELECT id,jenis_kode,catatan,jumlah_karung,tara_per_karung_kg
                FROM timbangan_muatan WHERE transaksi_id=:id ORDER BY urutan,id FOR UPDATE'''),{'id':raw['id']})).mappings()]
            try:
                await bk._tiket_keluar(db,raw['id'])
                nilai=await db.scalar(text(f'SELECT {SQL_REAL_TIKET} FROM timbangan_transaksi t WHERE id=:id'),{'id':raw['id']})
                berat=float(nilai) if nilai is not None else None
            except bk.BarangKeluarError as exc:pesan_tiket=str(exc)
            if await db.run_sync(lambda s:inspect(s.connection()).has_table('timbangan_kiriman')):
                # Ini tanda terima integrasi yang memang tersimpan, bukan
                # status baru. Pesan ditandai sebagai catatan percobaan, karena
                # ada jalur web lama yang tidak menyimpan jawaban integrasinya.
                row=(await db.execute(text('''SELECT jawaban,created_at FROM timbangan_kiriman
                    WHERE jalur=:jalur AND jawaban IS NOT NULL ORDER BY created_at DESC LIMIT 1'''),
                    {'jalur':f"/timbangan/tiket/{raw['id']}"})).mappings().first()
                if row:
                    try:
                        hasil=json.loads(row['jawaban'])
                        if hasil.get('peringatan') and hasil.get('pesan'):
                            catatan_integrasi=dict(pesan=str(hasil['pesan']),waktu=waktu(row['created_at']))
                    except (ValueError,TypeError,AttributeError):pass
        else:pesan_tiket='Tiket armada tidak ditemukan.'
    logs=list((await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='outgoing_records',
        ActivityLog.record_id.in_(ids),ActivityLog.aksi=='barang_keluar_verifikasi',ActivityLog.dibatalkan_pada.is_(None))
        .order_by(ActivityLog.id.desc()))).all())
    jejak_sumber=dict((await db.execute(select(ActivityLog.record_id,func.max(ActivityLog.id)).where(
        ActivityLog.table_name=='outgoing_records',ActivityLog.record_id.in_(ids))
        .group_by(ActivityLog.record_id))).all())
    terbaru={}
    for log in logs:terbaru.setdefault(log.record_id,log)
    jejak=[]
    for r in anggota:
        log=terbaru.get(r.id)
        if r.status!='selesai':continue
        otomatis=bool(log and ' · otomatis ±0,2% setelah tara' in (log.new_value or ''))
        pelaksana=await db.get(User,r.diverifikasi_oleh) if r.diverifikasi_oleh else None
        jejak.append(dict(perintah_id=r.id,kode=r.kode,metode='otomatis' if otomatis else 'manual' if log else 'tidak_tercatat',
            pelaksana=pelaksana.nama if pelaksana else None,waktu=waktu(r.waktu_verifikasi),sebab_selisih=r.sebab_selisih))
    verified=bool(anggota) and all(r.status=='selesai' for r in anggota)
    siap=bool(anggota) and all(r.status=='dimuat' for r in anggota)
    halangan=None
    if not siap and not verified:halangan='Selesaikan muat setiap pelanggan dalam kiriman sebelum verifikasi armada bersama.'
    if pesan_tiket and not halangan:halangan=pesan_tiket
    if rec.timbangan_transaksi_id:
        q=select(OutgoingRecord.id).where(OutgoingRecord.timbangan_transaksi_id==rec.timbangan_transaksi_id,
            OutgoingRecord.status!='batal',OutgoingRecord.id.not_in(ids))
        if await db.scalar(q.limit(1)):
            halangan=halangan or 'Tiket armada sudah tertaut ke pengiriman lain. Satu tiket hanya untuk satu kiriman.'
    auto_note=halangan
    if not verified and not auto_note:
        if not raw:auto_note='Verifikasi otomatis memerlukan tiket armada dan muatan aktual lebih dari nol.'
        else:
            try:
                snapshot=raw.get('pengiriman_snapshot')
                if isinstance(snapshot,str):snapshot=json.loads(snapshot)
                if snapshot is not None and not isinstance(snapshot,dict):
                    raise bk.VerifikasiOtomatisDitahan('Snapshot Pos Timbang tidak sah; periksa data tiket.')
                if snapshot and snapshot.get('sidik_sumber') and snapshot['sidik_sumber']!=sidik:
                    raise bk.MuatanBerubah('Snapshot sumber Pos Timbang berbeda dari muatan saat ini. Baca ulang rincian dan periksa timbang kedua.')
                bk.periksa_angka_otomatis(raw,total)
            except (bk.BarangKeluarError,ValueError) as exc:auto_note=str(exc)
    if not verified and not auto_note:
        auto_note='Belum ada verifikasi otomatis yang tercatat. Timbang tersimpan belum berarti pengiriman sudah terverifikasi; periksa hasil integrasi atau riwayat.'
    angka=bk.angka_verifikasi(total,berat)
    if verified:judul='Terverifikasi otomatis' if jejak and all(j['metode']=='otomatis' for j in jejak) else 'Pengiriman terverifikasi'
    else:judul='Verifikasi masih menunggu' if halangan else 'Perlu pemeriksaan Admin'
    koreksi=list((await db.scalars(select(KoreksiPengiriman).where(KoreksiPengiriman.outgoing_record_id.in_(ids)).order_by(KoreksiPengiriman.waktu.desc()))).all())
    if verified and koreksi:judul='Pengiriman terverifikasi · koreksi manual tercatat; verifikasi awal tetap tersimpan'
    # Semua yang memengaruhi pemeriksaan termasuk bobot/tara tiket. Sidik
    # TeraFlow tetap terpisah dan tidak diganti, agar replay callback tetap sah.
    fingerprint=dict(sidik=sidik,pelanggan=[[r.id,r.status,r.pelanggan_id,r.timbangan_transaksi_id,
        r.sebab_selisih,str(r.waktu_verifikasi),r.diverifikasi_oleh,str(r.waktu_muat),r.dimuat_oleh,jejak_sumber.get(r.id)] for r in anggota],tiket=tiket,kemasan=kemasan,
        audit=[[r.id,terbaru[r.id].id if r.id in terbaru else None] for r in anggota],aturan=angka,
        snapshot_tiket=raw.get('pengiriman_snapshot') if raw else None)
    dasar=hashlib.sha256(json.dumps(fingerprint,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
    return dict(perintah_id=rec.id,kiriman_id=rec.kiriman_id,perintah_ids=ids,tiket=tiket,kemasan=kemasan,
        **angka,dasar=dasar,sidik_sumber=sidik,terverifikasi=verified,boleh_manual=siap and not halangan,
        halangan=halangan,status=judul,catatan_otomatis=None if verified else auto_note,
        catatan_integrasi=None if verified else catatan_integrasi,jejak=jejak,
        sumber_berat='netto_kompatibilitas' if tiket and tiket['kompatibilitas_netto'] else 'berat_barang' if tiket else 'tanpa_tiket')


async def periksa_dasar(db,rec,dasar):
    now=await baca(db,rec)
    if not dasar or now['dasar']!=dasar:
        raise bk.MuatanBerubah('Data pemeriksaan kiriman berubah. Catatan tetap tersedia; baca data terbaru dan konfirmasi ulang.')
    return now


async def periksa_konteks(db,req):
    await bk._kunci_saldo_keluar(db)
    try:rid=int(req.perintah)
    except (TypeError,ValueError):raise HTTPException(400,'Perintah yang mana?') from None
    rec=(await db.scalars(select(OutgoingRecord).where(OutgoingRecord.id==rid).with_for_update()
        .execution_options(populate_existing=True))).first()
    if not rec:raise bk.MuatanBerubah('Kiriman sudah tidak tersedia. Baca data terbaru.')
    now=await periksa_dasar(db,rec,req.dasar)
    if 'kiriman_id' in req.model_fields_set and req.kiriman_id!=rec.kiriman_id:
        raise HTTPException(400,'Kiriman tidak sesuai dengan perintah yang diperiksa.')
    if 'perintah_ids' in req.model_fields_set:
        ids=req.perintah_ids
        if ids is None or len(ids)!=len(set(ids)) or set(ids)!=set(now['perintah_ids']):
            raise HTTPException(400,'Daftar perintah pelanggan tidak sesuai kiriman yang diperiksa.')
    if (req.tiket or '').strip() and int(req.tiket)!=rec.timbangan_transaksi_id:
        raise HTTPException(400,'Tiket berbeda dari armada yang diperiksa. Pilih tiket melalui tindakan armada dan periksa ulang.')
    return now
