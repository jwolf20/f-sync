import os

import psycopg2

conn = psycopg2.connect(
    host="localhost",
    database="fsync_db",
    user=os.getenv("DB_USERNAME"),
    password=os.getenv("DB_PASSWORD"),
)

cur = conn.cursor()

# Create the User tokens table.
cur.execute("DROP TABLE IF EXISTS user_tokens CASCADE;")
cur.execute(
    """CREATE TABLE user_tokens (
        fitbit_id varchar (10) PRIMARY KEY,
        fitbit_access_token varchar (400) NOT NULL,
        fitbit_refresh_token varchar (100) NOT NULL,
        strava_access_token varchar (400) NOT NULL,
        strava_refresh_token varchar (100) NOT NULL,
        date_added date DEFAULT CURRENT_TIMESTAMP,
        fitbit_date_refreshed date DEFAULT CURRENT_TIMESTAMP,
        strava_data_refreshed date DEFAULT CURRENT_TIMESTAMP);"""
)

# Create the User activity table.
cur.execute("DROP TABLE IF EXISTS user_activity CASCADE;")
cur.execute(
    """CREATE TABLE user_activity (
        fitbit_id varchar (10) PRIMARY KEY,
        fitbit_latest_activity_date date NOT NULL DEFAULT date '2000-01-01',
        strava_latest_activity_date date NOT NULL DEFAULT date '2000-01-01',
        CONSTRAINT fk_fitbit_id
            FOREIGN KEY(fitbit_id)
                REFERENCES user_tokens(fitbit_id)
                ON DELETE CASCADE
    );"""
)

conn.commit()
cur.close()
conn.close()
