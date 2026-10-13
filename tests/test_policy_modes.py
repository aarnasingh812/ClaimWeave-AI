from fastapi import HTTPException
from app.agent.workflow import acquire_policy, after_acquire, plan_requirements, validate_claim
from app.agent.policy_discovery import domains_for, validated_url

def test_provisional_requires_no_policy():
    state = {'policy_path': None, 'insurer': 'Demo', 'claim_description': 'Hospital visit'}
    result = acquire_policy(state)
    assert result['policy_verified'] is False
    assert result['status'] == 'provisional'
    assert after_acquire(state) == 'classify'

def test_provisional_checklist_is_not_policy_requirement():
    suggestions = plan_requirements({'policy_verified': False})['planned_requirements']
    assert suggestions
    assert all(not x['mandatory'] for x in suggestions)
    assert all(x['source_reference'] == 'GENERAL_GUIDANCE_NOT_POLICY' for x in suggestions)

def test_provisional_never_passes_final_validation():
    result = validate_claim({'policy_verified': False, 'planned_requirements': [],
        'document_check': {'missing': [], 'needs_confirmation': []}, 'warnings': []})
    assert result['validation']['passed'] is False

def test_unknown_insurer_has_no_discovery_domains():
    assert domains_for('Random Unknown Insurer') == ()

def test_external_url_is_rejected():
    try:
        validated_url('https://localhost/internal.pdf', ('starhealth.in',))
        assert False, 'Must reject non-allowlisted URL'
    except HTTPException as e:
        assert e.status_code == 422
