from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("insurer", sa.String(200), nullable=False),
        sa.Column("policy_name", sa.String(250), nullable=False),
        sa.Column("policy_number", sa.String(100), nullable=True),
        sa.Column("claim_description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "claim_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_claim_documents_claim_id", "claim_documents", ["claim_id"])

def downgrade():
    op.drop_index("ix_claim_documents_claim_id", table_name="claim_documents")
    op.drop_table("claim_documents")
    op.drop_table("claims")
