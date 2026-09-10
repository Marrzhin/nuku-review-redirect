"""skema provisioning kartu: review_links (status/token/batch) + redirect_hits

Migration tunggal dari skema final. Versi sebelumnya (kolom `active` boolean)
sengaja tidak dipertahankan lewat migrasi bertahap — belum ada data produksi,
jadi database lama cukup di-drop dan dibuat ulang dari sini.

Revision ID: 0001_card_provisioning
Revises:
Create Date: 2026-09-09 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_card_provisioning"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

link_status = sa.Enum(
    "unassigned", "active", "inactive", name="link_status"
)


def upgrade() -> None:
    op.create_table(
        "review_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("status", link_status, nullable=False),
        sa.Column("activation_token", sa.String(length=48), nullable=True),
        sa.Column("batch_label", sa.String(length=32), nullable=False),
        sa.Column("business_name", sa.String(length=255), nullable=True),
        sa.Column("destination_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_links_slug", "review_links", ["slug"], unique=True)
    op.create_index("ix_review_links_status", "review_links", ["status"])
    op.create_index("ix_review_links_batch_label", "review_links", ["batch_label"])

    op.create_table(
        "redirect_hits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("link_id", sa.Integer(), nullable=False),
        sa.Column("hit_at", sa.DateTime(), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["link_id"], ["review_links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_redirect_hits_link_id_hit_at", "redirect_hits", ["link_id", "hit_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_redirect_hits_link_id_hit_at", table_name="redirect_hits")
    op.drop_table("redirect_hits")
    op.drop_index("ix_review_links_batch_label", table_name="review_links")
    op.drop_index("ix_review_links_status", table_name="review_links")
    op.drop_index("ix_review_links_slug", table_name="review_links")
    op.drop_table("review_links")
    link_status.drop(op.get_bind(), checkfirst=True)
