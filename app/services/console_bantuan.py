"""Diagnosis dan pemulihan akun; seluruh writer terbatas kredensial/metadata."""
from datetime import timedelta
import hashlib,json,secrets,uuid
from sqlalchemy import select,text,update,func
from sqlalchemy.dialects.postgresql import insert
from hmu_identitas import peran as P,pintu
from hmu_identitas.model import Akun
from hmu_identitas.sandi import hash_sandi
from hmu_identitas.monitoring import KejadianPemakaian as E,PembukaanMasuk,RencanaBantuan,PemulihanAkun
from hmu_identitas.ruang_data import RuangData
from hmu_core import User,Perusahaan,KeanggotaanPerusahaan
from app.models import ActivityLog
from app.models.portal import PortalAccount
from app.services import console_monitoring as m

AKSI=('tautan_sandi','cabut_sesi','aktifkan_akun','buka_penahanan','aktifkan_keanggotaan')
NAMA_AKSI={'tautan_sandi':'Terbitkan tautan pemulihan sandi','cabut_sesi':'Akhiri seluruh sesi aplikasi','aktifkan_akun':'Aktifkan kembali akun','buka_penahanan':'Buka penahanan percobaan masuk','aktifkan_keanggotaan':'Aktifkan keanggotaan tersimpan'}

class BantuanError(ValueError):pass


def json_(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def hash_(x):return hashlib.sha256(x.encode()).hexdigest()
def sidik(x):return hash_(json_({k:v for k,v in x.items() if k!='terakhir_login'}))


async def pelaku(db,uid):
    row=await db.scalar(select(User).where(User.id==uid).execution_options(populate_existing=True))
    if not row or (row.status or '').lower()!='aktif' or not P.super_saja(row.role):raise PermissionError('Bantuan pengguna hanya untuk Admin Sistem aktif.')
    return row


def tindakan(a,*,perusahaan_aktif=True):
    if a['jenis']=='staf_belum_login':return []
    out=['aktifkan_akun'] if not a['aktif'] else ['tautan_sandi','buka_penahanan','cabut_sesi']
    if perusahaan_aktif and a['keanggotaan'] and not a['keanggotaan']['aktif']:out.append('aktifkan_keanggotaan')
    return out


async def diagnosis(db,*,cid,jenis,aid):
    a=await m.akun(db,cid,jenis,aid);scope=await m.cakupan(db,cid)
    sebab=[]
    if a['jenis']=='staf_belum_login':sebab.append('belum_ada_login')
    elif not a['aktif']:sebab.append('akun_nonaktif')
    if a['wajib_ganti']:sebab.append('wajib_ganti_sandi')
    if jenis=='staf' and not a['keanggotaan']:sebab.append('keanggotaan_belum_ada')
    elif a['keanggotaan'] and not a['keanggotaan']['aktif']:sebab.append('keanggotaan_nonaktif')
    company=await db.get(Perusahaan,cid)
    if not company.aktif:sebab.append('master_perusahaan_nonaktif')
    apps=[]
    if jenis=='staf':
        for app,gate in [('padiflow',pintu.PRODUKSI),('teraflow',pintu.TIMBANGAN)]:
            reason=pintu.sebab_tolak(a['peran'],gate)
            apps.append(dict(aplikasi=app,boleh=a['aktif'] and not reason,sebab='akun_nonaktif' if not a['aktif'] else ('peran' if reason else 'tersedia')))
    elif jenis=='pelanggan':apps=[dict(aplikasi='portal',boleh=a['aktif'],sebab='tersedia' if a['aktif'] else 'akun_nonaktif')]
    elif jenis=='timbangan_lama':apps=[dict(aplikasi='teraflow',boleh=a['aktif'],sebab='tersedia' if a['aktif'] else 'akun_nonaktif')]
    since=m.sekarang()-timedelta(days=30)
    rows=list(await db.scalars(select(E).where(E.company_id==cid,E.jenis_akun==jenis,E.akun_id==aid,E.jenis=='login',E.waktu>=since).order_by(E.waktu.desc(),E.id.desc()).limit(50)))
    login=[dict(aplikasi=e.aplikasi,kode=e.kode,waktu=e.waktu.isoformat(),browser=e.browser,perangkat=e.perangkat) for e in rows if e.jenis=='login']
    devices=(await db.execute(select(E.aplikasi,E.browser,E.perangkat,E.warehouse_id,func.max(E.waktu)).where(E.company_id==cid,E.jenis_akun==jenis,E.akun_id==aid,E.jenis=='interaksi',E.waktu>=since).group_by(E.aplikasi,E.browser,E.perangkat,E.warehouse_id).order_by(func.max(E.waktu).desc()).limit(10))).all()
    last_fail=next((e for e in login if e['kode']!='berhasil'),None)
    if last_fail and (not login or last_fail['waktu']>=next((e['waktu'] for e in login if e['kode']=='berhasil'),'')):sebab.append('ada_kegagalan_masuk')
    key=f'{cid}:{jenis}:{aid}'
    logs=list(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='console_bantuan',ActivityLog.field_name==key).order_by(ActivityLog.id.desc()).limit(20)))
    grants=[]
    if a['user_id'] and a['keanggotaan']:
        from app.services.keanggotaan import snapshot
        member=await db.get(KeanggotaanPerusahaan,a['keanggotaan']['id'])
        grants=(await snapshot(db,member))['lokasi']
    return dict(akun=a,cakupan=scope,sebab=sebab,aplikasi=apps,login=login,
        perangkat=[dict(aplikasi=app,browser=b,perangkat=d,warehouse_id=w,terakhir=t.isoformat()) for app,b,d,w,t in devices],
        lokasi=grants,tindakan=tindakan(a,perusahaan_aktif=company.aktif),
        audit=[dict(id=r.id,waktu=r.waktu_perubahan.isoformat(),alasan=r.alasan_perubahan,sebelum=r.old_value,sesudah=r.new_value,pelaku_id=r.changed_by) for r in logs])


