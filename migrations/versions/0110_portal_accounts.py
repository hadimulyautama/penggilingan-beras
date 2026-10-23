"""Separate customer login, never a production staff role."""
from alembic import op
import sqlalchemy as sa
revision = '0110_portal_accounts'
down_revision = '0109_pk_penyesuaian_stok'
branch_labels = depends_on = None


def upgrade():
    # Do not hold shared production tables waiting on a long-running writer.
    # PostgreSQL rolls back this additive migration on timeout; startup retries.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '60s'")
    op.create_table('portal_accounts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pelanggan_id', sa.Integer(), sa.ForeignKey('pelanggan.id'), nullable=False),
        sa.Column('username', sa.String(80), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='1'))
    op.create_index('ix_portal_accounts_pelanggan_id', 'portal_accounts', ['pelanggan_id'])

    op.create_table('portal_notification_reads',
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('portal_accounts.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('notification_id', sa.Integer(), sa.ForeignKey('notifications.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('dibaca', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table('portal_ownership_events',
        sa.Column('audit_id', sa.Integer(), sa.ForeignKey('activity_logs.id'), primary_key=True),
        sa.Column('pelanggan_id', sa.Integer(), sa.ForeignKey('pelanggan.id'), primary_key=True))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT (SELECT count(*) FROM portal_accounts)+(SELECT count(*) FROM portal_ownership_events)')):
        raise RuntimeError('Portal accounts exist; revoke/export them before downgrade.')
    op.drop_table('portal_notification_reads')
    op.drop_table('portal_ownership_events')
    op.drop_table('portal_accounts')
