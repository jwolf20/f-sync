from contextlib import contextmanager
import os

import psycopg2

db_connection_pool = psycopg2.ThreadedConnectionPool(
    minconn=1,
    maxconn=15,
    host=os.getenv("DB_HOST"),
    database=os.getenv("DB_NAME"),
    user=os.getenv("DB_USERNAME"),
    password=os.getenv("DB_PASSWORD"),
)


@contextmanager
def get_db_connection():
    conn = db_connection_pool.getconn()
    try:
        yield conn
    finally:
        db_connection_pool.putconn(conn)