async def pratinjau(db,*,cid,jenis,aid,pelaku_id,aksi,alasan):
    await pelaku(db,pelaku_id)
    alasan=alasan.strip()
    if aksi not in AKSI or not 10<=len(alasan)<=500:raise BantuanError('Pilih tindakan dan isi alasan 10–500 karakter.')
    if aksi=='aktifkan_keanggotaan':await _perusahaan_aktif(db,cid)
    a=await m.akun(db,cid,jenis,aid)
    if aksi not in tindakan(a):raise BantuanError('Tindakan tidak tersedia pada keadaan akun sekarang.')
    plan=RencanaBantuan(id=str(uuid.uuid4()),company_id=cid,pelaku_id=pelaku_id,jenis_akun=jenis,akun_id=aid,aksi=aksi,
        alasan=alasan,sidik=sidik(a),sebelum=json_(a),kedaluwarsa=m.sekarang()+timedelta(minutes=10))
    db.add(plan);await db.flush()
    return dict(id=plan.id,company_id=cid,jenis=jenis,akun_id=aid,nama=a['nama'],username=a['username'],aksi=aksi,
                alasan=alasan,sebelum=a,kedaluwarsa=plan.kedaluwarsa.isoformat(),berdampak_sesi=aksi=='cabut_sesi')


async def _perusahaan_aktif(db,cid):
    company=await db.scalar(select(Perusahaan).where(Perusahaan.id==cid).with_for_update(key_share=True).execution_options(populate_existing=True))
    if not company or not company.aktif:raise BantuanError('Aktifkan perusahaan sebelum memulihkan keanggotaan.')


async def _buka(db,a):
    stmt=insert(PembukaanMasuk).values(company_id=a['company_id'],jenis_akun=a['jenis'],akun_id=a['id'],generasi=1)
    await db.execute(stmt.on_conflict_do_update(index_elements=['company_id','jenis_akun','akun_id'],set_={'generasi':PembukaanMasuk.generasi+1}))


