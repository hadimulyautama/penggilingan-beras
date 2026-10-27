"""Proyeksi baca pengajuan; membuka detail tidak menjalankan transaksi retur."""
from sqlalchemy import select, text
from app.models import User
from app.models.retur_supplier import ReturSupplier, ReturSupplierItem
from app.services import retur_supplier as layanan


async def detail(db, identitas, user):
    rec,items=await layanan.ambil(db,identitas,user)
    pengaju=await db.get(User,rec.input_by)
    t=await layanan.tiket(db,rec.timbangan_transaksi_id) if rec.timbangan_transaksi_id else None
    bobot=sum((x.bobot_kg for x in items),layanan.D(0))
    hubungan_sah=bool(t and t['arah']=='RETUR_KELUAR' and t['jenis_kode']=='RETUR_SUPPLIER' and t['supplier_id']==rec.supplier_id)
    final=(t.get('berat_barang_kg') if hubungan_sah and t['status_tiket']=='SELESAI' and t['status_transaksi']=='AKTIF' else None)
    status_tiket=('belum_ada_tiket' if not rec.timbangan_transaksi_id else
        'tidak_pasti' if not t else 'hubungan_berubah' if not hubungan_sah else 'dibatalkan' if t['status_transaksi']!='AKTIF' else
        'menunggu_timbang_kedua' if t['status_tiket']=='TERBUKA' else
        'hasil_tersedia' if final is not None else 'hasil_belum_lengkap')
    audit=(await db.execute(text('''SELECT l.action,l.aksi,l.alasan_perubahan,l.new_value,
            l.waktu_perubahan,u.nama FROM activity_logs l LEFT JOIN users u ON u.id=l.changed_by
            WHERE l.table_name='retur_supplier' AND l.record_id=:id ORDER BY l.id'''),{'id':rec.id})).mappings().all()
    return dict(rec=rec,items=items,pengaju=pengaju.nama if pengaju else 'Tidak tercatat',tiket=t,
                total_kg=bobot,total_karung=sum(int(x.jumlah) for x in items if x.satuan=='karung'),
                total_curah_kg=sum((x.bobot_kg for x in items if x.satuan=='kg'),layanan.D(0)),
                hasil_kg=final,selisih_kg=layanan.D(final)-bobot if final is not None else None,
                status_tiket=status_tiket,audit=audit)


async def kandidat(db, rec):
    rows=(await db.execute(text('''SELECT t.id,t.kode,t.nomor_polisi,t.status_tiket,t.status_transaksi,
          r.id AS pengajuan_id FROM timbangan_transaksi t
          LEFT JOIN retur_supplier r ON r.timbangan_transaksi_id=t.id
          WHERE t.arah='RETUR_KELUAR' AND t.jenis_kode='RETUR_SUPPLIER' AND t.supplier_id=:sid
          ORDER BY t.id DESC'''),{'sid':rec.supplier_id})).mappings().all()
    return [dict(x,alasan=('Tiket dibatalkan' if x['status_transaksi']!='AKTIF' else
                         'Tiket ditutup/tidak sah' if x['status_tiket'] not in ('TERBUKA','SELESAI') else
                         'Sudah dipakai pengajuan lain' if x['pengajuan_id'] and x['pengajuan_id']!=rec.id else None)) for x in rows]


async def kontrak(db, tid, user):
    await layanan.pelaku(db,user)
    t=await layanan.tiket(db,tid)
    if not t or t['arah']!='RETUR_KELUAR' or t['jenis_kode']!='RETUR_SUPPLIER':
        raise ValueError('Tiket bukan kegiatan Retur ke Supplier.')
    rec=await db.scalar(select(ReturSupplier).where(ReturSupplier.timbangan_transaksi_id==tid))
    hasil=dict(tiket_id=tid,kode_tiket=t['kode'],arah=t['arah'],supplier_id=t['supplier_id'],
               status='belum_terhubung',pengajuan=None)
    if not rec:return hasil
    rec,items=await layanan.ambil(db,rec.id,user)
    if rec.supplier_id!=t['supplier_id']:
        raise ValueError('Supplier tiket berubah dari hubungan pengajuan; perlu pemeriksaan data.')
    hasil.update(status=rec.status,pengajuan=dict(id=rec.id,kode=rec.kode,
        penerimaan_tiket_id=rec.penerimaan_tiket_id,supplier_id=rec.supplier_id,
        supplier=rec.sumber['supplier'],penerimaan=rec.sumber['kode_tiket'],nota=rec.sumber.get('nota'),
        alasan=rec.alasan,catatan=rec.catatan,total_kg=str(sum((x.bobot_kg for x in items),layanan.D(0))),
        items=[dict(kunci_sumber=x.kunci_sumber,kode=x.snapshot['kode'],nama=x.snapshot['nama'],
            gudang=x.snapshot['gudang'],pemilik=x.snapshot['pemilik'],satuan=x.satuan,
            jumlah=str(x.jumlah),bobot_kg=str(x.bobot_kg)) for x in items]))
    from app.models.retur_supplier import ReturSupplierKeluar
    selesai=await db.scalar(select(ReturSupplierKeluar).where(ReturSupplierKeluar.retur_supplier_id==rec.id))
    if selesai:
        hasil['penyelesaian']=dict(kode=selesai.kode,waktu=selesai.waktu.isoformat(),
            total_kg=selesai.snapshot['total_kg'],metode_verifikasi=selesai.snapshot['verifikasi']['metode'])
        from app.models.retur_supplier_koreksi import ReturSupplierEfektif
        from app.services.retur_supplier_stok import efektif
        from app.models.retur_supplier import ReturSupplierAktual
        state=await db.get(ReturSupplierEfektif,rec.id)
        if state and state.versi:
            rows=(await db.execute(select(ReturSupplierItem.id,efektif('jumlah'),efektif('bobot_kg'))
                .join(ReturSupplierAktual,ReturSupplierAktual.item_id==ReturSupplierItem.id)
                .where(ReturSupplierItem.retur_supplier_id==rec.id))).all()
            # Tambahan opsional; kontrak pengajuan dan penyelesaian AWAL
            # tetap sama untuk pembaca TeraFlow lama.
            hasil['pencatatan_efektif']=dict(versi=state.versi,total_kg=str(sum((kg for _,_,kg in rows),layanan.D(0))),
                dibatalkan_administratif=state.dibatalkan,keberadaan=state.keberadaan,
                items=[dict(item_id=i,jumlah=str(n),bobot_kg=str(kg)) for i,n,kg in rows])
    return hasil
