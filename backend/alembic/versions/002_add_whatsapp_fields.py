"""Add WhatsApp fields

Revision ID: 002_add_whatsapp_fields
Revises: 001_initial
Create Date: 2026-05-11

"""
from alembic import op
import sqlalchemy as sa


revision = '002_add_whatsapp_fields'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('businesses', sa.Column('whatsapp_access_token', sa.String(512), nullable=True))
    op.add_column('businesses', sa.Column('whatsapp_business_account_id', sa.String(255), nullable=True))
    op.add_column('businesses', sa.Column('whatsapp_phone_number_id', sa.String(255), nullable=True))
    op.add_column('businesses', sa.Column('whatsapp_verify_token', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('businesses', 'whatsapp_verify_token')
    op.drop_column('businesses', 'whatsapp_phone_number_id')
    op.drop_column('businesses', 'whatsapp_business_account_id')
    op.drop_column('businesses', 'whatsapp_access_token')
