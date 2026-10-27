"""Proyeksi baca riwayat. Tidak memanggil pemeriksaan, reservasi, atau mutasi.

Agregasi item/aktual dilakukan terpisah dari ledger dan audit. Satu ledger
keluar tetap dihitung sekali, termasuk bila label pengajuan kemudian berubah.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
import json
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, exists, text
from sqlalchemy.exc import DBAPIError
from hmu_identitas import peran as P
from app.config import settings
from app.models import Warehouse, User, ActivityLog
from app.models.retur_supplier import (ReturSupplier as R, ReturSupplierItem as I,
    ReturSupplierAktual as A, ReturSupplierPemeriksaan as C, ReturSupplierKeluar as K)
from app.services import retur_supplier as s
from app.services.retur_supplier_selesai import versi_tiket

STATUS = {'ticket':'Menunggu tiket', 'weigh':'Menunggu timbang kedua',
    'check':'Menunggu pemeriksaan', 'correction':'Perlu koreksi',
    'manual':'Menunggu verifikasi manual', 'ready':'Siap dicatat keluar',
    'done':'Barang keluar tercatat', 'cancel':'Dibatalkan',
    'stale':'Perlu pemeriksaan ulang', 'blocked':'Tiket perlu diperiksa',
    'unknown':'Status tiket terkini belum dapat dipastikan'}
UKURAN_HALAMAN = 20


def rentang(awal='', akhir=''):
    try:
        a = date.fromisoformat(awal) if awal else None
        b = date.fromisoformat(akhir) if akhir else None
        if a and b and a > b: raise ValueError()
        zona = ZoneInfo(settings.app_timezone)
        return (datetime.combine(a,time.min,zona) if a else None,
                datetime.combine(b+timedelta(days=1),time.min,zona) if b else None)
    except (ValueError, OverflowError):
        raise ValueError('Rentang tanggal tidak sah. Tanggal akhir harus sama atau setelah tanggal awal.') from None


async def cakupan(db,user):
    efektif=await s.pelaku(db,user)
    wh=(await db.scalars(select(Warehouse).where(Warehouse.kode_fungsi.in_(['g1','g2'])))).all()
    if not P.admin_keatas(efektif.role):
        wh=[w for w in wh if w.aktif and w.id==efektif.default_warehouse_id]
    return efektif,wh


def terbatas(ids):
    # Harus seluruh item berada di cakupan, sama dengan layanan ambil().
    return (exists(select(I.id).where(I.retur_supplier_id==R.id)),
        ~exists(select(I.id).where(I.retur_supplier_id==R.id,I.warehouse_id.not_in(ids))))


async def tiket_banyak(db,ids):
    if not ids:return {},False
    try:
        # Savepoint membiarkan rekaman historis tetap dibaca bila relasi
        # integrasi sementara tidak tersedia. Tidak mengubah status tiket.
        async with db.begin_nested():
            rows=(await db.execute(text('''SELECT id,kode,arah,jenis_kode,supplier_id,
                status_tiket,status_transaksi,jumlah_revisi,updated_at,
                timbang1_kg,timbang2_kg,timbang1_waktu,timbang2_waktu,
                berat_barang_kg,total_tara_kg,tara_lain_kg,nomor_polisi,nama_sopir
                FROM timbangan_transaksi WHERE id=ANY(:ids)'''),{'ids':list(ids)})).mappings().all()
        return {r['id']:dict(r) for r in rows},False
    except DBAPIError:
        return {},True


def keadaan(rec,last,keluar,tiket,*,gagal=False):
    if keluar:return 'done'
    if rec.status=='dibatalkan':return 'cancel'
    if not rec.timbangan_transaksi_id:return 'ticket'
    if gagal or not tiket:return 'unknown'
    try:s.syarat_tiket(tiket,rec)
    except ValueError:return 'blocked'
    if tiket['status_tiket']!='SELESAI':return 'weigh'
    if last and (last.versi_aktual!=rec.versi_aktual or
            last.snapshot.get('versi_tiket')!=versi_tiket(tiket)):return 'stale'
    if last and last.status=='perlu_koreksi':return 'correction'
    v=rec.verifikasi
    if v and v.get('versi_aktual')==rec.versi_aktual and v.get('versi_tiket')==versi_tiket(tiket):
        if not rec.wajib_manual or v.get('metode')=='manual':return 'ready'
    if rec.wajib_manual:return 'manual'
    return 'check'


async def daftar(db,user,*,q='',awal='',akhir='',status='',supplier=None,gudang=None,penerimaan=None,halaman=1):
    efektif,wh=await cakupan(db,user)
    ids=[w.id for w in wh]
    if gudang and gudang not in ids:raise PermissionError('Gudang berada di luar cakupan akses akun.')
    if status and status not in STATUS:raise ValueError('Status filter tidak dikenal.')
    if halaman<1:raise ValueError('Nomor halaman harus positif.')
    mulai,sampai=rentang(awal,akhir)
    scope=terbatas(ids)
    dasar=select(R).where(*scope)
    # Pilihan supplier hanya berasal dari catatan yang dapat dibaca; tidak
    # menampilkan master supplier gudang lain melalui daftar filter.
    options=(await db.execute(select(R.supplier_id,R.sumber).where(*scope,
        *([R.penerimaan_tiket_id==penerimaan] if penerimaan else [])))).all()
    suppliers={sid:src.get('supplier','Supplier historis') for sid,src in options}
    if supplier and supplier not in suppliers:raise PermissionError('Supplier tidak tersedia dalam cakupan riwayat ini.')
    asal=None
    if penerimaan:
        # Izin cakupan penerimaan tetap diperiksa walaupun belum ada retur.
        meta=(await db.execute(text('SELECT id,kode,jenis_kode FROM timbangan_transaksi WHERE id=:id AND arah=\'MASUK\''),{'id':penerimaan})).mappings().first()
        if not meta:raise ValueError('Penerimaan asal tidak ditemukan.')
        from app.services.barang_masuk import jenis_tiket
        fungsi='g1' if jenis_tiket(meta['jenis_kode']).startswith('gabah') else 'g2'
        if fungsi not in {w.kode_fungsi for w in wh}:raise PermissionError('Penerimaan berada di luar gudang akun.')
        asal=dict(meta)
        dasar=dasar.where(R.penerimaan_tiket_id==penerimaan)
    if mulai:dasar=dasar.where(R.waktu>=mulai)
    if sampai:dasar=dasar.where(R.waktu<sampai)
    if supplier:dasar=dasar.where(R.supplier_id==supplier)
    if gudang:dasar=dasar.where(exists(select(I.id).where(I.retur_supplier_id==R.id,I.warehouse_id==gudang)))
    agg=select(I.retur_supplier_id.label('rid'),func.count(I.id).label('n'),func.sum(I.bobot_kg).label('pengajuan'),
        func.string_agg(func.distinct(I.snapshot['gudang'].as_string()),' · ').label('gudang'),
        func.string_agg(I.snapshot['nama'].as_string()+' '+I.snapshot['kode'].as_string(),' ').label('barang'),
        func.sum(A.bobot_kg).label('aktual'),func.count(A.item_id).label('na')).outerjoin(A,A.item_id==I.id).group_by(I.retur_supplier_id).subquery()
    terbaru=select(C.retur_supplier_id.label('rid'),func.max(C.id).label('id')).group_by(C.retur_supplier_id).subquery()
    rows=(await db.execute(select(R,agg.c.n,agg.c.pengajuan,agg.c.gudang,agg.c.barang,agg.c.aktual,agg.c.na,C,K)
        .join(agg,agg.c.rid==R.id).outerjoin(terbaru,terbaru.c.rid==R.id).outerjoin(C,C.id==terbaru.c.id)
        .outerjoin(K,K.retur_supplier_id==R.id).where(R.id.in_(dasar.with_only_columns(R.id)))
        .order_by(R.waktu.desc(),R.id.desc()))).all()
    tickets,gagal=await tiket_banyak(db,{r[0].timbangan_transaksi_id for r in rows if r[0].timbangan_transaksi_id})
    hasil=[]
    for r,n,proposal,warehouse,barang,actual,na,last,ledger in rows:
        t=tickets.get(r.timbangan_transaksi_id)
        st=keadaan(r,last,ledger,t,gagal=gagal)
        if status and status!=st:continue
        kode_historis=(ledger.snapshot if ledger else last.snapshot if last else {}).get('kode_tiket')
        hay=' '.join(str(v or '') for v in [r.kode,r.sumber.get('supplier'),r.sumber.get('kode_tiket'),r.sumber.get('nota'),
            barang,t.get('kode') if t else kode_historis,t.get('nomor_polisi') if t else '',ledger.kode if ledger else ''])
        if q.strip().casefold() not in hay.casefold():continue
        kg=ledger.snapshot.get('total_kg') if ledger else None
        hasil.append(dict(rec=r,jumlah_item=n,pengajuan=proposal,gudang=warehouse,
            aktual=actual if na==n else None,keluar=D(kg) if kg is not None else None,ledger=ledger,status=st))
    total=len(hasil);pages=max(1,(total+UKURAN_HALAMAN-1)//UKURAN_HALAMAN)
    halaman=min(halaman,pages)
    return dict(rows=hasil[(halaman-1)*UKURAN_HALAMAN:halaman*UKURAN_HALAMAN],total=total,halaman=halaman,pages=pages,
        total_keluar=sum((r['keluar'] for r in hasil if r['keluar'] is not None),D(0)),
        jumlah_keluar=sum(r['ledger'] is not None for r in hasil),keluar_tidak_lengkap=sum(r['ledger'] is not None and r['keluar'] is None for r in hasil),
        suppliers=suppliers,warehouses=wh,asal=asal,gagal_tiket=gagal,efektif=efektif)


def baca_json(v):
    if isinstance(v,str):
        try:return json.loads(v)
        except ValueError:return v
    return v


def stok_href(i):
    from app.web.stok_navigasi import alamat
    # Gunakan pintu Stok yang sudah memeriksa izin. Kode partai tetap tampil
    # di sebelah tautan bila sumber lama tidak memiliki URL detail tersendiri.
    return alamat('produk' if i.finished_goods_stock_id or i.byproduct_stock_id else 'bahan','pabrik',
        gudang='g1' if i.purchase_batch_id else 'g2')


async def koreksi_tiket(db,user,kode):
    """Hanya bidang timbang dari audit tiket ini, dengan gerbang Super TF.

    Izin PadiFlow saja tidak cukup. Profil TeraFlow aktif tertaut ke akun
    bersama aktif (atau profil lama Super milik orang yang sama) diperlukan.
    Tidak menjalankan sinkronisasi profil, login, atau pemeriksaan tiket.
    """
    efektif=await s.pelaku(db,user)
    if not kode or not P.super_saja(efektif.role):return [],'dibatasi'
    try:
        async with db.begin_nested():
            ada=await db.scalar(text("SELECT to_regclass('timbangan_akun') IS NOT NULL AND to_regclass('timbangan_audit') IS NOT NULL"))
            if not ada:return [],'belum_tersedia'
            izin=await db.scalar(text('''SELECT EXISTS(SELECT 1 FROM timbangan_akun t
                LEFT JOIN produksi_akun p ON p.id=t.akun_id
                WHERE t.status='aktif' AND ((t.akun_id IS NOT NULL AND p.user_id=:uid AND p.status='aktif')
                OR (t.akun_id IS NULL AND t.user_id=:uid AND t.role='SUPERADMIN')))'''),{'uid':user.id})
            if not izin:return [],'dibatasi'
            rows=(await db.execute(text('''SELECT waktu,akun_nama,ringkasan,nilai_sebelum,nilai_sesudah
                FROM timbangan_audit WHERE entitas='transaksi' AND entitas_id=:kode AND aksi='KOREKSI' ORDER BY id'''),{'kode':kode})).mappings().all()
        hasil=[]
        for row in rows:
            a,b=baca_json(row['nilai_sebelum']),baca_json(row['nilai_sesudah'])
            if not isinstance(a,dict) or not isinstance(b,dict):continue
            nilai=[dict(field=k,sebelum=a[k],sesudah=b[k]) for k in
                ('timbang1_kg','timbang2_kg','berat_barang_kg','total_tara_kg','tara_lain_kg')
                if k in a and k in b and str(a[k])!=str(b[k])]
            if nilai:hasil.append(dict(waktu=row['waktu'],oleh=row['akun_nama'],alasan=row['ringkasan'],nilai=nilai))
        return hasil,'tersedia'
    except DBAPIError:return [],'belum_tersedia'


async def detail(db,identitas,user):
    rec,items=await s.ambil(db,identitas,user)
    latest=await db.scalar(select(C).where(C.retur_supplier_id==rec.id).order_by(C.id.desc()).limit(1))
    ledger=await db.scalar(select(K).where(K.retur_supplier_id==rec.id))
    actual={a.item_id:a for a in (await db.scalars(select(A).where(A.item_id.in_([i.id for i in items])))).all()}
    tickets,gagal=await tiket_banyak(db,{rec.timbangan_transaksi_id} if rec.timbangan_transaksi_id else set())
    t=tickets.get(rec.timbangan_transaksi_id)
    audits=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='retur_supplier',ActivityLog.record_id==rec.id).order_by(ActivityLog.id))).all()
    checks=(await db.scalars(select(C).where(C.retur_supplier_id==rec.id).order_by(C.id))).all()
    # Snapshot transaksi menjadi sumber mutasi historis, bukan saldo sekarang.
    snap=ledger.snapshot if ledger else latest.snapshot if latest else None
    out={x.get('item_id'):x for x in (ledger.snapshot.get('items',[]) if ledger else [])}
    verifier=(ledger.snapshot.get('verifikasi') if ledger else rec.verifikasi) or {}
    uids={rec.input_by,rec.tiket_dihubungkan_oleh,rec.dibatalkan_oleh,verifier.get('oleh')}
    uids.update(a.changed_by for a in audits);uids.update(c.input_by for c in checks)
    if ledger:uids.add(ledger.input_by)
    users=dict((await db.execute(select(User.id,User.nama).where(User.id.in_([v for v in uids if v])))).all())
    koreksi,akses_koreksi=await koreksi_tiket(db,user,t.get('kode') if t else snap.get('kode_tiket') if snap else None)
    try:waktu_verifikasi=datetime.fromisoformat(verifier.get('waktu',''))
    except (ValueError,TypeError):waktu_verifikasi=None
    barang=[dict(item=i,aktual=actual.get(i.id),keluar=out.get(i.id),stok_href=stok_href(i)) for i in items]
    return dict(rec=rec,barang=barang,total_pengajuan=sum((i.bobot_kg for i in items),D(0)),
        total_aktual=sum((a.bobot_kg for a in actual.values()),D(0)) if len(actual)==len(items) else None,
        ledger=ledger,snap=snap,verifikasi=verifier,waktu_verifikasi=waktu_verifikasi,checks=checks,users=users,
        koreksi_tiket=koreksi,akses_koreksi=akses_koreksi,
        audit=[dict(aksi=a.aksi or a.action,oleh=a.changed_by,waktu=a.waktu_perubahan,alasan=a.alasan_perubahan,
            sebelum=baca_json(a.old_value),sesudah=baca_json(a.new_value)) for a in audits],
        tiket=t,gagal_tiket=gagal,status=keadaan(rec,latest,ledger,t,gagal=gagal),
        tiket_berubah=bool(snap and t and snap.get('versi_tiket')!=versi_tiket(t)))
