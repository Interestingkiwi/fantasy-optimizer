"""
Handles Yahoo OAuth2 authentication for the application.
"""
import os
import json
from urllib.parse import urlencode
from flask import Blueprint, request, redirect, session, jsonify, url_for
from yahoo_oauth import OAuth2
from . import config

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

def get_oauth_client(token=None, token_secret=None):
    """Creates an OAuth2 client instance."""
    redirect_uri = url_for('auth.callback', _external=True)

    if '127.0.0.1' not in redirect_uri and 'localhost' not in redirect_uri:
        redirect_uri = redirect_uri.replace('http://', 'https://')

    # This function is now simplified, as the initial login doesn't create an oauth object first.
    # It's used for the callback and subsequent API calls.
    return OAuth2(None, None, from_file=config.YAHOO_CREDENTIALS_FILE,
                  token={'access_token': token, 'token_secret': token_secret} if token else None,
                  redirect_uri=redirect_uri)

@auth_bp.route('/login')
def login():
    """
    Initiates the Yahoo login process by manually constructing the authorization
    URL and redirecting the user to Yahoo's auth page. This avoids the library's
    interactive command-line prompt.
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
            redirect_uri = redirect_uri.replace('http://', 'https://')

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
    Handles the callback from Yahoo after user authorization.
    """
    oauth = get_oauth_client()
    try:
        oauth.get_token(request.args.get('code'))
        session['yahoo_token'] = oauth.access_token
        session['yahoo_token_secret'] = oauth.token_secret
        session.permanent = True
        print("Successfully stored tokens in session.")
    except Exception as e:
        print(f"Error getting token from callback: {e}")
        return "Authentication failed. Please try again.", 400

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
