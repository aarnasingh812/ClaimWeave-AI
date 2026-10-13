"""Persist structured health intake without altering existing claims."""
from alembic import op
import sqlalchemy as sa

revision = '0004_health_intake'
down_revision = '0003_policy_source'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('claims', sa.Column('health_intake', sa.JSON(), nullable=True))
    op.add_column('claims', sa.Column('guidance_version', sa.String(40), nullable=True))


def downgrade():
    op.drop_column('claims', 'guidance_version')
    op.drop_column('claims', 'health_intake')
