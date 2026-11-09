"""Koreksi satu kontribusi hasil; pengemasan hanya pembacaan saldo lama.

PolishingOutputLog sejak migrasi 0060 menyimpan tambahan, walaupun formulir
operator menerima total kumulatif. Sumber tersebut tidak diperlakukan sebagai
angka kumulatif yang harus dikurangkan seluruhnya dari hasil proses.
"""
import hmac,json,re
from decimal import Decimal as D
from sqlalchemy import select
from app.models import PolishingProcess,PolishingOutputLog,Peristiwa,ActivityLog
from app.services import peristiwa as buku,koreksi_bahan_berjalan as aktif,pengemasan_otomatis as auto
from app.services.koreksi_pengiriman import cap as tanda
from app.penggilingan.gudang2 import polishing as p
from hmu_identitas import peran as P
JENIS='koreksi_asal_pengemasan'

async def batal_ids(db,pid):
    q=select(Peristiwa.muatan['catatan_id'].as_integer()).where(Peristiwa.jenis==JENIS,
        Peristiwa.muatan['proses_id'].as_integer()==pid,Peristiwa.muatan['aksi'].as_string()=='batal')
    return set((await db.scalars(q)).all())

async def izin(db,user,proc,aksi='ubah'):
    await aktif.izin(db,user,'sosoh')
    if proc.status not in ('proses','selesai'):raise ValueError('Status proses tidak mendukung koreksi hasil.')
    if (proc.status=='selesai' or aksi=='batal') and not P.admin_keatas(user.role):
        raise PermissionError('Koreksi hasil selesai dan pembatalan catatan memerlukan Admin/Super Admin pada peran efektifnya.')

async def ambil(db,pid,kind,user,aksi='ubah',lock=False):
    if kind not in auto.stok._UKURAN_KEMASAN_OTOMATIS:raise ValueError('Jenis ini tidak memiliki ringkasan pengemasan otomatis yang didukung.')
    if lock:
        from app.services.barang_keluar import _kunci_saldo_keluar
        await _kunci_saldo_keluar(db)
    q=select(PolishingProcess).where(PolishingProcess.id==pid).execution_options(populate_existing=True)
    proc=await db.scalar(q.with_for_update() if lock else q)
    if not proc:raise ValueError('Proses tidak ditemukan.')
    await izin(db,user,proc,aksi)
    return proc

async def data(db,pid,kind,user,*,sebelum=None,riwayat_sebelum=None):
    proc=await ambil(db,pid,kind,user)
    q=select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==pid,PolishingOutputLog.jenis==kind)
    if sebelum:q=q.where(PolishingOutputLog.id<sebelum)
    rows=list((await db.scalars(q.order_by(PolishingOutputLog.id.desc()).limit(26))).all())
    ids=await batal_ids(db,pid)
    eq=select(Peristiwa).where(Peristiwa.jenis==JENIS,Peristiwa.muatan['proses_id'].as_integer()==pid,Peristiwa.muatan['jenis'].as_string()==kind)
    if riwayat_sebelum:eq=eq.where(Peristiwa.id<riwayat_sebelum)
    events=list((await db.scalars(eq.order_by(Peristiwa.id.desc()).limit(31))).all())
    return dict(proc=proc,jenis=kind,ringkasan=await auto.ringkasan(db,proc,kind),
        awal_catatan=[dict(id=r.id,kg=float(r.berat_kg),batal=r.id in ids) for r in rows[:25]],
        catatan=[dict(id=r.id,kg=float(r.berat_kg),waktu=r.waktu_update,pencatat=r.input_by,spek=r.spek,batal=r.id in ids) for r in rows[:25]],
        berikut=rows[24].id if len(rows)>25 else None,riwayat=events[:30],riwayat_berikut=events[29].id if len(events)>30 else None,boleh_batal=P.admin_keatas(user.role))

