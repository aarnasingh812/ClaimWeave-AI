from app.core.config import settings
from app.api.workflows import thread_config

def test_postgres_checkpoint_dsn():
    assert settings.checkpoint_dsn.startswith('postgresql://')
    assert 'sqlite' not in settings.checkpoint_dsn

def test_checkpoint_tenant_namespacing():
    a = thread_config('same-claim', 'user-a')
    b = thread_config('same-claim', 'user-b')
    assert a != b
