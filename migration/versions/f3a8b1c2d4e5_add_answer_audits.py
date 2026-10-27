"""Add answer audit table.

Revision ID: f3a8b1c2d4e5
Revises: 9c1d7f2a4b6e
Create Date: 2026-10-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a8b1c2d4e5"
down_revision: Union[str, Sequence[str], None] = "9c1d7f2a4b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "answer_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("thread_id", sa.String(length=100), nullable=True),
        sa.Column("route", sa.String(length=50), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("retrieval_score", sa.Float(), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("created_at_wib", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_answer_audits_user_id"), "answer_audits", ["user_id"], unique=False)
    op.create_index(op.f("ix_answer_audits_thread_id"), "answer_audits", ["thread_id"], unique=False)
    op.create_index(op.f("ix_answer_audits_route"), "answer_audits", ["route"], unique=False)
    op.create_index(op.f("ix_answer_audits_created_at"), "answer_audits", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_answer_audits_created_at"), table_name="answer_audits")
    op.drop_index(op.f("ix_answer_audits_route"), table_name="answer_audits")
    op.drop_index(op.f("ix_answer_audits_thread_id"), table_name="answer_audits")
    op.drop_index(op.f("ix_answer_audits_user_id"), table_name="answer_audits")
    op.drop_table("answer_audits")
