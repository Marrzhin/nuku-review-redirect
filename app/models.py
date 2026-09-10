import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    """UTC naive — MySQL DATETIME tidak menyimpan timezone."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LinkStatus(str, enum.Enum):
    """Siklus hidup satu kartu fisik.

    unassigned : kartu sudah dicetak dan ada di stok, belum terhubung ke bisnis.
    active     : sudah diaktivasi klien, redirect jalan.
    inactive   : klien berhenti / dinonaktifkan sementara oleh admin.
    """

    UNASSIGNED = "unassigned"
    ACTIVE = "active"
    INACTIVE = "inactive"


class ReviewLink(Base):
    __tablename__ = "review_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Dibuat saat batch produksi, dicetak ke QR/NFC sebelum ada klien.
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    status: Mapped[LinkStatus] = mapped_column(
        Enum(
            LinkStatus,
            name="link_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=LinkStatus.UNASSIGNED,
        index=True,
    )

    # Dikirim privat ke klien saat closing — TIDAK PERNAH dicetak di kartu.
    activation_token: Mapped[str | None] = mapped_column(String(48), nullable=True)

    # mis. "batch-2026-09" — untuk melacak masalah yang spesifik ke satu cetakan.
    batch_label: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Keduanya kosong selama status unassigned, diisi saat aktivasi.
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    destination_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    hits: Mapped[list["RedirectHit"]] = relationship(
        back_populates="link", cascade="all, delete-orphan"
    )


class RedirectHit(Base):
    __tablename__ = "redirect_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link_id: Mapped[int] = mapped_column(
        ForeignKey("review_links.id", ondelete="CASCADE"), nullable=False
    )
    hit_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    # Sengaja tidak menyimpan IP address (lihat catatan privasi di blueprint).
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    link: Mapped[ReviewLink] = relationship(back_populates="hits")

    __table_args__ = (Index("ix_redirect_hits_link_id_hit_at", "link_id", "hit_at"),)
