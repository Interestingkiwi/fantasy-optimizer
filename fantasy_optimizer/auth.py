"""
Handles Yahoo OAuth2 authentication for the application.
"""
import os
import json
import time
from urllib.parse import urlencode
import requests
from requests.auth import HTTPBasicAuth
from flask import Blueprint, request, redirect, session, jsonify, url_for
from yahoo_oauth import OAuth2
from . import config

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Location for the cached refresh token
TOKEN_CACHE_FILE = 'token_cache.json'

# --- Token Cache Helper Functions ---

def save_token_to_cache(token_data):
    """
    Saves the refresh token to a local file for persistent login.
    NOTE: In a production environment, this file should be encrypted or stored securely.
    """
    if 'refresh_token' in token_data:
        try:
            with open(TOKEN_CACHE_FILE, 'w') as f:
                json.dump({'refresh_token': token_data['refresh_token']}, f)
            print("Successfully cached refresh token.")
        except IOError as e:
            print(f"Error saving token cache: {e}")

def load_token_from_cache():
    """Loads a refresh token from the cache file if it exists."""
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, 'r') as f:
                # FIX: Pass the file object 'f' to json.load()
                # This ensures we read the content of the opened file.
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            print(f"Error loading or parsing token cache: {e}")
            # If the file is empty or corrupt, remove it to prevent login loops.
            delete_token_cache()
    return None

def delete_token_cache():
    """Deletes the token cache file to log the user out permanently."""
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            os.remove(TOKEN_CACHE_FILE)
            print("Token cache deleted.")
        except OSError as e:
            print(f"Error deleting token cache file: {e}")

# --- OAuth Client ---

def get_oauth_client(token_data=None):
    """Creates an OAuth2 client instance, used for making API calls after authentication."""
    redirect_uri = url_for('auth.callback', _external=True)

    if '127.0.0.1' not in redirect_uri and 'localhost' not in redirect_uri:
        redirect_uri = redirect_uri.replace('http://', 'https')

    if token_data:
        return OAuth2(None, None, from_file=config.YAHOO_CREDENTIALS_FILE,
                      redirect_uri=redirect_uri, **token_data)

    return OAuth2(None, None, from_file=config.YAHOO_CREDENTIALS_FILE, redirect_uri=redirect_uri)


@auth_bp.route('/login')
def login():
    """
    Initiates the Yahoo login process.
    First, it tries to auto-login using a cached refresh token. If that fails
    or doesn't exist, it proceeds with the standard manual login flow.
    """
    session['remember_me'] = request.args.get('remember', 'false').lower() == 'true'

    # Attempt to log in from the cached token first
    cached_token = load_token_from_cache()
    if cached_token and 'refresh_token' in cached_token:
        print("Found cached refresh token. Attempting to auto-login...")
        try:
            oauth = get_oauth_client({'refresh_token': cached_token['refresh_token']})
            oauth.refresh_access_token()

            token_data = oauth.token_data
            token_data['token_time'] = time.time()
            session['yahoo_token_data'] = token_data
            session.permanent = True  # Keep session alive for the browser session
            print("Successfully refreshed token and logged in from cache.")
            return redirect(url_for('api.index'))
        except Exception as e:
            print(f"Failed to refresh from cached token: {e}. Deleting cache and proceeding to manual login.")
            delete_token_cache()  # The cached token is likely invalid

    # If no valid cache, proceed with standard login
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
    Handles the callback from Yahoo. Exchanges the code for tokens and caches
    the refresh token if the user selected 'Remember Me'.
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

        token_data['token_time'] = time.time()
        session['yahoo_token_data'] = token_data
        session.permanent = True
        print("Successfully stored full token data in session.")

        # If user checked 'Remember Me', save the refresh token to the file cache
        if session.get('remember_me', False):
            save_token_to_cache(token_data)

        # Clean up the 'remember_me' flag from the session as it's no longer needed
        session.pop('remember_me', None)

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
    if 'yahoo_token_data' in session:
        return jsonify({'logged_in': True})
    return jsonify({'logged_in': False})

@auth_bp.route('/logout')
def logout():
    """
    Logs the user out by clearing their session and the token cache.
    """
    session.clear()
    delete_token_cache()
    return jsonify({'status': 'logged_out'})
