import uuid
from datetime import datetime, timezone
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

def uid() -> str:
    return str(uuid.uuid4())

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Claim(Base):
    __tablename__ = 'claims'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    # Nullable only to preserve old Phase 3 records during migration.
    # Unowned legacy claims are deliberately inaccessible via the API.
    owner_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True, nullable=True)
    insurer: Mapped[str] = mapped_column(String(200))
    policy_name: Mapped[str] = mapped_column(String(250))
    policy_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claim_description: Mapped[str] = mapped_column(Text)
    health_intake: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    guidance_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    preparation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    policy_source_mode: Mapped[str] = mapped_column(String(20), default='upload')
    policy_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default='draft')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    documents: Mapped[list['ClaimDocument']] = relationship(back_populates='claim', cascade='all, delete-orphan')

class ClaimDocument(Base):
    __tablename__ = 'claim_documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    claim_id: Mapped[str] = mapped_column(ForeignKey('claims.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    document_type: Mapped[str] = mapped_column(String(80), default='other')
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(100), default='application/pdf')
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    analysis_cache: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    field_reviews: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claim: Mapped[Claim] = relationship(back_populates='documents')

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
