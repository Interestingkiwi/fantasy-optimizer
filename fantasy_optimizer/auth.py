"""
Handles Yahoo OAuth2 authentication for the application.
"""
import os
import json
from urllib.parse import urlencode
import requests
from requests.auth import HTTPBasicAuth
from flask import Blueprint, request, redirect, session, jsonify, url_for
from yahoo_oauth import OAuth2
from . import config

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

def get_oauth_client(token=None, token_secret=None):
    """Creates an OAuth2 client instance, used for making API calls after authentication."""
    redirect_uri = url_for('auth.callback', _external=True)

    if '127.0.0.1' not in redirect_uri and 'localhost' not in redirect_uri:
        redirect_uri = redirect_uri.replace('http://', 'https')

    # The library expects 'refresh_token' in its token dictionary for refreshing.
    # It confusingly uses 'token_secret' as the variable name for this in OAuth2.
    token_dict = {
        'access_token': token,
        'refresh_token': token_secret,
        'token_type': 'bearer'
    } if token else None

    # Pass the full token dict, allowing the library to refresh correctly later.
    return OAuth2(None, None, from_file=config.YAHOO_CREDENTIALS_FILE,
                  token=token_dict,
                  redirect_uri=redirect_uri)

@auth_bp.route('/login')
def login():
    """
    Initiates the Yahoo login process by manually constructing the authorization
    URL and redirecting the user to Yahoo's auth page.
    """
    if not os.path.exists(config.YAHOO_CREDENTIALS_FILE):
        return "Error: Yahoo credentials file (private.json) not found on server.", 500

    try:
        with open(config.YAHOO_CREDENTIALS_FILE) as f:
            creds = json.load(f)

        consumer_key = creds.get('consumer_key')
        if not consumer_key:
            return "Error: Consumer key not found in private.json.", 500

        redirect_uri = url_for('auth.callback', _external=True)
        if '127.0.0.1' not in redirect_uri and 'localhost' not in redirect_uri:
            redirect_uri = redirect_uri.replace('http://', 'https')

        params = {
            'client_id': consumer_key,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'language': 'en-us'
        }

        auth_url = f"https://api.login.yahoo.com/oauth2/request_auth?{urlencode(params)}"

        return redirect(auth_url)

    except json.JSONDecodeError as e:
        error_msg = f"Error parsing private.json: {e}. Please ensure it is valid JSON."
        print(error_msg)
        return error_msg, 500
    except Exception as e:
        print(f"Error during login initiation: {e}")
        return "Failed to start login process. Check server logs.", 500

@auth_bp.route('/callback')
def callback():
    """
    Handles the callback from Yahoo. This function now manually handles the token
    exchange using the 'requests' library to avoid library issues.
    """
    code = request.args.get('code')
    if not code:
        return "Authorization code not found in callback.", 400

    try:
        redirect_uri = url_for('auth.callback', _external=True)
        if '127.0.0.1' not in redirect_uri and 'localhost' not in redirect_uri:
            redirect_uri = redirect_uri.replace('http://', 'https')

        with open(config.YAHOO_CREDENTIALS_FILE) as f:
            creds = json.load(f)

        consumer_key = creds.get('consumer_key')
        consumer_secret = creds.get('consumer_secret')

        token_url = 'https://api.login.yahoo.com/oauth2/get_token'
        payload = {
            'client_id': consumer_key,
            'client_secret': consumer_secret,
            'redirect_uri': redirect_uri,
            'code': code,
            'grant_type': 'authorization_code'
        }

        auth = HTTPBasicAuth(consumer_key, consumer_secret)

        response = requests.post(token_url, data=payload, auth=auth)
        response.raise_for_status()

        token_data = response.json()

        if 'access_token' not in token_data or 'refresh_token' not in token_data:
            print(f"Error: Token data incomplete. Response: {token_data}")
            return "Failed to retrieve complete tokens from Yahoo.", 500

        session['yahoo_token'] = token_data['access_token']
        session['yahoo_token_secret'] = token_data['refresh_token']
        session.permanent = True
        print("Successfully stored tokens in session via manual exchange.")

    except requests.exceptions.RequestException as e:
        print(f"Error during manual token exchange: {e.response.text if e.response else e}")
        return "Authentication failed: Could not exchange code for token.", 400
    except Exception as e:
        print(f"Error in callback: {e}")
        return "Authentication failed due to an unexpected server error.", 500

    return redirect(url_for('api.index'))

@auth_bp.route('/status')
def status():
    """
    Checks if the current user has valid Yahoo tokens in their session.
    """
    if 'yahoo_token' in session and 'yahoo_token_secret' in session:
        return jsonify({'logged_in': True})
    return jsonify({'logged_in': False})

@auth_bp.route('/logout')
def logout():
    """
    Logs the user out by clearing their session.
    """
    session.clear()
    return jsonify({'status': 'logged_out'})
