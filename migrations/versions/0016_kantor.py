"""Domain Kantor AI: SOP/otak, approval, audit, aset, kartu pemeliharaan, penomoran

Revision ID: 0016_kantor
Revises: 0015_cooling_phase
Create Date: 2026-08-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_kantor"
down_revision: Union[str, None] = "0015_cooling_phase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kantor_sop_dokumen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("judul", sa.String(255), nullable=False),
        sa.Column("kategori", sa.String(40), server_default="sop"),
        sa.Column("sumber", sa.String(20), server_default="manual"),
        sa.Column("sumber_ref", sa.String(512)),
        sa.Column("konten_hash", sa.String(64)),
        sa.Column("ranah", sa.String(20), server_default="umum"),
        sa.Column("status", sa.String(20), server_default="aktif"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "kantor_sop_chunk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dokumen_id", sa.Integer(), sa.ForeignKey("kantor_sop_dokumen.id", ondelete="CASCADE"), nullable=False),
        sa.Column("urutan", sa.Integer(), server_default="0"),
        sa.Column("isi", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text()),  # jadi pgvector saat fase semantic
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "kantor_aksi_pending",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("peran", sa.String(20), nullable=False),
        sa.Column("jenis", sa.String(40), nullable=False),
        sa.Column("tier", sa.String(10), server_default="merah"),
        sa.Column("ringkasan", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text()),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("diminta_oleh", sa.String(60)),
        sa.Column("diputus_oleh", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("hasil", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("diputus_at", sa.DateTime(timezone=True)),
        sa.Column("kedaluwarsa_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "kantor_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("peran", sa.String(20)),
        sa.Column("aksi", sa.String(60), nullable=False),
        sa.Column("target", sa.String(512)),
        sa.Column("detail", sa.Text()),
        sa.Column("status", sa.String(20), server_default="sukses"),
        sa.Column("aksi_pending_id", sa.Integer(), sa.ForeignKey("kantor_aksi_pending.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "kantor_aset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kode", sa.String(40), nullable=False, unique=True),
        sa.Column("nama", sa.String(255), nullable=False),
        sa.Column("kategori", sa.String(60)),
        sa.Column("lokasi", sa.String(255)),
        sa.Column("penanggung_jawab", sa.String(120)),
        sa.Column("tanggal_perolehan", sa.Date()),
        sa.Column("nilai_perolehan", sa.Numeric(15, 2)),
        sa.Column("masa_manfaat_tahun", sa.Integer()),
        sa.Column("metode_penyusutan", sa.String(20), server_default="garis_lurus"),
        sa.Column("nilai_residu", sa.Numeric(15, 2)),
        sa.Column("status", sa.String(20), server_default="aktif"),
        sa.Column("catatan", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "kantor_kartu_pemeliharaan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("aset_id", sa.Integer(), sa.ForeignKey("kantor_aset.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tanggal", sa.Date(), nullable=False),
        sa.Column("jenis", sa.String(40), server_default="rutin"),
        sa.Column("deskripsi", sa.Text(), nullable=False),
        sa.Column("biaya", sa.Numeric(15, 2)),
        sa.Column("pelaksana", sa.String(120)),
        sa.Column("jadwal_berikutnya", sa.Date()),
        sa.Column("bukti_ref", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "kantor_nomor_dokumen",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nomor_lengkap", sa.String(80), nullable=False, unique=True),
        sa.Column("jenis", sa.String(10), nullable=False, server_default="surat"),
        sa.Column("kode", sa.String(12), nullable=False),
        sa.Column("divisi", sa.String(8)),
        sa.Column("tahun", sa.Integer(), nullable=False),
        sa.Column("bulan", sa.Integer()),
        sa.Column("urut", sa.Integer(), nullable=False),
        sa.Column("perihal", sa.Text()),
        sa.Column("pihak", sa.String(255)),
        sa.Column("pembuat", sa.String(120)),
        sa.Column("file_ref", sa.String(512)),
        sa.Column("status", sa.String(10), server_default="aktif"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("jenis", "kode", "divisi", "tahun", "urut", name="uq_nomor_urut"),
    )


def downgrade() -> None:
    op.drop_table("kantor_nomor_dokumen")
    op.drop_table("kantor_kartu_pemeliharaan")
    op.drop_table("kantor_aset")
    op.drop_table("kantor_audit_log")
    op.drop_table("kantor_aksi_pending")
    op.drop_table("kantor_sop_chunk")
    op.drop_table("kantor_sop_dokumen")
