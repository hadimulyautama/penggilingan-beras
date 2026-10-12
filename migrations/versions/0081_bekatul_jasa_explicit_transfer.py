"""Bekatul proses jasa tetap milik pemilik sampai dipindahkan manual.

Perubahan keputusan operasional 12 Oktober 2026: bekatul dari jasa tidak
otomatis menjadi stok pabrik. Baris lama yang dulu otomatis berstatus pabrik
dikembalikan ke pemilik proses. Proses yang memiliki jejak pindah kepemilikan
manual tidak disentuh.

Revision ID: 0081_bekatul_jasa_explicit_transfer
Revises: 0080_outgoing_item_jasa_id
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0081_bekatul_jasa_explicit_transfer"
down_revision: Union[str, None] = "0080_outgoing_item_jasa_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Audit perpindahan lama hanya menunjuk satu baris per operasi. Karena itu
    # pengecualian berlaku pada seluruh stok bekatul proses tersebut agar
    # pemindahan manual yang sah tidak dibalik sebagian secara keliru.
    op.execute("""
        UPDATE byproduct_stock AS b
           SET jasa_id = p.jasa_id
          FROM polishing_process AS p
         WHERE b.jenis_produk = 'bekatul'
           AND b.source_type = 'polishing'
           AND b.jasa_id IS NULL
           AND p.id = b.source_id
           AND p.jasa_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM byproduct_stock AS moved
                 JOIN activity_logs AS a
                   ON a.table_name = 'byproduct_stock'
                  AND a.record_id = moved.id
                  AND a.aksi = 'pindah_kepemilikan_produk'
                WHERE moved.jenis_produk = 'bekatul'
                  AND moved.source_type = b.source_type
                  AND moved.source_id = b.source_id
           )
    """)
    op.execute("""
        UPDATE finished_goods_stock AS f
           SET jasa_id = p.jasa_id
          FROM polishing_process AS p, product_skus AS sku
         WHERE sku.id = f.product_sku_id
           AND sku.kategori = 'bekatul'
           AND f.source_type = 'polishing'
           AND f.jasa_id IS NULL
           AND p.id = f.source_id
           AND p.jasa_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM finished_goods_stock AS moved
                 JOIN product_skus AS moved_sku
                   ON moved_sku.id = moved.product_sku_id
                  AND moved_sku.kategori = 'bekatul'
                 JOIN activity_logs AS a
                   ON a.table_name = 'finished_goods_stock'
                  AND a.record_id = moved.id
                  AND a.aksi = 'pindah_kepemilikan_produk'
                WHERE moved.source_type = f.source_type
                  AND moved.source_id = f.source_id
           )
    """)


def downgrade() -> None:
    # Tidak dibalik: sesudah migrasi, nilai NULL menandakan stok yang memang
    # dipindahkan ke pabrik secara eksplisit, dan data lama sudah dikembalikan
    # ke pemilik proses tanpa penanda yang dapat memisahkannya lagi.
    pass
