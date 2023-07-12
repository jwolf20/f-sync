import base64
import datetime
import hashlib
import hmac
import os
import requests
from typing import Callable

from database_utils import get_db_connection

Response = requests.models.Response
Request = requests.models.Request


def get_fitbit_access_token(fitbit_id: str) -> str:
    """Returns the Fitbit API access token associated with the provided `fitbit_id` from the database.

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
                "SELECT fitbit_access_token FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            access_token = cur.fetchone()[0]
    return access_token


def get_fitbit_refresh_token(fitbit_id: str) -> str:
    """Returns the Fitbit API refresh token associated with the provided `fitbit_id` from the database.

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
                "SELECT fitbit_refresh_token FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            refresh_token = cur.fetchone()[0]
    return refresh_token


def update_fitbit_tokens(token_data: dict[str, str], fitbit_id: str) -> None:
    """Update the Fitbit access and refresh tokens for the provided `fitbit_id`
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
                "UPDATE user_tokens SET fitbit_access_token = %s, fitbit_refresh_token = %s, fitbit_date_refreshed = CURRENT_TIMESTAMP WHERE fitbit_id = %s",
                (new_access_token, new_refresh_token, fitbit_id),
            )
        conn.commit()


def fitbit_refresh_tokens(fitbit_id: str) -> None:
    """Consume the Fitbit refresh_token associated with the given `fitbit_id` to generate a new pair
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
    refresh_token = get_fitbit_refresh_token(fitbit_id)
    basic_token = base64.urlsafe_b64encode(
        f"{os.getenv('FITBIT_CLIENT_ID')}:{os.getenv('FITBIT_CLIENT_SECRET')}".encode()
    ).decode()
    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    params = {
        "grant_type": "refresh_token",
        "client_id": os.getenv("FITBIT_CLIENT_ID"),
        "refresh_token": refresh_token,
    }

    response = requests.post(
        url="https://api.fitbit.com/oauth2/token", params=params, headers=headers
    )

    # Store the new tokens
    if response.status_code == 200:
        update_fitbit_tokens(response.json(), fitbit_id)

    else:
        print(response.status_code)
        print(response.json())
        raise requests.exceptions.HTTPError(response)


def fitbit_token_refresh_decorator(
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
            fitbit_refresh_tokens(fitbit_id)

            # Resubmit the response
            response = api_call(*args, **kwargs)

        return response

    return refresh_api_call


@fitbit_token_refresh_decorator
def get_fitbit_profile(*, fitbit_id: str) -> Response:
    """Submit an API request for the Fitbit profile corresponding to the given `fitbit_id`.

    Parameters
    ----------
    fitbit_id : str
        The Fitbit Id for the user related to this request.

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_fitbit_access_token(fitbit_id)
    url = "https://api.fitbit.com/1/user/-/profile.json"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers)
    return response


@fitbit_token_refresh_decorator
def get_fitbit_activity_tcx(log_id: int | str, *, fitbit_id: str) -> Response:
    """Submit an API request to get the .tcx data for a user activity.

    Parameters
    ----------
    log_id : int | str
        The log_id of the requested activity.
    fitbit_id : str
        The Fitbit Id for the user related to this request.

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_fitbit_access_token(fitbit_id)
    url = f"https://api.fitbit.com/1/user/-/activities/{log_id}.tcx"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers)
    return response


