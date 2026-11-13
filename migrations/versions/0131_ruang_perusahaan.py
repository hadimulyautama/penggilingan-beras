"""Pagar ruang perusahaan; tidak menulis ulang transaksi atau saldo lama."""
from alembic import op
import sqlalchemy as sa
revision = '0131_ruang_perusahaan'
down_revision = '0130_console_akses_anggota'
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION hmu_pagar_ruang_setelan() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE identitas jsonb;
    BEGIN
      IF TG_OP <> 'INSERT' AND OLD.kunci = 'ruang_data_perusahaan' THEN
        RAISE EXCEPTION 'Identitas ruang data perusahaan tidak dapat diubah atau dihapus';
      END IF;
      IF TG_OP <> 'DELETE' AND NEW.kunci = 'ruang_data_perusahaan' THEN
        identitas := NEW.nilai::jsonb;
        IF NOT (identitas ? 'company_id' AND identitas ? 'ruang_id')
           OR NOT EXISTS (SELECT 1 FROM hmu_companies WHERE id=(identitas->>'company_id')::int)
           OR EXISTS (SELECT 1 FROM warehouses w LEFT JOIN hmu_warehouse_sites p ON p.warehouse_id=w.id
                      WHERE p.warehouse_id IS NULL OR p.company_id<>(identitas->>'company_id')::int) THEN
          RAISE EXCEPTION 'Gudang belum seluruhnya cocok dengan perusahaan ruang data';
        END IF;
        PERFORM (identitas->>'ruang_id')::uuid;
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER hmu_pagar_ruang_setelan BEFORE INSERT OR UPDATE OR DELETE ON setelan_pabrik
                  FOR EACH ROW EXECUTE FUNCTION hmu_pagar_ruang_setelan()""")
    op.execute("""CREATE FUNCTION hmu_pagar_ruang_gudang() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE cid int;
    BEGIN
      SELECT (nilai::jsonb->>'company_id')::int INTO cid FROM setelan_pabrik WHERE kunci='ruang_data_perusahaan';
      IF cid IS NOT NULL AND NEW.company_id <> cid THEN
        RAISE EXCEPTION 'Gudang perusahaan lain harus memakai ruang data terpisah';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER hmu_pagar_ruang_gudang BEFORE INSERT OR UPDATE ON hmu_warehouse_sites
                  FOR EACH ROW EXECUTE FUNCTION hmu_pagar_ruang_gudang()""")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM setelan_pabrik WHERE kunci='ruang_data_perusahaan'")).first():
        raise RuntimeError('Ruang perusahaan sudah diaktifkan; pagar data tidak boleh dilepas melalui downgrade.')
    op.execute('DROP TRIGGER hmu_pagar_ruang_gudang ON hmu_warehouse_sites')
    op.execute('DROP FUNCTION hmu_pagar_ruang_gudang()')
    op.execute('DROP TRIGGER hmu_pagar_ruang_setelan ON setelan_pabrik')
    op.execute('DROP FUNCTION hmu_pagar_ruang_setelan()')
