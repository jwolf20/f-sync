import io
import os
import requests

from database_utils import get_db_connection

Response = requests.models.Response


def get_strava_access_token(fitbit_id: str) -> str:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT strava_access_token FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            access_token = cur.fetchone()[0]
    return access_token


def get_strava_refresh_token(fitbit_id: str) -> str:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT strava_refresh_token FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            refresh_token = cur.fetchone()[0]
    return refresh_token


def update_strava_tokens(token_data: dict[str, str], fitbit_id: str) -> None:
    new_access_token = token_data["access_token"]
    new_refresh_token = token_data["refresh_token"]
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_tokens SET strava_access_token = %s, strava_refresh_token = %s, strava_date_refreshed = CURRENT_TIMESTAMP WHERE fitbit_id = %s",
                (new_access_token, new_refresh_token, fitbit_id),
            )
        conn.commit()


def strava_refresh_tokens(fitbit_id: str) -> None:
    refresh_token = get_strava_refresh_token(fitbit_id)
    params = {
        "grant_type": "refresh_token",
        "client_id": os.getenv("STRAVA_CLIENT_ID"),
        "client_secret": os.getenv("STRAVA_CLIENT_SECRET"),
        "refresh_token": refresh_token,
    }

    response = requests.post(
        url="https://www.strava.com/api/v3/oauth/token", params=params
    )

    # Store the new tokens
    if response.status_code == 200:
        update_strava_tokens(response.json(), fitbit_id)

    else:
        print(response.status_code)
        print(response.json())
        raise requests.exceptions.HTTPError(response)


def strava_token_refresh_decorator(api_call):
    def refresh_api_call(*args, **kwargs) -> Response:
        response = api_call(*args, **kwargs)

        # Check if tokens need to be refreshed
        if response.status_code == 401:
            fitbit_id = kwargs["fitbit_id"]
            strava_refresh_tokens(fitbit_id)

            # Resubmit the response
            response = api_call(*args, **kwargs)

        return response

    return refresh_api_call


@strava_token_refresh_decorator
def strava_activity_upload(file_buffer: io.BytesIO, *, fitbit_id: str) -> Response:
    access_token = get_strava_access_token(fitbit_id)
    file_buffer.seek(0)
    url = "https://www.strava.com/api/v3/uploads"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"data_type": "tcx"}
    files = {"file": file_buffer}

    response = requests.post(url=url, headers=headers, files=files, params=params)

    return response


@strava_token_refresh_decorator
def strava_check_upload_status(upload_id: int | str, *, fitbit_id: str) -> Response:
    access_token = get_strava_access_token(fitbit_id)
    url = f"https://www.strava.com/api/v3/uploads/{upload_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers)

    return response


@strava_token_refresh_decorator
def strava_get_activity_list(*, fitbit_id: str) -> Response:
    access_token = get_strava_access_token(fitbit_id)
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers)

    return response


@strava_token_refresh_decorator
def get_strava_most_recent_activity(*, fitbit_id: str) -> Response:
    access_token = get_strava_access_token(fitbit_id)
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "per_page": 1,
    }
    response = requests.get(url=url, headers=headers, params=params)

    return response