@fitbit_token_refresh_decorator
def get_fitbit_activity_log(
    timedelta: int = 7,
    limit: int = 5,
    offset: int = 0,
    sort: str = "desc",
    *,
    fitbit_id: str,
) -> Response:
    """Submit an API request for the a list of Fitbit activities for a user.
    This request will look for activities that occur BEFORE the provided date.

    Parameters
    ----------
    fitbit_id : str
        The Fitbit Id for the user related to this request.
    timedelta : int, optional
        Indicates the value for the beforeDate parameter as a difference in days from the current date, by default 7
    limit : int, optional
        Limits the number of activities returned (maximum allowed value of 100), by default 5
    offset : int, optional
        Used for pagination of results, by default 0
    sort : str, optional
        Indicating the sorted order of the results (by timestamp).
        Use "desc" for descending order or "asc" for ascending order., by default "desc"

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_fitbit_access_token(fitbit_id)
    url = f"https://api.fitbit.com/1/user/-/activities/list.json"
    params = {
        "beforeDate": (
            datetime.date.today() + datetime.timedelta(days=timedelta)
        ).isoformat(),
        "limit": limit,
        "offset": offset,
        "sort": sort,
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers, params=params)
    return response


@fitbit_token_refresh_decorator
def get_fitbit_most_recent_activity(*, fitbit_id: str) -> Response:
    """Submit an API request for the information related to a users most recent activity.

    Parameters
    ----------
    fitbit_id : str
        The Fitbit Id for the user related to this request.

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_fitbit_access_token(fitbit_id)
    url = f"https://api.fitbit.com/1/user/-/activities/list.json"
    params = {
        "beforeDate": (
            datetime.date.today() + datetime.timedelta(days=5)
        ).isoformat(),  # NOTE: Using a date that is after today in order to make sure we are provided the most recent activity.
        "limit": 1,
        "offset": 0,
        "sort": "desc",
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers, params=params)
    return response


@fitbit_token_refresh_decorator
def get_fitbit_activities_after_date(
    after_date, limit: int = 100, offset: int = 0, *, fitbit_id: str
) -> Response:
    """Submit an API request for the users activities after a specified date.
    The activities are returned sorted by date in ascending order.

    Parameters
    ----------
    after_date : str
        Must be a string in yyyy-MM-dd or yyyy-MM-ddTHH:mm:ss format.  The yyyy-MM-dd portion is required, however the timestamp version
        can be used to filter results using finer granularity.
    fitbit_id : str
        The Fitbit Id for the user related to this request.
    limit : int, optional
        The number of activities returned (max value: 100), by default 100
    offset : int, optional
        Used for pagination adjustments, by default 0

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_fitbit_access_token(fitbit_id)
    url = f"https://api.fitbit.com/1/user/-/activities/list.json"
    params = {
        "afterDate": after_date,
        "limit": limit,
        "offset": offset,
        "sort": "asc",
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers, params=params)
    return response


def fitbit_validate_signature(request: Request) -> bool:
    """Follow the verification best practices as outlined in https://dev.fitbit.com/build/reference/web-api/developer-guide/best-practices/#Subscriber-Security

    Checks the headers of the request to confirm the request originated from Fitbit.

    Parameters
    ----------
    request : Request
        An HTTP request sent to the server.

    Returns
    -------
    bool
        Indicates if the request has appropriately signed headers to indicate it originated from Fitbit.
    """
    body = request.data
    value = base64.b64encode(
        hmac.digest(
            f"{os.getenv('FITBIT_CLIENT_SECRET')}&".encode(), body, hashlib.sha1
        )
    ).decode()
    signature = request.headers.get("X-Fitbit-Signature", None)

    return value == signature


@fitbit_token_refresh_decorator
def fitbit_webhook_subscribe(
    subscriber_id: int | str, collection: str = "activities", *, fitbit_id: str
) -> Response:
    """Submit an API request to register a webhook subscription for a user / collection to the subscriber
     endpoint specified by the provided `subscriber_id` as determined by the application configuration.

     See https://dev.fitbit.com/build/reference/web-api/developer-guide/using-subscriptions/#Subscribers for more details.

    Parameters
    ----------
    subscriber_id : int | str
        An id associated with the application's subscription endpoint.
    fitbit_id : str
        The Fitbit Id for the user related to this request.
    collection : str, optional
        The name for the data collection(s) that should be sent to this endpoint, by default "activities"

    Returns
    -------
    Response
        The HTTP response from the API.
    """
    access_token = get_fitbit_access_token(fitbit_id)
    url = f"https://api.fitbit.com/1/user/-/{collection}/apiSubscriptions/{subscriber_id}.json"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.post(url=url, headers=headers)
    return response
