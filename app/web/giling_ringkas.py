"""Lembar kerja giling: adaptor konteks/pratinjau, memakai layanan operasional lama."""
from app.services.fasilitas import label_fasilitas
from app.web.api import _is_jenis_operator
import hashlib,hmac,json
from types import SimpleNamespace
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,FiniteFloat,ValidationError
from sqlalchemy import select,or_,cast,literal
from app.database import SessionLocal,now_local
from app.models import (MillingProcess,MillingProcessSource,MillingProgressLog,MillingQcLog,
    MillingProcessVerification,SiloStorage,Silo,PurchaseBatch,DryingLot,DryingLotBatch,
    User,ActivityLog,JedaProses,JedaCatatan,InternalTransfer,Jasa)
from app.penggilingan.gudang1.services import milling as m,jeda,silo as si
from app.web import form_selesai_giling as akhir,form_tambah_silo_giling as mix
from app.web import form_hasil_giling as hasil,form_bebaskan_silo_giling as bebas
from app.web.api import _is_g1_operator,_wajib_mutu,HasilGilingReq,SelesaiGilingReq,QcGilingReq
from app.web.security import _kunci
from app.web.deps import pengguna_aksi
from app.web.tampilan import render_laci,templates
from app.peran import can_see_financials
from app.services.mutu_pk import penilaian_dari_log,KLASIFIKASI_QC_PK,JUMLAH_KOMPONEN_QC_PK
from app.web.qc_warna import gaya
router=APIRouter()

def raw(r):return [getattr(r,c.name) for c in r.__table__.columns]
def hash_(v):return hashlib.sha256(json.dumps(v,sort_keys=True,default=str).encode()).hexdigest()
async def izin(user,kode=None):
 if not await _is_jenis_operator(user,'penggilingan'):raise HTTPException(403,'Penggilingan mengikuti akses Gudang 1 yang sedang berlaku.')
 if kode:
  from app.services.cakupan_fasilitas import batas
  async with SessionLocal() as db:
   if not await db.scalar(select(MillingProcess.id).where(MillingProcess.kode_proses==kode,batas(user,MillingProcess))):raise HTTPException(403,'Proses berada di luar gudang kerja Anda.')
async def rows(db,model,kolom,pid):
 return list((await db.scalars(select(model).where(kolom==pid).order_by(model.id).execution_options(populate_existing=True))).all())
async def sidik(db,pr):
 sources=await rows(db,MillingProcessSource,MillingProcessSource.milling_process_id,pr.id)
 stores=list((await db.scalars(select(SiloStorage).where(SiloStorage.id.in_([s.silo_storage_id for s in sources] or [pr.silo_storage_id or -1])).order_by(SiloStorage.id))).all())
 lots=list((await db.scalars(select(DryingLot).where(DryingLot.id.in_([s.drying_lot_id for s in sources] or [pr.drying_lot_id or -1])).order_by(DryingLot.id))).all())
 bid={s.purchase_batch_id for s in sources}|{pr.purchase_batch_id}
 bid.update((await db.scalars(select(DryingLotBatch.purchase_batch_id).where(DryingLotBatch.drying_lot_id.in_([r.id for r in lots])))).all())
 batches=list((await db.scalars(select(PurchaseBatch).where(PurchaseBatch.id.in_(bid-{None} or {-1})).order_by(PurchaseBatch.id))).all())
 parts=[raw(pr),[raw(s) for s in sources],[raw(s) for s in stores],[raw(l) for l in lots],[raw(b) for b in batches]]
 for model in [MillingProgressLog,MillingQcLog,MillingProcessVerification,InternalTransfer]:parts.append([raw(r) for r in await rows(db,model,model.milling_process_id,pr.id)])
 pauses=await rows(db,JedaProses,JedaProses.milling_process_id,pr.id)
 events=list((await db.scalars(select(JedaCatatan).where(JedaCatatan.jeda_id.in_([j.id for j in pauses] or [-1])).order_by(JedaCatatan.id))).all())
 parts.extend([[raw(r) for r in pauses],[raw(r) for r in events]])
 # Saldo tetap dari pembaca stok lama; bukan rumus baru pada adaptor.
 bd=await m._pk_breakdown(db,pr.id);parts.append(vars(bd));parts.append(await m._sold_pk_langsung(db,pr.id))
 return hash_(parts)

