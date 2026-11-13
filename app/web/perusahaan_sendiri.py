"""Pengaturan perusahaan sendiri; identitas/cakupan selalu berasal dari sesi."""
from fastapi import APIRouter,Depends,HTTPException,Request
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.services import keanggotaan as anggota,perusahaan_sendiri as svc
from app.services.organisasi_master import OrganisasiError
from app.web.security import butuh_akun,AksesDitolak
from app.web.tampilan import render_laci,redirect
from app.web.console import RuteConsole
from hmu_identitas import peran as P

router=APIRouter(route_class=RuteConsole)
DASAR='/pengaturan/perusahaan-sendiri'


async def pelaku(request:Request,akun=Depends(butuh_akun)):
    # Penyamaran tetap dihormati; tidak mengangkat kembali hak Admin ketika
    # pengguna sedang mencoba layar operator. Peran keanggotaan diperiksa DB.
    if P.normal(getattr(request.state,'peran_asli',akun.peran))!=P.normal(akun.peran):raise AksesDitolak('Kembali ke tampilan akun sendiri untuk mengelola perusahaan.')
    return akun


def angka(v):
    try:n=int(v)
    except (TypeError,ValueError):raise OrganisasiError('Identitas pilihan tidak valid.')
    if not anggota.id_sah(n):raise OrganisasiError('Identitas pilihan tidak valid.')
    return n


@router.get(DASAR)
async def daftar(request:Request,akun=Depends(pelaku)):
    async with SessionLocal() as db:companies=await svc.daftar(db,akun.user.id)
    if len(companies)==1:return redirect(f'{DASAR}/{companies[0].id}')
    return await render_laci(request,'perusahaan_sendiri.html',layar='pengaturan',kembali='/pengaturan',
        companies=companies,info=None,form={},err='',edit=None,logs=[],lanjut=None)


async def halaman(request,akun,cid,*,form=None,err='',status=200):
    ruang=anggota.RuangAdministrasi(akun.user.id,cid)
    try:
        async with SessionLocal() as db:
            info=await svc.baca(db,ruang,cari_pengguna=request.query_params.get('cari',''),
                anggota_id=angka(request.query_params['anggota']) if request.query_params.get('anggota') else None)
            logs,lanjut=await svc.riwayat(db,ruang,sebelum=angka(request.query_params['sebelum']) if 'sebelum' in request.query_params else None)
    except PermissionError as e:raise AksesDitolak(str(e)) from e
    except OrganisasiError as e:raise HTTPException(422,str(e)) from e
    uid=(form or {}).get('user_id') or request.query_params.get('anggota')
    edit=next((m for m in info['anggota'] if str(m['user_id'])==str(uid)),None)
    return await render_laci(request,'perusahaan_sendiri.html',layar='pengaturan',kembali=DASAR,
        companies=[],info=info,form=form or {},err=err,status_code=status,edit=edit,logs=logs,lanjut=lanjut)


@router.get(DASAR+'/{company_id:int}')
async def rincian(request:Request,company_id:int,akun=Depends(pelaku)):
    return await halaman(request,akun,company_id)


@router.post(DASAR+'/{company_id:int}/{aksi}')
async def simpan(request:Request,company_id:int,aksi:str,akun=Depends(pelaku)):
    raw=await request.form();form=dict(raw);ruang=anggota.RuangAdministrasi(akun.user.id,company_id)
    allowed={'_csrf','alasan','bukti'}
    if aksi=='anggota':allowed|={'user_id','peran','aktif'}|{k for k in raw if k.startswith(('lokasi_','semua_','gudang_'))}
    elif aksi=='lokasi':allowed|={'lokasi_id','nama','kode','alamat'}
    elif aksi=='gudang':allowed|={'lokasi_id','gudang_id','nama','alamat'}
    else:raise HTTPException(404,'Pengaturan tidak ditemukan.')
    try:
        if set(raw)-allowed or any(len(raw.getlist(k))!=1 for k in raw if not k.startswith('gudang_')):
            raise OrganisasiError('Isian tidak dikenal atau berulang. Gunakan formulir yang tersedia.')
        async with SessionLocal() as db:
            # Otorisasi dilakukan sebelum membaca sasaran, termasuk saat
            # payload salah atau pengguna menebak ID perusahaan lain.
            info=await svc.baca(db,ruang)
            if aksi=='anggota':
                lokasi=[]
                known={str(s['id']) for s in info['lokasi']}
                for k in raw:
                    if k.startswith(('lokasi_','semua_','gudang_')) and k.split('_',1)[1] not in known:
                        raise PermissionError('Lokasi di luar cakupan pengelolaan Anda.')
                for s in info['lokasi']:
                    lid=s['id']
                    if raw.get(f'lokasi_{lid}')=='on':
                        lokasi.append(dict(lokasi_pabrik_id=lid,semua_gudang=raw.get(f'semua_{lid}')=='on',gudang_ids=[angka(x) for x in raw.getlist(f'gudang_{lid}')]))
                # Pembacaan memakai sesi terpisah agar writer hanya menerima
                # transaksi metadata bersih, bukan draf atau aktor detached.
                await anggota.simpan(db,ruang=ruang,company_id=company_id,user_id=angka(raw.get('user_id')),peran=raw.get('peran',''),
                    aktif=raw.get('aktif')=='on',lokasi=lokasi,bukti=raw.get('bukti',''),alasan=raw.get('alasan',''))
            elif aksi=='lokasi':
                await svc.simpan_lokasi(db,ruang=ruang,lokasi_id=angka(raw['lokasi_id']) if raw.get('lokasi_id') else None,
                    nama=raw.get('nama',''),kode=raw.get('kode',''),alamat=raw.get('alamat',''),bukti=raw.get('bukti',''),alasan=raw.get('alasan',''))
            else:
                await svc.simpan_gudang(db,ruang=ruang,lokasi_id=angka(raw.get('lokasi_id')),gudang_id=angka(raw['gudang_id']) if raw.get('gudang_id') else None,
                    nama=raw.get('nama',''),alamat=raw.get('alamat',''),bukti=raw.get('bukti',''),alasan=raw.get('alasan',''))
            await db.commit()
    except PermissionError as e:raise AksesDitolak(str(e)) from e
    except (OrganisasiError,IntegrityError) as e:
        # Tidak mengganti bukti formulir yang gagal: draf usang tidak boleh
        # memperoleh izin untuk menimpa perubahan yang baru disimpan orang lain.
        form['_aksi']=aksi
        form['_gudang']={k:raw.getlist(k) for k in raw if k.startswith('gudang_')}
        return await halaman(request,akun,company_id,form=form,err=str(e) if isinstance(e,OrganisasiError) else 'Data berubah. Buka data terbaru.',status=422)
    return redirect(f'{DASAR}/{company_id}?tersimpan=1')
