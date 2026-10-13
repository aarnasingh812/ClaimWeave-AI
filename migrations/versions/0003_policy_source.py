from alembic import op
import sqlalchemy as sa
revision = '0003_policy_source'
down_revision = '0002_auth_audit'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('claims', sa.Column('policy_source_mode', sa.String(20), nullable=False, server_default='upload'))
    op.add_column('claims', sa.Column('policy_source_url', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('claims', 'policy_source_url')
    op.drop_column('claims', 'policy_source_mode')
