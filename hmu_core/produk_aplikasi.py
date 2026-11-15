"""Metadata produk dan izin; tidak memiliki relasi ke transaksi bisnis."""
from sqlalchemy import Boolean,CheckConstraint,ForeignKey,ForeignKeyConstraint,String,false
from sqlalchemy.orm import Mapped,mapped_column
from hmu_core.base import Base,TimestampMixin

class ProdukAplikasiPerusahaan(Base,TimestampMixin):
    __tablename__='hmu_company_products'
    __table_args__=(CheckConstraint("produk IN ('padiflow','teraflow')",name='ck_hmu_company_products_code'),)
    company_id:Mapped[int]=mapped_column(ForeignKey('hmu_companies.id',ondelete='RESTRICT'),primary_key=True)
    produk:Mapped[str]=mapped_column(String(30),primary_key=True)
    aktif:Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,server_default=false())
    # Hanya diisi saat migrasi ruang warisan terverifikasi; bukan pilihan aktivasi perusahaan baru.
    warisan:Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,server_default=false())

class AksesProdukAnggota(Base,TimestampMixin):
    __tablename__='hmu_member_products'
    __table_args__=(
        ForeignKeyConstraint(['company_id','produk'],['hmu_company_products.company_id','hmu_company_products.produk'],ondelete='RESTRICT',name='fk_hmu_member_product_company'),
        ForeignKeyConstraint(['company_id','user_id'],['hmu_company_memberships.company_id','hmu_company_memberships.user_id'],ondelete='RESTRICT',name='fk_hmu_member_product_membership'),
        CheckConstraint("peran IN ('admin','operator')",name='ck_hmu_member_products_role'),)
    company_id:Mapped[int]=mapped_column(primary_key=True)
    user_id:Mapped[int]=mapped_column(primary_key=True)
    produk:Mapped[str]=mapped_column(String(30),primary_key=True)
    aktif:Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,server_default=false())
    peran:Mapped[str]=mapped_column(String(20),nullable=False)

class IntegrasiProdukPerusahaan(Base,TimestampMixin):
    __tablename__='hmu_company_integrations'
    __table_args__=(CheckConstraint("kode='padiflow_teraflow'",name='ck_hmu_company_integrations_code'),)
    company_id:Mapped[int]=mapped_column(ForeignKey('hmu_companies.id',ondelete='RESTRICT'),primary_key=True)
    kode:Mapped[str]=mapped_column(String(50),primary_key=True)
    aktif:Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,server_default=false())
