"""Sampel sebelum timbang; identitas terkunci, hasil lab menyusul."""
from alembic import op
import sqlalchemy as sa

revision = "0120_qc_sosoh"
down_revision = "0119_koreksi_bahan_berjalan"
branch_labels = depends_on = None


def upgrade():
    op.create_table("sampel_qc_sosoh",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("polishing_process_id", sa.Integer(), sa.ForeignKey("polishing_process.id"), nullable=False),
        sa.Column("jenis", sa.String(20), nullable=False),
        sa.Column("kunci_kiriman", sa.String(80)),
        sa.Column("waktu_sampel", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dicatat_pada", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pengambil_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("hasil_pada", sa.DateTime(timezone=True)),
        sa.Column("pemeriksa_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("kadar_air", sa.Numeric(5, 2)),
        sa.Column("broken_persen", sa.Numeric(5, 2)),
        sa.Column("md", sa.Numeric(12, 2)),
        sa.Column("transparant", sa.Numeric(12, 2)),
        sa.Column("whiteness", sa.Numeric(12, 2)),
        sa.Column("catatan_lab", sa.String(500)),
        sa.Column("dibatalkan_pada", sa.DateTime(timezone=True)),
        sa.Column("dibatalkan_oleh_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("alasan_batal", sa.String(500)),
        sa.UniqueConstraint("polishing_process_id", "kunci_kiriman", name="uq_sampel_sosoh_kiriman"),
        sa.CheckConstraint("jenis IN ('medium', 'premium', 'medsuper', 'sayur', 'beras_b')", name="ck_sampel_sosoh_jenis"),
        sa.CheckConstraint("hasil_pada IS NULL OR hasil_pada >= waktu_sampel", name="ck_sampel_sosoh_waktu"),
        *(sa.CheckConstraint(f"{kolom} BETWEEN 0 AND 100", name=f"ck_sampel_sosoh_{kolom}")
          for kolom in ("kadar_air", "broken_persen")),
        *(sa.CheckConstraint(f"{kolom} >= 0", name=f"ck_sampel_sosoh_{kolom}")
          for kolom in ("md", "transparant", "whiteness")))
    op.create_index("ix_sampel_qc_sosoh_proses_waktu", "sampel_qc_sosoh", ["polishing_process_id", "waktu_sampel", "id"])
    op.add_column("polishing_output_logs", sa.Column("cara_input", sa.String(20), nullable=False, server_default=sa.text("'lama'")))
    op.create_check_constraint("ck_hasil_sosoh_cara_input", "polishing_output_logs", "cara_input IN ('lama', 'tambahan', 'kumulatif')")
    op.execute("""
        CREATE FUNCTION jaga_identitas_sampel_sosoh() RETURNS trigger AS $$
        BEGIN
          IF ROW(NEW.polishing_process_id, NEW.jenis, NEW.kunci_kiriman, NEW.waktu_sampel,
                 NEW.dicatat_pada, NEW.pengambil_id)
             IS DISTINCT FROM
             ROW(OLD.polishing_process_id, OLD.jenis, OLD.kunci_kiriman, OLD.waktu_sampel,
                 OLD.dicatat_pada, OLD.pengambil_id) THEN
            RAISE EXCEPTION 'Identitas sampel QC sosoh tidak boleh diubah';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""CREATE TRIGGER identitas_sampel_sosoh_tetap BEFORE UPDATE ON sampel_qc_sosoh
        FOR EACH ROW EXECUTE FUNCTION jaga_identitas_sampel_sosoh()""")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM sampel_qc_sosoh")):
        raise RuntimeError("Sampel QC telah dicatat; jangan hapus riwayat pemeriksaan untuk mundur versi.")
    op.drop_constraint("ck_hasil_sosoh_cara_input", "polishing_output_logs", type_="check")
    op.drop_column("polishing_output_logs", "cara_input")
    op.drop_table("sampel_qc_sosoh")
    op.execute("DROP FUNCTION jaga_identitas_sampel_sosoh()")