def qc_view(logs):
 p=penilaian_dari_log(logs);p['total_komponen']=JUMLAH_KOMPONEN_QC_PK
 for r in p['rows']:r['gaya']=gaya(r['label'],r['hasil'])
 return p

async def baca(db,kode,user):
 pr=await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses==kode).execution_options(populate_existing=True))
 if not pr or pr.status not in ('proses','selesai'):raise HTTPException(404,'Proses penggilingan tidak ditemukan.')
 dasar=await sidik(db,pr)
 d=await akhir.ringkasan(db,kode_proses=kode)
 sources=await rows(db,MillingProcessSource,MillingProcessSource.milling_process_id,pr.id)
 bobot=mix.bobot_proses(pr,sources)
 d.update(dasar=dasar,aktif=pr.status=='proses',bahan=bobot.teks(),bobot_diketahui=bobot.diketahui,
     jenis_pk=await m.pk_jenis(db,pr),gudang=await label_fasilitas(db,pr),siap=False,penghalang=None)
 d['bobot_acuan']=bobot.angka() if bobot.diketahui else None
 d['rendemen']=m.hitung_rendemen(d['tercatat'],d['bobot_acuan']) if d['bobot_acuan'] is not None else None
 order=await db.get(Jasa,pr.jasa_id) if pr.jasa_id else None;d['pesanan']=order.kode if order else None
 logs=await rows(db,MillingProgressLog,MillingProgressLog.milling_process_id,pr.id)
 qc=await rows(db,MillingQcLog,MillingQcLog.milling_process_id,pr.id)
 ver=await db.scalar(select(MillingProcessVerification).where(MillingProcessVerification.milling_process_id==pr.id))
 people={u.id:u.nama for u in (await db.scalars(select(User).where(User.id.in_({pr.created_by}|{r.input_by for r in logs+qc}|({ver.verified_by} if ver else set()))))).all()}
 d['riwayat_hasil']=[dict(id=r.id,user_id=r.input_by,kg=float(r.berat_kumulatif_kg),waktu=r.waktu_update,petugas=people.get(r.input_by,'Tidak tercatat')) for r in logs]
 d['qc']=qc_view(qc)
 d['riwayat_qc']=[dict(id=r.id,user_id=r.input_by,nomor=i+1,waktu=r.waktu,petugas=people.get(r.input_by,'Tidak tercatat'),kondisi=r.kondisi,catatan_lab=r.catatan_lab,nilai=dict(kadar_air=float(r.kadar_air) if r.kadar_air is not None else None,broken=float(r.broken_persen) if r.broken_persen is not None else None,susut=float(r.susut_persen) if r.susut_persen is not None else None,butir_kuning=r.butir_kuning,gabah=r.gabah,merang=r.merang,catatan_lab=r.catatan_lab),penilaian=qc_view([r])) for i,r in enumerate(sorted(qc,key=lambda x:(x.waktu,x.id)))]
 from app.services.setelan import fitur_mutu
 d['fitur_mutu']=await fitur_mutu(db);d['boleh_qc']=can_see_financials(user) and d['fitur_mutu']
 d['pilihan_qc']=[dict(value=c,label=l) for c,l,_,_ in KLASIFIKASI_QC_PK]
 d['verifikasi']=dict(kg=float(ver.berat_output_final_kg) if ver.berat_output_final_kg is not None else None,waktu=ver.waktu_verifikasi,petugas=people.get(ver.verified_by,'Tidak tercatat'),status=ver.status_verifikasi) if ver else None
 from app.services.berjalan import lama_kata
 end=pr.waktu_selesai if pr.status=='selesai' else now_local();dur=max(0,(end-pr.waktu_mulai).total_seconds()) if end and pr.waktu_mulai else None
 paused=await jeda.tertahan_detik(db,'giling',pr.id,sampai=end) if end else None
 d['waktu']=dict(mulai=pr.waktu_mulai,selesai=pr.waktu_selesai,durasi=lama_kata(dur) if dur is not None else 'Belum tersedia',jeda=lama_kata(paused) if paused else '0 menit' if paused is not None else 'Belum tersedia',aktif=lama_kata(max(0,dur-paused)) if dur is not None and paused is not None else 'Belum tersedia')
 j=await jeda.jeda_terbuka(db,'giling',pr.id);d['jeda']=dict(sebab=j.sebab,mulai=j.mulai) if j else None
 d['boleh_qc']=d['boleh_qc'] and j is None  # Tombol QC pada kartu lama ditutup saat dijeda.
 pauses=await rows(db,JedaProses,JedaProses.milling_process_id,pr.id)
 d['kiriman_jeda']=list((await db.scalars(select(JedaCatatan.kunci_kiriman).where(JedaCatatan.jeda_id.in_([x.id for x in pauses] or [-1]),JedaCatatan.kunci_kiriman.is_not(None)))).all())
 from app.services.riwayat_jeda import riwayat_jeda
 d['jejak_jeda']=await riwayat_jeda(db,jenis='giling',id_=pr.id,semua=True)
 from app.services.proses_aktif import rincian
 detail=await rincian(db,jenis='giling',model=pr,kartu=SimpleNamespace(kode=kode),params={})
 d['asal_html']=templates.get_template('_giling_ringkas_asal.html').render(d=detail)
 d['silos_aktif']=[]
 for name in dict.fromkeys(s['silo'] for s in d['sumber'] if s['sisa'] is None):
  ids=[s['id'] for s in d['sumber'] if s['silo']==name and s['sisa'] is None]
  d['silos_aktif'].append(dict(silo=name,ids=ids))
 logs_a=list((await db.scalars(select(ActivityLog).where(or_(
  (ActivityLog.table_name.in_(['milling_process','milling_progress_logs','milling_qc_logs','milling_process_verifications']))&(ActivityLog.record_id==pr.id),
  (ActivityLog.table_name=='milling_process_sources')&(ActivityLog.record_id.in_([s.id for s in sources] or [-1]))
 )).order_by(ActivityLog.id))).all())
 users={u.id:u.nama for u in (await db.scalars(select(User).where(User.id.in_({r.changed_by for r in logs_a} or {-1})))).all()}
 d['jejak']=[dict(id=r.id,user_id=r.changed_by,record_id=r.record_id,tabel=r.table_name,aksi=r.aksi or r.action,medan=r.field_name,sebelum=r.old_value,sesudah=r.new_value,alasan=r.alasan_perubahan,waktu=r.waktu_perubahan,petugas=users.get(r.changed_by,'Tidak tercatat'),dibatalkan=bool(r.dibatalkan_pada)) for r in logs_a]
 closing=next((a for a in reversed(d['jejak']) if a['aksi']=='selesai_giling_terperiksa' and not a['dibatalkan']),None)
 d['petugas_selesai']=closing['petugas'] if closing else None
 if d['aktif']:
  from app.services.penyelesaian_proses import ringkasan_selesai
  try:await ringkasan_selesai(db,jenis='giling',kode=kode);d['siap']=True
  except ValueError as e:d['penghalang']=str(e)
 return jsonable_encoder(d)

