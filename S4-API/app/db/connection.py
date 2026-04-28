from contextlib import contextmanager

import pyodbc

from app.settings import settings


def get_connection_string() -> str:
    return settings.connection_string


def get_connection() -> pyodbc.Connection:
    return pyodbc.connect(get_connection_string())


def test_connection() -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
    finally:
        conn.close()


@contextmanager
def db_cursor():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor, conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
