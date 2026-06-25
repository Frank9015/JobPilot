"""add_application_question_table

Revision ID: a1b2c3d4e5f6
Revises: c3e80a8e477c
Create Date: 2026-06-25 10:32:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c3e80a8e477c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('application_question',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('application_id', sa.UUID(), nullable=False),
    sa.Column('question_label', sa.Text(), nullable=False),
    sa.Column('question_type', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('answer_source', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Text(), nullable=True),
    sa.Column('gemini_reasoning', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['application.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('application_question')
