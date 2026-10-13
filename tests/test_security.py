from app.core.security import create_access_token, hash_password, verify_password
from app.core.config import settings
import jwt

def test_password_hashing():
    raw = 'a long test password 123!'
    hashed = hash_password(raw)
    assert raw != hashed
    assert verify_password(raw, hashed)
    assert not verify_password('wrong', hashed)

def test_jwt_has_expiration():
    token = create_access_token('user-id')
    payload = jwt.decode(token, settings.jwt_secret, algorithms=['HS256'])
    assert payload['sub'] == 'user-id'
    assert 'exp' in payload
