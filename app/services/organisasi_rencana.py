"""Pratinjau dan penetapan gudang; tidak menulis transaksi atau fasilitas lama."""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from sqlalchemy import select, func
from hmu_core import Perusahaan,LokasiPabrik,PenempatanGudang,Warehouse,Silo,Dryer,User
from app.models import LiniProduksi,ActivityLog
from app.services.activity_log import log_activity
from app.services.organisasi_master import OrganisasiError,pengelola,potret,teks

UMUR_PRATINJAU=30*60


@dataclass(frozen=True)
class BarisRencana:
    warehouse_id:int
    nama:str
    keadaan:str
    tujuan_lama:str
    silo:int
    dryer:int
    lini:int
    baru:bool
    boleh:bool


@dataclass(frozen=True)
class RencanaPenetapan:
    company_id:int
    lokasi_pabrik_id:int
    perusahaan:str
    lokasi:str
    gudang:tuple[BarisRencana,...]
    sidik:str

    @property
    def bisa_diterapkan(self):
        return all(w.boleh for w in self.gudang)

    @property
    def jumlah_baru(self):
        return sum(w.baru for w in self.gudang)


@dataclass(frozen=True)
class HasilPenetapan:
    lokasi_pabrik_id:int
    jumlah_baru:int
    diulang:bool=False


def _json(data):
    return json.dumps(data,sort_keys=True,ensure_ascii=False,default=str,separators=(',',':'))


async def fasilitas(db):
    with db.no_autoflush:
        wh=list(await db.scalars(select(Warehouse).order_by(Warehouse.nama_gudang,Warehouse.id)))
        counts={}
        for model in (Silo,Dryer,LiniProduksi):
            counts[model]=dict((await db.execute(select(model.warehouse_id,func.count()).group_by(model.warehouse_id))).all())
    return wh,counts


async def pratinjau(db,*,lokasi_pabrik_id,warehouse_ids):
    if type(lokasi_pabrik_id) is not int or lokasi_pabrik_id<=0:
        raise OrganisasiError('Pilih lokasi pabrik tujuan.')
    if not isinstance(warehouse_ids,(list,tuple)) or not warehouse_ids or len(warehouse_ids)>1000 or any(type(i) is not int or i<=0 for i in warehouse_ids):
        raise OrganisasiError('Pilih minimal satu gudang yang tersedia (maksimal 1.000).')
    ids=set(warehouse_ids)
    with db.no_autoflush:
        tujuan=(await db.execute(select(LokasiPabrik,Perusahaan).join(Perusahaan,LokasiPabrik.company_id==Perusahaan.id)
          .where(LokasiPabrik.id==lokasi_pabrik_id,LokasiPabrik.aktif.is_(True),Perusahaan.aktif.is_(True)))).one_or_none()
        if tujuan is None:raise OrganisasiError('Lokasi pabrik atau perusahaan tujuan tidak aktif atau tidak tersedia.')
        site,company=tujuan
        wh,counts=await fasilitas(db)
        if ids-{w.id for w in wh}:raise OrganisasiError('Daftar gudang sudah berubah. Periksa pilihan kembali.')
        lama={p.warehouse_id:(p,s,c) for p,s,c in (await db.execute(select(PenempatanGudang,LokasiPabrik,Perusahaan)
          .join(LokasiPabrik,PenempatanGudang.lokasi_pabrik_id==LokasiPabrik.id)
          .join(Perusahaan,PenempatanGudang.company_id==Perusahaan.id))).all()}
        from hmu_identitas.ruang_data import pastikan_perusahaan
        pastikan_perusahaan(company.id)
        rows=[];snapshot=[]
        for w in wh:
            if w.id not in ids:continue
            old=lama.get(w.id)
            sesuai=old is not None and old[0].lokasi_pabrik_id==site.id and old[0].company_id==company.id
            keadaan='Belum ditetapkan' if not old else 'Sudah sesuai' if sesuai else 'Lokasi berbeda — perlu ditinjau'
            if not w.aktif:keadaan='Gudang nonaktif — perlu ditinjau'
            rows.append(BarisRencana(w.id,w.nama_gudang,keadaan,
                f'{old[2].nama} / {old[1].nama}' if old else 'Belum ditetapkan',
                counts[Silo].get(w.id,0),counts[Dryer].get(w.id,0),counts[LiniProduksi].get(w.id,0),
                old is None,bool(w.aktif and (not old or sesuai))))
            snapshot.append(dict(gudang={c.name:getattr(w,c.name) for c in Warehouse.__table__.columns},
                penetapan={c.name:getattr(old[0],c.name) for c in PenempatanGudang.__table__.columns} if old else None,
                fasilitas=[counts[m].get(w.id,0) for m in (Silo,Dryer,LiniProduksi)]))
        sidik=hashlib.sha256(_json([potret(company),potret(site),snapshot]).encode()).hexdigest()
        return RencanaPenetapan(company.id,site.id,company.nama,site.nama,tuple(rows),sidik)


