"""Customer credentials are deliberately separate from production staff accounts."""
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PortalAccount(Base):
    __tablename__ = 'portal_accounts'
    id: Mapped[int] = mapped_column(primary_key=True)
    pelanggan_id: Mapped[int] = mapped_column(ForeignKey('pelanggan.id'), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PortalNotificationRead(Base):
    __tablename__ = 'portal_notification_reads'
    account_id: Mapped[int] = mapped_column(ForeignKey('portal_accounts.id', ondelete='CASCADE'), primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey('notifications.id', ondelete='CASCADE'), primary_key=True)
    dibaca: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PortalOwnershipEvent(Base):
    """Immutable customer attribution, surviving changes to a stock row owner."""
    __tablename__ = 'portal_ownership_events'
    audit_id: Mapped[int] = mapped_column(ForeignKey('activity_logs.id'), primary_key=True)
    pelanggan_id: Mapped[int] = mapped_column(ForeignKey('pelanggan.id'), primary_key=True)
