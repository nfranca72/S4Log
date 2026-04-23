import pyodbc
from contextlib import contextmanager
from app.settings import settings

def get_connection_string() -> str:
    return (
        f"DRIVER={{{settings.DB_DRIVER}}};"
        f"SERVER={settings.DB_HOST};"
        f"DATABASE={settings.DB_NAME};"
        f"UID={settings.DB_USER};"
        f"PWD={settings.DB_PASSWORD};"
        "TrustServerCertificate=yes;"
    )

def get_connection() -> pyodbc.Connection:
    return pyodbc.connect(get_connection_string())

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
