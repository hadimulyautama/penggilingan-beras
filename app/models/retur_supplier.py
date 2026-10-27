"""Pengajuan, pemeriksaan, dan satu pencatatan keluar pembelian supplier.

Penerimaan dan tiket asal tetap utuh. Empat FK sumber mempertahankan item
asli; JSON hanya menyimpan keterangan saat diajukan, bukan pengganti relasi.
Rincian awal tidak ditimpa aktual. Stok hanya membaca proyeksi peristiwa
keluar yang sudah tercatat. Tidak ada jurnal pembelian atau Kledo otomatis.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class ReturSupplier(Base, TimestampMixin):
    __tablename__ = 'retur_supplier'
    __table_args__ = (
        CheckConstraint("status IN ('diajukan','dibatalkan','selesai_gudang')", name='ck_retur_supplier_status'),
        Index('ix_retur_supplier_penerimaan', 'penerimaan_tiket_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(32), unique=True)
    penerimaan_tiket_id: Mapped[int] = mapped_column(nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey('suppliers.id'), nullable=False)
    # Tabel tiket dikelola TeraFlow dan tidak dimasukkan metadata PadiFlow.
    # UNIQUE tetap menjaga satu tiket satu pengajuan, termasuk riwayat batal.
    timbangan_transaksi_id: Mapped[int | None] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(String(20), default='diajukan', nullable=False)
    alasan: Mapped[str] = mapped_column(Text, nullable=False)
    catatan: Mapped[str | None] = mapped_column(Text)
    sumber: Mapped[dict] = mapped_column(JSON, nullable=False)
    kunci: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    sidik: Mapped[str] = mapped_column(String(64), nullable=False)
    input_by: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tiket_dihubungkan_oleh: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    tiket_dihubungkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dibatalkan_oleh: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    dibatalkan_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alasan_batal: Mapped[str | None] = mapped_column(Text)
    versi_aktual: Mapped[int] = mapped_column(default=0,server_default='0')
    wajib_manual: Mapped[bool] = mapped_column(Boolean,default=False,server_default='false')
    dasar_selisih_besar: Mapped[dict | None] = mapped_column(JSON)
    verifikasi: Mapped[dict | None] = mapped_column(JSON)


class ReturSupplierItem(Base):
    __tablename__ = 'retur_supplier_items'
    __table_args__ = (
        CheckConstraint("jumlah > 0 AND bobot_kg > 0", name='ck_retur_supplier_item_positif'),
        CheckConstraint("satuan IN ('karung','kg') AND (satuan <> 'karung' OR jumlah = round(jumlah))", name='ck_retur_supplier_item_satuan'),
        CheckConstraint('(CASE WHEN purchase_batch_id IS NULL THEN 0 ELSE 1 END + '
                        'CASE WHEN pk_purchase_batch_id IS NULL THEN 0 ELSE 1 END + '
                        'CASE WHEN finished_goods_stock_id IS NULL THEN 0 ELSE 1 END + '
                        'CASE WHEN byproduct_stock_id IS NULL THEN 0 ELSE 1 END) = 1', name='ck_retur_supplier_satu_sumber'),
        UniqueConstraint('retur_supplier_id', 'kunci_sumber', name='uq_retur_supplier_item_sumber'),
        Index('ix_retur_supplier_item_sumber', 'kunci_sumber'),
        Index('ix_retur_supplier_item_gabah','purchase_batch_id'),
        Index('ix_retur_supplier_item_pk','pk_purchase_batch_id'),
        Index('ix_retur_supplier_item_beras','finished_goods_stock_id'),
        Index('ix_retur_supplier_item_broken','byproduct_stock_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    retur_supplier_id: Mapped[int] = mapped_column(ForeignKey('retur_supplier.id'), nullable=False)
    kunci_sumber: Mapped[str] = mapped_column(String(64), nullable=False)
    purchase_batch_id: Mapped[int | None] = mapped_column(ForeignKey('purchase_batches.id'))
    pk_purchase_batch_id: Mapped[int | None] = mapped_column(ForeignKey('pk_purchase_batches.id'))
    finished_goods_stock_id: Mapped[int | None] = mapped_column(ForeignKey('finished_goods_stock.id'))
    byproduct_stock_id: Mapped[int | None] = mapped_column(ForeignKey('byproduct_stock.id'))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey('warehouses.id'), nullable=False)
    jumlah: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    satuan: Mapped[str] = mapped_column(String(12), nullable=False)
    bobot_kg: Mapped[Decimal] = mapped_column(Numeric(22, 8), nullable=False)
    # Dimensi yang juga dipakai reservasi barang keluar. Tidak ada harga/HPP.
    tipe_pool: Mapped[str] = mapped_column(String(24), nullable=False)
    product_sku_id: Mapped[int | None] = mapped_column(ForeignKey('product_skus.id'))
    rice_quality_standard_id: Mapped[int | None] = mapped_column(ForeignKey('rice_quality_standards.id'))
    jenis_produk: Mapped[str | None] = mapped_column(String(24))
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)


class ReturSupplierAktual(Base):
    __tablename__='retur_supplier_aktual'
    __table_args__=(CheckConstraint('jumlah >= 0 AND bobot_kg >= 0',name='ck_rsp_aktual_positif'),)
    item_id: Mapped[int] = mapped_column(ForeignKey('retur_supplier_items.id'),primary_key=True)
    jumlah: Mapped[Decimal] = mapped_column(Numeric(14,2))
    bobot_kg: Mapped[Decimal] = mapped_column(Numeric(22,8))
    kemasan_tara_id: Mapped[int | None] = mapped_column(ForeignKey('kemasan_tara.id'))
    tara_per_karung_kg: Mapped[Decimal | None] = mapped_column(Numeric(10,4))


class ReturSupplierPemeriksaan(Base):
    __tablename__='retur_supplier_pemeriksaan'
    id: Mapped[int] = mapped_column(primary_key=True)
    retur_supplier_id: Mapped[int] = mapped_column(ForeignKey('retur_supplier.id'),index=True)
    versi_aktual: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(30))
    snapshot: Mapped[dict] = mapped_column(JSON)
    input_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReturSupplierKeluar(Base):
    """Proyeksi SATU peristiwa keluar; rincian historis ada pada snapshot.

    Pembaca stok lama memasukkan suku keluar ini. Tidak ada OutgoingItem
    penjualan tambahan atau perubahan jumlah penerimaan asal.
    """
    __tablename__='retur_supplier_keluar'
    peristiwa_id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer,'sqlite'),ForeignKey('peristiwa.id'),primary_key=True)
    retur_supplier_id: Mapped[int] = mapped_column(ForeignKey('retur_supplier.id'),unique=True)
    kode: Mapped[str] = mapped_column(String(32),unique=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    input_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True))

def pasang_saldo_sumber():
    # Bobot operasi gabah menggunakan saldo sesudah retur. Berat penerimaan
    # tetap kolom lama. Ekspresi juga dapat dipakai penjumlah SQL pengering.
    from sqlalchemy import select,func
    from sqlalchemy.orm import column_property
    I,A,K=ReturSupplierItem,ReturSupplierAktual,ReturSupplierKeluar
    from app.services.retur_supplier_stok import efektif
    from app.penggilingan.gudang1.models import PurchaseBatch
    from app.penggilingan.inventory.models import FinishedGoodsStock
    for model,fk in ((PurchaseBatch,I.purchase_batch_id),(FinishedGoodsStock,I.finished_goods_stock_id)):
        model.retur_supplier_keluar_kg=column_property(select(func.coalesce(func.sum(efektif('bobot_kg')),0))
            .select_from(A).join(I,I.id==A.item_id).join(K,K.retur_supplier_id==I.retur_supplier_id)
            .where(fk==model.id).correlate_except(A,I,K).scalar_subquery())
    FinishedGoodsStock.retur_supplier_keluar_karung=column_property(select(func.coalesce(func.sum(efektif('jumlah')),0))
        .select_from(A).join(I,I.id==A.item_id).join(K,K.retur_supplier_id==I.retur_supplier_id)
        .where(I.finished_goods_stock_id==FinishedGoodsStock.id,I.satuan=='karung').correlate_except(A,I,K).scalar_subquery())
