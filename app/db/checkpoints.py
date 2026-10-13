"""LangGraph checkpoint tables are created in the same PostgreSQL database.

PostgresSaver.setup() creates its own tables, separate from Alembic-managed app tables.
Run: python -m app.db.checkpoints
"""
from contextlib import contextmanager
from langgraph.checkpoint.postgres import PostgresSaver
from app.core.config import settings

@contextmanager
def open_checkpointer():
    with PostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
        yield saver

def setup_checkpoints():
    with open_checkpointer() as saver:
        saver.setup()

if __name__ == '__main__':
    setup_checkpoints()
    print('LangGraph PostgreSQL checkpoint tables initialized')
