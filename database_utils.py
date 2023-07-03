from contextlib import contextmanager
import os

import psycopg2


@contextmanager
def get_db_connection():
    conn = psycopg2.connect(
        host="localhost",
        database="fsync_db",
        user=os.getenv("DB_USERNAME"),
        password=os.getenv("DB_PASSWORD"),
    )
    try:
        yield conn
    finally:
        conn.close()
