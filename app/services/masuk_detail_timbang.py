"""Kontrak baca penerimaan untuk Pos Timbang, tanpa saldo atau nilai uang.

Pembaca Barang Masuk tetap menentukan sumber dan total penerimaan. Proyeksi
ini hanya membatasi kolom yang boleh keluar serta menjaga cakupan gudang.
Tidak memanggil layanan penerimaan, sinkronisasi bobot, QC, atau stok.
"""
from types import SimpleNamespace
from sqlalchemy import select, text
from hmu_identitas import peran as P
from app.models import Warehouse, Jasa
from app.services import barang_masuk as masuk


async def baca(db, tid, user, lihat=None):
    from app.web.api import _is_g1_operator, _is_g2_operator
    asli = user.role
    efektif = SimpleNamespace(role=P.peran_efektif(asli, lihat),
                             default_warehouse_id=user.default_warehouse_id)
    _, gudang = P.urai(lihat)
    if P.operator_saja(efektif.role) and gudang and P.boleh_ganti_gudang(asli):
        efektif.default_warehouse_id = await db.scalar(select(Warehouse.id).where(
            Warehouse.kode_fungsi == gudang, Warehouse.aktif.is_(True)))
    g1, g2 = await _is_g1_operator(efektif), await _is_g2_operator(efektif)
    tiket = await masuk.tiket_riwayat(db, tid)
    if not tiket:
        raise ValueError('Tiket masuk tidak ditemukan.')
    jenis = masuk.jenis_tiket(tiket['jenis_kode'])
    boleh = g1 if jenis.startswith('gabah') else g2 if jenis != 'lain' else P.admin_keatas(efektif.role)
    if not boleh:
        raise PermissionError('Rincian penerimaan berada di luar cakupan gudang akun.')
    rows = await masuk.riwayat(db, g1=g1, g2=g2, tid=tid)
    sumber = rows[0]['catatan'] if rows else []
    catatan = []
    for c in sumber:
        lokasi, _, petugas = await masuk.rincian_lokasi(db, [c])
        qc = await masuk.hasil_qc(db, [c])
        pesanan = await db.get(Jasa, c['jasa_id']) if c['jasa_id'] else None
        catatan.append(dict(
            id=c['id'], model=c['model'], kode=c['kode'], pemilik=c['pemilik'],
            jasa_id=c['jasa_id'], jasa_kode=pesanan.kode if pesanan else None,
            berat_kg=str(c['berat']) if c['berat'] is not None else None,
            sumber_berat=c['sumber_berat'], status=c['status'],
            sementara=c['sumber_berat'] in ('menunggu', 'perkiraan'),
            waktu=c['waktu'].isoformat() if c['waktu'] else None,
            petugas=petugas.get(c['petugas_id']), lokasi=lokasi,
            qc=[dict(status=q['status'],putaran=q['putaran']) for q in qc],
        ))
    berat, keterangan = masuk.bobot_diterima(sumber)
    # Pesanan kepala tiket bukan pengganti pemilik masing-masing catatan.
    jasa_id = await db.scalar(text('SELECT jasa_id FROM timbangan_transaksi WHERE id=:tid'), {'tid':tid})
    pesanan = await db.get(Jasa, jasa_id) if jasa_id else None
    return dict(tiket_id=tid, kode_tiket=tiket['kode'], jenis_kode=tiket['jenis_kode'],
                jasa=bool(tiket.get('jasa')), catatan=catatan,
                pesanan=dict(id=pesanan.id,kode=pesanan.kode) if pesanan else None,
                berat_diterima_kg=str(berat) if berat is not None else None,
                keterangan_berat=keterangan if sumber else 'Belum ada catatan penerimaan',
                status='tercatat' if sumber else 'belum',
                cakupan='Gudang 1 dan 2' if g1 and g2 else 'Gudang 1' if g1 else 'Gudang 2')