async def _cabut(db,a,*,hash_baru=None):
    if a['jenis']=='staf':
        vals=dict(token_version=Akun.token_version+1)
        if hash_baru:vals.update(password_hash=hash_baru,harus_ganti_sandi=False)
        await db.execute(update(Akun).where(Akun.id==a['id']).values(**vals))
        if await m.timbangan_siap(db):
            await db.execute(text('UPDATE timbangan_akun SET token_version=token_version+1 WHERE akun_id=:id'),{'id':a['id']})
    elif a['jenis']=='pelanggan':
        vals=dict(token_version=PortalAccount.token_version+1)
        if hash_baru:vals['password_hash']=hash_baru
        await db.execute(update(PortalAccount).where(PortalAccount.id==a['id']).values(**vals))
    else:
        sql='UPDATE timbangan_akun SET token_version=token_version+1'+(',password_hash=:h' if hash_baru else '')+' WHERE id=:id AND akun_id IS NULL'
        await db.execute(text(sql),dict(id=a['id'],**({'h':hash_baru} if hash_baru else {})))


async def _audit(db,a,uid,aksi,reason,before,after):
    # Hash sandi dan cap pemulihan tidak pernah dimasukkan ke audit.
    db.add(ActivityLog(table_name='console_bantuan_akun',record_id=a['id'],action='UPDATE',
        field_name=f"{a['company_id']}:{a['jenis']}:{a['id']}",old_value=json_(dict(aksi=aksi,akun=before)),new_value=json_(dict(aksi=aksi,akun=after)),
        changed_by=uid,alasan_perubahan=reason,aksi='console_bantuan'))
    await db.flush()


async def terapkan(db,*,cid,jenis,aid,pelaku_id,plan_id):
    await pelaku(db,pelaku_id);m.pastikan_lokal(cid)
    plan=await db.scalar(select(RencanaBantuan).where(RencanaBantuan.id==plan_id,RencanaBantuan.company_id==cid,
        RencanaBantuan.pelaku_id==pelaku_id,RencanaBantuan.jenis_akun==jenis,RencanaBantuan.akun_id==aid).with_for_update().execution_options(populate_existing=True))
    if not plan:raise BantuanError('Pratinjau tidak tersedia untuk akun ini.')
    if plan.diterapkan:return dict(sudah=True,aksi=plan.aksi,tautan_sekali=True)
    if plan.kedaluwarsa<=m.sekarang():raise BantuanError('Pratinjau sudah berakhir. Periksa keadaan akun terbaru.')
    # Urutan induk -> akun/anggota sama dengan writer master/keanggotaan.
    if plan.aksi=='aktifkan_keanggotaan':await _perusahaan_aktif(db,cid)
    a=await m.akun(db,cid,jenis,aid,kunci=True)
    if sidik(a)!=plan.sidik:
        # Pratinjau sepuluh menit dari rilis lama menyertakan waktu login.
        # Terima hanya snapshot lama yang hash aslinya utuh dan seluruh
        # keadaan keamanan terkini tetap sama.
        try:lama=json.loads(plan.sebelum)
        except (ValueError,TypeError):lama={}
        if not isinstance(lama,dict):lama={}
        if hash_(plan.sebelum)!=plan.sidik or sidik(a)!=sidik(lama):
            raise BantuanError('Keadaan akun berubah. Buat pratinjau baru sebelum menerapkan.')
    if plan.aksi not in tindakan(a):raise BantuanError('Tindakan tidak tersedia lagi.')
    result=dict(sudah=False,aksi=plan.aksi)
    if plan.aksi=='tautan_sandi':
        await db.execute(update(PemulihanAkun).where(PemulihanAkun.company_id==cid,PemulihanAkun.jenis_akun==jenis,PemulihanAkun.akun_id==aid,PemulihanAkun.dipakai.is_(None)).values(dicabut=True))
        cap=secrets.token_urlsafe(48);expires=m.sekarang()+timedelta(minutes=30)
        db.add(PemulihanAkun(id=str(uuid.uuid4()),company_id=cid,jenis_akun=jenis,akun_id=aid,cap_hash=hash_(cap),versi=a['versi'],kedaluwarsa=expires,dicabut=False,pelaku_id=pelaku_id))
        await db.flush();result.update(cap=cap,kedaluwarsa=expires.isoformat())
    elif plan.aksi=='buka_penahanan':await _buka(db,a)
    elif plan.aksi=='cabut_sesi':await _cabut(db,a)
    elif plan.aksi=='aktifkan_akun':
        if jenis=='staf':
            await db.execute(update(User).where(User.id==a['user_id']).values(status='aktif'))
            await db.execute(update(Akun).where(Akun.id==aid).values(status='aktif'))
            if await m.timbangan_siap(db):
                await db.execute(text("UPDATE timbangan_akun SET status='aktif' WHERE akun_id=:id"),{'id':aid})
        elif jenis=='pelanggan':await db.execute(update(PortalAccount).where(PortalAccount.id==aid).values(active=True))
        else:
            if a['user_id']:await db.execute(update(User).where(User.id==a['user_id']).values(status='aktif'))
            await db.execute(text("UPDATE timbangan_akun SET status='aktif' WHERE id=:id AND akun_id IS NULL"),{'id':aid})
    elif plan.aksi=='aktifkan_keanggotaan':
        # Peran serta seluruh lokasi/gudang dipertahankan persis seperti sebelumnya.
        await db.execute(update(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.id==a['keanggotaan']['id'],KeanggotaanPerusahaan.company_id==cid).values(aktif=True))
    after=await m.akun(db,cid,jenis,aid)
    await _audit(db,a,pelaku_id,plan.aksi,plan.alasan,a,after)
    plan.diterapkan=m.sekarang();plan.hasil=json_(dict(aksi=plan.aksi,tersimpan=True))
    await db.flush();return result


