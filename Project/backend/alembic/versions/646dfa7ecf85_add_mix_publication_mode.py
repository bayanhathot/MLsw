"""add mixes.publication_mode and published_manifest_json

Revision ID: 646dfa7ecf85
Revises: a6d1c8e4f209
Create Date: 2026-08-30 00:00:00.000000

Backfills `publication_mode` for every already-published row from its
segments' own `source` column (never from application code, so this stays
correct even if the app's own default policy changes later): any published
mix with at least one non-'catalog' segment is provider-sourced and is
backfilled as 'provider_manifest'; every other published mix is backfilled
as 'rendered_asset'. `published_manifest_json` is deliberately left NULL
for every pre-existing row -- see mix.py's own column docstring and
publish_service.py's `resolve_playback_manifest`, which reconstructs an
equivalent manifest on demand from `published_segments_json` for exactly
this legacy case rather than requiring a manifest to already exist.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "646dfa7ecf85"
down_revision: Union[str, Sequence[str], None] = "a6d1c8e4f209"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mixes", sa.Column("publication_mode", sa.String(length=20), nullable=True))
    op.add_column("mixes", sa.Column("published_manifest_json", sa.JSON(), nullable=True))
    op.create_check_constraint(
        "ck_mix_publication_mode",
        "mixes",
        "publication_mode IS NULL OR publication_mode IN ('rendered_asset', 'provider_manifest')",
    )

    bind = op.get_bind()
    mixes = sa.table(
        "mixes",
        sa.column("id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("publication_mode", sa.String),
    )
    mix_segments = sa.table(
        "mix_segments",
        sa.column("mix_id", sa.Integer),
        sa.column("source", sa.String),
    )
    published_ids = [
        row[0]
        for row in bind.execute(sa.select(mixes.c.id).where(mixes.c.status == "published"))
    ]
    for mix_id in published_ids:
        provider_segment_count = bind.execute(
            sa.select(sa.func.count())
            .select_from(mix_segments)
            .where(mix_segments.c.mix_id == mix_id, mix_segments.c.source != "catalog")
        ).scalar()
        mode = "provider_manifest" if provider_segment_count else "rendered_asset"
        bind.execute(mixes.update().where(mixes.c.id == mix_id).values(publication_mode=mode))


def downgrade() -> None:
    op.drop_constraint("ck_mix_publication_mode", "mixes", type_="check")
    op.drop_column("mixes", "published_manifest_json")
    op.drop_column("mixes", "publication_mode")
