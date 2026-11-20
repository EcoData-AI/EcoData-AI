"""study and tutor (Milestone 6)

Adds SM-2 spaced-repetition state to `learning_progress`, a one-row-per-topic
uniqueness constraint, and `conversations.study_plan_id` so a conversation can
be a tutoring session for a course. Both tables existed since the initial
schema with no writer, so there is no existing data to backfill.

Revision ID: b7d2e9a41c03
Revises: f4912cad95c6
Create Date: 2026-11-20 10:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b7d2e9a41c03'
down_revision = 'f4912cad95c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('learning_progress', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ease', sa.Float(), nullable=False, server_default='2.5'))
        batch_op.add_column(
            sa.Column('interval_days', sa.Float(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('repetitions', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(sa.Column('last_score', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('last_note', sa.Text(), nullable=True))
        batch_op.create_unique_constraint(
            'uq_learning_progress_plan_topic', ['study_plan_id', 'topic']
        )

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('study_plan_id', sa.String(length=32), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_conversations_study_plan_id'), ['study_plan_id'], unique=False
        )
        batch_op.create_foreign_key(
            batch_op.f('fk_conversations_study_plan_id_study_plans'),
            'study_plans',
            ['study_plan_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f('fk_conversations_study_plan_id_study_plans'), type_='foreignkey'
        )
        batch_op.drop_index(batch_op.f('ix_conversations_study_plan_id'))
        batch_op.drop_column('study_plan_id')

    with op.batch_alter_table('learning_progress', schema=None) as batch_op:
        batch_op.drop_constraint('uq_learning_progress_plan_topic', type_='unique')
        batch_op.drop_column('last_note')
        batch_op.drop_column('last_score')
        batch_op.drop_column('repetitions')
        batch_op.drop_column('interval_days')
        batch_op.drop_column('ease')
