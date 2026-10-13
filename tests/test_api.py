import io
import uuid
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_delete_claim(db_ready, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models import AuditEvent, Claim, ClaimDocument
    from sqlalchemy import select
    from contextlib import contextmanager

    monkeypatch.setattr(settings, 'storage_dir', tmp_path)
    deleted_threads = []

    @contextmanager
    def checkpointer():
        class Saver:
            def delete_thread(self, thread_id):
                deleted_threads.append(thread_id)
        yield Saver()

    monkeypatch.setattr('app.api.claims.open_checkpointer', checkpointer)
    suffix = uuid.uuid4().hex
    owner = register(f'owner-{suffix}@example.com')
    other = register(f'other-{suffix}@example.com')
    claim_id = client.post('/api/v1/claims', headers=owner, json={
        'insurer': 'A', 'policy_name': 'B', 'claim_description': 'C'}).json()['id']
    path = f'/api/v1/claims/{claim_id}'
    assert client.delete(path).status_code == 401
    assert client.delete(path, headers=other).status_code == 404
    upload = client.post(path + '/documents', headers=owner,
        data={'kind': 'supporting'},
        files={'file': ('bill.pdf', b'%PDF-1.4\nexample', 'application/pdf')})
    assert upload.status_code == 201
    with SessionLocal() as db:
        claim = db.get(Claim, claim_id)
        owner_id = claim.owner_id
        claim.status = 'running'
        db.commit()
    assert client.delete(path, headers=owner).status_code == 409
    assert len(list(tmp_path.rglob('*.pdf'))) == 1
    with SessionLocal() as db:
        db.get(Claim, claim_id).status = 'awaiting_review'
        db.commit()
    response = client.delete(path, headers=owner)
    assert response.status_code == 204
    assert response.content == b''
    assert deleted_threads == [f'{owner_id}:{claim_id}']
    assert client.get(path, headers=owner).status_code == 404
    assert client.get('/api/v1/claims', headers=owner).json() == []
    assert list(tmp_path.rglob('*.pdf')) == []
    assert client.delete(path, headers=owner).status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(ClaimDocument).where(ClaimDocument.claim_id == claim_id)) is None
        assert db.scalar(select(AuditEvent).where(
            AuditEvent.claim_id == claim_id, AuditEvent.action == 'claim_deleted')) is not None

def register(email: str):
    response = client.post('/api/v1/auth/register', json={
        'email': email, 'password': 'TestPassword-123456!'})
    assert response.status_code == 201, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}

def test_auth_and_claim_isolation(db_ready):
    suffix = uuid.uuid4().hex
    alice = register(f'alice-{suffix}@example.com')
    bob = register(f'bob-{suffix}@example.com')
    assert client.get('/api/v1/claims').status_code == 401
    claim = client.post('/api/v1/claims', headers=alice, json={
        'insurer':'Example Insurer', 'policy_name':'Health Plus',
        'claim_description':'Hospital visit'})
    assert claim.status_code == 201, claim.text
    claim_id = claim.json()['id']
    assert len(client.get('/api/v1/claims', headers=alice).json()) == 1
    assert client.get('/api/v1/claims', headers=bob).json() == []
    assert client.get(f'/api/v1/claims/{claim_id}', headers=bob).status_code == 404
    assert client.post(f'/api/v1/claims/{claim_id}/workflow/start', headers=bob).status_code == 404
    assert client.get(f'/api/v1/claims/{claim_id}/workflow', headers=bob).status_code == 404
    assert client.get(f'/api/v1/claims/{claim_id}/workflow/export', headers=bob).status_code == 404
    assert client.post(f'/api/v1/claims/{claim_id}/workflow/review', headers=bob,
                       json={'approved': True}).status_code == 404
    upload = client.post(f'/api/v1/claims/{claim_id}/documents', headers=alice,
        data={'kind':'policy','document_type':'other'},
        files={'file':('policy.pdf',io.BytesIO(b'%PDF-1.4\nexample'),'application/pdf')})
    assert upload.status_code == 201, upload.text
    assert len(client.get(f'/api/v1/claims/{claim_id}', headers=alice).json()['documents']) == 1
    assert client.post(f'/api/v1/claims/{claim_id}/documents', headers=alice,
        data={'kind':'policy'},files={'file':('second.pdf',b'%PDF-1.4','application/pdf')}).status_code == 409
    assert client.post(f'/api/v1/claims/{claim_id}/documents', headers=bob,
        data={'kind':'supporting'},files={'file':('doc.pdf',b'%PDF-1.4','application/pdf')}).status_code == 404

def test_remove_uploaded_document(db_ready, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models import Claim, ClaimDocument
    monkeypatch.setattr(settings, 'storage_dir', tmp_path)
    suffix = uuid.uuid4().hex
    owner = register(f'doc-owner-{suffix}@example.com')
    other = register(f'doc-other-{suffix}@example.com')
    claim_id = client.post('/api/v1/claims', headers=owner, json={
        'insurer': 'A', 'policy_name': 'B', 'claim_description': 'C'}).json()['id']
    other_claim_id = client.post('/api/v1/claims', headers=owner, json={
        'insurer': 'A', 'policy_name': 'Other', 'claim_description': 'C'}).json()['id']
    base = f'/api/v1/claims/{claim_id}'
    docs = []
    for kind in ('policy', 'supporting'):
        response = client.post(base + '/documents', headers=owner, data={'kind': kind},
            files={'file': (kind + '.pdf', b'%PDF-1.4\nexample', 'application/pdf')})
        assert response.status_code == 201
        docs.append(response.json()['id'])
    path = base + '/documents/' + docs[0]
    assert client.delete(path).status_code == 401
    assert client.delete(path, headers=other).status_code == 404
    assert client.delete(f'/api/v1/claims/{other_claim_id}/documents/{docs[0]}',
                         headers=owner).status_code == 404
    with SessionLocal() as db:
        db.get(Claim, claim_id).status = 'awaiting_review'
        db.commit()
    assert client.delete(path, headers=owner).status_code == 409
    assert len(list(tmp_path.rglob('*.pdf'))) == 2
    with SessionLocal() as db:
        claim = db.get(Claim, claim_id)
        claim.status = 'draft'
        claim.policy_source_mode = 'online'
        claim.policy_source_url = 'https://example.com/policy.pdf'
        db.commit()
    response = client.delete(path, headers=owner)
    assert response.status_code == 204
    assert response.content == b''
    detail = client.get(base, headers=owner).json()
    assert [d['id'] for d in detail['documents']] == [docs[1]]
    assert detail['policy_source_mode'] == 'upload'
    assert detail['policy_source_url'] is None
    assert len(list(tmp_path.rglob('*.pdf'))) == 1
    assert client.delete(path, headers=owner).status_code == 404
    with SessionLocal() as db:
        assert db.get(ClaimDocument, docs[0]) is None
        assert db.get(ClaimDocument, docs[1]) is not None
    assert client.delete(base + '/documents/' + docs[1], headers=owner).status_code == 204
    assert list(tmp_path.rglob('*.pdf')) == []


def test_reject_invalid_pdf(db_ready):
    user = register(f'test-{uuid.uuid4().hex}@example.com')
    claim = client.post('/api/v1/claims', headers=user, json={
        'insurer':'A','policy_name':'B','claim_description':'C'}).json()
    response = client.post(f"/api/v1/claims/{claim['id']}/documents", headers=user,
        data={'kind':'supporting'},files={'file':('fake.pdf',b'not a pdf','application/pdf')})
    assert response.status_code == 415
