"""Kabar per pengguna, memakai penerima dan histori notifikasi lama.

Status notifications tetap milik penyelesaian/eskalasi proses. Status baca
pribadi disimpan terpisah; tanpa baris pribadi, status historis menjadi bawaan.
Semua pembaca dan mutasi memakai cakupan SQL yang sama.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, literal
from sqlalchemy.ext.asyncio import AsyncSession
from hmu_identitas import peran as P

from app.database import now_local
from app.models import Notification, User

#: Konstanta kompatibilitas pemanggil lama; daftar baru tidak dibatasi umur.
HARI = 7

#: Peran yang membaca kabar mana. Kosakatanya `notifications.target_role` yang
#: sudah dipakai lima penulisnya — bukan kosakata baru, supaya baris lama ikut
#: terbaca tanpa disentuh.
ADMIN, OPERATOR = "admin", "operator"

#: Jenis kabar yang HANYA berkepentingan bagi satu gudang. Jenis lama yang tidak terdaftar
#: tetap mengikuti penerima peran dan tabel asalnya.
TIPE_GUDANG = {
    # `permintaan_pk` SENGAJA TIDAK di sini, dan itu perubahan 27 September
    # 2026: rantainya melibatkan KEDUA gudang — Gudang 2 yang meminta, Gudang 1
    # yang memuat dan mengirim sesudah Admin menyetujui. Sehari sebelumnya ia
    # tercatat milik "g2" saja, dan dengan tangan yang sekarang itu akan
    # menyembunyikan kabar "ada yang harus Anda kirim" dari orang yang harus
    # mengirimnya.
    # Lot yang telat diperbarui berdiri di dryer Gudang 1.
    "pengeringan_telat": "g1",
}


@dataclass
class Kabar:
    """Satu baris kabar, siap digambar."""

    id: int
    tipe: str
    pesan: str
    prioritas: str
    #: Status baca pribadi, dengan bawaan status historis.
    baru: bool
    waktu: object
    #: Identitas catatan asal untuk navigasi, bukan hasil pencocokan judul.
    table_name: str | None = None
    record_id: int | None = None
    judul: str = ""
    referensi: str = ""
    lokasi: str = ""


async def keranjang(user: User) -> tuple[str, str | None]:
    """Kabar mana yang milik orang ini: (peran, gudang).

    `gudang` None berarti tak disaring — Admin ke atas memegang kedua gudang,
    dan kabar yang disembunyikan dari orang yang bertanggung jawab atas
    keduanya adalah kabar yang hilang.
    """
    from app.peran import can_see_financials
    from app.web.api import _is_g1_operator, _is_g2_operator

    if can_see_financials(user):
        return ADMIN, None
    if await _is_g2_operator(user):
        return OPERATOR, "g2"
    if await _is_g1_operator(user):
        return OPERATOR, "g1"
    # Belum ada gudang kerja yang sah: jangan memakai None (cakupan semua
    # gudang). Pilihan gudang resmi tetap dibaca oleh akun_opsional.
    return OPERATOR, P.TANPA


def _dibaca():
    from app.models import NotificationRead
    return func.coalesce(NotificationRead.dibaca, Notification.status != "baru")


async def _cakupan(user):
    from sqlalchemy import or_
    # Super Admin membaca gabungan seluruh penerima, termasuk kabar operator.
    # Cakupan yang sama dipakai daftar, badge, buka, dan status baca pribadi.
    if P.super_saja(user.role):
        return []
    peran, gudang = await keranjang(user)
    if gudang == P.TANPA:
        # Satu pagar untuk daftar, badge, histori, buka, dan status pribadi.
        return [literal(False)]
    syarat = [or_(Notification.target_role == peran, Notification.target_role.is_(None))]
    terlarang = [t for t, g in TIPE_GUDANG.items() if gudang and g != gudang]
    if terlarang:
        syarat.append(Notification.tipe.not_in(terlarang))
    # Cakupan tabel yang diketahui juga berlaku untuk jenis baru dalam modul
    # yang sama. NULL/jenis lintas gudang tetap mengikuti kontrak lama.
    tabel_g1 = ['purchase_batches', 'drying_lots', 'milling_process',
                'purchase_batch_qc', 'purchase_batch_qc_samples', 'milling_qc_logs']
    tabel_g2 = ['pk_purchase_batches', 'pk_rejections', 'polishing_process',
                'outgoing_records', 'customer_returns', 'pk_purchase_qc_logs']
    if gudang:
        syarat.append(or_(Notification.table_name.is_(None),
                          Notification.table_name.not_in(tabel_g2 if gudang == 'g1' else tabel_g1)))
    return syarat


async def _pilih(user):
    from app.models import NotificationRead
    return (select(Notification, _dibaca().label("dibaca"))
            .outerjoin(NotificationRead,
                       (NotificationRead.notification_id == Notification.id)
                       & (NotificationRead.user_id == user.id))
            .where(*await _cakupan(user)))


async def daftar(db: AsyncSession, user: User, *, hari=None, jenis="", belum=False,
                 batas=None, offset=0, sampai=None, sebelum=None) -> list[Kabar]:
    # Histori tidak dibatasi umur. Urutan tanggal dan id membuat halaman stabil
    # untuk timestamp sama; daftar web memakai jendela id saat pertama dibuka.
    q = await _pilih(user)
    if sebelum is not None:
        from sqlalchemy import tuple_
        titik = await ambil(db, user, sebelum)
        q = q.where(tuple_(Notification.created_at, Notification.id) <
                    tuple_(titik.created_at, titik.id))
    if sampai is not None:
        q = q.where(Notification.id <= sampai)
    if jenis:
        q = q.where(Notification.tipe == jenis)
    if belum:
        q = q.where(~_dibaca())
    if hari is not None:
        q = q.where(Notification.created_at >= now_local() - timedelta(days=hari))
    q = q.order_by(Notification.created_at.desc(), Notification.id.desc()).offset(offset)
    if batas is not None:
        q = q.limit(batas)
    return [Kabar(id=n.id, tipe=n.tipe, pesan=n.pesan, prioritas=n.prioritas,
                  baru=not dibaca, waktu=n.created_at,
                  table_name=n.table_name, record_id=n.record_id)
            for n, dibaca in (await db.execute(q)).all()]


async def jumlah_baru(db: AsyncSession, user: User, *, hari=None) -> int:
    q = (await _pilih(user)).where(~_dibaca())
    return int(await db.scalar(select(func.count()).select_from(q.subquery())))


async def ada_merah(db: AsyncSession, user: User, *, hari=None) -> bool:
    q = (await _pilih(user)).where(~_dibaca(), Notification.prioritas == "merah").limit(1)
    return (await db.execute(q)).first() is not None


async def batas_histori(db, user):
    return await db.scalar(select(func.max(Notification.id)).where(*await _cakupan(user))) or 0


async def jenis_tersedia(db, user):
    return list((await db.scalars(select(Notification.tipe)
                .where(*await _cakupan(user)).distinct().order_by(Notification.tipe))).all())


async def ambil(db, user, id_):
    q = (await _pilih(user)).where(Notification.id == id_)
    row = (await db.execute(q)).first()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Kabar tidak ditemukan atau tidak tersedia untuk Anda.")
    return row[0]


async def tandai(db, user, *, dibaca, id_=None):
    from sqlalchemy.dialects.postgresql import insert
    from app.models import NotificationRead
    if id_ is not None:
        await ambil(db, user, id_)
    sumber = select(Notification.id).where(*await _cakupan(user))
    if id_ is not None:
        sumber = sumber.where(Notification.id == id_)
    # INSERT SELECT: semua histori dalam cakupan, tanpa batas halaman dan tanpa
    # memuat ribuan id ke aplikasi. Upsert aman untuk dua perangkat bersamaan.
    sumber = sumber.with_only_columns(
        literal(user.id), Notification.id,
        literal(dibaca))
    stmt = insert(NotificationRead).from_select(
        ["user_id", "notification_id", "dibaca"], sumber)
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["user_id", "notification_id"], set_={"dibaca": dibaca}))
    await db.commit()


# Nama tabel adalah identitas terstruktur dari penulis notifikasi. Tidak ada
# pencocokan pesan, sehingga perubahan kalimat tidak memindahkan tujuan.
async def tujuan(db, user, n):
    from urllib.parse import quote
    from app.models import (PurchaseBatch, PkPurchaseBatch, PkRejection, DryingLot,
                            MillingProcess, PolishingProcess, InternalTransfer,
                            OutgoingRecord, CustomerReturn, PermintaanPk, PurchaseBatchQc,
                            PurchaseBatchQcSample, MillingQcLog, PkPurchaseQcLog)
    from app.web.api import _is_g1_operator, _is_g2_operator
    model = {
        'purchase_batch_qc': PurchaseBatchQc, 'purchase_batch_qc_samples': PurchaseBatchQcSample,
        'milling_qc_logs': MillingQcLog, 'pk_purchase_qc_logs': PkPurchaseQcLog,
        'purchase_batches': PurchaseBatch, 'pk_purchase_batches': PkPurchaseBatch,
        'pk_rejections': PkRejection, 'drying_lots': DryingLot,
        'milling_process': MillingProcess, 'polishing_process': PolishingProcess,
        'internal_transfers': InternalTransfer, 'outgoing_records': OutgoingRecord,
        'customer_returns': CustomerReturn, 'permintaan_pk': PermintaanPk,
    }.get(n.table_name)
    if model is None or n.record_id is None:
        return None
    g1 = {'purchase_batches', 'drying_lots', 'milling_process',
          'purchase_batch_qc', 'purchase_batch_qc_samples', 'milling_qc_logs'}
    g2 = {'pk_purchase_batches', 'pk_rejections', 'polishing_process',
          'outgoing_records', 'customer_returns', 'pk_purchase_qc_logs'}
    if n.table_name in g1 and not await _is_g1_operator(user):
        return None
    if n.table_name in g2 and not await _is_g2_operator(user):
        return None
    obj = await db.get(model, n.record_id)
    if obj is None or getattr(obj, 'dibatalkan_pada', None):
        return None
    if n.table_name in {'purchase_batch_qc', 'purchase_batch_qc_samples', 'milling_qc_logs', 'pk_purchase_qc_logs'}:
        if n.table_name == 'purchase_batch_qc_samples':
            obj = await db.get(PurchaseBatchQc, obj.purchase_batch_qc_id)
            if obj is None:
                return None
        if n.table_name in {'purchase_batch_qc', 'purchase_batch_qc_samples'}:
            batch = await db.get(PurchaseBatch, obj.purchase_batch_id)
            jenis = ('gabah-kering' if batch and batch.kondisi_gabah == 'kering' else 'gabah-basah')
        elif n.table_name == 'milling_qc_logs':
            batch = await db.get(MillingProcess, obj.milling_process_id)
            jenis = 'pk-hasil-giling'
        else:
            batch = await db.get(PkPurchaseBatch, obj.pk_purchase_batch_id)
            jenis = 'pk-luar'
        if batch is None or getattr(batch, 'dibatalkan_pada', None):
            return None
        kode = getattr(batch, 'kode_batch', None) or batch.kode_proses
        return f'/riwayat-qc/{jenis}/{quote(kode, safe="")}'
    if n.table_name == 'pk_rejections':
        obj = await db.get(PkPurchaseBatch, obj.pk_purchase_batch_id)
        if obj is None:
            return None
    if n.table_name in {'purchase_batches', 'pk_purchase_batches', 'pk_rejections'}:
        tid = obj.timbangan_transaksi_id
        if tid:
            return f'/barang-masuk/{tid}'
        jenis = ('pk-luar' if n.table_name != 'purchase_batches' else
                 'gabah-kering' if obj.kondisi_gabah == 'kering' else 'gabah-basah')
        return f'/riwayat-qc/{jenis}/{quote(obj.kode_batch, safe="")}'
    if n.table_name == 'drying_lots':
        return f'/proses-aktif/pengeringan/{quote(obj.kode_lot, safe="")}' if obj.waktu_selesai_pendinginan is None else f'/riwayat-pengeringan/{obj.id}'
    if n.table_name == 'milling_process':
        return f'/proses-aktif/giling/{quote(obj.kode_proses, safe="")}' if obj.status == 'proses' else f'/riwayat-giling/{obj.id}'
    if n.table_name == 'polishing_process':
        return f'/proses-aktif/sosoh/{quote(obj.kode_proses, safe="")}' if obj.status == 'proses' else f'/riwayat-sosoh/{obj.id}'
    if n.table_name == 'internal_transfers':
        if not await _is_g1_operator(user):
            # Riwayat transfer lama berpagar G1. Operator G2 memakai stoknya.
            from app.models import PkGudang2Intake
            intake = await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id == obj.id))
            return f'/stok/pk/detail?gudang=g2&id={intake.id}&jasa={int(bool(intake.jasa_id))}' if intake else None
        return f'/riwayat-transfer/{obj.id}'
    if n.table_name == 'outgoing_records':
        return f'/barang-keluar/{obj.id}'
    if n.table_name == 'customer_returns':
        from app.peran import can_see_financials
        if not can_see_financials(user):
            return None
        return f'/retur/{obj.id}'
    if n.table_name == 'permintaan_pk':
        return f'/pekerjaan/permintaan/{obj.id}'


async def lengkapi(db, baris):
    """Identitas tampilan dibaca dari objek, tidak ditebak dari kalimat kabar."""
    from app.database import Base
    judul = {'pengeringan_telat': 'Pengeringan perlu diperbarui',
             'permintaan_pk': 'Permintaan transfer PK', 'barang_keluar': 'Barang keluar',
             'verifikasi_pk_luar': 'Penerimaan PK luar', 'pk_luar_ditolak': 'PK luar ditolak',
             'verifikasi_penyosohan': 'Hasil penyosohan',
             'verifikasi_harga_gabah': 'Verifikasi harga gabah'}
    sah = {'purchase_batches', 'pk_purchase_batches', 'pk_rejections', 'drying_lots',
           'milling_process', 'polishing_process', 'internal_transfers',
           'outgoing_records', 'customer_returns', 'permintaan_pk'}
    model = {m.local_table.name: m.class_ for m in Base.registry.mappers if m.local_table.name in sah}
    for k in baris:
        k.judul = judul.get(k.tipe, k.tipe.replace('_', ' ').capitalize())
        if k.table_name not in model or k.record_id is None:
            continue
        obj = await db.get(model[k.table_name], k.record_id)
        if obj is None or getattr(obj, 'dibatalkan_pada', None):
            continue
        k.referensi = next((str(getattr(obj, f)) for f in
                            ('kode_batch', 'kode_lot', 'kode_proses', 'kode_transfer', 'kode')
                            if getattr(obj, f, None)), f'Catatan #{k.record_id}')
        if k.table_name == 'permintaan_pk':
            from app.models import MillingProcess
            lot = await db.get(MillingProcess, obj.milling_process_id)
            if lot:
                k.referensi = f'{lot.kode_proses} · Permintaan #{obj.id}'
        if k.table_name in ('purchase_batches', 'drying_lots', 'milling_process'):
            k.lokasi = 'Gudang 1'
        elif k.table_name in ('pk_purchase_batches', 'pk_rejections', 'polishing_process'):
            k.lokasi = 'Gudang 2'
        elif k.table_name in ('permintaan_pk', 'internal_transfers'):
            k.lokasi = 'Gudang 1 → Gudang 2'
