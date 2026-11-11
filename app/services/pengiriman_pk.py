"""Penghubung permintaan→perjalanan→tiket; seluruh perpindahan tetap melalui buku stok lama.

Tidak ada konfirmasi operator tujuan. Timbang selesai dengan selisih absolut
KURANG dari 0,5% mengesahkan muatan asal apa adanya. Angka timbang tetap utuh;
selisih perjalanan tidak pernah dibagi ke lot atau dianggap susut gudang asal.
"""
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
import hashlib, json
from sqlalchemy import select, func, text, inspect
from app.database import now_local
from app.models import (User, Warehouse, Silo, MillingProcess, PermintaanPk,
                        PengirimanPk, PengirimanPkItem)
from app.peran import can_see_financials
from hmu_identitas import peran as P

D=lambda x:Decimal(str(x or 0))
class PengirimanError(ValueError): pass

def angka(x):return format(D(x).normalize(),'f')
def sidik(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def kg(x):
    try:value=Decimal(str(x))
    except (InvalidOperation,TypeError,ValueError):raise PengirimanError('Bobot tidak sah.')
    if not value.is_finite() or value<=0 or value>Decimal('9999999999.99') or value!=value.quantize(Decimal('.01')):raise PengirimanError('Bobot harus positif, maksimal dua desimal.')
    return value

def admin(u):
    if not u or u.status!='aktif' or not can_see_financials(u):raise PermissionError('Tindakan ini memerlukan Admin aktif.')

async def operator_asal(db,u,wid=None):
    if not u or u.status!='aktif':raise PermissionError('Akun tidak aktif.')
    if can_see_financials(u):return
    w=await db.get(Warehouse,u.default_warehouse_id) if u.default_warehouse_id else None
    if not P.operator_saja(u.role) or not w or w.kode_fungsi!='g1' or (wid is not None and w.id!=wid):raise PermissionError('Pengiriman dicatat operator gudang asal yang berwenang.')

async def kunci_stok(db):
    from app.services.barang_keluar import _kunci_saldo_keluar
    await _kunci_saldo_keluar(db)

async def kunci_perjalanan(db,pid):
    if db.bind.dialect.name=='postgresql':await db.execute(text('SELECT pg_advisory_xact_lock(14146833,:id)'),{'id':pid})

async def reservasi(db):
    """Alokasi yang belum berubah menjadi transfer fisik, termasuk yang sedang ditimbang.

    Pelepasan sementara hanya untuk item yang sedang difinalisasi dalam sesi
    writer ini. Sesi lain tetap melihat seluruh alokasi sampai transaksi commit.
    """
    sent=dict((await db.execute(select(PengirimanPkItem.permintaan_id,func.sum(PengirimanPkItem.berat_kg))
        .where(PengirimanPkItem.internal_transfer_id.is_not(None)).group_by(PengirimanPkItem.permintaan_id))).all())
    result={}
    for r in (await db.scalars(select(PermintaanPk).where(PermintaanPk.bertahap.is_(True),PermintaanPk.status.in_(['disetujui','dikirim'])))).all():
        key=(r.milling_process_id,r.jasa_id)
        result[key]=result.get(key,D(0))+max(D(0),D(r.berat_setuju_kg)-D(sent.get(r.id)))
    for key,value in db.info.get('pk_transfer_dilepas',{}).items():result[key]=max(D(0),result.get(key,D(0))-value)
    return result

@contextmanager
def lepas_item(db,r,value):
    old=db.info.get('pk_transfer_dilepas',{})
    db.info['pk_transfer_dilepas']={**old,(r.milling_process_id,r.jasa_id):D(value)}
    try:yield
    finally:db.info['pk_transfer_dilepas']=old

async def terpakai(db,rid,*,selesai=False):
    q=select(func.coalesce(func.sum(PengirimanPkItem.berat_kg),0)).join(PengirimanPk,PengirimanPk.id==PengirimanPkItem.pengiriman_id).where(PengirimanPkItem.permintaan_id==rid,PengirimanPk.status!='dibatalkan')
    if selesai:q=q.where(PengirimanPk.status=='selesai')
    return D(await db.scalar(q))

async def sisa(db,r):return max(D(0),D(r.berat_setuju_kg)-await terpakai(db,r.id))

async def _rute(db,r):
    proc=await db.get(MillingProcess,r.milling_process_id)
    # Sumber lama mengikuti pembaca fasilitas kanonis, bukan default akun.
    from app.services.cakupan_fasilitas import lokasi_banyak
    loc=(await lokasi_banyak(db,MillingProcess,[proc.id]))[proc.id]
    asal=await db.get(Warehouse,loc['warehouse_id'])
    silo=await db.get(Silo,r.silo_id) if r.silo_id else None
    tujuan=await db.get(Warehouse,silo.warehouse_id) if silo else await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2',Warehouse.aktif.is_(True)))
    if not asal or not asal.aktif or not tujuan or not tujuan.aktif:raise PengirimanError('Gudang asal atau tujuan tidak aktif.')
    if silo and (not silo.aktif or silo.jenis_isi!='pk'):raise PengirimanError('Silo tujuan bukan silo PK aktif.')
    return proc,asal,tujuan,silo

async def _jejak(db,j,user,aksi,pesan):
    from app.services.activity_log import log_activity
    await log_activity(db,table_name='pengiriman_pk',record_id=j.id,action='UPDATE' if aksi!='buat' else 'INSERT',changed_by=user.id,new_value=pesan,aksi='pengiriman_pk_'+aksi)

async def setujui_banyak(db,*,user,items):
    """Satu commit untuk semua pilihan. Permintaan yang tidak dipilih tetap utuh."""
    admin(user);await kunci_stok(db)
    ids=[x['permintaan_id'] for x in items]
    if not ids or len(ids)!=len(set(ids)):raise PengirimanError('Pilih permintaan berbeda sedikitnya satu.')
    rows={r.id:r for r in (await db.scalars(select(PermintaanPk).where(PermintaanPk.id.in_(ids)).order_by(PermintaanPk.id).with_for_update())).all()}
    from app.penggilingan.gudang2.service import _tujuan_and_silo,Gudang2Error
    from app.services.transfer import pending_transfer_kg
    from app.services.jasa import cocok_pemilik,pemilik_silo_g2
    from app.services.permintaan_pk import _jejak as jejak_minta,_kabar,_kode_lot
    for x in items:
        r=rows.get(x['permintaan_id']);value=kg(x['berat_kg'])
        if not r or r.status!='diminta':raise PengirimanError('Permintaan sudah berubah; baca daftar terbaru.')
        if value>D(await pending_transfer_kg(db,r.milling_process_id,pemilik_id=r.jasa_id,bebas=True)):raise PengirimanError('Stok bebas lot tidak mencukupi persetujuan.')
        try:tujuan,silo_id=await _tujuan_and_silo(db,x['tujuan'])
        except Gudang2Error as e:raise PengirimanError(str(e)) from None
        if silo_id:
            owners=await pemilik_silo_g2(db,silo_id)
            if not all([await cocok_pemilik(db,r.jasa_id,o) for o in owners]):raise PengirimanError('Pemilik silo tujuan berbeda dari lot.')
        r.bertahap=True;r.status='disetujui';r.tujuan=tujuan;r.silo_id=silo_id;r.berat_setuju_kg=value;r.disetujui_oleh=user.id;r.waktu_setuju=now_local()
        await db.flush()
        await jejak_minta(db,r,langkah='setujui_bertahap',oleh=user,ringkas='Disetujui '+angka(value)+' kg; pengiriman per perjalanan setelah timbang.')
        await _kabar(db,r,untuk='operator',pesan='Permintaan '+await _kode_lot(db,r)+' disetujui '+angka(value)+' kg. Operator asal dapat membuat pengiriman sebagian.',prioritas='hijau')
    await db.commit()
    return dict(ok=True,permintaan_ids=ids)

async def buat(db,*,user,items,nomor_polisi,nama_sopir,kunci):
    await operator_asal(db,user);await kunci_stok(db)
    nomor_polisi=' '.join(nomor_polisi.upper().split());nama_sopir=' '.join(nama_sopir.split())
    if len(nomor_polisi)>20 or len(nama_sopir)>100:raise PengirimanError('Nomor polisi maksimal 20 karakter dan sopir maksimal 100 karakter.')
    if not nomor_polisi or not nama_sopir:raise PengirimanError('Isi nomor polisi dan sopir.')
    ids=[x['permintaan_id'] for x in items]
    if not ids or len(ids)!=len(set(ids)):raise PengirimanError('Pilih permintaan berbeda sedikitnya satu.')
    payload=dict(items=sorted([dict(permintaan_id=x['permintaan_id'],berat_kg=angka(kg(x['berat_kg']))) for x in items],key=lambda x:x['permintaan_id']),nomor_polisi=nomor_polisi,nama_sopir=nama_sopir)
    signature=sidik(payload);key='pk:'+str(user.id)+':'+kunci
    old=await db.scalar(select(PengirimanPk).where(PengirimanPk.kunci==key))
    if old:
        if old.sidik!=signature:raise PengirimanError('Kunci kiriman sudah dipakai untuk muatan berbeda.')
        return dict(ok=True,id=old.id,ulang=True)
    requests={r.id:r for r in (await db.scalars(select(PermintaanPk).where(PermintaanPk.id.in_(ids)).order_by(PermintaanPk.id).with_for_update())).all()}
    route=None;owner=...;now=now_local()
    from app.services.jasa import cocok_pemilik
    from app.services.transfer import pending_transfer_kg
    for x in payload['items']:
        r=requests.get(x['permintaan_id'])
        if not r or r.status not in ('disetujui','dikirim'):raise PengirimanError('Pilih permintaan yang sudah disetujui dan belum selesai.')
        if not r.bertahap:
            if r.internal_transfer_id is not None or r.status!='disetujui':raise PengirimanError('Permintaan memakai transfer lama; lanjutkan melalui alurnya sendiri.')
            if D(r.berat_setuju_kg)>D(await pending_transfer_kg(db,r.milling_process_id,pemilik_id=r.jasa_id,bebas=True)):raise PengirimanError('Stok bebas tidak lagi mencukupi sisa persetujuan.')
            r.bertahap=True;await db.flush()
        if kg(x['berat_kg'])>await sisa(db,r):raise PengirimanError('Muatan melebihi sisa persetujuan; perjalanan yang masih berjalan sudah diperhitungkan.')
        proc,a,t,s=await _rute(db,r);await operator_asal(db,user,a.id)
        current=(a.id,t.id,s.id if s else None)
        if route and route!=current:raise PengirimanError('Gabungkan hanya permintaan dengan asal dan tujuan yang sama.')
        if owner is not ... and not await cocok_pemilik(db,owner,r.jasa_id):raise PengirimanError('Pemilik muatan berbeda; buat perjalanan terpisah.')
        route=current;owner=r.jasa_id
    j=PengirimanPk(kunci=key,sidik=signature,asal_id=route[0],tujuan_id=route[1],silo_id=route[2],jasa_id=owner,nomor_polisi=nomor_polisi,nama_sopir=nama_sopir,dibuat_oleh=user.id,waktu=now,status='dalam_perjalanan')
    db.add(j);await db.flush()
    for x in payload['items']:
        r=requests[x['permintaan_id']];sebelumnya=await terpakai(db,r.id);db.add(PengirimanPkItem(pengiriman_id=j.id,permintaan_id=r.id,berat_kg=D(x['berat_kg'])))
        r.status='dikirim';r.berat_kirim_kg=sebelumnya+D(x['berat_kg']);r.dikirim_oleh=user.id;r.waktu_kirim=now
    await _jejak(db,j,user,'buat','Muatan perjalanan dicatat; menunggu timbang, belum menambah stok tujuan.')
    await db.commit();return dict(ok=True,id=j.id,ulang=False)

async def rincian(db,pid):
    j=await db.get(PengirimanPk,pid)
    if not j:raise PengirimanError('Pengiriman PK tidak ditemukan.')
    a=await db.get(Warehouse,j.asal_id);t=await db.get(Warehouse,j.tujuan_id);s=await db.get(Silo,j.silo_id) if j.silo_id else None
    rows=(await db.execute(select(PengirimanPkItem,PermintaanPk,MillingProcess).join(PermintaanPk,PermintaanPk.id==PengirimanPkItem.permintaan_id).join(MillingProcess,MillingProcess.id==PermintaanPk.milling_process_id).where(PengirimanPkItem.pengiriman_id==pid).order_by(PengirimanPkItem.id))).all()
    items=[dict(id=i.id,permintaan_id=r.id,lot=p.kode_proses,berat_kg=angka(i.berat_kg),transfer_id=i.internal_transfer_id,jasa_id=r.jasa_id) for i,r,p in rows]
    # The ticket is created by TeraFlow before its first completion callback.
    # Resolve it even while that callback has not reached PadiFlow yet.
    columns=await db.run_sync(lambda d:{c['name'] for c in inspect(d.connection()).get_columns('timbangan_transaksi')})
    ticket=None
    if 'pengiriman_pk_id' in columns:
        ticket=(await db.execute(text('SELECT id,status_tiket FROM timbangan_transaksi WHERE pengiriman_pk_id=:id LIMIT 1'),{'id':pid})).mappings().first()

    return dict(id=j.id,waktu=j.waktu.isoformat(),waktu_selesai=j.waktu_selesai.isoformat() if j.waktu_selesai else None,status=j.status,sidik=j.sidik,nomor_polisi=j.nomor_polisi,nama_sopir=j.nama_sopir,tiket_id=j.tiket_id or (ticket['id'] if ticket else None),status_tiket=ticket['status_tiket'] if ticket else None,total=angka(sum((D(i['berat_kg']) for i in items),D(0))),items=items,
                lintasan=dict(versi=1,asal=dict(gudang_id=a.id,nama=a.nama_gudang),tujuan=dict(gudang_id=t.id,silo_id=j.silo_id,pilihan='silo:'+str(s.id) if s else 'gudang:'+str(t.id),nama=s.nama_silo+' · '+t.nama_gudang if s else 'Tumpukan · '+t.nama_gudang)),
                bobot_timbang_kg=None if j.bobot_timbang_kg is None else angka(j.bobot_timbang_kg),selisih_kg=None if j.selisih_kg is None else angka(j.selisih_kg),alasan=j.alasan)

async def sinkron(db,*,pid,tid,user=None,alasan=None):
    """Token layanan hanya meminta pembacaan; bobot selalu dibaca dari tiket terkunci.

    Urutan kunci: koordinasi perjalanan → tiket → stok → perjalanan/permintaan.
    Post timbang memanggil sesudah commit; pemanggilan yang hilang dapat diulang.
    """
    await kunci_perjalanan(db,pid)
    ticket=(await db.execute(text('SELECT * FROM timbangan_transaksi WHERE id=:id FOR UPDATE'),{'id':tid})).mappings().first()
    if not ticket or ticket.get('pengiriman_pk_id')!=pid or ticket.get('arah')!='TRANSFER' or ticket.get('cara_timbang')=='PARTAI':raise PengirimanError('Tiket bukan milik perjalanan transfer ini.')
    await kunci_stok(db)
    j=await db.scalar(select(PengirimanPk).where(PengirimanPk.id==pid).with_for_update())
    if not j or j.status=='dibatalkan':raise PengirimanError('Pengiriman tidak aktif.')
    route=ticket.get('lintasan_transfer')
    if isinstance(route,str):route=json.loads(route)
    if not isinstance(route,dict) or route.get('_pengiriman_pk',{}).get('sidik')!=j.sidik:raise PengirimanError('Cuplikan muatan tiket tidak cocok dengan perjalanan.')
    if route.get('asal',{}).get('gudang_id')!=j.asal_id or route.get('tujuan',{}).get('gudang_id')!=j.tujuan_id or route.get('tujuan',{}).get('silo_id')!=j.silo_id:raise PengirimanError('Lintasan tiket berbeda dari tujuan yang disetujui.')
    if j.tiket_id is not None and j.tiket_id!=tid:raise PengirimanError('Perjalanan sudah memiliki tiket lain.')
    if ticket.get('status_transaksi')=='VOID' or ticket.get('status_tiket')!='SELESAI':raise PengirimanError('Selesaikan timbang sebelum menyelesaikan transfer.')
    measured=D(ticket.get('berat_barang_kg'))
    if not measured.is_finite() or measured<=0:raise PengirimanError('Hasil timbang belum sah.')
    if j.status=='selesai':
        if D(j.bobot_timbang_kg)!=measured:raise PengirimanError('Tiket berubah setelah stok dicatat; gunakan pemeriksaan koreksi yang menjaga stok.')
        return dict(ok=True,status=j.status,ulang=True)
    items=list((await db.scalars(select(PengirimanPkItem).where(PengirimanPkItem.pengiriman_id==pid).order_by(PengirimanPkItem.permintaan_id).with_for_update())).all())
    requests={r.id:r for r in (await db.scalars(select(PermintaanPk).where(PermintaanPk.id.in_([i.permintaan_id for i in items])).order_by(PermintaanPk.id).with_for_update())).all()}
    total=sum((D(i.berat_kg) for i in items),D(0));delta=measured-total
    if total<=0:raise PengirimanError('Muatan perjalanan kosong.')
    j.tiket_id=tid;j.bobot_timbang_kg=measured;j.selisih_kg=delta
    if abs(delta)*200>=total and alasan is None:
        j.status='menunggu_admin';j.alasan='Selisih absolut mencapai 0,5% atau lebih; menunggu keputusan Admin.'
        await db.commit();return dict(ok=True,status=j.status,selisih_kg=angka(delta))
    if alasan is not None:
        admin(user)
        if not alasan.strip():raise PengirimanError('Isi alasan menerima selisih perjalanan.')
        j.diputus_oleh=user.id;j.alasan=alasan.strip()
    actor=user if user else await db.get(User,j.dibuat_oleh)
    from app.services.transfer import create_internal_transfer,TransferError
    from app.penggilingan.gudang2.service import label_tujuan
    from app.services.permintaan_pk import _jejak as jejak_minta
    for i in items:
        r=requests[i.permintaan_id]
        if not r.bertahap or r.status not in ('disetujui','dikirim'):raise PengirimanError('Permintaan lot sudah berubah sebelum pencatatan stok.')
        if i.internal_transfer_id:raise PengirimanError('Sebagian perjalanan telah tercatat secara tidak lengkap; periksa jejak sebelum melanjutkan.')
        proc=await db.get(MillingProcess,r.milling_process_id)
        if j.silo_id:
            from app.penggilingan.gudang2.service import hitung_stok_silo
            silo=await db.scalar(select(Silo).where(Silo.id==j.silo_id).with_for_update())
            if not silo or not silo.aktif or silo.jenis_isi!='pk':raise PengirimanError('Silo tujuan tidak lagi tersedia untuk PK.')
            if silo.kapasitas_ton is not None and D(await hitung_stok_silo(db,silo.id))+D(i.berat_kg)>D(silo.kapasitas_ton)*1000:
                raise PengirimanError('Kapasitas silo tujuan tidak mencukupi perjalanan. Timbangan tetap tersimpan; pencatatan stok menunggu ruang tersedia.')
        with lepas_item(db,r,i.berat_kg):
            result=await create_internal_transfer(db,user=actor,kode_proses=proc.kode_proses,lokasi_tujuan=(await db.get(Silo,r.silo_id)).nama_silo if r.silo_id else 'ditumpuk',berat=float(i.berat_kg),pemilik_id=r.jasa_id,kunci_kiriman='pengiriman-pk:'+str(pid)+':item:'+str(i.id),commit=False,aksi='pengiriman_pk_selesai',alasan=alasan or 'Selisih kurang dari 0,5%; bobot lot asal dianggap genap.')
        if D(result.transfer.berat_kg)!=D(i.berat_kg):raise PengirimanError('Bobot transfer terpotong oleh saldo; seluruh perjalanan dibatalkan penyimpanannya.')
        i.internal_transfer_id=result.transfer.id;await db.flush()
    j.status='selesai';j.waktu_selesai=now_local();await db.flush()
    for r in requests.values():
        final=await terpakai(db,r.id,selesai=True)
        if final>D(r.berat_setuju_kg):raise PengirimanError('Akumulasi perjalanan melebihi persetujuan lot.')
        if final==D(r.berat_setuju_kg):
            r.status='selesai';r.berat_final_kg=final;r.waktu_tutup=now_local();r.sebab='Selesai otomatis dari seluruh perjalanan yang sudah selesai timbang.'
            await jejak_minta(db,r,langkah='selesai_bertahap',oleh=actor,ringkas=r.sebab)
    await _jejak(db,j,actor,'selesai','Hasil timbang '+angka(measured)+' kg; muatan lot '+angka(total)+' kg; selisih '+angka(delta)+' kg. Tanpa konfirmasi penerimaan operator tujuan.')
    await db.commit();return dict(ok=True,status='selesai',selisih_kg=angka(delta),ulang=False)

async def batalkan(db,*,pid,user,alasan):
    admin(user)
    if not alasan.strip():raise PengirimanError('Isi alasan pembatalan.')
    await kunci_perjalanan(db,pid);await kunci_stok(db)
    j=await db.scalar(select(PengirimanPk).where(PengirimanPk.id==pid).with_for_update())
    if not j:raise PengirimanError('Pengiriman tidak ditemukan.')
    if j.status=='dibatalkan':return dict(ok=True,ulang=True)
    if j.status!='dalam_perjalanan' or j.tiket_id is not None:raise PengirimanError('Pengiriman sudah mempunyai hasil timbang; pembatalan terpisah ditahan.')
    columns=await db.run_sync(lambda d:{c['name'] for c in inspect(d.connection()).get_columns('timbangan_transaksi')})
    ticket=await db.scalar(text('SELECT id FROM timbangan_transaksi WHERE pengiriman_pk_id=:id LIMIT 1'),{'id':pid}) if 'pengiriman_pk_id' in columns else None
    if ticket is not None:raise PengirimanError('Pengiriman sudah memiliki tiket; periksa melalui jejak timbang, tidak membebaskan muatan diam-diam.')
    j.status='dibatalkan';j.alasan=alasan.strip();j.diputus_oleh=user.id
    await db.flush()
    ids=list((await db.scalars(select(PengirimanPkItem.permintaan_id).where(PengirimanPkItem.pengiriman_id==pid))).all())
    for r in (await db.scalars(select(PermintaanPk).where(PermintaanPk.id.in_(ids)).order_by(PermintaanPk.id).with_for_update())).all():
        allocated=await terpakai(db,r.id);r.berat_kirim_kg=allocated
        r.status='dikirim' if allocated>0 else 'disetujui'

    await _jejak(db,j,user,'batal',j.alasan);await db.commit();return dict(ok=True)

async def tutup_sisa(db,*,rid,user,alasan):
    """Batasi penutupan administratif ke sisa yang belum berangkat.

    Persetujuan asli tidak ditulis ulang. Barang yang sudah berangkat harus
    diselesaikan lewat tiketnya dahulu, bukan dilepas sebagai stok bebas.
    """
    admin(user)
    if not alasan.strip():raise PengirimanError('Isi alasan tidak mengirim sisa persetujuan.')
    await kunci_stok(db)
    r=await db.scalar(select(PermintaanPk).where(PermintaanPk.id==rid).with_for_update())
    if not r or not r.bertahap or r.status not in ('disetujui','dikirim'):raise PengirimanError('Permintaan sudah berubah atau bukan persetujuan bertahap aktif.')
    allocated=await terpakai(db,rid);completed=await terpakai(db,rid,selesai=True)
    if allocated!=completed:raise PengirimanError('Masih ada perjalanan yang belum selesai. Selesaikan timbang dan pencatatan stoknya dahulu.')
    r.status='selesai' if completed>0 else 'gugur';r.berat_final_kg=completed;r.ditutup_oleh=user.id;r.waktu_tutup=now_local();r.sebab='Sisa persetujuan tidak dikirim: '+alasan.strip()
    from app.services.permintaan_pk import _jejak as jejak_minta,_kabar
    await jejak_minta(db,r,langkah='tutup_sisa_bertahap',oleh=user,ringkas=r.sebab+'; selesai '+angka(completed)+' kg dari persetujuan '+angka(r.berat_setuju_kg)+' kg.')
    await _kabar(db,r,untuk='operator',pesan=r.sebab,prioritas='kuning')
    await db.commit();return dict(ok=True)