async def halaman(kode,request,akun):
 await izin(akun.user,kode)
 async with SessionLocal() as db:d=await baca(db,kode,akun.user)
 from app.web.layar_pekerjaan import konteks_aman
 return await render_laci(request,'giling_ringkas.html',awal=d,boleh=True,layar='pekerjaan',kembali=konteks_aman(request.query_params.get('kembali_kerja')) or '/pekerjaan?tab=berjalan',breadcrumb_detail=kode,buka=request.query_params.get('buka',''),nilai=request.query_params.get('nilai',''))

@router.get('/api/actions/giling-ringkas/{kode}')
async def papan(kode:str,user:User=Depends(pengguna_aksi)):
 await izin(user,kode)
 async with SessionLocal() as db:return JSONResponse(await baca(db,kode,user),headers={'Cache-Control':'no-store'})

class Permintaan(BaseModel):
 model_config=ConfigDict(extra='forbid')
 dasar:str
 total:FiniteFloat|None=None
 akhir:FiniteFloat|None=None
 silo:str=''
 sumber_ids:list[int]=[]
 sisa:FiniteFloat|None=None
 qc:QcGilingReq|None=None
 pemeriksaan:str=''
 konfirmasi:bool=False

async def rencana(db,kode,req,user,act):
 pr=await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses==kode).with_for_update().execution_options(populate_existing=True))
 if not pr:raise HTTPException(404,'Proses tidak ditemukan.')
 sources=await rows(db,MillingProcessSource,MillingProcessSource.milling_process_id,pr.id)
 ids=set(await si.silo_ids_proses(db,pr))
 if req.silo:
  selected=await si.get_g1_silo(db,req.silo)
  if not selected:raise HTTPException(400,'Silo yang dipilih tidak ditemukan.')
  ids.add(selected.id)
 for sid in sorted(ids):await si.kunci_silo(db,sid)
 if not req.dasar or req.dasar!=await sidik(db,pr):raise HTTPException(409,'Data proses atau stok berubah. Isian tetap tersedia; baca data terbaru dan periksa ulang.')
 if pr.status!='proses' and act!='qc':raise HTTPException(409,'Proses sudah selesai. Gunakan tindakan lanjutan yang diizinkan.')
 base=dict(kode=kode,aksi=act,dasar=req.dasar)
 if act=='hasil':
  HasilGilingReq(kode_proses=kode,berat_kumulatif=req.total)
  base['hasil']=await hasil.ringkasan(db,kode_proses=kode,berat_kumulatif=req.total)
  base['rincian']=await akhir.ringkasan(db,kode_proses=kode,berat_akhir=req.total)
  base['total']=req.total
  # Gunakan pembulatan tipe NUMERIC database yang sama dengan log lama.
  base['tersimpan']=float(await db.scalar(select(cast(literal(req.total,type_=MillingProgressLog.__table__.c.berat_kumulatif_kg.type),MillingProgressLog.__table__.c.berat_kumulatif_kg.type))))
 elif act=='mix':
  if not req.silo:raise HTTPException(400,'Pilih silo yang ditambahkan.')
  base['mix']=await mix.ringkasan(db,kode_proses=kode,silo=req.silo)
 elif act=='bebaskan':
  active=[s['id'] for s in (await akhir.ringkasan(db,kode_proses=kode))['sumber'] if s['sisa'] is None and s['silo']==req.silo]
  if not active or sorted(req.sumber_ids)!=sorted(active):raise HTTPException(409,'Siklus sumber silo tidak lagi sesuai dengan pemeriksaan.')
  if req.sisa is None:raise HTTPException(400,'Sisa fisik wajib diisi; kosong bukan nol.')
  from app.services.penyelesaian_proses import ringkasan_bebaskan
  base['bebaskan']=await ringkasan_bebaskan(db,jenis='giling',kode=kode,silo=req.silo,sisa=req.sisa)
  base['rincian']=await bebas.ringkasan(db,kode_proses=kode,silo=req.silo,sisa=req.sisa)
  base.update(silo=req.silo,sumber_ids=active,sisa=req.sisa)
 elif act=='selesai':
  SelesaiGilingReq(kode_proses=kode,berat_akhir=req.akhir)
  from app.services.penyelesaian_proses import ringkasan_selesai
  base['selesai']=await ringkasan_selesai(db,jenis='giling',kode=kode,berat_akhir=req.akhir)
  base['rincian']=await akhir.ringkasan(db,kode_proses=kode,berat_akhir=req.akhir)
  base['akhir']=req.akhir
 elif act=='qc':
  if not can_see_financials(user):raise HTTPException(403,'Hak pemeriksa QC mengikuti izin aplikasi yang berlaku.')
  await _wajib_mutu()
  if not req.qc or req.qc.kode_proses!=kode:raise HTTPException(400,'QC harus merujuk proses yang sedang diperiksa.')
  from app.services.mutu_pk import wajib_kualitatif
  wajib_kualitatif(butir_kuning=req.qc.butir_kuning,gabah=req.qc.gabah,merang=req.qc.merang)
  if req.qc.catatan_lab and len(req.qc.catatan_lab.strip())>255:raise HTTPException(400,'Catatan lab maksimal 255 karakter.')
  base['qc']=req.qc.model_dump()
  # Korelasi respons yang terputus memakai nilai tersimpan, bukan hanya
  # keberadaan putaran baru dari perangkat lain milik pemeriksa yang sama.
  base['qc_tersimpan']=wajib_kualitatif(butir_kuning=req.qc.butir_kuning,gabah=req.qc.gabah,merang=req.qc.merang)
  for key,col in [('kadar_air','kadar_air'),('broken','broken_persen'),('susut','susut_persen')]:
   value=getattr(req.qc,key)
   base['qc_tersimpan'][key]=float(await db.scalar(select(cast(literal(value,type_=MillingQcLog.__table__.c[col].type),MillingQcLog.__table__.c[col].type)))) if value is not None else None
  base['qc_tersimpan']['catatan_lab']=req.qc.catatan_lab.strip() if req.qc.catatan_lab else None
 else:raise HTTPException(404,'Tindakan tidak dikenali.')
 return jsonable_encoder(base)

