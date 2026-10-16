from alembic import op
import sqlalchemy as sa

revision = '0005_preparation'
down_revision = '0004_health_intake'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('claims', sa.Column('preparation', sa.JSON(), nullable=True))
    op.add_column('claims', sa.Column('revision', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('claim_documents', sa.Column('content_hash', sa.String(64), nullable=True))
    op.add_column('claim_documents', sa.Column('analysis_cache', sa.JSON(), nullable=True))
    op.add_column('claim_documents', sa.Column('field_reviews', sa.JSON(), nullable=True))
    op.create_index('ix_claim_documents_content_hash', 'claim_documents', ['content_hash'])


def downgrade():
    op.drop_index('ix_claim_documents_content_hash', table_name='claim_documents')
    for column in ('field_reviews', 'analysis_cache', 'content_hash'):
        op.drop_column('claim_documents', column)
    op.drop_column('claims', 'revision')
    op.drop_column('claims', 'preparation')
