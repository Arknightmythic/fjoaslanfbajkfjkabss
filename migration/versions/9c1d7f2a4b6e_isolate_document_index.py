"""Isolate FAQ and non-FAQ document indexes.

Revision ID: 9c1d7f2a4b6e
Revises: b72f61a4c3d9
Create Date: 2026-10-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c1d7f2a4b6e"
down_revision: Union[str, Sequence[str], None] = "b72f61a4c3d9"
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
        sa.Column("source_type", sa.String(length=20), server_default=sa.text("'faq'"), nullable=False),
    )
    op.create_index(
        op.f("ix_knowledge_documents_source_type"),
        "knowledge_documents",
        ["source_type"],
        unique=False,
    )

    op.create_table(
        "knowledge_index_state",
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("active_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("source_type"),
    )

    # Existing documents and vectors all belong to the FAQ source. A fresh database
    # has no langchain_pg_* tables yet (langchain-postgres creates them on first use).
    op.execute("UPDATE knowledge_documents SET source_type = 'faq'")
    if _has_vector_tables():
        op.execute(
            """UPDATE langchain_pg_embedding AS e
               SET cmetadata = COALESCE(e.cmetadata, '{}'::jsonb) || jsonb_build_object('source_type', 'faq')
               FROM langchain_pg_collection AS c
               WHERE e.collection_id = c.uuid
                 AND c.name = 'synchrono_faq_docs'
                 AND e.cmetadata ->> 'source_type' IS NULL"""
        )

    op.execute(
        """INSERT INTO knowledge_index_state (source_type, active_version, next_version)
           SELECT 'faq',
                  COALESCE((SELECT active_version FROM faq_index_state WHERE id = 1), 0),
                  COALESCE((SELECT next_version FROM faq_index_state WHERE id = 1), 1)"""
    )
    op.execute(
        """INSERT INTO knowledge_index_state (source_type, active_version, next_version)
           VALUES ('document', 0, 1)"""
    )

    op.drop_table("faq_index_state")


def downgrade() -> None:
    op.create_table(
        "faq_index_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """INSERT INTO faq_index_state (id, active_version, next_version)
           SELECT 1, active_version, next_version
           FROM knowledge_index_state
           WHERE source_type = 'faq'"""
    )

    if _has_vector_tables():
        op.execute(
            """UPDATE langchain_pg_embedding
               SET cmetadata = cmetadata - 'source_type'
               WHERE cmetadata ? 'source_type'"""
        )

    op.drop_table("knowledge_index_state")
    op.drop_index(op.f("ix_knowledge_documents_source_type"), table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "source_type")
