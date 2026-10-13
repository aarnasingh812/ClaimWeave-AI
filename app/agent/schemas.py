from pydantic import BaseModel, Field
from typing import Literal

DocType = Literal["hospital_bill","discharge_summary","id_proof","cancelled_cheque","investigation_report","prescription","payment_receipt","fir_mlc","claim_form","other"]

class Requirement(BaseModel):
    requirement_id: str
    name: str
    category: Literal["form","document"]
    canonical_document_type: DocType = "other"
    mandatory: bool = True
    condition: str | None = None
    reason: str
    evidence_quote: str
    source_reference: str

class PolicyExtraction(BaseModel):
    insurer: str | None = None
    policy_name: str | None = None
    policy_number: str | None = None
    holder_name: str | None = None
    requirements: list[Requirement] = Field(default_factory=list)
    facts_not_found: list[str] = Field(default_factory=list)

class ClaimClassification(BaseModel):
    claim_type: str = "unclear"
    incident_type: str = "unclear"
    hospitalization: bool | None = None
    incident_date: str | None = None
    diagnosis_or_reason: str | None = None
    missing_facts: list[str] = Field(default_factory=list)

class DocumentExtraction(BaseModel):
    fields: dict[str,str | None] = Field(default_factory=dict)
    uncertain_fields: list[str] = Field(default_factory=list)
