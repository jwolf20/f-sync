import datetime
import io
import json
from logging.config import dictConfig

from flask import Flask, render_template, request

from celery_utils import get_celery_app_instance
from database_utils import get_db_connection
from fitbit_api import *
from strava_api import *


dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
            },
            "file-rotate": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": "app.log",
                "maxBytes": 1000000,
                "backupCount": 5,
                "formatter": "default",
            },
        },
        "root": {"level": "DEBUG", "handlers": ["console", "file-rotate"]},
    }
)

# Initialize flask app
app = Flask(__name__)

# Initialize celery app instance
celery = get_celery_app_instance(app)


def process_activity(log_id, fitbit_id) -> bool:
    tcx_response = get_fitbit_activity_tcx(log_id, fitbit_id=fitbit_id)
    if tcx_response.status_code != 200:
        app.logger.error(
            f"Failed Response: {tcx_response.status_code=}\n{tcx_response.json()}"
        )
        return False

    tcx_buffer = io.BytesIO(tcx_response.content)
    upload_response = strava_activity_upload(tcx_buffer, fitbit_id=fitbit_id)

    if upload_response.status_code != 201:
        app.logger.error(
            f"Unexpected Response: {upload_response.status_code=}\n{upload_response.json()}"
        )
        return False
    app.logger.info("A new activity is being uploaded to Strava!")
    return True


@celery.task
def upload_latest_activities(fitbit_id):
    app.logger.info(f"Attempting to upload new activity for {fitbit_id=}")
    response = get_fitbit_activity_log(fitbit_id=fitbit_id)
    if response.status_code != 200:
        return  # TODO: put an appropriate error here
    # Check that the response is good
    if len(response.json()["activities"]) == 0:
        app.logger.warning("No recent Fitbit activities found!")
        return  # TODO: put an appropriate error here

    latest_activity = response.json()["activities"][0]
    if latest_activity["logType"] != "tracker":
        app.logger.warning(
            "Latest activity was not recorded by a tracker (likely a manual upload without GPS data)"
        )
        return  # TODO: put an appropriate error here

    if latest_activity["activityName"].lower() not in ("run", "hike"):
        app.logger.error(
            f"Unsupported type for latest activity: {latest_activity['activityName']}."
        )
        return  # TODO: put an appropriate error here

    # Check if this activity is an improvement over the most recent known activity
    app.logger.debug("Connecting to database")
    with get_db_connection() as conn:
        latest_fitbit_timestamp = datetime.datetime.fromisoformat(
            latest_activity["startTime"]
        ).replace(tzinfo=None)
        app.logger.debug(f"{latest_fitbit_timestamp=}")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fitbit_latest_activity_date FROM user_activity WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            sql_fitbit_timestamp_result = cur.fetchone()[0]
            app.logger.debug(f"{sql_fitbit_timestamp_result=}")

            if latest_fitbit_timestamp == sql_fitbit_timestamp_result:
                app.logger.info(
                    f"There is no new activity for user with {fitbit_id=}.  The timestamp for this activity has already been seen {latest_fitbit_timestamp=}.  The database has noted {sql_fitbit_timestamp_result=}"
                )
                return

            log_id = latest_activity["logId"]
            app.logger.info(f"Uploading activity {log_id=}")
            upload_successful = process_activity(log_id=log_id, fitbit_id=fitbit_id)
            app.logger.info(f"{upload_successful=}")

            # Update the database recording the new timestamp
            if upload_successful:
                app.logger.debug(
                    f"Updating database activity records for {fitbit_id=}."
                )
                cur.execute(
                    "UPDATE user_activity SET fitbit_latest_activity_date = %s WHERE fitbit_id = %s",
                    (latest_fitbit_timestamp, fitbit_id),
                )
                conn.commit()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/fitbit-notifications/", methods=["GET", "POST"])
def webhook_link():
    if request.method == "POST":
        if fitbit_validate_signature(request):
            app.logger.debug("Received a valid notification from Fitbit.")
            app.logger.debug(request.data)
            notifications = json.loads(request.data)
            for notification in notifications:
                if (
                    notification.get("collectionType") == "activities"
                    and notification.get("ownerType") == "user"
                ):
                    fitbit_id = notification.get("ownerId")
                    if fitbit_id is not None:
                        upload_latest_activities.delay(fitbit_id=fitbit_id)
            return "Success", 204
        else:
            app.logger.warning(
                f"Bad request:\nHeaders: {request.headers}\nData: {request.data}"
            )
            return "Bad Request", 400

    else:
        # TODO: Figure out how to modify verification to support additional users?  I had to manually go into my app's page and create a subscriber and get this hardcoded value.
        VERIFICATION_GOAL = (
            "6d3a00596cc20459b058a4da628690718c162fd7dc8325fd1e07f9fc22a50641"
        )
        verification_code = request.args.get("verify")
        if verification_code == VERIFICATION_GOAL:
            app.logger.info(f"Successful verification of {verification_code}")
            return "Success", 204
        else:
            return "Failure", 404


if __name__ == "__main__":
    app.run(debug=True)
