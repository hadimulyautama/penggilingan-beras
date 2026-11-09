"""Master hasil operasional: nama Ekonomis, jenis QC dinamis, hasil samping."""
import json
from alembic import op
import sqlalchemy as sa
revision = '0124_master_hasil'
down_revision = '0123_lokasi_penerimaan'
branch_labels = depends_on = None


def upgrade():
    db = op.get_bind()
    # Ubah label saja. ID/kode/FK dan semua angka transaksi tetap sama.
    db.execute(sa.text("UPDATE rice_quality_standards SET nama='Ekonomis' WHERE kode='sayur' AND lower(trim(nama))='sayur'"))
    op.drop_constraint('ck_sampel_sosoh_jenis', 'sampel_qc_sosoh', type_='check')
    for kode, nama, ukuran in [('broken','Broken',50),('menir','Menir',50),('bekatul','Bekatul',40),('reject','Reject',50)]:
        nilai = json.dumps(dict(kode=kode, nama=nama, aktif=True, bentuk='karung', kg_karung=ukuran))
        db.execute(sa.text('INSERT INTO setelan_pabrik (kunci,nilai) VALUES (:k,:v) ON CONFLICT (kunci) DO NOTHING'),
                   dict(k='jenis_hasil_samping:'+kode, v=nilai))

    db.execute(sa.text("INSERT INTO setelan_pabrik (kunci,nilai) VALUES ('master_hasil_samping_disiapkan','1') ON CONFLICT (kunci) DO NOTHING"))


def downgrade():
    # NOT VALID mempertahankan sampel jenis baru saat rollback aplikasi.
    op.create_check_constraint('ck_sampel_sosoh_jenis', 'sampel_qc_sosoh',
        "jenis IN ('medium','premium','medsuper','sayur','beras_b')", postgresql_not_valid=True)
    # Nama/config adalah keputusan pengguna; jangan hapus atau timpa saat downgrade.