async def periksa_pemulihan(db,cap):
    if not isinstance(cap,str) or len(cap)!=64:raise BantuanError('Tautan pemulihan tidak valid atau sudah berakhir.')
    ruang=RuangData.lingkungan()
    if not ruang:raise BantuanError('Ruang perusahaan belum tersedia.')
    row=await db.scalar(select(PemulihanAkun).where(PemulihanAkun.cap_hash==hash_(cap),PemulihanAkun.company_id==ruang.company_id).execution_options(populate_existing=True))
    if not row or row.dipakai or row.dicabut or row.kedaluwarsa<=m.sekarang():raise BantuanError('Tautan pemulihan tidak valid atau sudah berakhir.')
    a=await m.akun(db,row.company_id,row.jenis_akun,row.akun_id)
    if not a['aktif'] or a['versi']!=row.versi:raise BantuanError('Keadaan akun berubah. Minta tautan pemulihan baru kepada Admin Sistem.')
    return row,a


async def pulihkan_sandi(db,*,cap,sandi,ulangi):
    if sandi!=ulangi:raise BantuanError('Pengulangan kata sandi tidak sama.')
    # Cap diperiksa sebelum scrypt; token acak tidak boleh menghabiskan CPU.
    row,a=await periksa_pemulihan(db,cap)
    import asyncio
    try:hashed=await asyncio.to_thread(hash_sandi,sandi)
    except ValueError as exc:raise BantuanError(str(exc)) from None
    a=await m.akun(db,row.company_id,row.jenis_akun,row.akun_id,kunci=True)
    row=await db.scalar(select(PemulihanAkun).where(PemulihanAkun.id==row.id).with_for_update().execution_options(populate_existing=True))
    if row.dipakai or row.dicabut or row.kedaluwarsa<=m.sekarang() or a['versi']!=row.versi or not a['aktif']:raise BantuanError('Tautan sudah dipakai atau keadaan akun berubah.')
    await _cabut(db,a,hash_baru=hashed);await _buka(db,a)
    row.dipakai=m.sekarang()
    await _audit(db,a,row.pelaku_id,'sandi_dipulihkan','Pemilik akun menetapkan sandi sendiri melalui tautan sekali pakai',a,await m.akun(db,row.company_id,row.jenis_akun,row.akun_id))
    await db.flush();return a
