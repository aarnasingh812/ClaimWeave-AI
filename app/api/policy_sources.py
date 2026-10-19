"""Policy discovery and explicit user confirmation, owner scoped."""
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.api.claims import get_claim_or_404
from app.core.security import current_user
from app.core.config import settings
from app.db.session import get_db
from app.db.audit import audit
from app.models import User, Claim, ClaimDocument
from app.agent.policy_discovery import discover, download_official_pdf, domains_for
from app.preparation import EDITABLE_STATUSES, invalidate_claim
import hashlib

router = APIRouter(prefix='/api/v1/claims', tags=['policy sources'])

class SourceSelection(BaseModel):
    url: HttpUrl
    confirmed_policy_match: bool

@router.get('/{claim_id}/policy/support')
def policy_search_support(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = get_claim_or_404(db, claim_id, user)
    domains = domains_for(claim.insurer)
    return {'supported_insurer': bool(domains), 'official_domains': domains}

@router.get('/{claim_id}/policy/discover')
def search_official_policies(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = get_claim_or_404(db, claim_id, user)
    if claim.status not in EDITABLE_STATUSES:
        raise HTTPException(409, 'Cannot change policy after workflow starts')
    domains = domains_for(claim.insurer)
    return {'supported_insurer': bool(domains), 'official_domains': domains,
            'candidates': discover(claim.insurer, claim.policy_name) if domains else [],
            'message': 'Candidates are not proof of coverage. Verify product, edition, dates and endorsements before selecting.'}

@router.post('/{claim_id}/policy/confirm')
def confirm_official_policy(claim_id: str, selection: SourceSelection,
                            db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = db.scalar(select(Claim).where(Claim.id == claim_id, Claim.owner_id == user.id).with_for_update())
    if claim is None:
        raise HTTPException(404, 'Claim not found')
    recoverable = bool(claim.health_intake) or claim.status in ('workflow_error', 'policy_mismatch')
    if claim.status not in EDITABLE_STATUSES:
        raise HTTPException(409, 'Workflow already started')
    if not selection.confirmed_policy_match:
        raise HTTPException(422, 'User confirmation is required')
    existing = db.scalars(select(ClaimDocument).where(
        ClaimDocument.claim_id == claim_id, ClaimDocument.kind == 'policy')).all()
    if existing and not recoverable:
        raise HTTPException(409, 'A policy is already attached')
    # A user-provided URL must still pass the official domain allowlist.
    data = download_official_pdf(str(selection.url), claim.insurer)
    folder = settings.storage_dir / claim_id
    folder.mkdir(parents=True, exist_ok=True)
    key = f'{claim_id}/{uuid.uuid4().hex}.pdf'
    path = settings.storage_dir / key
    replaced_keys = [old.storage_key for old in existing] if recoverable else []
    try:
        with path.open('xb') as f:
            f.write(data)
        doc = ClaimDocument(claim_id=claim_id, kind='policy', document_type='other',
                            original_filename='official-policy.pdf', storage_key=key, size_bytes=len(data),
                            content_hash=hashlib.sha256(data).hexdigest())
        for old in existing:
            db.delete(old)
        db.add(doc)
        claim.policy_source_mode = 'online'
        claim.policy_source_url = str(selection.url)
        if claim.preparation:
            claim.preparation = {**claim.preparation, 'condition_answers': {}, 'requirement_documents': {}, 'policy_applicability_confirmed': False}
        invalidate_claim(claim)
        audit(db, user.id, claim_id, 'online_policy_confirmed')
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    for old_key in replaced_keys:
        try:
            (settings.storage_dir / old_key).unlink(missing_ok=True)
        except OSError:
            pass
    return {'status': 'attached', 'document_id': doc.id, 'source_url': claim.policy_source_url,
            'warning': 'Source identity and applicability still require verification during workflow.'}