def _tanda(isi):
    from app.web.security import _kunci
    return hmac.new(_kunci(),b'penetapan-gudang-v1:'+isi.encode(),hashlib.sha256).hexdigest()


def buat_bukti(plan,*,user_id):
    data=dict(v=1,user_id=user_id,lokasi_pabrik_id=plan.lokasi_pabrik_id,
        warehouse_ids=sorted(w.warehouse_id for w in plan.gudang),sidik=plan.sidik,sampai=int(time.time())+UMUR_PRATINJAU)
    isi=base64.urlsafe_b64encode(_json(data).encode()).decode()
    tanda=_tanda(isi)
    return isi+'.'+tanda


def _periksa_bukti(bukti,*,user_id):
    try:
        if not isinstance(bukti,str) or len(bukti)>16000:raise ValueError
        isi,tanda=bukti.split('.')
        benar=_tanda(isi)
        if not hmac.compare_digest(tanda,benar):raise ValueError
        data=json.loads(base64.b64decode(isi,altchars=b'-_',validate=True))
        if set(data)!={'v','user_id','lokasi_pabrik_id','warehouse_ids','sidik','sampai'} or data['v']!=1 or data['user_id']!=user_id:raise ValueError
        if type(data['sampai']) is not int or type(data['lokasi_pabrik_id']) is not int:raise ValueError
        if not isinstance(data['warehouse_ids'],list) or not 0<len(data['warehouse_ids'])<=1000 or any(type(i) is not int or i<=0 for i in data['warehouse_ids']):raise ValueError
    except (ValueError,TypeError,KeyError,UnicodeError) as exc:
        raise OrganisasiError('Pratinjau tidak valid untuk akun ini. Buat pratinjau baru.') from exc
    if data['sampai']<int(time.time()):raise OrganisasiError('Pratinjau sudah kedaluwarsa. Buat pratinjau baru sebelum menerapkan.')
    return data


