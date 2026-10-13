"""Deterministic intake/API tests with an isolated in-memory test database and no LLM calls."""
import uuid
from datetime import date
from urllib.parse import urlsplit
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.health import INSURERS, guidance_for
from app.models import Claim, AuditEvent
from app.schemas import ClaimCreate, HealthIntake


@pytest.fixture
def health_client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)

    def test_db():
        with sessions() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        yield client, sessions
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    engine.dispose()


def account(client):
    response = client.post('/api/v1/auth/register', json={
        'email': f'{uuid.uuid4().hex}@example.com', 'password': 'TestPassword-123456!'})
    assert response.status_code == 201, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def complete_payload(route='reimbursement'):
    return {'insurer': 'Star Health', 'policy_name': 'Family Health Optima', 'policy_number': 'POL-001',
            'claim_description': 'Hospitalization for illness', 'health_intake': {
                'patient_name': 'Demo Patient', 'policyholder_name': 'Demo Patient', 'relationship': 'self',
                'claim_route': route, 'admission_type': 'emergency', 'hospital_name': 'Demo Hospital',
                'hospital_city': 'Pune', 'admission_date': '2026-09-01', 'discharge_date': '2026-09-05',
                'intimation_status': 'not_notified', 'intake_completed': True}}


def test_guidance_sources_and_aliases():
    assert len(INSURERS) == 4
    assert guidance_for(' NIVA BUPA ')['id'] == 'niva-bupa'
    assert guidance_for('unknown') is None
    assert guidance_for('Star Health and Allied Insurance Co. Ltd.')['id'] == 'star-health'
    for insurer in INSURERS:
        assert date.fromisoformat(insurer['last_checked'])
        source_ids = {source['id'] for source in insurer['sources']}
        for item in [*insurer['timelines'], *insurer['documents'], insurer['submission'], insurer['cashless']]:
            assert item['source_ids'] and set(item['source_ids']) <= source_ids
        for item in [*insurer['sources'], *insurer['links']]:
            assert urlsplit(item['url']).scheme == 'https'
    assert any(t.get('conflict') and len(t['source_ids']) == 2
               for t in guidance_for('Star Health')['timelines'])


def test_formal_insurer_name_does_not_cause_false_policy_mismatch():
    from app.agent.workflow import verify_policy
    result = verify_policy({'insurer': 'Star Health', 'policy_name': 'Family Health Optima',
                            'policy_extraction': {'insurer': 'Star Health and Allied Insurance Co. Ltd.',
                                                  'policy_name': 'Family Health Optima'}})
    assert result['policy_verified']
    result = verify_policy({'insurer': 'Star Health', 'policy_name': 'Family Health Optima',
                            'policy_extraction': {'insurer': 'Care Health', 'policy_name': 'Family Health Optima'}})
    assert not result['policy_verified']


@pytest.mark.parametrize('intake', [
    {'admission_date': '2026-09-05', 'discharge_date': '2026-09-01'},
    {'policy_start_date': '2026-09-05', 'policy_end_date': '2026-09-01'},
    {'patient_dob': '2999-01-01'},
    {'claim_route': 'not_a_route'},
    {'intimation_status': 'not_notified', 'intimation_number': 'REF-123'},
    {'contact_email': 'invalid'},
])
def test_invalid_intake(intake):
    with pytest.raises(ValidationError):
        HealthIntake(**intake)


def test_completion_requires_details_but_draft_does_not():
    draft = ClaimCreate(insurer='Care Health', health_intake={})
    assert not draft.health_intake.intake_completed
    with pytest.raises(ValidationError, match='Complete these details'):
        ClaimCreate(insurer='Care Health', health_intake={'intake_completed': True})
    with pytest.raises(ValidationError, match='supported health insurer'):
        ClaimCreate(insurer='Unknown', health_intake={})


def test_save_resume_confirm_and_isolate(health_client):
    client, sessions = health_client
    owner, other = account(client), account(client)
    assert client.get('/api/v1/health/insurers').status_code == 401
    assert len(client.get('/api/v1/health/insurers', headers=owner).json()) == 4
    response = client.post('/api/v1/claims', headers=owner,
                           json={'insurer': 'Star Health', 'health_intake': {'patient_name': 'Demo Patient'}})
    assert response.status_code == 201, response.text
    claim = response.json()
    path = f"/api/v1/claims/{claim['id']}"
    assert 'Policy number' in claim['intake_missing']
    assert claim['guidance_version'] == guidance_for('Star Health')['version']
    assert client.get(path, headers=owner).json()['health_intake']['patient_name'] == 'Demo Patient'
    assert client.patch(path, headers=other, json=complete_payload()).status_code == 404
    assert client.post(path + '/workflow/start', headers=owner).status_code == 422
    response = client.patch(path, headers=owner, json=complete_payload())
    assert response.status_code == 200, response.text
    assert response.json()['intake_missing'] == []
    assert response.json()['health_intake']['intake_completed']
    with sessions() as db:
        stored = db.get(Claim, claim['id'])
        assert stored.health_intake['admission_date'] == '2026-09-01'
        assert db.scalar(select(AuditEvent).where(AuditEvent.claim_id == claim['id'],
                                               AuditEvent.action == 'claim_intake_updated'))
        stored.status = 'running'
        db.commit()
    assert client.patch(path, headers=owner, json=complete_payload()).status_code == 409


def test_cashless_cannot_run_reimbursement_analysis(health_client):
    client, _ = health_client
    owner = account(client)
    payload = complete_payload('cashless')
    payload['health_intake']['discharge_date'] = None
    response = client.post('/api/v1/claims', headers=owner, json=payload)
    assert response.status_code == 201, response.text
    response = client.post(f"/api/v1/claims/{response.json()['id']}/workflow/start", headers=owner)
    assert response.status_code == 409
    assert 'hospital insurance desk' in response.json()['detail']


def test_attached_documents_protect_policy_identity(health_client, monkeypatch, tmp_path):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'storage_dir', tmp_path)
    client, _ = health_client
    owner = account(client)
    payload = complete_payload()
    response = client.post('/api/v1/claims', headers=owner, json=payload)
    path = f"/api/v1/claims/{response.json()['id']}"
    response = client.post(path + '/documents', headers=owner, data={'kind': 'policy'},
                           files={'file': ('policy.pdf', b'%PDF-1.4\nexample', 'application/pdf')})
    assert response.status_code == 201, response.text
    payload['insurer'] = 'Niva Bupa'
    assert client.patch(path, headers=owner, json=payload).status_code == 409
    payload['insurer'] = 'Star Health'
    payload['health_intake']['hospital_city'] = 'Mumbai'
    assert client.patch(path, headers=owner, json=payload).status_code == 200


def test_browser_can_patch_and_delete(health_client):
    client, _ = health_client
    for method in ('PATCH', 'DELETE'):
        response = client.options('/api/v1/claims/demo', headers={
            'Origin': 'http://127.0.0.1:5173', 'Access-Control-Request-Method': method,
            'Access-Control-Request-Headers': 'authorization,content-type'})
        assert response.status_code == 200
        assert method in response.headers['access-control-allow-methods']
