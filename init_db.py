import os

import psycopg2


def reset_db():
    conn = psycopg2.connect(
        host="localhost",
        database="fsync_db",
        user=os.getenv("DB_USERNAME"),
        password=os.getenv("DB_PASSWORD"),
    )

    with conn.cursor() as cur:
        # Create the User tokens table.
        cur.execute("DROP TABLE IF EXISTS user_tokens CASCADE;")
        cur.execute(
            """CREATE TABLE user_tokens (
                fitbit_id varchar (10) PRIMARY KEY,
                fitbit_access_token varchar (400) NOT NULL,
                fitbit_refresh_token varchar (100) NOT NULL,
                strava_access_token varchar (400) NOT NULL,
                strava_refresh_token varchar (100) NOT NULL,
                date_added timestamp DEFAULT CURRENT_TIMESTAMP,
                fitbit_date_refreshed timestamp DEFAULT CURRENT_TIMESTAMP,
                strava_data_refreshed timestamp DEFAULT CURRENT_TIMESTAMP);"""
        )

        # Create the User activity table.
        cur.execute("DROP TABLE IF EXISTS user_activity CASCADE;")
        cur.execute(
            """CREATE TABLE user_activity (
                fitbit_id varchar (10) PRIMARY KEY,
                fitbit_latest_activity_date timestamp NOT NULL DEFAULT date '2000-01-01',
                strava_latest_activity_date timestamp NOT NULL DEFAULT date '2000-01-01',
                CONSTRAINT fk_fitbit_id
                    FOREIGN KEY(fitbit_id)
                        REFERENCES user_tokens(fitbit_id)
                        ON DELETE CASCADE
            );"""
        )

        conn.commit()

    conn.close()


if __name__ == "__main__":
    proceed = input(
        "WARNING: Executing this script will ERASE ALL EXISTING APPLICATION FROM THE DATABASE!  Are you sure you want to proceed? (Y/N):"
    )
    if proceed == "Y":
        print("Resetting the database.")
        reset_db()
