import sqlite3
import logging
from contextlib import contextmanager
from typing import Generator
from app.config import settings

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS transacoes (
                id          TEXT PRIMARY KEY,
                valor       REAL NOT NULL,
                data        TEXT NOT NULL,
                status      TEXT NOT NULL,
                cliente     TEXT NOT NULL,
                descricao   TEXT NOT NULL,
                categoria   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_status   ON transacoes(status);
            CREATE INDEX IF NOT EXISTS idx_cliente  ON transacoes(cliente);
            CREATE INDEX IF NOT EXISTS idx_data     ON transacoes(data);
        """)
    logger.info("Database initialized at %s", settings.db_path)
