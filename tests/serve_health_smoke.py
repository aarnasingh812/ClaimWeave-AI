"""Optional browser QA server: isolated in-memory database, synthetic account, no insurer/LLM calls.

Run from the project root: env/Scripts/python.exe -m tests.serve_health_smoke
Point VITE_API_URL to http://127.0.0.1:8001 for this test session only.
"""
import os
os.environ['DATABASE_URL'] = 'postgresql+psycopg://test:test@localhost/claimpilot_test'
os.environ['JWT_SECRET'] = 'local-browser-smoke-test-only-secret-1234567890'
os.environ['GOOGLE_API_KEY'] = ''

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.models import User
from app.core.security import hash_password

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
sessions = sessionmaker(engine, expire_on_commit=False)
with sessions() as db:
    db.add(User(email='health-smoke@example.com', password_hash=hash_password('SmokeTest-Only-123456!')))
    db.commit()


def test_db():
    with sessions() as db:
        yield db


app.dependency_overrides[get_db] = test_db

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8001)
