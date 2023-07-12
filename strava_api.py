import io
import os
import requests
from typing import Callable

from database_utils import get_db_connection

Response = requests.models.Response


def get_strava_access_token(fitbit_id: str) -> str:
    """Returns the Strava API access token associated with the provided `fitbit_id` from the database.

    Parameters
    ----------
    fitbit_id : str
        The primary key value for the user_tokens table.

    Returns
    -------
    str
        The requested access token.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT strava_access_token FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            access_token = cur.fetchone()[0]
    return access_token


def get_strava_refresh_token(fitbit_id: str) -> str:
    """Returns the Strava API refresh token associated with the provided `fitbit_id` from the database.

    Parameters
    ----------
    fitbit_id : str
        The primary key value for the user_tokens table.

    Returns
    -------
    str
        The requested refresh token.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT strava_refresh_token FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            refresh_token = cur.fetchone()[0]
    return refresh_token


def update_strava_tokens(token_data: dict[str, str], fitbit_id: str) -> None:
    """Update the Strava access and refresh tokens for the provided `fitbit_id`
    within the database.

    Parameters
    ----------
    token_data : dict[str, str]
        A dictionary containing the new "access_token" and "refresh_token" values.
    fitbit_id : str
        The primary key value for the user_tokens table.
    """
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
    """Consume the Strava refresh_token associated with the given `fitbit_id` to generate a new pair
    of access and refresh tokens.

    An additional function call is made to store the new values in the database.

    Parameters
    ----------
    fitbit_id : str
        The primary key value for the user_tokens table.

    Raises
    ------
    requests.exceptions.HTTPError
        This is raised when the request to the API is unsuccessful.
    """
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


def strava_token_refresh_decorator(
    api_call: Callable[..., Response]
) -> Callable[..., Response]:
    """A decorator that is useful for API calls.  In the event that an API call returns a
    response code indicating the that access token has expired and needs to be refreshed.
    This decorator will execute the call to refresh the access token and then attempt to
    execute the API call again after the tokens have been refreshed.

    If the original API request does not return a response indicating that the access token
    needs to be refreshed, then no action is taken.

    Parameters
    ----------
    api_call : Callable[..., Response]
        The function making an API call.  This function MUST contain
        `fitbit_id` as a keyword argument.  In order to be able to perform
        the action of refreshing the tokens.

    Returns
    -------
    Callable[..., Response]
    """

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
    """Submit an API request to upload the .tcx file data from the `file_buffer` as
    a Strava activity.

    Parameters
    ----------
    file_buffer : io.BytesIO
        A file buffer for the .tcx activity file being uploaded.
    fitbit_id : str
        The Fitbit Id for the user related to this request.

    Returns
    -------
    Response
        The HTTP response from the API.
    """
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
    """Submit an API request to check the status of an activity that has been
    uploaded to Strava.

    Parameters
    ----------
    upload_id : int | str
        The upload id for the activity.
    fitbit_id : str
        The Fitbit Id for the user related to this request.

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_strava_access_token(fitbit_id)
    url = f"https://www.strava.com/api/v3/uploads/{upload_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers)

    return response


@strava_token_refresh_decorator
def strava_get_activity_list(*, fitbit_id: str) -> Response:
    """Submit an API request to get a list of recent Strava activities
    for the user.

    The activities are sorted in descending order by activity date.

    Parameters
    ----------
    fitbit_id : str
        The Fitbit Id for the user related to this request.

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_strava_access_token(fitbit_id)
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers)

    return response


@strava_token_refresh_decorator
def get_strava_most_recent_activity(*, fitbit_id: str) -> Response:
    """Submit an API request to get the most recent Strava activity
    for the user.

    Parameters
    ----------
    fitbit_id : str
        The Fitbit Id for the user related to this request.

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_strava_access_token(fitbit_id)
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "per_page": 1,
    }
    response = requests.get(url=url, headers=headers, params=params)

    return response
