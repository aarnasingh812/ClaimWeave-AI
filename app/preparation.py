"""Deterministic health claim preparation, review and approval invalidation."""
import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from app.models import ClaimDocument
from app.health import guidance_for
from app.extraction import FIELD_NAMES
from app.agent.workflow import verify_policy

BUSY_STATUSES = {'running', 'reviewing'}
EDITABLE_STATUSES = {'draft', 'provisional_ready', 'workflow_error', 'policy_mismatch', 'needs_attention',
                     'awaiting_review', 'package_ready', 'approved', 'completed', 'rejected'}
FORM_FIELDS = ('patient_name', 'date_of_birth', 'gender', 'policyholder_name', 'relationship', 'policy_number',
               'policy_start_date', 'policy_end_date', 'contact_email', 'contact_phone', 'address', 'city', 'state',
               'pincode', 'hospital_name', 'hospital_city', 'admission_date', 'discharge_date', 'diagnosis',
               'claimed_amount', 'bank_account_holder', 'bank_account_number', 'bank_name', 'bank_branch',
               'ifsc_code', 'intimation_number', 'occupation', 'customer_id', 'pan')
REQUIRED_FORM_FIELDS = ('patient_name', 'policyholder_name', 'policy_number', 'hospital_name', 'admission_date',
                        'discharge_date', 'claimed_amount', 'bank_account_holder', 'bank_account_number',
                        'ifsc_code', 'contact_phone', 'contact_email', 'address', 'city', 'state', 'pincode')
ESSENTIAL_DOCUMENT_FIELDS = {'hospital_bill': ['patient_name', 'bill_total'],
                             'discharge_summary': ['patient_name', 'admission_date', 'discharge_date'],
                             'payment_receipt': ['payment_amount'], 'cancelled_cheque': ['bank_account_number', 'ifsc_code'],
                             'doctor_certificate': ['patient_name'], 'indoor_case_papers': ['patient_name'],
                             'pharmacy_bill': ['bill_total']}


def invalidate_claim(claim):
    claim.revision = (claim.revision or 0) + 1
    prep = deepcopy(claim.preparation or {})
    prep.update({'stale': True, 'approved_revision': None})
    prep.pop('package', None)
    prep.pop('chat_cache', None)
    claim.preparation = prep
    claim.status = 'draft'


def value_key(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())


def money(value):
    try:
        amount = Decimal(str(value).replace(',', '').replace('INR', '').replace('Rs.', '').strip())
        return amount if amount.is_finite() else None
    except (InvalidOperation, TypeError):
        return None


def requirement(identifier, name, document_type, sources, mandatory=True, condition=None, origin='insurer_guidance'):
    return {'requirement_id': identifier, 'name': name, 'category': 'document',
            'canonical_document_type': document_type, 'mandatory': mandatory, 'condition': condition,
            'reason': 'Published insurer document guidance; check your exact policy and claim circumstances.',
            'origin': origin, 'source_reference': ', '.join(sources), 'source_urls': sources,
            'evidence_quote': '', 'needs_user_confirmation': bool(condition)}


def insurer_requirements(claim):
    guide = guidance_for(claim.insurer)
    if not guide:
        return []
    sources = [source['url'] for source in guide['sources'] if source['id'] in ('checklist', 'claims')]
    if not sources:
        sources = [guide['sources'][0]['url']]
    base = [('hospital_bill', 'Itemized final hospital bill'), ('payment_receipt', 'Hospital payment receipts'),
            ('discharge_summary', 'Discharge summary'), ('cancelled_cheque', 'Bank payment proof')]
    conditional = [('prescription', 'Prescriptions / consultation papers', 'Were medicines or prescribed consultations claimed?'),
                   ('pharmacy_bill', 'Pharmacy bills', 'Are separate pharmacy expenses included in this claim?'),
                   ('investigation_report', 'Investigation reports', 'Were diagnostic tests performed or claimed?'),
                   ('fir_mlc', 'Accident / MLC / FIR records', 'Was this hospitalization caused by an accident?'),
                   ('implant_invoice', 'Implant invoices and stickers', 'Was an implant used during treatment?'),
                   ('id_proof', 'KYC / identity documents', 'Does your claim or policy require KYC or identity proof? Check the insurer guidance and form.')]
    if guide['id'] == 'care-health':
        # Care guidance makes identity proof a general reimbursement item.
        base.append(('id_proof', 'Policyholder identity proof'))
        base.append(('indoor_case_papers', 'Indoor case papers'))
        conditional = [item for item in conditional if item[0] != 'id_proof']
    if guide['id'] == 'star-health':
        base.append(('doctor_certificate', "Treating doctor's certificate"))
    if guide['id'] == 'hdfc-ergo':
        conditional.append(('hospital_registration', 'Hospital registration details', 'Does your applicable policy or claim form request the hospital registration certificate?'))
    return [requirement(f"guide-{guide['id']}-{kind}", name, kind, sources) for kind, name in base] + [
        requirement(f"guide-{guide['id']}-{kind}", name, kind, sources, condition=condition)
        for kind, name, condition in conditional]


