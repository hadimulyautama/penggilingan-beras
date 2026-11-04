"""Identitas gudang sumber PK dan pemilik pada saat PK dipakai."""
from alembic import op
import sqlalchemy as sa

revision = '0121_pk_gudang_pemilik'
down_revision = '0120_qc_sosoh'
branch_labels = depends_on = None


def upgrade():
    for table in ['milling_process', 'pk_gudang2_intakes']:
        op.add_column(table, sa.Column('warehouse_id', sa.Integer(), nullable=True))
        op.create_foreign_key('fk_'+table+'_warehouse', table, 'warehouses', ['warehouse_id'], ['id'])
        op.create_index('ix_'+table+'_warehouse_id', table, ['warehouse_id'])
    for table in ['pk_tumpukan_to_silo', 'permintaan_pk']:
        op.add_column(table, sa.Column('jasa_id', sa.Integer(), nullable=True))
        op.create_foreign_key('fk_'+table+'_jasa', table, 'jasa', ['jasa_id'], ['id'])
    # Lebih dari satu gudang pada proses lama tetap tidak ditebak. Operasi
    # kepemilikan menolak sumber yang lokasi fisiknya belum dapat dibuktikan.
    op.execute('''UPDATE milling_process p SET warehouse_id=x.wid FROM
        (SELECT m.milling_process_id pid, min(s.warehouse_id) wid
         FROM milling_process_sources m JOIN silo_storage st ON st.id=m.silo_storage_id
         JOIN silos s ON s.id=st.silo_id GROUP BY m.milling_process_id
         HAVING count(DISTINCT s.warehouse_id)=1) x WHERE p.id=x.pid''')
    op.execute('''UPDATE milling_process p SET warehouse_id=s.warehouse_id FROM silos s
        WHERE s.id=p.silo_id AND p.warehouse_id IS NULL AND NOT EXISTS
        (SELECT 1 FROM milling_process_sources m WHERE m.milling_process_id=p.id)''')
    # Pemetaan kode legacy hanya dilakukan ketika memigrasikan data lama.
    # Transaksi baru menyimpan dan memakai ID gudang, termasuk gudang baru.
    op.execute('''UPDATE pk_gudang2_intakes i SET warehouse_id=coalesce(
        (SELECT s.warehouse_id FROM silos s WHERE s.id=i.silo_id),
        (SELECT w.id FROM warehouses w WHERE w.kode_fungsi='g2'))''')
    op.execute("""UPDATE outgoing_records r SET warehouse_id=(SELECT id FROM warehouses WHERE kode_fungsi='g2')
        WHERE warehouse_id IS NULL AND EXISTS (SELECT 1 FROM outgoing_items i
        WHERE i.outgoing_record_id=r.id AND i.item_type='pk_g2' AND i.silo_id IS NULL)""")
    op.execute('''UPDATE pk_tumpukan_to_silo m SET jasa_id=i.jasa_id
        FROM pk_gudang2_intakes i WHERE i.id=m.pk_gudang2_intake_id''')
    op.execute('''UPDATE permintaan_pk r SET jasa_id=p.jasa_id
        FROM milling_process p WHERE p.id=r.milling_process_id''')


def downgrade():
    for table in ['pk_tumpukan_to_silo', 'permintaan_pk']:
        op.drop_constraint('fk_'+table+'_jasa', table, type_='foreignkey')
        op.drop_column(table, 'jasa_id')
    for table in ['milling_process', 'pk_gudang2_intakes']:
        op.drop_index('ix_'+table+'_warehouse_id', table_name=table)
        op.drop_constraint('fk_'+table+'_warehouse', table, type_='foreignkey')
        op.drop_column(table, 'warehouse_id')
