"""Fase 1 — Gudang 1 dasar: 12 tabel

Revision ID: 0001_phase1
Revises:
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_phase1"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    # ── warehouses ──
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama_gudang", sa.String(100), nullable=False),
        sa.Column("alamat", sa.Text),
        sa.Column("kapasitas_tumpuk_ton", sa.Numeric(10, 2)),
        sa.Column("kapasitas_tumpuk_pk_ton", sa.Numeric(10, 2)),
        *_timestamps(),
    )

    # ── users ──
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("whatsapp_number", sa.String(30), unique=True),
        sa.Column("telegram_user_id", sa.BigInteger, unique=True),
        sa.Column("default_warehouse_id", sa.Integer, sa.ForeignKey("warehouses.id")),
        sa.Column("access_level", sa.String(20), server_default="operational"),
        sa.Column("wa_broadcast_opt_in", sa.Boolean, server_default=sa.false()),
        sa.Column("status", sa.String(20), server_default="aktif"),
        *_timestamps(),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"])

    # ── suppliers ──
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nama_supplier", sa.String(150), nullable=False),
        sa.Column("no_telfon", sa.String(30)),
        sa.Column("alamat", sa.Text),
        sa.Column("status", sa.String(20), server_default="aktif"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )

    # ── silos ──
    op.create_table(
        "silos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("warehouse_id", sa.Integer, sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("nama_silo", sa.String(50), nullable=False),
        sa.Column("kapasitas_ton", sa.Numeric(10, 2)),
        sa.Column("status", sa.String(20), server_default="kosong"),
        *_timestamps(),
    )

    # ── purchase_batches ──
    op.create_table(
        "purchase_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_batch", sa.String(20), nullable=False, unique=True),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("berat_total_kg", sa.Numeric(12, 2), nullable=False),
        sa.Column("no_polisi_truk", sa.String(20)),
        sa.Column("kondisi_gabah", sa.String(10), nullable=False),
        sa.Column("kadar_air_awal_persen", sa.Numeric(5, 2)),
        sa.Column("tanggal_pembelian", sa.Date, nullable=False),
        sa.Column("waktu_pembelian", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status_batch", sa.String(20), server_default="baru"),
        sa.Column("flag_unverified", sa.Boolean, server_default=sa.true()),
        *_timestamps(),
    )

    # ── purchase_batch_verifications ──
    op.create_table(
        "purchase_batch_verifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("purchase_batch_id", sa.Integer, sa.ForeignKey("purchase_batches.id"), nullable=False, unique=True),
        sa.Column("harga_per_kg", sa.Numeric(12, 2)),
        sa.Column("total_biaya", sa.Numeric(16, 2)),
        sa.Column("metode_harga", sa.String(10)),
        sa.Column("verified_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("waktu_verifikasi", sa.DateTime(timezone=True)),
        sa.Column("status_verifikasi", sa.String(20), server_default="terverifikasi"),
        *_timestamps(),
    )

    # ── drying_lots ──
    op.create_table(
        "drying_lots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kode_lot", sa.String(20), nullable=False, unique=True),
        sa.Column("waktu_mulai_pengeringan", sa.DateTime(timezone=True)),
        sa.Column("waktu_selesai_pengeringan", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), server_default="proses"),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        *_timestamps(),
    )

    # ── drying_lot_batches ──
    op.create_table(
        "drying_lot_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id"), nullable=False),
        sa.Column("purchase_batch_id", sa.Integer, sa.ForeignKey("purchase_batches.id"), nullable=False),
        sa.UniqueConstraint("drying_lot_id", "purchase_batch_id", name="uq_lot_batch"),
    )

    # ── drying_moisture_logs ──
    op.create_table(
        "drying_moisture_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id"), nullable=False),
        sa.Column("waktu_update", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kadar_air_indikator", sa.Numeric(5, 2)),
        sa.Column("kadar_air_tes_manual", sa.Numeric(5, 2)),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
    )

    # ── silo_storage ──
    op.create_table(
        "silo_storage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("silo_id", sa.Integer, sa.ForeignKey("silos.id"), nullable=False),
        sa.Column("drying_lot_id", sa.Integer, sa.ForeignKey("drying_lots.id")),
        sa.Column("purchase_batch_id", sa.Integer, sa.ForeignKey("purchase_batches.id")),
        sa.Column("tipe_masuk", sa.String(20), nullable=False),
        sa.Column("tanggal_masuk", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tanggal_keluar", sa.DateTime(timezone=True)),
        sa.Column("input_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), server_default="terisi"),
        *_timestamps(),
    )

    # ── activity_logs ──
    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("record_id", sa.Integer, nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("field_name", sa.String(64)),
        sa.Column("old_value", sa.Text),
        sa.Column("new_value", sa.Text),
        sa.Column("changed_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("waktu_perubahan", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("alasan_perubahan", sa.Text),
    )
    op.create_index("ix_activity_logs_table_record", "activity_logs", ["table_name", "record_id"])

    # ── notifications ──
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipe", sa.String(50), nullable=False),
        sa.Column("record_id", sa.Integer),
        sa.Column("table_name", sa.String(64)),
        sa.Column("target_role", sa.String(20)),
        sa.Column("pesan", sa.Text, nullable=False),
        sa.Column("prioritas", sa.String(10), server_default="kuning"),
        sa.Column("status", sa.String(20), server_default="baru"),
        sa.Column("eskalasi_target", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("eskalasi_jam", sa.Integer, server_default="24"),
        sa.Column("status_eskalasi", sa.String(20), server_default="belum"),
        sa.Column("waktu_eskalasi", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    for tbl in [
        "notifications",
        "activity_logs",
        "silo_storage",
        "drying_moisture_logs",
        "drying_lot_batches",
        "drying_lots",
        "purchase_batch_verifications",
        "purchase_batches",
        "silos",
        "suppliers",
        "users",
        "warehouses",
    ]:
        op.drop_table(tbl)