async def rencana(db,pid,kind,user,req):
    aksi=req.get('aksi')
    if aksi not in ('ubah','batal'):raise ValueError('Pilih koreksi atau pembatalan catatan.')
    if not req.get('alasan','').strip() or len(req['alasan'])>2000:raise ValueError('Alasan wajib diisi, maksimal 2.000 karakter.')
    proc=await ambil(db,pid,kind,user,aksi,lock=True)
    rows=list((await db.scalars(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==pid).order_by(PolishingOutputLog.id).with_for_update().execution_options(populate_existing=True))).all())
    src=next((x for x in rows if x.id==req.get('catatan_id') and x.jenis==kind),None)
    if not src:raise ValueError('Catatan bukan milik proses dan jenis hasil yang dipilih.')
    if src.id in await batal_ids(db,pid):raise ValueError('Catatan ini sudah dibatalkan; tidak boleh diproses atau dipulihkan ulang.')
    old=D(str(src.berat_kg))
    if not old.is_finite() or old<0:raise ValueError('Bobot historis belum dapat dibuktikan. Rekonsiliasi data asal dahulu.')
    new=D(0) if aksi=='batal' else aktif.angka(req.get('kg'),'Bobot yang benar',presisi=2)
    if old==new and aksi!='batal':raise ValueError('Tidak ada perubahan bobot efektif catatan terpilih.')
    totals=await auto.stok.output_sosoh(db,pid)
    before=await auto.ringkasan(db,proc,kind)
    # Sidik operasional mencakup saldo/relasi, bukan data timbang.
    source=buku.bersih(aktif.raw(src))
    changed={k:totals.get(k,0) for k in set(await p.jenis_hasil(db, termasuk_nonaktif=True))}
    changed[kind]=float(D(str(changed[kind]))-old+new)
    last_event=await db.scalar(select(Peristiwa.id).where(Peristiwa.jenis==JENIS,Peristiwa.muatan['catatan_id'].as_integer()==src.id).order_by(Peristiwa.id.desc()).limit(1))
    version=await db.scalar(select(ActivityLog.id).where(ActivityLog.table_name=='polishing_output_logs',ActivityLog.record_id==src.id).order_by(ActivityLog.id.desc()).limit(1))
    snapshot_before=dict(catatan=source,ringkasan=before,hasil=totals,status=proc.status)
    sp=await db.begin_nested()
    try:
        if old!=new:
            await p.koreksi_hasil_sosoh(db,user=user,process_id=pid,perubahan=changed,
                dasar={k:totals.get(k,0) for k in set(await p.jenis_hasil(db, termasuk_nonaktif=True))},alasan=req['alasan'],
                berjalan=proc.status=='proses',simpan=False,catatan_id=src.id)
        after=await auto.ringkasan(db,proc,kind)
    finally:await sp.rollback()
    result=buku.bersih(dict(versi_sebelumnya=last_event,versi_catatan=version,pemeriksa_id=user.id,peran_efektif=user.role,proses_id=pid,jenis=kind,catatan_id=req['catatan_id'],aksi=aksi,
        alasan=req['alasan'].strip(),sebelum=snapshot_before,
        sesudah=dict(kg=float(new),ringkasan=after,hasil=changed),
        hasil_lain=float(D(str(totals.get(kind,0)))-old),
        semantik='Tambahan hasil; total kumulatif formulir operator disimpan sebagai selisih oleh layanan lama.'))
    return result

async def simpan(db,pid,kind,user,req,*,dasar,kunci):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}',kunci):raise ValueError('Identitas operasi tidak sah.')
    proc=await ambil(db,pid,kind,user,req.get('aksi'),lock=True)
    key=f'{JENIS}:{user.id}:{kunci}'
    old=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==key))
    clean=buku.bersih(req)
    if old:
        if old.muatan['isian']!=clean or old.muatan['proses_id']!=pid or old.muatan['jenis']!=kind:raise ValueError('Identitas operasi sudah dipakai untuk rancangan lain.')
        return old
    plan=await rencana(db,pid,kind,user,req)
    if not hmac.compare_digest(tanda(plan),dasar):raise ValueError('Data berubah sejak tinjauan. Pertahankan isian dan periksa dampak terbaru.')
    proc=await ambil(db,pid,kind,user,req['aksi'],lock=True)
    async with db.begin_nested():
        if float(plan['sebelum']['catatan']['berat_kg'])!=float(plan['sesudah']['kg']):
            await p.koreksi_hasil_sosoh(db,user=user,process_id=pid,perubahan=plan['sesudah']['hasil'],
                dasar={k:plan['sebelum']['hasil'].get(k,0) for k in set(await p.jenis_hasil(db, termasuk_nonaktif=True))},alasan=req['alasan'],
                berjalan=proc.status=='proses',simpan=False,catatan_id=req['catatan_id'])
        event=await buku.catat(db,jenis=JENIS,pelaku_id=user.id,kunci_kiriman=key,muatan={**plan,'isian':clean},terapkan=False)
        from app.services.activity_log import log_activity
        await log_activity(db,table_name='polishing_output_logs',record_id=req['catatan_id'],action='UPDATE',changed_by=user.id,
            field_name='koreksi_asal',old_value=json.dumps(plan['sebelum']),new_value=json.dumps(plan['sesudah']),
            alasan=req['alasan'],aksi=JENIS)
        await db.flush()
    return event