def effective_document(document, prep):
    cache = document.analysis_cache or {}
    extraction = cache.get('extracted') or {}
    fields = deepcopy(extraction.get('fields') or {})
    for name, review in (document.field_reviews or {}).items():
        fields[name] = {**fields.get(name, {}), 'value': review.get('value'), 'confirmed': review.get('confirmed', False),
                        'corrected': review.get('corrected', False), 'review_source': 'user_review'}
    metadata = (prep.get('document_reviews') or {}).get(document.id, {})
    kind = document.document_type if document.document_type not in ('auto', 'other') else extraction.get('suggested_type', 'other')
    return {'document_id': document.id, 'filename': document.original_filename, 'kind': document.kind,
            'document_type': kind, 'declared_type': document.document_type,
            'suggested_type': extraction.get('suggested_type', 'other'), 'fields': fields,
            'page_count': cache.get('page_count', 0), 'pages': [{key: page.get(key) for key in ('page', 'method', 'confidence', 'warnings')}
                                                           for page in cache.get('pages', [])],
            'errors': cache.get('errors', []), 'warnings': cache.get('warnings', []) + extraction.get('warnings', []),
            'extracted': cache.get('extracted') is not None, 'quality_confirmed': metadata.get('quality_confirmed', False),
            'type_confirmed': metadata.get('type_confirmed', False), 'contains_receipt': metadata.get('contains_receipt', False),
            'hash': document.content_hash}


