"""Pisahkan lokasi, fasilitas produksi, dan jenis proses tanpa menulis ulang riwayat."""
from alembic import op
import sqlalchemy as sa
revision = "0122_fasilitas"
down_revision = "0121_pk_gudang_pemilik"
branch_labels = depends_on = None

def waktu():
    return [sa.Column(n, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
            for n in ("created_at", "updated_at")]

def upgrade():
    op.create_table("jenis_proses_produksi", sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("kode",sa.String(40),nullable=False,unique=True),
        sa.Column("nama",sa.String(100),nullable=False), sa.Column("aktif",sa.Boolean(),nullable=False),
        sa.Column("versi",sa.Integer(),nullable=False), *waktu())
    op.create_table("lini_produksi", sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("kode",sa.String(40),nullable=False),sa.Column("nama",sa.String(100),nullable=False),
        sa.Column("warehouse_id",sa.Integer(),sa.ForeignKey("warehouses.id"),nullable=False),
        sa.Column("jenis_proses_id",sa.Integer(),sa.ForeignKey("jenis_proses_produksi.id"),nullable=False),
        sa.Column("dryer_id",sa.Integer(),sa.ForeignKey("dryers.id"),unique=True),
        sa.Column("aktif",sa.Boolean(),nullable=False),sa.Column("versi",sa.Integer(),nullable=False),
        sa.UniqueConstraint("warehouse_id","kode",name="uq_lini_gudang_kode"), *waktu())
    op.create_table("audit_fasilitas",sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),
        sa.Column("objek",sa.String(40),nullable=False),sa.Column("objek_id",sa.Integer(),nullable=False),
        sa.Column("sebelum",sa.JSON()),sa.Column("sesudah",sa.JSON(),nullable=False),*waktu())
    op.execute("INSERT INTO jenis_proses_produksi (kode,nama,aktif,versi) VALUES ('pengeringan','Pengeringan',true,1),('penggilingan','Penggilingan',true,1),('penyosohan','Penyosohan',true,1)")
    # Satu fasilitas per alat yang benar-benar ada. Tidak membuat dryer baru.
    op.execute("""INSERT INTO lini_produksi (kode,nama,warehouse_id,jenis_proses_id,dryer_id,aktif,versi)
        SELECT 'dryer-'||d.id,d.nama,d.warehouse_id,j.id,d.id,d.status='aktif',1
        FROM dryers d CROSS JOIN jenis_proses_produksi j WHERE j.kode='pengeringan'""")
    for kode,gudang in (("penggilingan","g1"),("penyosohan","g2")):
        op.execute(sa.text("""INSERT INTO lini_produksi (kode,nama,warehouse_id,jenis_proses_id,aktif,versi)
            SELECT :kode,j.nama||' 1',w.id,j.id,true,1 FROM warehouses w
            CROSS JOIN jenis_proses_produksi j WHERE w.kode_fungsi=:gudang AND j.kode=:kode""").bindparams(kode=kode,gudang=gudang))
    for tabel in ("drying_lots","milling_process","polishing_process"):
        op.add_column(tabel,sa.Column("lini_produksi_id",sa.Integer(),sa.ForeignKey("lini_produksi.id")))
        op.create_index("ix_"+tabel+"_lini_produksi_id",tabel,["lini_produksi_id"])
    # Riwayat tidak diberi identitas line hasil tebakan. Kolom lama tetap utuh.

def downgrade():
    for tabel in ("drying_lots","milling_process","polishing_process"):
        op.drop_index("ix_"+tabel+"_lini_produksi_id",table_name=tabel)
        op.drop_column(tabel,"lini_produksi_id")
    op.drop_table("audit_fasilitas")
    op.drop_table("lini_produksi")
    op.drop_table("jenis_proses_produksi")
