"""Selaraskan empat rujukan yang sudah dideklarasikan model.

NOT VALID mempertahankan catatan historis apa adanya tanpa memindai/mengubah
isinya. Rujukan baru tetap diperiksa. Indeks/kolom lama hanya dilengkapi di
metadata aplikasi; tidak ada indeks atau kolom operasional yang dihapus.
"""
from alembic import op
import sqlalchemy as sa
revision='0105_selaras_referensi'
down_revision='0104_kemas_ulang'
branch_labels=depends_on=None
RUJUKAN=[('outgoing_records','diperintah_oleh','users'),('outgoing_records','dimuat_oleh','users'),
         ('outgoing_records','diverifikasi_oleh','users'),('proyeksi_transfer_pk','silo_id','silos')]

def upgrade():
    db=op.get_bind()
    for tabel,kolom,tujuan in RUJUKAN:
        ada=any(f['constrained_columns']==[kolom] and f['referred_table']==tujuan for f in sa.inspect(db).get_foreign_keys(tabel))
        if not ada:
            opsi={'postgresql_not_valid':True} if db.dialect.name=='postgresql' else {}
            op.create_foreign_key('fk_selaras_'+tabel+'_'+kolom,tabel,tujuan,[kolom],['id'],**opsi)

def downgrade():
    for tabel,kolom,_ in reversed(RUJUKAN):
        nama='fk_selaras_'+tabel+'_'+kolom
        if any(f['name']==nama for f in sa.inspect(op.get_bind()).get_foreign_keys(tabel)):
            op.drop_constraint(nama,tabel,type_='foreignkey')