async def terapkan(db,*,user_id,bukti,alasan):
    # Sesi khusus mencegah flush draf/transaksi lain ikut tersimpan bersama
    # metadata. Commit tetap milik rute; audit dan seluruh gudang satu transaksi.
    if db.new or db.dirty or db.deleted:raise OrganisasiError('Penetapan harus memakai transaksi tersendiri.')
    await pengelola(db,user_id)
    data=_periksa_bukti(bukti,user_id=user_id)
    alasan=teks(alasan,'Alasan penetapan',500,5)
    awal=await db.get(LokasiPabrik,data['lokasi_pabrik_id'])
    if awal is None:raise OrganisasiError('Lokasi pabrik tidak tersedia. Buat pratinjau baru.')
    from hmu_identitas.ruang_data import pastikan_perusahaan
    pastikan_perusahaan(awal.company_id)
    await db.scalar(select(Perusahaan).where(Perusahaan.id==awal.company_id).with_for_update(key_share=True).execution_options(populate_existing=True))
    site=await db.scalar(select(LokasiPabrik).where(LokasiPabrik.id==data['lokasi_pabrik_id'])
        .with_for_update(key_share=True).execution_options(populate_existing=True))
    if site is None:raise OrganisasiError('Lokasi pabrik tidak tersedia. Buat pratinjau baru.')
    # Sama dengan urutan editor master: perusahaan -> lokasi. Kunci gudang
    # diambil menurut ID walau belum ada baris penempatannya. NO KEY UPDATE
    # tidak menghalangi KEY SHARE pemakaian FK oleh pekerjaan operator.
    await db.execute(select(Warehouse).where(Warehouse.id.in_(data['warehouse_ids'])).order_by(Warehouse.id)
        .with_for_update(key_share=True).execution_options(populate_existing=True))
    await db.execute(select(PenempatanGudang).where(PenempatanGudang.warehouse_id.in_(data['warehouse_ids'])).order_by(PenempatanGudang.warehouse_id)
        .with_for_update().execution_options(populate_existing=True))
    plan=await pratinjau(db,lokasi_pabrik_id=site.id,warehouse_ids=data['warehouse_ids'])
    rencana=hashlib.sha256(bukti.encode()).hexdigest()
    sudah=await db.scalar(select(ActivityLog.id).where(ActivityLog.table_name=='hmu_warehouse_sites',
        ActivityLog.aksi=='penetapan_gudang',ActivityLog.changed_by==user_id,
        ActivityLog.new_value.contains('"rencana": "'+rencana+'"')).limit(1))
    if sudah and plan.bisa_diterapkan and not plan.jumlah_baru:
        return HasilPenetapan(site.id,0,True)
    if plan.sidik!=data['sidik']:
        raise OrganisasiError('Data gudang atau tujuan sudah berubah sejak pratinjau. Periksa pratinjau terbaru sebelum menerapkan.')
    if not plan.bisa_diterapkan:
        raise OrganisasiError('Penetapan belum dapat diterapkan. Periksa gudang nonaktif atau penetapan yang berbeda; tidak ada gudang yang diubah.')
    for w in plan.gudang:
        if not w.baru:continue
        row=PenempatanGudang(warehouse_id=w.warehouse_id,company_id=plan.company_id,lokasi_pabrik_id=site.id)
        db.add(row)
        nilai=dict(warehouse_id=w.warehouse_id,gudang=w.nama,company_id=plan.company_id,perusahaan=plan.perusahaan,
            lokasi_pabrik_id=site.id,lokasi=plan.lokasi,rencana=rencana)
        await log_activity(db,table_name='hmu_warehouse_sites',record_id=w.warehouse_id,action='INSERT',
            changed_by=user_id,field_name='penetapan_gudang',old_value=None,new_value=json.dumps(nilai,ensure_ascii=False),
            alasan=alasan,aksi='penetapan_gudang')
    await db.flush()
    return HasilPenetapan(site.id,plan.jumlah_baru)


async def riwayat(db,*,lokasi_pabrik_id,sebelum=None):
    """Snapshot audit tetap terbaca walau nama master kemudian diperbarui."""
    q=select(ActivityLog,User.nama).outerjoin(User,ActivityLog.changed_by==User.id).where(
        ActivityLog.table_name=='hmu_warehouse_sites',ActivityLog.aksi=='penetapan_gudang',
        ActivityLog.record_id.in_(select(PenempatanGudang.warehouse_id).where(PenempatanGudang.lokasi_pabrik_id==lokasi_pabrik_id)))
    if sebelum is not None:q=q.where(ActivityLog.id<sebelum)
    logs=list((await db.execute(q.order_by(ActivityLog.id.desc()).limit(51))).all())
    rows=[]
    for log,nama in logs[:50]:
        try:potret=json.loads(log.new_value or '{}')
        except (ValueError,TypeError):potret={}
        rows.append(dict(id=log.id,waktu=log.waktu_perubahan,pelaku=nama or 'Tidak diketahui',
            alasan=log.alasan_perubahan or '',gudang=potret.get('gudang',f'Gudang #{log.record_id}'),
            perusahaan=potret.get('perusahaan','Tidak tercatat'),lokasi=potret.get('lokasi','Tidak tercatat'),
            company_id=potret.get('company_id'),lokasi_pabrik_id=potret.get('lokasi_pabrik_id'),
            sebelum='Belum ditetapkan' if not log.old_value else log.old_value))
    return rows,logs[49][0].id if len(logs)>50 else None
