from contextlib import contextmanager
import os

from psycopg2.pool import ThreadedConnectionPool

db_connection_pool = ThreadedConnectionPool(
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


def database_user_check(fitbit_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(1) FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            result = cur.fetchone()[0]
            return result > 0


def database_create_user(fitbit_id):
    if not database_user_check(fitbit_id):
        # User does not yet exist and needs to be inserted
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_tokens (fitbit_id) VALUES (%s)", (fitbit_id,)
                )
                cur.execute(
                    "INSERT INTO user_activity (fitbit_id) VALUES (%s)", (fitbit_id,)
                )
            conn.commit()
        return True
    else:
        return False
