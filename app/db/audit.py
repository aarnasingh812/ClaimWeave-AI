from sqlalchemy.orm import Session
from app.models import AuditEvent

def audit(db: Session, owner_id: str, claim_id: str | None, action: str):
    db.add(AuditEvent(owner_id=owner_id, claim_id=claim_id, action=action))
