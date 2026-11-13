"""Master organisasi bersama; belum mengaktifkan cakupan transaksi aplikasi.

Penempatan gudang memakai tabel penghubung agar gudang dan transaksi lama
bisa tetap utuh, tanpa menebak perusahaan/lokasi dari nama atau kode g1/g2.
Model dimiliki core; pelari migrasi tetap PadiFlow sampai pemindahan runner
core dilakukan sebagai tahap tersendiri.
"""
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column
from hmu_core.base import Base, TimestampMixin


class Perusahaan(Base, TimestampMixin):
    __tablename__ = 'hmu_companies'
    __table_args__ = (
        CheckConstraint("length(trim(kode)) > 0", name='ck_hmu_companies_kode'),
        CheckConstraint("length(trim(nama)) > 0", name='ck_hmu_companies_nama'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kode: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nama: Mapped[str] = mapped_column(String(200), nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


class LokasiPabrik(Base, TimestampMixin):
    __tablename__ = 'hmu_factory_sites'
    __table_args__ = (
        UniqueConstraint('company_id', 'kode', name='uq_hmu_sites_company_kode'),
        UniqueConstraint('id', 'company_id', name='uq_hmu_sites_id_company'),
        CheckConstraint("length(trim(kode)) > 0", name='ck_hmu_sites_kode'),
        CheckConstraint("length(trim(nama)) > 0", name='ck_hmu_sites_nama'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('hmu_companies.id', ondelete='RESTRICT'), nullable=False)
    kode: Mapped[str] = mapped_column(String(50), nullable=False)
    nama: Mapped[str] = mapped_column(String(200), nullable=False)
    alamat: Mapped[str | None] = mapped_column(Text)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


class KeanggotaanPerusahaan(Base, TimestampMixin):
    __tablename__ = 'hmu_company_memberships'
    __table_args__ = (
        UniqueConstraint('company_id', 'user_id', name='uq_hmu_memberships_company_user'),
        UniqueConstraint('id','company_id',name='uq_hmu_memberships_id_company'),
        CheckConstraint("length(trim(peran)) > 0", name='ck_hmu_memberships_peran'),
        Index('ix_hmu_memberships_user', 'user_id'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('hmu_companies.id', ondelete='RESTRICT'), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    # Peran dalam perusahaan; tidak disalin dari users.role saat membaca.
    peran: Mapped[str] = mapped_column(String(20), nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


class PenempatanGudang(Base, TimestampMixin):
    __tablename__ = 'hmu_warehouse_sites'
    __table_args__ = (
        ForeignKeyConstraint(['lokasi_pabrik_id', 'company_id'],
            ['hmu_factory_sites.id', 'hmu_factory_sites.company_id'],
            name='fk_hmu_warehouse_site_company', ondelete='RESTRICT'),
        Index('ix_hmu_warehouse_sites_lokasi', 'lokasi_pabrik_id', 'company_id'),
        UniqueConstraint('warehouse_id','lokasi_pabrik_id','company_id',name='uq_hmu_warehouse_site_company'),
    )
    # Satu gudang hanya berada pada satu lokasi; line mengikuti warehouse_id.
    warehouse_id: Mapped[int] = mapped_column(ForeignKey('warehouses.id', ondelete='RESTRICT'), primary_key=True, autoincrement=False)
    company_id: Mapped[int] = mapped_column(ForeignKey('hmu_companies.id', ondelete='RESTRICT'), nullable=False)
    lokasi_pabrik_id: Mapped[int] = mapped_column(nullable=False)


class AksesLokasiAnggota(Base, TimestampMixin):
    """Hak eksplisit; keanggotaan saja tidak memberikan seluruh fasilitas."""
    __tablename__ = 'hmu_membership_sites'
    __table_args__ = (
        ForeignKeyConstraint(['keanggotaan_id','company_id'],['hmu_company_memberships.id','hmu_company_memberships.company_id'],ondelete='RESTRICT',name='fk_hmu_member_site_membership'),
        ForeignKeyConstraint(['lokasi_pabrik_id','company_id'],['hmu_factory_sites.id','hmu_factory_sites.company_id'],ondelete='RESTRICT',name='fk_hmu_member_site_company'),
        UniqueConstraint('keanggotaan_id','lokasi_pabrik_id','company_id',name='uq_hmu_member_site_company'),
    )
    keanggotaan_id: Mapped[int] = mapped_column(primary_key=True,autoincrement=False)
    lokasi_pabrik_id: Mapped[int] = mapped_column(primary_key=True,autoincrement=False)
    company_id: Mapped[int] = mapped_column(nullable=False)
    semua_gudang: Mapped[bool] = mapped_column(Boolean,nullable=False,default=False,server_default=false())


class AksesGudangAnggota(Base, TimestampMixin):
    __tablename__ = 'hmu_membership_warehouses'
    __table_args__ = (
        ForeignKeyConstraint(['keanggotaan_id','lokasi_pabrik_id','company_id'],['hmu_membership_sites.keanggotaan_id','hmu_membership_sites.lokasi_pabrik_id','hmu_membership_sites.company_id'],ondelete='RESTRICT',name='fk_hmu_member_warehouse_site'),
        ForeignKeyConstraint(['warehouse_id','lokasi_pabrik_id','company_id'],['hmu_warehouse_sites.warehouse_id','hmu_warehouse_sites.lokasi_pabrik_id','hmu_warehouse_sites.company_id'],ondelete='RESTRICT',name='fk_hmu_member_warehouse_binding'),
    )
    keanggotaan_id: Mapped[int] = mapped_column(primary_key=True,autoincrement=False)
    warehouse_id: Mapped[int] = mapped_column(primary_key=True,autoincrement=False)
    lokasi_pabrik_id: Mapped[int] = mapped_column(nullable=False)
    company_id: Mapped[int] = mapped_column(nullable=False)
