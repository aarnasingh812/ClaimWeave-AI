"""Owner-scoped preparation APIs. User corrections and rules never call an LLM."""
import logging
from copy import deepcopy
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import current_user
from app.db.session import get_db
from app.db.audit import audit
from app.models import Claim, ClaimDocument, User
from app.api.claims import get_claim_or_404
from app.health import intake_missing
from app.extraction import extract_changed_documents, FIELD_NAMES
from app.preparation import (BUSY_STATUSES, FORM_FIELDS, invalidate_claim, rebuild_preparation,
                             preparation_response, source_snapshot, plan_source)
from app.documents import preview_page
from app.forms import template_for, templates_for, prefilled_form
from app.submission import submission_pack, summary_pdf

router = APIRouter(prefix='/api/v1/claims', tags=['health preparation'])
logger = logging.getLogger(__name__)


def locked_claim(db, claim_id, user):
    claim = db.scalar(select(Claim).where(Claim.id == claim_id, Claim.owner_id == user.id).with_for_update())
    if claim is None:
        raise HTTPException(404, 'Claim not found')
    if claim.status in BUSY_STATUSES:
        raise HTTPException(409, 'Wait for the current analysis or review to finish')
    return claim


def check_revision(claim, revision):
    if revision != claim.revision:
        raise HTTPException(409, 'The claim changed in another request. Refresh it before saving.')


class FieldReview(BaseModel):
    value: str | None = Field(default=None, max_length=4000)
    confirmed: bool = False


class ReviewFields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    fields: dict[str, FieldReview] = Field(default_factory=dict, max_length=30)
    quality_confirmed: bool = False
    type_confirmed: bool = False
    contains_receipt: bool = False
    document_type: str | None = None


class PreparationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    condition_answers: dict[str, bool | None] | None = Field(default=None, max_length=150)
    requirement_documents: dict[str, list[str]] | None = Field(default=None, max_length=150)
    form_values: dict[str, str | None] | None = Field(default=None, max_length=40)
    template_id: str | None = None
    template_confirmed: bool | None = None
    policy_applicability_confirmed: bool | None = None
    form_values_confirmed: bool | None = None
    signatures_acknowledged: bool | None = None

    @field_validator('form_values')
    @classmethod
    def valid_values(cls, value):
        if value:
            if set(value) - set(FORM_FIELDS):
                raise ValueError('Unknown claim form field')
            if any(item is not None and len(item) > 4000 for item in value.values()):
                raise ValueError('Claim form field is too long')
        return value


