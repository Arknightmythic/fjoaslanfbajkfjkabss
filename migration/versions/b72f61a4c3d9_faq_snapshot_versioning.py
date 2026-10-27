"""Add atomic FAQ snapshot versioning.

Revision ID: b72f61a4c3d9
Revises: 2703abf01be0
Create Date: 2026-10-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b72f61a4c3d9"
down_revision: Union[str, Sequence[str], None] = "2703abf01be0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_vector_tables() -> bool:
    return bool(op.get_bind().execute(sa.text(
        "SELECT to_regclass('langchain_pg_embedding') IS NOT NULL "
        "AND to_regclass('langchain_pg_collection') IS NOT NULL"
    )).scalar())


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("version_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )

    op.create_table(
        "faq_index_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # The langchain_pg_* vector tables are created by langchain-postgres on first
    # use, so a fresh database does not have them yet: nothing to tag then.
    if not _has_vector_tables():
        op.execute(
            """INSERT INTO faq_index_state (id, active_version, next_version)
               SELECT 1, 0, COALESCE((SELECT MAX(version_number) + 1 FROM knowledge_documents), 1)"""
        )
        return

    # Existing vectors form the initial active FAQ snapshot. Preserve their data
    # and tag it as version 1 instead of dropping/rebuilding the vector tables.
    op.execute(
        """UPDATE langchain_pg_embedding AS e
           SET cmetadata = COALESCE(e.cmetadata, '{}'::jsonb) || jsonb_build_object('faq_version', 1)
           FROM langchain_pg_collection AS c
           WHERE e.collection_id = c.uuid
             AND c.name = 'synchrono_faq_docs'
             AND e.cmetadata ->> 'faq_version' IS NULL"""
    )
    op.execute(
        """INSERT INTO faq_index_state (id, active_version, next_version)
           SELECT 1,
                  CASE WHEN EXISTS (
                      SELECT 1 FROM langchain_pg_embedding e
                      JOIN langchain_pg_collection c ON c.uuid = e.collection_id
                      WHERE c.name = 'synchrono_faq_docs'
                  ) THEN 1 ELSE 0 END,
                   GREATEST(
                       COALESCE((SELECT MAX(version_number) + 1 FROM knowledge_documents), 1),
                       CASE WHEN EXISTS (
                           SELECT 1 FROM langchain_pg_embedding e
                           JOIN langchain_pg_collection c ON c.uuid = e.collection_id
                           WHERE c.name = 'synchrono_faq_docs'
                       ) THEN 2 ELSE 1 END
                   )"""
    )


def downgrade() -> None:
    op.drop_table("faq_index_state")
    op.drop_column("knowledge_documents", "version_number")