def source_snapshot(claim, documents):
    data = {'revision': claim.revision, 'insurer': claim.insurer, 'policy_name': claim.policy_name,
            'policy_number': claim.policy_number, 'intake': claim.health_intake,
            'documents': [(doc.id, doc.content_hash, doc.document_type, doc.field_reviews) for doc in documents]}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def plan_source(claim):
    """Supporting uploads do not invalidate a plan; policy or intake edits do."""
    data = {'insurer': claim.insurer, 'policy_name': claim.policy_name, 'policy_number': claim.policy_number,
            'description': claim.claim_description, 'intake': claim.health_intake,
            'policies': sorted((doc.id, doc.content_hash) for doc in claim.documents if doc.kind == 'policy')}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def rebuild_preparation(db, claim, usage=None):
    from app.forms import templates_for, template_for, form_status
    documents = db.scalars(select(ClaimDocument).where(ClaimDocument.claim_id == claim.id)
                           .order_by(ClaimDocument.uploaded_at, ClaimDocument.id)).all()
    previous = deepcopy(claim.preparation or {})
    prep = {key: previous.get(key, {}) for key in ('condition_answers', 'document_reviews', 'form_values', 'requirement_documents')}
    for key in ('policy_applicability_confirmed', 'template_confirmed', 'form_values_confirmed', 'signatures_acknowledged'):
        prep[key] = previous.get(key, False)
    prep['template_confirmed_hash'] = previous.get('template_confirmed_hash')
    prep['template_id'] = previous.get('template_id')
    prep['document_plan_source'] = previous.get('document_plan_source')
    prep['usage'] = usage or previous.get('usage') or {'requests': 0, 'cached_documents': 0}
    prep['last_action_requests'] = usage.get('requests', 0) if usage else 0
    extracted = [effective_document(document, prep) for document in documents]
    policies = [document for document in documents if document.kind == 'policy']
    policy = ((policies[0].analysis_cache or {}).get('extracted') or {}).get('policy') if policies else None
    verification = verify_policy({'insurer': claim.insurer, 'policy_name': claim.policy_name,
                                  'policy_source_mode': claim.policy_source_mode, 'policy_extraction': policy}) if policy else {
        'policy_verified': False, 'warnings': ['Attach and analyze your actual policy before final approval.']}
    requirements = insurer_requirements(claim)
    for index, item in enumerate((policy or {}).get('requirements', []) if verification['policy_verified'] else []):
        requirements.append({**item, 'requirement_id': f'policy-{index}-{item.get("requirement_id", "item")}',
                             'origin': 'policy', 'source_urls': [], 'needs_user_confirmation': bool(item.get('condition'))})
    guide = guidance_for(claim.insurer)
    suggestions = {key: value for key, value in (claim.health_intake or {}).items() if key in FORM_FIELDS and value}
    suggestions.update({'policy_number': claim.policy_number, 'date_of_birth': (claim.health_intake or {}).get('patient_dob'),
                        'diagnosis': claim.claim_description})
    supporting = [item for item in extracted if item['kind'] == 'supporting']
    for item in supporting:
        for key in ('bank_account_holder', 'bank_account_number', 'ifsc_code'):
            field = item['fields'].get(key)
            if field and field.get('confirmed') and field.get('value'):
                suggestions.setdefault(key, field['value'])
    bills = [money(item['fields'].get('bill_total', {}).get('value')) for item in supporting
             if item['document_type'] == 'hospital_bill' and item['fields'].get('bill_total', {}).get('confirmed')]
    if bills and all(value is not None for value in bills):
        suggestions['claimed_amount'] = str(sum(bills, Decimal('0')))
    form_values = {**suggestions, **{key: value for key, value in prep['form_values'].items() if value}}
    errors, warnings, issues = [], list(verification['warnings']), []

    def issue(code, message, document_id=None, severity='error'):
        issues.append({'code': code, 'message': message, 'document_id': document_id, 'severity': severity})
        (errors if severity == 'error' else warnings).append(message)

    if not verification['policy_verified']:
        issue('policy_identity', 'Policy identity has not been verified against the selected insurer and product.')
    if policy and not policy.get('requirements'):
        issue('policy_requirements', 'No source-grounded claim requirements were found in the policy. Attach complete readable wording, including the claims section.')
    if policy and policy.get('policy_number') and claim.policy_number and value_key(policy['policy_number']) != value_key(claim.policy_number):
        issue('policy_number_mismatch', 'The policy number extracted from the policy does not match the claim. Attach the correct schedule or correct the claim identity.')
    if not prep['policy_applicability_confirmed']:
        issue('policy_applicability', 'Confirm the policy schedule, edition, insured patient, dates and endorsements apply to this claim.')
    if not supporting:
        issue('no_documents', 'Upload your hospital documents before review.')
    hashes, bill_numbers = {}, {}
    valid_types = set()
    for item in extracted:
        if item['hash'] and item['hash'] in hashes:
            issue('duplicate_file', f"{item['filename']}: duplicate of {hashes[item['hash']]}; remove the duplicate.", item['document_id'])
        hashes[item['hash']] = item['filename']
        for error in item['errors']:
            issue('unreadable', f"{item['filename']}: {error}", item['document_id'])
        if not item['extracted']:
            issue('not_extracted', f"{item['filename']}: analyze this new or changed document.", item['document_id'])
        if item['warnings'] and not item['quality_confirmed']:
            issue('quality_review', f"{item['filename']}: review the page quality warnings and confirm legibility.", item['document_id'])
        if item['kind'] == 'policy':
            continue
        if not item['type_confirmed']:
            issue('document_type_review', f"{item['filename']}: confirm the actual document category.", item['document_id'])
        if item['declared_type'] not in ('auto', 'other', item['suggested_type']) and not item['type_confirmed']:
            issue('category_mismatch', f"{item['filename']}: uploaded category differs from extracted category.", item['document_id'])
        for key in ESSENTIAL_DOCUMENT_FIELDS.get(item['document_type'], []):
            if not item['fields'].get(key, {}).get('value'):
                issue('missing_field', f"{item['filename']}: enter and confirm {key.replace('_', ' ')} from the original.", item['document_id'])
        for key, field in item['fields'].items():
            if field.get('value') and not field.get('confirmed'):
                issue('field_review', f"{item['filename']}: confirm {key.replace('_', ' ')} against its source page.", item['document_id'])
            expected = form_values.get('date_of_birth' if key == 'date_of_birth' else key)
            if key in ('patient_name', 'policy_number', 'admission_date', 'discharge_date', 'date_of_birth', 'bank_account_number', 'ifsc_code') and expected and field.get('value') and value_key(expected) != value_key(field['value']):
                issue('field_mismatch', f"{item['filename']}: {key.replace('_', ' ')} differs from the claim details. Correct the source review or claim details.", item['document_id'])
        bill_number = item['fields'].get('bill_number', {}).get('value')
        if bill_number:
            bill_key = (value_key(item['fields'].get('hospital_name', {}).get('value') or form_values.get('hospital_name')), value_key(bill_number))
            if bill_key in bill_numbers and item['document_type'] == 'hospital_bill':
                issue('duplicate_bill', f"{item['filename']}: bill number already appears in {bill_numbers[bill_key]}.", item['document_id'])
            if item['document_type'] == 'hospital_bill':
                bill_numbers[bill_key] = item['filename']
        if not item['errors'] and item['extracted'] and item['type_confirmed']:
            valid_types.add(item['document_type'])
            if item['contains_receipt'] and item['fields'].get('payment_amount', {}).get('value'):
                valid_types.add('payment_receipt')
    missing, present, pending = [], [], []
    for req in requirements:
        answer = prep['condition_answers'].get(req['requirement_id'])
        if req.get('condition') and answer not in (True, False):
            pending.append(req['name'])
            req['status'] = 'needs_confirmation'
        elif req.get('condition') and answer is False:
            req['status'] = 'not_applicable'
        elif req['category'] == 'form':
            req['status'] = 'manual_completion'
            warnings.append(req['name'] + ': complete and sign the applicable official form before submission.')
        elif req['canonical_document_type'] != 'other' and req['canonical_document_type'] in valid_types:
            present.append(req['name'])
            req['status'] = 'present'
        elif req['canonical_document_type'] == 'other' and any(item['document_id'] in prep['requirement_documents'].get(req['requirement_id'], [])
            and item['type_confirmed'] and item['extracted'] and not item['errors'] for item in supporting):
            present.append(req['name'])
            req['status'] = 'present'
        elif req.get('mandatory', True):
            missing.append(req['name'])
            req['status'] = 'missing'
        else:
            req['status'] = 'suggested'
    if missing:
        issue('missing_documents', 'Missing required documents: ' + ', '.join(missing))
    if pending:
        issue('unresolved_conditions', 'Answer the conditional checklist questions: ' + ', '.join(pending))
    for key in REQUIRED_FORM_FIELDS:
        if not form_values.get(key):
            issue('form_field', 'Complete the claim form field: ' + key.replace('_', ' '))
    intake_values = {**(claim.health_intake or {}), 'policy_number': claim.policy_number,
                     'date_of_birth': (claim.health_intake or {}).get('patient_dob')}
    for key in ('patient_name', 'policyholder_name', 'policy_number', 'admission_date', 'discharge_date',
                'policy_start_date', 'policy_end_date', 'date_of_birth'):
        if intake_values.get(key) and form_values.get(key) and value_key(intake_values[key]) != value_key(form_values[key]):
            issue('intake_mismatch', f'{key.replace("_", " ")} in the form differs from your intake. Correct the intake or form before approval.')
    if form_values.get('ifsc_code') and not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}', str(form_values['ifsc_code']).upper()):
        issue('ifsc', 'IFSC must have four letters, a zero and six letters/digits.')
    if form_values.get('bank_account_number') and not re.fullmatch(r'\d{6,20}', str(form_values['bank_account_number'])):
        issue('bank_account', 'Check the bank account number (6–20 digits).')
    holder = form_values.get('bank_account_holder')
    allowed_holders = [form_values.get('policyholder_name')]
    if guide and guide['id'] in ('niva-bupa', 'hdfc-ergo'):
        allowed_holders.append(form_values.get('patient_name'))
    if holder and not any(value_key(holder) == value_key(name) for name in allowed_holders if name):
        issue('bank_holder', 'Bank account holder differs from the supported patient/proposer account details. Check the insurer requirements before approval.')
    if form_values.get('pincode') and not re.fullmatch(r'\d{6}', str(form_values['pincode'])):
        issue('pincode', 'Check the six-digit Indian PIN code.')
    if form_values.get('contact_email') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', str(form_values['contact_email'])):
        issue('email', 'Check the contact email address.')
    for key in ('admission_date', 'discharge_date', 'policy_start_date', 'policy_end_date', 'date_of_birth'):
        if form_values.get(key):
            try:
                date.fromisoformat(str(form_values[key]))
            except ValueError:
                issue('date_format', key.replace('_', ' ') + ': use YYYY-MM-DD.')
    start, end = form_values.get('admission_date'), form_values.get('discharge_date')
    if start and end and end < start:
        issue('date_order', 'Discharge cannot precede admission.')
    if start and form_values.get('policy_start_date') and start < form_values['policy_start_date']:
        issue('policy_period', 'Admission is before the entered policy period. Confirm the correct schedule with the insurer.')
    if start and form_values.get('policy_end_date') and start > form_values['policy_end_date']:
        issue('policy_period', 'Admission is after the entered policy period. Confirm the correct schedule with the insurer.')
    claimed = money(form_values.get('claimed_amount'))
    if claimed is None or claimed <= 0:
        issue('amount', 'Enter a positive claimed amount.')
    elif bills and all(value is not None for value in bills) and claimed != sum(bills, Decimal('0')):
        issue('amount_mismatch', 'Claimed hospitalization amount differs from the confirmed final hospital bills. Check for duplicated or omitted expenses.')
    if guide and guide['id'] in ('hdfc-ergo', 'niva-bupa') and claimed is not None and claimed >= Decimal('100000') and 'id_proof' not in valid_types:
        issue('kyc_amount', 'The insurer requires KYC for claims of INR 1 lakh or more. Upload and review the identity documents.')
    receipt_values = [money(item['fields'].get('payment_amount', {}).get('value')) for item in supporting
                      if item['document_type'] == 'payment_receipt' or item['contains_receipt']]
    if claimed and receipt_values and all(value is not None for value in receipt_values) and sum(receipt_values, Decimal('0')) < claimed:
        issue('receipt_amount', 'Payment receipts total less than the claimed amount. Check for missing receipts.', severity='warning')
    available = templates_for(claim.insurer)
    selected = template_for(claim.insurer, prep['template_id'], claim.policy_name)
    if selected and prep['template_confirmed_hash'] != selected['sha256']:
        prep['template_confirmed'] = False
    prep['template_id'] = selected['id'] if selected else None
    if not selected:
        issue('template_missing', 'No reviewed insurer template is installed for this claim.')
    selected_status = form_status(selected, form_values) if selected else {}
    for key in selected_status.get('overflow_fields', []):
        issue('form_overflow', f'{key.replace("_", " ")} is too long for the official form box. Enter a concise form value before approval.')
    if not prep['template_confirmed']:
        issue('template_confirmation', 'Inspect the official template and confirm it is appropriate for your policy/product.')
    if not prep['form_values_confirmed']:
        issue('form_confirmation', 'Review and confirm the claim form values.')
    if not prep['signatures_acknowledged']:
        issue('signature_acknowledgment', 'Acknowledge that you must complete signatures and hospital/doctor sections before submitting.')
    warnings.append('Signatures, hospital/doctor declarations and any unanswered insurance-history questions must be completed on the official form before submission.')
    snapshot = source_snapshot(claim, documents)
    is_approved = previous.get('approved_revision') == claim.revision and previous.get('snapshot') == snapshot and not errors
    prep.update({'snapshot': snapshot, 'revision': claim.revision, 'stale': False,
                 'approved_revision': claim.revision if is_approved else None,
                 'status': 'package_ready' if is_approved else 'awaiting_review' if not errors else 'needs_attention',
                 'policy_verified': verification['policy_verified'], 'policy_extraction': policy,
                 'extracted_documents': extracted, 'planned_requirements': requirements,
                 'document_check': {'present': present, 'missing': missing, 'needs_confirmation': pending},
                 'suggested_form_values': suggestions, 'form_draft': form_values,
                 'templates': available, 'selected_template': selected,
                 'form_status': selected_status,
                 'validation': {'passed': not errors, 'errors': list(dict.fromkeys(errors)),
                                'warnings': list(dict.fromkeys(warnings)), 'issues': issues},
                 'warnings': list(dict.fromkeys(warnings)),
                 'guidance_version': guide['version'] if guide else None})
    if is_approved:
        prep['package'] = {'status': 'prepared_for_manual_submission', 'revision': claim.revision,
                           'form_draft': form_values, 'note': 'Not submitted. Complete signatures and hospital sections.'}
    claim.preparation = prep
    claim.status = prep['status']
    return prep


def preparation_response(claim):
    prep = {**(claim.preparation or {})}
    prep['plan_stale'] = prep.get('document_plan_source') != plan_source(claim)
    return {'workflow_status': prep.get('status', claim.status), 'next_nodes': [],
            'interrupts': [{'kind': 'claim_draft_review'}] if claim.status == 'awaiting_review' else [], 'result': prep}
