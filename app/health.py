"""Versioned, source-reviewed guidance; never a determination of policy applicability."""
import json
import re
from pathlib import Path

INSURERS = json.loads(Path(__file__).with_name('health_guidance.json').read_text(encoding='utf-8'))


def guidance_for(insurer: str):
    normalize = lambda value: re.sub(r'[^a-z0-9]', '', value.lower())
    key = normalize(insurer)
    return next((item for item in INSURERS if key in {normalize(alias) for alias in item['aliases']}), None)


def intake_missing(policy_name: str, policy_number: str | None, description: str, intake: dict) -> list[str]:
    missing = []
    for label, value in [('Policy name', policy_name), ('Policy number', policy_number),
                         ('Treatment description', description)]:
        if not value or not value.strip():
            missing.append(label)
    for field, label in [('patient_name', 'Patient name'), ('policyholder_name', 'Policyholder name'),
                         ('relationship', 'Relationship to policyholder'), ('claim_route', 'Claim route'),
                         ('admission_type', 'Admission type'), ('hospital_name', 'Hospital name'),
                         ('hospital_city', 'Hospital city'), ('admission_date', 'Admission date'),
                         ('intimation_status', 'Insurer notification status')]:
        if not intake.get(field):
            missing.append(label)
    if intake.get('claim_route') == 'reimbursement' and not intake.get('discharge_date'):
        missing.append('Discharge date')
    return missing
