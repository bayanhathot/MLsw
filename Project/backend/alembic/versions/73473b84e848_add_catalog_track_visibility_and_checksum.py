"""add catalog_tracks.visibility and checksum_sha256

Revision ID: 73473b84e848
Revises: 38e415e3f655
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "73473b84e848"
down_revision: Union[str, Sequence[str], None] = "38e415e3f655"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_tracks",
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
    )
    op.add_column(
        "catalog_tracks", sa.Column("checksum_sha256", sa.String(length=64), nullable=True)
    )
    op.create_index("ix_catalog_tracks_visibility", "catalog_tracks", ["visibility"])
    op.create_index("ix_catalog_tracks_checksum_sha256", "catalog_tracks", ["checksum_sha256"])
    op.create_check_constraint(
        "ck_catalog_track_visibility", "catalog_tracks", "visibility IN ('private', 'public')"
    )
    # The seeded demo catalog (no owner) is shared, established content --
    # unlike a real user's own upload, it should stay publicly retrievable
    # once visibility is ever enforced at retrieval time.
    op.execute("UPDATE catalog_tracks SET visibility = 'public' WHERE owner_id IS NULL")


def downgrade() -> None:
    op.drop_constraint("ck_catalog_track_visibility", "catalog_tracks", type_="check")
    op.drop_index("ix_catalog_tracks_checksum_sha256", table_name="catalog_tracks")
    op.drop_index("ix_catalog_tracks_visibility", table_name="catalog_tracks")
    op.drop_column("catalog_tracks", "checksum_sha256")
    op.drop_column("catalog_tracks", "visibility")
