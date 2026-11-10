"""SQLite connection boundary. Existing user tables are never dropped or rewritten."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3


def get_database_path():
    return os.getenv('APP_DATABASE_FILE','data/app.sqlite3')


def init_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    conn.commit()


@contextmanager
def sqlite_connection(db_path=None):
    path=db_path or get_database_path()
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        yield conn
    finally:
        conn.close()
