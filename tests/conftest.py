"""Tests run against an explicit disposable PostgreSQL test database only."""
import os
import pytest

url = os.environ.get('TEST_DATABASE_URL')
if url:
    if not url.startswith('postgresql+psycopg://') or 'claimpilot_test' not in url:
        raise RuntimeError('TEST_DATABASE_URL must be a PostgreSQL database containing claimpilot_test in its URL')
    os.environ['DATABASE_URL'] = url
else:
    # Safe placeholder for importing pure logic tests; DB integration tests are skipped.
    os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://test:test@localhost/claimpilot_test')
os.environ.setdefault('JWT_SECRET', 'test-only-strong-jwt-secret-1234567890abcdef')
os.environ.setdefault('STORAGE_DIR', './test_private_uploads')

@pytest.fixture
def db_ready():
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to an isolated claimpilot_test PostgreSQL database')
    from app.db.base import Base
    from app.db.session import engine
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
