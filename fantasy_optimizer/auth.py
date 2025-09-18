"""
Handles Yahoo OAuth2 authentication for the application.
"""
import os
import json
from flask import Blueprint, request, redirect, session, jsonify, url_for
from yahoo_oauth import OAuth2
from . import config

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

def get_oauth_client(token=None, token_secret=None, consumer_key=None, consumer_secret=None):
    """Creates an OAuth2 client instance."""
    redirect_uri = url_for('auth.callback', _external=True)

    if '127.0.0.1' not in redirect_uri and 'localhost' not in redirect_uri:
        redirect_uri = redirect_uri.replace('http://', 'https://')

    if token and token_secret:
        # Used for authenticated API calls with tokens from the session
        return OAuth2(None, None, from_file=config.YAHOO_CREDENTIALS_FILE,
                      token={'access_token': token, 'token_secret': token_secret},
                      redirect_uri=redirect_uri)
    elif consumer_key and consumer_secret:
        # Used for initiating a new login, bypassing stored tokens in the file
        return OAuth2(consumer_key, consumer_secret, redirect_uri=redirect_uri)
    else:
        # Used for the callback
        return OAuth2(None, None, from_file=config.YAHOO_CREDENTIALS_FILE,
                      redirect_uri=redirect_uri)

@auth_bp.route('/login')
def login():
    """
    Initiates the Yahoo login process by redirecting the user to Yahoo's auth page.
    """
    if not os.path.exists(config.YAHOO_CREDENTIALS_FILE):
        return "Error: Yahoo credentials file (private.json) not found on server.", 500

    try:
        # Manually load credentials to prevent the library from auto-refreshing stale tokens
        with open(config.YAHOO_CREDENTIALS_FILE) as f:
            creds = json.load(f)

        consumer_key = creds.get('consumer_key')
        consumer_secret = creds.get('consumer_secret')

        if not consumer_key or not consumer_secret:
            return "Error: Consumer key or secret missing from credentials file.", 500

        oauth = get_oauth_client(consumer_key=consumer_key, consumer_secret=consumer_secret)
        return redirect(oauth.get_authorization_url())
    except json.JSONDecodeError as e:
        error_msg = f"Error parsing private.json: {e}. Please ensure it is valid JSON (e.g., keys and string values are in double quotes)."
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
        # Store the specific token components securely in the user's session
        session['yahoo_token'] = oauth.access_token
        session['yahoo_token_secret'] = oauth.token_secret
        session.permanent = True # Make the session last longer
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
        # We just check for presence; token validity is checked on each API call.
        return jsonify({'logged_in': True})

    return jsonify({'logged_in': False})

@auth_bp.route('/logout')
def logout():
    """
    Logs the user out by clearing their session.
    """
    session.clear()
    return jsonify({'status': 'logged_out'})
