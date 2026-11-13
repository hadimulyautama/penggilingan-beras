"""Pengaturan organisasi dan penetapan gudang melalui pratinjau bertanda."""
from fastapi import APIRouter,Depends,Request,HTTPException
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.services import organisasi_master as master
from app.services import organisasi_rencana as rencana
from app.web.perusahaan import butuh_perusahaan
from app.web.tampilan import render_laci,redirect

router=APIRouter()
DASAR='/pengaturan/organisasi'


def angka(v):
    if not str(v or '').isdigit() or int(v)<=0:raise master.OrganisasiError('Pilih data yang tersedia.')
    return int(v)


async def halaman(request,akun,*,mode='daftar',company_id=None,site_id=None,form=None,err='',status=200,plan=None,bukti=''):
    async with SessionLocal() as db:
        jejak=[];lanjut=None
        if site_id:
            try:sebelum=angka(request.query_params['sebelum']) if 'sebelum' in request.query_params else None
            except master.OrganisasiError as exc:raise HTTPException(422,str(exc)) from exc
            jejak,lanjut=await rencana.riwayat(db,lokasi_pabrik_id=site_id,sebelum=sebelum)
        companies,sites,bindings=await master.baca(db)
        wh,_=await rencana.fasilitas(db)
    company=next((c for c in companies if c.id==company_id),None)
    site=next((s for s in sites if s.id==site_id),None)
    if site:
        company=next((c for c in companies if c.id==site.company_id),None)
    if company_id is not None and not company or site_id is not None and not site:raise HTTPException(404,'Master organisasi tidak ditemukan.')
    return await render_laci(request,'organisasi.html',layar='pengaturan',kembali=DASAR if mode!='daftar' else '/pengaturan',
      mode=mode,companies=companies,sites=sites,bindings=bindings,warehouses=wh,company=company,site=site,
      form=form or {},err=err,plan=plan,master_sidik=master.sidik,status_code=status,
      pesan=request.query_params.get('tersimpan')=='1',bukti=bukti,
      pesan_penetapan=request.query_params.get('penetapan',''),jejak=jejak,jejak_lanjut=lanjut)


@router.get(DASAR)
async def daftar(request:Request,akun=Depends(butuh_perusahaan)):
    return await halaman(request,akun)


@router.get(DASAR+'/perusahaan/{company_id:int}')
async def perusahaan(request:Request,company_id:int,akun=Depends(butuh_perusahaan)):
    return await halaman(request,akun,mode='perusahaan',company_id=company_id)


@router.get(DASAR+'/lokasi/{site_id:int}')
async def lokasi(request:Request,site_id:int,akun=Depends(butuh_perusahaan)):
    return await halaman(request,akun,mode='lokasi',site_id=site_id)


@router.get(DASAR+'/penetapan')
async def penetapan(request:Request,akun=Depends(butuh_perusahaan)):
    form={'lokasi_pabrik_id':request.query_params.get('lokasi_pabrik_id',''),
          'warehouse_ids':request.query_params.getlist('warehouse_id')}
    plan=None;err=''
    if request.query_params.get('periksa')=='1':
        try:
            async with SessionLocal() as db:
                plan=await rencana.pratinjau(db,lokasi_pabrik_id=angka(form['lokasi_pabrik_id']),
                     warehouse_ids=[angka(i) for i in form['warehouse_ids']])
        except master.OrganisasiError as exc:err=str(exc)
    bukti=rencana.buat_bukti(plan,user_id=akun.user.id) if plan and plan.bisa_diterapkan and plan.jumlah_baru else ''
    return await halaman(request,akun,mode='penetapan',form=form,err=err,plan=plan,bukti=bukti,status=422 if err else 200)


