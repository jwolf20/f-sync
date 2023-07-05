import datetime
import io
import json
from logging.config import dictConfig
import os
import secrets
from urllib.parse import urlencode

from flask import (
    abort,
    flash,
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from celery_utils import get_celery_app_instance
from database_utils import get_db_connection, database_create_user, database_user_check
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


# OAUTH section
# This section contains the code necessary to interact with Oauth allowing users to register for the application.
@app.route("/auth/success")
def auth_success():
    return render_template("auth_success.html")


def generate_pkce_code():
    random_token = secrets.token_urlsafe(90)
    sha256_hash = hashlib.sha256(random_token.encode()).digest()
    pkce_code = base64.urlsafe_b64encode(sha256_hash).rstrip(b"=").decode()
    return pkce_code


@app.route("/auth/fitbit")
def fitbit_oauth():
    session["pkce_code"] = generate_pkce_code()
    session["oauth2_fitbit_state"] = secrets.token_urlsafe(20)
    param_string = urlencode(
        {
            "response_type": "code",
            "client_id": os.getenv("FITBIT_CLIENT_ID"),
            "scope": "activity",
            "code_challenge": session["pkce_code"],
            "code_challenge_method": "S256",
            "state": session["oauth2_fitbit_state"],
            "redirect_uri": os.getenv("FITBIT_REDIRECT_URI"),
        }
    )
    authorization_address = f"https://www.fitbit.com/oauth2/authorize?{param_string}"
    return redirect(authorization_address)


@app.route("/auth_verify/fitbit")
def fitbit_oauth_verify():
    # Verify the redirect has required information
    if "error" in request.args:
        for k, v in request.args.items():
            if k.startswith("error"):
                flash(f"{k}: {v}")
        return redirect(url_for("index"))

    if request.args["state"] != session.get("oauth2_fitbit_state"):
        abort(401)

    if session.get("pkce_code") is None:
        abort(401)

    if "code" not in request.args:
        abort(401)

    # Submit request for tokens
    ## Construct request parameters
    params = {
        "client_id": os.getenv("FITBIT_CLIENT_ID"),
        "grant_type": "authorization_code",
        "redirect_uri": os.getenv("FITBIT_REDIRECT_URI"),
        "code": request.args.get("code"),
        "code_verifier": session["pkce_code"],
    }

    basic_token = base64.urlsafe_b64encode(
        f"{os.getenv('FITBIT_CLIENT_ID')}:{os.getenv('FITBIT_CLIENT_SECRET')}".encode()
    ).decode()

    ## Construct request headers
    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    ## Submit request
    response = requests.post(
        url="https://api.fitbit.com/oauth2/token", params=params, headers=headers
    )

    # Verify request is successful
    if response.status_code != 200:
        abort(401)

    access_token = response.json().get("access_token")
    if not access_token:
        abort(401)

    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        abort(401)

    fitbit_id = response.json().get("user_id")
    if not fitbit_id:
        abort(401)

    # TODO: Check that user provided appropriate scope access
    app.logger.info(f"{fitbit_id=}, scope: {response.json().get('scope')}")

    # Add user to database
    user_added = database_create_user(fitbit_id=fitbit_id)
    if user_added:
        app.logger.info(f"Added New User to the database with{fitbit_id=}")
    else:
        app.logger.warning(
            f"User with {fitbit_id=} has re-registered for the application."
        )

    update_fitbit_tokens(response.json(), fitbit_id=fitbit_id)

    return redirect(url_for("strava_oauth", fitbit_id=fitbit_id))


@app.route("/auth/strava/<fitbit_id>")
def strava_oauth(fitbit_id):
    # Used to check that the request is coming from a redirect
    if session.get("oauth2_fitbit_state") is None:
        abort(401)

    # Verify user is valid
    if not database_user_check(fitbit_id=fitbit_id):
        abort(401)

    # Generate a new state token
    session["oauth2_strava_state"] = f"{fitbit_id}_{secrets.token_urlsafe(20)}"
    param_string = urlencode(
        {
            "client_id": os.getenv("STRAVA_CLIENT_ID"),
            "scope": "activity:write,activity:read",
            "response_type": "code",
            "approval_prompt": "auto",
            "state": session["oauth2_strava_state"],
            "redirect_uri": os.getenv("STRAVA_REDIRECT_URI"),
        }
    )
    authorization_address = f"https://www.strava.com/oauth/authorize?{param_string}"
    return redirect(authorization_address)


@app.route("/auth_verify/strava")
def strava_oauth_verify():
    # Verify the redirect has required information
    if "error" in request.args:
        for k, v in request.args.items():
            if k.startswith("error"):
                flash(f"{k}: {v}")
        return redirect(url_for("index"))

    if request.args["state"] != session.get("oauth2_strava_state"):
        abort(401)

    if "code" not in request.args:
        abort(401)

    fitbit_id, *_ = session.get("oauth2_strava_state").split("_")
    # Submit request for tokens
    ## Construct request parameters
    params = {
        "client_id": os.getenv("STRAVA_CLIENT_ID"),
        "client_secret": os.getenv("STRAVA_CLIENT_SECRET"),
        "grant_type": "authorization_code",
        "code": request.args.get("code"),
    }

    ## Submit request
    response = requests.post(
        url="https://www.strava.com/api/v3/oauth/token", params=params
    )

    # Verify request is successful
    if response.status_code != 200:
        abort(401)

    access_token = response.json().get("access_token")
    if not access_token:
        abort(401)

    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        abort(401)

    # Add tokens to the database
    update_strava_tokens(response.json(), fitbit_id=fitbit_id)

    # Add user to webhook endpoint subscription
    response = fitbit_webhook_subscribe(subscriber_id=1, fitbit_id=fitbit_id)

    if response.status_code == 200:
        app.logger.warning(
            f"User {fitbit_id=} already had an active webhook subscription."
        )
    elif response.status_code == 201:
        app.logger.info(
            f"Successfully created webhook subscription for user {fitbit_id=}!"
        )
    else:
        app.logger.error(
            f"Something went wrong attempting to create a webhook subscription for user {fitbit_id=}!"
        )
        abort(401)

    return redirect(url_for("auth_success"))


if __name__ == "__main__":
    app.run(debug=True)
