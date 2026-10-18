"""Pisahkan waktu kejadian jeda dari pencatatan dan pertahankan riwayat kondisi."""
from alembic import op
import sqlalchemy as sa
revision = '0101_jeda_kejadian'
down_revision = '0100_qc_pk_luar_berulang'
branch_labels = depends_on = None


def upgrade():
    op.add_column('jeda_proses',sa.Column('dibatalkan_pada',sa.DateTime(timezone=True)))
    op.create_table('jeda_catatan',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('jeda_id',sa.Integer(),sa.ForeignKey('jeda_proses.id'),nullable=False),
        sa.Column('aksi',sa.String(30),nullable=False),
        sa.Column('waktu_kejadian',sa.DateTime(timezone=True),nullable=False),
        sa.Column('dicatat_pada',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('dicatat_oleh',sa.Integer(),sa.ForeignKey('users.id')),
        sa.Column('sebab',sa.String(120),nullable=False),
        sa.Column('catatan',sa.Text()),
        sa.Column('alasan_terlambat',sa.Text()),
        sa.Column('kunci_kiriman',sa.String(64),unique=True),
        sa.Column('sidik_payload',sa.String(64)),
        sa.Column('hasil',sa.JSON()),
        sa.Column('asal_lama',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('dibatalkan_pada',sa.DateTime(timezone=True)),
        sa.Column('dibatalkan_oleh',sa.Integer(),sa.ForeignKey('users.id')),
    )
    op.create_index('ix_jeda_catatan_jeda','jeda_catatan',['jeda_id','id'])
    op.execute("""INSERT INTO jeda_catatan
      (jeda_id,aksi,waktu_kejadian,dicatat_pada,dicatat_oleh,sebab,asal_lama)
      SELECT id,'hentikan',mulai,created_at,dicatat_oleh,sebab,true FROM jeda_proses""")
    # Audit lama menunjuk ID proses, bukan ID jeda. Hanya pasangan kode,
    # waktu, dan kejadian yang tunggal boleh dipakai; selebihnya tetap tidak
    # diketahui. Penutupan otomatis saat proses selesai bukan pernyataan lanjut.
    op.execute("""INSERT INTO jeda_catatan
      (jeda_id,aksi,waktu_kejadian,dicatat_pada,dicatat_oleh,sebab,asal_lama)
      SELECT j.id,CASE WHEN a.n=1 THEN 'lanjutkan' ELSE 'penutupan_lama' END,
        j.selesai,COALESCE(a.dicatat,j.selesai),
        CASE WHEN a.n=1 THEN a.petugas ELSE NULL END,j.sebab,true
      FROM jeda_proses j
      LEFT JOIN drying_lots d ON d.id=j.drying_lot_id
      LEFT JOIN milling_process m ON m.id=j.milling_process_id
      LEFT JOIN polishing_process p ON p.id=j.polishing_process_id
      LEFT JOIN LATERAL (
        SELECT count(*) n,min(changed_by) petugas,min(waktu_perubahan) dicatat
        FROM activity_logs l WHERE l.table_name='jeda_proses'
          AND l.record_id=COALESCE(j.drying_lot_id,j.milling_process_id,j.polishing_process_id)
          AND l.action='UPDATE' AND l.field_name='selesai'
          AND l.dibatalkan_pada IS NULL
          AND l.new_value LIKE COALESCE(d.kode_lot,m.kode_proses,p.kode_proses)||' lanjut — %'
          AND abs(extract(epoch FROM l.waktu_perubahan-j.selesai))<=2
          AND (SELECT count(*) FROM jeda_proses lain
            WHERE lain.jenis=j.jenis
              AND COALESCE(lain.drying_lot_id,lain.milling_process_id,lain.polishing_process_id)
                = COALESCE(j.drying_lot_id,j.milling_process_id,j.polishing_process_id)
              AND abs(extract(epoch FROM l.waktu_perubahan-lain.selesai))<=2)=1
      ) a ON true WHERE j.selesai IS NOT NULL""")


def downgrade():
    op.drop_index('ix_jeda_catatan_jeda',table_name='jeda_catatan')
    op.drop_table('jeda_catatan')
    op.drop_column('jeda_proses','dibatalkan_pada')