@router.get('/{claim_id}/preparation')
def get_preparation(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = get_claim_or_404(db, claim_id, user)
    return preparation_response(claim)


@router.post('/{claim_id}/preparation/analyze')
def analyze_claim(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                  policy_only: bool = False):
    claim = locked_claim(db, claim_id, user)
    if not claim.health_intake:
        raise HTTPException(422, 'Complete the structured health intake before using health preparation')
    missing = intake_missing(claim.policy_name, claim.policy_number, claim.claim_description, claim.health_intake)
    if missing or not claim.health_intake.get('intake_completed'):
        raise HTTPException(422, 'Complete and confirm your health claim intake before analysis' + (': ' + ', '.join(missing) if missing else ''))
    if claim.health_intake.get('claim_route') != 'reimbursement':
        raise HTTPException(409, 'Cashless requests must be coordinated with your hospital insurance desk; use insurer guidance')
    previous_status = claim.status
    previous = deepcopy(claim.preparation or {})
    claim.status = 'running'
    audit(db, user.id, claim.id, 'preparation_started')
    db.commit()
    try:
        usage = extract_changed_documents(db, claim, kind='policy') if policy_only else extract_changed_documents(db, claim)
        prep = rebuild_preparation(db, claim, usage)
        audit(db, user.id, claim.id, 'preparation_analyzed')
        db.commit()
        return preparation_response(claim)
    except Exception as exc:
        db.rollback()
        claim = db.get(Claim, claim_id)
        claim.status = 'workflow_error'
        claim.preparation = {**previous, 'stale': True, 'approved_revision': None,
                             'analysis_error': str(exc) if isinstance(exc, ValueError) else 'Extraction failed. Successful prior batches remain cached; retry explicitly.'}
        audit(db, user.id, claim.id, 'preparation_failed')
        db.commit()
        logger.exception('Health extraction failed for claim %s', claim_id)
        raise HTTPException(503 if not settings.google_api_key else 502,
                            claim.preparation['analysis_error']) from exc


@router.post('/{claim_id}/preparation/plan')
def plan_documents(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Plan from claim details and the optional policy, before reading hospital records."""
    analyze_claim(claim_id, db, user, policy_only=True)
    claim = get_claim_or_404(db, claim_id, user)
    claim.preparation = {**claim.preparation, 'document_plan_source': plan_source(claim)}
    audit(db, user.id, claim.id, 'document_checklist_planned')
    db.commit()
    return preparation_response(claim)


@router.patch('/{claim_id}/documents/{document_id}/review')
def review_document(claim_id: str, document_id: str, payload: ReviewFields,
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.extraction import DOCUMENT_TYPES
    claim = locked_claim(db, claim_id, user)
    check_revision(claim, payload.expected_revision)
    document = db.scalar(select(ClaimDocument).where(ClaimDocument.id == document_id,
                                                    ClaimDocument.claim_id == claim_id))
    if document is None:
        raise HTTPException(404, 'Document not found')
    if set(payload.fields) - set(FIELD_NAMES):
        raise HTTPException(422, 'Unknown extracted field name')
    if payload.document_type and payload.document_type not in DOCUMENT_TYPES:
        raise HTTPException(422, 'Unknown document category')
    originals = ((document.analysis_cache or {}).get('extracted') or {}).get('fields', {})
    document.field_reviews = {key: {**item.model_dump(), 'corrected': item.value != originals.get(key, {}).get('value')}
                              for key, item in payload.fields.items()}
    if payload.document_type:
        document.document_type = payload.document_type
    prep = deepcopy(claim.preparation or {})
    reviews = prep.get('document_reviews', {})
    reviews[document.id] = {'quality_confirmed': payload.quality_confirmed, 'type_confirmed': payload.type_confirmed,
                            'contains_receipt': payload.contains_receipt}
    prep['document_reviews'] = reviews
    prep['form_values_confirmed'] = False
    claim.preparation = prep
    invalidate_claim(claim)
    db.flush()
    rebuild_preparation(db, claim)
    audit(db, user.id, claim.id, 'document_fields_reviewed')
    db.commit()
    return preparation_response(claim)


@router.patch('/{claim_id}/preparation')
def update_preparation(claim_id: str, payload: PreparationSettings,
                       db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = locked_claim(db, claim_id, user)
    check_revision(claim, payload.expected_revision)
    prep = deepcopy(claim.preparation or {})
    data = payload.model_dump(exclude_unset=True, exclude_none=True, exclude={'expected_revision'})
    if payload.condition_answers is not None:
        known = {item['requirement_id'] for item in prep.get('planned_requirements', []) if item.get('condition')}
        if set(payload.condition_answers) - known:
            raise HTTPException(422, 'Unknown conditional requirement')
    if payload.requirement_documents is not None:
        known = {item['requirement_id'] for item in prep.get('planned_requirements', [])}
        owned_documents = set(db.scalars(select(ClaimDocument.id).where(ClaimDocument.claim_id == claim_id)).all())
        if set(payload.requirement_documents) - known or any(len(ids) > 10 or set(ids) - owned_documents for ids in payload.requirement_documents.values()):
            raise HTTPException(422, 'Requirement links must refer to this claim and its own documents')
    if payload.template_id is not None and not template_for(claim.insurer, payload.template_id):
        raise HTTPException(422, 'Template does not belong to the selected insurer')
    if payload.template_id is not None and payload.template_id != prep.get('template_id'):
        prep['template_confirmed'] = False
    prep.update(data)
    selected = template_for(claim.insurer, prep.get('template_id'), claim.policy_name)
    if prep.get('template_confirmed'):
        prep['template_confirmed_hash'] = selected['sha256'] if selected else None
    claim.preparation = prep
    invalidate_claim(claim)
    rebuild_preparation(db, claim)
    audit(db, user.id, claim.id, 'preparation_details_updated')
    db.commit()
    return preparation_response(claim)


class PreparationApproval(BaseModel):
    expected_revision: int = Field(ge=0)
    approved: bool


@router.post('/{claim_id}/preparation/approve')
def approve_preparation(claim_id: str, payload: PreparationApproval,
                        db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = locked_claim(db, claim_id, user)
    check_revision(claim, payload.expected_revision)
    prep = rebuild_preparation(db, claim)
    if payload.approved and not prep['validation']['passed']:
        db.rollback()
        raise HTTPException(409, 'Resolve validation issues and confirm all required fields and conditions before approval')
    if payload.approved:
        prep['approved_revision'] = claim.revision
        prep['status'] = 'package_ready'
        prep['package'] = {'status': 'prepared_for_manual_submission', 'revision': claim.revision,
                           'note': 'Not submitted. Complete signatures and hospital/doctor sections.'}
        claim.status = 'package_ready'
    else:
        prep['approved_revision'] = None
        prep.pop('package', None)
        prep['status'] = 'rejected'
        claim.status = 'rejected'
    claim.preparation = prep
    audit(db, user.id, claim.id, 'preparation_approved' if payload.approved else 'preparation_rejected')
    db.commit()
    return preparation_response(claim)


@router.get('/{claim_id}/documents/{document_id}/preview')
def document_preview(claim_id: str, document_id: str, page: int = 1,
                     db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_claim_or_404(db, claim_id, user)
    document = db.scalar(select(ClaimDocument).where(ClaimDocument.id == document_id,
                                                    ClaimDocument.claim_id == claim_id))
    if document is None:
        raise HTTPException(404, 'Document not found')
    try:
        image = preview_page(settings.storage_dir / document.storage_key, page)
    except Exception:
        raise HTTPException(422, 'Could not preview that page. Check the page number or replace the unreadable file.')
    return Response(image, media_type='image/png', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/{claim_id}/preparation/form')
def download_form(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = get_claim_or_404(db, claim_id, user)
    prep = claim.preparation or {}
    template = template_for(claim.insurer, prep.get('template_id'), claim.policy_name)
    if template is None:
        raise HTTPException(409, 'Select an installed insurer template first')
    try:
        data = prefilled_form(template, prep.get('form_draft', {}))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return Response(data, media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename="claim-form-draft.pdf"', 'Cache-Control': 'no-store'})


@router.get('/{claim_id}/preparation/pack')
def download_submission_pack(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = locked_claim(db, claim_id, user)
    previous_approval = (claim.preparation or {}).get('approved_revision')
    prep = rebuild_preparation(db, claim)
    if previous_approval != claim.revision or prep.get('approved_revision') != claim.revision or claim.status != 'package_ready':
        db.rollback()
        raise HTTPException(409, 'Review and approve the current revision before downloading a submission pack')
    documents = db.scalars(select(ClaimDocument).where(ClaimDocument.claim_id == claim_id)
                           .order_by(ClaimDocument.uploaded_at, ClaimDocument.id)).all()
    try:
        data = submission_pack(claim, documents)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    audit(db, user.id, claim.id, 'submission_pack_exported')
    db.commit()
    return Response(data, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="claimweave-{claim_id}-submission.zip"', 'Cache-Control': 'no-store'})
