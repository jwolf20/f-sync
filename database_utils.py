"""Utility functions for interacting with a Postgres database.
This contains both general functions as well as some functions
related to the specific schema used within this application.
"""
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
    """Used to serve up connections to the PostgreSQL database.

    The connections are provided from a ThreadedConnectionPool.

    The context manager returns connections back to pool once the connection goes out of scope.

    Yields
    ------
    Generator[psycopg2.connection, None, None]
        A connection to PostgreSQL database.
    """
    conn = db_connection_pool.getconn()
    try:
        yield conn
    finally:
        db_connection_pool.putconn(conn)


def database_user_check(fitbit_id: str) -> bool:
    """Checks if a user with the given `fitbit_id` is present in the database.

    Parameters
    ----------
    fitbit_id : str
        The id used for the query.

    Returns
    -------
    bool
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(1) FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            result = cur.fetchone()[0]
            return result > 0


def database_create_user(fitbit_id: str) -> bool:
    """Adds a user to the database using the provided `fitbit_id`.

    There is a check to see if the user is already present in the database.
    If the user is present then no further action database action is taken.

    If the user is not present then the given `fitbit_id` is added
    to both the user_tokens and user_activity tables.

    Parameters
    ----------
    fitbit_id : str
        The id used for the query.


    Returns
    -------
    bool
        Indicates if a new user was added to the table.
        A value of False means the user was already present within the database.
    """
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
    return False
