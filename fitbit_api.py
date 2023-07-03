import base64
import datetime
import hashlib
import hmac
import os
import requests

from database_utils import get_db_connection


def get_fitbit_access_token(fitbit_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fitbit_access_token FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            access_token = cur.fetchone()[0]
    return access_token


def get_fitbit_refresh_token(fitbit_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fitbit_refresh_token FROM user_tokens WHERE fitbit_id = %s",
                (fitbit_id,),
            )
            refresh_token = cur.fetchone()[0]
    return refresh_token


def update_fitbit_tokens(token_data, fitbit_id):
    new_access_token = token_data["access_token"]
    new_refresh_token = token_data["refresh_token"]
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_tokens SET fitbit_access_token = %s, fitbit_refresh_token = %s, fitbit_data_refreshed = CURRENT_TIMESTAMP WHERE fitbit_id = %s",
                (new_access_token, new_refresh_token, fitbit_id),
            )
        conn.commit()


def fitbit_refresh_tokens(fitbit_id):
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
        # TODO: remove hardcoded filepath
        update_fitbit_tokens(response.json(), fitbit_id)

    else:
        print(response.status_code)
        print(response.json())
        raise requests.exceptions.HTTPError(response)


def fitbit_token_refresh_decorator(api_call):
    def refresh_api_call(*args, **kwargs):
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
def get_fitbit_profile(*, fitbit_id):
    access_token = get_fitbit_access_token(fitbit_id)
    url = "https://api.fitbit.com/1/user/-/profile.json"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers)
    return response


@fitbit_token_refresh_decorator
def get_fitbit_activity_tcx(log_id, *, fitbit_id):
    access_token = get_fitbit_access_token(fitbit_id)
    url = f"https://api.fitbit.com/1/user/-/activities/{log_id}.tcx"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url=url, headers=headers)
    return response


@fitbit_token_refresh_decorator
def get_fitbit_activity_log(timedelta=7, limit=5, offset=0, sort="desc", *, fitbit_id):
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


def fitbit_validate_signature(request):
    """Follow the verification best practices as outlined in https://dev.fitbit.com/build/reference/web-api/developer-guide/best-practices/#Subscriber-Security

    Parameters
    ----------
    request : _type_
        _description_

    Returns
    -------
    bool
        Indicates if the request should be validated or not.
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
def fitbit_create_subscription(subscriber_id, collection="activities", *, fitbit_id):
    access_token = get_fitbit_access_token(fitbit_id)
    url = f"https://api.fitbit.com/1/user/-/{collection}/apiSubscriptions/{subscriber_id}.json"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.post(url=url, headers=headers)
    return response
