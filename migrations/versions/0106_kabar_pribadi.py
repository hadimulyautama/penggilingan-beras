"""Status baca Kabar per pengguna, tanpa mengubah histori notifikasi."""
from alembic import op
import sqlalchemy as sa
revision = '0106_kabar_pribadi'
down_revision = '0105_selaras_referensi'
branch_labels = depends_on = None

def upgrade():
    op.create_table('notification_reads',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('notification_id', sa.Integer(), sa.ForeignKey('notifications.id'), primary_key=True),
        sa.Column('dibaca', sa.Boolean(), nullable=False))

def downgrade():
    op.drop_table('notification_reads')