def cap(user,act,plan):return hmac.new(_kunci(),json.dumps([user.id,str(user.role),act,plan],sort_keys=True).encode(),hashlib.sha256).hexdigest()

@router.post('/api/actions/giling-ringkas/{kode}/{act}/{step}')
async def tindakan(kode:str,act:str,step:str,req:Permintaan,user:User=Depends(pengguna_aksi)):
 await izin(user,kode)
 if step not in ('periksa','simpan'):raise HTTPException(404,'Langkah tidak dikenali.')
 async with SessionLocal() as db:
  try:
   plan=await rencana(db,kode,req,user,act);token=cap(user,act,plan)
   if step=='periksa':return dict(rencana=plan,pemeriksaan=token)
   if not req.pemeriksaan or not hmac.compare_digest(req.pemeriksaan,token):raise HTTPException(409,'Pemeriksaan berubah atau belum dilakukan. Baca ringkasan terbaru sebelum konfirmasi ulang.')
   if not req.konfirmasi:raise HTTPException(400,'Konfirmasikan pemeriksaan sebelum menyimpan.')
   u=await db.get(User,user.id);warning=None
   if act=='hasil':r=await m.log_progress(db,user=u,kode_proses=kode,berat_kumulatif=req.total);warning=r.peringatan
   elif act=='mix':await m.tambah_silo_giling(db,user=u,kode_proses=kode,nama_silo=req.silo)
   elif act=='bebaskan':await m.tutup_silo_giling(db,user=u,kode_proses=kode,nama_silo=req.silo,sisa_kg=req.sisa,dasar=plan['bebaskan']['dasar'])
   elif act=='selesai':await m.finish_milling(db,user=u,kode_proses=kode,berat_akhir=req.akhir,dasar=plan['selesai']['dasar'])
   else:await m.log_qc_milling(db,user=u,kondisi=None,**req.qc.model_dump())
   return dict(ok=True,pesan='Perubahan penggilingan tercatat melalui layanan yang berlaku.',peringatan=warning,aksi=act)
  except ValidationError as e:
   await db.rollback();raise HTTPException(422,jsonable_encoder(e.errors(include_url=False,include_context=False)))
  except (m.MillingError,ValueError) as e:
   await db.rollback();raise HTTPException(409,str(e))
  except Exception:
   await db.rollback();raise