async def simpan(request,akun,*,objek,identitas=None,company_id=None):
    if identitas is not None and identitas<=0 or company_id is not None and company_id<=0:
        raise HTTPException(404,'Master organisasi tidak ditemukan.')
    form=dict(await request.form())
    mode='lokasi' if objek=='lokasi' and identitas else 'perusahaan' if company_id or identitas else 'daftar'
    company_page=company_id if objek=='lokasi' else identitas
    try:
        allowed={'_csrf','kode','nama','aktif','alasan','sidik'}|({'alamat'} if objek=='lokasi' else set())
        if set(form)-allowed:raise master.OrganisasiError('Isian tidak dikenal. Buka formulir yang sesuai.')
        async with SessionLocal() as db:
            row=await master.simpan(db,user_id=akun.user.id,objek=objek,identitas=identitas,
                nama=form.get('nama',''),kode=form.get('kode',''),aktif=form.get('aktif')=='on',
                alamat=form.get('alamat',''),alasan=form.get('alasan',''),bukti=form.get('sidik',''),company_id=company_id)
            await db.commit();rid=row.id
    except PermissionError as exc:
        raise HTTPException(403,str(exc)) from exc
    except (master.OrganisasiError,IntegrityError) as exc:
        err='Kode sudah digunakan atau data berubah. Periksa kembali sebelum menyimpan.' if isinstance(exc,IntegrityError) else str(exc)
        # Token lama tetap dipertahankan pada formulir gagal agar draf usang
        # tidak mendapatkan izin untuk menimpa perubahan pengguna lain.
        return await halaman(request,akun,mode=mode,company_id=company_page,
          site_id=identitas if objek=='lokasi' else None,form=form,err=err,status=422)
    return redirect(f'{DASAR}/{"lokasi" if objek=="lokasi" else "perusahaan"}/{rid}?tersimpan=1')


@router.post(DASAR+'/perusahaan/baru')
async def tambah_perusahaan(request:Request,akun=Depends(butuh_perusahaan)):
    return await simpan(request,akun,objek='perusahaan')


@router.post(DASAR+'/perusahaan/{company_id:int}')
async def ubah_perusahaan(request:Request,company_id:int,akun=Depends(butuh_perusahaan)):
    return await simpan(request,akun,objek='perusahaan',identitas=company_id)


@router.post(DASAR+'/perusahaan/{company_id:int}/lokasi/baru')
async def tambah_lokasi(request:Request,company_id:int,akun=Depends(butuh_perusahaan)):
    return await simpan(request,akun,objek='lokasi',company_id=company_id)


@router.post(DASAR+'/lokasi/{site_id:int}')
async def ubah_lokasi(request:Request,site_id:int,akun=Depends(butuh_perusahaan)):
    return await simpan(request,akun,objek='lokasi',identitas=site_id)


@router.post(DASAR+'/penetapan/terapkan')
async def terapkan_penetapan(request:Request,akun=Depends(butuh_perusahaan)):
    isi=await request.form();form=dict(isi)
    try:
        if set(form)-{'_csrf','bukti','alasan','konfirmasi'} or any(len(isi.getlist(k))!=1 for k in form):
            raise master.OrganisasiError('Isian penetapan tidak dikenal. Gunakan pratinjau dari Pengaturan.')
        pilihan=rencana._periksa_bukti(form.get('bukti',''),user_id=akun.user.id)
        form.update(lokasi_pabrik_id=str(pilihan['lokasi_pabrik_id']),warehouse_ids=[str(i) for i in pilihan['warehouse_ids']])
        if form.get('konfirmasi')!='on':raise master.OrganisasiError('Periksa tujuan dan gudang, lalu tandai persetujuan penetapan.')
        async with SessionLocal() as db:
            hasil=await rencana.terapkan(db,user_id=akun.user.id,bukti=form.get('bukti',''),alasan=form.get('alasan',''))
            await db.commit()
    except PermissionError as exc:
        raise HTTPException(403,str(exc)) from exc
    except (master.OrganisasiError,IntegrityError) as exc:
        err='Data penetapan berubah. Buat pratinjau terbaru sebelum menerapkan.' if isinstance(exc,IntegrityError) else str(exc)
        # Bukti gagal tidak diganti diam-diam dengan izin baru. Draf alasan
        # tetap ditampilkan; pengguna harus meninjau ulang tujuan/gudangnya.
        return await halaman(request,akun,mode='penetapan',form=form,err=err,status=422)
    pesan='tersimpan' if hasil.jumlah_baru or hasil.diulang else 'sesuai'
    return redirect(f'{DASAR}/lokasi/{hasil.lokasi_pabrik_id}?penetapan={pesan}')
