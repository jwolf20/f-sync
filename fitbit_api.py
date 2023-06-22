import base64
import datetime
import hashlib
import hmac
import json
import requests

# TODO: Change app values to use environment variables.
with open("./fitbit_app_config.json") as fitbit_app_file:
    FITBIT_APP_CONFIG = json.load(fitbit_app_file)


# TODO: Update token storage to use a database.
def load_fitbit_tokens(filepath="./fitbit_tokens.json"):
    with open(filepath) as fitbit_token_file:
        tokens = json.load(fitbit_token_file)
    return tokens


FITBIT_TOKENS = load_fitbit_tokens()


def fitbit_refresh_tokens():
    global FITBIT_TOKENS
    basic_token = base64.urlsafe_b64encode(
        f"{FITBIT_APP_CONFIG['client_id']}:{FITBIT_APP_CONFIG['client_secret']}".encode()
    ).decode()
    headers = {
        "Authorization": f"Basic {basic_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    params = {
        "grant_type": "refresh_token",
        "client_id": FITBIT_APP_CONFIG["client_id"],
        "refresh_token": FITBIT_TOKENS["refresh_token"],
    }

    response = requests.post(
        url="https://api.fitbit.com/oauth2/token", params=params, headers=headers
    )

    # Store the new tokens
    if response.status_code == 200:
        # TODO: remove hardcoded filepath
        with open("./fitbit_tokens.json", "w") as fitbit_token_file:
            json.dump(response.json(), fitbit_token_file)

        # Refresh the tokens object
        FITBIT_TOKENS = load_fitbit_tokens()

    else:
        print(response.status_code)
        print(response.json())
        raise requests.exceptions.HTTPError(response)


def fitbit_token_refresh_decorator(api_call):
    def refresh_api_call(*args, **kwargs):
        response = api_call(*args, **kwargs)

        # Check if tokens need to be refreshed
        if response.status_code == 401:
            fitbit_refresh_tokens()

            # Resubmit the response
            response = api_call(*args, **kwargs)

        return response

    return refresh_api_call


@fitbit_token_refresh_decorator
def get_fitbit_profile():
    url = "https://api.fitbit.com/1/user/-/profile.json"
    headers = {"Authorization": f"Bearer {FITBIT_TOKENS['access_token']}"}
    response = requests.get(url=url, headers=headers)
    return response


@fitbit_token_refresh_decorator
def get_fitbit_activity_tcx(log_id):
    url = f"https://api.fitbit.com/1/user/{FITBIT_TOKENS['user_id']}/activities/{log_id}.tcx"
    headers = {"Authorization": f"Bearer {FITBIT_TOKENS['access_token']}"}
    response = requests.get(url=url, headers=headers)
    return response


@fitbit_token_refresh_decorator
def get_fitbit_activity_log(timedelta=7, limit=5, offset=0, sort="desc"):
    url = (
        f"https://api.fitbit.com/1/user/{FITBIT_TOKENS['user_id']}/activities/list.json"
    )
    params = {
        "beforeDate": (
            datetime.date.today() + datetime.timedelta(days=timedelta)
        ).isoformat(),
        "limit": limit,
        "offset": offset,
        "sort": sort,
    }
    headers = {"Authorization": f"Bearer {FITBIT_TOKENS['access_token']}"}
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
    key = f"{FITBIT_APP_CONFIG['client_secret']}&"
    value = base64.b64encode(hmac.digest(key.encode(), body, hashlib.sha1)).decode()
    signature = request.headers.get("X-Fitbit-Signature", None)

    return value == signature


@fitbit_token_refresh_decorator
def fitbit_create_subscription(subscriber_id, collection="activities"):
    url = f"https://api.fitbit.com/1/user/{FITBIT_TOKENS['user_id']}/{collection}/apiSubscriptions/{subscriber_id}.json"
    headers = {"Authorization": f"Bearer {FITBIT_TOKENS['access_token']}"}
    response = requests.post(url=url, headers=headers)
    return response
