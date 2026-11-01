"""Penyajian/konteks penerimaan. Seluruh penyimpanan tetap endpoint lama."""
from types import SimpleNamespace
from fastapi import APIRouter,Depends,Request,HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from app.web.deps import pengguna_aksi
from app.web.portal.scope import is_customer_read

router=APIRouter()
AKSI_PENERIMAAN={'gabah_masuk','catat_pk_luar','tolak_pk_luar','catat_beras_timbang_masuk','catat_broken_timbang_masuk'}

async def lengkapi_catatan(db,catatan):
    from app.models import Jasa,PkRejection
    ids={x['jasa_id'] for x in catatan if x['jasa_id'] is not None}
    jobs=dict((await db.execute(select(Jasa.id,Jasa.kode).where(Jasa.id.in_(ids or {-1})))).all())
    rejects={r.pk_purchase_batch_id:r for r in (await db.scalars(select(PkRejection).where(PkRejection.pk_purchase_batch_id.in_([c['id'] for c in catatan if c['model']=='pk' and c['status']=='ditolak'] or [-1])))).all()}
    for c in catatan:
        c['pesanan']=jobs.get(c['jasa_id'])
        r=rejects.get(c['id']) if c['model']=='pk' else None
        c['penolakan']=dict(kode=r.kode,alasan=r.alasan,waktu=r.waktu,petugas_id=r.created_by) if r else None

async def keadaan(ctx,b,user):
    from app.web.api import actions_menu
    from app.peran import can_see_financials
    specs={a['id']:a for a in await actions_menu(user)}
    t=ctx['tiket'];jenis=ctx['jenis'];pending=ctx['menunggu']
    action=('gabah_masuk' if jenis.startswith('gabah_') else {'pk':'catat_pk_luar','beras':'catat_beras_timbang_masuk','broken':'catat_broken_timbang_masuk'}.get(jenis))
    # Pilihan kartu lama mencakup tumpukan, kondisi alat dan kepemilikan.
    # Jangan menggantinya dengan subset picker remote atau simulasi mockup.
    destinations=[dict(value=x.data['tujuan'],label=x.nama,keterangan=x.ket,alasan=x.mati or '') for row in pending for x in row.tombol if x.data and 'tujuan' in x.data]
    destinations=list({d['value']:d for d in destinations}.values())
    forms=[]
    for id_ in ([action,'tolak_pk_luar'] if jenis=='pk' else [action]):
        if id_ and id_ in specs:
            a=dict(specs[id_]);a['boleh']=bool(a['boleh'] and pending)
            if not pending:a['alasan_akses']='Tiket ini tidak sedang ditawarkan untuk penerimaan. Periksa catatan dan status terbaru.'
            forms.append(a)
    codes={c['kode'] for c in ctx['catatan']}
    tasks=[]
    for row in b.meja:
        if row.aksi and row.aksi.startswith('qc_') and str(row.nilai or '').split('|')[0] in codes and row.aksi in specs and specs[row.aksi]['boleh']:
            tasks.append(dict(kode=row.nilai,aksi=row.aksi,label=specs[row.aksi]['label']))
    lanjutan=[]
    for row in b.menunggu+b.transit:
        if row.kode not in codes:continue
        for id_,nilai in [(row.aksi,row.nilai)]+[(p[0],p[3] if len(p)>3 else row.nilai) for p in row.pilihan]:
            if id_ and id_ not in AKSI_PENERIMAAN and not id_.startswith('qc_') and id_ in specs and specs[id_]['boleh']:
                item=dict(kode=nilai,aksi=id_,label=specs[id_]['label'])
                if item not in lanjutan:lanjutan.append(item)
    received=[c for c in ctx['catatan'] if c['status']!='ditolak']
    qc=[dict(kode=g['kode'],status=g['status']) for g in ctx['qc_penerimaan']]
    # Tiket diberi whitelist: pembaca timbang juga membawa data harga untuk
    # pemanggil lain, yang tidak boleh ikut tersebar ke operator lewat JSON.
    safe={k:t.get(k) for k in ['id','kode','jenis_kode','jenis_nama','arah','status_tiket','status_transaksi','jasa','jasa_kode','nomor_polisi','nama_sopir','nama_supplier','nama_pelanggan','pihak_nama','berat_hpp_kg','sumber_berat']}
    return jsonable_encoder(dict(tiket=safe,jenis=jenis,formulir=forms,tujuan=destinations,
        pending=bool(pending),catatan=ctx['catatan'],berat_diterima=ctx['berat_diterima'],keterangan_berat=ctx['keterangan_berat'],
        status_penerimaan='Penerimaan tercatat' if received else 'Ditolak' if ctx['catatan'] else 'Belum diterima',
        bobot_masuk=ctx['bobot_masuk'],status_qc=qc,qc_tindakan=tasks,tindak_lanjut=lanjutan,boleh_audit=can_see_financials(user)))

@router.get('/api/actions/penerimaan-ringkas/{tid:int}')
async def baca(tid:int,request:Request,user=Depends(pengguna_aksi)):
    if is_customer_read(request):raise HTTPException(403,'Gunakan detail penerimaan pada portal sesuai cakupan pelanggan.')
    from app.web.layar_pekerjaan import konteks_barang_masuk
    ctx,b=await konteks_barang_masuk(tid,request,SimpleNamespace(user=user))
    return JSONResponse(await keadaan(ctx,b,user),headers={'Cache-Control':'no-store'})
