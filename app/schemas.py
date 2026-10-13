from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from app.health import guidance_for, intake_missing


class HealthIntake(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    patient_name: str | None = Field(default=None, max_length=200)
    patient_dob: date | None = None
    policyholder_name: str | None = Field(default=None, max_length=200)
    relationship: Literal['self', 'spouse', 'child', 'parent', 'other'] | None = None
    contact_email: str | None = Field(default=None, max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    contact_phone: str | None = Field(default=None, max_length=20, pattern=r'^\+?[0-9 ()-]{7,20}$')
    policy_start_date: date | None = None
    policy_end_date: date | None = None
    policy_edition: str | None = Field(default=None, max_length=150)
    tpa_name: str | None = Field(default=None, max_length=200)
    claim_route: Literal['reimbursement', 'cashless'] | None = None
    admission_type: Literal['planned', 'emergency'] | None = None
    hospital_name: str | None = Field(default=None, max_length=250)
    hospital_city: str | None = Field(default=None, max_length=150)
    admission_date: date | None = None
    discharge_date: date | None = None
    treatment: str | None = Field(default=None, max_length=4000)
    intimation_status: Literal['not_notified', 'notified', 'unknown'] | None = None
    intimation_number: str | None = Field(default=None, max_length=150)
    intimation_date: date | None = None
    intake_completed: bool = False

    @model_validator(mode='after')
    def valid_dates(self):
        if self.admission_date and self.discharge_date and self.discharge_date < self.admission_date:
            raise ValueError('Discharge date cannot be before admission date')
        if self.policy_start_date and self.policy_end_date and self.policy_end_date < self.policy_start_date:
            raise ValueError('Policy end date cannot be before policy start date')
        if self.patient_dob and self.patient_dob > date.today():
            raise ValueError('Patient date of birth cannot be in the future')
        if self.patient_dob and self.admission_date and self.patient_dob > self.admission_date:
            raise ValueError('Admission date cannot be before patient date of birth')
        if self.intimation_status != 'notified' and (self.intimation_number or self.intimation_date):
            raise ValueError('Notification details require a notified status')
        return self

class ClaimCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    insurer: str = Field(min_length=1, max_length=200)
    policy_name: str = Field(default='', max_length=250)
    policy_number: str | None = Field(default=None, max_length=100)
    claim_description: str = Field(default='', max_length=10000)
    health_intake: HealthIntake | None = None

    @model_validator(mode='after')
    def valid_intake(self):
        if self.health_intake is None:
            if not self.policy_name.strip() or not self.claim_description.strip():
                raise ValueError('Policy name and claim description are required')
        else:
            if guidance_for(self.insurer) is None:
                raise ValueError('Select a supported health insurer')
            if self.health_intake.intake_completed:
                missing = intake_missing(self.policy_name, self.policy_number, self.claim_description,
                                         self.health_intake.model_dump())
                if missing:
                    raise ValueError('Complete these details: ' + ', '.join(missing))
        return self

class ClaimOut(ClaimCreate):
    guidance_version: str | None = None
    policy_source_mode: str
    policy_source_url: str | None
    id: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def intake_missing(self) -> list[str]:
        if self.health_intake is None:
            return []
        return intake_missing(self.policy_name, self.policy_number, self.claim_description,
                              self.health_intake.model_dump())

class DocumentOut(BaseModel):
    id: str
    claim_id: str
    kind: str
    document_type: str
    original_filename: str
    size_bytes: int
    uploaded_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ClaimDetail(ClaimOut):
    documents: list[DocumentOut]
