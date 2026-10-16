from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.core.security import current_user
from app.db.audit import audit
from app.db.checkpoints import open_checkpointer
from app.db.session import get_db
from app.models import Claim, ClaimDocument, User
from app.schemas import ClaimCreate, ClaimDetail, ClaimOut, DocumentOut
from app.storage import save_document
from app.core.config import settings
from app.health import guidance_for
from app.preparation import BUSY_STATUSES, EDITABLE_STATUSES, invalidate_claim

router = APIRouter(prefix='/api/v1/claims', tags=['claims'])

def get_claim_or_404(db: Session, claim_id: str, user: User) -> Claim:
    claim = db.scalar(select(Claim).where(Claim.id == claim_id, Claim.owner_id == user.id))
    if claim is None:
        raise HTTPException(404, 'Claim not found')
    return claim

@router.post('', response_model=ClaimOut, status_code=201)
def create_claim(payload: ClaimCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guidance = guidance_for(payload.insurer) if payload.health_intake else None
    claim = Claim(**payload.model_dump(mode='json'), owner_id=user.id,
                  guidance_version=guidance['version'] if guidance else None)
    db.add(claim)
    db.flush()
    audit(db, user.id, claim.id, 'claim_created')
    db.commit()
    db.refresh(claim)
    return claim

@router.patch('/{claim_id}', response_model=ClaimOut)
def update_claim_intake(claim_id: str, payload: ClaimCreate, db: Session = Depends(get_db),
                        user: User = Depends(current_user)):
    claim = db.scalar(select(Claim).where(
        Claim.id == claim_id, Claim.owner_id == user.id).with_for_update())
    if claim is None:
        raise HTTPException(404, 'Claim not found')
    if claim.status not in EDITABLE_STATUSES:
        raise HTTPException(409, 'Wait for the current analysis or review to finish')
    if payload.health_intake is None:
        raise HTTPException(422, 'Structured health intake is required')
    if claim.documents and (payload.insurer != claim.insurer
                            or bool(claim.policy_name) and payload.policy_name != claim.policy_name
                            or bool(claim.policy_number) and payload.policy_number != claim.policy_number):
        raise HTTPException(409, 'Remove attached documents before changing the insurer or policy identity')
    for field, value in payload.model_dump(mode='json').items():
        setattr(claim, field, value)
    claim.guidance_version = guidance_for(payload.insurer)['version']
    if claim.preparation:
        # Regenerate intake-backed values; preserve separately entered bank/contact details.
        intake_fields = {'patient_name', 'policyholder_name', 'policy_number', 'hospital_name',
                         'hospital_city', 'admission_date', 'discharge_date', 'date_of_birth',
                         'gender', 'relationship', 'diagnosis', 'policy_start_date', 'policy_end_date'}
        values = {key: value for key, value in claim.preparation.get('form_values', {}).items()
                  if key not in intake_fields}
        claim.preparation = {**claim.preparation, 'form_values': values,
                             'form_values_confirmed': False, 'policy_applicability_confirmed': False}
    invalidate_claim(claim)
    audit(db, user.id, claim_id, 'claim_intake_updated')
    db.commit()
    db.refresh(claim)
    return claim

@router.get('', response_model=list[ClaimOut])
def list_claims(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(Claim).where(Claim.owner_id == user.id).order_by(Claim.created_at.desc())).all()

@router.get('/{claim_id}', response_model=ClaimDetail)
def get_claim(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = db.scalar(select(Claim).options(selectinload(Claim.documents)).where(
        Claim.id == claim_id, Claim.owner_id == user.id))
    if claim is None:
        raise HTTPException(404, 'Claim not found')
    return claim

@router.delete('/{claim_id}', status_code=204)
def delete_claim(claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    claim = db.scalar(select(Claim).where(
        Claim.id == claim_id, Claim.owner_id == user.id).with_for_update())
    if claim is None:
        raise HTTPException(404, 'Claim not found')
    if claim.status in BUSY_STATUSES:
        raise HTTPException(409, 'Wait for the running analysis to finish before deleting this claim')
    keys = [doc.storage_key for doc in claim.documents]
    if claim.status != 'draft' and not claim.health_intake:
        with open_checkpointer() as saver:
            saver.delete_thread(f'{user.id}:{claim_id}')
    audit(db, user.id, claim_id, 'claim_deleted')
    db.delete(claim)
    db.commit()
    for key in keys:
        try:
            (settings.storage_dir / key).unlink(missing_ok=True)
        except OSError:
            pass
    return Response(status_code=204)

@router.delete('/{claim_id}/documents/{document_id}', status_code=204)
def delete_document(claim_id: str, document_id: str, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    claim = db.scalar(select(Claim).where(
        Claim.id == claim_id, Claim.owner_id == user.id).with_for_update())
    if claim is None:
        raise HTTPException(404, 'Claim not found')
    doc = db.scalar(select(ClaimDocument).where(
        ClaimDocument.id == document_id, ClaimDocument.claim_id == claim_id))
    if doc is None:
        raise HTTPException(404, 'Document not found')
    if claim.status not in EDITABLE_STATUSES:
        raise HTTPException(409, 'Wait for the current analysis or review to finish')
    key = doc.storage_key
    if doc.kind == 'policy':
        claim.policy_source_mode = 'upload'
        claim.policy_source_url = None
        if claim.preparation:
            claim.preparation = {**claim.preparation, 'condition_answers': {}, 'requirement_documents': {}, 'policy_applicability_confirmed': False}
    db.delete(doc)
    invalidate_claim(claim)
    audit(db, user.id, claim_id, 'document_deleted')
    db.commit()
    try:
        (settings.storage_dir / key).unlink(missing_ok=True)
    except OSError:
        pass
    return Response(status_code=204)

@router.post('/{claim_id}/documents', response_model=DocumentOut, status_code=201)
async def upload_document(claim_id: str, file: UploadFile = File(...), kind: str = Form(...),
                          document_type: str = Form('other'), db: Session = Depends(get_db),
                          user: User = Depends(current_user)):
    claim = db.scalar(select(Claim).where(Claim.id == claim_id, Claim.owner_id == user.id).with_for_update())
    if claim is None:
        raise HTTPException(404, 'Claim not found')
    recoverable_statuses = {'workflow_error', 'policy_mismatch'}
    if claim.status not in EDITABLE_STATUSES:
        raise HTTPException(409, 'Wait for the current analysis or review to finish')
    if kind not in {'policy', 'supporting'}:
        raise HTTPException(422, "kind must be 'policy' or 'supporting'")
    existing_policies = db.scalars(select(ClaimDocument).where(
        ClaimDocument.claim_id == claim_id, ClaimDocument.kind == 'policy')).all() if kind == 'policy' else []
    can_replace_policy = bool(claim.health_intake) or claim.status in recoverable_statuses
    if existing_policies and not can_replace_policy:
        raise HTTPException(409, 'One policy PDF per claim; create a new claim to change policies')
    valid_types = {'hospital_bill','discharge_summary','id_proof','cancelled_cheque',
                   'investigation_report','prescription','payment_receipt','fir_mlc','claim_form','implant_invoice',
                   'doctor_certificate','indoor_case_papers','pharmacy_bill','operation_notes','hospital_registration','other','auto'}
    if document_type not in valid_types:
        raise HTTPException(422, 'Unknown document type')
    key, size, content_type, content_hash = await save_document(file, claim_id)
    doc = ClaimDocument(claim_id=claim_id, kind=kind, document_type=document_type,
        original_filename=Path(file.filename.replace(chr(92), '/')).name[:255],
                        storage_key=key, size_bytes=size, content_type=content_type, content_hash=content_hash)
    replaced_keys = [old.storage_key for old in existing_policies] if can_replace_policy else []
    try:
        for old in existing_policies:
            db.delete(old)
        db.add(doc)
        if kind == 'policy':
            claim.policy_source_mode = 'upload'
            claim.policy_source_url = None
            if claim.preparation:
                claim.preparation = {**claim.preparation, 'condition_answers': {}, 'requirement_documents': {}, 'policy_applicability_confirmed': False}
        invalidate_claim(claim)
        db.flush()
        audit(db, user.id, claim_id, 'document_uploaded')
        db.commit()
        db.refresh(doc)
    except Exception:
        db.rollback()
        (settings.storage_dir / key).unlink(missing_ok=True)
        raise
    for old_key in replaced_keys:
        try:
            (settings.storage_dir / old_key).unlink(missing_ok=True)
        except OSError:
            pass
    return doc
