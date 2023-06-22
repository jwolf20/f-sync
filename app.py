import io
from logging.config import dictConfig

from flask import Flask, render_template, request
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

app = Flask(__name__)


def process_activity(log_id):
    tcx_response = get_fitbit_activity_tcx(log_id)
    if tcx_response.status_code != 200:
        app.logger.error(
            f"Failed Response: {tcx_response.status_code=}\n{tcx_response.json()}"
        )
        return

    tcx_buffer = io.BytesIO(tcx_response.content)
    upload_response = strava_activity_upload(tcx_buffer)

    if upload_response.status_code != 201:
        app.logger.error(
            f"Unexpected Response: {upload_response.status_code=}\n{upload_response.json()}"
        )
    app.logger.info("A new activity is being uploaded to Strava!")


def upload_latest_activity():
    response = get_fitbit_activity_log()
    if response.status_code != 200:
        return  # TODO: put an appropriate error here
    # Check that the response is good
    if len(response.json()["activities"]) == 0:
        app.logger.warning("No recent activities found!")
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

    log_id = latest_activity["logId"]
    process_activity(log_id=log_id)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/fitbit-notifications/", methods=["GET", "POST"])
def webhook_link():
    if request.method == "POST":
        app.logger.debug(request.headers)
        app.logger.debug(request.data)
        if fitbit_validate_signature(request):
            app.logger.debug("Received a valid notification from Fitbit.")
            upload_latest_activity()  # TODO: Change this action to be executed using an async task queue; Expand to allow for multiple users.
            return "Success", 204
        else:
            app.logger.warning("Bad request.")
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
