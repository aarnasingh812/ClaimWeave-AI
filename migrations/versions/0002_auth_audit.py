from alembic import op
import sqlalchemy as sa

revision = '0002_auth_audit'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(254), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.add_column('claims', sa.Column('owner_id', sa.String(36), nullable=True))
    op.create_foreign_key('fk_claims_owner_id_users', 'claims', 'users', ['owner_id'], ['id'])
    op.create_index('ix_claims_owner_id', 'claims', ['owner_id'])
    op.create_table('audit_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('claim_id', sa.String(36), nullable=True),
        sa.Column('action', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_audit_events_owner_id', 'audit_events', ['owner_id'])
    op.create_index('ix_audit_events_claim_id', 'audit_events', ['claim_id'])

def downgrade():
    op.drop_index('ix_audit_events_claim_id', table_name='audit_events')
    op.drop_index('ix_audit_events_owner_id', table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index('ix_claims_owner_id', table_name='claims')
    op.drop_constraint('fk_claims_owner_id_users', 'claims', type_='foreignkey')
    op.drop_column('claims', 'owner_id')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_table('users')
