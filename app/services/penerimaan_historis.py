"""Arsip produk yang sumber stoknya sudah habis/dipindahkan.

Hanya bukti INSERT penerimaan dengan hubungan tiket eksplisit/kode utuh.
Tidak merekonstruksi pemilik, saldo, kemasan atau izin tindakan dari nama.
"""
import re
from decimal import Decimal
from sqlalchemy import text,bindparam

SQL = '''SELECT t.id AS tid,a.id AS audit_id,a.record_id,a.waktu_perubahan,
 a.changed_by,a.new_value,t.jasa_id
 FROM activity_logs a JOIN timbangan_transaksi t ON
 ((a.aksi='produk_timbang_masuk' AND a.field_name='timbangan_transaksi_id' AND a.old_value=CAST(t.id AS text))
 OR (a.action='INSERT' AND split_part(a.new_value,' · ',1)=t.kode))
 WHERE a.action='INSERT' AND a.table_name IN ('finished_goods_stock','byproduct_stock')
 AND t.arah='MASUK' AND t.jenis_kode IN ('BERAS_MASUK','BROKEN_MASUK')
 AND NOT EXISTS(SELECT 1 FROM finished_goods_stock f WHERE f.source_type='timbangan' AND f.source_id=t.id)
 AND NOT EXISTS(SELECT 1 FROM byproduct_stock f WHERE f.source_type='timbangan' AND f.source_id=t.id)'''


async def baca(db, ids):
    if not ids:return []
    q=text('WITH arsip AS ('+SQL+''') SELECT a.*,t.kode,t.jenis_kode,j.nama AS jenis_nama,
 t.nomor_polisi,t.status_tiket,coalesce(p.nama_pelanggan,s.nama_supplier,t.pihak_nama,'?') AS nama
 FROM arsip a JOIN timbangan_transaksi t ON t.id=a.tid
 LEFT JOIN timbangan_jenis j ON j.kode=t.jenis_kode LEFT JOIN pelanggan p ON p.id=t.pelanggan_id
 LEFT JOIN suppliers s ON s.id=t.supplier_id WHERE tid IN :ids ORDER BY tid DESC,audit_id''').bindparams(bindparam('ids',expanding=True))
    hasil={}
    for r in (await db.execute(q,dict(ids=ids))).mappings():
        t=hasil.setdefault(r.tid,dict(id=r.tid,kode=r.kode,jenis_kode=r.jenis_kode,
            jenis_nama=r.jenis_nama,jenis='beras' if r.jenis_kode=='BERAS_MASUK' else 'broken',
            nama=r.nama,nomor_polisi=r.nomor_polisi,status_tiket=r.status_tiket,
            kepemilikan='periksa',catatan=[],historis=True,keterangan_berat='Arsip penerimaan · sumber stok tidak lagi tersedia'))
        # Hanya format audit penerimaan yang menyimpan kg eksplisit. Tidak
        # memakai bobot tiket saat ini sebagai pengganti snapshot penerimaan.
        m=re.fullmatch(re.escape(r.kode)+r' · ([0-9]+(?:\.[0-9]+)?) kg · .+',r.new_value or '')
        t['catatan'].append(dict(id=r.audit_id,kode='Audit #'+str(r.audit_id),
            model='historis',berat=Decimal(m[1]) if m else None,waktu=r.waktu_perubahan,
            petugas_id=r.changed_by,pemilik='Tidak tersedia pada arsip',jasa_id=None,
            status='historis',sumber_berat='snapshot audit' if m else 'belum tersedia',
            audit_id=r.audit_id))
    from app.services.barang_masuk import bobot_diterima
    for t in hasil.values():t['berat_diterima']=bobot_diterima(t['catatan'])[0]
    return list(hasil.values())
