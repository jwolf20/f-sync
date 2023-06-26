import json
import requests

# TODO: Change app values to use environment variables.
with open("./strava_app_config.json") as strava_app_file:
    STRAVA_APP_CONFIG = json.load(strava_app_file)


def load_strava_tokens(filepath="./strava_tokens.json"):
    with open(filepath) as strava_tokens_file:
        tokens = json.load(strava_tokens_file)
    return tokens


STRAVA_TOKENS = load_strava_tokens()


def strava_refresh_tokens():
    global STRAVA_TOKENS
    params = {
        "grant_type": "refresh_token",
        "client_id": STRAVA_APP_CONFIG["client_id"],
        "client_secret": STRAVA_APP_CONFIG["client_secret"],
        "refresh_token": STRAVA_TOKENS["refresh_token"],
    }

    response = requests.post(
        url="https://www.strava.com/api/v3/oauth/token", params=params
    )

    # Store the new tokens
    if response.status_code == 200:
        # TODO: remove hardcoded filepath
        with open("./strava_tokens.json", "w") as strava_tokens_file:
            json.dump(response.json(), strava_tokens_file)

        # Refresh the tokens object
        STRAVA_TOKENS = load_strava_tokens()

    else:
        print(response.status_code)
        print(response.json())
        raise requests.exceptions.HTTPError(response)


def strava_token_refresh_decorator(api_call):
    def refresh_api_call(*args, **kwargs):
        response = api_call(*args, **kwargs)

        # Check if tokens need to be refreshed
        if response.status_code == 401:
            strava_refresh_tokens()

            # Resubmit the response
            response = api_call(*args, **kwargs)

        return response

    return refresh_api_call


@strava_token_refresh_decorator
def strava_activity_upload(file_buffer):
    file_buffer.seek(0)
    url = "https://www.strava.com/api/v3/uploads"
    headers = {"Authorization": f"Bearer {STRAVA_TOKENS['access_token']}"}
    params = {"data_type": "tcx"}
    files = {"file": file_buffer}

    response = requests.post(url=url, headers=headers, files=files, params=params)

    return response


@strava_token_refresh_decorator
def strava_check_upload_status(upload_id):
    url = f"https://www.strava.com/api/v3/uploads/{upload_id}"
    headers = {"Authorization": f"Bearer {STRAVA_TOKENS['access_token']}"}
    response = requests.get(url=url, headers=headers)

    return response


@strava_token_refresh_decorator
def strava_get_activity_list():
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {STRAVA_TOKENS['access_token']}"}
    response = requests.get(url=url, headers=headers)

    return response
